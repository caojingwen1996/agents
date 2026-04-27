import tempfile
import unittest
from pathlib import Path

from trading_discipline_agent.archive import ArchiveTarget, suggest_archive_path, write_markdown


class ArchiveTests(unittest.TestCase):
    def test_suggests_pre_trade_archive_path(self):
        path = suggest_archive_path(ArchiveTarget("pre", "2026-04-27", "QQQ", "买入"))

        self.assertEqual(path, "Trading/03_Pre_Trade_Audit/20260427_QQQ_买入_审计.md")

    def test_suggests_llmwiki_reference_archive_path(self):
        path = suggest_archive_path(ArchiveTarget("ref", "2026-04-27", "纳斯达克100", "加仓"))

        self.assertEqual(path, "Trading/01_LLMWiki_Query_Refs/20260427_纳斯达克100_加仓_规则引用.md")

    def test_write_markdown_creates_parent_directories(self):
        with tempfile.TemporaryDirectory() as directory:
            output = write_markdown(
                Path(directory),
                ArchiveTarget("rule", "2026-04-27", "情绪纪律", "候选规则"),
                "# 候选个人规则\n",
            )

            self.assertTrue(output.exists())
            self.assertEqual(output.read_text(encoding="utf-8"), "# 候选个人规则\n")


if __name__ == "__main__":
    unittest.main()
