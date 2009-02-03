import os, struct, math, sys
from decimal import Decimal
from datetime import datetime, timedelta
from operator import itemgetter
import cPickle as pickle
from cStringIO import StringIO
from ctypes import *
import sqlite3
from scipy import *
import gst, gobject

DEBUG = True

class MirageAudio(Structure):
    pass

cdll.LoadLibrary("/usr/lib/banshee-1/Extensions/libmirageaudio.so")
libmirageaudio = CDLL("libmirageaudio.so")


class MatrixDimensionMismatchException(Exception):
    pass


class MatrixSingularException(Exception):
    pass


class MfccFailedException(Exception):
    pass


class ScmsImpossibleException(Exception):
    pass


class MirAnalysisImpossibleException(Exception):
    pass


class MirageAudio(Structure):
    pass


mirageaudio_initialize = libmirageaudio.mirageaudio_initialize
mirageaudio_decode = libmirageaudio.mirageaudio_decode
mirageaudio_decode.restype = POINTER(c_float)
mirageaudio_destroy = libmirageaudio.mirageaudio_destroy
mirageaudio_canceldecode = libmirageaudio.mirageaudio_canceldecode

def distance(scms1, scms2, scmsconf):
    val = 0.0
    dim = scmsconf.get_dimension()
    covlen = (dim * dim + dim) / 2
    s1cov = scms1.cov.d
    s2icov = scms2.icov.d
    s1icov = scms1.icov.d
    s2cov = scms2.cov.d
    s1mean = scms1.mean.d
    s2mean = scms2.mean.d

    for i in range(covlen):
        val += s1cov[i] * s2icov[i] + s2cov[i] * s1icov[i]
        scmsconf.aicov[i] = s1icov[i] + s2icov[i]

    for i in range(dim):
        scmsconf.mdiff[i] = s1mean[i] - s2mean[i]

    for i in range(dim):
        idx = i - dim
        tmp1 = 0
        for k in range(i + 1):
            idx += dim - k
            tmp1 += scmsconf.aicov[idx] * scmsconf.mdiff[k]
        for k in range(i + 1, dim):
            idx += 1
            tmp1 += scmsconf.aicov[idx] * scmsconf.mdiff[k]
        val += tmp1 * scmsconf.mdiff[i]
    val = val/2 - scms1.cov.dim
    return val

def gauss_jordan(a, n, b, m):
    icol = 0
    irow = 0
    big = Decimal()
    dum = Decimal()
    pivinv = Decimal()
    temp = Decimal()

    indxc = [0] * (n + 1)
    indxr = [0] * (n + 1)
    ipiv = [0] * (n + 1)

    for i in range(1, n + 1):
        big = Decimal()
        for j in range(1, n + 1):
            if ipiv[j] != 1:
                for k in range(1, n + 1):
                    if ipiv[k] == 0:
                        if abs(a[j, k]) >= big:
                            big = abs(a[j, k])
                            irow = j
                            icol = k
                    elif ipiv[k] > 1:
                        raise MatrixSingularException
        ipiv[icol] += 1
        if irow != icol:
            for l in range(1, n + 1):
                temp = a[irow, l]
                a[irow, l] = a[icol, l]
                a[icol, l] = temp
            for l in range(1, n + 1):
                temp = b[irow, l]
                b[irow, l] = b[icol, l]
                b[icol, l] = temp

        indxr[i] = irow
        indxc[i] = icol
        if a[icol, icol] == 0:
            raise MatrixSingularException
        pivinv = Decimal(1 / a[icol, icol])
        a[icol, icol] = Decimal(1)
        for l in range(1, n + 1):
            a[icol, l] *= pivinv
        for l in range(1, m + 1):
            b[icol, l] *= pivinv
        for ll in range(1, n + 1):
            if ll != icol:
                dum = a[ll, icol]
                a [ll, icol] = Decimal(0)
                for l in range(1, n + 1):
                    a[ll, l] -= a[icol, l] * dum
                for l in range(1, m + 1):
                    b[ll, l] -= b[icol, l] * dum
    for l in range(n, 0, -1):
        if indxr[l] != indxc[l]:
            for k in range(1, n + 1):
                temp = a[k, indxr[l]]
                a[k, indxr[l]] = a[k, indxc[l]]
                a[k, indxc[l]] = temp



