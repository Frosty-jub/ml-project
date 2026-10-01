"""Training/serving feature parity, calendar semantics and leakage checks."""

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from scripts.build_features import build_features as offline_build_features
from src.demand_forecasting.features import build_features
from src.demand_forecasting.serving_features import (
    load_feature_contract,
    prepare_prediction_request,
)

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / "config/pipeline.json").read_text("utf-8"))


def daily_fixture():
    """Unequal SKU start dates, explicit zero days, and future rows."""
    frames = []
    for sku, offset in (("A", 0), ("B", 7)):
        dates = pd.date_range("2020-01-01", periods=80)[offset:]
        units = np.arange(len(dates), dtype=np.int64) + 1
        units[10:13] = 0
        frames.append(pd.DataFrame({"sku_id": sku, "forecast_origin_date": dates,
                                    "daily_sold_units": units,
                                    "demand_next_7d_units": np.arange(len(dates)) * 1000}))
    panel = pd.concat(frames, ignore_index=True)
    offline, _ = offline_build_features(panel, CONFIG)
    names = [name for name in offline if name not in {"sku_id", "forecast_origin_date", "demand_next_7d_units"}]
    manifest = {"feature_columns": names, "forecast_horizon_days": 7,
                "configuration_sha256": hashlib.sha256((ROOT / "config/pipeline.json").read_bytes()).hexdigest()}
    return panel, offline, manifest


class ServingFeatureTests(unittest.TestCase):
    def setUp(self):
        self.panel, self.offline, self.manifest = daily_fixture()
        self.origin = "2020-03-01"

    def prepare(self, panel=None, manifest=None, origin=None):
        return prepare_prediction_request(self.panel if panel is None else panel,
                                          origin or self.origin, CONFIG, manifest or self.manifest)

    def test_offline_and_serving_use_the_same_function(self):
        self.assertIs(offline_build_features, build_features)

    def test_every_feature_and_column_order_match_offline(self):
        payload, keys = self.prepare(self.panel.sample(frac=1, random_state=4))
        expected = self.offline.loc[self.offline.forecast_origin_date.eq(self.origin)]
        self.assertEqual([row["sku_id"] for row in keys], expected.sku_id.tolist())
        self.assertEqual(list(payload["records"][0]), self.manifest["feature_columns"])
        np.testing.assert_array_equal(pd.DataFrame(payload["records"]).to_numpy(),
                                      expected[self.manifest["feature_columns"]].to_numpy())

    def test_lag_and_rolling_include_the_correct_days(self):
        payload, _ = self.prepare()
        row = payload["records"][0]
        self.assertEqual(row["daily_sold_units"], 61)
        self.assertEqual(row["sales_lag_1"], 60)
        self.assertEqual(row["sales_lag_7"], 54)
        self.assertEqual(row["sales_lag_28"], 33)
        self.assertEqual(row["sales_rolling_sum_7"], sum(range(55, 62)))
        self.assertEqual(row["days_since_first_sale"], 60)
        self.assertEqual(row["day_of_week"], 6)
        self.assertEqual(row["month"], 3)
        self.assertEqual(row["is_weekend"], 1)

    def test_future_sales_and_labels_do_not_affect_request(self):
        changed = self.panel.copy()
        changed.loc[changed.forecast_origin_date.gt(self.origin), "daily_sold_units"] = 999999
        changed["demand_next_7d_units"] = -999999
        self.assertEqual(self.prepare()[0], self.prepare(changed)[0])
        unlabeled = changed.drop(columns="demand_next_7d_units")
        self.assertEqual(self.prepare()[0], self.prepare(unlabeled)[0])

    def test_training_daily_file_and_explicit_sku_selection(self):
        history = self.panel.drop(columns="demand_next_7d_units").rename(columns={"forecast_origin_date": "date"})
        payload, keys = prepare_prediction_request(history, self.origin, CONFIG, self.manifest, ["B"])
        self.assertEqual(len(payload["records"]), 1)
        self.assertEqual(keys[0]["sku_id"], "B")

    def test_missing_duplicate_and_missing_origin_days_rejected(self):
        for history in (self.panel.drop(index=12), pd.concat([self.panel, self.panel.iloc[[12]]]),
                        self.panel.loc[~self.panel.forecast_origin_date.eq(self.origin)]):
            with self.subTest(rows=len(history)), self.assertRaises(ValueError):
                self.prepare(history)

    def test_invalid_sales_rejected(self):
        for value in (-1, 1.5, float("nan"), float("inf"), True, "12"):
            with self.subTest(value=value):
                changed = self.panel.astype({"daily_sold_units": object})
                changed.loc[0, "daily_sold_units"] = value
                with self.assertRaises(ValueError):
                    self.prepare(changed)

    def test_warmup_and_first_sale_contract(self):
        with self.assertRaisesRegex(ValueError, "Insufficient"):
            self.prepare(origin="2020-01-29")  # A has 28 prior days, B only 21.
        changed = self.panel.copy()
        changed.loc[0, "daily_sold_units"] = 0
        with self.assertRaisesRegex(ValueError, "first sale"):
            self.prepare(changed)

    def test_wrong_feature_order_or_target_in_manifest_rejected(self):
        for names in (self.manifest["feature_columns"][::-1],
                      self.manifest["feature_columns"] + ["demand_next_7d_units"]):
            with self.assertRaises(ValueError):
                self.prepare(manifest={**self.manifest, "feature_columns": names})

    def test_changed_pipeline_config_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "pipeline.json"
            manifest = Path(directory) / "manifest.json"
            config.write_bytes((ROOT / "config/pipeline.json").read_bytes())
            manifest.write_text(json.dumps(self.manifest), encoding="utf-8")
            load_feature_contract(config, manifest)
            config.write_text(json.dumps({**CONFIG, "forecast_horizon_days": 14}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "does not match"):
                load_feature_contract(config, manifest)

    def test_cli_writes_api_envelope_and_separate_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            history, manifest, output = root / "daily.csv.gz", root / "manifest.json", root / "request.json"
            self.panel.rename(columns={"forecast_origin_date": "date"}).to_csv(history, index=False)
            manifest.write_text(json.dumps(self.manifest), encoding="utf-8")
            subprocess.run([sys.executable, str(ROOT / "scripts/prepare_serving_request.py"),
                            "--history", str(history), "--origin", self.origin, "--sku", "B",
                            "--manifest", str(manifest), "--output", str(output)],
                           cwd=ROOT, check=True, capture_output=True)
            payload = json.loads(output.read_text("utf-8"))
            receipt = json.loads(output.with_suffix(".metadata.json").read_text("utf-8"))
            self.assertEqual(set(payload), {"records"})
            self.assertEqual(receipt["row_keys"][0]["sku_id"], "B")
            self.assertEqual(receipt["request_sha256"], hashlib.sha256(output.read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()
