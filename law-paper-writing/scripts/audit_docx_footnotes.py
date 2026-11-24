#!/usr/bin/env python3
"""Report raw XML footnote-reference issues in a Word DOCX without changing it."""

import argparse
from collections import defaultdict
import json
from pathlib import Path
import posixpath
import re
from string import ascii_lowercase, ascii_uppercase
import sys
from urllib.parse import urlsplit
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile
from zlib import error as DeflateError


REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"
CONTENT_TYPES = "{http://schemas.openxmlformats.org/package/2006/content-types}"
WORD_MIME_PREFIX = "application/vnd.openxmlformats-officedocument.wordprocessingml."
REL_PREFIXES = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/",
    "http://purl.oclc.org/ooxml/officeDocument/relationships/",
)
WORD_NAMESPACES = (
    "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}",
    "{http://purl.oclc.org/ooxml/wordprocessingml/main}",
)
SPECIAL_TYPES = {"separator", "continuationSeparator", "continuationNotice"}
MARKUP_COMPATIBILITY = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"
ALTERNATE_CONTENT = MARKUP_COMPATIBILITY + "AlternateContent"
ASCII_LOWER = str.maketrans(ascii_uppercase, ascii_lowercase)
MAX_PART_SIZE = 64 * 1024 * 1024


def part_present(names, part):
    key = part.translate(ASCII_LOWER)
    for suffix in ("/[0].piece", "/[0].last.piece"):
        if key + suffix in names:
            raise ValueError(f"Interleaved XML part requires a compatible OPC reader: {part}")
    return key in names


def read_part(package, names, part):
    part_present(names, part)
    matches = names.get(part.translate(ASCII_LOWER), [])
    if len(matches) != 1:
        raise ValueError(f"Expected one ZIP entry for {part}, found {len(matches)}")
    entry = matches[0]
    if entry.file_size > MAX_PART_SIZE:
        raise ValueError(f"XML part exceeds the 64 MiB audit limit: {part}")
    return ET.fromstring(package.read(entry))


def validate_part_type(content_types, part, expected):
    path = "/" + part.translate(ASCII_LOWER)
    overrides = [entry.get("ContentType") for entry in content_types.findall(CONTENT_TYPES + "Override")
                 if entry.get("PartName", "").translate(ASCII_LOWER) == path]
    _, separator, suffix = posixpath.basename(part).rpartition(".")
    extension = suffix.translate(ASCII_LOWER) if separator else ""
    defaults = [entry.get("ContentType") for entry in content_types.findall(CONTENT_TYPES + "Default")
                if entry.get("Extension", "").translate(ASCII_LOWER) == extension]
    declared = overrides or defaults
    if len(declared) != 1 or (declared[0] or "").translate(ASCII_LOWER) != expected:
        raise ValueError(f"Missing, ambiguous or unexpected content type for {part}")


def relationship_target(package, names, source, kind, required=False):
    folder, base = posixpath.split(source)
    relationships_part = posixpath.join(folder, "_rels", base + ".rels")
    if not part_present(names, relationships_part) and not required:
        return None
    root = read_part(package, names, relationships_part)
    if root.tag != REL + "Relationships":
        raise ValueError(f"Unrecognized relationships XML in {relationships_part}")
    for node in root.iter():
        if node.tag == ALTERNATE_CONTENT or MARKUP_COMPATIBILITY + "ProcessContent" in node.attrib:
            raise ValueError(f"Relationship markup compatibility requires separate review: {relationships_part}")
    types = {prefix + kind for prefix in REL_PREFIXES}
    matches = [relationship for relationship in root.findall(REL + "Relationship")
               if relationship.get("Type") in types]
    if len(matches) == 0 and not required:
        return None
    if len(matches) != 1:
        raise ValueError(f"Expected one {kind} relationship in {relationships_part}, found {len(matches)}")

    relationship = matches[0]
    raw_target = relationship.get("Target", "")
    target = urlsplit(raw_target)
    if (relationship.get("TargetMode", "Internal") != "Internal" or
            target.scheme or target.netloc or target.query or target.fragment or
            not target.path or "\\" in raw_target or re.search(r"\s|[\x00-\x1f\x7f]", raw_target)):
        raise ValueError(f"Unsupported {kind} relationship target in {relationships_part}")
    # Match the encoded OPC part name in the ZIP. Decoding escaped octets would
    # change the name, and escaped slashes must not become path delimiters.
    if re.search(r"%(?![0-9A-Fa-f]{2})|%(?:2[fF]|5[cC])", target.path):
        raise ValueError(f"Unsupported percent escape in {kind} relationship target in {relationships_part}")
    relative_path = target.path.lstrip("/") if target.path.startswith("/") else posixpath.join(folder, target.path)
    part = posixpath.normpath(relative_path)
    if part in {".", ".."} or part.startswith("../"):
        raise ValueError(f"Relationship target escapes the package root in {relationships_part}")
    return part


