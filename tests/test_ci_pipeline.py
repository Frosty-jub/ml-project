"""ตรวจการหยุด CI และการสร้างหลักฐาน โดยไม่ฝึกโมเดลซ้ำใน unit test"""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import ci_pipeline as ci


class CiPipelineTests(unittest.TestCase):
    def test_failed_previous_stage_blocks_next_stage(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            ci.write(out / 'code.json', {'status': 'failed'})
            with patch.object(ci, 'OUT', out), patch.object(ci, 'data') as data, \
                    patch('sys.argv', ['ci_pipeline.py', 'data']):
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