def write_line(string):
    if not DEBUG:
        return
    print string

def write(string):
    if not DEBUG:
        return
    print string,

    
class DbgTimer(object):
    def __init__(self):
        self.startt = 0
        self.stopt = 0
        self.time = 0
        
    def start(self):
        if not DEBUG:
            return
        self.startt = datetime.now()

    def stop(self):
        if not DEBUG:
            return
        self.stopt = datetime.now()
        self.time = self.stopt - self.startt


class AudioDecoder(object):
    def __init__(self, rate, seconds, winsize):
        self.seconds = seconds
        self.rate = rate
        self.winsize = winsize
        self.ma = mirageaudio_initialize(
            c_int(rate), c_int(seconds), c_int(winsize))

    def __del__(self):
        mirageaudio_destroy(self.ma)
        self.ma = None
        
    def decode(self, filename):
        frames = c_int(0)
        size = c_int(0)
        ret = c_int(0)

        frames_requested = self.seconds * self.rate / self.winsize
        data = mirageaudio_decode(
            self.ma, filename, byref(frames), byref(size), byref(ret))
        if ret == -1:
            raise AudioDecoderErrorException
        elif ret == -2:
            raise AudioDecoderCanceledException
        elif frames <= 0 or size <= 0:
            raise AudioDecoderErrorException

        write_line("Mirage: decoded frames=%s,size=%s" % (frames, size))

        # build a list of tuples with (value, position), then sort
        # it according to value.
        frameselection = [0.0] * frames.value
        for j in range(frames.value):
            for i in range(size.value):
                frameselection[j] += data[i*frames.value+j]
        frameselection = [(frame, i) for i, frame in enumerate(frameselection)]
        frameselection.sort()
        copyframes = frames.value / 2
        stft = Matrix(size.value, copyframes)
        for j in range(copyframes):
            for i in range(size.value):
                stft.d[i, j] = data[
                    i*frames.value+frameselection[copyframes+j][1]]
        return stft

    def cancel_decode(self):
        mirageaudio_canceldecode(self.ma)


class Matrix(object):
    def __init__(self, rows, columns):
        self.rows = rows
        self.columns = columns
        self.d = zeros([rows, columns])

    def multiply(self, m2):
        if self.columns != m2.rows:
            print self.columns, m2.rows
            raise MatrixDimensionMismatchException
        m3 = Matrix(self.rows, m2.columns)
        m3.d = dot(self.d, m2.d)
        return m3

    def mean(self):
        mean = Vector(self.rows)
        mean.d = self.d.mean(1)
        return mean
    
    def mprint(self, rows, columns):
        print "Rows: %s Columns: %s" % (self.rows, self.columns)
        print '['
        for i in range(rows):
            for j in range(columns):
                print self.d[i, j],
            print ";"
        print ']'

    def print_turn(self, rows, columns):
        print "Rows: %s Columns: %s" % (self.rows, self.columns)
        print '['
        for i in range(columns):
            for j in range(rows):
                print self.d[j, i],
            print ";"
        print ']'
        
    def covariance(self, mean):
        cache = Matrix(self.rows, self.columns)
        factor = 1.0 / (self.columns - 1)
        for j in range(self.rows):
            for i in range(self.columns):
                cache.d[j, i] = self.d[j, i] - mean.d[j]

        cov = Matrix(mean.rows, mean.rows)
        for i in range(cov.rows):
            for j in range(i+1):
                sum = 0.0
                for k in range(self.columns):
                    sum += cache.d[i, k] * cache.d[j, k]
                sum *= factor
                cov.d[i, j] = sum
                if i == j:
                    continue
                cov.d[j, i] = sum 
        return cov

    def write(self, filename):
        """we will use pickle, I think"""
        pass
    
    def load(self, filename):
        f = open(filename, 'rb')
        bytes = f.read(4)
        self.rows = struct.unpack('=l', bytes)[0]
        bytes = f.read(4)
        self.columns = struct.unpack('=l', bytes)[0]
        arr = fromfile(file=f, dtype=single)
        self.d = arr.reshape(self.rows, self.columns)

    def inverse(self):
        # XXX breaks if rows > cols ?
        e = array([Decimal()] * ((self.rows + 1) * (self.columns + 1)))
        e = e.reshape([self.rows + 1, self.columns + 1])
        for i in range(1, self.rows + 1):
            e[i, i] = Decimal(1)
        m = array([Decimal()] * ((self.rows + 1) * (self.columns + 1)))
        m = m.reshape([self.rows + 1, self.columns + 1])
        for i in range(1, self.rows + 1):
            for j in range(1, self.columns + 1):
                m[i, j] = Decimal(str(self.d[i - 1, j - 1]))
        gauss_jordan(m, self.rows, e, self.rows)
        inv = Matrix(self.rows, self.columns)
        for i in range(1, self.rows + 1):
            for j in range(1, self.columns + 1):
                inv.d[i - 1, j - 1] = m[i, j]
        return inv

            
