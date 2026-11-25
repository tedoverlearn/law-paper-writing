"""Exercise the audit CLI against DOCX packages generated without Word."""

import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from xml.sax.saxutils import quoteattr
from zipfile import ZIP_DEFLATED, ZipFile


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "audit_docx_footnotes.py"
PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
CONTENT_TYPE_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
TRANSITIONAL_WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
TRANSITIONAL_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
STRICT_WORD_NS = "http://purl.oclc.org/ooxml/wordprocessingml/main"
STRICT_REL_NS = "http://purl.oclc.org/ooxml/officeDocument/relationships"
WORD_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml"
SPECIAL_NOTES = (("-1", "separator"), ("0", "continuationSeparator"), ("-2", "continuationNotice"))


def footnote_xml(identifier, kind):
    if kind == "normal":
        kind_attr = ""
        body = "<w:footnoteRef/><w:t>合成脚注。</w:t>"
    else:
        kind_attr = f" w:type={quoteattr(kind)}"
        body = {
            "separator": "<w:separator/>",
            "continuationSeparator": "<w:continuationSeparator/>",
            "continuationNotice": "<w:t>续页提示。</w:t>",
        }[kind]
    return f"<w:footnote w:id={quoteattr(identifier)}{kind_attr}><w:p><w:r>{body}</w:r></w:p></w:footnote>"


def make_docx(path, *, references=(), notes=None, strict=False):
    """Create the minimum OPC parts and relationships for the selected fixture."""
    word_ns = STRICT_WORD_NS if strict else TRANSITIONAL_WORD_NS
    office_ns = STRICT_REL_NS if strict else TRANSITIONAL_REL_NS
    document = "word/manuscript.xml" if strict else "word/document.xml"
    note_part = "word/notes.xml" if strict else "word/footnotes.xml"
    types = (
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        f'<Override PartName="/{document}" ContentType="{WORD_TYPE}.document.main+xml"/>'
    )
    anchors = "".join(f"<w:r><w:footnoteReference w:id={quoteattr(key)}/></w:r>" for key in references)
    parts = {
        "_rels/.rels": (
            f'<Relationships xmlns="{PACKAGE_REL_NS}">'
            f'<Relationship Id="rId1" Type="{office_ns}/officeDocument" Target="{document}"/>'
            "</Relationships>"
        ),
        document: (
            f'<w:document xmlns:w="{word_ns}"><w:body><w:p>'
            f"<w:r><w:t>待审正文。</w:t></w:r>{anchors}</w:p></w:body></w:document>"
        ),
    }
    if notes is not None:
        types += f'<Override PartName="/{note_part}" ContentType="{WORD_TYPE}.footnotes+xml"/>'
        parts[f"word/_rels/{Path(document).name}.rels"] = (
            f'<Relationships xmlns="{PACKAGE_REL_NS}">'
            f'<Relationship Id="rId1" Type="{office_ns}/footnotes" Target="{Path(note_part).name}"/>'
            "</Relationships>"
        )
        definitions = "".join(footnote_xml(identifier, kind) for identifier, kind in notes)
        parts[note_part] = f'<w:footnotes xmlns:w="{word_ns}">{definitions}</w:footnotes>'
    parts["[Content_Types].xml"] = f'<Types xmlns="{CONTENT_TYPE_NS}">{types}</Types>'
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as package:
        for name, content in parts.items():
            package.writestr(name, content.encode("utf-8"))


