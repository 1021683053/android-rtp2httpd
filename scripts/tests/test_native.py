import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scripts.android_build.project import Project
from scripts.android_build import native, environment
project = Project.load()

class ToolDiscoveryTests(unittest.TestCase):
    def test_missing_tools_fail_without_running_installer(self):
        with tempfile.TemporaryDirectory() as work, patch.dict(os.environ, {}, clear=True):
            sdk = Path(work) / "sdk"
            with patch.object(environment, "sdk_roots", return_value=[sdk]), \
                 patch.object(environment.shutil, "which", return_value=None), \
                 patch.object(environment.subprocess, "run") as run:
                with self.assertRaisesRegex(RuntimeError, "Automatic installation is disabled"):
                    environment.tools(project, sdk)
                run.assert_not_called()
                self.assertFalse(sdk.exists())

    def test_missing_environment_fails_before_fetching_sources(self):
        with patch.object(native, "find_sdk", return_value=Path("/missing-sdk")), \
             patch.object(native, "tools", side_effect=RuntimeError("Missing build tools")), \
             patch.object(native, "fetch_source") as fetch:
            with self.assertRaisesRegex(RuntimeError, "Missing build tools"):
                native.build_native(project, type("Args", (), {"sdk_root":None,"source_dir":None,"abi":"universal"})())
            fetch.assert_not_called()

    def test_reuses_complete_ndk_from_another_sdk_without_installing(self):
        with tempfile.TemporaryDirectory() as work, patch.dict(os.environ, {}, clear=True):
            sdk = Path(work) / "sdk"
            alternate = Path(work) / "homebrew-sdk"
            ndk = alternate / "ndk" / project.lock["ndk_version"]
            (ndk / "toolchains/llvm/prebuilt/darwin-x86_64/bin").mkdir(parents=True)
            (ndk / "source.properties").write_text("Pkg.Revision = " + project.lock["ndk_version"])
            (ndk / "toolchains/llvm/prebuilt/darwin-x86_64/bin/llvm-strip").touch()
            cmake = Path(work) / "cmake"
            cmake.touch()
            with patch.object(environment, "sdk_roots", return_value=[sdk, alternate]), \
                 patch.object(environment.shutil, "which", return_value=str(cmake)), \
                 patch.object(environment.subprocess, "run") as run:
                found, _, _ = environment.tools(project, sdk)
                self.assertEqual(found, ndk.resolve())
                run.assert_not_called()

    def test_incomplete_ndk_directory_is_not_treated_as_installed(self):
        with tempfile.TemporaryDirectory() as work, patch.dict(os.environ, {}, clear=True):
            sdk = Path(work) / "sdk"
            alternate = Path(work) / "homebrew-sdk"
            (alternate / "ndk" / project.lock["ndk_version"]).mkdir(parents=True)
            with patch.object(environment, "sdk_roots", return_value=[sdk, alternate]):
                self.assertEqual(environment.find_ndk(project, sdk), (sdk / "ndk" / project.lock["ndk_version"]).resolve())

    def test_explicit_ndk_path_takes_precedence(self):
        with tempfile.TemporaryDirectory() as work, patch.dict(os.environ, {"ANDROID_NDK_HOME": work}):
            self.assertEqual(environment.find_ndk(project, Path("unused-sdk")), Path(work).resolve())
