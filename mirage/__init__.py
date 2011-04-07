"""Mirage integration for autoqueue.
version 0.3

Copyright 2007-2010 Eric Casteleijn <thisfred@gmail.com>,
                    Paolo Tranquilli <redsun82@gmail.com>


This program is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation; either version 2, or (at your option)
any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program; if not, write to the Free Software
Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA 02110-1301  USA.
"""

import os, struct, math
from decimal import Decimal
from datetime import datetime
import cPickle as pickle
from cStringIO import StringIO
from ctypes import *
import sqlite3
from scipy import *

DEBUG = True


class MirageAudio(Structure):
    pass


cdll.LoadLibrary("/usr/lib/banshee/Extensions/libmirageaudio.so")
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


class AudioDecoderErrorException(Exception):
    pass


class AudioDecoderCanceledException(Exception):
    pass


mirageaudio_initialize = libmirageaudio.mirageaudio_initialize
mirageaudio_decode = libmirageaudio.mirageaudio_decode
mirageaudio_decode.restype = POINTER(c_float)
mirageaudio_destroy = libmirageaudio.mirageaudio_destroy
mirageaudio_canceldecode = libmirageaudio.mirageaudio_canceldecode

def distance(scms1, scms2, scmsconf):
    val = 0.0
    dim = scmsconf.get_dimension()
    covlen = scmsconf.get_covariance_length()
    s1cov = scms1.cov
    s2icov = scms2.icov
    s1icov = scms1.icov
    s2cov = scms2.cov
    s1mean = scms1.mean
    s2mean = scms2.mean

    for i in range(covlen):
        scmsconf.aicov[i] = s1icov[i] + s2icov[i]

    for i in range(dim):
        idx = i * dim - (i * i + i) / 2
        val += s1cov[idx + i] * s2icov[idx + i] + s2cov[idx + i] * s1icov[
            idx + i]
        for k in range (i+1, dim):
            val += 2 * s1cov[idx + k] * s2icov[idx + k] + 2 * s2cov[
                idx + k] * s1icov[idx + k]

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
    val = val / 4 - scmsconf.get_dimension() / 2
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

    def decode(self, filename):
        frames = c_int(0)
        size = c_int(0)
        ret = c_int(0)

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
        thebytes = f.read(4)
        self.rows = struct.unpack('=l', thebytes)[0]
        thebytes = f.read(4)
        self.columns = struct.unpack('=l', thebytes)[0]
        arr = fromfile(file=f, dtype=single)
        self.d = arr.reshape(self.rows, self.columns)

    def inverse(self):
        e = array([Decimal()] * ((self.rows + 1) * (self.columns + 1)))
        e = e.reshape([self.rows + 1, self.columns + 1])
        for i in range(1, self.rows + 1):
            e[i, i] = Decimal(1)
        m = array([Decimal()] * ((self.rows + 1) * (self.columns + 1)))
        m = m.reshape([self.rows + 1, self.columns + 1])
        for i in range(1, self.rows + 1):
            for j in range(1, self.columns + 1):
                # XXX: the replace is a necessary hack for locales
                # where str(Decimal) uses commas. If anyone has a
                # better solution, please let me know.
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


