"""เรียกงานของทีมเป็นด่าน CI/CD และบันทึกหลักฐานโดยไม่เปลี่ยนเกณฑ์อนุมัติ"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone

ROOT = Path(os.environ.get('AIRFLOW_PROJECT_ROOT', Path(__file__).resolve().parents[1]))
RUN_ID = os.environ.get('CI_RUN_ID', 'local')
SCENARIO = os.environ.get('CI_SCENARIO', 'normal')
KEY = re.sub(r'[^A-Za-z0-9_.-]', '_', RUN_ID)
OUT = ROOT / 'reports/ci'
FLOW_OUT = ROOT / 'reports/orchestration' / KEY
WORK = ROOT / 'artifacts/orchestration/runs' / KEY / 'project'
STAGES = ('code', 'data', 'model', 'integration', 'package', 'delivery')


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def command(*args, cwd=ROOT):
    print('COMMAND:', subprocess.list2cmdline(list(map(str, args))), flush=True)
    env = {k: v for k, v in os.environ.items() if k not in ('PYTHONPATH', 'PYTHONHOME')}
    env['PYTHONNOUSERSITE'] = '1'
    subprocess.run(list(map(str, args)), cwd=cwd, env=env, check=True)


def flow(stage, scenario='normal'):
    command(sys.executable, ROOT / 'orchestration/airflow/run_stage.py', stage,
            '--run-id', RUN_ID, '--scenario', scenario)


def code():
    # ตัวอย่างผิดไวยากรณ์อยู่เฉพาะรอบพิสูจน์ ไม่แก้ไฟล์ของทีม
    if SCENARIO == 'bad_code':
        ast.parse('def deliberately_invalid(:\n', filename='isolated_bad_code_fixture.py')
    count = 0
    for directory in ('src', 'scripts', 'tests', 'serving/app', 'serving/scripts', 'orchestration'):
        for path in (ROOT / directory).rglob('*.py'):
            ast.parse(path.read_text(encoding='utf-8-sig'), filename=str(path))
            count += 1
    command(sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-t', '.', '-v')
    command(sys.executable, '-m', 'pytest', 'tests', '-q', '--junitxml=' + str(OUT / 'serving-tests.xml'),
            cwd=ROOT / 'serving')
    return {'syntax_files': count, 'project_unittests': 'passed', 'serving_tests': 'passed'}


def data():
    flow('initialize')
    if SCENARIO == 'bad_data':
        command(sys.executable, 'scripts/download_data.py', cwd=WORK)
        command(sys.executable, 'scripts/prepare_data.py', cwd=WORK)
        # ใช้ตัวฉีดข้อมูลผิดและ validator เดียวกับการทดสอบ Airflow เดิม
        flow('prepare_data', 'bad_data')
    else:
        flow('prepare_data')
    return read(WORK / 'reports/generated/validation_summary.json')


def model():
    for stage in ('experiment_2', 'experiment_3', 'verify_full_folds'):
        flow(stage)
    flow('candidate_quality_gate', 'bad_quality' if SCENARIO == 'bad_model' else 'normal')
    return read(FLOW_OUT / 'quality_gate.json')


def integration():
    for stage in ('register_models', 'export_bundles', 'benchmark_candidates',
                  'approve_and_deploy', 'rollback_drill', 'verify_monitoring'):
        flow(stage)
    return {'serving': 'passed', 'rollback': 'passed', 'monitoring_events': 'passed',
            'deployment_scope': 'isolated_ci_containers'}


def package():
    if SCENARIO != 'normal':
        raise ValueError('รอบทดสอบข้อผิดพลาดห้ามสร้างชุดส่งมอบ')
    target = ROOT / 'delivery'
    target.mkdir(exist_ok=False)
    for name, source in [('app', ROOT / 'serving/app'), ('src', ROOT / 'src')]:
        shutil.copytree(source, target / name, ignore=shutil.ignore_patterns('__pycache__'))
    bundles = read(FLOW_OUT / 'bundles.json')
    for role, info in bundles.items():
        bundle = target / 'bundles' / role
        bundle.mkdir(parents=True)
        for name in ('model.joblib', 'metadata.json', 'sample_request.json'):
            shutil.copy2(Path(info['bundle_dir']) / name, bundle / name)
    for source, name in [('orchestration/airflow/requirements.lock', 'requirements.lock'),
                         ('ci/runtime.Dockerfile', 'Dockerfile'), ('ci/delivery.compose.yaml', 'compose.yaml'),
                         ('docs/ci_delivery_th.md', 'README_TH.md')]:
        shutil.copy2(ROOT / source, target / name)
    write(target / 'provenance.json', {'run_id': RUN_ID, 'commit': os.environ.get('PROJECT_GIT_COMMIT'),
          'scenario': SCENARIO, 'models': bundles, 'quality_gate': read(FLOW_OUT / 'quality_gate.json'),
          'approval': read(FLOW_OUT / 'approval.json'),
          'scope': 'ชุดส่งมอบสำหรับสาธิต; การยืนยันของเจ้าของโมเดล/API ยังแยกจากผลอัตโนมัติ'})
    checksums = {str(p.relative_to(target)): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in sorted(target.rglob('*')) if p.is_file()}
    write(target / 'checksums.json', checksums)
    return {'files': len(checksums), 'models': bundles}


def delivery():
    # ตรวจ image ที่สร้างจากไฟล์ส่งมอบจริงอีกครั้ง เทียบกับ Registry ของรอบนี้
    import httpx
    sys.path.insert(0, str(ROOT))
    from orchestration.airflow.run_stage import Flow
    runner = Flow(RUN_ID)
    bundles = read(FLOW_OUT / 'bundles.json')
    for role in ('candidate', 'fallback'):
        url = 'http://delivery-' + role + ':8000'
        for attempt in range(60):
            try:
                response = httpx.get(url + '/health', timeout=3, trust_env=False)
                if response.status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(2)
        else:
            raise RuntimeError('ชุดส่งมอบยังไม่พร้อม: ' + role)
        runner.parity(url, bundles[role], 'delivery_' + role)
        command(sys.executable, 'serving/scripts/verify_http.py', '--url', url,
                '--bundle-dir', bundles[role]['bundle_dir'], '--output', FLOW_OUT / ('delivery_' + role + '_http.json'))
    return {'candidate': 'passed', 'fallback': 'passed', 'registry_parity': True}


def report():
    statuses = {s: read(OUT / (s + '.json')) if (OUT / (s + '.json')).exists()
                else {'status': 'not_run'} for s in STAGES}
    passed = all(value['status'] == 'success' for value in statuses.values())
    write(OUT / 'summary.json', {'run_id': RUN_ID, 'scenario': SCENARIO, 'passed': passed,
          'commit': os.environ.get('PROJECT_GIT_COMMIT'), 'stages': statuses,
          'delivery_allowed': passed and SCENARIO == 'normal'})
    if FLOW_OUT.exists():
        # เก็บเฉพาะรายงาน ไม่เผยแพร่ข้อมูลดิบหรือ observation รายแถว
        excluded = {'load_receipts.json', 'request_mapping.json', 'load_payload.json'}
        for path in FLOW_OUT.glob('*.json'):
            if path.name not in excluded and not path.name.endswith('_parity.json'):
                shutil.copy2(path, OUT / ('flow_' + path.name))
    lines = ['# ผล CI/CD', '', f'รอบ: `{RUN_ID}`', f'สถานการณ์: `{SCENARIO}`', '',
             '| ด่าน | ผล |', '|---|---|']
    lines += [f'| {name} | {value["status"]} |' for name, value in statuses.items()]
    lines += ['', 'ผลทดสอบนี้เป็นการ deploy ใน container แยกของ CI และใช้เกณฑ์เดิมของทีม']
    (OUT / 'summary.md').write_text('\n'.join(lines), encoding='utf-8')
    print('\n'.join(lines), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=(*STAGES, 'report'))
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    if SCENARIO not in ('normal', 'bad_code', 'bad_data', 'bad_model'):
        raise ValueError('สถานการณ์ไม่รองรับ')
    if args.stage == 'report':
        report()
        return
    started = datetime.now(timezone.utc).isoformat()
    try:
        for previous in STAGES[:STAGES.index(args.stage)]:
            if read(OUT / (previous + '.json'))['status'] != 'success':
                raise ValueError('ด่านก่อนหน้ายังไม่ผ่าน: ' + previous)
        result = globals()[args.stage]()
        write(OUT / (args.stage + '.json'), {'status': 'success', 'started_at_utc': started, 'result': result})
    except Exception as exc:
        write(OUT / (args.stage + '.json'), {'status': 'failed', 'started_at_utc': started,
              'error_type': type(exc).__name__, 'error': str(exc)})
        print('::error::ด่าน ' + args.stage + ' ไม่ผ่าน; หยุดก่อนส่งมอบ', flush=True)
        traceback.print_exc()
        raise SystemExit(1)


if __name__ == '__main__':
    main()
