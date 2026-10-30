import hashlib
import json
import zipfile
from .elf import validate_android_elf

def verify(project, apk, expected_abis=None):
    root = project.root
    expected = project.lock
    with zipfile.ZipFile(apk) as archive:
        native = [entry for entry in archive.namelist() if entry.startswith("lib/") and not entry.endswith("/")]
        if not native:
            raise ValueError("APK has no Android native core; a service-only APK must not be released")
        allowed = {"lib/" + abi + "/librtp2httpd.so": abi for abi in expected["abis"]}
        if len(native) != len(set(native)) or set(native) - set(allowed):
            raise ValueError("Unexpected or duplicate native APK entries: " + repr(native))
        abis = [allowed[name] for name in native]
        if expected_abis is not None and set(abis) != set(expected_abis):
            raise ValueError("Packaged ABIs do not match requested ABIs: " + repr(abis))
        info = json.loads(archive.read("assets/rtp2httpd/BUILD-INFO.json"))
        if any(info.get(key) != expected[key] for key in ("version", "commit", "ndk_version")):
            raise ValueError("Packaged core version differs from the lock file")
        if set(info.get("abis", [])) != set(info.get("cores", {})) or set(info["abis"]) - set(expected["abis"]):
            raise ValueError("Invalid build metadata ABI list")
        sizes = {}
        for name in native:
            abi = allowed[name]
            data = archive.read(name)
            elf = validate_android_elf(data, abi)
            core = info["cores"].get(abi, {})
            if (core.get("sha256") != hashlib.sha256(data).hexdigest() or core.get("size") != len(data)
                    or core.get("elf") != elf):
                raise ValueError("Packaged core does not match its build metadata: " + abi)
            sizes[abi] = len(data)
        if len(archive.read("assets/rtp2httpd/LICENSE")) < 1000:
            raise ValueError("Missing or incomplete upstream license")
        for path in (root / 'app/src/main/assets').rglob('*'):
            if path.is_file():
                entry = 'assets/' + path.relative_to(root / 'app/src/main/assets').as_posix()
                if archive.read(entry) != path.read_bytes():
                    raise ValueError('Missing or stale management asset: ' + entry)
    print("Verified APK: " + str(apk))
    print("Cores: " + repr(sizes) + "; upstream " + info["version"] + " @ " + info["commit"])
