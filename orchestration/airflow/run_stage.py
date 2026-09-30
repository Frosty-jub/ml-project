"""Project interpreter entry point for auditable Airflow tasks (no Airflow imports)."""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import time
import traceback
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(os.environ.get('AIRFLOW_PROJECT_ROOT', Path(__file__).resolve().parents[2]))
STORE = ROOT / 'artifacts/orchestration'
CANDIDATE_URL = os.environ.get('CANDIDATE_URL', 'http://candidate:8000')
PRODUCTION_URL = os.environ.get('PRODUCTION_URL', 'http://production:8000')


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    temp.replace(path)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def compatible_environment(tags, versions):
    return all(tags.get('runtime_' + name) == version for name, version in versions.items())


def reconcile_events(receipts, events, records):
    wanted = {(r['request_id'], i): (r, value) for r in receipts for i, value in enumerate(r['predictions'])}
    require(len(wanted) == sum(len(r['predictions']) for r in receipts), 'Duplicate receipt keys')
    counts = Counter()
    for event in events:
        key = (event['request_id'], event['row_index'])
        if key not in wanted:
            continue
        receipt, value = wanted[key]
        require(event['features'] == records[event['row_index']] and abs(event['prediction'] - value) < 1e-5
                and event['model_name'] == receipt['model_name']
                and str(event['model_version']) == str(receipt['model_version']), 'Observation content mismatch')
        counts[key] += 1
    require(set(counts) == set(wanted) and all(v == 1 for v in counts.values()), 'Missing/duplicate observation events')
    return {'expected': len(wanted), 'matched_once': len(counts)}


