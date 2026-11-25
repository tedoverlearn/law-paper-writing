"""Exercise read-only manuscript checks through their public command."""

from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


EVALUATIONS = Path(__file__).resolve().parent
CHECKER = EVALUATIONS.parent / "scripts" / "check_manuscript.py"
FIXTURES = EVALUATIONS / "fixtures"
NOTICE = "以上为候选防御性修辞，需人工核对是否属于必要限定，密度不构成删除依据。"


class ManuscriptCheckTest(unittest.TestCase):
    def setUp(self):
        scratch = TemporaryDirectory(prefix="manuscript-test-")
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name)

    def run_check(self, path, code, *options):
        result = subprocess.run(
            [sys.executable, "-B", str(CHECKER), str(path), *options],
            cwd=self.root, capture_output=True, encoding="utf-8",
        )
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        self.assertEqual(result.stderr, "")
        return result.stdout

    def write(self, text, *, encoding="utf-8", suffix=".md"):
        path = self.root / ("带空格 的稿件" + suffix)
        path.write_text(text, encoding=encoding)
        return path

    def test_full_markdown_passes_including_quoted_words_and_reused_note(self):
        path = FIXTURES / "clean-manuscript.md"
        before = path.read_bytes()
        report = self.run_check(path, 0, "--check-hedging")
        self.assertEqual(report.splitlines(), ["通过 | 0 项", "缓冲词命中 | 0 处", NOTICE])
        self.assertEqual(path.read_bytes(), before)

    def test_prose_and_bibliography_warnings_include_both_locations(self):
        path = FIXTURES / "warning-manuscript.txt"
        report = self.run_check(path, 1)
        self.assertIn(":1:6 [major] 结论强度", report)
        self.assertIn("正文第 3 行“提示”", report)
        self.assertIn(":7:1 [major] 参考文献重复 | 与第 6 行", report)
        self.assertIn("警告 | 2 项", report)
        self.assertNotIn(NOTICE, report)

    def test_placeholder_and_numbering_block_submission_and_preserve_input(self):
        path = FIXTURES / "blocked-manuscript.md"
        before = path.read_bytes()
        report = self.run_check(path, 2)
        self.assertIn(":4:9 [critical] 占位 | 待补原文", report)
        self.assertIn(":5:3 [critical] 占位 | 待核", report)
        self.assertIn("预期注 2，实际为注 3", report)
        self.assertIn("注 3 缺少定义", report)
        self.assertIn("注 1 重复定义，首个定义在第 9 行", report)
        self.assertIn("失败 | 5 项", report)
        self.assertEqual(path.read_bytes(), before)

    def test_hedging_is_opt_in_with_one_count_for_overlapping_terms(self):
        path = FIXTURES / "hedging-manuscript.md"
        self.assertEqual(self.run_check(path, 0).splitlines(), ["通过 | 0 项"])
        report = self.run_check(path, 1, "--check-hedging")
        self.assertIn(":3:3 [major] 单句缓冲词叠加 | 2 处，或许、在一定程度上", report)
        self.assertIn(":3:5 [minor] 缓冲词 | 在一定程度上", report)
        self.assertIn(":3:25 [minor] 自谦或免责 | 本文无意", report)
        self.assertEqual(report.count("[major] 段落连续限定或让步"), 1)
        self.assertIn(":5:1 [major] 段落连续限定或让步 | 2 句", report)
        self.assertIn(":10:7 [minor] 缓冲词 | 可能", report)
        self.assertEqual(report.splitlines()[-2:], ["缓冲词命中 | 3 处", NOTICE])

    def test_placeholders_in_headings_and_inline_english_markers(self):
        path = self.write("## 改革〔待核〕\n这里TODO，补核定位。\n候选词是TODOS。\n")
        report = self.run_check(path, 2)
        self.assertIn(":1:7 [critical] 占位 | 待核", report)
        self.assertIn(":2:3 [critical] 占位 | TODO", report)
        self.assertEqual(report.count("[critical] 占位"), 2)

    def test_separate_sentences_do_not_share_hedge_counts(self):
        path = self.write("本文可能引起讨论。或许还有另一种解释。\n")
        report = self.run_check(path, 1, "--check-hedging")
        self.assertEqual(report.count("[minor] 缓冲词"), 2)
        self.assertNotIn("单句缓冲词叠加", report)

    def test_multiline_sentence_uses_original_hit_locations(self):
        path = self.write("本文或许\n似乎可以解释登记簿。\n")
        report = self.run_check(path, 1, "--check-hedging")
        self.assertIn(":1:3 [major] 单句缓冲词叠加", report)
        self.assertIn(":2:1 [minor] 缓冲词 | 似乎", report)

    def test_caveats_separated_by_blank_lines_do_not_form_a_paragraph(self):
        path = self.write("尽管材料限于一处。\n\n现有材料仅覆盖日班。\n")
        report = self.run_check(path, 0, "--check-hedging")
        self.assertNotIn("段落连续限定或让步", report)

    def test_repeated_calls_for_more_research_are_review_candidates(self):
        path = self.write("有待进一步研究。尚需更多材料。\n")
        report = self.run_check(path, 1, "--check-hedging")
        self.assertIn(":1:1 [major] 段落连续限定或让步", report)

    def test_strength_distinguishes_subjects_and_negation(self):
        path = self.write(
            "## 摘要\n本文证明换签改变交接程序。\n"
            "## 正文\n本文提示互助改变交接程序。本文未证明换签改变交接程序。\n"
        )
        report = self.run_check(path, 1)
        self.assertIn("“未证明”", report)
        self.assertNotIn("“提示”", report)

    def test_strength_compares_frequency_within_same_claim(self):
        path = self.write("## 摘要\n全部窗口当班销号。\n## 正文\n部分窗口当班销号。\n")
        self.assertIn("频率相关表述“全部”", self.run_check(path, 1))

    def test_bibliography_preserves_different_editions_and_ignores_body_lists(self):
        path = self.write(
            "## 正文\n论证所用材料如下。\n[1] 桂浦书库。\n[2] 桂浦书库。\n"
            "## 参考文献\n### 专著\n[1] 谷池：《书库志》，初版。\n[2] 谷池：《书库志》，修订版。\n"
            "## 附录\n[1] 谷池：《书库志》，初版。\n"
        )
        self.assertIn("通过 | 0 项", self.run_check(path, 0))

    def test_note_references_ignore_numbered_bibliography_and_allow_exported_text(self):
        path = self.write(
            "正文\n第一段〔注１〕，第二段〔注２〕。同上〔注１〕。\n"
            "参考文献\n[30] 登记簿。\n"
        )
        self.assertIn("通过 | 0 项", self.run_check(path, 0))

    def test_note_zero_out_of_order_and_orphan_are_detected(self):
        path = self.write(
            "正文\n甲〔注0〕，乙〔注2〕，丙〔注1〕。\n"
            "注释\n注1：书一。\n注2：书二。\n注3：书三。\n"
        )
        report = self.run_check(path, 2)
        self.assertIn("注号须从正整数开始", report)
        self.assertIn("预期注 1，实际为注 2", report)
        self.assertIn("注 3 没有正文引用", report)

    def test_utf8_bom_and_unicode_paths(self):
        path = self.write("摘要：登记簿载有交回时刻。", encoding="utf-8-sig", suffix=".TXT")
        self.assertIn("通过 | 0 项", self.run_check(path, 0))

    def test_unsupported_format_missing_corrupt_and_empty_inputs_fail(self):
        bad_encoding = self.root / "invalid.md"
        bad_encoding.write_bytes(b"\xff\xfe\x00")
        empty_file = self.write(" \n")
        for path in (self.root / "missing.md", bad_encoding, empty_file, self.root / "draft.docx"):
            with self.subTest(path=path.name):
                report = self.run_check(path, 2, "--check-hedging")
                self.assertIn("[critical] 无法扫描", report)
                self.assertTrue(report.endswith(NOTICE + "\n"))


if __name__ == "__main__":
    unittest.main()
