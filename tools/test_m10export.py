"""Host tests for m10export.py geometry handling: x5 / Film OB strip, ImgMode 1 (no OB), Wide 1:3 FPM + DNG DefaultScale."""
import os
import struct
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import m10export as E  # noqa: E402
import m10wide_fpm as F  # noqa: E402


def dng_tags(path):
    d = open(path, 'rb').read()
    off = struct.unpack_from('<I', d, 4)[0]
    tags = {}
    for i in range(struct.unpack_from('<H', d, off)[0]):
        tag, typ, cnt, val = struct.unpack_from('<HHII', d, off + 2 + 12 * i)
        nb = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 10: 8}[typ] * cnt
        tags[tag] = d[off + 10 + 12 * i:off + 14 + 12 * i] if nb <= 4 else d[val:val + nb]
    return d, tags


class TestGeometry(unittest.TestCase):
    def test_x5_film_ob_strip(self):
        for h, w, exp in ((1104, 2512, (1076, 2512)), (1104, 2592, (1076, 2520)), (1157, 2304, (1128, 2304))):
            img = np.arange(h * w, dtype=np.uint16).reshape(h, w)
            a = E.active(img)
            self.assertEqual(a.shape, exp)
            self.assertEqual(a[0, 0], img[28, 72 if w == 2592 else 0])   # OB rows 0-27 (and cols 0-71) dropped
            self.assertFalse(E.is_m1(img) or E.is_wide(img))

    def test_imgmode1_no_ob(self):
        cases = (
            (1440, 1920, False), (1536, 2048, False), (1440, 2160, False),
            (1296, 2304, False), (1088, 2592, False), (1080, 1920, False),
            (1536, 2304, False), (1440, 2592, False),
            (1800, 1728, True), (1440, 1728, True), (1296, 1728, True),
        )
        for h, w, wide in cases:
            img = np.arange(h * w, dtype=np.uint32).reshape(h, w).astype(np.uint16)
            a = E.active(img)
            self.assertEqual(a.shape, (h, w))
            self.assertEqual(a[0, 0], img[0, 0])
            self.assertTrue(E.is_m1(img))
            self.assertEqual(E.is_wide(img), wide)

    def test_prepare_fpm_only_on_wide(self):
        rng = np.random.default_rng(1)
        wide = rng.integers(2048, 16383, (1800, 1728)).astype(np.uint16)
        m = F.site_mask(*wide.shape)
        fixed = E.prepare(wide, True)
        self.assertTrue((fixed[~m] == wide[~m]).all())
        self.assertTrue((fixed == F.fix_wide_raw(wide)).all())
        self.assertTrue((E.prepare(wide, False) == wide).all())
        m1 = rng.integers(2048, 16383, (1440, 1920)).astype(np.uint16)
        self.assertTrue((E.prepare(m1, True) == m1).all())   # 1440p 1920: no Wide lattice, untouched


class TestDng(unittest.TestCase):
    def _write(self, desq):
        img = np.full((8, 12), 3000, np.uint16)
        with tempfile.TemporaryDirectory() as t:
            p = os.path.join(t, 'f.dng')
            E.write_cdng(p, img, E.DAYLIGHT, '24', 0, desq)
            d, tags = dng_tags(p)
        so = struct.unpack('<I', tags[273])[0]
        self.assertTrue((np.frombuffer(d, '<u2', img.size, so).reshape(img.shape) == img).all())
        return tags

    def test_default_scale_wide(self):
        self.assertEqual(struct.unpack('<4I', self._write(3)[50718]), (3, 1, 1, 1))

    def test_no_default_scale_square(self):
        self.assertNotIn(50718, self._write(1))


if __name__ == '__main__':
    unittest.main()
