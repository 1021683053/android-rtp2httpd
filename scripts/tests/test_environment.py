import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scripts.android_build.project import Project
from scripts.android_build import environment
project = Project.load()

class PackagingSdkTests(unittest.TestCase):
    def populate(self, sdk, compile_sdk=34):
        for path in environment.required_sdk_files(sdk, compile_sdk):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()

    def test_falls_back_from_sdk_with_wrong_platform_to_complete_sdk(self):
        with tempfile.TemporaryDirectory() as work:
            preferred = Path(work) / "homebrew-sdk"
            complete = Path(work) / "android-sdk"
            self.populate(preferred, 35)
            self.populate(complete)
            with patch.object(environment, "find_sdk", return_value=preferred), \
                 patch.object(environment, "sdk_roots", return_value=[preferred, complete]):
                self.assertEqual(environment.find_packaging_sdk(project, None, 34), complete.resolve())

    def test_keeps_complete_preferred_sdk(self):
        with tempfile.TemporaryDirectory() as work:
            preferred = Path(work) / "preferred-sdk"
            complete = Path(work) / "other-sdk"
            self.populate(preferred)
            self.populate(complete)
            with patch.object(environment, "find_sdk", return_value=preferred), \
                 patch.object(environment, "sdk_roots", return_value=[preferred, complete]):
                self.assertEqual(environment.find_packaging_sdk(project, None, 34), preferred.resolve())

    def test_explicit_incomplete_sdk_fails_without_silently_changing_it(self):
        with tempfile.TemporaryDirectory() as work:
            preferred = Path(work) / "explicit-sdk"
            self.populate(preferred, 35)
            with patch.object(environment, "find_sdk", return_value=preferred), \
                 patch.object(environment, "sdk_roots") as roots:
                with self.assertRaisesRegex(RuntimeError, "platforms/android-34"):
                    environment.find_packaging_sdk(project, str(preferred), 34)
                roots.assert_not_called()

    def test_reports_missing_packaging_tools(self):
        with tempfile.TemporaryDirectory() as work:
            preferred = Path(work) / "incomplete-sdk"
            self.populate(preferred)
            (preferred / "build-tools/35.0.0/zipalign").unlink()
            with patch.object(environment, "find_sdk", return_value=preferred), \
                 patch.object(environment, "sdk_roots", return_value=[preferred]):
                with self.assertRaisesRegex(RuntimeError, "zipalign"):
                    environment.find_packaging_sdk(project, None, 34)


class EnvironmentTests(unittest.TestCase):
    def make_jdk(self, root, version):
        (root / "bin").mkdir()
        (root / "bin/java").touch()
        (root / "bin/javac").touch()
        (root / "release").write_text('JAVA_VERSION="' + version + '"\n')

    def test_reads_existing_jdk_without_changing_it(self):
        with tempfile.TemporaryDirectory() as work, patch.dict(os.environ, {"JAVA_HOME": work}):
            jdk = Path(work)
            self.make_jdk(jdk, "17.0.17")
            before = {str(path.relative_to(jdk)): path.read_bytes() for path in jdk.rglob("*") if path.is_file()}
            self.assertEqual(environment.find_jdk(), jdk.resolve())
            after = {str(path.relative_to(jdk)): path.read_bytes() for path in jdk.rglob("*") if path.is_file()}
            self.assertEqual(before, after)

    def test_rejects_other_java_without_switching_system_default(self):
        with tempfile.TemporaryDirectory() as work, patch.dict(os.environ, {"JAVA_HOME": work}):
            self.make_jdk(Path(work), "25.0.1")
            with self.assertRaisesRegex(RuntimeError, "requires JDK 17"):
                environment.find_jdk()
            self.assertEqual(os.environ["JAVA_HOME"], work)
