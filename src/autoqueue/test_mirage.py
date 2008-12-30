import sqlite3
from numpy import array, zeros
from nose.tools import assert_equals
from mirage import Mir, CovarianceMatrix, Matrix, Vector, MirDb
from mirage import ScmsConfiguration
from mirage import distance
from autoqueue import aq_db
from decimal import Decimal, getcontext

def decimize(f):
    return Decimal(str(f))

mir = Mir()
scms = mir.analyze('testfiles/test.mp3')
scms2 = mir.analyze('testfiles/test2.mp3')
scms3 = mir.analyze('testfiles/test3.ogg')
scms4 = mir.analyze('testfiles/test4.ogg')
scms5 = mir.analyze('testfiles/test5.ogg')
scmses = [scms, scms2, scms3, scms4, scms5]

class TestMir(object):
    
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
        c = ScmsConfiguration(20)

        assert_equals(0, int(distance(scms, scms, c)))
        assert_equals(67, int(distance(scms, scms2, c)))
        assert_equals(43, int(distance(scms, scms3, c)))
        assert_equals(113, int(distance(scms, scms4, c)))
        assert_equals(80, int(distance(scms, scms5, c)))

        assert_equals(67, int(distance(scms2, scms, c)))
        assert_equals(0, int(distance(scms2, scms2, c)))
        assert_equals(27, int(distance(scms2, scms3, c)))
        assert_equals(88, int(distance(scms2, scms4, c)))
        assert_equals(60, int(distance(scms2, scms5, c)))

        assert_equals(43, int(distance(scms3, scms, c)))
        assert_equals(27, int(distance(scms3, scms2, c)))
        assert_equals(0, int(distance(scms3, scms3, c)))
        assert_equals(86, int(distance(scms3, scms4, c)))
        assert_equals(63, int(distance(scms3, scms5, c)))

        assert_equals(113, int(distance(scms4, scms, c)))
        assert_equals(88, int(distance(scms4, scms2, c)))
        assert_equals(86, int(distance(scms4, scms3, c)))
        assert_equals(0, int(distance(scms4, scms4, c)))
        assert_equals(58, int(distance(scms4, scms5, c)))

        assert_equals(80, int(distance(scms5, scms, c)))
        assert_equals(60, int(distance(scms5, scms2, c)))
        assert_equals(63, int(distance(scms5, scms3, c)))
        assert_equals(58, int(distance(scms5, scms4, c)))
        assert_equals(0, int(distance(scms5, scms5, c)))

    def test_add_track(self):
        aq_db.set_path(":memory:")
        aq_db.create_db()
        testdb = MirDb(aq_db)
        for i, scms in enumerate(scmses):
            testdb.add_track(i, scms)
        
        assert_equals(
            [0,1,2],
            sorted([id for (scms, id) in
                    testdb.get_tracks(exclude_ids=['3','4'])]))

    def test_get_track(self):
        aq_db.set_path(":memory:")
        aq_db.create_db()
        testdb = MirDb(aq_db)
        for i, testscms in enumerate(scmses):
            testdb.add_track(i, testscms)
        scms3_db = testdb.get_track('3')
        scms4_db = testdb.get_track('4')
        c = ScmsConfiguration(20)
        assert_equals(58, int(distance(scms3_db, scms4_db, c)))

    def test_add_and_compare(self):
        aq_db.set_path(":memory:")
        aq_db.create_db()
        testdb = MirDb(aq_db)
        for i, testscms in enumerate(scmses):
            testdb.add_and_compare(i, testscms, cutoff=100000)
        distances = [row for row in aq_db.sql_query(
            ("SELECT * FROM distance" ,))]
        assert_equals(
            [(1, 0, 67616), (2, 0, 43465), (2, 1, 27516), (3, 1, 88447),
             (3, 2, 86641), (4, 0, 80452), (4, 1, 60046), (4, 2, 63272),
             (4, 3, 58181)],
            distances)

    def test_get_neighbours(self):
        aq_db.set_path(":memory:")
        aq_db.create_db()
        testdb = MirDb(aq_db)
        for i, testscms in enumerate(scmses):
            testdb.add_and_compare(i, testscms, cutoff=100000)
        assert_equals(
            [(43465, 2), (67616, 1), (80452, 4)],
            [a for a in testdb.get_neighbours(0)])
