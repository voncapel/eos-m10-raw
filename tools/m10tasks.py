#!/usr/bin/env python3
"""Read-only DryOS task preflight for M10 110d; decode module TNM1 snapshots.

No engine MMIO, no firmware calls, no writes on camera. The kernel signature
comes from 110f and MUST match the live 110d kernel before interpreting TCBs.
Task addresses can be recycled: names are snapshots, not permanent identities.
"""
import argparse
import json
from pathlib import Path
import struct

KERNEL = 0xBFE10F50
SIGNATURE = bytes.fromhex('0848006810b14ff0ff30704704480068006c7047')
LITERALS = 0xBFE10F70
CURRENT = 0x803C
TABLE = 0x80C0
COUNT = 0x80F4
TCB_SIZE = 0x54
NAME_SIZE = 32


def check_signature(code, literals):
    if code != SIGNATURE or literals != struct.pack('<II', CURRENT, 0x8040):
        raise ValueError('DryOS kernel signature mismatch; refusing task interpretation')


def table_bounds(base, count):
    if not 1 <= count <= 1024 or base & 3 or not 0x8000 <= base < 0x20000000:
        raise ValueError('invalid task table base/count')
    if base + count * TCB_SIZE > 0x20000000:
        raise ValueError('task table exceeds low RAM')


def task_records(base, count, data):
    table_bounds(base, count)
    if len(data) != count * TCB_SIZE:
        raise ValueError('truncated task table')
    records = []
    for i in range(count):
        off = i * TCB_SIZE
        task_id = struct.unpack_from('<I', data, off + 0x40)[0]
        if data[off + 0x49] == 0xFF or not task_id:
            continue
        if task_id & 0xFFFF != i + 1:
            raise ValueError('task id/index mismatch at slot %d' % (i + 1))
        entry = struct.unpack_from('<I', data, off + 0x0C)[0]
        name_ptr = struct.unpack_from('<I', data, off + 0x24)[0]
        records.append(dict(ptr=base + off, task_id=task_id, entry=entry, name_ptr=name_ptr))
    return records


def safe_name_address(p):
    return (0x8000 <= p <= 0x20000000 - NAME_SIZE
            or 0xBFE10800 <= p <= 0xBFE1741D - NAME_SIZE
            or 0xFC000000 <= p <= 0x100000000 - NAME_SIZE)


def decode_names(data):
    if len(data) < 16:
        raise ValueError('truncated TNM1 header')
    magic, count, stride, version = struct.unpack_from('<4I', data)
    if magic != 0x314D4E54 or count > 256 or stride != 44 or version != 153:
        raise ValueError('invalid TNM1 header')
    if len(data) != 16 + count * stride:
        raise ValueError('TNM1 length mismatch')
    names = {}
    for i in range(count):
        ptr, tid, entry, raw = struct.unpack_from('<III32s', data, 16 + i * stride)
        key = '0x%08x' % ptr
        if key in names:
            raise ValueError('duplicate TNM1 task pointer')
        names[key] = raw.split(b'\0', 1)[0].decode('ascii', errors='replace') or '<unnamed>'
    return names


def snapshot(c):
    check_signature(c.read(KERNEL, len(SIGNATURE)), c.read(LITERALS, 8))
    base, count, current = c.peek(TABLE)[0], c.peek(COUNT)[0], c.peek(CURRENT)[0]
    table_bounds(base, count)
    records = task_records(base, count, c.read(base, count * TCB_SIZE))
    if not any(r['ptr'] == current for r in records):
        raise ValueError('current task is not an active table slot')
    names = {}
    for r in records:
        p = r['name_ptr']
        if not safe_name_address(p):
            raise ValueError('unsafe task-name address 0x%08x' % p)
        raw = c.read(p, NAME_SIZE)
        names['0x%08x' % r['ptr']] = raw.split(b'\0', 1)[0].decode('ascii', errors='replace')
    return names, dict(current='0x%08x' % current, base='0x%08x' % base,
                       slots=count, active=len(records), signature='matched',
                       warning='Snapshot only; task slots can be recycled.')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='op', required=True)
    d = sub.add_parser('decode', help='offline TNM1 binary to flat names JSON')
    d.add_argument('input', type=Path)
    d.add_argument('output', type=Path)
    s = sub.add_parser('snapshot', help='read-only live task snapshot (requires USB)')
    s.add_argument('output', type=Path)
    a = p.parse_args()
    if a.output.exists():
        p.error('output exists; choose a fresh snapshot path')
    try:
        if a.op == 'decode':
            names = decode_names(a.input.read_bytes())
        else:
            from m10ptp import Cam
            c = Cam(timeout=20000)
            try:
                names, metadata = snapshot(c)
                print(json.dumps(metadata, ensure_ascii=False))
            finally:
                c.close()
        a.output.write_text(json.dumps(names, indent=2, ensure_ascii=False) + '\n')
        print('%d task names -> %s' % (len(names), a.output))
    except (ValueError, OSError) as e:
        p.exit(2, 'error: %s\n' % e)


if __name__ == '__main__':
    main()
