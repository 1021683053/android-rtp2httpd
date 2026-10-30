import hashlib
import io
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build_core
from elf_utils import validate_android_elf
import verify_apk
import package_release
import check_environment


def synthetic_elf(interpreter="/system/bin/linker64", library="libc.so", alignment=16384):
    """Program-header fixture only; never executed as a native program."""
    data = bytearray(512)
    ident = b"\x7fELF\x02\x01\x01" + bytes(9)
    struct.pack_into("<16sHHIQQQIHHHHHH", data, 0, ident, 3, 183, 1, 496, 64, 0, 0, 64, 56, 3, 0, 0, 0)
    interpreter = interpreter.encode() + b"\0"
    libraries = library.encode() + b"\0"
    struct.pack_into("<IIQQQQQQ", data, 64, 1, 5, 0, 0, 0, 512, 512, alignment)
    struct.pack_into("<IIQQQQQQ", data, 120, 3, 4, 256, 256, 256, len(interpreter), len(interpreter), 1)
    struct.pack_into("<IIQQQQQQ", data, 176, 2, 6, 320, 320, 320, 64, 64, 8)
    data[256:256 + len(interpreter)] = interpreter
    for i, pair in enumerate([(5, 448), (10, len(libraries)), (1, 0), (0, 0)]):
        struct.pack_into("<qQ", data, 320 + i * 16, *pair)
    data[448:448 + len(libraries)] = libraries
    return bytes(data)


class ElfTests(unittest.TestCase):
    def test_accepts_android_pie_layout(self):
        info = validate_android_elf(synthetic_elf())
        self.assertEqual(info["needed"], ["libc.so"])

    def test_rejects_desktop_and_unaligned_binaries(self):
        for data in [b"not an ELF", synthetic_elf("/lib/ld-linux-aarch64.so.1"),
                     synthetic_elf(library="libc.so.6"), synthetic_elf(alignment=4096)]:
            with self.subTest(prefix=data[:8]), self.assertRaises(ValueError):
                validate_android_elf(data)

    def test_rejects_truncated_segments(self):
        with self.assertRaises(ValueError):
            validate_android_elf(synthetic_elf()[:400])


class ApkTests(unittest.TestCase):
    def make_apk(self, filename, core=None, tamper=False, license_text=True):
        with zipfile.ZipFile(filename, "w") as archive:
            archive.writestr("AndroidManifest.xml", b"fixture")
            if core is not None:
                info = dict(build_core.LOCK, size=len(core), sha256=hashlib.sha256(core).hexdigest())
                if tamper:
                    info["sha256"] = "0" * 64
                archive.writestr("lib/arm64-v8a/librtp2httpd.so", core)
                archive.writestr("assets/rtp2httpd/BUILD-INFO.json", json.dumps(info))
                if license_text:
                    archive.writestr("assets/rtp2httpd/LICENSE", "License fixture\n" * 100)

    def test_rejects_shell_only_apk(self):
        with tempfile.TemporaryDirectory() as work:
            apk = Path(work) / "shell.apk"
            self.make_apk(apk)
            with self.assertRaisesRegex(ValueError, "no Android ARM64 core"):
                verify_apk.verify(apk)

    def test_verifies_metadata_and_license(self):
        with tempfile.TemporaryDirectory() as work:
            apk = Path(work) / "core.apk"
            self.make_apk(apk, synthetic_elf())
            verify_apk.verify(apk)
            self.make_apk(apk, synthetic_elf(), tamper=True)
            with self.assertRaisesRegex(ValueError, "does not match"):
                verify_apk.verify(apk)
            self.make_apk(apk, synthetic_elf(), license_text=False)
            with self.assertRaises(KeyError):
                verify_apk.verify(apk)


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
            modified = build_core.adapt_source(root)
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
                build_core.adapt_source(root)

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
                build_core.extract_archive(data.getvalue(), Path(work))

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
            lock = dict(build_core.LOCK, repository=str(remote), commit=commit)
            with patch.object(build_core, "ROOT", work / "project"), patch.object(build_core, "LOCK", lock):
                source = build_core.fetch_source()
                self.assertEqual((source / "source.c").read_text(), "locked\n")
                remote.rename(work / "offline-remote")
                self.assertEqual(build_core.fetch_source(), source)

    def test_source_bundle_includes_build_sources_and_excludes_local_secrets(self):
        with tempfile.TemporaryDirectory() as work:
            root = Path(work) / "project"
            upstream = Path(work) / "upstream"
            (upstream / "src").mkdir(parents=True)
            (upstream / "LICENSE").write_text("upstream license")
            (upstream / "src/rtp2httpd.c").write_text("original source")
            (root / "scripts").mkdir(parents=True)
            (root / "scripts/build_core.py").write_text("build script")
            (root / "scripts/__pycache__").mkdir()
            (root / "scripts/__pycache__/cache.pyc").write_bytes(b"cache")
            (root / "local.properties").write_text("local secret")
            (root / "signing.jks").write_bytes(b"private key")
            (root / "build").mkdir()
            (root / "build/old.apk").write_bytes(b"artifact")
            with patch.object(build_core, "ROOT", root):
                bundle = build_core.create_source_bundle(upstream, True, {"commit": "fixture"})
            with tarfile.open(bundle) as archive:
                names = archive.getnames()
                self.assertIn("rtp2httpd-source/upstream/LICENSE", names)
                self.assertIn("rtp2httpd-source/upstream/src/rtp2httpd.c", names)
                self.assertIn("rtp2httpd-source/android-rtp2httpd/scripts/build_core.py", names)
                self.assertFalse(any("local.properties" in name or name.endswith(".jks")
                                     or "__pycache__" in name or name.endswith("old.apk") for name in names))


