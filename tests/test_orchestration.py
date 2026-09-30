"""Safety properties at the model deployment and event reconciliation boundaries."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from fastapi.testclient import TestClient
from sklearn.linear_model import LinearRegression
from sklearn.pipeline import Pipeline

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'serving'))
from app.main import create_app
from app.selector import BundleSelector
from serving.scripts.export_model import export_bundle
from orchestration.airflow.run_stage import Flow, read, write, reconcile_events, compatible_environment


class EnvironmentTests(unittest.TestCase):
    def test_missing_environment_cannot_reuse_version(self):
        self.assertFalse(compatible_environment({}, {'scikit-learn': '1.7.2'}))

    def test_different_environment_cannot_reuse_version(self):
        self.assertFalse(compatible_environment({'runtime_scikit-learn': '1.9.1'}, {'scikit-learn': '1.7.2'}))

    def test_matching_environment_can_reuse_version(self):
        self.assertTrue(compatible_environment({'runtime_scikit-learn': '1.7.2'}, {'scikit-learn': '1.7.2'}))


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.pointer = self.root / 'production.json'
        self.bundles = self.root / 'bundles'
        X = pd.DataFrame({'x': [1., 2., 3.]})
        self.info = []
        for version in ('1', '2'):
            target = self.bundles / ('v' + version)
            model = Pipeline([('regressor', LinearRegression())]).fit(X, X['x'] * int(version))
            export_bundle(model, X, [{'name': 'x', 'type': 'number'}], target, 'test-model', version)
            manifest = read(target / 'metadata.json')
            self.info.append({'bundle_dir': str(target), 'model_name': 'test-model', 'model_version': version,
                              'model_sha256': manifest['model_sha256']})

    def tearDown(self):
        self.temp.cleanup()

    def test_switch_and_rollback_report_actual_loaded_version(self):
        with patch.dict(os.environ, {'MODEL_POINTER': str(self.pointer), 'BUNDLE_ROOT': str(self.bundles)}):
            with TestClient(create_app()) as client:
                self.assertEqual(client.get('/health').status_code, 503)
                for info in (self.info[0], self.info[1], self.info[0]):
                    write(self.pointer, info)
                    health = client.get('/health').json()
                    self.assertEqual(health['model_version'], info['model_version'])
                    predicted = client.post('/predict', json={'records': [{'x': 2.}]}).json()
                    self.assertEqual(predicted['model_version'], info['model_version'])
                    self.assertAlmostEqual(predicted['predictions'][0], 2 * int(info['model_version']))

    def test_invalid_pointer_fails_closed_then_recovers(self):
        selector = BundleSelector(self.pointer, self.bundles)
        write(self.pointer, self.info[0])
        previous = selector.get()
        write(self.pointer, {**self.info[1], 'model_sha256': '0' * 64})
        with self.assertRaises(ValueError):
            selector.get()
        self.assertEqual(previous.manifest.model_version, '1')
        write(self.pointer, self.info[0])
        self.assertEqual(selector.get().manifest.model_version, '1')

    def test_path_escape_rejected(self):
        write(self.pointer, {**self.info[0], 'bundle_dir': str(self.root)})
        with self.assertRaisesRegex(ValueError, 'BUNDLE_ROOT'):
            BundleSelector(self.pointer, self.bundles).get()

    def test_candidate_mismatch_cannot_promote(self):
        flow = object.__new__(Flow)
        flow.out = self.root / 'run'
        write(flow.out / 'bundles.json', {'candidate': {'source_model_sha256': 'changed'}, 'fallback': {}})
        write(flow.out / 'quality_gate.json', {'model_sha256': 'original'})
        with patch('src.demand_forecasting.registry.promote') as promote:
            with self.assertRaisesRegex(ValueError, 'Candidate changed'):
                flow.approve_and_deploy()
            promote.assert_not_called()


class EventTests(unittest.TestCase):
    def setUp(self):
        self.receipts = [{'request_id': 'ours', 'predictions': [2.0], 'model_name': 'm', 'model_version': '1'}]
        self.event = {'request_id': 'ours', 'row_index': 0, 'prediction': 2., 'features': {'x': 1.},
                      'model_name': 'm', 'model_version': '1'}

    def test_unrelated_traffic_does_not_satisfy_missing_receipt(self):
        with self.assertRaises(ValueError):
            reconcile_events(self.receipts, [{**self.event, 'request_id': 'someone-else'}], [{'x': 1.}])

    def test_duplicate_event_rejected(self):
        with self.assertRaises(ValueError):
            reconcile_events(self.receipts, [self.event, self.event], [{'x': 1.}])

    def test_wrong_prediction_rejected(self):
        with self.assertRaises(ValueError):
            reconcile_events(self.receipts, [{**self.event, 'prediction': 99.}], [{'x': 1.}])

    def test_exact_receipt_matches(self):
        result = reconcile_events(self.receipts, [self.event], [{'x': 1.}])
        self.assertEqual(result, {'expected': 1, 'matched_once': 1})


if __name__ == '__main__':
    unittest.main()
