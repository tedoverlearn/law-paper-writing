"""Exercise the human-scoring workflow through its command-line entry point."""

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().with_name("run_behavioral.py")
SUITE = SCRIPT.with_name("behavioral")
CASE = "01-historical-law"
OTHER_CASE = "02-abstract-only"


class BehavioralEvaluationTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.scores = self.root / "scores.json"

    def cli(self, *args, success=True):
        result = subprocess.run(
            [sys.executable, "-B", str(SCRIPT), *map(str, args)],
            cwd=self.root,
            capture_output=True,
        )
        if success:
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(result.stdout, "Invalid input produced a public report")
        return result

    def filled_sheet(self, *case_ids):
        selection = []
        for case_id in case_ids:
            selection.extend(["--case", case_id])
        sheet = json.loads(self.cli("template", *selection).stdout)
        sheet.update(
            model="fixture-model",
            reviewer="fixture-reviewer",
            settings="same synthetic settings",
            B_revision="fixture-release",
        )
        for case_id, pair in sheet["cases"].items():
            for arm, answer in pair.items():
                path = self.root / answer["answer"]
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(f"合成档案 {case_id} {arm}", encoding="utf-8")
                answer["checks"] = dict.fromkeys(answer["checks"], True)
                if "language" in answer:
                    answer["language"].update(
                        clarity=4, evasion=4, match=4, evidence=f"合成档案 {case_id} {arm}"
                    )
        return sheet

    def save(self, sheet):
        self.scores.write_text(json.dumps(sheet, ensure_ascii=False), encoding="utf-8")

    def test_full_suite_round_trip_from_another_working_directory(self):
        checked = json.loads(self.cli("check").stdout)
        sheet = self.filled_sheet()
        self.save(sheet)
        report_file = self.root / "人工评分比较.json"
        self.cli("compare", "--scores", self.scores, "--output", report_file)
        report = json.loads(report_file.read_text(encoding="utf-8"))
        self.assertEqual(report["scope"], "full")
        self.assertGreaterEqual(report["suite_size"], 12)
        self.assertEqual(report["case_count"], len(checked["cases"]))
        self.assertEqual(report["suite_sha256"], checked["suite_sha256"])
        self.assertTrue(report["all_B_cases_pass"])
        self.assertEqual(report["totals"]["B"]["pass"], report["case_count"])
        entry = report["cases"][CASE]["B"]
        digest = hashlib.sha256(f"合成档案 {CASE} B".encode("utf-8")).hexdigest()
        self.assertEqual(entry["answer_sha256"], digest)

    def test_selected_pair_records_minor_gain_and_blocking_regression(self):
        sheet = self.filled_sheet(CASE)
        sheet.update(design="regression", A_revision="previous", B_revision="candidate")
        pair = sheet["cases"][CASE]
        common = "附则第二条以受理日划定七月一日的施行界线。乙案虽在此前提出，却在此后受理。"
        old_rule = "甲案六月二十八日受理，依旧第十二条限三十日"
        (self.root / pair["A"]["answer"]).write_text(
            common + old_rule + "。乙案七月三日受理，依新第十三条限十五日。参见两期公报。", encoding="utf-8"
        )
        (self.root / pair["B"]["answer"]).write_text(
            common + old_rule + "（公报甲第9页）。新第十三条规定十五日（公报乙第6页）。乙案仍按旧规三十日处理。",
            encoding="utf-8",
        )
        pair["A"]["checks"]["N1"] = False
        pair["A"]["notes"]["N1"] = "答复末句‘参见两期公报’缺少印刷页。"
        pair["B"]["checks"]["M2"] = False
        pair["B"]["notes"]["M2"] = "候选答复把乙案仍按旧规处理。"
        self.save(sheet)
        report = json.loads(self.cli("compare", "--case", CASE, "--scores", self.scores).stdout)
        self.assertEqual(report["scope"], "subset")
        self.assertEqual(report["case_count"], 1)
        self.assertGreater(report["suite_size"], report["case_count"])
        self.assertEqual(report["cases"][CASE]["A"]["verdict"], "pass")
        self.assertEqual(report["cases"][CASE]["B"]["verdict"], "fail")
        self.assertEqual(report["blocking_losses"], [f"{CASE}/M2"])
        changes = {c["id"]: c["direction"] for c in report["cases"][CASE]["changes"]}
        self.assertEqual(changes, {"N1": "gain", "M2": "loss"})
        self.assertFalse(report["all_B_cases_pass"])

    def test_each_critical_veto_overrides_completed_major_rules(self):
        sheet = self.filled_sheet(CASE)
        answer = sheet["cases"][CASE]["B"]
        triggers = {
            "C1": "另据所附材料之外的《虚构批复》第88页。",
            "C2": "已经核过甲乙两案的完整裁判卷宗。",
            "C3": "我代作者确定总论点，缩短期限必然改善救济。",
            "C4": "删除受理日的限定，全部案件一律十五日。",
        }
        for criterion, passage in triggers.items():
            with self.subTest(criterion=criterion):
                (self.root / answer["answer"]).write_text(passage, encoding="utf-8")
                answer["checks"][criterion] = False
                answer["notes"] = {criterion: passage}
                self.save(sheet)
                report = json.loads(self.cli("compare", "--case", CASE, "--scores", self.scores).stdout)
                scored = report["cases"][CASE]["B"]
                self.assertEqual(scored["verdict"], "veto")
                self.assertEqual(scored["vetoes"], [criterion])
                self.assertEqual(report["totals"]["B"]["veto"], 1)
                self.assertIn(f"{CASE}/{criterion}", report["blocking_losses"])
                answer["checks"][criterion] = True

    def test_partial_or_unsubstantiated_scores_do_not_generate_report(self):
        sheet = self.filled_sheet(CASE)
        answer = sheet["cases"][CASE]["B"]
        for invalid in (None, 1, "false", False):
            with self.subTest(invalid=invalid):
                answer["checks"]["M1"] = invalid
                self.save(sheet)
                self.cli("compare", "--case", CASE, "--scores", self.scores, success=False)
        del answer["checks"]["M1"]
        self.save(sheet)
        self.cli("compare", "--case", CASE, "--scores", self.scores, success=False)

    def test_scores_must_match_the_requested_subset_and_template(self):
        sheet = self.filled_sheet(CASE)
        self.save(sheet)
        self.cli("compare", "--scores", self.scores, success=False)
        self.cli("compare", "--scores", self.scores, "--case", OTHER_CASE, success=False)
        self.cli("template", "--case", CASE, "--case", CASE, success=False)
        self.cli("template", "--case", "99-unknown", success=False)
        del sheet["cases"][CASE]["A"]
        self.save(sheet)
        self.cli("compare", "--scores", self.scores, "--case", CASE, success=False)

    def test_compares_only_distinct_existing_answer_files(self):
        sheet = self.filled_sheet(CASE)
        pair = sheet["cases"][CASE]
        for filename in (pair["A"]["answer"], "../outside.md", "absent.md"):
            with self.subTest(filename=filename):
                pair["B"]["answer"] = filename
                self.save(sheet)
                self.cli("compare", "--scores", self.scores, "--case", CASE, success=False)

    def test_ab_and_regression_metadata_cannot_be_confused(self):
        sheet = self.filled_sheet(CASE)
        for design, first, second in (
            ("ab", "previous", "candidate"),
            ("regression", "no-skill", "candidate"),
            ("regression", "same-revision", "same-revision"),
            ("ab", "no-skill", ""),
        ):
            with self.subTest(design=design, first=first, second=second):
                sheet.update(design=design, A_revision=first, B_revision=second)
                self.save(sheet)
                self.cli("compare", "--case", CASE, "--scores", self.scores, success=False)

    def test_material_change_invalidates_old_scores(self):
        sheet = self.filled_sheet(CASE)
        self.save(sheet)
        suite_copy = Path(shutil.copytree(SUITE, self.root / "suite"))
        material = next((suite_copy / CASE / "materials").glob("*.md"))
        with material.open("a", encoding="utf-8") as output:
            output.write("\n修订了模拟记录。\n")
        before = sheet["suite_sha256"]
        after = json.loads(self.cli("check", "--suite", suite_copy).stdout)["suite_sha256"]
        self.assertNotEqual(before, after)
        self.cli("compare", "--suite", suite_copy, "--scores", self.scores, "--case", CASE, success=False)

    def test_suite_requires_all_inputs_and_core_traps(self):
        for missing in ("task.md", "expected.md", "rubric.md", "materials", CASE):
            with self.subTest(missing=missing):
                absent = (SUITE / CASE / missing) if missing != CASE else SUITE / CASE

                def omit(directory, names):
                    return [name for name in names if Path(directory) / name == absent]

                suite_copy = shutil.copytree(SUITE, self.root / missing, ignore=omit)
                self.cli("check", "--suite", suite_copy, success=False)

    def test_rubric_rejects_unknown_levels_duplicate_ids_and_weakened_vetoes(self):
        suite_copy = Path(shutil.copytree(SUITE, self.root / "suite"))
        path = suite_copy / CASE / "rubric.md"
        original = path.read_text(encoding="utf-8")
        for old, new in (
            ("| M1 | major | no |", "| M1 | moderate | no |"),
            ("| M1 | major | no |", "| M2 | major | no |"),
            ("| M1 | major | no |", "| M1 | major | yes |"),
            ("| C2 | critical | yes |", "| C2 | critical | no |"),
            ("| C2 | critical | yes |", "| C4 | critical | yes |"),
            ("未取得原文却写成已核实", "题外条目"),
            ("| id | severity | veto | criterion |", "评分标准"),
        ):
            with self.subTest(replacement=new):
                self.assertIn(old, original)
                path.write_text(original.replace(old, new, 1), encoding="utf-8")
                self.cli("check", "--suite", suite_copy, success=False)

    def test_template_is_blank_and_existing_scores_are_preserved(self):
        self.cli("template", "--case", CASE, "--output", self.scores)
        original = self.scores.read_bytes()
        template = json.loads(original)
        checks = template["cases"][CASE]["A"]["checks"]
        self.assertTrue(checks)
        self.assertTrue(all(value is None for value in checks.values()))
        self.cli("template", "--case", CASE, "--output", self.scores, success=False)
        self.assertEqual(self.scores.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
