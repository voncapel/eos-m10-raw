"""Offline task preflight tests; never import m10ptp or open USB."""
import struct
import unittest
from m10tasks import (SIGNATURE, check_signature, table_bounds, task_records,
                      safe_name_address, decode_names, snapshot)


class TaskTests(unittest.TestCase):
    def test_signature_fail_closed(self):
        check_signature(SIGNATURE, struct.pack('<II', 0x803c, 0x8040))
        with self.assertRaises(ValueError):
            check_signature(b'\0' * 20, struct.pack('<II', 0x803c, 0x8040))

    def test_task_table(self):
        data = bytearray(0x54 * 2)
        struct.pack_into('<I', data, 0x40, 0x10001)
        struct.pack_into('<I', data, 0x24, 0xfc100000)
        data[0x54 + 0x49] = 0xff
        records = task_records(0x10000, 2, data)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['name_ptr'], 0xfc100000)
        struct.pack_into('<I', data, 0x40, 0x10002)
        with self.assertRaises(ValueError):
            task_records(0x10000, 2, data)

    def test_no_mmio_name(self):
        for p in [0xc0242014, 0xd0000000, 0, 0xfffffffe, 0x20000000]:
            self.assertFalse(safe_name_address(p))
        for p in [0x400000, 0x10000000, 0xbfe115d4, 0xfc123456]:
            self.assertTrue(safe_name_address(p))

    def test_bounds(self):
        for base, count in [(0, 1), (0x10000, 0), (0x10001, 2), (0x1ffffffc, 2), (0x10000, 1025)]:
            with self.assertRaises(ValueError):
                table_bounds(base, count)

    def test_name_snapshot(self):
        data = struct.pack('<4I', 0x314d4e54, 1, 44, 153)
        data += struct.pack('<III32s', 0x12340, 1, 0xfc123451, b'M10Cine')
        self.assertEqual(decode_names(data), {'0x00012340': 'M10Cine'})
        with self.assertRaises(ValueError):
            decode_names(data[:-1])


class FakeCam:
    """Records reads; intentionally implements NO write/call method."""
    def __init__(self, unsafe=False):
        self.reads = []
        self.table = bytearray(0x54)
        struct.pack_into('<I', self.table, 0x40, 0x10001)
        struct.pack_into('<I', self.table, 0x24, 0xc0242014 if unsafe else 0xbfe115d4)
        self.memory = {
            0xbfe10f50: SIGNATURE,
            0xbfe10f70: struct.pack('<II', 0x803c, 0x8040),
            0x80c0: struct.pack('<I', 0x680124),
            0x80f4: struct.pack('<I', 1),
            0x803c: struct.pack('<I', 0x680124),
            0x680124: bytes(self.table),
            0xbfe115d4: b'idle\0'.ljust(32, b'\0'),
        }

    def read(self, address, size):
        if address >> 28 in (0xc, 0xd):
            raise AssertionError('MMIO read attempted')
        self.reads.append((address, size))
        data = self.memory[address]
        if len(data) < size:
            raise AssertionError('read exceeds mock region')
        return data[:size]

    def peek(self, address):
        return struct.unpack('<I', self.read(address, 4))


class SnapshotTests(unittest.TestCase):
    def test_live_preflight_path_is_read_only_and_accepts_kernel_tcm_name(self):
        c = FakeCam()
        names, metadata = snapshot(c)
        self.assertEqual(names, {'0x00680124': 'idle'})
        self.assertEqual(metadata['signature'], 'matched')
        self.assertIn((0xbfe115d4, 32), c.reads)

    def test_bad_signature_never_reads_table_or_names(self):
        c = FakeCam()
        c.memory[0xbfe10f50] = bytes(20)
        with self.assertRaises(ValueError):
            snapshot(c)
        self.assertNotIn((0x680124, 0x54), c.reads)

    def test_unsafe_name_is_rejected_before_dereference(self):
        c = FakeCam(unsafe=True)
        with self.assertRaises(ValueError):
            snapshot(c)
        self.assertFalse(any(address == 0xc0242014 for address, size in c.reads))

    def test_current_pointer_outside_active_table_is_rejected(self):
        c = FakeCam()
        c.memory[0x803c] = struct.pack('<I', 0x680178)
        with self.assertRaises(ValueError):
            snapshot(c)
        self.assertNotIn((0xbfe115d4, 32), c.reads)


if __name__ == '__main__':
    unittest.main()