class ToolDiscoveryTests(unittest.TestCase):
    def test_missing_tools_fail_without_running_installer(self):
        with tempfile.TemporaryDirectory() as work, patch.dict(os.environ, {}, clear=True):
            sdk = Path(work) / "sdk"
            with patch.object(build_core, "sdk_roots", return_value=[sdk]), \
                 patch.object(build_core.shutil, "which", return_value=None), \
                 patch.object(build_core, "run") as run:
                with self.assertRaisesRegex(RuntimeError, "Automatic installation is disabled"):
                    build_core.tools(sdk)
                run.assert_not_called()
                self.assertFalse(sdk.exists())

    def test_missing_environment_fails_before_fetching_sources(self):
        with patch.object(sys, "argv", ["build_core.py"]), \
             patch.object(build_core, "find_sdk", return_value=Path("/missing-sdk")), \
             patch.object(build_core, "tools", side_effect=RuntimeError("Missing build tools")), \
             patch.object(build_core, "fetch_source") as fetch:
            with self.assertRaisesRegex(RuntimeError, "Missing build tools"):
                build_core.main()
            fetch.assert_not_called()

    def test_reuses_complete_ndk_from_another_sdk_without_installing(self):
        with tempfile.TemporaryDirectory() as work, patch.dict(os.environ, {}, clear=True):
            sdk = Path(work) / "sdk"
            alternate = Path(work) / "homebrew-sdk"
            ndk = alternate / "ndk" / build_core.LOCK["ndk_version"]
            (ndk / "toolchains/llvm/prebuilt/darwin-x86_64/bin").mkdir(parents=True)
            (ndk / "source.properties").write_text("Pkg.Revision = " + build_core.LOCK["ndk_version"])
            (ndk / "toolchains/llvm/prebuilt/darwin-x86_64/bin/llvm-strip").touch()
            cmake = Path(work) / "cmake"
            cmake.touch()
            with patch.object(build_core, "sdk_roots", return_value=[sdk, alternate]), \
                 patch.object(build_core.shutil, "which", return_value=str(cmake)), \
                 patch.object(build_core, "run") as run:
                found, _, _ = build_core.tools(sdk)
                self.assertEqual(found, ndk.resolve())
                run.assert_not_called()

    def test_incomplete_ndk_directory_is_not_treated_as_installed(self):
        with tempfile.TemporaryDirectory() as work, patch.dict(os.environ, {}, clear=True):
            sdk = Path(work) / "sdk"
            alternate = Path(work) / "homebrew-sdk"
            (alternate / "ndk" / build_core.LOCK["ndk_version"]).mkdir(parents=True)
            with patch.object(build_core, "sdk_roots", return_value=[sdk, alternate]):
                self.assertEqual(build_core.find_ndk(sdk), (sdk / "ndk" / build_core.LOCK["ndk_version"]).resolve())

    def test_explicit_ndk_path_takes_precedence(self):
        with tempfile.TemporaryDirectory() as work, patch.dict(os.environ, {"ANDROID_NDK_HOME": work}):
            self.assertEqual(build_core.find_ndk(Path("unused-sdk")), Path(work).resolve())


