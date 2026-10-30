import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
from scripts.android_build.project import Project
from scripts.android_build import apk as apk_tools, verification
from scripts.android_build.elf import validate_android_elf
project = Project.load()
from .fixtures import synthetic_elf

class ApkTests(unittest.TestCase):
    def make_apk(self, filename, core=None, tamper=False, license_text=True):
        with zipfile.ZipFile(filename, "w") as archive:
            archive.writestr("AndroidManifest.xml", b"fixture")
            for path in (project.root / "app/src/main/assets").rglob("*"):
                if path.is_file():
                    archive.write(path, "assets/" + path.relative_to(project.root / "app/src/main/assets").as_posix())
            if core is not None:
                cores = core if isinstance(core, dict) else {"arm64-v8a": core}
                info = dict(project.lock, abis=list(cores), cores={})
                for abi, data in cores.items():
                    info["cores"][abi] = dict(size=len(data), sha256="0" * 64 if tamper else hashlib.sha256(data).hexdigest(),
                                               elf=validate_android_elf(data))
                    archive.writestr("lib/" + abi + "/librtp2httpd.so", data)
                archive.writestr("assets/rtp2httpd/BUILD-INFO.json", json.dumps(info))
                if license_text:
                    archive.writestr("assets/rtp2httpd/LICENSE", "License fixture\n" * 100)

    def test_rejects_shell_only_apk(self):
        with tempfile.TemporaryDirectory() as work:
            apk = Path(work) / "shell.apk"
            self.make_apk(apk)
            with self.assertRaisesRegex(ValueError, "no Android native core"):
                verification.verify(project, apk)

    def test_verifies_metadata_and_license(self):
        with tempfile.TemporaryDirectory() as work:
            apk = Path(work) / "core.apk"
            self.make_apk(apk, synthetic_elf())
            verification.verify(project, apk)
            self.make_apk(apk, synthetic_elf(), tamper=True)
            with self.assertRaisesRegex(ValueError, "does not match"):
                verification.verify(project, apk)
            self.make_apk(apk, synthetic_elf(), license_text=False)
            with self.assertRaises(KeyError):
                verification.verify(project, apk)

    def test_rejects_incorrect_version_even_when_commit_matches(self):
        with tempfile.TemporaryDirectory() as work:
            original = Path(work) / "original.apk"
            changed = Path(work) / "changed.apk"
            self.make_apk(original, synthetic_elf())
            with zipfile.ZipFile(original) as source, zipfile.ZipFile(changed, 'w') as target:
                for entry in source.namelist():
                    data = source.read(entry)
                    if entry == 'assets/rtp2httpd/BUILD-INFO.json':
                        info = json.loads(data)
                        info['version'] = '0.0.0'
                        data = json.dumps(info).encode()
                    target.writestr(entry, data)
            with self.assertRaisesRegex(ValueError, 'version differs'):
                verification.verify(project, changed)

    def test_rejects_missing_management_assets(self):
        with tempfile.TemporaryDirectory() as work:
            apk = Path(work) / "complete.apk"
            self.make_apk(apk, synthetic_elf())
            missing = Path(work) / "missing.apk"
            with zipfile.ZipFile(apk) as source, zipfile.ZipFile(missing, 'w') as target:
                for name in source.namelist():
                    if name != 'assets/management/app.js':
                        target.writestr(name, source.read(name))
            with self.assertRaises(KeyError):
                verification.verify(project, missing)

    def test_verifies_universal_and_arm32_packages_and_rejects_missing_abi(self):
        with tempfile.TemporaryDirectory() as work:
            apk = Path(work) / "test.apk"
            cores = {abi: synthetic_elf(abi=abi) for abi in project.lock["abis"]}
            self.make_apk(apk, cores)
            verification.verify(project, apk, project.lock["abis"])
            self.make_apk(apk, {"armeabi-v7a": cores["armeabi-v7a"]})
            verification.verify(project, apk, ["armeabi-v7a"])
            with self.assertRaisesRegex(ValueError, "do not match requested ABIs"):
                verification.verify(project, apk, project.lock["abis"])
            self.make_apk(apk, {"armeabi-v7a": cores["arm64-v8a"]})
            with self.assertRaisesRegex(ValueError, "does not match APK ABI"):
                verification.verify(project, apk)

    def test_split_packaging_filters_native_code_and_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            resource_apk = work / "resources.apk"
            self.make_apk(resource_apk, synthetic_elf())
            generated = work / "generated"
            metadata = dict(project.lock, cores={})
            for abi in project.lock["abis"]:
                data = synthetic_elf(abi=abi)
                path = generated / "jniLibs" / abi / "librtp2httpd.so"
                path.parent.mkdir(parents=True)
                path.write_bytes(data)
                metadata["cores"][abi] = dict(size=len(data), sha256=hashlib.sha256(data).hexdigest(),
                                              elf=validate_android_elf(data, abi))
            dex = work / "dex"
            dex.mkdir()
            (dex / "classes.dex").write_bytes(b"fixture")
            # Real aapt2 resources APKs contain assets but no lib/ entries.
            with zipfile.ZipFile(resource_apk) as source, zipfile.ZipFile(work / "base.apk", "w") as target:
                for name in source.namelist():
                    if not name.startswith("lib/"):
                        target.writestr(name, source.read(name))
            for abis in [project.lock["abis"], ["armeabi-v7a"], ["arm64-v8a"]]:
                apk = work / "output.apk"
                apk_tools.write_unaligned_apk(work / "base.apk", dex, generated, metadata, {}, abis, apk)
                verification.verify(project, apk, abis)
                with zipfile.ZipFile(apk) as archive:
                    info = json.loads(archive.read("assets/rtp2httpd/BUILD-INFO.json"))
                    self.assertEqual(set(info["cores"]), set(abis))
                    self.assertEqual(len(archive.namelist()), len(set(archive.namelist())))
