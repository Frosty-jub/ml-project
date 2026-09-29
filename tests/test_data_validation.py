"""Exercise real data validation, including corrupted labels and daily values."""
import tempfile
import unittest
from pathlib import Path
import pandas as pd
from scripts.validate_data import load_table, validate


class DataValidationTests(unittest.TestCase):
    def frames(self):
        daily = pd.DataFrame({"sku_id": ["SKU"] * 10,
                              "date": pd.date_range("2020-01-01", periods=10),
                              "daily_sold_units": [1] * 10})
        labels = pd.DataFrame({"sku_id": ["SKU"] * 3,
                               "forecast_origin_date": pd.date_range("2020-01-01", periods=3),
                               "daily_sold_units": [1] * 3,
                               "demand_next_7d_units": [7] * 3})
        return daily, labels

    def test_valid_data_and_future_target(self):
        daily, labels = self.frames()
        self.assertEqual(validate(daily, labels, 7)["status"], "passed")
        labels.loc[0, "demand_next_7d_units"] = 99
        with self.assertRaises(ValueError):
            validate(daily, labels, 7)

    def test_negative_data_is_rejected(self):
        daily, _ = self.frames()
        daily.loc[0, "daily_sold_units"] = -1
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "bad.csv.gz"
            daily.to_csv(path, index=False, compression="gzip")
            with self.assertRaises(ValueError):
                load_table(path, "date", {"sku_id", "date", "daily_sold_units"})
