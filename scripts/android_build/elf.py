"""Validate the executable we package as a native library, without host tools."""
import struct


def validate_android_elf(data, expected_abi=None):
    if len(data) < 64 or data[:4] != b"\x7fELF" or data[5] != 1 or data[4] not in (1, 2):
        raise ValueError("Core must be a little-endian ELF32 or ELF64 executable")
    is_64 = data[4] == 2
    abi = "arm64-v8a" if is_64 else "armeabi-v7a"
    header = struct.unpack_from("<16sHHIQQQIHHHHHH" if is_64 else "<16sHHIIIIIHHHHHH", data)
    if header[1] != 3 or header[2] != (183 if is_64 else 40) or header[4] == 0:
        raise ValueError("Core must be an Android ARM PIE executable with an entry point")
    if expected_abi is not None and expected_abi != abi:
        raise ValueError("Core ELF architecture does not match APK ABI " + expected_abi)
    offset, entry_size, count = header[5], header[9], header[10]
    if entry_size != (56 if is_64 else 32) or not count or offset + count * entry_size > len(data):
        raise ValueError("Invalid ELF program headers")
    segments = [struct.unpack_from("<IIQQQQQQ" if is_64 else "<IIIIIIII", data,
                                  offset + i * entry_size) for i in range(count)]
    interpreter = None
    dynamic = None
    loads = []
    for segment in segments:
        if is_64:
            kind, flags, position, address, physical, size, memory_size, alignment = segment
        else:
            kind, position, address, physical, size, memory_size, flags, alignment = segment
        if position + size > len(data):
            raise ValueError("ELF segment exceeds file size")
        if kind == 1:
            if alignment < 16384 or (address - position) % 16384:
                raise ValueError("Core is not aligned for Android 16KB memory pages")
            loads.append((position, address, size))
        elif kind == 3:
            interpreter = data[position:position + size].rstrip(b"\0").decode("ascii")
        elif kind == 2:
            dynamic = (position, size)
    expected_linker = "/system/bin/linker64" if is_64 else "/system/bin/linker"
    if interpreter != expected_linker or dynamic is None or not loads:
        raise ValueError("Core must use Android " + expected_linker + ", not a desktop Linux runtime")
    dynamic_entry_size = 16 if is_64 else 8
    if dynamic[1] % dynamic_entry_size:
        raise ValueError("Invalid ELF dynamic segment size")
    needed, string_address, string_size = [], None, None
    for position in range(dynamic[0], dynamic[0] + dynamic[1], dynamic_entry_size):
        tag, value = struct.unpack_from("<qQ" if is_64 else "<iI", data, position)
        if tag == 0:
            break
        if tag == 1:
            needed.append(value)
        elif tag == 5:
            string_address = value
        elif tag == 10:
            string_size = value
    if string_address is None or string_size is None:
        raise ValueError("Missing ELF dynamic string table")
    string_table = None
    for position, address, size in loads:
        if address <= string_address and string_address + string_size <= address + size:
            start = position + string_address - address
            string_table = data[start:start + string_size]
            break
    if string_table is None:
        raise ValueError("ELF dynamic string table is outside loadable segments")
    libraries = []
    for offset in needed:
        end = string_table.find(b"\0", offset)
        if offset >= len(string_table) or end < 0:
            raise ValueError("Invalid ELF library name")
        libraries.append(string_table[offset:end].decode("ascii"))
    unsupported = set(libraries) - {"libc.so", "libm.so", "libdl.so", "liblog.so"}
    if unsupported or "libc.so" not in libraries:
        raise ValueError("Unexpected runtime libraries: " + repr(libraries))
    return {"abi": abi, "machine": "AArch64" if is_64 else "ARM", "bits": 64 if is_64 else 32,
            "interpreter": interpreter, "needed": libraries, "page_alignment": 16384}
