"""Exercise the release command without touching manuscripts or an installed skill."""

from pathlib import Path
import os
import runpy
import stat
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from zipfile import ZipFile


BUILDER = Path(__file__).resolve().parents[1] / "scripts" / "build_release.py"
RELEASE = runpy.run_path(str(BUILDER))
RUNTIME_FILES = RELEASE["RUNTIME_FILES"]


class BuildReleaseTest(unittest.TestCase):
    def setUp(self):
        scratch = TemporaryDirectory(prefix="release-test-", dir=Path(__file__).resolve().parent)
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name) / "可移植 skill"
        self.skill = self.root / "law-paper-writing"
        self.builder = self.write("scripts/build_release.py", BUILDER.read_bytes())
        for name in RUNTIME_FILES:
            self.write(name, b"fixture\n")
        self.write(
            "SKILL.md",
            b'---\nname: law-paper-writing\ndescription: Writing\nmetadata:\n  version: "0.4.0"\n---\n\n'
            b"[Source cards](assets/source-card.md)\n",
        )
        self.write("agents/openai.yaml", b'interface:\n  default_prompt: "$law-paper-writing"\n')

    def write(self, name, data):
        path = self.skill / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def run_builder(self, *args):
        return subprocess.run(
            [sys.executable, "-X", "utf8", str(self.builder), *args],
            cwd=self.root,
            capture_output=True,
            encoding="utf-8",
        )

    def test_archive_is_portable_and_omits_workspace_material(self):
        self.write("drafts/未发表稿.docx", b"private")
        self.write("evaluations/private-notes.md", b"private")
        self.write("references/unlisted-draft.md", b"private")
        first = self.run_builder("--output", "first.zip")
        self.assertEqual(first.returncode, 0, first.stderr)

        self.write("assets/source-card.md", b"fixture\r\n")
        second = self.run_builder("--output", "second.zip")
        self.assertEqual(second.returncode, 0, second.stderr)
        first_zip = self.root / "first.zip"
        original_bytes = first_zip.read_bytes()
        self.assertEqual(original_bytes, (self.root / "second.zip").read_bytes())
        with ZipFile(first_zip) as archive:
            self.assertIsNone(archive.testzip())
            self.assertEqual(
                sorted(archive.namelist()),
                sorted(f"law-paper-writing/{name}" for name in RUNTIME_FILES),
            )
        self.assertNotEqual(self.run_builder("--output", "first.zip").returncode, 0)
        self.assertEqual(first_zip.read_bytes(), original_bytes)

    def test_archive_rejects_unshipped_and_escaping_link_targets(self):
        self.write("evaluations/trial.md", b"not in archive")
        self.write(
            "references/methods.md",
            b"[Local-only record](../evaluations/trial.md)\n"
            b"[Escaping path](../../drafts/note.md)\n"
            b"```md\n[Example](example.md)\n```\n",
        )
        result = self.run_builder("--output", "broken.zip")
        self.assertEqual(result.returncode, 1)
        self.assertIn("../evaluations/trial.md", result.stderr)
        self.assertIn("../../drafts/note.md", result.stderr)
        self.assertNotIn("example.md", result.stderr)
        self.assertFalse((self.root / "broken.zip").exists())

    def test_packager_rejects_missing_runtime_file(self):
        (self.skill / "assets" / "source-card.md").unlink()
        result = self.run_builder("--check")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("source-card.md", result.stderr)

    def test_packager_rejects_linked_runtime_directory(self):
        candidate = self.skill / "assets"
        replacement = self.root / "external assets"
        replacement.mkdir()
        for asset in candidate.iterdir():
            (replacement / asset.name).write_bytes(asset.read_bytes())
            asset.unlink()
        candidate.rmdir()
        if os.name == "nt":
            command = (
                "New-Item -ItemType Junction -Path $env:SKILL_TEST_LINK "
                "-Target $env:SKILL_TEST_TARGET -ErrorAction Stop | Out-Null"
            )
            link = subprocess.run(
                ["powershell", "-NoProfile", "-Command", command],
                env=dict(os.environ, SKILL_TEST_LINK=str(candidate), SKILL_TEST_TARGET=str(replacement)),
                capture_output=True,
            )
            if link.returncode:
                workspace = BUILDER.parents[2]
                discovery_path = ".agents/skills/law-paper-writing"
                existing_link = workspace / discovery_path
                if not existing_link.exists() or not (
                    existing_link.lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT
                ):
                    self.skipTest("test environment has no usable directory junction")
                with self.assertRaisesRegex(ValueError, "symlink or reparse point"):
                    RELEASE["checked_file"](workspace, discovery_path + "/SKILL.md")
                return
        else:
            candidate.symlink_to(replacement, target_is_directory=True)
        result = self.run_builder("--check")
        self.assertEqual(result.returncode, 1)
        self.assertIn("symlink or reparse point", result.stderr)


if __name__ == "__main__":
    unittest.main()
