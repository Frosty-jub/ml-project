"""ตรวจการหยุด CI และการสร้างหลักฐาน โดยไม่ฝึกโมเดลซ้ำใน unit test"""
import json
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import ci_pipeline as ci


class CiPipelineTests(unittest.TestCase):
    def test_delivery_manifest_matches_files_without_git_placeholders(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            flow_out = root / 'flow'
            for relative in ('serving/app/main.py', 'src/example.py', 'src/data/.gitkeep',
                             'orchestration/airflow/requirements.lock', 'ci/runtime.Dockerfile',
                             'ci/delivery.compose.yaml', 'docs/ci_delivery_th.md',
                             'fixture/model.joblib', 'fixture/metadata.json', 'fixture/sample_request.json'):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('unit-test fixture', encoding='utf-8')
            ci.write(flow_out / 'bundles.json', {
                role: {'bundle_dir': str(root / 'fixture')} for role in ('candidate', 'fallback')})
            ci.write(flow_out / 'quality_gate.json', {'passed': True})
            ci.write(flow_out / 'approval.json', {'approved': True})
            with patch.object(ci, 'ROOT', root), patch.object(ci, 'FLOW_OUT', flow_out), \
                    patch.object(ci, 'SCENARIO', 'normal'):
                ci.package()
            delivery = root / 'delivery'
            checksums = ci.read(delivery / 'checksums.json')
            self.assertFalse(list(delivery.rglob('.gitkeep')))
            for name, expected in checksums.items():
                self.assertEqual(hashlib.sha256((delivery / name).read_bytes()).hexdigest(), expected)

    def test_failed_previous_stage_blocks_next_stage(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            ci.write(out / 'code.json', {'status': 'failed'})
            with patch.object(ci, 'OUT', out), patch.object(ci, 'data') as data, \
                    patch('sys.argv', ['ci_pipeline.py', 'data']), \
                    patch('builtins.print'), patch('traceback.print_exc'):
                with self.assertRaises(SystemExit) as result:
                    ci.main()
                self.assertEqual(result.exception.code, 1)
                data.assert_not_called()
            self.assertEqual(ci.read(out / 'data.json')['status'], 'failed')

    def test_failure_fixture_cannot_be_packaged(self):
        with patch.object(ci, 'SCENARIO', 'bad_model'):
            with self.assertRaisesRegex(ValueError, 'ห้ามสร้างชุดส่งมอบ'):
                ci.package()

    def test_missing_stages_never_report_delivery_allowed(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            with patch.object(ci, 'OUT', out), patch.object(ci, 'FLOW_OUT', out / 'absent'):
                ci.report()
            summary = json.loads((out / 'summary.json').read_text(encoding='utf-8'))
            self.assertFalse(summary['passed'])
            self.assertFalse(summary['delivery_allowed'])

    def test_all_stages_required_for_delivery(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            for stage in ci.STAGES:
                ci.write(out / (stage + '.json'), {'status': 'success'})
            with patch.object(ci, 'OUT', out), patch.object(ci, 'FLOW_OUT', out / 'absent'), \
                    patch.object(ci, 'SCENARIO', 'normal'):
                ci.report()
            self.assertTrue(ci.read(out / 'summary.json')['delivery_allowed'])


if __name__ == '__main__':
    unittest.main()
