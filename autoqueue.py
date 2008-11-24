"""AutoQueue: an automatic queueing plugin library.
version 0.3

Copyright 2007-2008 Eric Casteleijn <thisfred@gmail.com>,
                    Daniel Nouri <daniel.nouri@gmail.com>

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

from collections import deque
from datetime import datetime, timedelta
from time import strptime, sleep
import urllib
import random, os, heapq
from xml.dom import minidom
from cPickle import Pickler, Unpickler

try:
    import sqlite3
    SQL = True
except ImportError:
    SQL = False

#try:
from mirage import Mir, Db
MIRAGE = True
#except ImportError:
#    MIRAGE = False
    
# If you change even a single character of code, I would ask that you
# get and use your own (free) last.fm api key from here:
# http://www.last.fm/api/account
API_KEY = "09d0975a99a4cab235b731d31abf0057"

TRACK_URL = "http://ws.audioscrobbler.com/2.0/?method=track.getsimilar" \
            "&artist=%s&track=%s&api_key=" + API_KEY
ARTIST_URL = "http://ws.audioscrobbler.com/2.0/?method=artist.getsimilar" \
             "&artist=%s&api_key=" + API_KEY

# be nice to last.fm
WAIT_BETWEEN_REQUESTS = timedelta(0, 0, 0, 5) 

def transform_trackresult(tresult):
    score = tresult[0]
    result = {
        'artist': tresult[1],
        'title': tresult[2]}
    return (score, result)

def transform_artistresult(aresult):
    score = aresult[0]
    result = {'artist': aresult[1]}
    return (score, result)

def scale(score, max, scale_to, offset=0, invert=False):
    scaled = float(score) / float(max)
    if not invert:
        return int(scaled * scale_to) + offset
    return int((1 - scaled) * scale_to) + offset

def scale_transformer(orig, maximum, scale_to, offset=0):
    for result in orig:
        yield (scale(result[0], maximum, scale_to,
                    offset=offset, invert=True),) + result[1:]

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
                return self.cached[args]
            if args in self.t2: 
                self.t2.remove(args)
                self.t2.appendleft(args)
                return self.cached[args]
            result = func(*orig_args)
            self.cached[args] = result
            if args in self.b1:
                self.p = min(
                    self.c, self.p + max(len(self.b2) / len(self.b1) , 1))
                self.replace(args)
                self.b1.remove(args)
                self.t2.appendleft(args)
                #print "%s:: t1:%s b1:%s t2:%s b2:%s p:%s" % (
                #    repr(func)[10:30], len(self.t1),len(self.b1),len(self.t2),
                #    len(self.b2), self.p)
                return result            
            if args in self.b2:
                self.p = max(0, self.p - max(len(self.b1)/len(self.b2) , 1))
                self.replace(args)
                self.b2.remove(args)
                self.t2.appendleft(args)
                #print "%s:: t1:%s b1:%s t2:%s b2:%s p:%s" % (
                #   repr(func)[10:30], len(self.t1),len(self.b1),len(self.t2),
                #   len(self.b2), self.p)
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


class SongBase(object):
    """A wrapper object around player specific song objects."""
    def __init__(self, song):
        self.song = song
    
    def get_artist(self):
        """return lowercase UNICODE name of artist"""
        return NotImplemented

    def get_title(self):
        """return lowercase UNICODE title of song"""
        return NotImplemented

    def get_tags(self):
        """return a list of tags for the song"""
        return []

    def get_filename(self):
        """return filename for the song"""
        return NotImplemented

    def get_length(self):
        """return length in seconds"""
        return NotImplemented
    
class AutoQueueBase(object):
    """Generic base class for autoqueue plugins."""
    use_db = False
    store_blocked_artists = False
    in_memory = False 
    def __init__(self):
        self.max_track_match = 10000
        self.max_artist_match = 10000
        self.artist_block_time = 1
        self.track_block_time = 30
        self.desired_queue_length = 0
        self.cache_time = 90
        self.by_mirage = False
        self.by_tracks = True
        self.by_artists = True
        self.by_tags = False
        self.running = False
        self.verbose = False
        self.now = datetime.now()
        self.connection = None
        self.song = None
        self._songs = deque([])
        self._blocked_artists = deque([])
        self._blocked_artists_times = deque([])
        self.relaxors = None
        self.restrictors = None
        self._artists_to_update = {}
        self._tracks_to_update = {}
        self.random = False
        self.player_set_variables_from_config()
        if self.store_blocked_artists:
            self.get_blocked_artists_pickle()
        if self.use_db:
            self.check_db()
        if MIRAGE:
            self.mir = Mir()

    def player_get_userdir(self):
        """get the application user directory to store files"""
        return NotImplemented

    def player_construct_search(self, result, restrictions=None):
        artist = result.get('artist')
        title = result.get('title')
        tags = result.get('tags')
        if title:
            return self.player_construct_track_search(
                artist, title, restrictions)
        if artist:
            return self.player_construct_artist_search(
                artist, restrictions)
        if tags:
            return self.player_construct_tag_search(
                tags, restrictions)
            
    def player_construct_track_search(self, artist, title, restrictions=None):
        """construct a search that looks for songs with this artist
        and title"""
        return NotImplemented

    def player_construct_artist_search(self, artist, restrictions=None):
        """construct a search that looks for songs with this artist"""
        return NotImplemented
    
    def player_construct_tag_search(self, tags, restrictions=None):
        """construct a search that looks for songs with these
        tags"""
        return NotImplemented
        
    def player_construct_restrictions(
        self, track_block_time, relaxors, restrictors):
        """contstruct a search to further modify the searches"""
        return NotImplemented

    def player_set_variables_from_config(self):
        """Initialize user settings from the configuration storage"""
        return NotImplemented

    def player_get_queue_length(self):
        """Get the current length of the queue"""
        return 0

    def player_enqueue(self, song):
        """Put the song at the end of the queue"""
        return NotImplemented

    def player_search(self, search):
        """perform a player search"""
        return NotImplemented

    def player_get_songs_in_queue(self):
        """return (wrapped) song objects for the songs in the queue"""
        return []

    def check_db(self):
        if self.in_memory:
            self.create_db()
            return
        try:
            os.stat(self.get_db_path())
        except OSError:
            self.create_db()

    def get_blocked_artists_pickle(self):
        dump = os.path.join(
            self.player_get_userdir(), "autoqueue_block_cache")
        try:
            pickle = open(dump, 'r')
            try:
                unpickler = Unpickler(pickle)
                artists, times = unpickler.load()
                if isinstance(artists, list):
                    artists = deque(artists)
                if isinstance(times, list):
                    times = deque(times)
                self._blocked_artists = artists
                self._blocked_artists_times = times
            finally:
                pickle.close()
        except IOError:
            pass
        
    def get_db_path(self):
        return os.path.join(self.player_get_userdir(), "similarity.db")
    
    def get_database_connection(self):
        """get database reference"""
        if self.in_memory:
            if self.connection:
                return self.connection
            return sqlite3.connect(":memory:")
        return sqlite3.connect(self.get_db_path())

    def on_song_started(self, song):
        """Should be called by the plugin when a new song starts. If
        the right conditions apply, we start looking for new songs to
        queue."""
        if song is None:
            return
        self.now = datetime.now()
        artist_name = song.get_artist()
        title = song.get_title()
        if not (artist_name and title):
            return
        self.song = song
        # add the artist to the blocked list, so their songs won't be
        # played for a determined time
        self.block_artist(artist_name)
        if self.running:
            return
        if self.desired_queue_length == 0 or self.queue_needs_songs():
            yield
            self.fill_queue()

    def cleanup(self, songs, next_artist=''):
        ret = []
        seen = []
        if next_artist:
            seen = [next_artist]
        for (score, song) in songs:
            artist = song.get_artist()
            if artist in seen:
                continue
            if self.is_blocked(artist):
                continue
            seen.append(song.get_artist())
            ret.append((score, song))
        return ret
    
    def queue_needs_songs(self):
        """determine whether the queue needs more songs added"""
        time = self.player_get_queue_length()
        return time < self.desired_queue_length

    def song_generator(self):
        """yield songs that match the last song in the queue"""
        generators = []
        last_song = self.get_last_song()
        if MIRAGE and self.by_mirage:
            self.analyze_track(self.song)
            generators.append(self.get_ordered_mirage_tracks(last_song))
        if self.by_tracks:
            generators.append(self.get_ordered_similar_tracks(last_song))
        if self.by_artists:
            generators.append(self.get_ordered_similar_artists(last_song))
        if self.by_tags:
            generators.append(self.get_ordered_tag_search(last_song))
        for result in merge(*generators):
            yield result

    def queue_song(self):
        """Queue a single track"""
        restrictions = self.player_construct_restrictions(
            self.track_block_time, self.relaxors, self.restrictors)
        self.unblock_artists()
        found = []
        generator = self.song_generator()
        while len(found) < 2:
            blocked = self.get_blocked_artists()
            try:
                score, result = generator.next()
                if self._songs:
                    if score > self._songs[0][0]:
                        break
                self.log("looking for: %s, %s" % (score, repr(result)))
                search = self.player_construct_search(result, restrictions)
                artist = result.get('artist')
                if artist:
                    if artist in blocked:
                        continue
                songs = self.player_search(search)
                if songs:
                    song = random.choice(songs)
                    songs.remove(song)
                    while (
                        song.get_artist() in blocked
                        and songs):
                        song = random.choice(songs)
                        songs.remove(song)
                    if not song.get_artist() in blocked:
                        found.append((score, song))
            except StopIteration:
                break
        if not found:
            self.log("nothing found, using backup songs")
            if self._songs:
                score, song = self._songs.popleft()
                while self.is_blocked(
                    song.get_artist()) and self._songs:
                    score, song = self._songs.pop()
                if not self.is_blocked(song.get_artist()):
                    self.player_enqueue(song)
        else:
            self.player_enqueue(found[0][1])
        if len(found) > 1:
            songs = [found[1]] + list(self._songs)
            clean = self.cleanup(songs, found[0][1].get_artist())
            self._songs = deque(clean)
            if len(self._songs) > 10:
                self._songs.pop()
        if self._songs:
            self.log("%s backup songs: \n%s" % (
                len(self._songs),
                "\n".join(["%05d %s - %s" % (
                score,
                bsong.get_artist(),
                bsong.get_title()) for score, bsong in list(self._songs)])))
        for song in generator:
            pass
        if found:
            return True
        else:
            return False

    def fill_queue(self):
        """search for appropriate songs and put them in the queue"""
        self.running = True
        if self.use_db:
            self.connection = self.get_database_connection()
        if self.desired_queue_length == 0:
            self.queue_song()
        while self.queue_needs_songs():
            if not self.queue_song():
                break
        if self.use_db:
            for artist_id in self._artists_to_update:
                self._update_similar_artists(
                    artist_id, self._artists_to_update[artist_id])
            for track_id in self._tracks_to_update:
                self._update_similar_tracks(
                    track_id, self._tracks_to_update[track_id])
            self.connection.commit()
            self._artists_to_update = {}
            self._tracks_to_update = {}
        self.running = False
   
    def block_artist(self, artist_name):
        """store artist name and current daytime so songs by that
        artist can be blocked
        """
        self._blocked_artists.append(artist_name)
        self._blocked_artists_times.append(self.now)
        self.log("Blocked artist: %s (%s)" % (
            artist_name,
            len(self._blocked_artists)))
        if self.store_blocked_artists:
            dump = os.path.join(
                self.player_get_userdir(), "autoqueue_block_cache")
            try:
                os.remove(dump)
            except OSError:
                pass
        if len(self._blocked_artists) == 0:
            return
        if self.store_blocked_artists:
            pickle_file = open(dump, 'w')
            pickler = Pickler(pickle_file, -1)
            to_dump = (self._blocked_artists,
                       self._blocked_artists_times)
            pickler.dump(to_dump)
            pickle_file.close()

    def unblock_artists(self):
        """release blocked artists when they've been in the penalty
        box for long enough
        """
        while self._blocked_artists_times:
            if self._blocked_artists_times[
                0] + timedelta(self.artist_block_time) > self.now:
                break
            self.log("Unblocked %s (%s)" % (
                self._blocked_artists.popleft(),
                self._blocked_artists_times.popleft()))

    def is_blocked(self, artist_name):
        """check if the artist was played too recently"""
        return artist_name in self.get_blocked_artists()

    def get_blocked_artists(self):
        """prevent artists already in the queue from being queued"""
        return list(self._blocked_artists) + [
            song.get_artist() for song in
            self.player_get_songs_in_queue()]

    def get_last_song(self):
        """return the last song in the queue or the currently playing
        song"""
        queue = self.player_get_songs_in_queue()
        if queue:
            return queue[-1]
        return self.song

    @Cache(1000)
    def get_track_match(self, artist1, title1, artist2, title2):
        """get match score for tracks"""
        id1 = self.get_track(artist1, title1)[0]
        id2 = self.get_track(artist2, title2)[0]
        return max(
            self._get_track_match(id1, id2),
            self._get_track_match(id2, id1))

    @Cache(1000)
    def get_artist_match(self, artist1, artist2):
        """get match score for artists"""
        id1 = self.get_artist(artist1)[0]
        id2 = self.get_artist(artist2)[0]
        return max(
            self._get_artist_match(id1, id2),
            self._get_artist_match(id2, id1))        

    def get_tag_match(self, tags1, tags2):
        """get match score for tags"""
        tags1 = set([tag.split(":")[-1] for tag in tags1])
        tags2 = set([tag.split(":")[-1] for tag in tags2])
        return len(tags1 & tags2)

    def get_similar_tracks_from_lastfm(self, artist_name, title, track_id):
        """get similar tracks to the last one in the queue"""
        self.log("Getting similar tracks from last.fm for: %s - %s" % (
            artist_name, title))
        enc_artist_name = artist_name.encode("utf-8")
        enc_title = title.encode("utf-8")
        url = TRACK_URL % (
            urllib.quote_plus(enc_artist_name),
            urllib.quote_plus(enc_title))
        xmldoc = self.last_fm_request(url)
        if xmldoc is None:
            raise StopIteration
        nodes = xmldoc.getElementsByTagName("track")
        for node in nodes:
            similar_artist = similar_title = ''
            match = None
            for child in node.childNodes:
                if child.nodeName == 'artist':
                    similar_artist = child.getElementsByTagName(
                        "name")[0].firstChild.nodeValue.lower()
                elif child.nodeName == 'name':
                    similar_title = child.firstChild.nodeValue.lower()
                elif child.nodeName == 'match':
                    match = int(float(child.firstChild.nodeValue) * 100)
                if (similar_artist != '' and similar_title != ''
                    and match is not None):
                    break
            result = {
                'match': match,
                'artist': similar_artist,
                'title': similar_title,}
            if self.use_db:
                self._tracks_to_update.setdefault(track_id, []).append(result)
            yield (
                scale(match, self.max_track_match, 10000, invert=True), result)
            
    def get_similar_artists_from_lastfm(self, artist_name, artist_id):
        """get similar artists"""
        self.log("Getting similar artists from last.fm for: %s " % artist_name)
        enc_artist_name = artist_name.encode("utf-8")
        url = ARTIST_URL % (
            urllib.quote_plus(enc_artist_name))
        xmldoc = self.last_fm_request(url)
        if xmldoc is None:
            raise StopIteration
        nodes = xmldoc.getElementsByTagName("artist")
        for node in nodes:
            name = node.getElementsByTagName(
                "name")[0].firstChild.nodeValue.lower()
            match = 0
            matchnode = node.getElementsByTagName("match")
            if matchnode:
                match = int(float(matchnode[0].firstChild.nodeValue) * 100)
            result = {
                'match': match,
                'artist': name,}
            if self.use_db:
                self._artists_to_update.setdefault(artist_id, []).append(result)
            yield (
                scale(
                match, self.max_artist_match, 10000, offset=10000, invert=True),
                result)

    @Throttle(WAIT_BETWEEN_REQUESTS)
    def last_fm_request(self, url):
        try:
            stream = urllib.urlopen(url)
            xmldoc = minidom.parse(stream).documentElement
            return xmldoc
        except:
            return None
    
    @Cache(1000)
    def get_artist(self, artist_name):
        """get artist information from the database"""
        self.connection.commit()
        cursor = self.connection.cursor()
        artist_name = artist_name.encode("UTF-8")
        cursor.execute("SELECT * FROM artists WHERE name = ?", (artist_name,))
        row = cursor.fetchone()
        if row:
            return row
        cursor.execute("INSERT INTO artists (name) VALUES (?)", (artist_name,))
        self.connection.commit()
        cursor.execute("SELECT * FROM artists WHERE name = ?", (artist_name,))
        return cursor.fetchone()

    @Cache(2000)
    def get_track(self, artist_name, title):
        """get track information from the database"""
        self.connection.commit()
        cursor = self.connection.cursor()
        title = title.encode("UTF-8")
        artist_id = self.get_artist(artist_name)[0]
        cursor.execute(
            "SELECT * FROM tracks WHERE artist = ? AND title = ?",
            (artist_id, title))
        row = cursor.fetchone()
        if row:
            return row
        cursor.execute(
            "INSERT INTO tracks (artist, title) VALUES (?, ?)",
            (artist_id, title))
        self.connection.commit()
        cursor.execute(
            "SELECT * FROM tracks WHERE artist = ? AND title = ?",
            (artist_id, title))
        return cursor.fetchone()

    @Cache(2000)
    def get_artist_and_title(self, track_id):
        self.connection.commit()
        cursor = self.connection.cursor()
        cursor.execute(
            "SELECT artists.name, tracks.title FROM tracks INNER JOIN artists"
            " ON tracks.artist = artists.id WHERE tracks.id = ?",
            (track_id, ))
        row = cursor.fetchone()
        return row[0], row[1]

    def get_artist_tracks(self, artist_id):
        self.connection.commit()
        cursor = self.connection.cursor()
        cursor.execute(
            "SELECT tracks.id FROM tracks INNER JOIN artists"
            " ON tracks.artist = artists.id WHERE artists.id = ?",
            (artist_id, ))
        return [row[0] for row in cursor.fetchall()]

    def analyze_track(self, song):
        artist_name = song.get_artist()
        title = song.get_title()
        filename = song.get_filename()
        length = song.get_length()
        track = self.get_track(artist_name, title)
        track_id, artist_id = track[0], track[1]
        db = Db(self.connection)
        if db.get_track(track_id):
            return False
        self.log("no mirage data found, analyzing track")
        exclude_ids = self.get_artist_tracks(artist_id)
        try:
            scms = self.mir.analyze(filename)
        except:
            return False
        db.add_and_compare(track_id, scms,exclude_ids=exclude_ids)
        return True

    def get_ordered_mirage_tracks(self, song):
        """get similar tracks from mirage acoustic analysis"""
        maximum = 10000
        scale_to = 10000
        artist_name = song.get_artist()
        title = song.get_title()
        self.log("Getting similar tracks from mirage for: %s - %s" % (
            artist_name, title))
        if not self.use_db:
            raise StopIteration
        track = self.get_track(artist_name, title)
        track_id, artist_id, updated = track[0], track[1], track[3]
        db = Db(self.connection)
        yielded = False
        for match, mtrack_id in db.get_neighbours(track_id):
            match = scale(match, maximum, scale_to)
            track_artist, track_title = self.get_artist_and_title(mtrack_id)
            yield(scale(match, maximum, scale_to),
                  {'distance': scale(match, maximum, scale_to),
                   'artist': track_artist,
                   'title': track_title})
            yielded = True
        if yielded:
            raise StopIteration
        if not self.analyze_track(song):
            raise StopIteration
        for match, mtrack_id in db.get_neighbours(track_id):
            distance = scale(match, maximum, scale_to)
            track_artist, track_title = self.get_artist_and_title(mtrack_id)
            yield(scale(match, maximum, scale_to),
                  {'distance': scale(distance, maximum, scale_to),
                   'artist': track_artist,
                   'title': track_title})

    def get_ordered_similar_tracks(self, song):
        """get similar tracks from the database sorted by descending
        match score"""
        scale_to = 10000
        artist_name = song.get_artist()
        title = song.get_title()
        track = self.get_track(artist_name, title)
        track_id, updated = track[0], track[3]
        if not self.use_db:
            for result in scale_transformer(
                self.get_similar_tracks_from_lastfm(
                artist_name, title, track_id), self.max_track_match, scale_to):
                yield result 
        self.connection.commit()
        generators = []
        cursor1 = self.connection.cursor()
        cursor1.execute(
            "SELECT track_2_track.match, artists.name, tracks.title  FROM"
            " track_2_track INNER JOIN tracks ON track_2_track.track1"
            " = tracks.id INNER JOIN artists ON artists.id = tracks.artist"
            " WHERE track_2_track.track2 = ? ORDER BY track_2_track.match DESC",
            (track_id,))
        generators.append(
            scale_transformer(cursor1, self.max_track_match, scale_to))
        if updated:
            updated = datetime(*strptime(updated, "%Y-%m-%d %H:%M:%S")[0:6])
            if updated + timedelta(self.cache_time) > self.now:
                self.log("Getting similar tracks from db for: %s - %s" % (
                    artist_name, title))
                cursor2 = self.connection.cursor()
                cursor2.execute(
                    "SELECT track_2_track.match, artists.name, tracks.title"
                    " FROM track_2_track INNER JOIN tracks ON"
                    " track_2_track.track2 = tracks.id INNER JOIN artists ON"
                    " artists.id = tracks.artist WHERE track_2_track.track1"
                    " = ? ORDER BY track_2_track.match DESC",
                    (track_id,))
                generators.append(
                    scale_transformer(cursor2, self.max_track_match, scale_to))
        else:
            generators.append(
                self.get_similar_tracks_from_lastfm(
                artist_name, title, track_id))
        for result in merge(*generators):
            if len(result) > 2:
                result = transform_trackresult(result)
            yield result

    def get_ordered_similar_artists(self, song):
        """get similar artists from the database sorted by descending
        match score"""
        scale_to = 10000
        artist_name = song.get_artist()
        artist = self.get_artist(artist_name)
        artist_id, updated = artist[0], artist[2]
        if not self.use_db:
            for result in self.get_similar_artists_from_lastfm(
                artist_name, artist_id):
                yield result
        self.connection.commit()
        generators = []
        cursor1 = self.connection.cursor()
        cursor1.execute(
            "SELECT match, name  FROM artist_2_artist INNER JOIN artists"
            " ON artist_2_artist.artist1 = artists.id WHERE"
            " artist_2_artist.artist2 = ? ORDER BY match DESC",
            (artist_id,))
        generators.append(
            scale_transformer(
            cursor1, self.max_artist_match, scale_to, offset=10000))
        if updated:
            updated = datetime(*strptime(updated, "%Y-%m-%d %H:%M:%S")[0:6])
            if updated + timedelta(self.cache_time) > self.now:
                self.log(
                    "Getting similar artists from db for: %s " %
                    artist_name)
                cursor2 = self.connection.cursor()
                cursor2.execute(
                    "SELECT match, name  FROM artist_2_artist INNER JOIN"
                    " artists ON artist_2_artist.artist2 = artists.id WHERE"
                    " artist_2_artist.artist1 = ? ORDER BY match DESC",
                    (artist_id,))
                generators.append(
                    scale_transformer(
                    cursor2, self.max_artist_match, scale_to, offset=10000))
        else:
            generators.append(
                self.get_similar_artists_from_lastfm(artist_name, artist_id))
        for result in merge(*generators):
            if type(result[1]) != dict:
                result = transform_artistresult(result)
            yield result

    def get_ordered_tag_search(self, song):
        tags = song.get_tags()
        if not tags:
            raise StopIteration
        yield 20000, {'tags': tags}
        
    def _get_artist_match(self, artist1, artist2):
        """get artist match score from database"""
        self.connection.commit()
        cursor = self.connection.cursor()
        cursor.execute(
            "SELECT match FROM artist_2_artist WHERE artist1 = ?"
            " AND artist2 = ?",
            (artist1, artist2))
        row = cursor.fetchone()
        if not row:
            return 0
        return row[0]

    def _get_track_match(self, track1, track2):
        """get track match score from database"""
        self.connection.commit()
        cursor = self.connection.cursor()
        cursor.execute(
            "SELECT match FROM track_2_track WHERE track1 = ? AND track2 = ?",
            (track1, track2))
        row = cursor.fetchone()
        if not row:
            return 0
        return row[0]

    def _update_artist_match(self, artist1, artist2, match):
        """write match score to the database"""
        cursor = self.connection.cursor()
        cursor.execute(
            "UPDATE artist_2_artist SET match = ? WHERE artist1 = ? AND"
            " artist2 = ?",
            (match, artist1, artist2))

    def _update_track_match(self, track1, track2, match):
        """write match score to the database"""
        cursor = self.connection.cursor()
        cursor.execute(
            "UPDATE track_2_track SET match = ? WHERE track1 = ? AND"
            " track2 = ?",
            (match, track1, track2))

    def _insert_artist_match(self, artist1, artist2, match):
        """write match score to the database"""
        cursor = self.connection.cursor()
        cursor.execute(
            "INSERT INTO artist_2_artist (artist1, artist2, match) VALUES"
            " (?, ?, ?)",
            (artist1, artist2, match))

    def _insert_track_match(self, track1, track2, match):
        """write match score to the database"""
        cursor = self.connection.cursor()
        cursor.execute(
            "INSERT INTO track_2_track (track1, track2, match) VALUES"
            " (?, ?, ?)",
            (track1, track2, match))

    def _update_artist(self, artist_id):
        """write artist information to the database"""
        cursor = self.connection.cursor()
        cursor.execute(
            "UPDATE artists SET updated = DATETIME('now') WHERE id = ?",
            (artist_id,))

    def _update_track(self, track_id):
        """write track information to the database"""
        cursor = self.connection.cursor()
        cursor.execute(
            "UPDATE tracks SET updated = DATETIME('now') WHERE id = ?",
            (track_id,))
        
    def _update_similar_artists(self, artist_id, similar_artists):
        """write similar artist information to the database"""
        for artist in similar_artists:
            id2 = self.get_artist(artist['artist'])[0]
            if self._get_artist_match(artist_id, id2):
                self._update_artist_match(artist_id, id2, artist['match'])
                continue
            self._insert_artist_match(artist_id, id2, artist['match'])
        self._update_artist(artist_id)
        
    def _update_similar_tracks(self, track_id, similar_tracks):
        """write similar track information to the database"""
        for track in similar_tracks:
            id2 = self.get_track(track['artist'], track['title'])[0]
            if self._get_track_match(track_id, id2):
                self._update_track_match(track_id, id2, track['match'])
                continue
            self._insert_track_match(track_id, id2, track['match'])
        self._update_track(track_id)

    def log(self, msg):
        """print debug messages"""
        if not self.verbose:
            return
        print "[autoqueue]", msg.encode('utf-8')

    def create_db(self):
        """ Set up a database for the artist and track similarity scores
        """
        self.log("create_db")
        connection = self.get_database_connection()
        cursor = connection.cursor()
        cursor.execute(
            'CREATE TABLE IF NOT EXISTS artists (id INTEGER PRIMARY KEY, name'
            ' VARCHAR(100), updated DATE)')
        cursor.execute(
            'CREATE TABLE IF NOT EXISTS artist_2_artist (artist1 INTEGER,'
            ' artist2 INTEGER, match INTEGER)')
        cursor.execute(
            'CREATE TABLE IF NOT EXISTS tracks (id INTEGER PRIMARY KEY, artist'
            ' INTEGER, title VARCHAR(100), updated DATE)')
        cursor.execute(
            'CREATE TABLE IF NOT EXISTS track_2_track (track1 INTEGER, track2'
            ' INTEGER, match INTEGER)')
        connection.commit()
        if self.in_memory:
            self.connection = connection
            
    def prune_db(self, prunes):
        """clean up the database: remove tracks and artists that are
        never played"""
        if not prunes:
            return
        connection = self.get_database_connection()
        cursor = connection.cursor()
        before = {
            'tracks':
            cursor.execute('SELECT count(*) from tracks;').fetchone()[0],
            'track_2_track':
            cursor.execute('SELECT count(*) from track_2_track;').fetchone()[0],
            'mirage':
            cursor.execute('SELECT count(*) from mirage;').fetchone()[0],
            'distance':
            cursor.execute('SELECT count(*) from distance;').fetchone()[0],}
        self.log('before: %s' % repr(before))
        rows = []
        for prune in prunes:
            cursor.execute(
                'SELECT artists.name, tracks.title, tracks.id FROM tracks'
                ' INNER JOIN artists ON tracks.artist = artists.id WHERE '
                'artists.name = ?;', (prune['artist'],))
            rows.extend( cursor.fetchall())
            cursor.execute(
                'SELECT artists.name, tracks.title, tracks.id FROM tracks '
                'INNER JOIN artists ON tracks.artist = artists.id WHERE '
                'tracks.title = ?;', (prune['title'],))
            rows.extend(cursor.fetchall())
        cursor = None
        for i, item in enumerate(rows):
            search = self.player_construct_search(
                {'artist': item[0], 'title': item[1]})
            songs = self.player_search(search)
            if not songs:
                self.log("removing: %07d %s - %s" % (i, item[0], item[1]))
                self.delete_track_from_db(item[2])
            yield
        cursor = connection.cursor()
        after = {
            'tracks':
            cursor.execute('SELECT count(*) from tracks;').fetchone()[0],
            'track_2_track':
            cursor.execute('SELECT count(*) from track_2_track;').fetchone()[0],
            'mirage':
            cursor.execute('SELECT count(*) from mirage;').fetchone()[0],
            'distance':
            cursor.execute('SELECT count(*) from distance;').fetchone()[0],}
        self.log('after: %s' % repr(after))

    def delete_track_from_db(self, track_id):
        connection = self.get_database_connection()
        cursor = connection.cursor()
        cursor.execute(
            'DELETE FROM distance WHERE track_1 = ? OR track_2 = ?;',
            (track_id, track_id))
        cursor.execute('DELETE FROM mirage WHERE trackid = ?;', (track_id,))
        cursor.execute(
            'DELETE FROM track_2_track WHERE track1 = ? OR track2 = ?;',
            (track_id, track_id))
        cursor.execute('DELETE FROM tracks WHERE id = ?;', (track_id,))
        connection.commit()
        
