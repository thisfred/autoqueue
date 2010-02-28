import unittest, sqlite3
from mirage import Mir, Matrix, Db, ScmsConfiguration
from mirage import distance
from decimal import Decimal, getcontext

# we have to do this or the tests break badly
import pygst
pygst.require("0.10")

import gst

mir = Mir()

filenames = [
    'testfiles/test.mp3', 'testfiles/test2.mp3', 'testfiles/test3.ogg',
    'testfiles/test4.ogg', 'testfiles/test5.ogg']

scmses = {}
for filename in filenames:
    scmses[filename] = mir.analyze(filename)

scms = scmses[filenames[0]]
scms2 = scmses[filenames[1]]
scms3 = scmses[filenames[2]]
scms4 = scmses[filenames[3]]
scms5 = scmses[filenames[4]]

def decimize(f):
    return Decimal(str(f))


class TestMir(unittest.TestCase):
    def setUp(self):
        connection = sqlite3.connect(":memory:")
        self.db = Db(":memory:", connection=connection)
        connection.text_factory = str
        connection.execute(
            'CREATE TABLE IF NOT EXISTS mirage (trackid INTEGER PRIMARY KEY, '
            'filename VARCHAR(300), scms BLOB)')
        connection.execute(
            "CREATE TABLE IF NOT EXISTS distance (track_1 INTEGER, track_2 "
            "INTEGER, distance INTEGER)")
        connection.execute(
            "CREATE INDEX IF NOT EXISTS mfnx ON mirage (filename)")
        connection.execute(
            "CREATE INDEX IF NOT EXISTS dtrack1x ON distance (track_1)")
        connection.execute(
            "CREATE INDEX IF NOT EXISTS dtrack2x ON distance (track_2)")
        connection.commit()

    def test_matrix(self):
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
        c = ScmsConfiguration(20)

        self.assertEqual(0, int(distance(scms, scms, c)))
        self.assertEqual(70, int(distance(scms, scms2, c)))
        self.assertEqual(49, int(distance(scms, scms3, c)))
        self.assertEqual(69, int(distance(scms, scms4, c)))
        self.assertEqual(235, int(distance(scms, scms5, c)))

        self.assertEqual(70, int(distance(scms2, scms, c)))
        self.assertEqual(0, int(distance(scms2, scms2, c)))
        self.assertEqual(16, int(distance(scms2, scms3, c)))
        self.assertEqual(59, int(distance(scms2, scms4, c)))
        self.assertEqual(124, int(distance(scms2, scms5, c)))

        self.assertEqual(49, int(distance(scms3, scms, c)))
        self.assertEqual(16, int(distance(scms3, scms2, c)))
        self.assertEqual(0, int(distance(scms3, scms3, c)))
        self.assertEqual(49, int(distance(scms3, scms4, c)))
        self.assertEqual(84, int(distance(scms3, scms5, c)))

        self.assertEqual(69, int(distance(scms4, scms, c)))
        self.assertEqual(59, int(distance(scms4, scms2, c)))
        self.assertEqual(49, int(distance(scms4, scms3, c)))
        self.assertEqual(0, int(distance(scms4, scms4, c)))
        self.assertEqual(124, int(distance(scms4, scms5, c)))

        self.assertEqual(235, int(distance(scms5, scms, c)))
        self.assertEqual(124, int(distance(scms5, scms2, c)))
        self.assertEqual(84, int(distance(scms5, scms3, c)))
        self.assertEqual(124, int(distance(scms5, scms4, c)))
        self.assertEqual(0, int(distance(scms5, scms5, c)))

    def test_add_track(self):
        for filename in filenames:
            self.db.add_track(filename, scmses[filename])
        self.assertEqual(
            [1,2,3,4,5],
            sorted([id for (scms, id) in
                    self.db.get_tracks()]))
        self.assertEqual(
            [1,2,5],
            sorted([id for (scms, id) in
                    self.db.get_tracks(exclude_ids=['3','4'])]))

    def test_get_track(self):
        for filename in filenames:
            self.db.add_track(filename, scmses[filename])
        scms3_db = self.db.get_track(filenames[2])[1]
        scms4_db = self.db.get_track(filenames[3])[1]
        c = ScmsConfiguration(20)
        self.assertEqual(49, int(distance(scms3_db, scms4_db, c)))

    def test_add_neighbours(self):
        for filename in filenames:
            testscms = scmses[filename]
            self.db.add_track(filename, testscms)
            track_id = self.db.get_track_id(filename)
            for dummy in self.db.add_neighbours(track_id, testscms):
                pass
        connection = self.db.get_database_connection()
        distances = [
            row for row in connection.execute("SELECT * FROM distance")]
        self.assertEqual(
            [(2, 1, 70338), (3, 1, 49060), (3, 2, 16563), (4, 1, 69551),
             (4, 2, 59503), (4, 3, 49652), (5, 1, 235246), (5, 4, 124450),
             (5, 2, 124312), (5, 3, 84223)],
            distances)

    def test_get_neighbours(self):
        for filename in filenames:
            testscms = scmses[filename]
            self.db.add_track(filename, testscms)
            track_id = self.db.get_track_id(filename)
            for dummy in self.db.add_neighbours(track_id, testscms):
                pass
        self.assertEqual(
            [(84223, 3), (124312, 2), (124450, 4), (235246, 1)],
            [a for a in self.db.get_neighbours(5)])

