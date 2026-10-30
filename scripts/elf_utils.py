"""Validate the executable we package as a native library, without host tools."""
import struct


def validate_android_elf(data):
    if len(data) < 64 or data[:6] != b"\x7fELF\x02\x01":
        raise ValueError("Core must be a little-endian ELF64 executable")
    header = struct.unpack_from("<16sHHIQQQIHHHHHH", data)
    if header[1] != 3 or header[2] != 183 or header[4] == 0:
        raise ValueError("Core must be an ARM64 PIE executable with an entry point")
    offset, entry_size, count = header[5], header[9], header[10]
    if entry_size != 56 or not count or offset + count * entry_size > len(data):
        raise ValueError("Invalid ELF program headers")
    segments = [struct.unpack_from("<IIQQQQQQ", data, offset + i * entry_size) for i in range(count)]
    interpreter = None
    dynamic = None
    loads = []
    for kind, flags, position, address, physical, size, memory_size, alignment in segments:
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
    if interpreter != "/system/bin/linker64" or dynamic is None or not loads:
        raise ValueError("Core must use Android /system/bin/linker64, not a desktop Linux runtime")
    if dynamic[1] % 16:
        raise ValueError("Invalid ELF dynamic segment size")
    needed, string_address, string_size = [], None, None
    for position in range(dynamic[0], dynamic[0] + dynamic[1], 16):
        tag, value = struct.unpack_from("<qQ", data, position)
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
    return {"machine": "AArch64", "interpreter": interpreter, "needed": libraries, "page_alignment": 16384}