class Db(object):
    def __init__(self, path, connection=None):
        self.dbpath = path
        self.connection = connection

    def close_database_connection(self, connection):
        if self.dbpath == ':memory:':
            return
        connection.close()

    def get_database_connection(self):
        if self.dbpath == ':memory:':
            if not self.connection:
                self.connection = sqlite3.connect(':memory:')
                self.connection.text_factory = str
            return self.connection
        connection = sqlite3.connect(
            self.dbpath, timeout=5.0, isolation_level="immediate")
        connection.text_factory = str
        return connection

    def add_track(self, filename, scms):
        connection = self.get_database_connection()
        connection.execute("INSERT INTO mirage (filename, scms) VALUES (?, ?)",
                       (filename,
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
        connection.execute("DELETE FROM mirage WHERE trackid IN (%s);" % (
            ','.join(trackids),))
        connection.commit()
        self.close_database_connection(connection)

    def get_track(self, filename):
        connection = self.get_database_connection()
        rows = connection.execute(
            "SELECT trackid, scms FROM mirage WHERE filename = ?", (filename,))
        for row in rows:
            self.close_database_connection(connection)
            return (row[0], instance_from_picklestring(row[1]))
        self.close_database_connection(connection)
        return None

    def get_track_id(self, filename):
        connection = self.get_database_connection()
        rows = connection.execute(
            "SELECT trackid FROM mirage WHERE filename = ?", (filename,))
        for row in rows:
            self.close_database_connection(connection)
            return row[0]
        self.close_database_connection(connection)
        return None

    def has_scores(self, trackid, no=20):
        connection = self.get_database_connection()
        cursor = connection.execute(
            'SELECT COUNT(*) FROM distance WHERE track_1 = ?',
            (trackid,))
        l1 = cursor.fetchone()[0]
        self.close_database_connection(connection)
        if l1 < no:
            print "Only %d connections found, minimum %d." % (l1, no)
            return False
        connection = self.get_database_connection()
        cursor = connection.execute(
            "SELECT COUNT(track_1) FROM distance WHERE track_2 = ? AND "
            "distance < (SELECT MAX(distance) FROM distance WHERE track_1 = "
            "?);", (trackid, trackid))
        l2 = cursor.fetchone()[0]
        self.close_database_connection(connection)
        if l2 > l1:
            print "Found %d incoming connections and only %d outgoing." % (
                l2, l1)
            return False
        return True

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

    def add_neighbours(self, trackid, scms, exclude_ids=None, neighbours=20):
        to_add = neighbours * 2
        connection = self.get_database_connection()
        connection.execute(
            "DELETE FROM distance WHERE track_1 = ?", (trackid,))
        connection.commit()
        self.close_database_connection(connection)
        yield
        if not exclude_ids:
            exclude_ids = []
        c = ScmsConfiguration(20)
        best = []
        for buf, otherid in self.get_tracks(
            exclude_ids=exclude_ids):
            if trackid == otherid:
                yield
                continue
            other = instance_from_picklestring(buf)
            dist = int(distance(scms, other, c) * 1000)
            if dist < 0:
                yield
                continue
            if len(best) > to_add - 1:
                if dist > best[-1][0]:
                    yield
                    continue
            best.append((dist, trackid, otherid))
            best.sort()
            while len(best) > to_add:
                best.pop()
            yield
        added = 0
        if best:
            connection = self.get_database_connection()
            while best:
                added += 1
                best_tup = best.pop()
                try:
                    connection.execute(
                        "INSERT INTO distance (distance, track_1, track_2) "
                        "VALUES (?, ?, ?)", best_tup)
                except OverFlowError:
                    print "SNAFU:", repr(best_tup)
            connection.commit()
            self.close_database_connection(connection)
        print "added %d connections" % added

    def compare(self, id1, id2):
        c = ScmsConfiguration(20)
        t1 = self.get_track(id1)[1]
        t2 = self.get_track(id2)[1]
        return int(distance(t1, t2, c) * 1000)

    def get_filename(self, trackid):
        connection = self.get_database_connection()
        rows = connection.execute(
            'SELECT filename FROM mirage WHERE trackid = ?', (trackid, ))
        filename = None
        for row in rows:
            try:
                filename = unicode(row[0], 'utf-8')
            except UnicodeDecodeError:
                break
            break
        connection.close()
        return filename

    def get_neighbours(self, trackid):
        connection = self.get_database_connection()
        neighbours = [row for row in connection.execute(
            "SELECT distance, track_2 FROM distance WHERE track_1 = ? "
            "ORDER BY distance ASC",
            (trackid,))]
        self.close_database_connection(connection)
        return neighbours

class Mfcc(object):
    def __init__(self, winsize, srate, filters, cc):
        here = os.path.dirname( __file__)
        self.dct = Matrix(1,1)
        self.dct.load(os.path.join(here, 'res', 'dct.filter'))
        self.filterweights = Matrix(1,1)
        self.filterweights.load(os.path.join(
            here, 'res', 'filterweights.filter'))

        self.fwft = [[0, 0]] * self.filterweights.rows
        for i in range(self.filterweights.rows):
            last = 0.0
            for j in range(self.filterweights.columns):
                if self.filterweights.d[i, j] and last:
                    self.fwft[i][0] = j
                elif last and not self.filterweights.d[i, j]:
                    self.fwft[i][1] = j
                last = self.filterweights.d[i, j]
                if last:
                    self.fwft[i][1] = self.filterweights.columns

    def apply(self, m):
        def f(x):
            if x < 1.0:
                return 0.0
            return 10.0 * math.log10(x)
        vf = vectorize(f)

        t = DbgTimer()
        t.start()
        mel = Matrix(self.filterweights.rows, m.columns)
        try:
            mel.d = mel.d + dot(self.filterweights.d, m.d)
        except ValueError:
            raise MfccFailedException
        mel.d = vf(mel.d)

        try:
            mfcc = self.dct.multiply(mel)
            t.stop()
            write_line("Mirage: mfcc Execution Time: %s" % t.time)
            return mfcc
        except MatrixDimensionMismatchException:
            raise MfccFailedException


def instance_from_picklestring(picklestring):
    f = StringIO(picklestring)
    return pickle.load(f)

def instance_to_picklestring(instance):
    f = StringIO()
    pickle.dump(instance, f, protocol=2)
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
    def __init__(self, dim):
        self.mean = []
        self.cov = []
        self.icov = []
        self.dim = dim
        self.sym_dim = (dim * dim + dim) / 2


def scms_factory(mfcc):
    t = DbgTimer()
    t.start()

    m = mfcc.mean()

    c = mfcc.covariance(m)

    try:
        ic = c.inverse()
    except MatrixSingularException:
        raise ScmsImpossibleException

    dim = m.rows
    s = Scms(dim)
    for i in range(dim):
        s.mean.append(m.d[i])
        for j in range(i, dim):
            s.cov.append(c.d[i, j])
            s.icov.append(ic.d[i, j])
    t.stop()
    write_line("Mirage: scms created in: %s" % t.time)
    return s


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
