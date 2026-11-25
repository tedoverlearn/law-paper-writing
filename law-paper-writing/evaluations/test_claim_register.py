"""Exercise the released command against realistic claim and source changes."""

from pathlib import Path
import json
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_claim_register.py"
HEADER = "id\tclaim\tlocation\tdepends_on\tsources\tdecision\n"


class ClaimRegisterTest(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.register = self.root / "主张表.tsv"

    def run_checker(self, body, *args):
        self.register.write_text(HEADER + body, encoding="utf-8-sig")
        before = self.register.read_bytes()
        result = subprocess.run(
            [sys.executable, "-B", "-X", "utf8", str(SCRIPT), str(self.register), *map(str, args)],
            cwd=self.root, capture_output=True, text=True, encoding="utf-8", check=False,
        )
        self.assertEqual(self.register.read_bytes(), before)
        return result

    def manuscript(self, content, name="论文 工作稿.md"):
        path = self.root / name
        path.write_text(content, encoding="utf-8-sig")
        return path

    def test_source_change_followed_from_two_locations_to_abstract(self):
        result = self.run_checker(
            "C01\t异文解释\t第一节、注3\t\tS01@第19页\tconfirmed\n"
            "C02\t相关旧义\t第二节\t\tS01@第20页\tprovisional\n"
            "C03\t下游推论\t第三节\tC01,C02\t\tconfirmed\n"
            "C04\t摘要概括\t摘要第2句\tC03\t\tconfirmed\n"
            "C05\t独立记录\t第四节\t\tS010@第3页\tconfirmed\n",
            "--source", "S01", "--json",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["scope"], "claim_register")
        self.assertEqual([entry["id"] for entry in report["affected"]], [
            "C01", "C02", "C03", "C04",
        ])
        self.assertEqual(report["affected"][-1]["location"], "摘要第2句")

    def test_withdrawn_judgment_surfaces_still_active_dependents(self):
        result = self.run_checker(
            "C01\t旧判断\t第一节\t\tS01@第3页\twithdrawn\n"
            "C02\t旧中间推论\t第二节\tC01\t\twithdrawn\n"
            "C03\t仍在摘要的句子\t摘要\tC02\t\tconfirmed\n",
            "--claim", "C01", "--json",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["depends_on_withdrawn_claim"], ["C03"])

    def test_invalid_tables_fail_without_an_impact_report(self):
        cases = [
            ("C01\t旧判断\t摘要\tC99\t\tconfirmed\n", "missing dependencies"),
            ("C01\t旧判断\t摘要\tC01\t\tconfirmed\n", "circular dependency"),
            ("C01\t旧判断\t摘要\t\tS01@\tconfirmed\n", "source ID and location"),
        ]
        for body, expected in cases:
            with self.subTest(expected=expected):
                result = self.run_checker(body, "--json")
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")
                self.assertIn(expected, result.stderr)

    def test_coverage_reports_both_differences_and_preserves_manuscript(self):
        path = self.manuscript("摘要：〔C01〕已列。\n## 正文\n一处〔C99〕。\n再次标 C99。\n")
        before = path.read_bytes()
        body = (
            "C01\t摘要判断\t摘要第1句\tC99\tS01@第3页\tconfirmed\n"
            "C02\t撤回判断\t原稿第二节\tC01\t\twithdrawn\n"
        )
        result = self.run_checker(body, "--check-coverage", path, "--json")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertEqual(path.read_bytes(), before)
        report = json.loads(result.stdout)
        self.assertEqual(report["scope"], "claim_coverage")
        self.assertEqual(report["manuscript"], path.as_posix())
        self.assertEqual(report["entries"], 2)
        self.assertEqual(report["marked_claims"], 2)
        self.assertEqual(report["markers_missing_from_register"], [
            {"id": "C99", "occurrences": [{"line": 3, "column": 4}, {"line": 4, "column": 5}]},
        ])
        self.assertEqual(report["claims_missing_from_manuscript"], [
            {"id": "C02", "location": "原稿第二节", "decision": "withdrawn"},
        ])

    def test_coverage_text_report_explains_the_two_issue_types(self):
        path = self.manuscript("摘要：〔C03〕结果。\n", "在审稿.txt")
        result = self.run_checker("C01\t旧判断\t摘要末句\t\t\tprovisional\n", "--check-coverage", path)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("正文有标记但主张表未登记 | 1 条", result.stdout)
        self.assertIn("C03\t第 1 行第 5 列", result.stdout)
        self.assertIn("表内已登记但正文未出现 | 1 条", result.stdout)
        self.assertIn("C01\t摘要末句\tprovisional", result.stdout)

    def test_matching_coverage_counts_only_complete_ids(self):
        path = self.manuscript(
            "摘要：C01校核。\n## 正文\n复核〔C01〕、[C002] 与 `C03`。\n"
            "数据编码 XC01、key_C04、C05x、C06_2 单列。\n"
        )
        body = (
            "C01\t摘要判断\t摘要\t\t\tconfirmed\n"
            "C002\t正文判断\t正文第一段\tC01\t\tprovisional\n"
            "C03\t复核判断\t正文第一段\t\t\tconfirmed\n"
        )
        result = self.run_checker(body, "--check-coverage", path, "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["marked_claims"], 3)
        self.assertEqual(report["markers_missing_from_register"], [])
        self.assertEqual(report["claims_missing_from_manuscript"], [])

    def test_coverage_limits_markers_to_prose_sections(self):
        path = self.manuscript(
            "## 正文\n正文〔C01〕。\n> 附引文字 C20。\n"
            "```text\nC21\n```\n\n"
            "[^1]: 仅见注释 C22。\n    延续注释 C23。\n\n"
            "## 结语\n结语〔C02〕。\n"
            "## 参考文献\n题名 C30。\n## 附录\n保留旧判断 C25。\n"
        )
        body = (
            "C01\t正文判断\t正文第一段\t\t\tconfirmed\n"
            "C02\t结语判断\t结语\tC01\t\tprovisional\n"
            "C25\t旧判断\t附录\t\t\twithdrawn\n"
        )
        result = self.run_checker(body, "--check-coverage", path, "--json")
        self.assertEqual(result.returncode, 1, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["marked_claims"], 2)
        self.assertEqual(report["markers_missing_from_register"], [])
        self.assertEqual([record["id"] for record in report["claims_missing_from_manuscript"]], ["C25"])

    def test_coverage_is_exclusive_with_impact_queries(self):
        path = self.manuscript("判断 C01。\n")
        body = "C01\t稿件判断\t正文\t\tS01@第3页\tconfirmed\n"
        for selector, identifier in (("--claim", "C01"), ("--source", "S01")):
            with self.subTest(selector=selector):
                result = self.run_checker(body, "--check-coverage", path, selector, identifier)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")
                self.assertIn("not allowed with argument", result.stderr)

    def test_coverage_rejects_unreadable_inputs(self):
        invalid_utf8 = self.root / "损坏.md"
        invalid_utf8.write_bytes(b"\xff")
        for path in (self.root / "缺件.txt", invalid_utf8, self.root / "工作稿.docx"):
            with self.subTest(path=path.name):
                result = self.run_checker("", "--check-coverage", path, "--json")
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")
                self.assertIn("check_claim_register.py:", result.stderr)


if __name__ == "__main__":
    unittest.main()
