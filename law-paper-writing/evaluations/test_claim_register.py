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
    def run_checker(self, body, *args):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "主张表.tsv"
            path.write_text(HEADER + body, encoding="utf-8-sig")
            return subprocess.run(
                [sys.executable, "-X", "utf8", str(SCRIPT), str(path), *args],
                capture_output=True, text=True, encoding="utf-8", check=False,
            )

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


if __name__ == "__main__":
    unittest.main()