class Vector(Matrix):
    def __init__(self, rows):
        super(Vector, self).__init__(rows, 1)

class CovarianceMatrix(object):
    def __init__(self, dim_or_matrix):
        from_matrix = isinstance(dim_or_matrix, Matrix)
        if not from_matrix:
            self.dim = dim_or_matrix
            self.d = zeros([(self.dim * self.dim + self.dim) / 2])
        else:
            self.dim = dim_or_matrix.rows
            self.d = zeros([(self.dim * self.dim + self.dim) / 2])
            l = 0
            for i in range(self.dim):
                for j in range(i, dim_or_matrix.columns):
                    self.d[l] = dim_or_matrix.d[i,j];
                    l += 1
        
class Db(object):
    def __init__(self, path):
        self.dbpath = path
        self.connection = None
        connection = self.get_database_connection()
        connection.execute(
            "CREATE TABLE IF NOT EXISTS mirage (trackid INTEGER PRIMARY KEY, "
            "scms BLOB)")
        connection.execute(
            "CREATE TABLE IF NOT EXISTS distance (track_1 INTEGER, track_2 "
            "INTEGER, distance INTEGER)")
        connection.commit()
        self.close_database_connection(connection)

    def close_database_connection(self, connection):
        if self.dbpath == ':memory:':
            return
        connection.close()
        
    def get_database_connection(self):
        if self.dbpath == ':memory:':
            if not self.connection:
                self.connection = sqlite3.connect(':memory:')
            return self.connection
        return sqlite3.connect(
            self.dbpath, timeout=5.0, isolation_level="immediate")
    
    def add_track(self, trackid, scms):
        connection = self.get_database_connection()
        connection.execute("INSERT INTO mirage (trackid, scms) VALUES (?, ?)",
                       (trackid,
                        sqlite3.Binary(instance_to_picklestring(scms))))
        connection.commit()
        self.close_database_connection(connection)

    def remove_track(self, trackid):
        connection = self.get_database_connection()
        connection.execute("DELETE FROM mirage WHERE trackid = ?", (trackid,))
        connection.commit()
        self.close_database_connection(connection)

    def remove_tracks(self, trackids):
        connection = self.get_database_connection()
        connection.execute("DELETE FROM mirage WHERE trackid IN ?", (
            ','.join(trackids),))
        connection.commit()
        self.close_database_connection(connection)

    def get_track(self, trackid):
        connection = self.get_database_connection()
        rows = connection.execute(
            "SELECT scms FROM mirage WHERE trackid = ?", (trackid,))
        for row in rows:
            self.close_database_connection(connection)
            return instance_from_picklestring(row[0])
        self.close_database_connection(connection)
        return None
    
    def get_tracks(self, exclude_ids=None):
        if not exclude_ids:
            exclude_ids = []
        connection = self.get_database_connection()
        rows = connection.execute(
            "SELECT scms, trackid FROM mirage WHERE trackid NOT IN (%s);" %
            ','.join([str(ex) for ex in exclude_ids]))
        result = [row for row in rows]
        self.close_database_connection(connection)
        return result
    
    def get_all_track_ids(self):
        connection = self.get_database_connection()
        rows = connection.execute("SELECT trackid FROM mirage")
        result = [row[0] for row in rows]
        self.close_database_connection(connection)
        return result
        
    def reset(self):
        connection = self.get_database_connection()
        connection.execute("DELETE FROM mirage")
        connection.commit()
        self.close_database_connection(connection)

    def add_and_compare(self, trackid, scms, cutoff=15000, exclude_ids=None):
        if not exclude_ids:
            exclude_ids = []
        self.add_track(trackid, scms)
        c = ScmsConfiguration(20)
        added = 0
        best_of_the_rest = []
        for buf, otherid in self.get_tracks(
            exclude_ids=exclude_ids):
            if trackid == otherid:
                continue
            other = instance_from_picklestring(buf)
            dist = int(distance(scms, other, c) * 1000)
            if dist < cutoff:
                connection = self.get_database_connection()
                connection.execute(
                    "INSERT INTO distance (track_1, track_2, distance) "
                    "VALUES (?, ?, ?)",
                    (trackid, otherid, dist))
                connection.commit()
                self.close_database_connection(connection)
                added += 1
            else:
                if len(best_of_the_rest) > 9:
                    if dist > best_of_the_rest[-1][0]:
                        continue
                best_of_the_rest.append((dist, trackid, otherid))
                best_of_the_rest.sort()
                while len(best_of_the_rest) > 10:
                    best_of_the_rest.pop()
            yield
        while best_of_the_rest and added < 10:
            dist, trackid, otherid = best_of_the_rest.pop(0)
            connection = self.get_database_connection()
            connection.execute(
                "INSERT INTO distance (track_1, track_2, distance) "
                "VALUES (?, ?, ?)",
                (trackid, otherid, dist))
            connection.commit()
            self.close_database_connection(connection)
            yield
            added += 1
        print "added %d connections" % added
        
    def compare(self, id1, id2):
        c = ScmsConfiguration(20)
        t1 = self.get_track(id1)
        t2 = self.get_track(id2)
        return int(distance(t1, t2, c) * 1000)
        
    def get_neighbours(self, trackid):
        connection = self.get_database_connection()
        neighbours1 = [row for row in connection.execute(
            "SELECT distance, track_2 FROM distance WHERE track_1 = ? "
            "ORDER BY distance ASC LIMIT 100",
            (trackid,))]
        neighbours2 = [row for row in connection.execute(
            "SELECT distance, track_1 FROM distance WHERE track_2 = ? "
            "ORDER BY distance ASC LIMIT 100",
            (trackid,))]
        self.close_database_connection(connection)
        neighbours1.extend(neighbours2)
        neighbours1.sort()
        return neighbours1
            
