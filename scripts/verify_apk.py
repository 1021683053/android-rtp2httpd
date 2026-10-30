#!/usr/bin/env python3
"""Reject shell-only APKs or APKs containing a desktop Linux executable."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import zipfile
from elf_utils import validate_android_elf


def verify(apk):
    root = Path(__file__).resolve().parents[1]
    expected = json.loads((root / "third_party/rtp2httpd.lock.json").read_text())
    with zipfile.ZipFile(apk) as archive:
        name = "lib/arm64-v8a/librtp2httpd.so"
        if name not in archive.namelist():
            raise ValueError("APK has no Android ARM64 core; a service-only APK must not be released")
        other_abis = [entry for entry in archive.namelist() if entry.startswith("lib/") and entry != name]
        if other_abis:
            raise ValueError("Unexpected native APK entries: " + repr(other_abis))
        data = archive.read(name)
        validate_android_elf(data)
        info = json.loads(archive.read("assets/rtp2httpd/BUILD-INFO.json"))
        if info.get("commit") != expected["commit"] or info.get("ndk_version") != expected["ndk_version"]:
            raise ValueError("Packaged core version differs from the lock file")
        if info.get("sha256") != hashlib.sha256(data).hexdigest() or info.get("size") != len(data):
            raise ValueError("Packaged core does not match its build metadata")
        if len(archive.read("assets/rtp2httpd/LICENSE")) < 1000:
            raise ValueError("Missing or incomplete upstream license")
    print("Verified APK: " + str(apk))
    print("Core: " + str(len(data)) + " bytes; upstream " + info["version"] + " @ " + info["commit"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("apk", type=Path)
    args = parser.parse_args()
    try:
        verify(args.apk)
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as error:
        print("APK verification failed: " + str(error), file=sys.stderr)
        sys.exit(1)
