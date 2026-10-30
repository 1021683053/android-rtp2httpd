"""Exercise the user entry point across working directories and failure paths."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ENTRY = Path(__file__).resolve().parents[1] / 'android.py'

class CliTests(unittest.TestCase):
    def invoke(self, *args, cwd=None):
        return subprocess.run([sys.executable, str(ENTRY), *args], cwd=cwd,
                              text=True, capture_output=True)

    def test_help_and_invalid_abi_do_not_require_sdk_or_create_outputs(self):
        with tempfile.TemporaryDirectory(prefix='android cli ') as directory:
            with patch.dict(os.environ, {'ANDROID_HOME': directory, 'JAVA_HOME': directory}):
                result = self.invoke('--help', cwd=directory)
                self.assertEqual(result.returncode, 0, result.stderr)
                bad = self.invoke('native', '--abi', 'unsupported', cwd=directory)
                self.assertNotEqual(bad.returncode, 0)
                self.assertIn('Unsupported ABI', bad.stderr)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_local_source_path_with_spaces_from_other_working_directory(self):
        with tempfile.TemporaryDirectory(prefix='source path ') as directory:
            result = self.invoke('source', 'fetch', '--source-dir', directory, cwd='/tmp')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(Path(result.stdout.strip()), Path(directory).resolve())

    def test_extra_arguments_rejected_for_sdk_backend(self):
        result = self.invoke('build', '--backend', 'sdk', '--', '--offline')
        self.assertEqual(result.returncode, 2)
        self.assertIn('require build --backend gradle', result.stderr)

    def test_importing_modules_does_not_load_lock_or_run_commands(self):
        from scripts.android_build import project, environment, source, native, apk, verification, dependencies, elf, testing
        import importlib
        with patch.object(Path, 'read_text', side_effect=AssertionError('unexpected file read')), \
             patch.object(subprocess, 'run', side_effect=AssertionError('unexpected process')):
            for module in [project, environment, source, native, apk, verification, dependencies, elf, testing]:
                importlib.reload(module)
