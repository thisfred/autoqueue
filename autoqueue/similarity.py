"""Autoqueue similarity service."""

import dbus
import dbus.service
import gobject
import os
import urllib

from time import strptime, sleep
from datetime import datetime, timedelta

from xml.dom import minidom

from dbus.mainloop.glib import DBusGMainLoop
from dbus.service import method

import sqlite3

from mirage import (
    Mir, Db, MatrixDimensionMismatchException, MfccFailedException)

try:
    import xdg.BaseDirectory
    XDG = True
except ImportError:
    XDG = False

DBusGMainLoop(set_as_default=True)

DBUS_BUSNAME = 'org.autoqueue.Similarity'
DBUS_IFACE = 'org.autoqueue.SimilarityInterface'
DBUS_PATH = '/org/autoqueue/Similarity'

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

# TODO make configurable
NEIGHBOURS = 20


class Throttle(object):
    """Decorator that throttles calls to a function or method."""

    def __init__(self, wait):
        self.wait = wait
        self.last_called = datetime.now()

    def __call__(self, func):
        """Return the decorator."""

        def wrapper(*args, **kwargs):
            """The implementation of the decorator."""
            while self.last_called + self.wait > datetime.now():
                sleep(0.1)
            result = func(*args, **kwargs)
            self.last_called = datetime.now()
            return result

        return wrapper