class PackagingSdkTests(unittest.TestCase):
    def populate(self, sdk, compile_sdk=34):
        for path in package_release.required_sdk_files(sdk, compile_sdk):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()

    def test_falls_back_from_sdk_with_wrong_platform_to_complete_sdk(self):
        with tempfile.TemporaryDirectory() as work:
            preferred = Path(work) / "homebrew-sdk"
            complete = Path(work) / "android-sdk"
            self.populate(preferred, 35)
            self.populate(complete)
            with patch.object(package_release, "find_sdk", return_value=preferred), \
                 patch.object(package_release, "sdk_roots", return_value=[preferred, complete]):
                self.assertEqual(package_release.find_packaging_sdk(None, 34), complete.resolve())

    def test_keeps_complete_preferred_sdk(self):
        with tempfile.TemporaryDirectory() as work:
            preferred = Path(work) / "preferred-sdk"
            complete = Path(work) / "other-sdk"
            self.populate(preferred)
            self.populate(complete)
            with patch.object(package_release, "find_sdk", return_value=preferred), \
                 patch.object(package_release, "sdk_roots", return_value=[preferred, complete]):
                self.assertEqual(package_release.find_packaging_sdk(None, 34), preferred.resolve())

    def test_explicit_incomplete_sdk_fails_without_silently_changing_it(self):
        with tempfile.TemporaryDirectory() as work:
            preferred = Path(work) / "explicit-sdk"
            self.populate(preferred, 35)
            with patch.object(package_release, "find_sdk", return_value=preferred), \
                 patch.object(package_release, "sdk_roots") as roots:
                with self.assertRaisesRegex(RuntimeError, "platforms/android-34"):
                    package_release.find_packaging_sdk(str(preferred), 34)
                roots.assert_not_called()

    def test_reports_missing_packaging_tools(self):
        with tempfile.TemporaryDirectory() as work:
            preferred = Path(work) / "incomplete-sdk"
            self.populate(preferred)
            (preferred / "build-tools/35.0.0/zipalign").unlink()
            with patch.object(package_release, "find_sdk", return_value=preferred), \
                 patch.object(package_release, "sdk_roots", return_value=[preferred]):
                with self.assertRaisesRegex(RuntimeError, "zipalign"):
                    package_release.find_packaging_sdk(None, 34)


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
            self.assertEqual(check_environment.find_jdk(), jdk.resolve())
            after = {str(path.relative_to(jdk)): path.read_bytes() for path in jdk.rglob("*") if path.is_file()}
            self.assertEqual(before, after)

    def test_rejects_other_java_without_switching_system_default(self):
        with tempfile.TemporaryDirectory() as work, patch.dict(os.environ, {"JAVA_HOME": work}):
            self.make_jdk(Path(work), "25.0.1")
            with self.assertRaisesRegex(RuntimeError, "requires JDK 17"):
                check_environment.find_jdk()
            self.assertEqual(os.environ["JAVA_HOME"], work)


if __name__ == "__main__":
    unittest.main()