class DocxFootnotesTest(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory(prefix="footnote-test-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.path = self.root / "有 空格的稿件.docx"

    def run_audit(self, code):
        before = self.path.read_bytes()
        result = subprocess.run(
            [sys.executable, "-X", "utf8", str(SCRIPT), str(self.path)],
            cwd=self.root, capture_output=True, encoding="utf-8",
        )
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertEqual(self.path.read_bytes(), before)
        return json.loads(result.stdout)

    def test_document_without_footnotes(self):
        make_docx(self.path)
        report = self.run_audit(0)
        self.assertEqual(report["status"], "no_findings_in_scope")
        self.assertIsNone(report["footnotes_part"])
        self.assertEqual(report["reference_count"], 0)
        self.assertEqual(report["normal_note_count"], 0)
        self.assertEqual(report["special_note_count"], 0)
        self.assertEqual(report["findings"], [])
        self.assertEqual(report["review_flags"], [])

    def test_valid_normal_note_and_special_separators(self):
        make_docx(self.path, references=("17",), notes=(*SPECIAL_NOTES, ("17", "normal")))
        report = self.run_audit(0)
        self.assertEqual(report["reference_count"], 1)
        self.assertEqual(report["normal_note_count"], 1)
        self.assertEqual(report["special_note_count"], 3)
        self.assertEqual(report["findings"], [])

    def test_only_special_separators_are_not_orphaned_ordinary_notes(self):
        make_docx(self.path, notes=SPECIAL_NOTES)
        report = self.run_audit(0)
        self.assertEqual(report["reference_count"], 0)
        self.assertEqual(report["normal_note_count"], 0)
        self.assertEqual(report["special_note_count"], 3)
        self.assertEqual(report["findings"], [])

    def test_missing_definition_in_an_existing_notes_part(self):
        make_docx(self.path, references=("17", "29"), notes=(("17", "normal"),))
        report = self.run_audit(1)
        self.assertEqual(report["status"], "review_needed")
        self.assertEqual(report["findings"], [
            {"kind": "missing_definition", "id": 29, "references": [2], "definitions": []},
        ])

    def test_reference_with_no_related_notes_part(self):
        make_docx(self.path, references=("17",))
        report = self.run_audit(1)
        self.assertIsNone(report["footnotes_part"])
        self.assertEqual(report["findings"], [
            {"kind": "missing_definition", "id": 17, "references": [1], "definitions": []},
        ])

    def test_duplicate_definition_ids_are_compared_as_integers(self):
        make_docx(self.path, references=("17",), notes=(("17", "normal"), ("+017", "normal")))
        report = self.run_audit(1)
        self.assertEqual(report["findings"], [
            {"kind": "duplicate_definition_id", "id": 17, "references": [1], "definitions": [1, 2]},
        ])

    def test_repeated_reference_with_one_definition_is_a_review_signal(self):
        make_docx(self.path, references=("17", "+017"), notes=(("17", "normal"),))
        report = self.run_audit(1)
        self.assertEqual(report["findings"], [
            {"kind": "repeated_reference_id_review", "id": 17, "references": [1, 2], "definitions": [1]},
        ])

    def test_unreferenced_ordinary_note_is_reported(self):
        make_docx(self.path, notes=(*SPECIAL_NOTES, ("17", "normal")))
        report = self.run_audit(1)
        self.assertEqual(report["findings"], [
            {"kind": "unreferenced_normal_note_review", "id": 17, "references": [], "definitions": [4]},
        ])

    def test_reference_to_a_special_separator_is_reported(self):
        make_docx(self.path, references=("0",), notes=SPECIAL_NOTES)
        report = self.run_audit(1)
        self.assertEqual(report["findings"], [
            {"kind": "reference_to_special_note", "id": 0, "references": [1], "definitions": [2]},
        ])

    def test_strict_package_locates_renamed_parts_via_relationships(self):
        make_docx(self.path, references=("0",), notes=(("0", "normal"),), strict=True)
        report = self.run_audit(0)
        self.assertEqual(report["document_part"], "word/manuscript.xml")
        self.assertEqual(report["footnotes_part"], "word/notes.xml")
        self.assertEqual(report["findings"], [])

    def test_truncated_zip_returns_structured_error(self):
        make_docx(self.path)
        self.path.write_bytes(self.path.read_bytes()[:-22])  # ZIP end-of-central-directory record.
        report = self.run_audit(2)
        self.assertEqual(report["status"], "not_audited")
        self.assertTrue(report["error"])


if __name__ == "__main__":
    unittest.main()
