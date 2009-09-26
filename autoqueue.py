"""AutoQueue: an automatic queueing plugin library.
version 0.3

Copyright 2007-2009 Eric Casteleijn <thisfred@gmail.com>,
                    Daniel Nouri <daniel.nouri@gmail.com>
                    Jasper OpdeCoul <jasper.opdecoul@gmail.com>

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
from time import strptime, sleep, time
import urllib
import random, os, heapq
from xml.dom import minidom
from cPickle import Pickler, Unpickler

try:
    import sqlite3
    SQL = True
except ImportError:
    SQL = False

try:
    from mirage import (
        Mir, Db, MatrixDimensionMismatchException, MfccFailedException)
    MIRAGE = True
except ImportError:
    MIRAGE = False

# If you change even a single character of code, I would ask that you
# get and use your own (free) last.fm api key from here:
# http://www.last.fm/api/account
API_KEY = "09d0975a99a4cab235b731d31abf0057"

TRACK_URL = "http://ws.audioscrobbler.com/2.0/?method=track.getsimilar" \
            "&artist=%s&track=%s&api_key=" + API_KEY
ARTIST_URL = "http://ws.audioscrobbler.com/2.0/?method=artist.getsimilar" \
             "&artist=%s&api_key=" + API_KEY

# be nice to last.fm
WAIT_BETWEEN_REQUESTS = timedelta(0, 1)

# XXX make configurable
NEIGHBOURS = 20

def exhaust(iterator):
    for i in iterator:
        yield

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
        def wrapper(*args, **kwargs):
            while self.last_called + self.wait > datetime.now():
                sleep(0.1)
            result = func(*args, **kwargs)
            self.last_called = datetime.now()
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

    def get_playcount(self):
        """Return the number of times the song was played."""
        return NotImplemented

    def get_added(self):
        """Return the date the song was added to the library."""
        return NotImplemented

    def get_last_started(self):
        """Return the date the song was last played."""
        return NotImplemented

    def get_rating(self):
        """Return the rating of the song."""
        return NotImplemented


class AutoQueueBase(object):
    """Generic base class for autoqueue plugins."""
    use_db = False
    store_blocked_artists = False
    in_memory = False
    def __init__(self):
        self.connection = None
        self.max_track_match = 10000
        self.max_artist_match = 10000
        self.artist_block_time = 1
        self.track_block_time = 30
        self.desired_queue_length = 0
        self.cache_time = 90
        self.cached_misses = []
        self.by_mirage = False
        self.by_tracks = True
        self.by_artists = True
        self.by_tags = False
        self.running = False
        self.verbose = False
        self.weed = False
        self.lastfm = True
        self.now = datetime.now()
        self.song = None
        self._blocked_artists = deque([])
        self._blocked_artists_times = deque([])
        self.restrictions = None
        self._artists_to_update = {}
        self._tracks_to_update = {}
        self.prune_artists = []
        self.prune_titles = []
        self._rows = []
        self._nrows = []
        self.player_set_variables_from_config()
        if self.store_blocked_artists:
            self.get_blocked_artists_pickle()
        if self.use_db:
            self.check_db()
        if MIRAGE:
            self.mir = Mir()

    def close_database_connection(self, connection):
        if self.in_memory:
            return
        connection.close()

    def player_get_userdir(self):
        """get the application user directory to store files"""
        return NotImplemented

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

    def player_execute_async(self, method, *args, **kwargs):
        if 'funcid' in kwargs:
            del kwargs['funcid']
        for dummy in method(*args, **kwargs):
            pass

    def check_db(self):
        if self.in_memory:
            self.create_db()
            return
        try:
            os.stat(self.get_db_path())
        except OSError:
            self.create_db()
        self.create_indices()

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
        if self.in_memory:
            return ":memory:"
        return os.path.join(self.player_get_userdir(), "similarity.db")

    def get_database_connection(self):
        """get database reference"""
        if self.in_memory:
            if self.connection:
                return self.connection
            self.connection = sqlite3.connect(":memory:")
            self.connection.text_factory = str
            return self.connection
        connection = sqlite3.connect(
            self.get_db_path(), timeout=5.0, isolation_level="immediate")
        connection.text_factory = str
        return connection

    def disallowed(self, song):
        if song.get_artist() in self.get_blocked_artists():
            return True
        try:
            lastplayed = song.get_last_started()
        except NotImplemented:
            return False
        now = datetime.now()
        delta = now - datetime.fromtimestamp(lastplayed)
        days_ago = delta.days
        try:
            rating = song.get_rating()
        except NotImplemented:
            return self.track_block_time > days_ago
        bdays = max(1, self.track_block_time)
        suggested = 2 * bdays * (1 - rating)
        self.log("rating: %s last played %s days ago, suggested play: after %s "
                 "days" % (repr(rating), repr(days_ago), suggested))
        return suggested > days_ago

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
        # add the artist to the blocked list, so their songs won't be
        # played for a determined time
        self.block_artist(artist_name)
        self.prune_artists.append(artist_name)
        if self.running:
            return
        self.song = song
        if MIRAGE:
            fid = "analyze_track" + str(int(time()))
            self.player_execute_async(
                self.analyze_track, song, funcid=fid, add_neighbours=False)
        if self.desired_queue_length == 0 or self.queue_needs_songs():
            self.player_execute_async(self.fill_queue)
        if self.weed:
            self.player_execute_async(self.prune_db)
            self.player_execute_async(self.prune_search)
            self.player_execute_async(self.prune_delete)

    def queue_needs_songs(self):
        """determine whether the queue needs more songs added"""
        time = self.player_get_queue_length()
        return time < self.desired_queue_length

    def song_generator(self, last_song):
        """yield songs that match the last song in the queue"""
        generators = []
        if MIRAGE and self.by_mirage:
            for dummy in self.analyze_track(last_song):
                yield
            generators.append(self.get_ordered_mirage_tracks(last_song))
        if self.by_tracks:
            generators.append(self.get_ordered_similar_tracks(last_song))
        if self.by_artists:
            generators.append(self.get_ordered_similar_artists(last_song))
        if self.by_tags:
            generators.append(self.get_ordered_tag_search(last_song))
        for result in merge(*generators):
            yield result

    def construct_search(
        self, artist=None, title=None, tags=None, restrictions=None):
        if title:
            return self.player_construct_track_search(
                artist, title, restrictions)
        if artist:
            return self.player_construct_artist_search(
                artist, restrictions)
        if tags:
            return self.player_construct_tag_search(
                tags, restrictions)

    def search_and_filter(self, artist, title, tags):
        if (artist, title, tags) in self.cached_misses:
            return None
        search = self.construct_search(artist, title, tags, self.restrictions)
        songs = self.player_search(search)
        if songs:
            while songs:
                song = random.choice(songs)
                songs.remove(song)
                if not self.disallowed(song):
                    return song
        elif self.weed:
            self.prune_titles.append(title)
        self.cached_misses.append((artist, title, tags))
        return None

    def queue_song(self):
        """Queue a single track"""
        self.unblock_artists()
        found = None
        last_songs = self.get_last_songs()
        deletes = []
        while last_songs and not found:
            last_song = last_songs.pop()
            generator = self.song_generator(last_song)
            while not found:
                yield
                blocked = self.get_blocked_artists()
                try:
                    item = generator.next()
                    while not item:
                        item = generator.next()
                        yield
                    score, result = item
                    self.log("looking for: %s, %s" % (score, repr(result)))
                    artist = result.get('artist')
                    if artist:
                        if artist in blocked:
                            continue
                    found = self.search_and_filter(
                        result.get("artist"), result.get("title"),
                        result.get("tags"))
                except StopIteration:
                    break
        if found:
            self.player_enqueue(found)
            if MIRAGE and self.by_mirage:
                for dummy in self.analyze_track(self.get_last_songs()[-1]):
                    yield
        for dummy in exhaust(generator):
            yield
        if not found:
            yield "exhausted"

    def fill_queue(self):
        """search for appropriate songs and put them in the queue"""
        yield
        self.running = True
        if self.desired_queue_length == 0:
            for dummy in self.queue_song():
                yield
        stop = False
        exhausted = False
        while not exhausted and self.queue_needs_songs():
            for exhausted in self.queue_song():
                yield
        if self.use_db:
            for artist_id in self._artists_to_update:
                self._update_similar_artists(
                    artist_id, self._artists_to_update[artist_id])
                yield
            for track_id in self._tracks_to_update:
                self._update_similar_tracks(
                    track_id, self._tracks_to_update[track_id])
                yield
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

    def get_last_songs(self):
        """return the last song in the queue or the currently playing
        song"""
        queue = self.player_get_songs_in_queue() or []
        return [self.song] + queue

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
                'lastfm_match': match,
                'artist': similar_artist,
                'title': similar_title,}
            if self.use_db:
                self._tracks_to_update.setdefault(track_id, []).append(result)
            yield (
                scale(match, self.max_track_match, 10000, offset=1000,
                      invert=True), result)

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
                'lastfm_match': match,
                'artist': name,}
            if self.use_db:
                self._artists_to_update.setdefault(artist_id, []).append(result)
            yield (
                scale(
                match, self.max_artist_match, 10000, offset=10000, invert=True),
                result)

    @Throttle(WAIT_BETWEEN_REQUESTS)
    def last_fm_request(self, url):
        if not self.lastfm:
            return None
        try:
            stream = urllib.urlopen(url)
            xmldoc = minidom.parse(stream).documentElement
            return xmldoc
        except:
            self.lastfm = False
            return None

    def get_artist(self, artist_name, with_connection=None):
        """get artist information from the database"""
        if with_connection:
            connection = with_connection
        else:
            connection = self.get_database_connection()
        artist_name = artist_name.encode("UTF-8")
        rows = connection.execute(
            "SELECT * FROM artists WHERE name = ?", (artist_name,))
        for row in rows:
            return row
        connection.execute(
            "INSERT INTO artists (name) VALUES (?)", (artist_name,))
        connection.commit()
        rows = connection.execute(
            "SELECT * FROM artists WHERE name = ?", (artist_name,))
        for row in rows:
            if not with_connection:
                self.close_database_connection(connection)
            return row
        if not with_connection:
            self.close_database_connection(connection)

    def get_track(self, artist_name, title, with_connection=None):
        """get track information from the database"""
        if with_connection:
            connection = with_connection
        else:
            connection = self.get_database_connection()
        title = title.encode("UTF-8")
        artist_id = self.get_artist(artist_name, with_connection=connection)[0]
        rows = connection.execute(
            "SELECT * FROM tracks WHERE artist = ? AND title = ?",
            (artist_id, title))
        for row in rows:
            return row
        connection.execute(
            "INSERT INTO tracks (artist, title) VALUES (?, ?)",
            (artist_id, title))
        connection.commit()
        rows = connection.execute(
            "SELECT * FROM tracks WHERE artist = ? AND title = ?",
            (artist_id, title))
        for row in rows:
            if not with_connection:
                self.close_database_connection(connection)
            return row
        if not with_connection:
            self.close_database_connection(connection)

    def get_artist_and_title(self, track_id):
        connection = self.get_database_connection()
        rows = connection.execute(
            "SELECT artists.name, tracks.title FROM tracks INNER JOIN artists"
            " ON tracks.artist = artists.id WHERE tracks.id = ?",
            (track_id, ))
        result = None
        for row in rows:
            result = (row[0], row[1])
            break
        self.close_database_connection(connection)
        return result

    def get_artist_tracks(self, artist_id):
        connection = self.get_database_connection()
        result = []
        rows = connection.execute(
            "SELECT tracks.id FROM tracks INNER JOIN artists"
            " ON tracks.artist = artists.id WHERE artists.id = ?",
            (artist_id, ))
        result = [row[0] for row in rows]
        self.close_database_connection(connection)
        return result

    def analyze_track(self, song, add_neighbours=True):
        artist_name = song.get_artist()
        title = song.get_title()
        filename = song.get_filename()
        yield
        if not filename:
            return
        length = song.get_length()
        track = self.get_track(artist_name, title)
        track_id, artist_id = track[0], track[1]
        db = Db(self.get_db_path())
        yield
        if db.has_scores(track_id, no=NEIGHBOURS):
            return
        yield
        scms = db.get_track(track_id)
        if not scms:
            self.log("no mirage data found for %s, analyzing track" % filename)
            try:
                scms = self.mir.analyze(filename)
            except (MatrixDimensionMismatchException, MfccFailedException):
                return
            db.add_track(track_id, scms)
        yield
        if add_neighbours:
            exclude_ids = self.get_artist_tracks(artist_id)
            for dummy in db.add_neighbours(track_id, scms,
                                           exclude_ids=exclude_ids,
                                           add=NEIGHBOURS):
                yield
        return

    def get_ordered_mirage_tracks(self, song):
        """get similar tracks from mirage acoustic analysis"""
        maximum = 100
        scale_to = 10000
        artist_name = song.get_artist()
        title = song.get_title()
        self.log("Getting similar tracks from mirage for: %s - %s" % (
            artist_name, title))
        if not self.use_db:
            raise StopIteration
        track = self.get_track(artist_name, title)
        track_id, artist_id, updated = track[0], track[1], track[3]
        db = Db(self.get_db_path())
        for i, match, mtrack_id in db.get_neighbours(track_id):
            result = self.get_artist_and_title(mtrack_id)
            if not result:
                continue
            track_artist, track_title = result
            yield(scale(i, maximum, scale_to),
                  {'mirage_distance': match,
                   'artist': track_artist,
                   'title': track_title})

    def get_ordered_similar_tracks(self, song):
        """get similar tracks from the database sorted by descending
        match score"""
        scale_to = 10000
        artist_name = song.get_artist()
        title = song.get_title()
        connection = self.get_database_connection()
        track = self.get_track(artist_name, title, with_connection=connection)
        track_id, updated = track[0], track[3]
        if not self.use_db:
            for result in scale_transformer(
                self.get_similar_tracks_from_lastfm(
                artist_name, title, track_id), self.max_track_match, scale_to):
                yield result
        generators = []
        cursor1 = [row for row in connection.execute(
            "SELECT track_2_track.match, artists.name, tracks.title  FROM"
            " track_2_track INNER JOIN tracks ON track_2_track.track1"
            " = tracks.id INNER JOIN artists ON artists.id = tracks.artist"
            " WHERE track_2_track.track2 = ? ORDER BY track_2_track.match DESC",
            (track_id,))]
        self.close_database_connection(connection)
        generators.append(
            scale_transformer(cursor1, self.max_track_match, scale_to,
                              offset=1000))
        if updated:
            updated = datetime(*strptime(updated, "%Y-%m-%d %H:%M:%S")[0:6])
            if updated + timedelta(self.cache_time) > self.now:
                self.log("Getting similar tracks from db for: %s - %s" % (
                    artist_name, title))
                connection2 = self.get_database_connection()
                cursor2 = [row for row in connection2.execute(
                    "SELECT track_2_track.match, artists.name, tracks.title"
                    " FROM track_2_track INNER JOIN tracks ON"
                    " track_2_track.track2 = tracks.id INNER JOIN artists ON"
                    " artists.id = tracks.artist WHERE track_2_track.track1"
                    " = ? ORDER BY track_2_track.match DESC",
                    (track_id,))]
                self.close_database_connection(connection2)
                generators.append(
                    scale_transformer(cursor2, self.max_track_match, scale_to,
                                      offset=1000))
            else:
                generators.append(
                    self.get_similar_tracks_from_lastfm(
                    artist_name, title, track_id))
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
        connection = self.get_database_connection()
        artist = self.get_artist(artist_name, with_connection=connection)
        artist_id, updated = artist[0], artist[2]
        if not self.use_db:
            for result in self.get_similar_artists_from_lastfm(
                artist_name, artist_id):
                yield result
        generators = []
        cursor1 = [row for row in connection.execute(
            "SELECT match, name  FROM artist_2_artist INNER JOIN artists"
            " ON artist_2_artist.artist1 = artists.id WHERE"
            " artist_2_artist.artist2 = ? ORDER BY match DESC",
            (artist_id,))]
        self.close_database_connection(connection)
        generators.append(
            scale_transformer(
            cursor1, self.max_artist_match, scale_to, offset=10000))
        if updated:
            updated = datetime(*strptime(updated, "%Y-%m-%d %H:%M:%S")[0:6])
            if updated + timedelta(self.cache_time) > self.now:
                self.log(
                    "Getting similar artists from db for: %s " %
                    artist_name)
                connection2 = self.get_database_connection()
                cursor2 = [row for row in connection2.execute(
                    "SELECT match, name  FROM artist_2_artist INNER JOIN"
                    " artists ON artist_2_artist.artist2 = artists.id WHERE"
                    " artist_2_artist.artist1 = ? ORDER BY match DESC;",
                    (artist_id,))]
                self.close_database_connection(connection2)
                generators.append(
                    scale_transformer(
                    cursor2, self.max_artist_match, scale_to, offset=10000))
            else:
                generators.append(
                    self.get_similar_artists_from_lastfm(
                    artist_name, artist_id))
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

    def _get_artist_match(self, artist1, artist2, with_connection=None):
        """get artist match score from database"""
        if with_connection:
            connection = with_connection
        else:
            connection = self.get_database_connection()
        rows = connection.execute(
            "SELECT match FROM artist_2_artist WHERE artist1 = ?"
            " AND artist2 = ?",
            (artist1, artist2))
        result = 0
        for row in rows:
            result = row[0]
            break
        if not with_connection:
            self.close_database_connection(connection)
        return result

    def _get_track_match(self, track1, track2, with_connection=None):
        """get track match score from database"""
        if with_connection:
            connection = with_connection
        else:
            connection = self.get_database_connection()
        rows = connection.execute(
            "SELECT match FROM track_2_track WHERE track1 = ? AND track2 = ?",
            (track1, track2))
        result = 0
        for row in rows:
            result = row[0]
            break
        if not with_connection:
            self.close_database_connection(connection)
        return result

    def _update_artist_match(
        self, artist1, artist2, match, with_connection=None):
        """write match score to the database"""
        if with_connection:
            connection = with_connection
        else:
            connection = self.get_database_connection()
        connection.execute(
            "UPDATE artist_2_artist SET match = ? WHERE artist1 = ? AND"
            " artist2 = ?",
            (match, artist1, artist2))
        if not with_connection:
            connection.commit()
            self.close_database_connection(connection)

    def _update_track_match(self, track1, track2, match, with_connection=None):
        """write match score to the database"""
        if with_connection:
            connection = with_connection
        else:
            connection = self.get_database_connection()
        connection.execute(
            "UPDATE track_2_track SET match = ? WHERE track1 = ? AND"
            " track2 = ?",
            (match, track1, track2))
        if not with_connection:
            connection.commit()
            self.close_database_connection(connection)

    def _insert_artist_match(
        self, artist1, artist2, match, with_connection=None):
        """write match score to the database"""
        if with_connection:
            connection = with_connection
        else:
            connection = self.get_database_connection()
        connection.execute(
            "INSERT INTO artist_2_artist (artist1, artist2, match) VALUES"
            " (?, ?, ?)",
            (artist1, artist2, match))
        if not with_connection:
            connection.commit()
            self.close_database_connection(connection)

    def _insert_track_match(self, track1, track2, match, with_connection=None):
        """write match score to the database"""
        if with_connection:
            connection = with_connection
        else:
            connection = self.get_database_connection()
        connection.execute(
            "INSERT INTO track_2_track (track1, track2, match) VALUES"
            " (?, ?, ?)",
            (track1, track2, match))
        if not with_connection:
            connection.commit()
            self.close_database_connection(connection)

    def _update_artist(self, artist_id, with_connection=None):
        """write artist information to the database"""
        if with_connection:
            connection = with_connection
        else:
            connection = self.get_database_connection()
        connection.execute(
            "UPDATE artists SET updated = DATETIME('now') WHERE id = ?",
            (artist_id,))
        if not with_connection:
            connection.commit()
            self.close_database_connection(connection)

    def _update_track(self, track_id, with_connection=None):
        """write track information to the database"""
        if with_connection:
            connection = with_connection
        else:
            connection = self.get_database_connection()
        connection.execute(
            "UPDATE tracks SET updated = DATETIME('now') WHERE id = ?",
            (track_id,))
        if not with_connection:
            connection.commit()
            self.close_database_connection(connection)

    def _update_similar_artists(self, artist_id, similar_artists):
        """write similar artist information to the database"""
        connection = self.get_database_connection()
        for artist in similar_artists:
            id2 = self.get_artist(
                artist['artist'], with_connection=connection)[0]
            if self._get_artist_match(
                artist_id, id2, with_connection=connection):
                self._update_artist_match(
                    artist_id, id2, artist['lastfm_match'],
                    with_connection=connection)
                continue
            self._insert_artist_match(
                artist_id, id2, artist['lastfm_match'],
                with_connection=connection)
        self._update_artist(artist_id, with_connection=connection)
        connection.commit()
        self.close_database_connection(connection)

    def _update_similar_tracks(self, track_id, similar_tracks):
        """write similar track information to the database"""
        connection = self.get_database_connection()
        for track in similar_tracks:
            id2 = self.get_track(
                track['artist'], track['title'], with_connection=connection)[0]
            if self._get_track_match(track_id, id2, with_connection=connection):
                self._update_track_match(
                    track_id, id2, track['lastfm_match'],
                    with_connection=connection)
                continue
            self._insert_track_match(
                track_id, id2, track['lastfm_match'],
                with_connection=connection)
        self._update_track(track_id, with_connection=connection)
        connection.commit()
        self.close_database_connection(connection)

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
        connection.execute(
            'CREATE TABLE IF NOT EXISTS artists (id INTEGER PRIMARY KEY, name'
            ' VARCHAR(100), updated DATE)')
        connection.execute(
            'CREATE TABLE IF NOT EXISTS artist_2_artist (artist1 INTEGER,'
            ' artist2 INTEGER, match INTEGER)')
        connection.execute(
            'CREATE TABLE IF NOT EXISTS tracks (id INTEGER PRIMARY KEY, artist'
            ' INTEGER, title VARCHAR(100), updated DATE)')
        connection.execute(
            'CREATE TABLE IF NOT EXISTS track_2_track (track1 INTEGER, track2'
            ' INTEGER, match INTEGER)')
        connection.execute(
            "CREATE INDEX IF NOT EXISTS a2aa1x ON artist_2_artist (artist1)")
        connection.execute(
            "CREATE INDEX IF NOT EXISTS a2aa2x ON artist_2_artist (artist2)")
        connection.execute(
            "CREATE INDEX IF NOT EXISTS t2tt1x ON track_2_track (track1)")
        connection.execute(
            "CREATE INDEX IF NOT EXISTS t2tt1x ON track_2_track (track2)")
        connection.commit()
        self.close_database_connection(connection)

    def create_indices(self):
        self.log("create_indexes")
        connection = self.get_database_connection()
        connection.execute(
            "CREATE INDEX IF NOT EXISTS a2aa1x ON artist_2_artist (artist1)")
        connection.execute(
            "CREATE INDEX IF NOT EXISTS a2aa2x ON artist_2_artist (artist2)")
        connection.execute(
            "CREATE INDEX IF NOT EXISTS t2tt1x ON track_2_track (track1)")
        connection.execute(
            "CREATE INDEX IF NOT EXISTS t2tt1x ON track_2_track (track2)")
        connection.commit()
        self.close_database_connection(connection)

    def prune_db(self):
        """clean up the database: remove tracks and artists that are
        never played"""
        if not self.prune_titles and not self.prune_artists:
            return
        yield
        if self.prune_artists:
            seen_artists = []
            while self.prune_artists:
                artist = self.prune_artists.pop(0)
                if artist not in seen_artists:
                    seen_artists.append(artist)
                    connection = self.get_database_connection()
                    self._rows.extend(
                        [(row[0], row[1], row[2]) for row in connection.execute(
                        'SELECT artists.name, tracks.title, tracks.id FROM '
                        'tracks INNER JOIN artists ON tracks.artist = '
                        'artists.id WHERE artists.name = ?;', (artist,))])
                    self.close_database_connection(connection)
                    yield
        if self.prune_titles:
            seen_titles = []
            while self.prune_titles:
                vtitle = self.prune_titles.pop(0)
                if not vtitle:
                    continue
                title = vtitle.split("(")[0]
                if title not in seen_titles:
                    seen_titles.append(title)
                    connection = self.get_database_connection()
                    self._rows.extend(
                        [(row[0], row[1], row[2]) for row in connection.execute(
                        'SELECT artists.name, tracks.title, tracks.id FROM '
                        'tracks INNER JOIN artists ON tracks.artist = '
                        'artists.id WHERE tracks.title = ? OR tracks.title = ?;'
                        , (vtitle, title))])
                    self.close_database_connection(connection)
                    yield

    def prune_search(self):
        while self._rows:
            item = self._rows.pop(0)
            search = self.construct_search(artist=item[0], title=item[1])
            songs = self.player_search(search)
            if not songs:
                self._nrows.append(item)
            yield

    def prune_delete(self):
        while self._nrows:
            item = self._nrows.pop(0)
            connection = self.get_database_connection()
            self.log("deleting %s - %s" % (item[0], item[1]))
            track_id = item[2]
            connection.execute(
                'DELETE FROM distance WHERE track_1 = ? OR track_2 = '
                '?;',
                (track_id, track_id))
            connection.execute(
                'DELETE FROM mirage WHERE trackid = ?;', (track_id,))
            connection.execute(
                'DELETE FROM track_2_track WHERE track1 = ? OR track2 ='
                ' ?;',
                (track_id, track_id))
            connection.execute(
                'DELETE FROM tracks WHERE id = ?;', (track_id,))
            connection.commit()
            self.close_database_connection(connection)
            yield
        connection = self.get_database_connection()
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
        self.close_database_connection(connection)
        self.log('db: %s' % repr(after))
