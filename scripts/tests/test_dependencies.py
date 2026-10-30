import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scripts.android_build.project import Project
from scripts.android_build import dependencies
project = Project.load()

class JavaDependencyTests(unittest.TestCase):
    def test_checksum_and_both_packager_declarations_must_match(self):
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            directory = root / 'third_party/java'
            directory.mkdir(parents=True)
            (root / 'app').mkdir()
            jar = directory / 'dependency.jar'
            jar.write_bytes(b'fixture jar')
            (directory / 'dependencies.json').write_text(json.dumps({'jars': [
                {'file': jar.name, 'sha256': hashlib.sha256(jar.read_bytes()).hexdigest()}]}))
            gradle = root / 'app/build.gradle'
            gradle.write_text("implementation files('../third_party/java/dependency.jar')\n")
            with patch.object(project, 'root', root):
                self.assertEqual(dependencies.verified_jars(project), [jar])
                gradle.write_text("implementation 'untracked:library:1.0'\n")
                with self.assertRaisesRegex(ValueError, 'Runtime dependencies'):
                    dependencies.verified_jars(project)
                jar.write_bytes(b'tampered')
                with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
                    dependencies.verified_jars(project)
