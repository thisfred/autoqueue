"""Tests for mirage."""
import unittest
from mirage import Mir, Matrix, ScmsConfiguration
from mirage import distance
from decimal import Decimal, getcontext

import gst

MIR = Mir()

FILENAMES = [
    'mirage/tests/testfiles/test.mp3',
    'mirage/tests/testfiles/test2.mp3',
    'mirage/tests/testfiles/test3.ogg',
    'mirage/tests/testfiles/test4.ogg',
    'mirage/tests/testfiles/test5.ogg']

SCMSES = {}

for filename in FILENAMES:
    SCMSES[filename] = MIR.analyze(filename)

SCMS = SCMSES[FILENAMES[0]]
SCMS2 = SCMSES[FILENAMES[1]]
SCMS3 = SCMSES[FILENAMES[2]]
SCMS4 = SCMSES[FILENAMES[3]]
SCMS5 = SCMSES[FILENAMES[4]]


def decimize(f):
    """Convert to decimal."""
    return Decimal(str(f))


class TestMir(unittest.TestCase):
    """Test mirage analysis and comparison."""

    def test_matrix(self):
        """Test the matrix object."""
        getcontext().prec = 6
        mat = Matrix(8, 5)
        for i in range(mat.rows):
            for j in range(mat.columns):
                mat.d[i, j] = (i + j) / (i + 1.0)
        self.assertEqual(
            [decimize(t) for t in list(mat.d.flatten())],
            [decimize(t) for t in [0.0, 1.0, 2.0, 3.0, 4.0,
             0.5, 1.0, 1.5, 2.0, 2.5,
             0.666666666667, 1.0, 1.33333333333, 1.66666666667, 2.0,
             0.75, 1.0, 1.25, 1.5, 1.75,
             0.8, 1.0, 1.2, 1.4, 1.6,
             0.833333333333, 1.0, 1.16666666667, 1.33333333333, 1.5,
             0.857142857143, 1.0, 1.14285714286, 1.28571428571, 1.42857142857,
             0.875, 1.0, 1.125, 1.25, 1.375]])

    def test_multiply(self):
        """Test matrix multiplication."""
        getcontext().prec = 6
        mat = Matrix(8, 5)
        for i in range(mat.rows):
            for j in range(mat.columns):
                mat.d[i, j] = (i + j) / (i + 1.0)
        mat2 = Matrix(5, 4)
        for i in range(mat2.rows):
            for j in range(mat2.columns):
                mat2.d[i, j] = j / (i + 1.0)

        mat3 = mat.multiply(mat2)
        self.assertEquals(
            [decimize(t) for t in list(mat3.d.flatten())],
            [decimize(t) for t in [0.0, 2.71666666667, 5.43333333333, 8.15,
             0.0, 2.5, 5.0, 7.5,
             0.0, 2.42777777778, 4.85555555556, 7.28333333333,
             0.0, 2.39166666667, 4.78333333333, 7.175,
             0.0, 2.37, 4.74, 7.11,
             0.0, 2.35555555556, 4.71111111111, 7.06666666667,
             0.0, 2.34523809524, 4.69047619048, 7.03571428571,
             0.0, 2.3375, 4.675, 7.0125]])

    def test_analysis(self):
        """Test mirage analysis."""
        conf = ScmsConfiguration(20)

        self.assertEqual(0, int(distance(SCMS, SCMS, conf)))
        self.assertEqual(75, int(distance(SCMS, SCMS2, conf)))
        self.assertEqual(52, int(distance(SCMS, SCMS3, conf)))
        self.assertEqual(69, int(distance(SCMS, SCMS4, conf)))
        self.assertEqual(240, int(distance(SCMS, SCMS5, conf)))

        self.assertEqual(75, int(distance(SCMS2, SCMS, conf)))
        self.assertEqual(0, int(distance(SCMS2, SCMS2, conf)))
        self.assertEqual(16, int(distance(SCMS2, SCMS3, conf)))
        self.assertEqual(59, int(distance(SCMS2, SCMS4, conf)))
        self.assertEqual(124, int(distance(SCMS2, SCMS5, conf)))

        self.assertEqual(52, int(distance(SCMS3, SCMS, conf)))
        self.assertEqual(16, int(distance(SCMS3, SCMS2, conf)))
        self.assertEqual(0, int(distance(SCMS3, SCMS3, conf)))
        self.assertEqual(49, int(distance(SCMS3, SCMS4, conf)))
        self.assertEqual(84, int(distance(SCMS3, SCMS5, conf)))

        self.assertEqual(69, int(distance(SCMS4, SCMS, conf)))
        self.assertEqual(59, int(distance(SCMS4, SCMS2, conf)))
        self.assertEqual(49, int(distance(SCMS4, SCMS3, conf)))
        self.assertEqual(0, int(distance(SCMS4, SCMS4, conf)))
        self.assertEqual(124, int(distance(SCMS4, SCMS5, conf)))

        self.assertEqual(240, int(distance(SCMS5, SCMS, conf)))
        self.assertEqual(124, int(distance(SCMS5, SCMS2, conf)))
        self.assertEqual(84, int(distance(SCMS5, SCMS3, conf)))
        self.assertEqual(124, int(distance(SCMS5, SCMS4, conf)))
        self.assertEqual(0, int(distance(SCMS5, SCMS5, conf)))
