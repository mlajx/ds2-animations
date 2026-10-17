#!/usr/bin/env python3
"""Read DCX (DFLT) and BND4 containers as used by DS2 SotFS.

Usage:
  bnd4.py list FILE
  bnd4.py extract FILE OUT_DIR [NAME_SUBSTRING...]
  bnd4.py replace FILE OUT_FILE NAME_SUBSTRING NEW_DATA_FILE   (OUT_FILE ending in .dcx is compressed)
"""
import struct
import sys
import zlib
from pathlib import Path


def undcx(data):
    if data[:4] != b"DCX\0":
        return data
    if data[0x28:0x2C] != b"DFLT":
        raise ValueError("unsupported DCX compression %r" % data[0x28:0x2C])
    (size,) = struct.unpack_from(">I", data, 0x1C)
    out = zlib.decompress(data[0x4C:])
    assert len(out) == size, (len(out), size)
    return out


def dcx(data):
    """Wrap data in a DCX/DFLT container (zlib level 9, as the game's own files)."""
    comp = zlib.compress(data, 9)
    hdr = b"DCX\0" + struct.pack(">IIIII", 0x10000, 0x18, 0x24, 0x24, 0x2C)
    hdr += b"DCS\0" + struct.pack(">II", len(data), len(comp))
    hdr += b"DCP\0DFLT" + struct.pack(">IIIIII", 0x20, 0x09000000, 0, 0, 0, 0x00010100)
    hdr += b"DCA\0" + struct.pack(">I", 8)
    return hdr + comp


class BndFile:
    __slots__ = ("id", "name", "flags", "data", "usize")


def read_bnd4(data):
    data = undcx(data)
    if data[:4] != b"BND4":
        raise ValueError("not BND4")
    (count,) = struct.unpack_from("<i", data, 0x0C)
    (entry_size,) = struct.unpack_from("<q", data, 0x20)
    unicode = data[0x30]
    files = []
    for i in range(count):
        off = 0x40 + i * entry_size
        flags = data[off]
        size, usize, data_off, file_id, name_off = struct.unpack_from("<qqiii", data, off + 8)
        if unicode:
            end = name_off
            while data[end:end + 2] != b"\0\0":
                end += 2
            name = data[name_off:end].decode("utf-16-le")
        else:
            name = data[name_off:data.index(b"\0", name_off)].decode("shift_jis")
        f = BndFile()
        f.id, f.name, f.flags, f.data, f.usize = file_id, name, flags, data[data_off:data_off + size], usize
        files.append(f)
    return files


def write_bnd4(template, files):
    """Rebuild a BND4 with the header settings of template (bytes) and the given BndFile list
    (entry order = list order). Name encoding and data alignment are taken from the template."""
    template = undcx(template)
    unicode = template[0x30]
    (entry_size,) = struct.unpack_from("<q", template, 0x20)
    (count,) = struct.unpack_from("<i", template, 0x0C)
    offsets = [struct.unpack_from("<i", template, 0x40 + i * entry_size + 0x18)[0] for i in range(count)]
    alignment = 16
    while alignment < 0x10000 and all(o % (alignment * 2) == 0 for o in offsets):
        alignment *= 2
    out = bytearray(template[:0x40])
    struct.pack_into("<i", out, 0x0C, len(files))
    out += bytes(entry_size * len(files))
    for i, f in enumerate(files):
        name_off = len(out)
        out += f.name.encode("utf-16-le") + b"\0\0" if unicode else f.name.encode("shift_jis") + b"\0"
        e = 0x40 + i * entry_size
        struct.pack_into("<B3xi", out, e, f.flags, -1)
        struct.pack_into("<ii", out, e + 0x1C, f.id, name_off)
    struct.pack_into("<q", out, 0x28, len(out))
    for i, f in enumerate(files):
        while len(out) % alignment:
            out += b"\0"
        e = 0x40 + i * entry_size
        struct.pack_into("<qqi", out, e + 8, len(f.data), f.usize, len(out))
        out += f.data
    return bytes(out)


def new_file(file_id, name, data, compress=False, flags=None):
    f = BndFile()
    f.id, f.name, f.usize = file_id, name, len(data)
    f.data = zlib.compress(data, 9) if compress else data
    f.flags = flags if flags is not None else (0xC0 if compress else 0x40)
    return f


def replace_files(data, replacements):
    """Return BND4 bytes with file contents swapped. replacements: {index: new bytes}.
    Header, entry table and names are kept; data is re-laid in original order, 16-byte aligned."""
    data = bytearray(undcx(data))
    (count,) = struct.unpack_from("<i", data, 0x0C)
    (entry_size,) = struct.unpack_from("<q", data, 0x20)
    entries = []
    for i in range(count):
        off = 0x40 + i * entry_size
        size, _usize, data_off = struct.unpack_from("<qqi", data, off + 8)
        entries.append((data_off, i, off, bytes(data[data_off:data_off + size])))
    data_start = min(e[0] for e in entries)
    out = bytearray(data[:data_start])
    for _orig, i, entry_off, blob in sorted(entries):
        blob = replacements.get(i, blob)
        while len(out) % 16:
            out += b"\0"
        struct.pack_into("<qqi", out, entry_off + 8, len(blob), len(blob), len(out))
        out += blob
    return bytes(out)


def main(argv):
    if len(argv) < 3:
        sys.exit(__doc__)
    cmd, path, *args = argv[1:]
    files = read_bnd4(Path(path).read_bytes())
    if cmd == "list":
        for f in files:
            print(f"{f.id:6d} {len(f.data):9d} {f.data[:4]!r:12} {f.name}")
    elif cmd == "extract":
        out_dir, *filters = args
        for f in files:
            if filters and not any(s.lower() in f.name.lower() for s in filters):
                continue
            dest = Path(out_dir) / f.name.replace("\\", "/").lstrip("/").split(":")[-1].lstrip("/")
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(f.data)
        print(f"extracted to {out_dir}")
    elif cmd == "replace":
        out_path, needle, new_path = args
        hits = [i for i, f in enumerate(files) if needle.lower() in f.name.lower()]
        if len(hits) != 1:
            sys.exit(f"'{needle}' matches {len(hits)} files, need exactly 1")
        out = replace_files(Path(path).read_bytes(), {hits[0]: Path(new_path).read_bytes()})
        Path(out_path).write_bytes(dcx(out) if out_path.endswith(".dcx") else out)
        print(f"replaced {files[hits[0]].name} -> {out_path}")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv)
