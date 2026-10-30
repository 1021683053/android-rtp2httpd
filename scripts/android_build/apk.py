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
from .project import run, selected_abis
from .environment import find_packaging_sdk
from .dependencies import verified_jars
from .verification import verify

def write_unaligned_apk(resources, dex, generated, metadata, values, abis, destination):
    info = dict(metadata, abis=abis, cores={abi: metadata["cores"][abi] for abi in abis})
    with zipfile.ZipFile(resources) as source, zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as target:
        for entry in source.infolist():
            if entry.filename != "assets/rtp2httpd/BUILD-INFO.json":
                target.writestr(entry, source.read(entry.filename))
        target.writestr("assets/rtp2httpd/BUILD-INFO.json", json.dumps(info, indent=2))
        for path in sorted(dex.glob("*.dex")):
            target.write(path, path.name)
        for abi in abis:
            target.write(generated / "jniLibs" / abi / "librtp2httpd.so", "lib/" + abi + "/librtp2httpd.so")
        target.writestr("assets/rtp2httpd/ANDROID-BUILD.json",
                        json.dumps(dict(values, abis=abis, packager="SDK aapt2 + R8 + zipalign"), indent=2))



def package_apk(project, args):
    config = (project.root / "app/build.gradle").read_text()
    dependencies = verified_jars(project)
    resources = project.root / "app/src/main/res"
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
    sdk = find_packaging_sdk(project, args.sdk_root, values["compileSdk"])
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
    generated = project.root / "app/build/generated/native-core"
    abis = selected_abis(project, args.abi)
    for abi in abis:
        if not (generated / "jniLibs" / abi / "librtp2httpd.so").is_file():
            raise RuntimeError("Build the " + abi + " native core first with python3 scripts/android.py native --abi " + args.abi)
    metadata = json.loads((generated / "assets/rtp2httpd/BUILD-INFO.json").read_text())
    output = project.root / "app/build/outputs/apk/release"
    output.mkdir(parents=True, exist_ok=True)
    mapping = project.root / "app/build/outputs/mapping/release"
    mapping.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="sdk-release-", dir=project.root / "app/build") as work:
        work = Path(work)
        namespace = "http://schemas.android.com/apk/res/android"
        ET.register_namespace("android", namespace)
        manifest = ET.parse(project.root / "app/src/main/AndroidManifest.xml")
        manifest.getroot().set("package", values["applicationId"])
        application = manifest.getroot().find("application")
        application.set("{" + namespace + "}extractNativeLibs", "true")
        application.set("{" + namespace + "}debuggable", "false")
        manifest.write(work / "AndroidManifest.xml", encoding="utf-8", xml_declaration=True)
        assets = work / 'assets'
        shutil.copytree(generated / 'assets', assets)
        shutil.copytree(project.root / 'app/src/main/assets', assets, dirs_exist_ok=True)
        compiled_resources = []
        if resources.is_dir() and any(path.is_file() for path in resources.rglob('*')):
            run([tools / 'aapt2', 'compile', '--dir', resources, '-o', work / 'compiled-resources.zip'])
            compiled_resources.append(work / 'compiled-resources.zip')
        generated_java = work / 'generated-java'
        run([tools / "aapt2", "link", "--manifest", work / "AndroidManifest.xml",
             "-I", android_jar, "-A", assets, "--min-sdk-version", values["minSdk"],
             "--target-sdk-version", values["targetSdk"], "--version-code", values["versionCode"],
             "--version-name", values["versionName"], "--proguard", work / "manifest.pro",
             '--java', generated_java, '-o', work / 'resources.apk', *compiled_resources])
        classes = work / "classes"
        classes.mkdir()
        source = sorted((project.root / "app/src/main/java").rglob("*.java")) + sorted(generated_java.rglob('*.java'))
        run([javac, "-source", "8", "-target", "8", "-bootclasspath",
             str(android_jar) + os.pathsep + str(tools / "core-lambda-stubs.jar"),
             "-classpath", os.pathsep.join(str(path) for path in dependencies),
             "-d", classes, *source])
        with zipfile.ZipFile(work / "classes.jar", "w") as archive:
            for path in sorted(classes.rglob("*.class")):
                archive.write(path, str(path.relative_to(classes)))
        # Preserve the manifest service and its Android callbacks, while shrinking
        # internal Java helpers. Reflection rules for YAML are supplied separately.
        (work / "service.pro").write_text('''-keep public class local.rtp2httpd.RelayService {
    public <init>();
    public int onStartCommand(android.content.Intent,int,int);
    public android.os.IBinder onBind(android.content.Intent);
    public void onDestroy();
}
''')
        dex = work / "dex"
        dex.mkdir()
        # Android executes Java 8 base classes, not Java 9 multi-release variants.
        android_dependencies = []
        for dependency in dependencies:
            destination = work / dependency.name
            with zipfile.ZipFile(dependency) as source, zipfile.ZipFile(destination, 'w') as target:
                for name in source.namelist():
                    if name.endswith('.class') and not name.startswith('META-INF/') and name != 'module-info.class':
                        target.writestr(name, source.read(name))
            android_dependencies.append(destination)
        run([java, "-cp", tools / "lib/d8.jar", "com.android.tools.r8.R8", "--release",
             "--min-api", values["minSdk"], "--lib", android_jar,
             "--pg-conf", work / "manifest.pro", "--pg-conf", work / "service.pro",
             "--pg-conf", project.root / 'app/proguard-rules.pro',
             "--pg-map-output", mapping / "mapping.txt", "--output", dex, work / "classes.jar", *android_dependencies])
        groups = [abis] + ([[abi] for abi in abis] if len(abis) > 1 else [])
        elements = []
        for group in groups:
            filename = "app-release-unsigned.apk" if len(group) > 1 else "app-" + group[0] + "-release-unsigned.apk"
            write_unaligned_apk(work / "resources.apk", dex, generated, metadata, values, group, work / "unaligned.apk")
            run([tools / "zipalign", "-f", "4", work / "unaligned.apk", work / "release.apk"])
            verify(project, work / "release.apk", group)
            shutil.copyfile(work / "release.apk", output / filename)
            elements.append({"type": "SINGLE", "filters": [] if len(group) > 1 else [{"filterType": "ABI", "value": group[0]}],
                             "attributes": [], "versionCode": values["versionCode"], "versionName": values["versionName"],
                             "outputFile": filename})
            print("Unsigned Release APK: " + str(output / filename))
        if len(abis) == 1:
            shutil.copyfile(output / elements[0]["outputFile"], output / "app-release-unsigned.apk")
    (output / "output-metadata.json").write_text(json.dumps({
        "version": 3, "artifactType": {"type": "APK", "kind": "Directory"},
        "applicationId": values["applicationId"], "variantName": "release",
        "elements": elements,
        "elementType": "File", "minSdkVersionForDexing": values["minSdk"]}, indent=2) + "\n")
