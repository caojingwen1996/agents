import math
import sys
import unittest
from datetime import date
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from valuation_service import (  # noqa: E402
    ValuationError,
    calculate_percentile,
    match_thermometer,
    normalize_name,
    validate_code,
)


class ValuationRuleTests(unittest.TestCase):
    def test_validate_code_accepts_exactly_six_digits(self):
        self.assertEqual(validate_code("510500"), "510500")

        for value in ("", "51050", "5105000", "51050A", None):
            with self.subTest(value=value), self.assertRaises(ValuationError) as context:
                validate_code(value)
            self.assertEqual(context.exception.code, "INVALID_CODE")
            self.assertEqual(context.exception.status, 422)

    def test_normalize_name_removes_market_noise(self):
        self.assertEqual(normalize_name(" 中证-500（全收益）指数 "), "中证500")
        self.assertEqual(normalize_name("沪深300 ETF"), "沪深300")

    def test_match_thermometer_prefers_code_over_name(self):
        rows = [
            {"indexCode": "000905", "indexName": "其他名称", "temperature": 61},
            {"indexCode": "000300", "indexName": "中证500", "temperature": 20},
        ]

        match = match_thermometer(rows, "000905", "中证500")

        self.assertEqual(match["temperature"], 61)

    def test_match_thermometer_uses_unique_normalized_name_as_fallback(self):
        rows = [
            {"indexCode": "000905", "indexName": "中证 500 指数", "temperature": 61},
        ]

        match = match_thermometer(rows, "", "中证500")

        self.assertEqual(match["indexCode"], "000905")

    def test_match_thermometer_rejects_ambiguous_name(self):
        rows = [
            {"indexCode": "000905", "indexName": "中证500", "temperature": 61},
            {"indexCode": "399905", "indexName": "中证500指数", "temperature": 60},
        ]

        self.assertIsNone(match_thermometer(rows, "", "中证500"))

    def test_percentile_filters_invalid_values_and_uses_ten_year_window(self):
        points = [
            (date(2014, 1, 1), 1),
            (date(2016, 1, 1), 2),
            (date(2025, 1, 1), 4),
            (date(2026, 1, 1), 3),
            (date(2026, 2, 1), 0),
            (date(2026, 3, 1), math.nan),
            (date(2026, 4, 1), None),
        ]

        metric = calculate_percentile(points)

        self.assertEqual(metric["sampleCount"], 3)
        self.assertEqual(metric["currentValue"], 3)
        self.assertAlmostEqual(metric["percentilePct"], 2 / 3 * 100)
        self.assertEqual(metric["startDate"], "2016-01-01")
        self.assertEqual(metric["endDate"], "2026-01-01")

    def test_percentile_uses_all_available_history_when_shorter_than_ten_years(self):
        metric = calculate_percentile([
            (date(2023, 1, 1), 5),
            (date(2024, 1, 1), 7),
        ])

        self.assertEqual(metric["startDate"], "2023-01-01")
        self.assertEqual(metric["sampleCount"], 2)
        self.assertEqual(metric["percentilePct"], 100)

    def test_percentile_returns_none_when_no_valid_value_exists(self):
        self.assertIsNone(calculate_percentile([
            (date(2026, 1, 1), 0),
            (date(2026, 1, 2), -1),
            (date(2026, 1, 3), None),
        ]))


if __name__ == "__main__":
    unittest.main()
