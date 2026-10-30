import hashlib
import json
import os
import shutil
import subprocess
from .project import run, selected_abis
from .environment import tools, find_sdk
from .source import fetch_source, prepare_source, create_source_bundle
from .elf import validate_android_elf

def build_native(project, args):
    # Validate installed tools before fetching sources or creating build outputs.
    ndk, cmake, strip = tools(project, find_sdk(project, args.sdk_root))
    original = args.source_dir.resolve() if args.source_dir else fetch_source(project)
    source, changed_paths = prepare_source(project, original, args.source_dir is not None)
    abis = selected_abis(project, args.abi)
    environment = dict(os.environ, RELEASE_VERSION=project.lock["version"])
    generated = project.root / "app/build/generated/native-core"
    cores = {}
    for abi in abis:
        build = project.root / "build/native" / abi
        run([cmake, "-S", project.root / "native", "-B", build, "-G", "Unix Makefiles",
             "-DCMAKE_TOOLCHAIN_FILE=" + str(ndk / "build/cmake/android.toolchain.cmake"),
             "-DANDROID_ABI=" + abi, "-DANDROID_PLATFORM=android-" + str(project.lock["android_api"]),
             "-DCMAKE_BUILD_TYPE=Release", "-DCMAKE_C_FLAGS_RELEASE=-Oz -DNDEBUG",
             "-DRTP2HTTPD_SOURCE_DIR=" + str(source)], env=environment)
        run([cmake, "--build", build, "--parallel", str(os.cpu_count() or 2)], env=environment)
        library = generated / "jniLibs" / abi / "librtp2httpd.so"
        library.parent.mkdir(parents=True, exist_ok=True)
        temporary = library.with_suffix(".so.tmp")
        try:
            run([strip, "--strip-all", "-o", temporary, build / "bin/rtp2httpd"])
            data = temporary.read_bytes()
            elf = validate_android_elf(data, abi)
            temporary.chmod(0o755)
            temporary.replace(library)
        finally:
            temporary.unlink(missing_ok=True)
        cores[abi] = dict(sha256=hashlib.sha256(data).hexdigest(), size=len(data), elf=elf)
        print("Android core: " + str(library) + " (" + str(len(data)) + " bytes)")
    # A later single-ABI build must not accidentally package cached cores for other ABIs.
    for directory in (generated / "jniLibs").iterdir():
        if directory.is_dir() and directory.name not in abis:
            shutil.rmtree(directory)
    cmake_used = subprocess.check_output([str(cmake), "--version"], text=True).splitlines()[0]
    metadata = dict(project.lock, abis=abis, cores=cores, cmake_used=cmake_used,
                    adapted_tmp_paths=changed_paths, local_source_override=args.source_dir is not None)
    assets = generated / "assets/rtp2httpd"
    assets.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source / "LICENSE", assets / "LICENSE")
    (assets / "BUILD-INFO.json").write_text(json.dumps(metadata, indent=2) + "\n")
    bundle = create_source_bundle(project, original, args.source_dir is not None, metadata)
    print("Corresponding source: " + str(bundle))
