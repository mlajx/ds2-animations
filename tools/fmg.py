#!/usr/bin/env python3
"""DS2 FMG text files (version 1, little endian, UTF-16).

Layout: u8 0, u8 bigEndian, u8 version(1), u8 0, i32 fileSize, u8 1, u8[3], i32 groupCount,
i32 stringCount, i32 stringOffsetsOffset, i32 0, groups {i32 firstIndex, i32 firstId, i32 lastId},
i32 stringOffsets[stringCount] (0 = no text), UTF-16 strings with a 0 terminator.

Paths in GameDataEbl: /menu/text/<language>/<name>.fmg, languages: chinese english french germany
italian korean neutralspanish polish portuguese russian spanish. Gesture names are in ingamemenu.fmg.

Usage:
  fmg.py dump FILE.fmg [SUBSTRING]
"""
import struct
import sys


def read(data):
    """Returns (header bytes, groups [(first_index, first_id, last_id)], {id: text or None})."""
    group_count, string_count, offsets_off = struct.unpack_from("<iii", data, 0x0C)
    groups = [struct.unpack_from("<iii", data, 0x1C + 12 * g) for g in range(group_count)]
    offsets = struct.unpack_from(f"<{string_count}i", data, offsets_off)
    entries = {}
    for first_index, first_id, last_id in groups:
        for k in range(last_id - first_id + 1):
            off = offsets[first_index + k]
            text = None
            if off:
                end = off
                while data[end:end + 2] != b"\0\0":
                    end += 2
                text = data[off:end].decode("utf-16-le")
            entries[first_id + k] = text
    return data[:0x1C], groups, entries


def write(header, groups, entries):
    string_count = sum(last - first + 1 for _, first, last in groups)
    offsets_off = 0x1C + 12 * len(groups)
    out = bytearray(header)
    struct.pack_into("<iii", out, 0x0C, len(groups), string_count, offsets_off)
    for g in groups:
        out += struct.pack("<iii", *g)
    out += bytes(4 * string_count)
    for first_index, first_id, last_id in groups:
        for k in range(last_id - first_id + 1):
            text = entries.get(first_id + k)
            if text is None:
                continue
            struct.pack_into("<i", out, offsets_off + 4 * (first_index + k), len(out))
            out += text.encode("utf-16-le") + b"\0\0"
    while len(out) % 32:  # shipped files are padded to 32 bytes; fileSize counts the padding
        out += b"\0"
    struct.pack_into("<i", out, 4, len(out))
    return bytes(out)


def main(argv):
    if len(argv) >= 3 and argv[1] == "dump":
        _, _, entries = read(open(argv[2], "rb").read())
        for i, t in entries.items():
            if t is not None and (len(argv) < 4 or argv[3].lower() in t.lower()):
                print(i, repr(t))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv)
