"""Real Linux symlinks only. No users, root, services or report publication."""
from pathlib import Path
from tempfile import TemporaryDirectory
import sys
import unittest
from scripts.report_release import files, normalize_lib64


@unittest.skipUnless(sys.platform == "linux", "Linux symlink packaging gate")
class ReleaseLinuxTests(unittest.TestCase):
    def test_materializes_only_standard_lib64_without_leaving_links(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".venv/lib").mkdir(parents=True)
            (root / ".venv/lib/library.py").write_text("synthetic")
            (root / ".venv/lib64").symlink_to("lib", target_is_directory=True)
            with self.assertRaises(ValueError):
                list(files(root))
            self.assertTrue(normalize_lib64(root))
            self.assertFalse((root / ".venv/lib64").is_symlink())
            self.assertEqual((root / ".venv/lib64/library.py").read_text(), "synthetic")
            list(files(root))
            self.assertFalse(normalize_lib64(root))

    def test_external_and_nested_links_are_never_followed(self):
        with TemporaryDirectory() as directory, TemporaryDirectory() as outside:
            root = Path(directory)
            (root / ".venv/lib").mkdir(parents=True)
            alias = root / ".venv/lib64"
            alias.symlink_to(outside, target_is_directory=True)
            with self.assertRaises(ValueError):
                normalize_lib64(root)
            alias.unlink()
            alias.symlink_to("lib", target_is_directory=True)
            (root / ".venv/lib/foreign").symlink_to(outside, target_is_directory=True)
            with self.assertRaises(ValueError):
                normalize_lib64(root)
            self.assertTrue(alias.is_symlink())
