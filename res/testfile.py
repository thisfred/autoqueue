import struct, scipy
from numpy import *

f = open('dct.filter', 'rb')
a = f.read(4)
b = struct.unpack('=l', a)
a = f.read(4)
c = struct.unpack('=l', a)
print b, c
print arr
f.close()
