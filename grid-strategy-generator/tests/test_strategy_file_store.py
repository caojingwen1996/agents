import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from strategy_file_store import StrategyFileStore, StrategyStoreError  # noqa: E402


def record(code="510500", saved_at="2026-07-15T10:00:00+08:00", price="8.3"):
    return {
        "version": 2,
        "code": code,
        "name": "中证500ETF南方",
        "symbol": "中证500ETF南方",
        "savedAt": saved_at,
        "input": {
            "startPrice": price,
            "stepPct": "5",
            "maxDropPct": "40",
            "fundingMode": "perGrid",
            "amount": "10000",
            "feePct": "0.1",
            "profitRetentionMultiple": 0,
        },
        "valuationSnapshot": None,
    }


class StrategyFileStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "data" / "saved-strategies.json"
        self.store = StrategyFileStore(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def test_missing_file_reads_as_empty_store(self):
        self.assertEqual(self.store.read(), {"version": 2, "records": []})

    def test_write_creates_valid_utf8_store(self):
        envelope = {"version": 2, "records": [record()]}

        self.assertEqual(self.store.write(envelope), envelope)
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8")), envelope)

    def test_corrupt_file_is_not_silently_replaced(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text("not json", encoding="utf-8")

        with self.assertRaises(StrategyStoreError) as context:
            self.store.read()

        self.assertEqual(context.exception.code, "STRATEGY_STORE_CORRUPT")
        self.assertEqual(self.path.read_text(encoding="utf-8"), "not json")

    def test_invalid_record_is_rejected_before_write(self):
        invalid = record()
        invalid["input"]["startPrice"] = "bad"

        with self.assertRaises(StrategyStoreError) as context:
            self.store.write({"version": 2, "records": [invalid]})

        self.assertEqual(context.exception.code, "INVALID_STRATEGY_STORE")
        self.assertFalse(self.path.exists())

    def test_replace_failure_preserves_previous_file(self):
        original = {"version": 2, "records": [record()]}
        self.store.write(original)

        with patch("strategy_file_store.os.replace", side_effect=OSError("locked")):
            with self.assertRaises(StrategyStoreError) as context:
                self.store.write({"version": 2, "records": []})

        self.assertEqual(context.exception.code, "STRATEGY_STORE_WRITE_FAILED")
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8")), original)

    def test_import_keeps_newest_record_and_is_idempotent(self):
        self.store.write({
            "version": 2,
            "records": [record(saved_at="2026-07-15T11:00:00+08:00")],
        })

        result = self.store.import_records({
            "version": 2,
            "records": [
                record(saved_at="2026-07-15T09:00:00+08:00", price="8.0"),
                record(code="000300", saved_at="2026-07-15T12:00:00+08:00", price="4.0"),
            ],
        })

        self.assertEqual(result, {"imported": 1, "updated": 0, "skipped": 1, "total": 2})
        self.assertEqual(self.store.read()["records"][0]["code"], "000300")
        repeat = self.store.import_records({
            "version": 2,
            "records": [
                record(code="000300", saved_at="2026-07-15T12:00:00+08:00", price="4.0"),
            ],
        })
        self.assertEqual(repeat, {"imported": 0, "updated": 0, "skipped": 1, "total": 2})


if __name__ == "__main__":
    unittest.main()
