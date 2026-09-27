"""Monitoring contract tests using deterministic small observations."""

import csv
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.demand_forecasting.monitoring.core import (
    analyze,
    build_reference,
    join_labels,
    load_events,
)

POLICY = {
    "forecast_horizon_days": 7, "window_days": 7, "minimum_window_rows": 10,
    "minimum_labelled_rows": 10, "numeric_psi_alert": .2, "categorical_tvd_alert": .2,
    "mae_ratio_alert": 1.25, "mae_absolute_increase_alert": 2,
    "consecutive_degraded_windows_to_retrain": 2,
}


class MonitoringTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.origin = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def write(self, name, days, shift=0, feature_shift=0, labels=True):
        events = self.path / f"{name}.jsonl"
        actuals = self.path / f"{name}.csv"
        with events.open("w", encoding="utf-8") as stream, actuals.open(
            "w", newline="", encoding="utf-8"
        ) as csvfile:
            writer = csv.DictWriter(csvfile, ["request_id", "row_index", "actual", "observed_at"])
            writer.writeheader()
            for day in days:
                for i in range(20):
                    instant = self.origin + timedelta(days=day)
                    key = f"{name}-{day}-{i}"
                    stream.write(json.dumps({
                        "timestamp": instant.isoformat(), "request_id": key, "row_index": 0,
                        "model_name": "sku", "model_version": "1", "data_kind": "group_project",
                        "features": {"lag_1": i % 10 + feature_shift}, "prediction": float(i),
                    }) + "\n")
                    if labels:
                        writer.writerow({"request_id": key, "row_index": 0, "actual": i + shift,
                                         "observed_at": (instant + timedelta(days=8)).isoformat()})
        return events, actuals

    def test_delayed_performance_alert_triggers_after_two_windows(self):
        old, old_labels = self.write("old", range(7))
        new, new_labels = self.write("new", range(7, 21), shift=8)
        reference = build_reference(join_labels(load_events(old), old_labels, 7), 10)
        result = analyze(join_labels(load_events(new), new_labels, 7), reference, POLICY)
        self.assertTrue(result["retraining_trigger"])
        self.assertEqual(result["windows"][-1]["alerts"][-1]["type"], "suspected_concept_drift")

    def test_feature_drift_without_labels_does_not_trigger_retraining(self):
        old, old_labels = self.write("old", range(7))
        new, _ = self.write("new", range(7, 21), feature_shift=100, labels=False)
        reference = build_reference(join_labels(load_events(old), old_labels, 7), 10)
        result = analyze(join_labels(load_events(new), None, 7), reference, POLICY)
        self.assertFalse(result["retraining_trigger"])
        self.assertEqual(result["windows"][-1]["alerts"][0]["type"], "data_drift")
        self.assertEqual(result["windows"][-1]["label_status"], "pending_mature_labels")

    def test_early_and_orphan_labels_are_rejected(self):
        events, labels = self.write("sample", range(1))
        lines = labels.read_text(encoding="utf-8").splitlines()
        fields = lines[1].split(",")
        fields[-1] = (self.origin + timedelta(days=1)).isoformat()
        lines[1] = ",".join(fields)
        labels.write_text("\n".join(lines) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "before seven-day horizon"):
            join_labels(load_events(events), labels, 7)

    def test_mixed_model_versions_are_rejected(self):
        events, labels = self.write("sample", range(1))
        lines = events.read_text(encoding="utf-8").splitlines()
        changed = json.loads(lines[1])
        changed["model_version"] = "2"
        lines[1] = json.dumps(changed)
        events.write_text("\n".join(lines) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "mix model versions"):
            build_reference(join_labels(load_events(events), labels, 7), 10)


if __name__ == "__main__":
    unittest.main()
