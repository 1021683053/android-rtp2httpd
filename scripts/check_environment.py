#!/usr/bin/env python3
"""Check existing build prerequisites. Never install or update SDK components."""
import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

from build_core import LOCK, ROOT, tools
from package_release import find_packaging_sdk


def find_jdk():
    location = os.environ.get("JAVA_HOME")
    if not location and sys.platform == "darwin":
        try:
            location = subprocess.check_output(["/usr/libexec/java_home", "-v", "17"],
                                               text=True, stderr=subprocess.DEVNULL).strip()
        except subprocess.CalledProcessError:
            pass
    if not location:
        raise RuntimeError("Set JAVA_HOME to an existing JDK 17; see docs/ENVIRONMENT.md")
    jdk = Path(location).expanduser().resolve()
    release = jdk / "release"
    if not release.is_file() or not all((jdk / "bin" / command).is_file() for command in ("java", "javac")):
        raise RuntimeError("JAVA_HOME does not contain a complete JDK 17: " + str(jdk))
    version = re.search(r'^JAVA_VERSION="([^"]+)"', release.read_text(), re.MULTILINE)
    if not version or not version.group(1).startswith("17."):
        raise RuntimeError("This project requires JDK 17. Select it for this command with JAVA_HOME; "
                           "the system Java selection was not changed.")
    return jdk


def check(explicit_sdk=None):
    for command in ("git", "make"):
        if not shutil.which(command):
            raise RuntimeError("Missing executable: " + command + "; install it yourself; see docs/ENVIRONMENT.md")
    match = re.search(r"\bcompileSdk\s+(\d+)", (ROOT / "app/build.gradle").read_text())
    if not match:
        raise RuntimeError("Cannot resolve compileSdk from app/build.gradle")
    jdk = find_jdk()
    sdk = find_packaging_sdk(explicit_sdk, int(match.group(1)))
    ndk, cmake, strip = tools(sdk)
    version = subprocess.check_output([str(cmake), "--version"], text=True)
    match = re.search(r"cmake version (\d+)\.(\d+)", version)
    if not match or (int(match.group(1)), int(match.group(2))) < (3, 22):
        raise RuntimeError("CMake 3.22 or newer is required; select an installed version in PATH")
    return {"JDK": jdk, "SDK": sdk, "NDK " + LOCK["ndk_version"]: ndk, "CMake": cmake}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk-root")
    args = parser.parse_args()
    try:
        for label, location in check(args.sdk_root).items():
            print(label + ": " + str(location))
        print("Environment check passed. No tools were installed or updated.")
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print("Environment check failed: " + str(error), file=sys.stderr)
        sys.exit(1)