def note_id(element, namespace):
    value = element.get(namespace + "id", "").strip()
    if re.fullmatch(r"[+-]?[0-9]+", value):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def has_wrapped_note(root, note_tag, word_namespace):
    pending = [(root, False)]
    while pending:
        node, wrapped = pending.pop()
        if node.tag == note_tag and wrapped:
            return True
        wrapped = wrapped or not node.tag.startswith(word_namespace)
        pending.extend((child, wrapped) for child in node)
    return False


def audit(package):
    names = defaultdict(list)
    for entry in package.infolist():
        names[entry.filename.translate(ASCII_LOWER)].append(entry)
    content_types = read_part(package, names, "[Content_Types].xml")
    if content_types.tag != CONTENT_TYPES + "Types":
        raise ValueError("Unrecognized OPC content types XML")
    document_part = relationship_target(package, names, "", "officeDocument", required=True)
    validate_part_type(content_types, document_part, WORD_MIME_PREFIX + "document.main+xml")
    document = read_part(package, names, document_part)
    namespace = next((word for word in WORD_NAMESPACES if document.tag == word + "document"), None)
    if namespace is None:
        raise ValueError("The main part is not supported WordprocessingML")
    bodies = document.findall(namespace + "body")
    if len(bodies) != 1:
        raise ValueError("Expected one body in the main Word document part")
    body = bodies[0]

    notes_part = relationship_target(package, names, document_part, "footnotes")
    if notes_part:
        validate_part_type(content_types, notes_part, WORD_MIME_PREFIX + "footnotes+xml")
        notes_xml = read_part(package, names, notes_part)
    else:
        notes_xml = ET.Element(namespace + "footnotes")
    if notes_xml.tag != namespace + "footnotes":
        raise ValueError(f"Unexpected footnotes root in {notes_part}")

    references = defaultdict(list)
    definitions = defaultdict(list)
    findings = []
    reference_tag = namespace + "footnoteReference"
    reference_nodes = list(body.iter(reference_tag))
    for position, node in enumerate(reference_nodes, 1):
        identifier = note_id(node, namespace)
        if identifier is None:
            findings.append({"kind": "unusable_reference_id", "references": [position]})
        else:
            references[identifier].append(position)

    normal_count = special_count = 0
    footnote_tag = namespace + "footnote"
    for position, node in enumerate(notes_xml.findall(footnote_tag), 1):
        note_type = node.get(namespace + "type", "normal")
        if note_type == "normal":
            normal_count += 1
        elif note_type in SPECIAL_TYPES:
            special_count += 1
        else:
            findings.append({"kind": "unknown_note_type", "definitions": [position]})

        identifier = note_id(node, namespace)
        if identifier is None:
            findings.append({"kind": "unusable_definition_id", "definitions": [position]})
        else:
            definitions[identifier].append((position, note_type))

    for identifier in sorted(references.keys() | definitions.keys()):
        ref_positions = references.get(identifier, [])
        note_rows = definitions.get(identifier, [])
        location = {"id": identifier, "references": ref_positions,
                    "definitions": [position for position, _ in note_rows]}
        if len(note_rows) > 1:
            findings.append({"kind": "duplicate_definition_id", **location})
        if len(ref_positions) > 1:
            findings.append({"kind": "repeated_reference_id_review", **location})
        if ref_positions and not note_rows:
            findings.append({"kind": "missing_definition", **location})
        elif ref_positions and all(note_type in SPECIAL_TYPES for _, note_type in note_rows):
            findings.append({"kind": "reference_to_special_note", **location})
        elif not ref_positions and any(note_type == "normal" for _, note_type in note_rows):
            findings.append({"kind": "unreferenced_normal_note_review", **location})

    review_flags = []
    revision_tags = {namespace + tag for tag in ("ins", "del", "moveFrom", "moveTo", "cellIns", "cellDel")}
    if any(node.tag in revision_tags for root in (body, notes_xml) for node in root.iter()):
        review_flags.append("tracked_changes_present")
    if (any(next(branch.iter(reference_tag), None) is not None for branch in body.iter(ALTERNATE_CONTENT)) or
            any(next(branch.iter(footnote_tag), None) is not None for branch in notes_xml.iter(ALTERNATE_CONTENT))):
        review_flags.append("alternate_content_contains_footnotes")
    elif has_wrapped_note(body, reference_tag, namespace) or has_wrapped_note(notes_xml, footnote_tag, namespace):
        review_flags.append("extended_markup_contains_footnotes")
    return {"document_part": document_part, "footnotes_part": notes_part,
            "reference_count": len(reference_nodes), "normal_note_count": normal_count,
            "special_note_count": special_count, "findings": findings, "review_flags": review_flags}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("docx", type=Path, help="Local DOCX to read")
    args = parser.parse_args()
    try:
        with ZipFile(args.docx, "r") as package:
            result = audit(package)
    except (OSError, BadZipFile, ET.ParseError, DeflateError, RuntimeError, ValueError) as error:
        print(json.dumps({"status": "not_audited", "error": str(error)}))
        return 2

    needs_review = bool(result["findings"] or result["review_flags"])
    result["status"] = "review_needed" if needs_review else "no_findings_in_scope"
    print(json.dumps(result, indent=2))
    return 1 if needs_review else 0


if __name__ == "__main__":
    sys.exit(main())
