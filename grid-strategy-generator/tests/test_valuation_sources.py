import sys
import unittest
from datetime import date
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(PROJECT_DIR))

from valuation_sources import (  # noqa: E402
    THERMOMETER_URL,
    AkshareSource,
    SourceError,
    frame_metric_points,
    parse_thermometer_detail,
    parse_thermometer_listing,
    parse_tracking_target_html,
)


class SourceParserTests(unittest.TestCase):
    def fixture(self, name):
        return (FIXTURES / name).read_text(encoding="utf-8")

    def test_parse_thermometer_listing_extracts_links_and_missing_values(self):
        rows = parse_thermometer_listing(self.fixture("thermometer_listing.html"))

        self.assertEqual(rows[0], {
            "indexCode": "000905",
            "indexName": "中证500",
            "temperature": 82.0,
            "intrinsicReturnPct": 4.42,
            "dividendYieldPct": 1.53,
            "asOf": "2026-07-03",
            "url": "https://youzhiyouxing.cn/data/indices/000905.SH",
        })
        self.assertIsNone(rows[1]["intrinsicReturnPct"])
        self.assertIsNone(rows[1]["dividendYieldPct"])

    def test_parse_thermometer_detail_uses_latest_detail_date_and_band(self):
        row = parse_thermometer_detail(
            self.fixture("thermometer_detail.html"),
            f"{THERMOMETER_URL.rsplit('/', 1)[0]}/data/indices/000905.SH",
        )

        self.assertEqual(row["indexCode"], "000905")
        self.assertEqual(row["indexName"], "中证500")
        self.assertEqual(row["temperature"], 76.0)
        self.assertEqual(row["valuationBand"], "偏高")
        self.assertEqual(row["intrinsicReturnPct"], 4.42)
        self.assertEqual(row["dividendYieldPct"], 1.53)
        self.assertEqual(row["asOf"], "2026-07-14")

    def test_parse_tracking_target_reads_labeled_table_cell(self):
        self.assertEqual(
            parse_tracking_target_html(self.fixture("fund_basic.html")),
            "中证500指数",
        )

    def test_parse_tracking_target_rejects_absent_target(self):
        html = "<table><tr><th>跟踪标的</th><td>该基金无跟踪标的</td></tr></table>"
        with self.assertRaises(SourceError) as context:
            parse_tracking_target_html(html)
        self.assertEqual(context.exception.code, "TRACKING_INDEX_NOT_FOUND")

    def test_frame_metric_points_converts_dates_and_preserves_invalid_values(self):
        rows = [
            {"日期": "2026-01-02", "滚动市盈率": "12.5"},
            {"日期": date(2026, 1, 3), "滚动市盈率": None},
        ]

        points = frame_metric_points(rows, "日期", "滚动市盈率")

        self.assertEqual(points, [(date(2026, 1, 2), 12.5), (date(2026, 1, 3), None)])


class InstrumentResolutionTests(unittest.TestCase):
    def build_source(self, *, etfs, target="中证500指数", indexes=None):
        return AkshareSource(
            etf_rows=lambda: etfs,
            tracking_target=lambda _code: target,
            index_rows=lambda: indexes or [
                {"index_code": "000905", "display_name": "中证500"},
                {"index_code": "000300", "display_name": "沪深300"},
            ],
        )

    def test_resolve_etf_uses_tracking_target_and_index_catalog(self):
        source = self.build_source(etfs=[{"代码": "510500", "名称": "中证500ETF南方"}])

        instrument = source.resolve("510500")

        self.assertEqual(instrument.code, "510500")
        self.assertEqual(instrument.name, "中证500ETF南方")
        self.assertEqual(instrument.instrument_type, "etf")
        self.assertEqual(instrument.tracked_index_code, "000905")
        self.assertEqual(instrument.tracked_index_name, "中证500")

    def test_resolve_direct_index_code(self):
        source = self.build_source(etfs=[])

        instrument = source.resolve("000300")

        self.assertEqual(instrument.name, "沪深300")
        self.assertEqual(instrument.instrument_type, "index")
        self.assertEqual(instrument.tracked_index_code, "000300")

    def test_resolve_rejects_unknown_code(self):
        source = self.build_source(etfs=[])

        with self.assertRaises(SourceError) as context:
            source.resolve("999999")
        self.assertEqual(context.exception.code, "UNSUPPORTED_INSTRUMENT")

    def test_resolve_rejects_ambiguous_tracking_name(self):
        source = self.build_source(
            etfs=[{"代码": "510500", "名称": "中证500ETF"}],
            indexes=[
                {"index_code": "000905", "display_name": "中证500"},
                {"index_code": "399905", "display_name": "中证500指数"},
            ],
        )

        with self.assertRaises(SourceError) as context:
            source.resolve("510500")
        self.assertEqual(context.exception.code, "AMBIGUOUS_INDEX")


if __name__ == "__main__":
    unittest.main()
