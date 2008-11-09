import os, struct, math
from decimal import Decimal
from datetime import datetime, timedelta
from operator import itemgetter
import cPickle as pickle
from cStringIO import StringIO
from ctypes import *
from scipy import *
import gst, gobject
import sqlite3

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
    def __init__(self, rate, seconds, skipseconds, winsize):
        self.seconds = seconds
        self.rate = rate
        self.winsize = winsize
        self.ma = mirageaudio_initialize(
            c_int(rate), c_int(seconds + 2 * skipseconds),
            c_int(winsize))
        
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


        if frames <= frames_requested:
            startframe = 0
            copyframes = frames
        else:
            startframe = frames.value / 2 - (frames_requested / 2)
            copyframes = frames_requested

        write_line("Mirage: decoded frames=%s,size=%s" % (frames, size))
            
        stft = Matrix(size.value, copyframes)
        for i in range(size.value):
            for j in range(copyframes):
                stft.d[i, j] = data[i*frames.value+j+startframe]
        return stft
    
    def free_decoder(self):
        mirageaudio_destroy(self.ma)
        self.ma = None

    def cancel_decode(self):
        mirageaudio_canceldecode(self.ma)


class Matrix(object):
    def __init__(self, rows, columns):
        self.rows = rows
        self.columns = columns
        self.d = zeros([rows, columns])

    def multiply(self, m2):
        if self.columns != m2.rows:
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
        self.rows = struct.unpack('l', bytes)[0]
        bytes = f.read(4)
        self.columns = struct.unpack('l', bytes)[0]
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
    def __init__(self, dbfile):
        self.connection = sqlite3.connect(dbfile)
        cursor = self.connection.cursor()
        cursor.execute("CREATE TABLE IF NOT EXISTS mirage (trackid INTEGER "
                       "PRIMARY KEY, scms BLOB)")
        self.connection.commit()

    def add_track(self, trackid, scms):
        cursor = self.connection.cursor()
        cursor.execute("INSERT INTO mirage (trackid, scms) VALUES (?, ?)",
                       (trackid,
                        sqlite3.Binary(instance_to_picklestring(scms))))
        self.connection.commit()

    def remove_track(self, trackid):
        cursor = self.connection.cursor()
        cursor.execute("DELETE FROM mirage WHERE trackid = ?", (trackid,))
        self.connection.commit()

    def remove_tracks(self, trackids):
        cursor = self.connection.cursor()
        cursor.execute("DELETE FROM mirage WHERE trackid IN ?", (
            ','.join(trackids),))
        self.connection.commit()

    def get_track(self, trackid):
        cursor = self.connection.cursor()
        cursor.execute("SELECT scms FROM mirage WHERE trackid = ?", (trackid,))
        row = cursor.fetchone()
        return instance_from_picklestring(row[0])

    def get_tracks(self, exclude_ids=None):
        if not exclude_ids:
            exclude_ids = []
        cursor = self.connection.cursor()
        cursor.execute("SELECT scms, trackid FROM mirage WHERE trackid"
                       " NOT IN (%s);" % ','.join(exclude_ids))
        return cursor

    def get_all_track_ids(self):
        cursor = self.connection.cursor()
        cursor.execute("SELECT trackid FROM mirage")
        return [row[0] for row in cursor.fetchall()]
        
    def reset(self):
        cursor = self.connection.cursor()
        cursor.execute("DELETE FROM mirage")
        self.connection.commit()


class Mfcc(object):
    def __init__(self, winsize, srate, filters, cc):
        self.dct = Matrix(1,1)
        self.dct.load(os.path.join('res', 'dct.filter'))
        self.filterweights = Matrix(1,1)
        self.filterweights.load(os.path.join('res', 'filterweights.filter'))

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
    
class Scms(object):
    mean = None
    cov = None
    icov = None
           
    def distance(self, scms2):
        val = 0.0
        dim = self.cov.dim
        covlen = (dim * dim + dim) / 2
        s1cov = self.cov.d
        s2icov = scms2.icov.d
        s1icov = self.icov.d
        s2cov = scms2.cov.d
        s1mean = self.mean.d
        s2mean = scms2.mean.d

        mdiff = []
        aicov = []
        for i in range(covlen):
            val += s1cov[i] * s2icov[i] + s2cov[i] * s1icov[i]
            aicov.append(s1icov[i] + s2icov[i])

        for i in range(dim):
            mdiff.append(s1mean[i] - s2mean[i])

        for i in range(dim):
            idx = i - dim
            tmp1 = 0
            for k in range(i + 1):
                idx += dim - k
                tmp1 += aicov[idx] * mdiff[k]
            for k in range(i + 1, dim):
                idx += 1
                tmp1 += aicov[idx] * mdiff[k]
            val += tmp1 * mdiff[i]

        return val
        
    
class Mir(object):

    def __init__(self):
        self.samplingrate = 11025
        self.windowsize = 512
        self.melcoefficients = 36
        self.mfcccoefficients = 20
        self.secondstoanalyze = 120
        self.secondstoskip = 15
        self.mfcc = Mfcc(
            self.windowsize, self.samplingrate, self.melcoefficients,
            self.mfcccoefficients)
        self.ad = AudioDecoder(
            self.samplingrate, self.secondstoanalyze, self.secondstoskip,
            self.windowsize)

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
        
    def similar_tracks(ids, exclude, db):
        seed_scms = []
        for i in range(len(ids)):
            seed_scms.append(db.get_track(ids[i]))
        ht = {}
        scmss = []
        mapping = []
        read = 1

        t = DbgTimer()
        t.start()

        cursor = db.get_tracks(exclude)
        for row in cursor.fetchall():
            cur_scms = instance_from_picklestring(row[0])
            cur_id = row[1]
            d = 0.0        
            count = 0.0
            for j in range(len(seed_scms)):
                dcur = seed_scms[j].distance()
                if dcur >= 0:
                    d += dcur
                    count += 1
                else:
                    write_line(
                        "Mirage: Faulty SCMS id=" + mapping[i] + "d=" + d)
                    break
            if d >= 0:
                ht[mapping[i]] = d/count
        keys = [key for (key, value) in sorted(ht.items(), key=itemgetter(1))]
        t.stop()
        write_line("Mirage: playlist in: %s" % t.time)
        return keys

## if __name__ == '__main__':
    ## mir = Mir()
    ## scms = mir.analyze('testfiles/test.mp3')
    ## scms2 = mir.analyze('testfiles/test2.mp3')
    ## scms3 = mir.analyze('testfiles/test3.ogg')
    ## scms4 = mir.analyze('testfiles/test4.ogg')
    ## scms5 = mir.analyze('testfiles/test5.ogg')
    ## scmses = [scms, scms2, scms3, scms4, scms5]

    ## testdb = Db(":memory:")
    ## for i, scms in enumerate(scmses):
    ##     testdb.add_track(i, scms)
        
    ## print sorted(
    ##     [id for (scms, id) in testdb.get_tracks(exclude_ids=['3','4'])]) # [0,1,2]

    ## scms3_db = testdb.get_track('3')
    ## scms4_db = testdb.get_track('4')

    ## print int(scms3_db.distance(scms4_db) * 100) # 9647
