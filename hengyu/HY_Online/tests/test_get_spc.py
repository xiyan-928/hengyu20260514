"""
SPC 写入兼容性回归测试（基于上游 SPyC_Writer 修复版本）。
"""
from __future__ import annotations

import os
import struct
import sys
import tempfile
import unittest

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from Devices.get_spc import write_spc
from Devices.read_spc import read_spc_xy
from SPyC_Writer.SPCEnums import SPCFileType, SPCXType


X_UNITS_OFFSET = 28
HEADER_SIZE = 512
SUBHEADER_SIZE = 32


class TestGetSpcCompatibility(unittest.TestCase):
    def test_write_spc_even_axis_generates_standard_layout(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = os.path.join(tmpdir, "even.spc")
            wavelengths = np.array([400.0, 500.0, 600.0], dtype=np.float64)
            spectrum = np.array([1.0, 2.0, 3.0], dtype=np.float64)

            file_path = write_spc(wavelengths, spectrum, out_path)
            data = open(file_path, "rb").read()

            self.assertGreaterEqual(len(data), HEADER_SIZE + SUBHEADER_SIZE + 12)
            self.assertFalse(data[0] & int(SPCFileType.SIXTEENPREC))
            self.assertEqual(data[0], 0)
            self.assertEqual(data[X_UNITS_OFFSET], int(SPCXType.SPCXNMetr))
            self.assertEqual(struct.unpack("<b", data[HEADER_SIZE + 1 : HEADER_SIZE + 2])[0], -128)
            self.assertEqual(struct.unpack("<3f", data[HEADER_SIZE + SUBHEADER_SIZE : HEADER_SIZE + SUBHEADER_SIZE + 12]), (1.0, 2.0, 3.0))

    def test_write_spc_uneven_axis_generates_txvals_layout(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = os.path.join(tmpdir, "uneven.spc")
            wavelengths = np.array([400.0, 500.5, 600.0], dtype=np.float64)
            spectrum = np.array([1.0, 2.0, 3.0], dtype=np.float64)

            file_path = write_spc(wavelengths, spectrum, out_path)
            data = open(file_path, "rb").read()

            self.assertTrue(data[0] & int(SPCFileType.TXVALS))
            subheader_offset = HEADER_SIZE + wavelengths.size * 4
            self.assertEqual(struct.unpack("<b", data[subheader_offset + 1 : subheader_offset + 2])[0], -128)
            self.assertGreaterEqual(len(data), subheader_offset + SUBHEADER_SIZE + spectrum.size * 4)

    def test_read_spc_xy_round_trip_even(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = os.path.join(tmpdir, "roundtrip_even.spc")
            wavelengths = np.linspace(190.685, 840.3275, 2048, dtype=np.float64)
            spectrum = np.linspace(1315.0, 7434.0, 2048, dtype=np.float64)

            file_path = write_spc(wavelengths, spectrum, out_path)
            read_x, read_y = read_spc_xy(file_path)

            np.testing.assert_allclose(read_x, wavelengths, rtol=1e-6, atol=1e-6)
            np.testing.assert_allclose(read_y, spectrum, rtol=1e-6, atol=1e-6)

    def test_read_spc_xy_round_trip_uneven(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = os.path.join(tmpdir, "roundtrip_uneven.spc")
            wavelengths = np.array([190.685, 191.02, 191.37, 191.81], dtype=np.float64)
            spectrum = np.array([1315.0, 1545.0, 1516.0, 1370.0], dtype=np.float64)

            file_path = write_spc(wavelengths, spectrum, out_path)
            read_x, read_y = read_spc_xy(file_path)

            np.testing.assert_allclose(read_x, wavelengths, rtol=1e-6, atol=1e-6)
            np.testing.assert_allclose(read_y, spectrum, rtol=1e-6, atol=1e-6)


if __name__ == "__main__":
    unittest.main()
