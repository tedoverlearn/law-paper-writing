#!/usr/bin/env python3
"""Check the runtime files and optionally package them for a local installation."""

import argparse
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import posixpath
import re
import stat
from urllib.parse import unquote, urlsplit
from zipfile import ZIP_STORED, ZipFile, ZipInfo


SKILL_NAME = "law-paper-writing"
RUNTIME_FILES = (
    "SKILL.md",
    "agents/openai.yaml",
    "assets/claim-register.tsv",
    "assets/project-record.md",
    "assets/source-card.md",
    "references/argument-and-review.md",
    "references/behavioral-evaluation.md",
    "references/citation-profiles.md",
    "references/claims-and-qualifications.md",
    "references/doctrinal-civil.md",
    "references/evidence-maintenance.md",
    "references/institutional-history.md",
    "references/long-form-revision.md",
    "references/methods.md",
    "references/publication.md",
    "references/qualitative-and-mixed-methods.md",
    "references/research-contribution.md",
    "references/sources-and-citations.md",
    "references/text-and-history.md",
    "references/theory-and-normative-argument.md",
    "references/workflow.md",
    "references/writing-workshop.md",
    "scripts/audit_docx_footnotes.py",
    "scripts/check_claim_register.py",
    "scripts/check_manuscript.py",
)
LINK_DESTINATION = r"(?:<([^>]+)>|([^\s()]+))"
INLINE_LINK = re.compile(r"\]\(\s*" + LINK_DESTINATION)
REFERENCE_LINK = re.compile(r" {0,3}\[[^\]]+\]:\s*" + LINK_DESTINATION)


def checked_file(root, name):
    path = root
    parts = name.split("/")
    for index, part in enumerate(parts):
        path /= part
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or (
            getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
        ):
            raise ValueError(f"symlink or reparse point in runtime path: {name}")
        expected = stat.S_ISREG if index == len(parts) - 1 else stat.S_ISDIR
        if not expected(info.st_mode):
            raise ValueError(f"unexpected file type in runtime path: {name}")
    return path


def load_runtime(root):
    files = {}
    for name in RUNTIME_FILES:
        # All items are authored text. Normalize line endings for portable archives.
        files[name] = checked_file(root, name).read_text(encoding="utf-8")
    return files


def check_project_metadata(files):
    _, start, after_open = files["SKILL.md"].partition("---\n")
    header, end, body = after_open.partition("\n---\n")
    if not start or not end or not body.strip() or not files["SKILL.md"].startswith("---\n"):
        raise ValueError("SKILL.md must start with front matter and include a body")

    # The project writes these fields as one-line scalars. The host's validator
    # handles the general YAML schema and other front-matter keys.
    def field(name, indent=""):
        matches = re.findall(rf"^{indent}{name}:[ \t]*(.+)$", header, re.MULTILINE)
        if len(matches) != 1:
            raise ValueError(f"SKILL.md must include one {name} field")
        return matches[0].strip()

    if field("name") != SKILL_NAME:
        raise ValueError(f"SKILL.md name must match the package directory {SKILL_NAME}")
    description = field("description").strip("\"'")
    if not description.strip() or description in {"|", ">"} or len(description) > 1024:
        raise ValueError("SKILL.md requires a one-line description of 1–1024 characters")
    version = field("version", "  ").strip("\"'")
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("metadata.version must use major.minor.patch format")
    if "$" + SKILL_NAME not in files["agents/openai.yaml"]:
        raise ValueError("agents/openai.yaml must use the shipped Skill name")
    return version


def check_markdown_links(files):
    errors = []
    for source, content in files.items():
        if not source.endswith(".md"):
            continue
        fence = None
        for number, line in enumerate(content.splitlines(), 1):
            marker = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
            if marker:
                delimiter, suffix = marker.groups()
                if fence is None:
                    fence = delimiter
                elif delimiter[0] == fence[0] and len(delimiter) >= len(fence) and not suffix.strip():
                    fence = None
                continue
            if fence:
                continue
            matches = list(INLINE_LINK.finditer(line))
            reference = REFERENCE_LINK.match(line)
            if reference:
                matches.append(reference)
            for match in matches:
                destination = match.group(1) or match.group(2)
                parts = urlsplit(destination)
                if parts.scheme.lower() in {"http", "https", "mailto"}:
                    continue
                path = unquote(parts.path)
                if parts.scheme or parts.netloc or path.startswith("/") or "\\" in path or ":" in path:
                    errors.append(f"{source}:{number}: unsupported local path {destination}")
                    continue
                if not path:
                    continue  # A same-file fragment requires no additional packaged file.
                target = posixpath.normpath(posixpath.join(posixpath.dirname(source), path))
                if target not in files:
                    errors.append(f"{source}:{number}: link target is missing from the package: {destination}")
    if errors:
        raise ValueError("\n".join(errors))


def make_archive(files):
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_STORED) as archive:
        for name in sorted(files):
            info = ZipInfo(f"{SKILL_NAME}/{name}", date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            archive.writestr(info, files[name].encode("utf-8"))
    return output.getvalue()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="validate the runtime files without writing")
    mode.add_argument("--output", type=Path, metavar="ZIP", help="write a new ZIP after validation")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    try:
        files = load_runtime(root)
        version = check_project_metadata(files)
        check_markdown_links(files)
        if args.output is not None:
            if args.output.suffix.lower() != ".zip":
                raise ValueError("the output filename must end in .zip")
            payload = make_archive(files)
            with args.output.open("xb") as output:
                output.write(payload)
            print(f"SHA-256: {sha256(payload).hexdigest()}")
        print(f"{SKILL_NAME} {version}: {len(files)} runtime files checked")
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Release check failed: {exc}\n")


if __name__ == "__main__":
    main()
