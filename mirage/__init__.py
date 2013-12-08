"""Mirage integration for autoqueue.
version 0.3

Copyright 2007-2012 Eric Casteleijn <thisfred@gmail.com>,
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

import math
import os
import struct

import cPickle as pickle

from decimal import Decimal
from cStringIO import StringIO
from ctypes import cdll, Structure, POINTER, c_float, c_int, byref
from scipy import array, fromfile, zeros, dot, single, vectorize

import gi
gi.require_version('Gst', '1.0')
from gi.repository import GObject, Gst

GObject.threads_init()
Gst.init(None)


class MirageAudio(Structure):
    """Mirage audio."""
    pass


try:
    libmirageaudio = cdll.LoadLibrary(
        "/usr/lib/banshee/Extensions/libmirageaudio.so")
except:
    libmirageaudio = cdll.LoadLibrary(
        "/usr/lib/banshee-1/Extensions/libmirageaudio.so")


class MatrixDimensionMismatchException(Exception):
    """Matrix dimension mismatch."""
    pass


class MatrixSingularException(Exception):
    """Matrix singular."""
    pass


class MfccFailedException(Exception):
    """Mfcc failed."""
    pass


class ScmsImpossibleException(Exception):
    """Scms impossible."""
    pass


class MirAnalysisImpossibleException(Exception):
    """Mir analysis impossible."""
    pass


class AudioDecoderErrorException(Exception):
    """Audio decoder error."""
    pass


class AudioDecoderCanceledException(Exception):
    """Audio decoder canceled."""
    pass

mirageaudio_initialize = libmirageaudio.mirageaudio_initialize
mirageaudio_decode = libmirageaudio.mirageaudio_decode
mirageaudio_decode.restype = POINTER(c_float)
mirageaudio_destroy = libmirageaudio.mirageaudio_destroy
mirageaudio_canceldecode = libmirageaudio.mirageaudio_canceldecode


def distance(scms1, scms2, scmsconf):
    """Compute distance between two scmses."""
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
        for k in range(i + 1, dim):
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
    """Gauss Jordan."""
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
                a[ll, icol] = Decimal(0)
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


class AudioDecoder(object):
    """Audio decoder."""

    def __init__(self, rate, seconds, winsize):
        self.seconds = seconds
        self.rate = rate
        self.winsize = winsize
        self.ma = mirageaudio_initialize(
            c_int(rate), c_int(seconds), c_int(winsize))

    def decode(self, filename):
        """Decode audio in filename."""
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

        # build a list of tuples with (value, position), then sort
        # it according to value.
        frameselection = [0.0] * frames.value
        for j in range(frames.value):
            for i in range(size.value):
                frameselection[j] += data[i * frames.value + j]
        frameselection = [(frame, i) for i, frame in enumerate(frameselection)]
        frameselection.sort()
        copyframes = frames.value / 2
        stft = Matrix(size.value, copyframes)
        for j in range(copyframes):
            for i in range(size.value):
                stft.d[i, j] = data[
                    i * frames.value + frameselection[copyframes + j][1]]
        return stft

    def cancel_decode(self):
        """Cancel decoding."""
        mirageaudio_canceldecode(self.ma)


class Matrix(object):
    """Matrix."""

    def __init__(self, rows, columns):
        self.rows = rows
        self.columns = columns
        self.d = zeros([rows, columns])

    def multiply(self, m2):
        """Matrix multiplication."""
        if self.columns != m2.rows:
            raise MatrixDimensionMismatchException
        m3 = Matrix(self.rows, m2.columns)
        m3.d = dot(self.d, m2.d)
        return m3

    def mean(self):
        """Matrix mean."""
        mean = Vector(self.rows)
        mean.d = self.d.mean(1)
        return mean

    def covariance(self, mean):
        """Matrix covariance."""
        cache = Matrix(self.rows, self.columns)
        factor = 1.0 / (self.columns - 1)
        for j in range(self.rows):
            for i in range(self.columns):
                cache.d[j, i] = self.d[j, i] - mean.d[j]

        cov = Matrix(mean.rows, mean.rows)
        for i in range(cov.rows):
            for j in range(i + 1):
                total = 0.0
                for k in range(self.columns):
                    total += cache.d[i, k] * cache.d[j, k]
                total *= factor
                cov.d[i, j] = total
                if i == j:
                    continue
                cov.d[j, i] = total
        return cov

    def load(self, filename):
        """Load from file."""
        f = open(filename, 'rb')
        thebytes = f.read(4)
        self.rows = struct.unpack('=l', thebytes)[0]
        thebytes = f.read(4)
        self.columns = struct.unpack('=l', thebytes)[0]
        arr = fromfile(file=f, dtype=single)
        self.d = arr.reshape(self.rows, self.columns)

    def inverse(self):
        """Matrix inverse."""
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
    """Vector."""

    def __init__(self, rows):
        super(Vector, self).__init__(rows, 1)


class Mfcc(object):
    """Mfcc."""

    def __init__(self, winsize, srate, filters, cc):
        here = os.path.dirname(__file__)
        self.dct = Matrix(1, 1)
        self.dct.load(os.path.join(here, 'res', 'dct.filter'))
        self.filterweights = Matrix(1, 1)
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
        """Apply matrix."""

        def f(x):
            """Function."""
            if x < 1.0:
                return 0.0
            return 10.0 * math.log10(x)
        vf = vectorize(f)

        mel = Matrix(self.filterweights.rows, m.columns)
        try:
            mel.d = mel.d + dot(self.filterweights.d, m.d)
        except ValueError:
            raise MfccFailedException
        mel.d = vf(mel.d)

        try:
            mfcc = self.dct.multiply(mel)
            return mfcc
        except MatrixDimensionMismatchException:
            raise MfccFailedException


def instance_from_picklestring(picklestring):
    """Read from pickle."""
    f = StringIO(picklestring)
    return pickle.load(f)


def instance_to_picklestring(instance):
    """Write to pickle."""
    f = StringIO()
    pickle.dump(instance, f, protocol=2)
    return f.getvalue()


class ScmsConfiguration(object):
    """Scms configuration."""

    def __init__(self, dimension):
        self.dim = dimension
        self.covlen = (self.dim * self.dim + self.dim) / 2
        self.mdiff = zeros([self.dim])
        self.aicov = zeros([self.covlen])

    def get_dimension(self):
        """Return dimension."""
        return self.dim

    def get_covariance_length(self):
        """Get covariance length."""
        return self.covlen

    def get_add_inverse_covariance(self):
        """Get add inverse covariance."""
        return self.aicov

    def get_mean_diff(self):
        """Get mean diff."""
        return self.mdiff


class Scms(object):
    """Scms."""

    def __init__(self, dim):
        self.mean = []
        self.cov = []
        self.icov = []
        self.dim = dim
        self.sym_dim = (dim * dim + dim) / 2


def scms_factory(mfcc):
    """Scms factory."""

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
    return s


class Mir(object):
    """Mirage analysis class."""

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
        """Cancel analysis."""
        self.ad.cancel_decode()

    def analyze(self, filename):
        """Analyze file."""
        stftdata = self.ad.decode(filename)
        mfccdata = self.mfcc.apply(stftdata)
        scms = scms_factory(mfccdata)
        return scms