class Flow:
    def __init__(self, run_id, scenario='normal'):
        self.run_id = run_id
        self.key = re.sub(r'[^A-Za-z0-9_.-]', '_', run_id)
        self.work = STORE / 'runs' / self.key / 'project'
        self.out = ROOT / 'reports/orchestration' / self.key
        self.out.mkdir(parents=True, exist_ok=True)
        self.scenario = scenario
        os.environ['MLFLOW_TRACKING_URI'] = 'sqlite:///' + str(STORE / 'registry/mlflow.db')
        (STORE / 'registry').mkdir(parents=True, exist_ok=True)

    def command(self, *args):
        print('COMMAND:', subprocess.list2cmdline([sys.executable, *map(str, args)]), flush=True)
        subprocess.run([sys.executable, *map(str, args)], cwd=self.work, check=True)

    def initialize(self):
        require(not self.work.exists(), 'Run workspace already exists; trigger a new run ID')
        self.work.mkdir(parents=True)
        for name in ('src', 'scripts', 'config', 'serving', 'orchestration'):
            shutil.copytree(ROOT / name, self.work / name,
                            ignore=shutil.ignore_patterns('__pycache__', 'artifacts', 'reports', '.venv'))
        # Each run starts with code only: no prior dataset, trained model, or bundle.
        files = {str(p.relative_to(self.work)): digest(p) for p in self.work.rglob('*') if p.is_file()}
        write(self.work / 'source_revision.json', {
            'commit': os.environ.get('PROJECT_GIT_COMMIT') or None,
            'branch': 'airflow-code-snapshot',
            'working_tree_dirty': os.environ.get('PROJECT_GIT_DIRTY', 'unknown'),
            'snapshot_sha256': hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest(),
            'source': 'immutable_content_snapshot',
        })
        freeze = subprocess.check_output([sys.executable, '-m', 'pip', 'freeze'], text=True)
        (self.out / 'environment.txt').write_text(freeze, encoding='utf-8')
        import sklearn
        require(Path(sklearn.__file__).resolve().is_relative_to(Path(sys.prefix).resolve()),
                'Airflow packages leaked into the project interpreter')
        write(self.out / 'interpreter.json', {'executable': sys.executable, 'prefix': sys.prefix,
              'sklearn_version': sklearn.__version__, 'sklearn_path': sklearn.__file__})
        before = read(STORE / 'production.json') if (STORE / 'production.json').exists() else None
        fixture = None
        if self.scenario != 'normal':
            fixture_info = read(STORE / 'last_successful_workspace.json')
            fixture = Path(fixture_info['workspace']).resolve()
            require(fixture.is_relative_to((STORE / 'runs').resolve()), 'Invalid failure-test fixture path')
            shutil.copytree(fixture / 'data', self.work / 'data')
            if self.scenario == 'bad_quality':
                shutil.copytree(fixture / 'artifacts/training', self.work / 'artifacts/training')
                shutil.copytree(fixture / 'reports/generated', self.work / 'reports/generated')
        write(self.out / 'lineage.json', {'run_id': self.run_id, 'scenario': self.scenario,
              'created_at_utc': datetime.now(timezone.utc).isoformat(), 'code_sha256': files,
              'started_without_data_or_models': self.scenario == 'normal', 'production_before': before,
              'isolated_failure_test_fixture': str(fixture) if fixture else None})
        return {'workspace': str(self.work), 'source_files': len(files)}

    def prepare_data(self):
        if self.scenario == 'normal':
            self.command('scripts/download_data.py')
            self.command('scripts/prepare_data.py')
        if self.scenario == 'bad_data':
            import pandas as pd
            path = self.work / 'data/interim/sku_daily_sales.csv.gz'
            frame = pd.read_csv(path, compression='gzip', dtype={'sku_id': str})
            frame.loc[0, 'daily_sold_units'] = -1
            frame.to_csv(path, index=False, compression='gzip')
        self.command('scripts/validate_data.py')
        self.command('scripts/build_features.py')
        return read(self.work / 'reports/generated/validation_summary.json')

    def experiment_2(self):
        if self.scenario == 'bad_quality':
            return {'experiment': 2, 'mode': 'isolated_copy_of_successful_run_for_failure_test'}
        self.command('-m', 'src.demand_forecasting.training.experiment2')
        return {'experiment': 2}

    def experiment_3(self):
        if self.scenario == 'bad_quality':
            return {'experiment': 3, 'mode': 'isolated_copy_of_successful_run_for_failure_test'}
        self.command('-m', 'src.demand_forecasting.training.experiment3')
        return {'experiment': 3}

    def verify_full_folds(self):
        if self.scenario == 'bad_quality':
            return {'mode': 'isolated_copy_of_successful_run_for_failure_test'}
        self.command('-m', 'src.demand_forecasting.training.verify_full_folds')
        return {'full_folds_verified': True}

    def candidate_quality_gate(self):
        from src.demand_forecasting.registry import check_candidate
        if self.scenario == 'bad_quality':
            path = self.work / 'artifacts/training/final_candidate_metadata.json'
            metadata = read(path)
            metadata['aggregate_metrics']['MAE'] = metadata['baseline_metrics']['MAE'] * 2
            write(path, metadata)
        gate, _, _ = check_candidate()
        write(self.out / 'quality_gate.json', gate)
        require(gate['passed'], 'Candidate quality gate rejected: ' + str(gate['checks']))
        return gate

    def register_models(self):
        from importlib.metadata import version as package_version
        import joblib
        import mlflow
        import mlflow.sklearn
        import pandas as pd
        from mlflow.models import infer_signature
        from src.demand_forecasting.registry import check_candidate, evaluate_gate, canonical_sha256
        training = self.work / 'artifacts/training'
        policy = read(self.work / 'config/model_registry.json')
        name = policy['registered_model_name']
        experiment = mlflow.get_experiment_by_name(name)
        if experiment is None:
            mlflow.create_experiment(name, artifact_location=str(STORE / 'registry/artifacts'))
        mlflow.set_experiment(name)
        client = mlflow.MlflowClient()
        features = read(training / 'feature_list.json')['features']
        manifest = read(self.work / 'reports/generated/feature_split_manifest.json')
        require(features == manifest['feature_columns'], 'Training and data manifest feature order differ')
        require(not set(features).intersection({'target', 'demand_next_7d_units', 'sku_id', 'forecast_origin_date'}),
                'Forbidden feature')
        gate3, meta3, model3 = check_candidate()
        require(gate3['passed'] and gate3['model_sha256'] == read(self.out / 'quality_gate.json')['model_sha256'],
                'Candidate changed after quality gate')
        meta2 = read(training / 'experiment2_training_metadata.json')
        folds2 = read(training / 'experiment2_fold_metrics.json')
        trial = meta2['selected_trial']
        candidates = {r['fold']: r for r in folds2 if r['trial_id'] == trial}
        baselines = {r['fold']: r for r in folds2 if r['trial_id'] == 'historical_7d_sum'}
        wins = sum(candidates[f]['MAE'] < baselines[f]['MAE'] for f in candidates)
        evidence2 = {'feature_order': features, 'aggregate_metrics': {**meta2['selected_metrics'], 'folds_won_vs_baseline': wins},
                     'baseline_metrics': read(training / 'baseline_metrics.json'), 'model_name': trial,
                     'fold_date_ranges': meta2['folds'], 'test_set_used': False}
        model2 = joblib.load(training / 'best_candidate_model.joblib')
        gate2 = evaluate_gate(evidence2, folds2, model2, policy)
        gate2['validation_folds_sha256'] = canonical_sha256(meta2['folds'])
        require(gate2['passed'], 'Experiment 2 fallback did not pass quality gate')
        selected = {}
        versions = {name: package_version(name) for name in ('scikit-learn', 'lightgbm', 'numpy', 'pandas', 'joblib')}
        # Experiment 1 is a frozen reference; record its existing scores without retraining.
        reference = read(self.work / 'config/experiment1_reference.json')
        require(bool(reference.get('rows')), 'Experiment 1 reference has no score rows')
        for record in reference['rows']:
            require(all(metric in record for metric in ('model', 'MAE', 'RMSE', 'WAPE')),
                    'Experiment 1 reference row is incomplete')
            model_id = str(record['model'])
            with mlflow.start_run(run_name=f'{self.key}-exp1-reference-{model_id}'):
                mlflow.set_tags({
                    'airflow_run_id': self.run_id,
                    'experiment_number': '1',
                    'evidence_type': 'frozen_reference',
                    'validation_strategy': str(reference.get('validation_strategy', '')),
                    'reference_feature_manifest_sha256': str(reference.get('feature_manifest_sha256', '')),
                    'reference_source_workbook_sha256': str(reference.get('source_workbook_sha256', '')),
                })
                params = {'model': model_id}
                params.update({f'hyperparameter_{key}': str(value)
                               for key, value in record.get('hyperparameters', {}).items()})
                mlflow.log_params(params)
                mlflow.log_metrics({metric: float(record[metric]) for metric in ('MAE', 'RMSE', 'WAPE')})
                mlflow.log_dict(reference, 'experiment1_reference.json')
                mlflow.log_dict(record, 'trial.json')

        # Record every Experiment 2/3 trial and the current code/data/environment lineage.
        for number in (2, 3):
            for record in read(training / f'experiment{number}_trials.json'):
                with mlflow.start_run(run_name=f'{self.key}-exp{number}-{record["trial_id"]}'):
                    mlflow.set_tags({'airflow_run_id': self.run_id, 'experiment_number': str(number)})
                    mlflow.log_params({k: str(v) for k, v in record.get('parameters', {}).items()})
                    mlflow.log_metrics({k: float(record[k]) for k in ('MAE', 'RMSE', 'WAPE')})
                    mlflow.log_dict(record, 'trial.json')
                    mlflow.log_dict([r for r in read(training / f'experiment{number}_fold_metrics.json')
                                     if r['trial_id'] == record['trial_id']], 'folds.json')
                    mlflow.log_artifact(str(self.out / 'lineage.json'))
                    mlflow.log_artifact(str(self.out / 'environment.txt'))
                    mlflow.log_dict(manifest, 'data_manifest.json')
        full_rows_path = training / 'final_candidate_full_fold_metrics.json'
        full_summary_path = training / 'final_candidate_full_fold_summary.json'
        full_csv_path = training / 'final_candidate_full_fold_metrics.csv'
        require(full_rows_path.is_file() and full_summary_path.is_file() and full_csv_path.is_file(),
                'Full-fold verification outputs are missing')
        full_rows = read(full_rows_path)
        full_summary = read(full_summary_path)
        require(full_summary.get('model') == meta3.get('model_name'),
                'Full-fold verification model differs from the gated candidate')
        require(full_summary.get('selection_changed') is False and full_summary.get('test_set_used') is False,
                'Full-fold verification changed selection or used the test set')
        full_metrics = {}
        for metric, values in full_summary['aggregate'].items():
            full_metrics[f'full_fold_{metric.lower()}_mean'] = float(values['mean'])
            full_metrics[f'full_fold_{metric.lower()}_std'] = float(values['std'])
        full_metrics['folds_won_vs_baseline'] = float(full_summary['folds_won_vs_baseline'])
        full_metrics['baseline_mean_mae'] = float(full_summary['baseline_mean_MAE'])
        full_metrics['full_minus_sampled_mae'] = float(full_summary['full_minus_sampled_MAE'])
        full_metrics['mae_improvement_vs_baseline_pct'] = float(
            full_summary['MAE_improvement_vs_baseline_pct'])
        with mlflow.start_run(run_name=f'{self.key}-exp3-full-fold-verification'):
            mlflow.set_tags({
                'airflow_run_id': self.run_id,
                'experiment_number': '3',
                'verification_type': 'full_fold_robustness_check',
                'selection_changed': 'false',
                'test_set_used': 'false',
            })
            mlflow.log_params({
                'model': str(full_summary['model']),
                'fold_count': str(full_summary['fold_count']),
                'protocol': str(full_summary['protocol']),
            })
            mlflow.log_metrics(full_metrics)
            mlflow.log_dict(full_summary, 'full_fold_verification/summary.json')
            mlflow.log_dict(full_rows, 'full_fold_verification/fold_metrics.json')
            mlflow.log_artifact(str(full_csv_path), artifact_path='full_fold_verification')
            mlflow.log_artifact(str(self.out / 'lineage.json'))
            mlflow.log_artifact(str(self.out / 'environment.txt'))
            mlflow.log_dict(manifest, 'data_manifest.json')

        for role, model, path, gate, meta in (
            ('fallback', model2, training / 'best_candidate_model.joblib', gate2, meta2),
            ('candidate', model3, training / 'final_candidate_model.joblib', gate3, meta3),
        ):
            source_hash = digest(path)
            existing = [v for v in client.search_model_versions(f"name='{name}'")
                        if v.tags.get('source_model_sha256') == source_hash
                        and v.tags.get('validation_folds_sha256') == gate['validation_folds_sha256']
                        and compatible_environment(v.tags, versions)
                        and v.tags.get('gate_passed') == 'true']
            if existing:
                version = str(max(existing, key=lambda v: int(v.version)).version)
            else:
                frame = pd.DataFrame([[0.0] * len(features)], columns=features)
                with mlflow.start_run(run_name=f'{self.key}-{role}'):
                    mlflow.set_tags({'airflow_run_id': self.run_id, 'role': role})
                    mlflow.log_dict(meta, 'training_metadata.json')
                    mlflow.log_dict(gate, 'quality_gate.json')
                    mlflow.log_artifact(str(self.out / 'lineage.json'))
                    mlflow.log_artifact(str(self.out / 'environment.txt'))
                    mlflow.log_dict(manifest, 'data_manifest.json')
                    logged = mlflow.sklearn.log_model(model, name='model', registered_model_name=name,
                        signature=infer_signature(frame, model.predict(frame)), input_example=frame,
                        code_paths=[str(self.work / 'src')], serialization_format='cloudpickle')
                    version = str(logged.registered_model_version)
                for k, v in {'gate_passed': 'true', 'source_model_sha256': source_hash,
                             'validation_mae': gate['candidate_mae'], 'baseline_mae': gate['baseline_mae'],
                             'folds_won': gate['folds_won'], 'validation_folds_sha256': gate['validation_folds_sha256'],
                             'airflow_run_id': self.run_id,
                             **{'runtime_' + k: v for k, v in versions.items()}}.items():
                    client.set_model_version_tag(name, version, k, str(v))
            selected[role] = {'model_name': name, 'model_version': version, 'source_model_sha256': source_hash}
        write(self.out / 'registered.json', selected)
        return selected

    def export_bundles(self):
        import mlflow.sklearn
        import numpy as np
        import pandas as pd
        from serving.scripts.export_model import export_feature_ordered_joblib_bundle
        from app.runtime import ModelRuntime
        selected = read(self.out / 'registered.json')
        manifest = read(self.work / 'reports/generated/feature_split_manifest.json')
        features = manifest['feature_columns']
        frame = pd.read_csv(self.work / manifest['splits']['validation']['path'], nrows=64)[features]
        for info in selected.values():
            model = mlflow.sklearn.load_model(f"models:/{info['model_name']}/{info['model_version']}")
            require(list(model.feature_names) == features, 'Registry feature manifest mismatch')
            target = STORE / 'bundles' / ('v' + info['model_version'] + '-' + info['source_model_sha256'][:12])
            if not target.exists():
                temp = target.with_name(target.name + '.' + uuid.uuid4().hex)
                export_feature_ordered_joblib_bundle(model, frame, temp, info['model_name'], info['model_version'])
                meta = read(temp / 'metadata.json')
                meta['source_model_sha256'] = info['source_model_sha256']
                write(temp / 'metadata.json', meta)
                temp.rename(target)
            runtime = ModelRuntime(target)
            require(runtime.manifest.source_model_sha256 == info['source_model_sha256'], 'Bundle provenance mismatch')
            require(np.allclose(runtime.predict(frame), model.predict(frame), rtol=1e-5, atol=1e-5), 'Export parity failed')
            info.update(bundle_dir=str(target), model_sha256=digest(target / 'model.joblib'))
        write(self.out / 'bundles.json', selected)
        return selected

    def set_pointer(self, slot, info):
        write(STORE / f'{slot}.json', {**info, 'airflow_run_id': self.run_id, 'revision': uuid.uuid4().hex})

    def parity(self, url, info, prefix):
        import httpx
        import mlflow.sklearn
        import numpy as np
        import pandas as pd
        metadata = read(Path(info['bundle_dir']) / 'metadata.json')
        payload = read(Path(info['bundle_dir']) / 'sample_request.json')
        with httpx.Client(base_url=url, timeout=30, trust_env=False) as client:
            response = client.get('/health')
            response.raise_for_status()
            health = response.json()
            require(health['model_name'] == info['model_name'] and str(health['model_version']) == info['model_version']
                    and health['model_sha256'] == info['model_sha256'], 'Serving identity/checksum mismatch')
            schema_response = client.get('/schema')
            schema_response.raise_for_status()
            require(schema_response.json()['features'] == metadata['features'], 'API feature schema mismatch')
            request_id = uuid.uuid4().hex
            response = client.post('/predict', json=payload, headers={'X-Request-ID': request_id})
            response.raise_for_status()
            body = response.json()
            require(body['request_id'] == request_id and body['model_name'] == info['model_name']
                    and str(body['model_version']) == info['model_version'], 'Prediction response identity mismatch')
        names = [f['name'] for f in metadata['features']]
        source = mlflow.sklearn.load_model(f"models:/{info['model_name']}/{info['model_version']}")
        expected = np.asarray(source.predict(pd.DataFrame(payload['records'], columns=names)), dtype=float)
        actual = np.asarray(body['predictions'], dtype=float)
        require(expected.shape == actual.shape and np.isfinite(actual).all()
                and np.allclose(expected, actual, rtol=1e-5, atol=1e-5), 'Registry/API prediction parity failed')
        result = {'passed': True, 'health': health, 'request_id': request_id, 'expected': expected.tolist(),
                  'actual': actual.tolist(), 'records': payload['records']}
        write(self.out / f'{prefix}_parity.json', result)
        return result

    def benchmark_candidates(self):
        from src.demand_forecasting.registry import benchmark_version
        bundles = read(self.out / 'bundles.json')
        for role, info in bundles.items():
            self.set_pointer('candidate', info)
            self.parity(CANDIDATE_URL, info, role)
            result = benchmark_version(info['model_version'], CANDIDATE_URL)
            write(self.out / f'{role}_benchmark.json', result)
            require(result['gate']['passed'], f'{role} Registry serving gate rejected')
        info = bundles['candidate']
        self.command('serving/scripts/verify_http.py', '--url', CANDIDATE_URL,
                     '--bundle-dir', info['bundle_dir'], '--output', self.out / 'http.json')
        sample = read(Path(info['bundle_dir']) / 'sample_request.json')
        write(self.out / 'load_payload.json', {'records': [sample['records'][0]]})
        self.command('serving/scripts/load_test.py', '--url', CANDIDATE_URL, '--payload', self.out / 'load_payload.json',
                     '--slo', self.work / 'serving/slo.json', '--output', self.out / 'load_test.json',
                     '--environment', 'airflow-candidate', '--receipts', self.out / 'load_receipts.json')
        receipts = read(self.out / 'load_receipts.json')
        require(len(receipts) == 520, 'Expected 500 measured plus 20 warmup receipts')
        events = [json.loads(line) for line in (STORE / 'candidate_events.jsonl').read_text(encoding='utf-8').splitlines()]
        matched = reconcile_events(receipts, events, [sample['records'][0]])
        write(self.out / 'load_event_reconciliation.json', {**matched,
              'scope': 'All successful load-test and warmup requests by request_id + row_index'})
        return {'registry_gate_passed': True, 'http_passed': True, 'single_record_slo_passed': True}

    def approve_and_deploy(self):
        import mlflow
        from src.demand_forecasting.registry import promote
        bundles = read(self.out / 'bundles.json')
        candidate, fallback = bundles['candidate'], bundles['fallback']
        require(candidate['source_model_sha256'] == read(self.out / 'quality_gate.json')['model_sha256'],
                'Candidate changed: refusing deployment')
        require(read(self.out / 'load_test.json')['slo_passed'], 'Single-record SLO failed')
        client = mlflow.MlflowClient()
        name = candidate['model_name']
        prior = read(STORE / 'production.json') if (STORE / 'production.json').exists() else None
        # First installation gives the real Experiment 2 fallback a verified live state.
        if prior is None:
            promote(fallback['model_version'])
            self.set_pointer('production', fallback)
            self.parity(PRODUCTION_URL, fallback, 'bootstrap_fallback')
            prior = read(STORE / 'production.json')
        aliases = {k: str(v) for k, v in client.get_registered_model(name).aliases.items()}
        require(aliases.get('production') == str(prior['model_version']), 'Registry and production pointer diverged')
        write(self.out / 'deployment_before.json', {'pointer': prior, 'aliases': aliases})
        try:
            # Registry promotion enforces current serving gate, equal folds and no MAE regression.
            promote(candidate['model_version'])
            self.set_pointer('production', candidate)
            self.parity(PRODUCTION_URL, candidate, 'deployed')
        except Exception:
            self.set_pointer('production', prior)
            self.restore_aliases(client, name, aliases)
            self.parity(PRODUCTION_URL, prior, 'deployment_recovered')
            raise
        result = {'approved': True, 'approval_mode': 'existing_quality_and_serving_policy_for_local_demo',
                  'team_document_signoff': 'pending', 'model': candidate,
                  'policy_sha256': digest(self.work / 'config/model_registry.json'),
                  'slo_sha256': digest(self.work / 'serving/slo.json'), 'production_url': PRODUCTION_URL}
        write(self.out / 'approval.json', result)
        return result

    @staticmethod
    def restore_aliases(client, name, aliases):
        current = client.get_registered_model(name).aliases
        for key in ('production', 'champion', 'previous'):
            if key in aliases:
                client.set_registered_model_alias(name, key, aliases[key])
            elif key in current:
                client.delete_registered_model_alias(name, key)

    def rollback_drill(self):
        import mlflow
        from src.demand_forecasting.registry import rollback
        client = mlflow.MlflowClient()
        candidate = read(self.out / 'bundles.json')['candidate']
        name = candidate['model_name']
        aliases = {k: str(v) for k, v in client.get_registered_model(name).aliases.items()}
        previous = aliases.get('previous')
        require(previous and previous != candidate['model_version'], 'No distinct previous version for rollback drill')
        bundles = [read(p) for p in (STORE / 'bundles').glob('*/metadata.json')]
        target_meta = next(m for m in bundles if m['model_version'] == previous)
        target_path = next(p.parent for p in (STORE / 'bundles').glob('*/metadata.json')
                           if read(p)['model_version'] == previous)
        target = {'model_name': name, 'model_version': previous, 'bundle_dir': str(target_path),
                  'model_sha256': target_meta['model_sha256'], 'source_model_sha256': target_meta['source_model_sha256']}
        try:
            rollback()
            self.set_pointer('production', target)
            reverted = self.parity(PRODUCTION_URL, target, 'rollback')
        finally:
            self.restore_aliases(client, name, aliases)
            self.set_pointer('production', candidate)
            restored = self.parity(PRODUCTION_URL, candidate, 'restored')
        return {'rollback_version': previous, 'restored_version': candidate['model_version'],
                'rollback_parity': reverted['passed'], 'restored_parity': restored['passed']}

    def verify_monitoring(self):
        info = read(self.out / 'bundles.json')['candidate']
        probe = self.parity(PRODUCTION_URL, info, 'monitoring_probe')
        path = STORE / 'production_events.jsonl'
        expected_keys = {(probe['request_id'], i) for i in range(len(probe['records']))}
        matched = []
        for line in path.read_text(encoding='utf-8').splitlines():
            event = json.loads(line)
            if event['request_id'] == probe['request_id']:
                matched.append(event)
        counts = Counter((e['request_id'], e['row_index']) for e in matched)
        require(set(counts) == expected_keys and all(v == 1 for v in counts.values()), 'Missing/duplicate observation events')
        for event in matched:
            i = event['row_index']
            require(event['model_name'] == info['model_name'] and str(event['model_version']) == info['model_version']
                    and event['features'] == probe['records'][i]
                    and abs(event['prediction'] - probe['actual'][i]) < 1e-5, 'Observation content mismatch')
        # These are live requests now; labels cannot be invented before seven days elapse.
        (self.out / 'verified_events.jsonl').write_text(''.join(json.dumps(e) + '\n' for e in matched), encoding='utf-8')
        manifest = read(self.work / 'reports/generated/feature_split_manifest.json')
        import pandas as pd
        origins = pd.read_csv(self.work / manifest['splits']['validation']['path'], nrows=len(matched),
                              dtype={'sku_id': str})
        mapping = [{'request_id': probe['request_id'], 'row_index': i,
                    'sku_id': str(row['sku_id']), 'forecast_origin_date': str(row['forecast_origin_date']),
                    'request_kind': 'historical_validation_replay', 'live_label_status': 'not_live_forecast'}
                   for i, row in origins.iterrows()]
        write(self.out / 'request_mapping.json', mapping)
        from src.demand_forecasting.monitoring.__main__ import service_status
        return {'expected': len(expected_keys), 'matched_exactly': len(matched), 'request_id': probe['request_id'],
                'service': service_status(PRODUCTION_URL, read(self.work / 'config/monitoring.json')),
                'live_labels': 'No mature live labels yet; historical replay mapping is recorded separately'}

    def simulate_drift(self):
        self.command('-m', 'src.demand_forecasting.monitoring', 'simulate', '--output-dir', self.out / 'drift_demo')
        return {'data_kind': 'synthetic_demo_only', 'purpose': 'Demonstrate drift and delayed-label orchestration'}

    def check_drift(self):
        directory = self.out / 'drift_demo'
        self.command('-m', 'src.demand_forecasting.monitoring', 'reference', '--events', directory / 'reference_events.jsonl',
                     '--labels', directory / 'reference_labels.csv', '--output', directory / 'reference.json')
        self.command('-m', 'src.demand_forecasting.monitoring', 'check', '--events', directory / 'live_events.jsonl',
                     '--labels', directory / 'live_labels.csv', '--reference', directory / 'reference.json',
                     '--output', directory / 'report.json')
        report = read(directory / 'report.json')
        require(report['retraining_trigger'], 'Drift demonstration did not trigger retraining')
        # A second, explicitly synthetic input shifts features without mature labels.
        # Data drift alone must not fabricate labels or trigger retraining.
        shifted = []
        for line in (directory / 'live_events.jsonl').read_text(encoding='utf-8').splitlines():
            event = json.loads(line)
            event['features'] = {k: v + 1000 for k, v in event['features'].items()}
            shifted.append(event)
        (directory / 'shifted_events.jsonl').write_text(''.join(json.dumps(e) + '\n' for e in shifted), encoding='utf-8')
        self.command('-m', 'src.demand_forecasting.monitoring', 'check', '--events', directory / 'shifted_events.jsonl',
                     '--reference', directory / 'reference.json', '--output', directory / 'feature_drift_report.json')
        feature_report = read(directory / 'feature_drift_report.json')
        require(any(a['type'] == 'data_drift' for w in feature_report['windows'] for a in w['alerts']),
                'Feature distribution shift was not detected')
        require(not feature_report['retraining_trigger'], 'Unlabelled data drift must not retrain')
        write(self.out / 'drift_alert.json', {'data_kind': 'synthetic_demo_only', 'retraining_trigger': True,
              'windows': report['windows']})
        print('ALERT: monitoring policy triggered retraining (synthetic demonstration)', flush=True)
        return {'trigger': True, 'data_drift_without_labels_detected': True, 'data_kind': 'synthetic_demo_only'}

    def retrain_candidate(self):
        directory = self.out / 'drift_demo'
        self.command('-m', 'src.demand_forecasting.monitoring', 'retrain', '--events', directory / 'live_events.jsonl',
                     '--labels', directory / 'live_labels.csv', '--report', directory / 'report.json',
                     '--current-model', directory / 'champion_model.joblib', '--params', directory / 'params.json',
                     '--output', directory / 'retrained', '--allow-demo')
        return read(directory / 'retrained/candidate_review.json')

    def live_monitor(self):
        inputs = STORE / 'monitoring_inputs.json'
        if not inputs.is_file():
            return {'status': 'pending_inputs', 'retraining_trigger': False,
                    'reason': 'Provide real reference, events and mature labels; see the orchestration guide'}
        config = read(inputs)
        for key in ('events', 'reference', 'current_model', 'params'):
            path = Path(config[key]).resolve()
            require(path.is_relative_to(STORE.resolve()) and path.is_file(), f'Invalid monitoring input {key}')
        args = ['-m', 'src.demand_forecasting.monitoring', 'check', '--events', config['events'],
                '--reference', config['reference'], '--output', self.out / 'live_monitoring.json',
                '--health-url', PRODUCTION_URL]
        if config.get('labels'):
            path = Path(config['labels']).resolve()
            require(path.is_relative_to(STORE.resolve()) and path.is_file(), 'Invalid label input')
            args += ['--labels', str(path)]
        self.command(*args)
        report = read(self.out / 'live_monitoring.json')
        require(report['identity']['data_kind'] == 'group_project', 'Real monitoring rejects synthetic observations')
        write(self.out / 'live_inputs.json', config)
        alerts = [w for w in report['windows'] if w['alerts']]
        if alerts or report.get('service', {}).get('alerts'):
            write(self.out / 'live_alert.json', report)
            print('ALERT: live monitoring detected drift/performance/service changes', flush=True)
        return report

    def live_retrain(self):
        checked = read(self.out / 'live_monitor.json')['result']
        if not checked.get('retraining_trigger'):
            return {'status': 'not_triggered', 'reason': checked.get('reason', 'Policy did not trigger retraining')}
        config = read(self.out / 'live_inputs.json')
        require(config.get('labels'), 'Mature labels are required before retraining')
        self.command('-m', 'src.demand_forecasting.monitoring', 'retrain', '--events', config['events'],
                     '--labels', config['labels'], '--report', self.out / 'live_monitoring.json',
                     '--current-model', config['current_model'], '--params', config['params'],
                     '--output', self.out / 'live_retrained')
        return read(self.out / 'live_retrained/candidate_review.json')

    def report(self):
        expected = ['initialize', 'prepare_data', 'experiment_2', 'experiment_3', 'verify_full_folds',
                    'candidate_quality_gate', 'register_models', 'export_bundles', 'benchmark_candidates',
                    'approve_and_deploy', 'rollback_drill', 'verify_monitoring', 'simulate_drift', 'check_drift', 'retrain_candidate']
        steps = {name: read(self.out / (name + '.json')) if (self.out / (name + '.json')).exists()
                 else {'status': 'not_run'} for name in expected}
        passed = all(item['status'] == 'success' for item in steps.values())
        current = read(STORE / 'production.json') if (STORE / 'production.json').exists() else None
        before = read(self.out / 'lineage.json').get('production_before') if (self.out / 'lineage.json').exists() else None
        result = {'status': 'passed' if passed else 'failed', 'run_id': self.run_id, 'scenario': self.scenario,
                  'steps': steps, 'production_after': current,
                  'production_unchanged': current == before,
                  'demo_limitations': ['Team owner sign-off pending; automated policy approval is local demo only',
                    'Drift-to-retraining uses explicitly synthetic delayed labels; candidate is never auto-promoted']}
        write(self.out / 'summary.json', result)
        lines = [f'# Airflow run {self.run_id}', f'\nStatus: **{result["status"]}**',
                 f'\nScenario: {self.scenario}', '\n| Task | Status |', '|---|---|']
        lines.extend(f'| {name} | {row["status"]} |' for name, row in steps.items())
        lines += ['\nSee summary.json, per-task logs, approval.json, parity reports, load_test.json and drift_demo/.',
                  '\nDrift/retraining evidence is synthetic_demo_only. Team sign-off remains pending.']
        (self.out / 'summary.md').write_text('\n'.join(lines), encoding='utf-8')
        if not passed:
            write(self.out / 'failure_alert.json', {'run_id': self.run_id, 'severity': 'error',
                  'failed_tasks': [k for k,v in steps.items() if v['status'] == 'failed'],
                  'production_unchanged': current == before})
            print('ALERT: pipeline failed; inspect failure_alert.json', flush=True)
            raise RuntimeError('Pipeline failed: summary and alert saved')
        write(STORE / 'last_successful_workspace.json', {'workspace': str(self.work), 'run_id': self.run_id})
        return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('stage')
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--scenario', choices=['normal', 'bad_data', 'bad_quality'], default='normal')
    args = parser.parse_args()
    allowed = {name for name in Flow.__dict__ if not name.startswith('_')} - {'command', 'set_pointer', 'parity', 'restore_aliases'}
    require(args.stage in allowed, 'Unsupported stage')
    flow = Flow(args.run_id, args.scenario)
    if args.stage != 'initialize':
        sys.path.insert(0, str(flow.work))
        sys.path.insert(0, str(flow.work / 'serving'))
        os.chdir(flow.work)
    started = datetime.now(timezone.utc).isoformat()
    try:
        result = getattr(flow, args.stage)()
        write(flow.out / f'{args.stage}.json', {'status': 'success', 'started_at_utc': started,
              'finished_at_utc': datetime.now(timezone.utc).isoformat(), 'result': result})
    except Exception as exc:
        write(flow.out / f'{args.stage}.json', {'status': 'failed', 'started_at_utc': started,
              'error_type': type(exc).__name__, 'error': str(exc)})
        write(flow.out / f'alert_{args.stage}.json', {'severity': 'error', 'run_id': args.run_id,
              'stage': args.stage, 'error': str(exc)})
        print(f'ALERT: {args.stage}: {exc}', flush=True)
        traceback.print_exc()
        raise SystemExit(1)
    print(json.dumps({'stage': args.stage, 'status': 'success', 'evidence': str(flow.out)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
