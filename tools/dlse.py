#!/usr/bin/env python3
"""Generic reader for DS2 FFX effects (DLsE serialized object trees).

Each object: u16 classIndex+1, u32 version, u32 byteSize (from the object start), payload.
Payload fields are not self-describing; this reader treats anything that parses as a valid
object header (known class, size inside the parent) as a child, and other 4-byte words as fields.

Usage: dlse.py FILE.ffx      print the tree
"""
import struct
import sys


def read_classes(d):
    o = 0x17
    names = []
    while True:
        (length,) = struct.unpack_from("<I", d, o)
        s = d[o + 4:o + 4 + length]
        if length == 0 or length > 80 or not all(32 <= c < 127 for c in s):
            break
        names.append(s.decode())
        o += 4 + length
    return names, o


class Node:
    __slots__ = ("cls", "version", "offset", "size", "fields", "children", "value")


def parse(d, o, end, names):
    cls = struct.unpack_from("<H", d, o)[0] - 1
    version, size = struct.unpack_from("<II", d, o + 2)
    n = Node()
    n.cls, n.version, n.offset, n.size = names[cls], version, o, size
    n.fields, n.children, n.value = [], [], None
    p, stop = o + 10, o + size
    if n.cls.startswith("FXSerializablePrimitive<dl_float32>"):
        n.value = struct.unpack_from("<f", d, p)[0]
    elif n.cls.startswith("FXSerializablePrimitive<dl_int32>"):
        n.value = struct.unpack_from("<i", d, p)[0]
    else:
        while p + 4 <= stop:
            if p + 10 <= stop and _is_object(d, p, stop, names):
                child = parse(d, p, stop, names)
                n.children.append(child)
                p += child.size
            else:
                n.fields.append(struct.unpack_from("<i", d, p)[0])
                p += 4
    return n


def _is_object(d, p, stop, names):
    cls = struct.unpack_from("<H", d, p)[0] - 1
    if not 0 <= cls < len(names):
        return False
    version, size = struct.unpack_from("<II", d, p + 2)
    return version < 16 and 10 <= size <= stop - p


def load(data):
    names, body = read_classes(data)
    return parse(data, body, len(data), names)


def walk(n, depth=0):
    yield n, depth
    for c in n.children:
        yield from walk(c, depth + 1)


def dump(n, depth=0, out=sys.stdout):
    val = f" = {n.value}" if n.value is not None else ""
    fields = f" fields={n.fields[:12]}{'...' if len(n.fields) > 12 else ''}" if n.fields else ""
    print(f"{'  ' * depth}{n.cls.replace('FXSerializable', '')}{val}{fields}", file=out)
    for c in n.children:
        dump(c, depth + 1, out)


if __name__ == "__main__":
    dump(load(open(sys.argv[1], "rb").read()))
