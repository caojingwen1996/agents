import math
import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from valuation_service import (  # noqa: E402
    ValuationError,
    ValuationService,
    calculate_percentile,
    match_thermometer,
    normalize_name,
    validate_code,
)
from valuation_sources import Instrument  # noqa: E402


THERMOMETER_LISTING_ROW = {
    "indexCode": "000905",
    "indexName": "中证500",
    "temperature": 82,
    "intrinsicReturnPct": 4.42,
    "dividendYieldPct": 1.53,
    "asOf": "2026-07-03",
    "url": "https://youzhiyouxing.cn/data/indices/000905.SH",
}
THERMOMETER_DETAIL_ROW = {
    **THERMOMETER_LISTING_ROW,
    "temperature": 76,
    "valuationBand": "偏高",
    "asOf": "2026-07-14",
}


class FakeMarketSource:
    def __init__(self, pe=None, pb=None, pe_error=None, pb_error=None):
        self.instrument = Instrument("510500", "中证500ETF南方", "etf", "000905", "中证500")
        self.pe = pe if pe is not None else [
            (date(2025, 1, 1), 10),
            (date(2026, 1, 1), 20),
        ]
        self.pb = pb if pb is not None else [
            (date(2025, 1, 1), 1),
            (date(2026, 1, 1), 1.5),
        ]
        self.pe_error = pe_error
        self.pb_error = pb_error
        self.resolve_calls = 0
        self.pe_calls = 0
        self.pb_calls = 0

    def resolve(self, code):
        self.resolve_calls += 1
        return self.instrument

    def pe_points(self, instrument):
        self.pe_calls += 1
        if self.pe_error:
            raise self.pe_error
        return self.pe

    def pb_points(self, instrument):
        self.pb_calls += 1
        if self.pb_error:
            raise self.pb_error
        return self.pb


class MutableClock:
    def __init__(self):
        self.value = datetime(2026, 7, 15, 10, 0, tzinfo=timezone(timedelta(hours=8)))

    def __call__(self):
        return self.value

    def advance(self, **kwargs):
        self.value += timedelta(**kwargs)


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


class ValuationServiceTests(unittest.TestCase):
    def build_service(
        self,
        source=None,
        listing=None,
        listing_error=None,
        detail=None,
        detail_error=None,
        clock=None,
    ):
        def listing_fetcher():
            if listing_error:
                raise listing_error
            return listing if listing is not None else [THERMOMETER_LISTING_ROW]

        def detail_fetcher(_url):
            if detail_error:
                raise detail_error
            return detail if detail is not None else THERMOMETER_DETAIL_ROW

        return ValuationService(
            source or FakeMarketSource(),
            thermometer_listing=listing_fetcher,
            thermometer_detail=detail_fetcher,
            clock=clock or MutableClock(),
        )

    def test_thermometer_hit_uses_latest_detail_and_skips_percentiles(self):
        source = FakeMarketSource()
        source.instrument = Instrument("510500", "中证500ETF南方", "etf", "", "中证500")
        result = self.build_service(source=source).lookup("510500")

        self.assertEqual(result["version"], 1)
        self.assertEqual(result["source"], "youzhiyouxing")
        self.assertEqual(result["asOf"], "2026-07-14")
        self.assertEqual(result["thermometer"]["temperature"], 76)
        self.assertEqual(result["thermometer"]["valuationBand"], "偏高")
        self.assertEqual(result["trackedIndex"], {"code": "000905", "name": "中证500"})
        self.assertIsNone(result["percentiles"])
        self.assertEqual(source.pe_calls, 0)
        self.assertEqual(source.pb_calls, 0)

    def test_normal_unmatched_listing_falls_back_without_unavailable_warning(self):
        result = self.build_service(listing=[]).lookup("510500")

        self.assertEqual(result["source"], "historical_percentile")
        self.assertEqual(result["warnings"], [])
        self.assertEqual(result["percentiles"]["pe"]["currentValue"], 20)
        self.assertEqual(result["percentiles"]["pb"]["currentValue"], 1.5)

    def test_unavailable_thermometer_falls_back_with_distinct_warning(self):
        result = self.build_service(listing_error=TimeoutError()).lookup("510500")

        self.assertEqual(result["source"], "historical_percentile")
        self.assertEqual(result["warnings"][0]["code"], "THERMOMETER_UNAVAILABLE")
        self.assertEqual(result["warnings"][0]["message"], "温度计暂不可用")

    def test_failed_detail_falls_back_with_unavailable_warning(self):
        result = self.build_service(detail_error=TimeoutError()).lookup("510500")

        self.assertEqual(result["source"], "historical_percentile")
        self.assertEqual(result["warnings"][0]["code"], "THERMOMETER_UNAVAILABLE")

    def test_percentiles_keep_available_metric_when_other_metric_fails(self):
        source = FakeMarketSource(pb_error=RuntimeError("unsupported"))
        result = self.build_service(source=source, listing=[]).lookup("510500")

        self.assertIsNotNone(result["percentiles"]["pe"])
        self.assertIsNone(result["percentiles"]["pb"])

    def test_both_percentile_metrics_failing_returns_public_error(self):
        source = FakeMarketSource(
            pe_error=RuntimeError("pe failed"),
            pb_error=RuntimeError("pb failed"),
        )
        service = self.build_service(source=source, listing=[])

        with self.assertRaises(ValuationError) as context:
            service.lookup("510500")
        self.assertEqual(context.exception.code, "NO_VALUATION_DATA")
        self.assertEqual(context.exception.status, 502)

    def test_success_cache_is_reused_then_expires_after_one_hour(self):
        source = FakeMarketSource()
        clock = MutableClock()
        service = self.build_service(source=source, clock=clock)

        first = service.lookup("510500")
        second = service.lookup("510500")
        clock.advance(hours=1, seconds=1)
        third = service.lookup("510500")

        self.assertFalse(first["cached"])
        self.assertTrue(second["cached"])
        self.assertFalse(third["cached"])
        self.assertEqual(source.resolve_calls, 2)

    def test_failures_are_not_cached(self):
        source = FakeMarketSource(pe_error=RuntimeError(), pb_error=RuntimeError())
        service = self.build_service(source=source, listing=[])

        for _ in range(2):
            with self.assertRaises(ValuationError):
                service.lookup("510500")

        self.assertEqual(source.resolve_calls, 2)


if __name__ == "__main__":
    unittest.main()
