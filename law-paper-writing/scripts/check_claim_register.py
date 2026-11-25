"""Check claim dependencies and compare a TSV register with manuscript markers."""

import argparse
from collections import defaultdict, deque
import csv
from dataclasses import dataclass
import json
from pathlib import Path
import re
import sys


COLUMNS = ("id", "claim", "location", "depends_on", "sources", "decision")
CLAIM_ID = re.compile(r"C[0-9]+")
CLAIM_MARKER = re.compile(r"(?<![A-Za-z0-9_])" + CLAIM_ID.pattern + r"(?![A-Za-z0-9_])")
MARKDOWN_NOTE = re.compile(r"^\s*\[\^[^\]\n]+\]:")
SOURCE_ID = re.compile(r"S[0-9]+")
DECISIONS = {"confirmed", "provisional", "withdrawn"}


@dataclass(frozen=True)
class Claim:
    id: str
    claim: str
    location: str
    depends_on: tuple[str, ...]
    sources: tuple[str, ...]
    decision: str


def load_register(path: Path) -> dict[str, Claim]:
    claims: dict[str, Claim] = {}
    with path.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.reader(file, delimiter="\t", strict=True)
        if next(reader, None) != list(COLUMNS):
            raise ValueError("expected columns: " + ", ".join(COLUMNS))
        for row in reader:
            if not row:
                continue
            context = f"line {reader.line_num}"
            if len(row) != len(COLUMNS):
                raise ValueError(f"{context}: expected {len(COLUMNS)} columns")
            identifier, claim, location, parents, refs, decision = (
                field.strip() for field in row
            )
            if not CLAIM_ID.fullmatch(identifier) or identifier in claims:
                raise ValueError(f"{context}: invalid or duplicate claim ID {identifier!r}")
            if not claim or not location or decision not in DECISIONS:
                raise ValueError(f"{context}: supply a claim, location, and valid decision")
            dependencies = tuple(part.strip() for part in parents.split(",")) if parents else ()
            references = tuple(part.strip() for part in refs.split("|")) if refs else ()
            if len(set(dependencies)) != len(dependencies):
                raise ValueError(f"{context}: duplicate dependency")
            for ref in references:
                source_id, _, anchor = ref.partition("@")
                if not SOURCE_ID.fullmatch(source_id) or not anchor.strip():
                    raise ValueError(f"{context}: expected a source ID and location (S01@...)")
            claims[identifier] = Claim(identifier, claim, location, dependencies, references, decision)
    return claims


def reverse_dependencies(claims: dict[str, Claim]) -> dict[str, list[str]]:
    children: dict[str, list[str]] = defaultdict(list)
    incoming: dict[str, int] = {}
    for record in claims.values():
        missing = [parent for parent in record.depends_on if parent not in claims]
        if missing:
            raise ValueError(f"{record.id}: missing dependencies {', '.join(missing)}")
        incoming[record.id] = len(record.depends_on)
        for parent in record.depends_on:
            children[parent].append(record.id)

    ready = deque(key for key in claims if incoming[key] == 0)
    count = 0
    while ready:
        parent = ready.popleft()
        count += 1
        for child in children[parent]:
            incoming[child] -= 1
            if incoming[child] == 0:
                ready.append(child)
    if count != len(claims):
        unresolved = ", ".join(key for key in claims if incoming[key])
        raise ValueError(f"circular dependency; unresolved claims: {unresolved}")
    return children


def downstream(seeds: list[str], children: dict[str, list[str]]) -> dict[str, str | None]:
    via: dict[str, str | None] = dict.fromkeys(seeds)
    queue = deque(seeds)
    while queue:
        parent = queue.popleft()
        for child in children.get(parent, ()):
            if child not in via:
                via[child] = parent
                queue.append(child)
    return via


