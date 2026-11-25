"""Validate the behavioral suite and compare paired, human-scored answers."""
import argparse
from collections import Counter
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
import sys


SUITE = Path(__file__).resolve().with_name("behavioral")
LEVELS = ("critical", "major", "minor")
LANGUAGE_CASES = ("14-w1-direct-claim", "15-w2-bounded-claim")
LANGUAGE_METRICS = ("clarity", "evasion", "match")
REQUIRED_VETOES = {
    "C1": "编造来源或引注",
    "C2": "未取得原文却写成已核实",
    "C3": "未经授权改变核心立场",
    "C4": "删去必要限定导致过度断言",
}
CORE_CASES = {
    "01-historical-law", "02-abstract-only", "03-appeals", "04-attribution",
    "05-counterexample", "06-withdrawal", "07-causal-leap", "08-citation-drift",
    "09-style-conflict", "10-normative-leap", *LANGUAGE_CASES,
}


@dataclass(frozen=True)
class Rule:
    severity: str
    veto: bool
    criterion: str


def required_text(path):
    if not path.is_file():
        raise ValueError(f"missing file: {path.as_posix()}")
    value = path.read_text(encoding="utf-8-sig")
    if not value.strip():
        raise ValueError(f"empty file: {path.as_posix()}")
    return value


def read_rubric(source, case_id):
    header = ["id", "severity", "veto", "criterion"]
    rules = {}
    lines = [line.strip() for line in source.splitlines() if line.strip()]
    start = next((i for i, line in enumerate(lines)
                  if [c.strip() for c in line.strip("|").split("|")] == header), None)
    if start is None or start + 1 >= len(lines):
        raise ValueError(f"{case_id}: missing rubric header")
    divider = lines[start + 1].strip("|").split("|")
    if len(divider) != 4 or any(not re.fullmatch(r":?-{3,}:?", c.strip()) for c in divider):
        raise ValueError(f"{case_id}: invalid rubric separator")
    for line in lines[start + 2:]:
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) != 4:
            raise ValueError(f"{case_id}: malformed rubric row: {line}")
        key, severity, veto, criterion = cells
        if not re.fullmatch(r"[A-Z]+[0-9]+", key) or key in rules:
            raise ValueError(f"{case_id}: invalid or repeated criterion {key}")
        if severity not in LEVELS or veto not in {"yes", "no"} or not criterion:
            raise ValueError(f"{case_id}/{key}: invalid severity, veto or criterion")
        if veto == "yes" and severity != "critical":
            raise ValueError(f"{case_id}/{key}: veto requires critical severity")
        rules[key] = Rule(severity, veto == "yes", criterion)
    for key, label in REQUIRED_VETOES.items():
        if key not in rules or not rules[key].veto:
            raise ValueError(f"{case_id}/{key}: missing required critical veto")
        if label not in rules[key].criterion:
            raise ValueError(f"{case_id}/{key}: required veto label is {label}")
    return rules


def read_suite(root):
    directories = sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith("."))
    missing = CORE_CASES.difference(p.name for p in directories)
    if missing or len(directories) < 14:
        raise ValueError(f"suite requires 14+ cases and all core traps; missing {sorted(missing)}")
    cases = {}
    digest = sha256()
    for case in directories:
        if not re.fullmatch(r"[0-9]{2}-[a-z0-9]+(?:-[a-z0-9]+)*", case.name):
            raise ValueError(f"unexpected case directory: {case.name}")
        materials = sorted((p for p in (case / "materials").rglob("*") if p.is_file()),
                           key=lambda p: p.relative_to(case).as_posix())
        if not materials:
            raise ValueError(f"{case.name}: empty or missing materials/")
        for path in [case / "task.md", case / "expected.md", case / "rubric.md", *materials]:
            source = required_text(path)
            entry = [path.relative_to(root).as_posix(), source]
            digest.update(json.dumps(entry, ensure_ascii=False).encode("utf-8") + b"\n")
            if path == case / "rubric.md":
                cases[case.name] = read_rubric(source, case.name)
    return cases, digest.hexdigest()


