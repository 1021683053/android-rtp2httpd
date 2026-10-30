import struct

def synthetic_elf(interpreter=None, library="libc.so", alignment=16384, abi="arm64-v8a"):
    """Program-header fixture only; never executed as a native program."""
    data = bytearray(512)
    is_64 = abi == "arm64-v8a"
    ident = b"\x7fELF" + bytes([2 if is_64 else 1, 1, 1]) + bytes(9)
    if is_64:
        struct.pack_into("<16sHHIQQQIHHHHHH", data, 0, ident, 3, 183, 1, 496, 64, 0, 0, 64, 56, 3, 0, 0, 0)
    else:
        struct.pack_into("<16sHHIIIIIHHHHHH", data, 0, ident, 3, 40, 1, 496, 52, 0, 0x5000200, 52, 32, 3, 0, 0, 0)
    interpreter = interpreter or ("/system/bin/linker64" if is_64 else "/system/bin/linker")
    interpreter = interpreter.encode() + b"\0"
    libraries = library.encode() + b"\0"
    if is_64:
        struct.pack_into("<IIQQQQQQ", data, 64, 1, 5, 0, 0, 0, 512, 512, alignment)
        struct.pack_into("<IIQQQQQQ", data, 120, 3, 4, 256, 256, 256, len(interpreter), len(interpreter), 1)
        struct.pack_into("<IIQQQQQQ", data, 176, 2, 6, 320, 320, 320, 64, 64, 8)
    else:
        struct.pack_into("<IIIIIIII", data, 52, 1, 0, 0, 0, 512, 512, 5, alignment)
        struct.pack_into("<IIIIIIII", data, 84, 3, 256, 256, 256, len(interpreter), len(interpreter), 4, 1)
        struct.pack_into("<IIIIIIII", data, 116, 2, 320, 320, 320, 32, 32, 6, 4)
    data[256:256 + len(interpreter)] = interpreter
    for i, pair in enumerate([(5, 448), (10, len(libraries)), (1, 0), (0, 0)]):
        struct.pack_into("<qQ" if is_64 else "<iI", data, 320 + i * (16 if is_64 else 8), *pair)
    data[448:448 + len(libraries)] = libraries
    return bytes(data)