class Mfcc(object):
    def __init__(self, winsize, srate, filters, cc):
        here = os.path.dirname( __file__)
        self.dct = Matrix(1,1)
        self.dct.load(os.path.join(here, 'res', 'dct.filter'))
        self.filterweights = Matrix(1,1)
        self.filterweights.load(os.path.join(
            here, 'res', 'filterweights.filter'))

    def apply(self, m):
        def f(x):
            if x < 1.0:
                return 0.0
            return 10.0 * math.log10(x)
        vf = vectorize(f)
        
        t = DbgTimer()
        t.start()
        mel = Matrix(self.filterweights.rows, m.columns)
        mel = self.filterweights.multiply(m)
        mel.d = vf(mel.d)
        mel.d = mel.d + dot(self.filterweights.d, m.d)
        mel.d = vf(mel.d)
        
        try:
            mfcc = self.dct.multiply(mel)
            t.stop()
            write_line("Mirage: mfcc Execution Time: %s" % t.time)
            return mfcc
        except MatrixDimensionMismatchException:
            raise MfccFailedException

def scms_factory(mfcc):
    t = DbgTimer()
    t.start()
    s = Scms()
    s.mean = mfcc.mean()
    full_cov = mfcc.covariance(s.mean)

    s.cov = CovarianceMatrix(full_cov)
    for i in range(s.cov.dim):
        for j in range(i + 1, s.cov.dim):
            s.cov.d[i * s.cov.dim + j - (i * i + i)/2] *= 2
    try:
        full_icov = full_cov.inverse()
        s.icov = CovarianceMatrix(full_icov)
    except MatrixSingularException:
        raise ScmsImpossibleException
    t.stop()
    write_line("Mirage: scms created in: %s" % t.time)
    return s