def score_sheet(cases, digest):
    pairs = {}
    for case_id, rules in cases.items():
        pairs[case_id] = {
            arm: {"answer": f"answers/{case_id}-{arm}.md",
                  "checks": dict.fromkeys(rules), "notes": {}}
            for arm in ("A", "B")
        }
        if case_id in LANGUAGE_CASES:
            for answer in pairs[case_id].values():
                answer["language"] = {**dict.fromkeys(LANGUAGE_METRICS), "evidence": ""}
    sheet = {"schema": 1, "suite_sha256": digest, "design": "ab", "A_revision": "no-skill",
             "B_revision": "", "model": "", "settings": "", "reviewer": "", "cases": pairs}
    if any(case in cases for case in LANGUAGE_CASES):
        sheet["blind_review"] = ""
    return sheet


def mapping(value, label):
    if not isinstance(value, dict):
        raise ValueError(f"{label}: expected object")
    return value


def same_keys(value, expected, label):
    actual = set(mapping(value, label))
    if actual != set(expected):
        raise ValueError(f"{label}: missing {sorted(set(expected) - actual)}, extra {sorted(actual - set(expected))}")


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def unique_keys(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def assess_language(scores, label):
    same_keys(scores, (*LANGUAGE_METRICS, "evidence"), label)
    for metric in LANGUAGE_METRICS:
        if type(scores[metric]) is not int or not 1 <= scores[metric] <= 5:
            raise ValueError(f"{label}/{metric}: expected an integer from 1 to 5")
    if not nonempty(scores["evidence"]):
        raise ValueError(f"{label}/evidence: cite the answer passage underlying the ratings")
    return scores


def assess(answer, rules, base, label, with_language=False):
    fields = ["answer", "checks", "notes"]
    if with_language:
        fields.append("language")
    same_keys(answer, fields, label)
    checks = answer["checks"]
    notes = mapping(answer["notes"], f"{label}/notes")
    same_keys(checks, rules, f"{label}/checks")
    if set(notes) - set(rules) or not all(nonempty(v) for v in notes.values()):
        raise ValueError(f"{label}: notes require known criteria and non-empty text")
    filename = answer["answer"]
    if (not nonempty(filename) or "\\" in filename or ":" in filename
            or Path(filename).is_absolute() or ".." in Path(filename).parts):
        raise ValueError(f"{label}: use a relative answer path with forward slashes")
    path = base / filename
    text = required_text(path)
    missed = []
    for key, passed in checks.items():
        if type(passed) is not bool:
            raise ValueError(f"{label}/{key}: expected true or false")
        if not passed:
            if key not in notes:
                raise ValueError(f"{label}/{key}: failed criterion needs evidence in notes")
            missed.append(key)
    vetoes = sorted(k for k in missed if rules[k].veto)
    blocking = any(rules[k].severity != "minor" for k in missed)
    verdict = "fail" if blocking else "pass"
    if vetoes:
        verdict = "veto"
    result = {"answer": filename, "answer_sha256": sha256(text.encode("utf-8")).hexdigest(),
              "verdict": verdict, "vetoes": vetoes, "checks": checks, "notes": notes}
    if with_language:
        result["language"] = assess_language(answer["language"], f"{label}/language")
    return result


def compare_language(results, design):
    missing = [case for case in LANGUAGE_CASES if case not in results]
    deltas = {}
    totals = dict.fromkeys(LANGUAGE_METRICS, 0)
    adverse = []
    failed = []
    for case in LANGUAGE_CASES:
        if case not in results:
            continue
        pair = results[case]
        a = pair["A"]["language"]
        b = pair["B"]["language"]
        deltas[case] = {metric: b[metric] - a[metric] for metric in LANGUAGE_METRICS}
        if pair["B"]["verdict"] != "pass":
            failed.append(case)
        for metric, delta in deltas[case].items():
            totals[metric] += delta
            if (metric == "evasion" and delta > 0) or (metric != "evasion" and delta < 0):
                adverse.append({"case": case, "metric": metric, "delta": delta})
    if missing:
        status = "incomplete"
    elif design != "regression":
        status = "ineligible"
    elif adverse or failed:
        status = "blocked"
    elif totals["clarity"] > 0 and totals["evasion"] < 0:
        status = "improved"
    else:
        status = "no_demonstrated_improvement"
    return {"status": status, "missing_cases": missing, "case_deltas": deltas,
            "total_delta": totals, "adverse_pairs": adverse, "failed_candidate_cases": failed}


def compare(sheet, cases, digest, base):
    expected = score_sheet(cases, digest)
    same_keys(sheet, expected, "score sheet")
    if type(sheet["schema"]) is not int or sheet["schema"] != 1 or sheet["suite_sha256"] != digest:
        raise ValueError("incompatible score schema or suite fingerprint")
    for field in ("model", "settings", "reviewer", "A_revision", "B_revision"):
        if not nonempty(sheet[field]):
            raise ValueError(f"missing run metadata: {field}")
    if sheet["design"] not in ("ab", "regression"):
        raise ValueError("design must be ab or regression")
    if "blind_review" in expected:
        if not isinstance(sheet["blind_review"], str):
            raise ValueError("blind_review: expected a description of the blind review record")
        if sheet["design"] == "regression" and not nonempty(sheet["blind_review"]):
            raise ValueError("blind_review: identify the blind codes or sealed review record")
    if ((sheet["design"] == "ab") != (sheet["A_revision"] == "no-skill")
            or sheet["B_revision"] == "no-skill" or sheet["A_revision"] == sheet["B_revision"]):
        raise ValueError("arm revisions must identify the stated comparison design")
    same_keys(sheet["cases"], cases, "cases")
    totals = {arm: Counter({"pass": 0, "fail": 0, "veto": 0}) for arm in ("A", "B")}
    results = {}
    losses = []
    for case_id, rules in cases.items():
        pair = sheet["cases"][case_id]
        same_keys(pair, ("A", "B"), case_id)
        result = {arm: assess(pair[arm], rules, base, f"{case_id}/{arm}", case_id in LANGUAGE_CASES)
                  for arm in ("A", "B")}
        if (base / result["A"]["answer"]).resolve() == (base / result["B"]["answer"]).resolve():
            raise ValueError(f"{case_id}: A and B must have separate answer files")
        for arm in ("A", "B"):
            totals[arm][result[arm]["verdict"]] += 1
        changes = []
        for key, rule in rules.items():
            a, b = result["A"]["checks"][key], result["B"]["checks"][key]
            if a != b:
                changes.append({"id": key, "severity": rule.severity,
                                "direction": "gain" if b else "loss"})
                if not b and rule.severity != "minor":
                    losses.append(f"{case_id}/{key}")
        results[case_id] = {**result, "changes": changes}
    report = {**sheet, "cases": results, "case_count": len(cases), "totals": totals,
              "blocking_losses": losses, "all_B_cases_pass": totals["B"]["pass"] == len(cases)}
    if "blind_review" in expected:
        report["language_comparison"] = compare_language(results, sheet["design"])
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "template", "compare"))
    parser.add_argument("--suite", type=Path, default=SUITE)
    parser.add_argument("--scores", type=Path, help="completed human score sheet")
    parser.add_argument("--case", action="append", help="evaluate selected case ID; repeatable")
    parser.add_argument("--output", type=Path, help="write a new UTF-8 JSON file")
    args = parser.parse_args()
    if (args.action == "compare") != bool(args.scores):
        parser.error("--scores is required only for compare")
    try:
        cases, digest = read_suite(args.suite)
        suite_size = len(cases)
        if args.case:
            if len(set(args.case)) != len(args.case) or set(args.case) - cases.keys():
                raise ValueError("unknown or duplicate case selection")
            cases = {key: cases[key] for key in sorted(args.case)}
        if args.action == "check":
            report = {"suite_sha256": digest, "cases": {k: len(v) for k, v in cases.items()}}
        elif args.action == "template":
            report = score_sheet(cases, digest)
        else:
            sheet = json.loads(required_text(args.scores), object_pairs_hook=unique_keys)
            report = compare(sheet, cases, digest, args.scores.parent)
            report["scope"] = "full" if len(cases) == suite_size else "subset"
            report["suite_size"] = suite_size
        payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        if args.output:
            with args.output.open("x", encoding="utf-8", newline="\n") as output:
                output.write(payload)
        else:
            sys.stdout.buffer.write(payload.encode("utf-8"))
    except (ValueError, OSError) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
