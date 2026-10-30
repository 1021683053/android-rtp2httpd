import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys

def find_sdk(project, explicit):
    if explicit:
        return Path(explicit).expanduser().resolve()
    for name in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        if os.environ.get(name):
            return Path(os.environ[name]).expanduser().resolve()
    properties = project.root / "local.properties"
    if properties.is_file():
        for line in properties.read_text().splitlines():
            if line.startswith("sdk.dir="):
                return Path(line.split("=", 1)[1].replace("\\ ", " ").replace("\\:", ":")).expanduser().resolve()
    default = Path.home() / ("Library/Android/sdk" if platform.system() == "Darwin" else "Android/Sdk")
    if default.is_dir():
        return default
    raise RuntimeError("Set ANDROID_HOME or sdk.dir in local.properties to your Android SDK")



def sdk_roots(sdk):
    roots = [sdk]
    for name in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        if os.environ.get(name):
            roots.append(Path(os.environ[name]).expanduser())
    roots.extend([Path.home() / "Library/Android/sdk", Path.home() / "Android/Sdk",
                  Path("/opt/homebrew/share/android-commandlinetools")])
    manager = shutil.which("sdkmanager")
    if manager:
        path = Path(manager).resolve()
        if len(path.parents) > 3 and path.parents[2].name == "cmdline-tools":
            roots.append(path.parents[3])
    return roots



def find_ndk(project, sdk):
    if os.environ.get("ANDROID_NDK_HOME"):
        return Path(os.environ["ANDROID_NDK_HOME"]).expanduser().resolve()
    for root in sdk_roots(sdk):
        candidate = root / "ndk" / project.lock["ndk_version"]
        properties = candidate / "source.properties"
        if properties.is_file():
            revision = re.search(r"^Pkg.Revision\s*=\s*(\S+)", properties.read_text(), re.MULTILINE)
            if revision and revision.group(1) == project.lock["ndk_version"]:
                return candidate.resolve()
    return (sdk / "ndk" / project.lock["ndk_version"]).resolve()



def tools(project, sdk):
    ndk = find_ndk(project, sdk)
    ndk_properties = ndk / "source.properties"
    cmake = sdk / "cmake" / project.lock["cmake_version"] / "bin/cmake"
    if not cmake.is_file() and shutil.which("cmake"):
        cmake = Path(shutil.which("cmake"))
    missing = []
    if not ndk_properties.is_file():
        if os.environ.get("ANDROID_NDK_HOME"):
            raise RuntimeError("ANDROID_NDK_HOME does not contain an Android NDK")
        missing.append("ndk;" + project.lock["ndk_version"])
    if not cmake.is_file():
        missing.append("cmake;" + project.lock["cmake_version"])
    if missing:
        raise RuntimeError("Missing build tools: " + ", ".join(missing)
                           + ". Automatic installation is disabled. Install them manually in an SDK you choose; "
                           "see docs/development/environment.md. No SDK files were changed.")
    revision = re.search(r"^Pkg.Revision\s*=\s*(\S+)", ndk_properties.read_text(), re.MULTILINE)
    if not revision or revision.group(1) != project.lock["ndk_version"]:
        raise RuntimeError("Use the pinned NDK " + project.lock["ndk_version"])
    hosts = sorted((ndk / "toolchains/llvm/prebuilt").glob("*"))
    hosts = [host for host in hosts if (host / "bin/llvm-strip").is_file()]
    if len(hosts) != 1:
        raise RuntimeError("Expected one NDK host toolchain with llvm-strip")
    return ndk, cmake, hosts[0] / "bin/llvm-strip"



def required_sdk_files(sdk, compile_sdk):
    tools = sdk / "build-tools/35.0.0"
    return [sdk / "platforms" / ("android-" + str(compile_sdk)) / "android.jar",
            tools / "aapt2", tools / "zipalign", tools / "lib/d8.jar", tools / "core-lambda-stubs.jar"]



def find_packaging_sdk(project, explicit, compile_sdk):
    preferred = find_sdk(project, explicit).expanduser().resolve()
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



def find_jdk():
    location = os.environ.get("JAVA_HOME")
    if not location and sys.platform == "darwin":
        try:
            location = subprocess.check_output(["/usr/libexec/java_home", "-v", "17"],
                                               text=True, stderr=subprocess.DEVNULL).strip()
        except subprocess.CalledProcessError:
            pass
    if not location:
        raise RuntimeError("Set JAVA_HOME to an existing JDK 17; see docs/development/environment.md")
    jdk = Path(location).expanduser().resolve()
    release = jdk / "release"
    if not release.is_file() or not all((jdk / "bin" / command).is_file() for command in ("java", "javac")):
        raise RuntimeError("JAVA_HOME does not contain a complete JDK 17: " + str(jdk))
    version = re.search(r'^JAVA_VERSION="([^"]+)"', release.read_text(), re.MULTILINE)
    if not version or not version.group(1).startswith("17."):
        raise RuntimeError("This project requires JDK 17. Select it for this command with JAVA_HOME; "
                           "the system Java selection was not changed.")
    return jdk



def check(project, explicit_sdk=None):
    for command in ("git", "make"):
        if not shutil.which(command):
            raise RuntimeError("Missing executable: " + command + "; install it yourself; see docs/development/environment.md")
    match = re.search(r"\bcompileSdk\s+(\d+)", (project.root / "app/build.gradle").read_text())
    if not match:
        raise RuntimeError("Cannot resolve compileSdk from app/build.gradle")
    jdk = find_jdk()
    sdk = find_packaging_sdk(project, explicit_sdk, int(match.group(1)))
    ndk, cmake, strip = tools(project, sdk)
    version = subprocess.check_output([str(cmake), "--version"], text=True)
    match = re.search(r"cmake version (\d+)\.(\d+)", version)
    if not match or (int(match.group(1)), int(match.group(2))) < (3, 22):
        raise RuntimeError("CMake 3.22 or newer is required; select an installed version in PATH")
    return {"JDK": jdk, "SDK": sdk, "NDK " + project.lock["ndk_version"]: ndk, "CMake": cmake}
