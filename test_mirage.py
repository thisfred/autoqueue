from numpy import array, zeros
from nose.tools import assert_equals
from mirage import Mir, CovarianceMatrix, Matrix, Vector
from decimal import Decimal, getcontext

def decimize(f):
    return Decimal(str(f))

class TestMir(object):
    def setup(self):
        self.mir = Mir()

    def test_covariance_matrix(self):
        cov = CovarianceMatrix(10)
        assert_equals(cov.dim, 10)
        assert_equals(list(cov.d), list(zeros([(10 * 10 + 10) / 2])))

    def test_matrix(self):
        getcontext().prec = 6
        mat = Matrix(8, 5)
        for i in range(mat.rows):
            for j in range(mat.columns):
                mat.d[i, j] = (i + j) / (i + 1.0)
        assert_equals(
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
        assert_equals(
            [decimize(t) for t in list(mat3.d.flatten())],
            [decimize(t) for t in [0.0, 2.71666666667, 5.43333333333, 8.15,
             0.0, 2.5, 5.0, 7.5,
             0.0, 2.42777777778, 4.85555555556, 7.28333333333,
             0.0, 2.39166666667, 4.78333333333, 7.175,
             0.0, 2.37, 4.74, 7.11,
             0.0, 2.35555555556, 4.71111111111, 7.06666666667,
             0.0, 2.34523809524, 4.69047619048, 7.03571428571,
             0.0, 2.3375, 4.675, 7.0125]])

    def test_covariance_matrix2(self):
        getcontext().prec = 11
        mat = Matrix(8, 5)
        for i in range(mat.rows):
            for j in range(mat.columns):
                mat.d[i, j] = (i + j) / (i + 1.0)
        mat2 = Matrix(5, 4)
        for i in range(mat2.rows):
            for j in range(mat2.columns):
                mat2.d[i, j] = j / (i + 1.0)
        mat3 = mat.multiply(mat2)
        cov2 = CovarianceMatrix(mat3)
        assert_equals(cov2.dim, 8)
        assert_equals(
            [decimize(t) for t in list(cov2.d)][:10],
            [decimize(t) for t in [
             0.0, 2.71666666667, 5.43333333333, 8.15, 2.5, 5.0, 7.5,
             4.85555555556, 7.28333333333, 7.175]]
            )

    def test_analysis(self):
        mir = Mir()
        scms = mir.analyze('testfiles/test.mp3')
        scms2 = mir.analyze('testfiles/test2.mp3')
        scms3 = mir.analyze('testfiles/test3.ogg')
        scms4 = mir.analyze('testfiles/test4.ogg')
        scms5 = mir.analyze('testfiles/test5.ogg')

        assert_equals(decimize(scms.distance(scms)), decimize(40.0))
        assert_equals(decimize(scms.distance(scms2)), decimize(60.0410784026))
        assert_equals(decimize(scms.distance(scms3)), decimize(69.7778050071))
        assert_equals(decimize(scms.distance(scms4)), decimize(69.9353307839))
        assert_equals(decimize(scms.distance(scms5)), decimize(64.4393694913))

        assert_equals(decimize(scms2.distance(scms)), decimize(60.0410784026))
        assert_equals(decimize(scms2.distance(scms2)), decimize(40.0))
        assert_equals(decimize(scms2.distance(scms3)), decimize(67.7742869702))
        assert_equals(decimize(scms2.distance(scms4)), decimize(65.3971024652))
        assert_equals(decimize(scms2.distance(scms5)), decimize(73.2605282954))

        assert_equals(decimize(scms3.distance(scms)), decimize(69.7778050071))
        assert_equals(decimize(scms3.distance(scms2)), decimize(67.7742869702))
        assert_equals(decimize(scms3.distance(scms3)), decimize(40.0))
        assert_equals(decimize(scms3.distance(scms4)), decimize(72.5249084377))
        assert_equals(decimize(scms3.distance(scms5)), decimize(104.545284935))

        assert_equals(decimize(scms4.distance(scms)), decimize(69.9353307839))
        assert_equals(decimize(scms4.distance(scms2)), decimize(65.3971024652))
        assert_equals(decimize(scms4.distance(scms3)), decimize(72.5249084377))
        assert_equals(decimize(scms4.distance(scms4)), decimize(40.0))
        assert_equals(decimize(scms4.distance(scms5)), decimize(96.7413449229))

        assert_equals(decimize(scms5.distance(scms)), decimize(64.4393694913))
        assert_equals(decimize(scms5.distance(scms2)), decimize(73.2605282954))
        assert_equals(decimize(scms5.distance(scms3)), decimize(104.545284935))
        assert_equals(decimize(scms5.distance(scms4)), decimize(96.7413449229))
        assert_equals(decimize(scms5.distance(scms5)), decimize(40.0))

