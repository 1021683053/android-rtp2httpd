import unittest
from scripts.android_build.project import Project
from scripts.android_build.elf import validate_android_elf
project = Project.load()
from .fixtures import synthetic_elf

class ElfTests(unittest.TestCase):
    def test_accepts_android_pie_layout(self):
        info = validate_android_elf(synthetic_elf())
        self.assertEqual(info["needed"], ["libc.so"])

    def test_accepts_arm32_and_rejects_mislabeled_cores(self):
        core = synthetic_elf(abi="armeabi-v7a")
        info = validate_android_elf(core, "armeabi-v7a")
        self.assertEqual(info["bits"], 32)
        self.assertEqual(info["interpreter"], "/system/bin/linker")
        for core, abi in [(core, "arm64-v8a"), (synthetic_elf(), "armeabi-v7a")]:
            with self.assertRaisesRegex(ValueError, "does not match APK ABI"):
                validate_android_elf(core, abi)
        with self.assertRaisesRegex(ValueError, "must use Android"):
            validate_android_elf(synthetic_elf(interpreter="/system/bin/linker64", abi="armeabi-v7a"))

    def test_rejects_desktop_and_unaligned_binaries(self):
        for data in [b"not an ELF", synthetic_elf("/lib/ld-linux-aarch64.so.1"),
                     synthetic_elf(library="libc.so.6"), synthetic_elf(alignment=4096)]:
            with self.subTest(prefix=data[:8]), self.assertRaises(ValueError):
                validate_android_elf(data)

    def test_rejects_truncated_segments(self):
        with self.assertRaises(ValueError):
            validate_android_elf(synthetic_elf()[:400])
