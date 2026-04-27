from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


@dataclass(frozen=True)
class ArchiveTarget:
    report_type: str
    date_text: str
    symbol: str
    action: str


def suggest_archive_path(target: ArchiveTarget) -> str:
    compact_date = target.date_text.replace("-", "")
    symbol = _safe_path_part(target.symbol or "未命名标的")
    action = _safe_path_part(target.action or "未命名操作")

    if target.report_type == "post":
        return f"Trading/04_Post_Trade_Review/{compact_date}_{symbol}_{action}_复盘.md"
    if target.report_type == "rule":
        return f"Trading/02_Personal_Rules/{compact_date}_{symbol}_{action}_候选规则.md"
    if target.report_type == "ref":
        return f"Trading/01_LLMWiki_Query_Refs/{compact_date}_{symbol}_{action}_规则引用.md"
    return f"Trading/03_Pre_Trade_Audit/{compact_date}_{symbol}_{action}_审计.md"


def write_markdown(root: Path, target: ArchiveTarget, content: str) -> Path:
    relative_path = Path(suggest_archive_path(target))
    output_path = root / relative_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")
    return output_path


def _safe_path_part(value: str) -> str:
    return re.sub(r'[\\/:*?"<>|\\s]+', "_", value).strip("_")