class SimilarityService(dbus.service.Object):
    """Service that can be queried for similar songs."""

    _data_dir = None

    def __init__(self, bus_name, object_path):
        self.create_db()
        self.lastfm = True
        self.cache_time = 90
        self.mir = Mir()
        super(SimilarityService, self).__init__(
            bus_name=bus_name, object_path=object_path)

    def close_database_connection(self, connection):
        """Close the database connection."""
        connection.close()

    def player_get_data_dir(self):
        """Get the directory to store user data.

        Defaults to $XDG_DATA_HOME/autoqueue on Gnome.

        """
        if self._data_dir:
            return self._data_dir
        if not XDG:
            return NotImplemented
        data_dir = os.path.join(xdg.BaseDirectory.xdg_data_home, 'autoqueue')
        if not os.path.exists(data_dir):
            os.makedirs(data_dir)
        self._data_dir = data_dir
        return data_dir

    def get_db_path(self):
        """Get the directory where the database lives."""
        return os.path.join(self.player_get_data_dir(), "similarity.db")

    def get_database_connection(self):
        """Get a database connection."""
        connection = sqlite3.connect(
            self.get_db_path(), timeout=5.0, isolation_level="immediate")
        connection.text_factory = str
        return connection

    def get_artist(self, artist_name, with_connection=None):
        """Get artist information from the database."""
        if with_connection:
            connection = with_connection
        else:
            connection = self.get_database_connection()
        artist_name = artist_name.encode("UTF-8")
        rows = connection.execute(
            "SELECT * FROM artists WHERE name = ?", (artist_name,))
        for row in rows:
            if not with_connection:
                self.close_database_connection(connection)
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
        """Get track information from the database."""
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
            if not with_connection:
                self.close_database_connection(connection)
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

    def get_ids_for_filenames(self, filenames):
        """Get database ids for a list of filenames."""
        connection = self.get_database_connection()
        rows = connection.execute(
            'SELECT trackid FROM mirage WHERE filename IN (%s)' %
            (','.join(['"%s"' % filename for filename in filenames]), ))
        result = [row[0] for row in rows]
        self.close_database_connection(connection)
        return result

    def get_artist_tracks(self, artist_id):
        """Get all track ids for a given artist id."""
        connection = self.get_database_connection()
        result = []
        rows = connection.execute(
            "SELECT tracks.id FROM tracks INNER JOIN artists"
            " ON tracks.artist = artists.id WHERE artists.id = ?",
            (artist_id, ))
        result = [row[0] for row in rows]
        self.close_database_connection(connection)
        return result

    def get_similar_tracks_from_db(self, track_id):
        """Get similar tracks from the database.

        Sorted by descending match score.

        """
        connection = self.get_database_connection()
        results = [row for row in connection.execute(
            "SELECT track_2_track.match, artists.name, tracks.title"
            " FROM track_2_track INNER JOIN tracks ON"
            " track_2_track.track2 = tracks.id INNER JOIN artists ON"
            " artists.id = tracks.artist WHERE track_2_track.track1"
            " = ? ORDER BY track_2_track.match DESC",
            (track_id,))]
        self.close_database_connection(connection)
        return results

    def get_similar_artists_from_db(self, artist_id):
        """Get similar artists from the database.

        Sorted by descending match score.

        """
        connection = self.get_database_connection()
        results = [row for row in connection.execute(
            "SELECT match, name FROM artist_2_artist INNER JOIN"
            " artists ON artist_2_artist.artist2 = artists.id WHERE"
            " artist_2_artist.artist1 = ? ORDER BY match DESC;",
            (artist_id,))]
        self.close_database_connection(connection)
        return results

    def _get_artist_match(self, artist1, artist2, with_connection=None):
        """Get artist match score from database."""
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
        """Get track match score from database."""
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
        """Write match score to the database."""
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
        """Write match score to the database."""
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

    def _insert_artist_match(self, artist1, artist2, match,
                             with_connection=None):
        """Write match score to the database."""
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
        """Write match score to the database."""
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
        """Write artist information to the database."""
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
        """Write track information to the database."""
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

    def _update_similar_artists(self, artists_to_update):
        """Write similar artist information to the database."""
        connection = self.get_database_connection()
        for artist_id, similar in artists_to_update.items():
            for artist in similar:
                id2 = self.get_artist(
                    artist['artist'], with_connection=connection)[0]
                if self._get_artist_match(
                    artist_id, id2, with_connection=connection):
                    self._update_artist_match(
                        artist_id, id2, artist['score'],
                        with_connection=connection)
                    continue
                self._insert_artist_match(
                    artist_id, id2, artist['score'],
                    with_connection=connection)
            self._update_artist(artist_id, with_connection=connection)
        connection.commit()
        self.close_database_connection(connection)

    def _update_similar_tracks(self, tracks_to_update):
        """Write similar track information to the database."""
        connection = self.get_database_connection()
        for track_id, similar in tracks_to_update.items():
            for track in similar:
                id2 = self.get_track(
                    track['artist'], track['title'],
                    with_connection=connection)[0]
                if self._get_track_match(
                    track_id, id2, with_connection=connection):
                    self._update_track_match(
                        track_id, id2, track['score'],
                        with_connection=connection)
                    continue
                self._insert_track_match(
                    track_id, id2, track['score'],
                    with_connection=connection)
            self._update_track(track_id, with_connection=connection)
        connection.commit()
        self.close_database_connection(connection)

    def create_db(self):
        """Set up a database for the artist and track similarity scores."""
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
            'CREATE TABLE IF NOT EXISTS mirage (trackid INTEGER PRIMARY KEY, '
            'filename VARCHAR(300), scms BLOB)')
        connection.execute(
            "CREATE TABLE IF NOT EXISTS distance (track_1 INTEGER, track_2 "
            "INTEGER, distance INTEGER)")
        connection.execute(
            "CREATE INDEX IF NOT EXISTS a2aa1x ON artist_2_artist (artist1)")
        connection.execute(
            "CREATE INDEX IF NOT EXISTS a2aa2x ON artist_2_artist (artist2)")
        connection.execute(
            "CREATE INDEX IF NOT EXISTS t2tt1x ON track_2_track (track1)")
        connection.execute(
            "CREATE INDEX IF NOT EXISTS t2tt2x ON track_2_track (track2)")
        connection.execute(
            "CREATE INDEX IF NOT EXISTS mfnx ON mirage (filename)")
        connection.execute(
            "CREATE INDEX IF NOT EXISTS dtrack1x ON distance (track_1)")
        connection.execute(
            "CREATE INDEX IF NOT EXISTS dtrack2x ON distance (track_2)")
        connection.commit()
        self.close_database_connection(connection)

    def delete_orphan_artists(self, artists):
        """Delete artists that have no tracks."""
        connection = self.get_database_connection()
        connection.execute(
            'DELETE FROM artists WHERE artists.id in (%s) AND artists.id NOT '
            'IN (SELECT tracks.artist from tracks);' %
            ",".join([str(artist) for artist in artists]))
        connection.execute(
            'DELETE FROM artist_2_artist WHERE artist1 NOT I (SELECT '
            'artists.id FROM artists) OR artist2 NOT IN (SELECT artists.id '
            'FROM artists);')
        connection.commit()
        connection.close()

    def log(self, message):
        """Log message."""
        print message

    def get_similar_tracks_from_lastfm(self, artist_name, title, track_id):
        """Get similar tracks to the last one in the queue."""
        self.log("Getting similar tracks from last.fm for: %s - %s" % (
            artist_name, title))
        enc_artist_name = artist_name.encode("utf-8")
        enc_title = title.encode("utf-8")
        url = TRACK_URL % (
            urllib.quote_plus(enc_artist_name),
            urllib.quote_plus(enc_title))
        xmldoc = self.last_fm_request(url)
        if xmldoc is None:
            return []
        nodes = xmldoc.getElementsByTagName("track")
        results = []
        tracks_to_update = {}
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
                'score': match,
                'artist': similar_artist,
                'title': similar_title}
            tracks_to_update.setdefault(track_id, []).append(result)
            results.append((match, similar_artist, similar_title))
        self._update_similar_tracks(tracks_to_update)
        return results

    def get_similar_artists_from_lastfm(self, artist_name, artist_id):
        """Get similar artists from lastfm."""
        self.log("Getting similar artists from last.fm for: %s " % artist_name)
        enc_artist_name = artist_name.encode("utf-8")
        url = ARTIST_URL % (
            urllib.quote_plus(enc_artist_name))
        xmldoc = self.last_fm_request(url)
        if xmldoc is None:
            return []
        nodes = xmldoc.getElementsByTagName("artist")
        results = []
        artists_to_update = {}
        for node in nodes:
            name = node.getElementsByTagName(
                "name")[0].firstChild.nodeValue.lower()
            match = 0
            matchnode = node.getElementsByTagName("match")
            if matchnode:
                match = int(float(matchnode[0].firstChild.nodeValue) * 100)
            result = {
                'score': match,
                'artist': name}
            artists_to_update.setdefault(artist_id, []).append(result)
            results.append((match, name))
        self._update_similar_artists(artists_to_update)
        return results

    @Throttle(WAIT_BETWEEN_REQUESTS)
    def last_fm_request(self, url):
        """Make an http request to last.fm."""
        if not self.lastfm:
            return None
        try:
            stream = urllib.urlopen(url)
        except Exception, e:            # pylint: disable=W0703
            self.log("Error: %s" % e)
            return None
        try:
            xmldoc = minidom.parse(stream).documentElement
            return xmldoc
        except Exception, e:            # pylint: disable=W0703
            self.log("Error: %s" % e)
            self.lastfm = False
            return None

    @method(dbus_interface=DBUS_IFACE, in_signature='as')
    def remove_tracks(self, filenames):
        """Remove tracks from database."""
        db = Db(self.get_db_path())
        db.remove_tracks(filenames)

    @method(dbus_interface=DBUS_IFACE, in_signature='sbas')
    def analyze_track(self, filename, add_neighbours, exclude_filenames):
        """Perform mirage analysis of a track."""
        if not filename:
            return
        db = Db(self.get_db_path())
        trackid_scms = db.get_track(filename)
        if not trackid_scms:
            self.log("no mirage data found for %s, analyzing track" % filename)
            try:
                scms = self.mir.analyze(filename)
            except (MatrixDimensionMismatchException, MfccFailedException,
                    IndexError), e:
                self.log(repr(e))
                return
            db.add_track(filename, scms)
            trackid = db.get_track_id(filename)
        else:
            trackid, scms = trackid_scms
        if not add_neighbours:
            return
        if db.has_scores(trackid, no=NEIGHBOURS):
            return
        db.add_neighbours(
            trackid, scms, exclude_filenames=exclude_filenames,
            neighbours=NEIGHBOURS)

    @method(dbus_interface=DBUS_IFACE, in_signature='s', out_signature='a(is)')
    def get_ordered_mirage_tracks(self, filename):
        """Get similar tracks by mirage acoustic analysis."""
        db = Db(self.get_db_path())
        trackid = db.get_track_id(filename)
        return db.get_neighbours(trackid)

    @method(dbus_interface=DBUS_IFACE, in_signature='ss',
            out_signature='a(iss)')
    def get_ordered_similar_tracks(self, artist_name, title):
        """Get similar tracks from last.fm/the database.

        Sorted by descending match score.

        """
        now = datetime.now()
        track = self.get_track(artist_name, title)
        track_id, updated = track[0], track[3]
        if updated:
            updated = datetime(*strptime(updated, "%Y-%m-%d %H:%M:%S")[0:6])
            if updated + timedelta(self.cache_time) > now:
                self.log("Getting similar tracks from db for: %s - %s" % (
                    artist_name, title))
                return self.get_similar_tracks_from_db(track_id)
        return self.get_similar_tracks_from_lastfm(
            artist_name, title, track_id)

    @method(dbus_interface=DBUS_IFACE, in_signature='as',
            out_signature='a(is)')
    def get_ordered_similar_artists(self, artists):
        """Get similar artists from the database.

        Sorted by descending match score.

        """
        results = []
        now = datetime.now()
        for artist_name in artists:
            result = None
            artist = self.get_artist(artist_name)
            artist_id, updated = artist[0], artist[2]
            if updated:
                updated = datetime(
                    *strptime(updated, "%Y-%m-%d %H:%M:%S")[0:6])
                if updated + timedelta(self.cache_time) > now:
                    self.log(
                        "Getting similar artists from db for: %s " %
                        artist_name)
                    result = self.get_similar_artists_from_db(artist_id)
            if not result:
                result = self.get_similar_artists_from_lastfm(
                    artist_name, artist_id)
            results.extend(result)
        results.sort(reverse=True)
        return results

    def run(self):
        loop = gobject.MainLoop()
        loop.run()


def register_service(bus):
    """Try to register DBus service for making sure we run only one instance.

    Return True if succesfully registered, False if already running.
    """
    name = bus.request_name(DBUS_BUSNAME, dbus.bus.NAME_FLAG_DO_NOT_QUEUE)
    return name != dbus.bus.REQUEST_NAME_REPLY_EXISTS


def publish_service(bus):
    """Publish the service on DBus."""
    bus_name = dbus.service.BusName(DBUS_BUSNAME, bus=bus)
    service = SimilarityService(bus_name=bus_name, object_path=DBUS_PATH)
    service.run()


def main():
    """Start the service if it is not already running."""
    DBusGMainLoop(set_as_default=True)

    bus = dbus.SessionBus()
    if register_service(bus):
        publish_service(bus)
