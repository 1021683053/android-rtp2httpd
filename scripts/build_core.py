#!/usr/bin/env python3
"""Fetch a pinned upstream tree, adapt it for Android, and build the real core."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile

from elf_utils import validate_android_elf

ROOT = Path(__file__).resolve().parents[1]
LOCK_FILE = ROOT / "third_party/rtp2httpd.lock.json"
LOCK = json.loads(LOCK_FILE.read_text())


def run(command, **kwargs):
    print("+ " + shlex.join(str(part) for part in command), flush=True)
    return subprocess.run([str(part) for part in command], check=True, **kwargs)


def git_output(source, *args):
    return subprocess.check_output(["git", "-C", str(source), *args], text=True,
                                   stderr=subprocess.DEVNULL).strip()


def fetch_source():
    source = ROOT / "build/upstream" / LOCK["commit"]
    if not (source / ".git").is_dir():
        source.parent.mkdir(parents=True, exist_ok=True)
        run(["git", "init", source])
        run(["git", "-C", source, "remote", "add", "origin", LOCK["repository"]])
    try:
        head = git_output(source, "rev-parse", "HEAD")
    except subprocess.CalledProcessError:
        head = None
    if head != LOCK["commit"]:
        run(["git", "-C", source, "fetch", "--depth", "1", "origin", LOCK["commit"]])
        run(["git", "-C", source, "-c", "advice.detachedHead=false", "checkout", "--detach", "FETCH_HEAD"])
    if git_output(source, "rev-parse", "HEAD") != LOCK["commit"]:
        raise RuntimeError("Upstream commit does not match the lock file")
    return source


def extract_archive(data, destination):
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        members = archive.getmembers()
        for member in members:
            path = Path(member.name)
            if path.is_absolute() or ".." in path.parts or member.islnk():
                raise ValueError("Unsafe source archive path: " + member.name)
            if member.issym():
                target = (destination / path.parent / member.linkname).resolve()
                if not target.is_relative_to(destination.resolve()):
                    raise ValueError("Unsafe source archive link: " + member.name)
            elif not (member.isfile() or member.isdir()):
                raise ValueError("Unsupported source archive member: " + member.name)
        # Git archive contains trusted pinned sources, with paths checked above.
        archive.extractall(destination, members=members)


def replace_once(text, before, after, filename):
    if text.count(before) != 1:
        raise ValueError("Upstream layout changed; review Android adaptation in " + filename)
    return text.replace(before, after, 1)


def adapt_source(source):
    cmake = source / "CMakeLists.txt"
    text = replace_once(cmake.read_text(), 'if(CMAKE_SYSTEM_NAME STREQUAL "Linux")',
                        'if(CMAKE_SYSTEM_NAME STREQUAL "Linux" OR ANDROID)', "CMakeLists.txt")
    text = replace_once(text, 'target_link_libraries(rtp2httpd PRIVATE rt)',
                        'if(NOT ANDROID)\n    target_link_libraries(rtp2httpd PRIVATE rt)\n  endif()',
                        "CMakeLists.txt")
    cmake.write_text(text)
    main = source / "src/rtp2httpd.c"
    main.write_text(replace_once(main.read_text(), 'int main(int argc, char *argv[]) {',
                                'int rtp2httpd_upstream_main(int argc, char *argv[]);\n\n'
                                'int rtp2httpd_upstream_main(int argc, char *argv[]) {', "src/rtp2httpd.c"))
    configuration = source / "src/configuration.c"
    text = configuration.read_text()
    text, index_count = re.subn(r"\bindex\s*\(", "strchr(", text)
    text, rindex_count = re.subn(r"\brindex\s*\(", "strrchr(", text)
    if index_count != 3 or rindex_count != 2:
        raise ValueError("Upstream index/rindex call sites changed; review Bionic adaptation")
    configuration.write_text(text)
    buffers = source / "src/buffer_pool.c"
    buffers.write_text(replace_once(
        buffers.read_text(),
        '#if (defined(__linux__) || defined(__FreeBSD__)) && defined(MFD_ALLOW_SEALING) && defined(F_ADD_SEALS)',
        '#if (defined(__linux__) || defined(__FreeBSD__)) && defined(MFD_ALLOW_SEALING) && defined(F_ADD_SEALS) '
        '&& (!defined(__ANDROID__) || __ANDROID_API__ >= 30)',
        "src/buffer_pool.c"))
    # Android has no writable /tmp. RelayService sets cwd and TMPDIR to private cache.
    # Keep the upstream generated web header intact; no frontend rebuild is needed.
    changed_paths = []
    for filename in sorted((source / "src").rglob("*.c")):
        text = filename.read_text()
        updated = text.replace('"/tmp/', '"./').replace('"/tmp"', '"."')
        if updated != text:
            filename.write_text(updated)
            changed_paths.append(str(filename.relative_to(source)))
    if "src/status.c" not in changed_paths:
        raise ValueError("Expected status shared-memory path was not adapted; review upstream")
    return changed_paths


def prepare_source(original, local_source):
    destination = ROOT / "build/native-source" / LOCK["commit"]
    digest = hashlib.sha256()
    for filename in [LOCK_FILE, Path(__file__), *sorted((ROOT / "native").rglob("*"))]:
        if filename.is_file():
            digest.update(filename.read_bytes())
    fingerprint = digest.hexdigest()
    stamp = destination / ".android-prepared.json"
    if not local_source and stamp.is_file():
        metadata = json.loads(stamp.read_text())
        if metadata.get("fingerprint") == fingerprint:
            return destination, metadata["adapted_tmp_paths"]
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)
    if local_source:
        # Explicit offline source input, for rebuilding the accompanying source bundle.
        shutil.copytree(original, destination, dirs_exist_ok=True, symlinks=True,
                        ignore=shutil.ignore_patterns(".git", ".android-prepared.json"))
    else:
        data = subprocess.check_output(["git", "-C", str(original), "archive", "HEAD"])
        extract_archive(data, destination)
    changed_paths = adapt_source(destination)
    stamp.write_text(json.dumps({"commit": LOCK["commit"], "fingerprint": fingerprint,
                                 "adapted_tmp_paths": changed_paths}, indent=2) + "\n")
    return destination, changed_paths


def find_sdk(explicit):
    if explicit:
        return Path(explicit).expanduser().resolve()
    for name in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        if os.environ.get(name):
            return Path(os.environ[name]).expanduser().resolve()
    properties = ROOT / "local.properties"
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


def find_ndk(sdk):
    if os.environ.get("ANDROID_NDK_HOME"):
        return Path(os.environ["ANDROID_NDK_HOME"]).expanduser().resolve()
    for root in sdk_roots(sdk):
        candidate = root / "ndk" / LOCK["ndk_version"]
        properties = candidate / "source.properties"
        if properties.is_file():
            revision = re.search(r"^Pkg.Revision\s*=\s*(\S+)", properties.read_text(), re.MULTILINE)
            if revision and revision.group(1) == LOCK["ndk_version"]:
                return candidate.resolve()
    return (sdk / "ndk" / LOCK["ndk_version"]).resolve()


def tools(sdk):
    ndk = find_ndk(sdk)
    ndk_properties = ndk / "source.properties"
    cmake = sdk / "cmake" / LOCK["cmake_version"] / "bin/cmake"
    if not cmake.is_file() and shutil.which("cmake"):
        cmake = Path(shutil.which("cmake"))
    missing = []
    if not ndk_properties.is_file():
        if os.environ.get("ANDROID_NDK_HOME"):
            raise RuntimeError("ANDROID_NDK_HOME does not contain an Android NDK")
        missing.append("ndk;" + LOCK["ndk_version"])
    if not cmake.is_file():
        missing.append("cmake;" + LOCK["cmake_version"])
    if missing:
        raise RuntimeError("Missing build tools: " + ", ".join(missing)
                           + ". Automatic installation is disabled. Install them manually in an SDK you choose; "
                           "see docs/ENVIRONMENT.md. No SDK files were changed.")
    revision = re.search(r"^Pkg.Revision\s*=\s*(\S+)", ndk_properties.read_text(), re.MULTILINE)
    if not revision or revision.group(1) != LOCK["ndk_version"]:
        raise RuntimeError("Use the pinned NDK " + LOCK["ndk_version"])
    hosts = sorted((ndk / "toolchains/llvm/prebuilt").glob("*"))
    hosts = [host for host in hosts if (host / "bin/llvm-strip").is_file()]
    if len(hosts) != 1:
        raise RuntimeError("Expected one NDK host toolchain with llvm-strip")
    return ndk, cmake, hosts[0] / "bin/llvm-strip"


def create_source_bundle(original, local_source, metadata):
    output = ROOT / "build/outputs/native" / ("rtp2httpd-" + LOCK["version"] + "-source.tar.gz")
    output.parent.mkdir(parents=True, exist_ok=True)
    allowed = [".gitattributes", ".gitignore", "README.md", "build.gradle", "settings.gradle", "gradle.properties",
               "gradlew", "gradlew.bat", "gradle", "app/build.gradle", "app/src/main/java",
               "app/src/main/AndroidManifest.xml", "app/src/test", "native", "scripts", "third_party", "docs"]
    with tempfile.TemporaryDirectory(prefix="rtp2httpd-source-", dir=output.parent) as work:
        work = Path(work)
        pristine = work / "upstream"
        pristine.mkdir()
        if local_source:
            shutil.copytree(original, pristine, dirs_exist_ok=True, symlinks=True,
                            ignore=shutil.ignore_patterns(".git", ".android-prepared.json"))
        else:
            data = subprocess.check_output(["git", "-C", str(original), "archive", "HEAD"])
            extract_archive(data, pristine)
        temporary = work / "source.tar.gz"
        with tarfile.open(temporary, "w:gz") as archive:
            archive.add(pristine, arcname="rtp2httpd-source/upstream")
            for relative in allowed:
                path = ROOT / relative
                if path.exists():
                    archive.add(path, arcname="rtp2httpd-source/android-rtp2httpd/" + relative,
                                filter=lambda info: None if "__pycache__" in Path(info.name).parts else info)
            info_data = (json.dumps(metadata, indent=2) + "\n").encode()
            info = tarfile.TarInfo("rtp2httpd-source/BUILD-INFO.json")
            info.size = len(info_data)
            archive.addfile(info, io.BytesIO(info_data))
        temporary.replace(output)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk-root")
    parser.add_argument("--fetch-only", action="store_true")
    parser.add_argument("--print-ndk-path", action="store_true", help="Locate an installed pinned NDK without downloading")
    parser.add_argument("--source-dir", type=Path,
                        default=os.environ.get("RTP2HTTPD_SOURCE_DIR"),
                        help="Explicit pristine local source, e.g. from the source bundle")
    args = parser.parse_args()
    if args.print_ndk_path:
        print(find_ndk(find_sdk(args.sdk_root)))
        return
    if args.fetch_only:
        original = args.source_dir.resolve() if args.source_dir else fetch_source()
        print("Upstream source: " + str(original))
        return
    # Validate installed tools before fetching sources or creating build outputs.
    ndk, cmake, strip = tools(find_sdk(args.sdk_root))
    original = args.source_dir.resolve() if args.source_dir else fetch_source()
    source, changed_paths = prepare_source(original, args.source_dir is not None)
    build = ROOT / "build/native" / LOCK["abi"]
    environment = dict(os.environ, RELEASE_VERSION=LOCK["version"])
    run([cmake, "-S", ROOT / "native", "-B", build, "-G", "Unix Makefiles",
         "-DCMAKE_TOOLCHAIN_FILE=" + str(ndk / "build/cmake/android.toolchain.cmake"),
         "-DANDROID_ABI=" + LOCK["abi"], "-DANDROID_PLATFORM=android-" + str(LOCK["android_api"]),
         "-DCMAKE_BUILD_TYPE=Release", "-DCMAKE_C_FLAGS_RELEASE=-Oz -DNDEBUG",
         "-DRTP2HTTPD_SOURCE_DIR=" + str(source)], env=environment)
    run([cmake, "--build", build, "--parallel", str(os.cpu_count() or 2)], env=environment)
    generated = ROOT / "app/build/generated/native-core"
    library = generated / "jniLibs" / LOCK["abi"] / "librtp2httpd.so"
    library.parent.mkdir(parents=True, exist_ok=True)
    temporary = library.with_suffix(".so.tmp")
    try:
        run([strip, "--strip-all", "-o", temporary, build / "bin/rtp2httpd"])
        data = temporary.read_bytes()
        elf = validate_android_elf(data)
        temporary.chmod(0o755)
        temporary.replace(library)
    finally:
        temporary.unlink(missing_ok=True)
    cmake_used = subprocess.check_output([str(cmake), "--version"], text=True).splitlines()[0]
    metadata = dict(LOCK, sha256=hashlib.sha256(data).hexdigest(), size=len(data), elf=elf, cmake_used=cmake_used,
                    adapted_tmp_paths=changed_paths, local_source_override=args.source_dir is not None)
    assets = generated / "assets/rtp2httpd"
    assets.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source / "LICENSE", assets / "LICENSE")
    (assets / "BUILD-INFO.json").write_text(json.dumps(metadata, indent=2) + "\n")
    bundle = create_source_bundle(original, args.source_dir is not None, metadata)
    print("Android core: " + str(library) + " (" + str(len(data)) + " bytes)")
    print("Corresponding source: " + str(bundle))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print("Native build failed: " + str(error), file=sys.stderr)
        sys.exit(1)
