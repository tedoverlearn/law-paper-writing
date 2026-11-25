"""Test the language regression gate with synthetic scores, independent of model outputs."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import run_behavioral as runner


class LanguageComparisonTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        suite, cls.digest = runner.read_suite(runner.SUITE)
        cls.cases = {case: suite[case] for case in runner.LANGUAGE_CASES}

    def setUp(self):
        scratch = TemporaryDirectory(prefix="language-test-", dir=Path(__file__).resolve().parent)
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name)
        self.sheet = runner.score_sheet(self.cases, self.digest)
        self.sheet.update(
            design="regression", A_revision="old", B_revision="new",
            model="test model", settings="identical", reviewer="test reviewer",
            blind_review="test blind record",
        )
        (self.root / "answers").mkdir()
        for pair in self.sheet["cases"].values():
            for answer in pair.values():
                (self.root / answer["answer"]).write_text("合成测试段落。\n", encoding="utf-8")
                answer["checks"] = dict.fromkeys(answer["checks"], True)
                answer["language"].update(clarity=3, evasion=3, match=3, evidence="测试段落首句")

    def language(self, case, arm="B"):
        return self.sheet["cases"][case][arm]["language"]

    def report(self):
        return runner.compare(self.sheet, self.cases, self.digest, self.root)

    def test_language_can_improve_with_tied_evidence_match(self):
        w1, w2 = runner.LANGUAGE_CASES
        self.language(w1)["clarity"] = 4
        self.language(w2)["evasion"] = 2
        comparison = self.report()["language_comparison"]
        self.assertEqual(comparison["status"], "improved")
        self.assertEqual(comparison["total_delta"], {"clarity": 1, "evasion": -1, "match": 0})
        self.assertEqual(comparison["adverse_pairs"], [])

    def test_each_adverse_pair_blocks_even_when_total_improves(self):
        w1, w2 = runner.LANGUAGE_CASES
        self.language(w1).update(clarity=5, evasion=1, match=5)
        for metric, value in (("clarity", 2), ("evasion", 4), ("match", 2)):
            with self.subTest(metric=metric):
                self.language(w2)[metric] = value
                comparison = self.report()["language_comparison"]
                self.assertEqual(comparison["status"], "blocked")
                self.assertEqual(comparison["adverse_pairs"], [
                    {"case": w2, "metric": metric, "delta": value - 3},
                ])
                self.language(w2)[metric] = 3

    def test_ties_or_only_one_required_gain_do_not_establish_improvement(self):
        w1 = runner.LANGUAGE_CASES[0]
        for changes in ({}, {"clarity": 4}, {"evasion": 2}):
            with self.subTest(changes=changes):
                self.language(w1).update(clarity=3, evasion=3, match=3)
                self.language(w1).update(changes)
                self.assertEqual(self.report()["language_comparison"]["status"],
                                 "no_demonstrated_improvement")

    def test_overstatement_veto_blocks_high_language_ratings(self):
        w1, w2 = runner.LANGUAGE_CASES
        self.language(w1).update(clarity=5, evasion=1, match=5)
        self.language(w2).update(clarity=5, evasion=1, match=5)
        answer = self.sheet["cases"][w2]["B"]
        answer["checks"]["C4"] = False
        answer["notes"]["C4"] = "合成判分例漏掉日班。"
        report = self.report()
        self.assertEqual(report["cases"][w2]["B"]["verdict"], "veto")
        self.assertEqual(report["language_comparison"]["status"], "blocked")
        self.assertEqual(report["language_comparison"]["failed_candidate_cases"], [w2])

    def test_unblinded_ab_scores_do_not_establish_version_regression_result(self):
        self.sheet.update(design="ab", A_revision="no-skill", blind_review="")
        self.assertEqual(self.report()["language_comparison"]["status"], "ineligible")

    def test_one_language_case_cannot_validate_the_pair(self):
        w1, w2 = runner.LANGUAGE_CASES
        del self.sheet["cases"][w2]
        report = runner.compare(self.sheet, {w1: self.cases[w1]}, self.digest, self.root)
        self.assertEqual(report["language_comparison"]["status"], "incomplete")
        self.assertEqual(report["language_comparison"]["missing_cases"], [w2])

    def test_regression_requires_blind_review_record(self):
        self.sheet["blind_review"] = ""
        with self.assertRaisesRegex(ValueError, "blind_review"):
            self.report()

    def test_requires_three_integer_ratings_and_passage_evidence(self):
        scores = self.language(runner.LANGUAGE_CASES[0])
        for key, value in (
            ("clarity", None), ("evasion", True), ("match", 0), ("match", 6),
            ("clarity", 3.0), ("evidence", " "),
        ):
            with self.subTest(key=key, value=value):
                original = scores[key]
                scores[key] = value
                with self.assertRaisesRegex(ValueError, key):
                    self.report()
                scores[key] = original


if __name__ == "__main__":
    unittest.main()
