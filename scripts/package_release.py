#!/usr/bin/env python3
"""Build this dependency-free service with SDK tools when Gradle cannot run."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile

from build_core import ROOT, find_sdk, run, sdk_roots
from verify_apk import verify


def required_sdk_files(sdk, compile_sdk):
    tools = sdk / "build-tools/35.0.0"
    return [sdk / "platforms" / ("android-" + str(compile_sdk)) / "android.jar",
            tools / "aapt2", tools / "zipalign", tools / "lib/d8.jar", tools / "core-lambda-stubs.jar"]


def find_packaging_sdk(explicit, compile_sdk):
    preferred = find_sdk(explicit).expanduser().resolve()
    candidates = [preferred] if explicit else sdk_roots(preferred)
    checked = set()
    for candidate in candidates:
        candidate = candidate.expanduser().resolve()
        if candidate in checked:
            continue
        checked.add(candidate)
        if all(path.is_file() for path in required_sdk_files(candidate, compile_sdk)):
            if candidate != preferred:
                print("Selected installed packaging SDK: " + str(candidate)
                      + " (preferred SDK is missing Android " + str(compile_sdk)
                      + " or Build Tools 35.0.0 components)", file=sys.stderr)
            return candidate
    missing = [str(path) for path in required_sdk_files(preferred, compile_sdk) if not path.is_file()]
    raise RuntimeError("No complete packaging SDK found. Missing from " + str(preferred) + ": "
                       + ", ".join(missing) + ". Install platforms/android-" + str(compile_sdk)
                       + " and build-tools/35.0.0, or select a complete SDK with --sdk-root.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk-root")
    parser.add_argument("--print-sdk-path", action="store_true", help="Find a complete packaging SDK without building")
    args = parser.parse_args()
    config = (ROOT / "app/build.gradle").read_text()
    if re.search(r"\b(?:implementation|api|runtimeOnly|compileOnly)\s", config):
        raise RuntimeError("SDK-only packaging does not resolve runtime dependencies; use Gradle")
    resources = ROOT / "app/src/main/res"
    if resources.exists() and any(path.is_file() for path in resources.rglob("*")):
        raise RuntimeError("SDK-only packaging is limited to this service without custom resources")
    values = {}
    for name in ("compileSdk", "targetSdk", "minSdk", "versionCode"):
        match = re.search(r"\b" + name + r"\s+(\d+)", config)
        if not match:
            raise RuntimeError("Cannot resolve " + name + "; use Gradle")
        values[name] = int(match.group(1))
    for name in ("applicationId", "versionName"):
        match = re.search(r"\b" + name + r"\s+'([^']+)'", config)
        if not match:
            raise RuntimeError("Cannot resolve " + name + "; use Gradle")
        values[name] = match.group(1)
    sdk = find_packaging_sdk(args.sdk_root, values["compileSdk"])
    if args.print_sdk_path:
        print(sdk)
        return
    tools = sdk / "build-tools/35.0.0"
    android_jar = sdk / "platforms" / ("android-" + str(values["compileSdk"])) / "android.jar"
    java_home = os.environ.get("JAVA_HOME")
    if not java_home and sys.platform == "darwin":
        java_home = subprocess.check_output(["/usr/libexec/java_home", "-v", "17"], text=True).strip()
    if not java_home:
        raise RuntimeError("Set JAVA_HOME to JDK 17")
    java = Path(java_home) / "bin/java"
    javac = Path(java_home) / "bin/javac"
    for path in (java, javac, android_jar, tools / "aapt2", tools / "zipalign", tools / "lib/d8.jar"):
        if not path.is_file():
            raise RuntimeError("Missing build tool: " + str(path))
    generated = ROOT / "app/build/generated/native-core"
    core = generated / "jniLibs/arm64-v8a/librtp2httpd.so"
    if not core.is_file():
        raise RuntimeError("Build the native core first with scripts/build_core.py")
    output = ROOT / "app/build/outputs/apk/release"
    output.mkdir(parents=True, exist_ok=True)
    mapping = ROOT / "app/build/outputs/mapping/release"
    mapping.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="sdk-release-", dir=ROOT / "app/build") as work:
        work = Path(work)
        namespace = "http://schemas.android.com/apk/res/android"
        ET.register_namespace("android", namespace)
        manifest = ET.parse(ROOT / "app/src/main/AndroidManifest.xml")
        manifest.getroot().set("package", values["applicationId"])
        application = manifest.getroot().find("application")
        application.set("{" + namespace + "}extractNativeLibs", "true")
        application.set("{" + namespace + "}debuggable", "false")
        manifest.write(work / "AndroidManifest.xml", encoding="utf-8", xml_declaration=True)
        run([tools / "aapt2", "link", "--manifest", work / "AndroidManifest.xml",
             "-I", android_jar, "-A", generated / "assets", "--min-sdk-version", values["minSdk"],
             "--target-sdk-version", values["targetSdk"], "--version-code", values["versionCode"],
             "--version-name", values["versionName"], "--proguard", work / "manifest.pro",
             "-o", work / "resources.apk"])
        classes = work / "classes"
        classes.mkdir()
        source = sorted((ROOT / "app/src/main/java").rglob("*.java"))
        run([javac, "-source", "8", "-target", "8", "-bootclasspath",
             str(android_jar) + os.pathsep + str(tools / "core-lambda-stubs.jar"),
             "-d", classes, *source])
        with zipfile.ZipFile(work / "classes.jar", "w") as archive:
            for path in sorted(classes.rglob("*.class")):
                archive.write(path, str(path.relative_to(classes)))
        # Preserve the manifest service and its Android callbacks, while shrinking
        # internal Java helpers. This project has no reflection-based dependencies.
        (work / "service.pro").write_text('''-keep public class local.rtp2httpd.RelayService {
    public <init>();
    public int onStartCommand(android.content.Intent,int,int);
    public android.os.IBinder onBind(android.content.Intent);
    public void onDestroy();
}
''')
        dex = work / "dex"
        dex.mkdir()
        run([java, "-cp", tools / "lib/d8.jar", "com.android.tools.r8.R8", "--release",
             "--min-api", values["minSdk"], "--lib", android_jar,
             "--pg-conf", work / "manifest.pro", "--pg-conf", work / "service.pro",
             "--pg-map-output", mapping / "mapping.txt", "--output", dex, work / "classes.jar"])
        shutil.copyfile(work / "resources.apk", work / "unaligned.apk")
        with zipfile.ZipFile(work / "unaligned.apk", "a", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(dex.glob("*.dex")):
                archive.write(path, path.name)
            archive.write(core, "lib/arm64-v8a/librtp2httpd.so")
            archive.writestr("assets/rtp2httpd/ANDROID-BUILD.json",
                             json.dumps(dict(values, packager="SDK aapt2 + R8 + zipalign"), indent=2))
        run([tools / "zipalign", "-f", "4", work / "unaligned.apk", work / "release.apk"])
        verify(work / "release.apk")
        shutil.copyfile(work / "release.apk", output / "app-release-unsigned.apk")
    (output / "output-metadata.json").write_text(json.dumps({
        "version": 3, "artifactType": {"type": "APK", "kind": "Directory"},
        "applicationId": values["applicationId"], "variantName": "release",
        "elements": [{"type": "SINGLE", "filters": [], "attributes": [],
                      "versionCode": values["versionCode"], "versionName": values["versionName"],
                      "outputFile": "app-release-unsigned.apk"}],
        "elementType": "File", "minSdkVersionForDexing": values["minSdk"]}, indent=2) + "\n")
    print("Unsigned Release APK: " + str(output / "app-release-unsigned.apk"))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print("SDK-only packaging failed: " + str(error), file=sys.stderr)
        sys.exit(1)