def instance_from_picklestring(picklestring):
    f = StringIO(picklestring)
    return pickle.load(f)

def instance_to_picklestring(instance):
    f = StringIO()
    pickle.dump(instance, f)
    return f.getvalue()

class ScmsConfiguration(object):
    def __init__(self, dimension):
        self.dim = dimension
        self.covlen = (self.dim * self.dim + self.dim) / 2
        self.mdiff = zeros([self.dim])
        self.aicov = zeros([self.covlen])

    def get_dimension(self):
        return self.dim

    def get_covariance_length(self):
        return self.covlen

    def get_add_inverse_covariance(self):
        return self.aicov

    def get_mean_diff(self):
        return self.mdiff


class Scms(object):
    def __init__(self):
        self.mean = None
        self.cov = None
        self.icov = None

    
class Mir(object):

    def __init__(self):
        self.samplingrate = 22050
        self.windowsize = 1024
        self.melcoefficients = 36
        self.mfcccoefficients = 20
        self.secondstoanalyze = 120

        self.mfcc = Mfcc(
            self.windowsize, self.samplingrate, self.melcoefficients,
            self.mfcccoefficients)
        self.ad = AudioDecoder(
            self.samplingrate, self.secondstoanalyze, self.windowsize)

    def cancel_analyze(self):
        self.ad.cancel_decode()

    def analyze(self, filename):
        t = DbgTimer()
        t.start()

        stftdata = self.ad.decode(filename)
        mfccdata = self.mfcc.apply(stftdata)
        scms = scms_factory(mfccdata)

        t.stop()
        return scms
        
    def similar_tracks(ids, exclude, db, length=0):
        seed_scms = []
        for i in range(len(ids)):
            seed_scms.append(db.get_track(ids[i]))
        ht = {}
        mapping = []
        read = 1

        t = DbgTimer()
        t.start()

        c = ScmsConfiguration(self.mfcccoefficients)

        cursor = db.get_tracks(exclude)
        for row in cursor.fetchall():
            cur_scms = instance_from_picklestring(row[0])
            cur_id = row[1]
            d = 0.0        
            count = 0.0
            for j in range(len(seed_scms)):
                dcur = distance(seed_scms[j], cur_scms, c)
                if dcur >= 0:
                    d += dcur
                    count += 1
                else:
                    write_line(
                        "Mirage: Faulty SCMS id=" + mapping[i] + "d=" + d)
                    # XXX Almost certainly wrong
                    d = float(sys.maxint)
                    break
            if d >= 0:
                ht[mapping[i]] = d/count
        keys = [key for (key, value) in sorted(ht.items(), key=itemgetter(1))]
        if length:
            keys = keys[:length]
        t.stop()
        write_line("Mirage: playlist in: %s" % t.time)
        return keys

## if __name__ == '__main__':
##     mir = Mir()
##     scms = mir.analyze('testfiles/test.mp3')
##     scms2 = mir.analyze('testfiles/test2.mp3')
##     scms3 = mir.analyze('testfiles/test3.ogg')
##     scms4 = mir.analyze('testfiles/test4.ogg')
##     scms5 = mir.analyze('testfiles/test5.ogg')
##     scmses = [scms, scms2, scms3, scms4, scms5]

##     testdb = Db(":memory:")
##     for i, scms in enumerate(scmses):
##         testdb.add_track(i, scms)
        
##     print sorted(
##         [id for (scms, id) in testdb.get_tracks(exclude_ids=['3','4'])]) # [0,1,2]

##     scms3_db = testdb.get_track('3')
##     scms4_db = testdb.get_track('4')
##     c = ScmsConfiguration(20)
##     print int(distance(scms3_db, scms4_db, c) * 100) # 9647

