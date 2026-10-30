import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile
from .project import run

def git_output(source, *args):
    return subprocess.check_output(["git", "-C", str(source), *args], text=True,
                                   stderr=subprocess.DEVNULL).strip()



def fetch_source(project):
    source = project.root / "build/upstream" / project.lock["commit"]
    if not (source / ".git").is_dir():
        source.parent.mkdir(parents=True, exist_ok=True)
        run(["git", "init", source])
        run(["git", "-C", source, "remote", "add", "origin", project.lock["repository"]])
    try:
        head = git_output(source, "rev-parse", "HEAD")
    except subprocess.CalledProcessError:
        head = None
    if head != project.lock["commit"]:
        run(["git", "-C", source, "fetch", "--depth", "1", "origin", project.lock["commit"]])
        run(["git", "-C", source, "-c", "advice.detachedHead=false", "checkout", "--detach", "FETCH_HEAD"])
    if git_output(source, "rev-parse", "HEAD") != project.lock["commit"]:
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



def prepare_source(project, original, local_source):
    destination = project.root / "build/native-source" / project.lock["commit"]
    digest = hashlib.sha256()
    for filename in [project.lock_file, *sorted((project.root / "scripts/android_build").glob("*.py")), *sorted((project.root / "native").rglob("*"))]:
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
    stamp.write_text(json.dumps({"commit": project.lock["commit"], "fingerprint": fingerprint,
                                 "adapted_tmp_paths": changed_paths}, indent=2) + "\n")
    return destination, changed_paths



def create_source_bundle(project, original, local_source, metadata):
    output = project.root / "build/outputs/native" / ("rtp2httpd-" + project.lock["version"] + "-source.tar.gz")
    output.parent.mkdir(parents=True, exist_ok=True)
    allowed = [".github", ".gitattributes", ".gitignore", "README.md", "build.gradle", "settings.gradle", "gradle.properties",
               "gradlew", "gradlew.bat", "gradle", "app/build.gradle", "app/src/main/java",
               "app/src/main/AndroidManifest.xml", "app/src/main/assets", "app/src/main/res", "app/proguard-rules.pro", "app/src/test", "artwork", "native", "scripts", "third_party", "docs"]
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
                path = project.root / relative
                if path.exists():
                    archive.add(path, arcname="rtp2httpd-source/android-rtp2httpd/" + relative,
                                filter=lambda info: None if "__pycache__" in Path(info.name).parts else info)
            info_data = (json.dumps(metadata, indent=2) + "\n").encode()
            info = tarfile.TarInfo("rtp2httpd-source/BUILD-INFO.json")
            info.size = len(info_data)
            archive.addfile(info, io.BytesIO(info_data))
        temporary.replace(output)
    return output
