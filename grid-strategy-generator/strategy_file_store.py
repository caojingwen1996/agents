"""Validated, atomic persistence for saved grid strategies."""

from __future__ import annotations

import copy
import json
import math
import os
import tempfile
import threading
from datetime import datetime
from pathlib import Path
from typing import Any


EMPTY_STORE = {"version": 2, "records": []}


class StrategyStoreError(Exception):
    def __init__(self, code: str, message: str, status: int = 500):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def _number(value: Any, *, positive: bool = False, non_negative: bool = False) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError from error
    if not math.isfinite(parsed):
        raise ValueError
    if positive and parsed <= 0:
        raise ValueError
    if non_negative and parsed < 0:
        raise ValueError
    return parsed


def _record_key(item: dict[str, Any]) -> str:
    return str(item.get("code") or item.get("symbol") or "").strip().lower()


def _saved_at(item: dict[str, Any]) -> datetime:
    return datetime.fromisoformat(str(item["savedAt"]).replace("Z", "+00:00"))


def validate_store(payload: Any) -> dict[str, Any]:
    try:
        if not isinstance(payload, dict) or payload.get("version") != 2:
            raise ValueError
        records = payload.get("records")
        if not isinstance(records, list):
            raise ValueError
        seen = set()
        for item in records:
            if not isinstance(item, dict) or item.get("version") != 2:
                raise ValueError
            code = item.get("code")
            if not isinstance(code, str) or (code and (len(code) != 6 or not code.isdigit())):
                raise ValueError
            if not isinstance(item.get("name"), str) or not isinstance(item.get("symbol"), str):
                raise ValueError
            key = _record_key(item)
            if not key or key in seen:
                raise ValueError
            seen.add(key)
            _saved_at(item)
            inputs = item.get("input")
            if not isinstance(inputs, dict) or inputs.get("fundingMode") not in {"total", "perGrid"}:
                raise ValueError
            _number(inputs.get("startPrice"), positive=True)
            _number(inputs.get("stepPct"), positive=True)
            _number(inputs.get("maxDropPct"), positive=True)
            _number(inputs.get("amount"), positive=True)
            _number(inputs.get("feePct"), non_negative=True)
            if inputs.get("profitRetentionMultiple") not in {0, 1, 2, 3}:
                raise ValueError
            snapshot = item.get("valuationSnapshot")
            if snapshot is not None and not isinstance(snapshot, dict):
                raise ValueError
        return copy.deepcopy({"version": 2, "records": records})
    except (KeyError, TypeError, ValueError) as error:
        raise StrategyStoreError("INVALID_STRATEGY_STORE", "策略数据格式无效", 422) from error


class StrategyFileStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.RLock()

    def _read_unlocked(self) -> dict[str, Any]:
        if not self.path.exists():
            return copy.deepcopy(EMPTY_STORE)
        try:
            return validate_store(json.loads(self.path.read_text(encoding="utf-8")))
        except StrategyStoreError as error:
            raise StrategyStoreError("STRATEGY_STORE_CORRUPT", "策略文件格式损坏") from error
        except (OSError, json.JSONDecodeError) as error:
            raise StrategyStoreError("STRATEGY_STORE_CORRUPT", "策略文件无法读取") from error

    def read(self) -> dict[str, Any]:
        with self._lock:
            return self._read_unlocked()

    def _write_unlocked(self, payload: Any) -> dict[str, Any]:
        validated = validate_store(payload)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise StrategyStoreError("STRATEGY_STORE_WRITE_FAILED", "策略文件保存失败") from error
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=self.path.parent,
                delete=False,
            ) as handle:
                temporary = Path(handle.name)
                json.dump(validated, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            return validated
        except OSError as error:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
            raise StrategyStoreError("STRATEGY_STORE_WRITE_FAILED", "策略文件保存失败") from error

    def write(self, payload: Any) -> dict[str, Any]:
        with self._lock:
            return self._write_unlocked(payload)

    def import_records(self, payload: Any) -> dict[str, int]:
        incoming = validate_store(payload)["records"]
        with self._lock:
            current = self._read_unlocked()["records"]
            merged = {_record_key(item): item for item in current}
            imported = updated = skipped = 0
            for item in incoming:
                key = _record_key(item)
                previous = merged.get(key)
                if previous is None:
                    merged[key] = item
                    imported += 1
                elif _saved_at(item) > _saved_at(previous):
                    merged[key] = item
                    updated += 1
                else:
                    skipped += 1
            records = sorted(merged.values(), key=_saved_at, reverse=True)
            self._write_unlocked({"version": 2, "records": records})
            return {
                "imported": imported,
                "updated": updated,
                "skipped": skipped,
                "total": len(records),
            }