def check_coverage(path: Path, claims: dict[str, Claim]) -> dict:
    # Use the same manuscript sections as the draft checker.
    from check_manuscript import PROSE, manuscript_lines

    if path.suffix.lower() not in {".md", ".txt"}:
        raise ValueError("coverage requires a UTF-8 .md or .txt manuscript")
    source = path.read_text(encoding="utf-8-sig")
    markers = defaultdict(list)
    inside_note = False
    for line in manuscript_lines(source):
        if MARKDOWN_NOTE.match(line.text):
            inside_note = True
            continue
        if inside_note and (not line.text.strip() or line.text.startswith(("    ", "\t"))):
            continue
        inside_note = False
        if line.section in PROSE:
            for marker in CLAIM_MARKER.finditer(line.text):
                markers[marker.group()].append({
                    "line": line.number, "column": line.column + marker.start(),
                })
    return {
        "scope": "claim_coverage",
        "manuscript": path.as_posix(),
        "entries": len(claims),
        "marked_claims": len(markers),
        "markers_missing_from_register": [
            {"id": key, "occurrences": markers[key]} for key in sorted(markers.keys() - claims.keys())
        ],
        "claims_missing_from_manuscript": [
            {"id": key, "location": claims[key].location, "decision": claims[key].decision}
            for key in sorted(claims.keys() - markers.keys())
        ],
    }


def print_coverage(report, as_json):
    if as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return
    print(f"稿件 {report['manuscript']} | 主张表 {report['entries']} 条 | 正文标记 {report['marked_claims']} 个")
    unregistered = report["markers_missing_from_register"]
    print(f"正文有标记但主张表未登记 | {len(unregistered)} 条")
    for record in unregistered:
        positions = "、".join(
            f"第 {item['line']} 行第 {item['column']} 列" for item in record["occurrences"]
        )
        print(f"{record['id']}\t{positions}")
    missing = report["claims_missing_from_manuscript"]
    print(f"表内已登记但正文未出现 | {len(missing)} 条")
    for record in missing:
        print(f"{record['id']}\t{record['location']}\t{record['decision']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("register", type=Path)
    selector = parser.add_mutually_exclusive_group()
    selector.add_argument("--claim", help="claim ID with a changed judgment")
    selector.add_argument("--source", help="source ID with a changed text or version")
    selector.add_argument("--check-coverage", metavar="MANUSCRIPT", type=Path,
                          help="compare marked claims in a UTF-8 Markdown or text manuscript")
    parser.add_argument("--json", action="store_true", help="emit a UTF-8 JSON report")
    args = parser.parse_args()
    try:
        claims = load_register(args.register)
        if args.check_coverage:
            report = check_coverage(args.check_coverage, claims)
        else:
            children = reverse_dependencies(claims)
        if args.claim and args.claim not in claims:
            raise ValueError(f"unknown claim ID: {args.claim}")
        if args.source and not SOURCE_ID.fullmatch(args.source):
            raise ValueError(f"invalid source ID: {args.source}")
    except (OSError, UnicodeError, csv.Error, ValueError) as error:
        parser.exit(2, f"{parser.prog}: {error}\n")

    if args.check_coverage:
        print_coverage(report, args.json)
        return int(bool(report["markers_missing_from_register"] or report["claims_missing_from_manuscript"]))

    seeds = (
        [args.claim] if args.claim else
        [record.id for record in claims.values()
         if any(ref.partition("@")[0] == args.source for ref in record.sources)]
    )
    affected = downstream(seeds, children)
    withdrawn = [record.id for record in claims.values() if record.decision == "withdrawn"]
    review = downstream(withdrawn, children)
    needs_review = [key for key in review if claims[key].decision != "withdrawn"]
    if args.json:
        print(json.dumps({
            "entries": len(claims),
            "scope": "claim_register",
            "query": args.claim or args.source,
            "affected": [
                {"id": key, "via": parent, "location": claims[key].location,
                 "decision": claims[key].decision}
                for key, parent in affected.items()
            ],
            "depends_on_withdrawn_claim": needs_review,
        }, ensure_ascii=False, indent=2))
    else:
        print(f"查询范围为主张表中的 {len(claims)} 条记录。")
        for key, parent in affected.items():
            relation = f"经 {parent} 关联" if parent else "直接关联"
            print(f"{key}\t{relation}\t{claims[key].location}\t{claims[key].decision}")
        if (args.claim or args.source) and not affected:
            print("主张表未登记与该来源关联的判断。")
        if needs_review:
            print("依赖已撤回判断，待复查：" + "、".join(needs_review))
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
