import sqlite3, heapq, os
from time import sleep
from collections import deque
from datetime import datetime, timedelta
from threading import Lock

lock = Lock()

def get_userdir():
    """get the application user directory to store files"""
    userdir = os.path.join(os.path.expanduser("~"), '.autoqueue')
    if not os.path.exists(userdir):
        os.mkdir(path)
    return userdir

def transform_trackresult(tresult):
    score = tresult[0]
    result = {
        'artist': tresult[1],
        'title': tresult[2],
        'db_score': tresult[3],}
    return (score, result)

def transform_artistresult(aresult):
    score = aresult[0]
    result = {'artist': aresult[1],
              'db_score': aresult[2]}
    return (score, result)

def scale(score, max, scale_to, offset=0, invert=False):
    scaled = float(score) / float(max)
    if not invert:
        return int(scaled * scale_to) + offset
    return int((1 - scaled) * scale_to) + offset

def scale_transformer(orig, maximum, scale_to, offset=0):
    for result in orig:
        yield (scale(result[0], maximum, scale_to,
                    offset=offset, invert=True),) + result[1:] + (result[0],)

def merge(*subsequences):
    # prepare a priority queue whose items are pairs of the form
    # (current-value, iterator), one each per (non-empty) subsequence
    heap = [  ]
    for subseq in subsequences:
        iterator = iter(subseq)
        for current_value in iterator:
            # subseq is not empty, therefore add this subseq's pair
            # (current-value, iterator) to the list
            heap.append((current_value, iterator))
            break
    # make the priority queue into a heap
    heapq.heapify(heap)
    while heap:
        # get and yield lowest current value (and corresponding iterator)
        current_value, iterator = heap[0]
        yield current_value
        for current_value in iterator:
            # subseq is not finished, therefore add this subseq's pair
            # (current-value, iterator) back into the priority queue
            heapq.heapreplace(heap, (current_value, iterator))
            break
        else:
            # subseq has been exhausted, therefore remove it from the queue
            heapq.heappop(heap)

class Throttle(object):
    def __init__(self, wait):
        self.wait = wait
        self.last_called = datetime.now()

    def __call__(self, func):
        def wrapper(*orig_args):
            while self.last_called + self.wait > datetime.now():
                sleep(0.1)
            result = func(*orig_args)
            self.last_called = datetime.now()
            return result
        return wrapper


class Cache(object):
    """
    >>> dec_cache = Cache(10)
    >>> @dec_cache
    ... def identity(f):
    ...     return f
    >>> dummy = [identity(x) for x in range(20) + range(11,15) + range(20) +
    ... range(11,40) + [39, 38, 37, 36, 35, 34, 33, 32, 16, 17, 11, 41]] 
    >>> dec_cache.t1
    deque([(41,)])
    >>> dec_cache.t2
    deque([(11,), (17,), (16,), (32,), (33,), (34,), (35,), (36,), (37,)])
    >>> dec_cache.b1
    deque([(31,), (30,)])
    >>> dec_cache.b2
    deque([(38,), (39,), (19,), (18,), (15,), (14,), (13,), (12,)])
    >>> dec_cache.p
    5
    """
    def __init__(self, size):
        self.cached = {}
        self.c = size
        self.p = 0
        self.t1 = deque()
        self.t2 = deque()
        self.b1 = deque()
        self.b2 = deque()
        self.hits = 0
        self.misses = 0
        
    def replace(self, args):
        if self.t1 and (
            (args in self.b2 and len(self.t1) == self.p) or
            (len(self.t1) > self.p)):
            old = self.t1.pop()
            self.b1.appendleft(old)
        else:
            old = self.t2.pop()
            self.b2.appendleft(old)
        del(self.cached[old])
        
    def __call__(self, func):
        def wrapper(*orig_args):
            """decorator function wrapper"""
            args = orig_args[:]
            if args in self.t1: 
                self.t1.remove(args)
                self.t2.appendleft(args)
                self.hits += 1
                ## print repr(func)
                ## print "hits: %04d, misses: %04d, rate: %.2f, p: %s of %s" % (
                ##     self.hits, self,misses, float(self.hits)/float(self.misses),
                ##     self.p, self.size)
                return self.cached[args]
            if args in self.t2: 
                self.t2.remove(args)
                self.t2.appendleft(args)
                self.hits += 1
                #print repr(func)
                #print "hits: %04d, misses: %04d, rate: %.2f, p: %s of %s" % (
                #    self.hits, self,misses, float(self.hits)/float(self.misses),
                #    self.p, self.size)
                return self.cached[args]
            self.misses += 1
            result = func(*orig_args)
            self.cached[args] = result
            if args in self.b1:
                self.p = min(
                    self.c, self.p + max(len(self.b2) / len(self.b1) , 1))
                self.replace(args)
                self.b1.remove(args)
                self.t2.appendleft(args)
                return result            
            if args in self.b2:
                self.p = max(0, self.p - max(len(self.b1)/len(self.b2) , 1))
                self.replace(args)
                self.b2.remove(args)
                self.t2.appendleft(args)
                return result
            if len(self.t1) + len(self.b1) == self.c:
                if len(self.t1) < self.c:
                    self.b1.pop()
                    self.replace(args)
                else:
                    del(self.cached[self.t1.pop()])
            else:
                total = len(self.t1) + len(self.b1) + len(
                    self.t2) + len(self.b2)
                if total >= self.c:
                    if total == (2 * self.c):
                        self.b2.pop()
                    self.replace(args)
            self.t1.appendleft(args)
            return result
        return wrapper


class DbManager(object):
    def __init__(self):
        self.con = None
        self.dirty = False
        
    def set_path(self, path):
        self.con = sqlite3.connect(path)
        
    def sql_query(self, sql):
        cur = self.con.cursor()
        return cur.execute(*sql)

    def sql_statement(self, sql):
        lock.acquire()
        try:
            cur = self.con.cursor()
            cur.execute(*sql)
            self.con.commit()
        finally:
            lock.release()
        
    def create_db(self):
        """ Set up a database for the artist and track similarity scores
        """
        self.sql_statement(
            ("CREATE TABLE IF NOT EXISTS artists (id INTEGER PRIMARY KEY, "
             "name VARCHAR(100), updated DATE);",))
        self.sql_statement(
            ("CREATE TABLE IF NOT EXISTS artist_2_artist (artist1 INTEGER, "
             "artist2 INTEGER, match INTEGER);",))
        self.sql_statement(
            ("CREATE TABLE IF NOT EXISTS tracks (id INTEGER PRIMARY KEY, "
             "artist INTEGER, title VARCHAR(100), updated DATE);",))
        self.sql_statement(
            ("CREATE TABLE IF NOT EXISTS track_2_track (track1 INTEGER, "
             "track2 INTEGER, match INTEGER);",))
        self.sql_statement(
            ("CREATE TABLE IF NOT EXISTS mirage (trackid INTEGER PRIMARY KEY, "
             "scms BLOB)",))
        self.sql_statement(
            ("CREATE TABLE IF NOT EXISTS distance (track_1 INTEGER, track_2 "
             "INTEGER, distance INTEGER);",))
