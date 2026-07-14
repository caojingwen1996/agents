from dataclasses import dataclass
from pathlib import Path
import re

from .errors import DashboardError
from .excel_io import load_workbook


FILENAME_PATTERN = re.compile(r"^(?P<code>\d{6})-(?P<name>.+)\.xlsx$", re.IGNORECASE)


@dataclass(frozen=True)
class PositionFile:
    file_id: str
    path: Path
    stock_code: str | None
    display_name: str
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "file_id": self.file_id,
            "stock_code": self.stock_code,
            "display_name": self.display_name,
            "error": self.error,
        }


def discover_positions(data_dir: str | Path) -> tuple[PositionFile, ...]:
    root = Path(data_dir).resolve()
    if not root.exists():
        return ()

    positions = []
    for candidate in sorted(root.glob("*.xlsx"), key=lambda path: path.name):
        if candidate.name.startswith("~$"):
            continue
        path = candidate.resolve()
        if path.parent != root:
            continue

        match = FILENAME_PATTERN.match(candidate.name)
        if match is None:
            positions.append(
                PositionFile(
                    file_id=candidate.name,
                    path=path,
                    stock_code=None,
                    display_name=candidate.stem,
                    error="文件名必须为 6位代码-标的名称.xlsx",
                )
            )
            continue

        stock_code = match.group("code")
        try:
            workbook = load_workbook(path)
        except DashboardError as exc:
            error = str(exc)
        else:
            error = (
                None
                if workbook.settings.stock_code == stock_code
                else f"文件名代码 {stock_code} 与配置股票代码 {workbook.settings.stock_code} 不一致"
            )
        positions.append(
            PositionFile(
                file_id=candidate.name,
                path=path,
                stock_code=stock_code,
                display_name=match.group("name"),
                error=error,
            )
        )
    return tuple(positions)
