"""Run the browser async regression cases with Node's built-in test runner."""
from pathlib import Path
import shutil
import subprocess
import unittest


class ManagementUiTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node.js is required for browser regression checks')
    def test_async_editor_operations(self):
        subprocess.run(['node', '--test', str(Path(__file__).with_suffix('.cjs'))], check=True)
