import io
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch
from scripts.android_build.project import Project
from scripts.android_build import source as source_tools
project = Project.load()

class SourceTests(unittest.TestCase):
    def test_adapts_android_platform_entry_and_private_paths(self):
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            (root / "src").mkdir()
            (root / "CMakeLists.txt").write_text('if(CMAKE_SYSTEM_NAME STREQUAL "Linux")\nendif()\n'
                                                  'target_link_libraries(rtp2httpd PRIVATE rt)\n')
            (root / "src/rtp2httpd.c").write_text('int main(int argc, char *argv[]) { return 0; }\n')
            (root / "src/configuration.c").write_text(
                "index(line, '='); index(line + i, ']'); index(arg++, ']');\n"
                "rindex(++p, ':'); rindex(arg, ':');\n")
            (root / "src/buffer_pool.c").write_text(
                '#if (defined(__linux__) || defined(__FreeBSD__)) && defined(MFD_ALLOW_SEALING) && defined(F_ADD_SEALS)\n'
                'int fd = memfd_create("batch", 0);\n#else\n(void)ref;\n#endif\n')
            (root / "src/status.c").write_text('const char *path = "/tmp/rtp2httpd_status_%d";\n')
            (root / "src/embedded_web_data.h").write_text('/* generated header must stay intact */\n')
            modified = source_tools.adapt_source(root)
            self.assertIn("src/status.c", modified)
            self.assertIn('"./rtp2httpd_status_%d"', (root / "src/status.c").read_text())
            self.assertIn("OR ANDROID", (root / "CMakeLists.txt").read_text())
            self.assertIn("if(NOT ANDROID)", (root / "CMakeLists.txt").read_text())
            self.assertIn("rtp2httpd_upstream_main", (root / "src/rtp2httpd.c").read_text())
            configuration = (root / "src/configuration.c").read_text()
            self.assertEqual(configuration.count("strchr("), 3)
            self.assertEqual(configuration.count("strrchr("), 2)
            self.assertIn("__ANDROID_API__ >= 30", (root / "src/buffer_pool.c").read_text())
            self.assertEqual((root / "src/embedded_web_data.h").read_text(),
                             '/* generated header must stay intact */\n')
            with self.assertRaisesRegex(ValueError, "layout changed"):
                source_tools.adapt_source(root)

    def test_rejects_unsafe_source_archives(self):
        for name, link in [("../outside", None), ("link", "/etc/passwd")]:
            data = io.BytesIO()
            with tarfile.open(fileobj=data, mode="w") as archive:
                member = tarfile.TarInfo(name)
                if link:
                    member.type = tarfile.SYMTYPE
                    member.linkname = link
                archive.addfile(member)
            with tempfile.TemporaryDirectory() as work, self.assertRaises(ValueError):
                source_tools.extract_archive(data.getvalue(), Path(work))

    def test_fetches_locked_commit_instead_of_newer_head_and_reuses_cache(self):
        with tempfile.TemporaryDirectory() as work:
            work = Path(work)
            remote = work / "remote"
            subprocess.run(["git", "init", remote], check=True, capture_output=True)
            def git(*args):
                return subprocess.check_output(["git", "-C", str(remote), *args], text=True,
                                               stderr=subprocess.DEVNULL).strip()
            git("config", "user.name", "Build test")
            git("config", "user.email", "build-test@example.invalid")
            (remote / "source.c").write_text("locked\n")
            git("add", ".")
            git("commit", "-m", "Locked source")
            commit = git("rev-parse", "HEAD")
            (remote / "source.c").write_text("newer\n")
            git("commit", "-am", "Newer source")
            lock = dict(project.lock, repository=str(remote), commit=commit)
            with patch.object(project, "root", work / "project"), patch.object(project, "lock", lock):
                source = source_tools.fetch_source(project)
                self.assertEqual((source / "source.c").read_text(), "locked\n")
                remote.rename(work / "offline-remote")
                self.assertEqual(source_tools.fetch_source(project), source)

    def test_source_bundle_includes_build_sources_and_excludes_local_secrets(self):
        with tempfile.TemporaryDirectory() as work:
            root = Path(work) / "project"
            upstream = Path(work) / "upstream"
            (upstream / "src").mkdir(parents=True)
            (upstream / "LICENSE").write_text("upstream license")
            (upstream / "src/rtp2httpd.c").write_text("original source")
            (root / "scripts").mkdir(parents=True)
            (root / "scripts/android.py").write_text("build script")
            (root / "scripts/__pycache__").mkdir()
            (root / "scripts/__pycache__/cache.pyc").write_bytes(b"cache")
            (root / "local.properties").write_text("local secret")
            (root / "signing.jks").write_bytes(b"private key")
            (root / "build").mkdir()
            (root / "build/old.apk").write_bytes(b"artifact")
            with patch.object(project, "root", root):
                bundle = source_tools.create_source_bundle(project, upstream, True, {"commit": "fixture"})
            with tarfile.open(bundle) as archive:
                names = archive.getnames()
                self.assertIn("rtp2httpd-source/upstream/LICENSE", names)
                self.assertIn("rtp2httpd-source/upstream/src/rtp2httpd.c", names)
                self.assertIn("rtp2httpd-source/android-rtp2httpd/scripts/android.py", names)
                self.assertFalse(any("local.properties" in name or name.endswith(".jks")
                                     or "__pycache__" in name or name.endswith("old.apk") for name in names))
