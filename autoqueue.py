"""AutoQueue: an automatic queueing plugin library.
version 0.3

Copyright 2007-2008 Eric Casteleijn <thisfred@gmail.com>

This program is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License version 2 as
published by the Free Software Foundation"""

from collections import deque
from datetime import datetime, timedelta
from time import strptime, sleep
import urllib, threading
import random, os
from xml.dom import minidom
from cPickle import Pickler, Unpickler

try:
    import sqlite3
    SQL = True
except ImportError:
    SQL = False
    
# If you change even a single character of code, I would ask that you
# get and use your own (free) api key from last.fm here:
# http://www.last.fm/api/account
API_KEY = "09d0975a99a4cab235b731d31abf0057"

TRACK_URL = "http://ws.audioscrobbler.com/2.0/?method=track.getsimilar" \
            "&artist=%s&track=%s&api_key=" + API_KEY
ARTIST_URL = "http://ws.audioscrobbler.com/2.0/?method=artist.getsimilar" \
             "&artist=%s&api_key=" + API_KEY

# be nice to last.fm
WAIT_BETWEEN_REQUESTS = timedelta(0, 0, 0, 5) 


class Cache(object):
    """
    >>> dec_cache = Cache(10)
    >>> @dec_cache
    ... def identity(f):
    ...     pass
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
    >>> identity(41)
    41
    >>> identity(32)
    32
    >>> identity(16)
    16
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
        raise NotImplemented

    def get_title(self):
        """return lowercase UNICODE title of song"""
        raise NotImplemented

    def get_tags(self):
        """return a list of tags for the songs"""
        raise NotImplemented


class AutoQueueBase(object):
    """Generic base class for autoqueue plugins."""
    def __init__(self):
        self.artist_block_time = 1
        self.track_block_time = 30
        self.desired_queue_length = 4440
        self.cache_time = 90
        self.cache = SQL and True
        self.by_tracks = True
        self.by_artists = True
        self.by_tags = True
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
        self._last_call = datetime.now()
        self.player_set_variables_from_config()
        self.dump = os.path.join(
            self.player_get_userdir(), "autoqueue_block_cache")
        self.db = os.path.join(self.player_get_userdir(), "similarity.db")

        try:
            pickle = open(self.dump, 'r')
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
        if self.cache:
            try:
                os.stat(self.db)
                self.prune_db()
            except OSError:
                self.create_db()

    def player_get_userdir(self):
        """get the application user directory to store files"""
        raise NotImplemented
    
    def player_construct_track_search(self, artist, title, restrictions):
        """construct a search that looks for songs with this artist
        and title"""
        raise NotImplemented
    
    def player_construct_tag_search(self, tags, exclude_artists, restrictions):
        """construct a search that looks for songs with these
        tags"""
        raise NotImplemented
    
    def player_construct_artist_search(self, artist, restrictions):
        """construct a search that looks for songs with this artist"""
        raise NotImplemented
        
    def player_construct_restrictions(
        self, track_block_time, relaxors, restrictors):
        """contstruct a search to further modify the searches"""
        raise NotImplemented

    def player_set_variables_from_config(self):
        """Initialize user settings from the configuration storage"""
        raise NotImplemented

    def player_get_queue_length(self):
        """Get the current length of the queue"""
        raise NotImplemented

    def player_enqueue(self, song):
        """Put the song at the end of the queue"""
        raise NotImplemented

    def player_search(self, search):
        """perform a player search"""
        raise NotImplemented

    def player_get_songs_in_queue(self):
        """return (wrapped) song objects for the songs in the wueue"""
        raise NotImplemented
    
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
        # if a thread is already running, do nothing
        if self.running:
            return
        #start a new thread to look up songs if necessary
        if self.queue_needs_songs():
            background = threading.Thread(None, self.add_to_queue) 
            background.setDaemon(True)
            background.start()
    
    def queue_needs_songs(self):
        """determine whether the queue needs more songs added"""
        time = self.player_get_queue_length()
        return time < self.desired_queue_length

    def song_generator(self):
        """yield songs that match the last song in the queue"""
        restrictions = self.player_construct_restrictions(
            self.track_block_time, self.relaxors, self.restrictors)
        if self.by_tracks:
            for match, artist, title in self.get_sorted_similar_tracks():
                if self.is_blocked(artist):
                    continue
                self.log("looking for: %s, %s, %s" % (match, artist, title))
                search = self.player_construct_track_search(
                    artist, title, restrictions)
                songs = self.player_search(search)
                if songs:
                    yield random.choice(songs)
        if self.by_artists:
            for match, artist in self.get_sorted_similar_artists():
                if self.is_blocked(artist):
                    continue
                self.log("looking for: %s, %s" % (match, artist))
                search = self.player_construct_artist_search(
                    artist, restrictions)
                songs = self.player_search(search)
                if songs:
                    yield random.choice(songs)
        if self.by_tags:
            tags = self.get_last_song().get_tags()
            if tags:
                self.log("Searching for tags: %s" % tags)
                search = self.player_construct_tag_search(tags, restrictions)
                for song in self.player_search(search):
                    yield song
        return

    def add_to_queue(self):
        """search for appropriate songs and put them in the queue"""
        self.running = True
        self.connection = sqlite3.connect(self.db)
        while self.queue_needs_songs():
            self.unblock_artists()
            generator = self.song_generator()
            song = None
            try:
                song = generator.next()
                self.log("found song")
            except StopIteration:
                if self._songs:
                    song = self._songs.popleft()
                    while self.is_blocked(
                        song.get_artist()) and self._songs:
                        song = self._songs.pop()
                    if self.is_blocked(song.get_artist()):
                        song = None
            try:
                song2 = generator.next()
            except StopIteration:
                song2 = None
            if (song2 and not (song is song2) and not
                self.is_blocked(song2.get_artist())
                and not song2 in self._songs):
                self._songs = deque([
                    bsong for bsong in list(self._songs) if not
                    self.is_blocked(bsong.get_artist())])
                self._songs.appendleft(song2)
                if len(self._songs) > 10:
                    self._songs.pop()
                if self._songs:
                    self.log("%s backup songs: \n%s" % (
                        len(self._songs),
                        "\n".join(["%s - %s" % (
                        bsong.get_artist(),
                        bsong.get_title()) for bsong in list(self._songs)])))
            if song:
                self.player_enqueue(song)
            else:
                break
            
        for artist_id in self._artists_to_update:
            self._update_similar_artists(
                artist_id, self._artists_to_update[artist_id])
        self._artists_to_update = {}
        for track_id in self._tracks_to_update:
            self._update_similar_tracks(
                track_id, self._tracks_to_update[track_id])
        self.connection.commit()
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
        try:
            os.remove(self.dump)
        except OSError:
            pass
        if len(self._blocked_artists) == 0:
            return
        pickler = Pickler(open(self.dump, 'w'), -1)
        to_dump = (self._blocked_artists,
                   self._blocked_artists_times)
        pickler.dump(to_dump)

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
        tags1 = list(set([tag.split(":")[-1] for tag in tags1]))
        tags2 = list(set([tag.split(":")[-1] for tag in tags2]))
        return len([tag for tag in tags2 if tag in tags1])

    def get_similar_tracks(self):
        """get similar tracks to the last one in the queue"""
        last_song = self.get_last_song()
        artist_name = last_song.get_artist()
        title = last_song.get_title()
        self.log("Getting similar tracks from last.fm for: %s - %s" % (
            artist_name, title))
        enc_artist_name = artist_name.encode("utf-8")
        enc_title = title.encode("utf-8")
        if ("&" in artist_name or "/" in artist_name or "?" in artist_name
            or "#" in artist_name or "&" in title or "/" in title
            or "?" in title or "#" in title):
            enc_artist_name = urllib.quote_plus(enc_artist_name)
            enc_title = urllib.quote_plus(enc_title)
        url = TRACK_URL % (
            urllib.quote(enc_artist_name),
            urllib.quote(enc_title))
        try:
            while self._last_call + WAIT_BETWEEN_REQUESTS > datetime.now():
                sleep(5)
            stream = urllib.urlopen(url)
            xmldoc = minidom.parse(stream).documentElement
            self._last_call = datetime.now()
        except:
            return []
        tracks = []
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
            tracks.append((match, similar_artist, similar_title))
        return tracks
            
    def get_similar_artists(self):
        """get similar artists to that of the last song in the queue"""
        artist_name = self.get_last_song().get_artist()
        self.log("Getting similar artists from last.fm for: %s " % artist_name)
        if ("&" in artist_name or "/" in artist_name or "?" in artist_name
            or "#" in artist_name):
            artist_name = urllib.quote_plus(artist_name)
        url = ARTIST_URL % (
            urllib.quote(artist_name.encode("utf-8")))
        try:
            while self._last_call + WAIT_BETWEEN_REQUESTS > datetime.now():
                sleep(5)
            stream = urllib.urlopen(url)
            xmldoc = minidom.parse(stream).documentElement
            self._last_call = datetime.now()
        except:
            return []
        artists = []
        nodes = xmldoc.getElementsByTagName("artist")
        for node in nodes:
            name = node.getElementsByTagName(
                "name")[0].firstChild.nodeValue.lower()
            match = 0
            matchnode = node.getElementsByTagName("match")
            if matchnode:
                match = int(float(matchnode[0].firstChild.nodeValue) * 100)
            artists.append((match, name))
        return artists

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

    def get_sorted_similar_artists(self):
        """get similar artists from the database sorted by descending
        match score"""
        if not self.cache:
            return sorted(list(set(self.get_similar_artists())), reverse=True)
        artist = self.get_artist(self.get_last_song().get_artist())
        artist_id, updated = artist[0], artist[2]
        cursor = self.connection.cursor()
        cursor.execute(
            "SELECT match, name  FROM artist_2_artist INNER JOIN artists"
            " ON artist_2_artist.artist1 = artists.id WHERE"
            " artist_2_artist.artist2 = ?",
            (artist_id,))
        reverse_lookup = cursor.fetchall()
        if updated:
            updated = datetime(*strptime(updated, "%Y-%m-%d %H:%M:%S")[0:6])
            if updated + timedelta(self.cache_time) > self.now:
                artist_name = self.get_last_song().get_artist()
                self.log(
                    "Getting similar artists from db for: %s " %
                    artist_name)
                cursor.execute(
                    "SELECT match, name  FROM artist_2_artist INNER JOIN"
                    " artists ON artist_2_artist.artist2 = artists.id WHERE"
                    " artist_2_artist.artist1 = ?",
                    (artist_id,))
                return sorted(list(set(cursor.fetchall() + reverse_lookup)),
                            reverse=True)
        similar_artists = self.get_similar_artists()
        self._artists_to_update[artist_id] = similar_artists
        return sorted(list(set(similar_artists + reverse_lookup)), reverse=True)

    def get_sorted_similar_tracks(self):
        """get similar tracks from the database sorted by descending
        match score"""
        if not self.cache:
            return sorted(list(set(self.get_similar_tracks())), reverse=True)
        last_song = self.get_last_song()
        artist = last_song.get_artist()
        title = last_song.get_title()
        track = self.get_track(artist, title)
        track_id, updated = track[0], track[3]
        cursor = self.connection.cursor()
        cursor.execute(
            "SELECT track_2_track.match, artists.name, tracks.title  FROM"
            " track_2_track INNER JOIN tracks ON track_2_track.track1"
            " = tracks.id INNER JOIN artists ON artists.id = tracks.artist"
            " WHERE track_2_track.track2 = ?",
            (track_id,))
        reverse_lookup = cursor.fetchall()
        if updated:
            updated = datetime(*strptime(updated, "%Y-%m-%d %H:%M:%S")[0:6])
            if updated + timedelta(self.cache_time) > self.now:
                self.log("Getting similar tracks from db for: %s - %s" % (
                    artist, title))
                cursor.execute(
                    "SELECT track_2_track.match, artists.name, tracks.title"
                    " FROM track_2_track INNER JOIN tracks ON"
                    " track_2_track.track2 = tracks.id INNER JOIN artists ON"
                    " artists.id = tracks.artist WHERE track_2_track.track1"
                    " = ?",
                    (track_id,))
                return sorted(list(set(cursor.fetchall() + reverse_lookup)),
                              reverse=True)
        similar_tracks = self.get_similar_tracks()
        self._tracks_to_update[track_id] = similar_tracks
        return sorted(list(set(similar_tracks + reverse_lookup)), reverse=True)

    @Cache(1000)
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

    @Cache(1000)
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
        for match, artist_name in similar_artists:
            id2 = self.get_artist(artist_name)[0]
            if self._get_artist_match(artist_id, id2):
                self._update_artist_match(artist_id, id2, match)
                continue
            self._insert_artist_match(artist_id, id2, match)
        self._update_artist(artist_id)
        
    def _update_similar_tracks(self, track_id, similar_tracks):
        """write similar track information to the database"""
        for match, artist_name, title in similar_tracks:
            id2 = self.get_track(artist_name, title)[0]
            if self._get_track_match(track_id, id2):
                self._update_track_match(track_id, id2, match)
                continue
            self._insert_track_match(track_id, id2, match)
        self._update_track(track_id)

    def log(self, msg):
        """print debug messages"""
        if not self.verbose:
            return
        print "[autoqueue]", msg

    def create_db(self):
        """ Set up a database for the artist and track similarity scores
        """
        self.log("create_db")
        connection = sqlite3.connect(self.db)
        cursor = connection.cursor()
        cursor.execute(
            'CREATE TABLE artists (id INTEGER PRIMARY KEY, name'
            ' VARCHAR(100), updated DATE)')
        cursor.execute(
            'CREATE TABLE artist_2_artist (artist1 INTEGER, artist2 INTEGER,'
            ' match INTEGER)')
        cursor.execute(
            'CREATE TABLE tracks (id INTEGER PRIMARY KEY, artist INTEGER,'
            ' title VARCHAR(100), updated DATE)')
        cursor.execute(
            'CREATE TABLE track_2_track (track1 INTEGER, track2 INTEGER,'
            ' match INTEGER)')
        connection.commit()

    def prune_db(self):
        """clean up the database: remove tracks and artists that are
        never played"""
        connection = sqlite3.connect(self.db)
        cursor = connection.cursor()
        cursor.execute(
            'DELETE FROM tracks WHERE updated IS NULL AND tracks.id NOT IN'
            ' (SELECT track1 FROM track_2_track);')
        connection.commit()
        cursor.execute(
            'DELETE FROM track_2_track WHERE track2 NOT IN (SELECT '
            'id FROM tracks);')
        connection.commit()
        cursor.execute(
            'DELETE FROM artists WHERE updated IS NULL AND artists.id NOT '
            'IN (SELECT tracks.artist FROM tracks) AND artists.id NOT IN '
            '(SELECT artist1 FROM artist_2_artist);'
            )
        cursor.execute(
            'DELETE FROM artist_2_artist WHERE artist2 NOT IN (SELECT '
            'id FROM artists);'
            )
        connection.commit()
        
    def dump_stuff(self):
        """dump persistent data to pickles
        """
        try:
            os.remove(self.dump)
        except OSError:
            pass
        if len(self._blocked_artists) == 0:
            return 0
        pickle = open(self.dump, 'w')
        try:
            pickler = Pickler(pickle, -1)
            to_dump = (self._blocked_artists, self._blocked_artists_times)
            pickler.dump(to_dump)
        finally:
            pickle.close()
        return 0
