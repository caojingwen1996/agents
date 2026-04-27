from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from trading_discipline_agent.archive import ArchiveTarget, write_markdown


def main() -> None:
    parser = argparse.ArgumentParser(description="Archive an LLM-generated trading discipline report.")
    parser.add_argument("--type", choices=("pre", "post", "rule", "ref"), required=True)
    parser.add_argument("--date", required=True)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--action", required=True)
    parser.add_argument("--root", default=".")
    parser.add_argument("--file", help="Read Markdown content from this file. Defaults to stdin.")
    args = parser.parse_args()

    if args.file:
        content = Path(args.file).read_text(encoding="utf-8")
    else:
        content = sys.stdin.read()

    output_path = write_markdown(
        Path(args.root),
        ArchiveTarget(args.type, args.date, args.symbol, args.action),
        content,
    )
    print(output_path)


if __name__ == "__main__":
    main()
