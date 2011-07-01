"""Autoqueue similarity service."""

# TODO: real logging

import dbus
import dbus.service
import gobject
import os

from threading import Thread
from Queue import Queue, PriorityQueue
from time import strptime
from datetime import datetime, timedelta
from collections import namedtuple
from dbus.mainloop.glib import DBusGMainLoop
from dbus.service import method

import sqlite3

from autoqueue.pylast import LastFMNetwork, WSError, NetworkError

from mirage import (
    Mir, MatrixDimensionMismatchException, MfccFailedException,
    instance_from_picklestring, instance_to_picklestring, ScmsConfiguration,
    distance)

try:
    import xdg.BaseDirectory
    XDG = True
except ImportError:
    XDG = False

DBusGMainLoop(set_as_default=True)

DBUS_BUSNAME = 'org.autoqueue'
IFACE = 'org.autoqueue.SimilarityInterface'
DBUS_PATH = '/org/autoqueue/Similarity'

# If you change even a single character of code, I would ask that you
# get and use your own (free) last.fm api key from here:
# http://www.last.fm/api/account
API_KEY = "09d0975a99a4cab235b731d31abf0057"

# TODO make configurable
NEIGHBOURS = 20


def cluster_match(cluster1, cluster2):
    """@cluster1 and @cluster2 have matching ends."""
    return (
        cluster1[0] == cluster2[0] or cluster1[-1] == cluster2[0] or
        cluster1[0] == cluster2[-1] or cluster1[-1] == cluster2[-1])


class SQLCommand(object):
    """A SQL command object."""

    def __init__(self, sql_statements):
        self.sql = sql_statements
        self.result_queue = Queue()


class DatabaseWrapper(Thread):
    """Process to handle all database access."""

    def set_path(self, path):
        """Set the database path."""
        self.path = path                # pylint: disable=W0201

    def set_queue(self, queue):
        """Set the queue to use."""
        self.queue = queue              # pylint: disable=W0201

    def run(self):
        connection = sqlite3.connect(
            self.path, timeout=5.0, isolation_level="immediate")
        cursor = connection.cursor()
        while True:
            _, cmd = self.queue.get()
            sql = cmd.sql
            if sql == ('STOP',):
                cmd.result_queue.put(None)
                connection.close()
                break
            commit_needed = False
            result = []
            try:
                cursor.execute(*sql)
            except:
                print repr(sql)         # pylint: disable=W0702
            if not sql[0].upper().startswith('SELECT'):
                commit_needed = True
            for row in cursor.fetchall():
                result.append(row)
            if commit_needed:
                connection.commit()
            cmd.result_queue.put(result)


class Pair():
    """A pair of songs"""

    def __init__(self, song1, song2, song_distance):
        self.song1 = song1
        self.song2 = song2
        self.distance = song_distance

    def other(self, song):
        """Return the song paired with @song."""
        if self.song1 == song:
            return self.song2
        return self.song1

    def songs(self):
        """Return both songs."""
        return [self.song1, self.song2]

    def __eq__(self, other):
        return self.song1 == other.song1 and self.song2 == other.song2

    def __cmp__(self, other):
        if self.distance < other.distance:
            return -1
        if self.distance > other.distance:
            return 1
        return 0

    def __repr__(self):
        return '<Pair {song1}, {song2}: {distance}>'.format(
            song1=self.song1, song2=self.song2, distance=self.distance)


class Clusterer(object):
    """Build a list of songs in optimized order."""

    def __init__(self, songs, comparison_function):
        self.clusters = []
        self.ends = []
        self.similarities = []
        self.build_similarity_matrix(songs, comparison_function)

    def build_similarity_matrix(self, songs, comparison_function):
        """Build the similarity matrix."""
        for song1 in songs:
            for song2 in songs[songs.index(song1) + 1:]:
                self.similarities.append(
                    Pair(song1, song2, comparison_function(song1, song2)))
        self.similarities.sort(reverse=True)

    def join(self, cluster1, cluster2):
        """Join two clusters together."""
        if cluster1[0] == cluster2[0]:
            cluster2.reverse()
            self.clean(cluster1[0])
            return cluster2 + cluster1[1:]
        elif cluster1[-1] == cluster2[0]:
            self.clean(cluster1[-1])
            return cluster1 + cluster2[1:]
        elif cluster1[0] == cluster2[-1]:
            self.clean(cluster1[0])
            return cluster2 + cluster1[1:]
        cluster2.reverse()
        self.clean(cluster1[-1])
        return cluster1[:-1] + cluster2

    def pop_cluster_ending_in(self, song):
        """Pop a cluster with @song at either end."""
        for cluster in self.clusters[:]:
            if cluster[0] == song:
                self.clusters.remove(cluster)
                self.ends.remove(cluster[0])
                self.ends.remove(cluster[-1])
                return cluster
            if cluster[-1] == song:
                self.clusters.remove(cluster)
                self.ends.remove(cluster[0])
                self.ends.remove(cluster[-1])
                return cluster

    def cluster(self):
        """Build clusters out of similarity matrix."""
        sim = self.similarities.pop()
        self.clusters = [sim.songs()]
        self.ends = sim.songs()
        while self.similarities:
            sim = self.similarities.pop()
            songs = sim.songs()
            if sim.song1 in self.ends or sim.song2 in self.ends:
                cluster1 = self.pop_cluster_ending_in(sim.song1)
                cluster2 = self.pop_cluster_ending_in(sim.song2)
                if cluster1 and cluster2:
                    new_cluster = self.join(cluster1, songs)
                    new_cluster = self.join(new_cluster, cluster2)
                elif cluster1:
                    if sim.song1 in cluster1 and sim.song2 in cluster1:
                        new_cluster = cluster1
                    else:
                        new_cluster = self.join(cluster1, songs)
                else:
                    if sim.song1 in cluster2 and sim.song2 in cluster2:
                        new_cluster = cluster2
                    else:
                        new_cluster = self.join(cluster2, songs)
                self.clusters.append(new_cluster)
                self.ends.extend([new_cluster[0], new_cluster[-1]])
            else:
                self.clusters.append(songs)
                self.ends.extend(songs)

    def clean(self, found):
        """Remove similarity scores for processed cluster."""
        new = []
        for sim in self.similarities:
            if found in sim.songs():
                continue
            new.append(sim)
        self.similarities = new


class Similarity(object):
    """Here the actual similarity computation and lookup happens."""

    def __init__(self):
        self.db_path = os.path.join(
            self.player_get_data_dir(), "similarity.db")
        self.queue = PriorityQueue()
        self._db_wrapper = DatabaseWrapper()
        self._db_wrapper.daemon = True
        self._db_wrapper.set_path(self.db_path)
        self._db_wrapper.set_queue(self.queue)
        self._db_wrapper.start()
        self.create_db()
        self.mir = Mir()
        self.network = LastFMNetwork(api_key=API_KEY)
        self.cache_time = 90

    def execute_sql(self, sql=None, priority=1, command=None):
        """Put sql command on the queue to be executed."""
        if command is None:
            command = SQLCommand(sql)
        self.queue.put((priority, command))

    def get_sql_command(self, sql, priority=1):
        """Build a SQLCommand, put it on the queue and return it."""
        command = SQLCommand(sql)
        self.execute_sql(command=command, priority=priority)
        return command

    def player_get_data_dir(self):
        """Get the directory to store user data.

        Defaults to $XDG_DATA_HOME/autoqueue on Gnome.

        """
        if not XDG:
            return NotImplemented
        data_dir = os.path.join(xdg.BaseDirectory.xdg_data_home, 'autoqueue')
        if not os.path.exists(data_dir):
            os.makedirs(data_dir)
        return data_dir

    def add_track(self, filename, scms, priority):
        """Add track to database."""
        self.execute_sql(
            ("INSERT INTO mirage (filename, scms) VALUES (?, ?);",
            (filename, sqlite3.Binary(instance_to_picklestring(scms)))),
            priority=priority)

    def remove_track_by_filename(self, filename):
        """Remove tracks from database."""
        sql = ('SELECT trackid FROM mirage WHERE filename = ?', (filename,))
        command = self.get_sql_command(sql, priority=10)
        for row in command.result_queue.get():
            track_id = row[0]
            self.execute_sql((
                'DELETE FROM distance WHERE track_1 = ? OR track_2 = ?;',
            (track_id, track_id)), priority=10)
            self.execute_sql((
                "DELETE FROM mirage WHERE trackid = ?;",
                (track_id,)), priority=10)

    def remove_track(self, artist, title):
        """Delete missing track."""
        sql = (
            'SELECT tracks.id FROM tracks WHERE tracks.title = ? AND WHERE '
            'tracks.artist IN (SELECT artists.id FROM artists WHERE '
            'artists.name = ?);', (artist, title))
        command = self.get_sql_command(sql, priority=10)
        for row in command.result_queue.get():
            track_id = row[0]
            self.execute_sql(
                ('DELETE FROM track_2_track WHERE track1 = ? or track2 = ?;',
                 (track_id, track_id)), priority=10)
            self.execute_sql(
                ('DELETE FROM tracks WHERE id = ?;', (track_id,)), priority=10)
        self.delete_orphan_artist(artist)

    def remove_artist(self, artist):
        """Delete missing artist."""
        sql = ('SELECT id from artists WHERE artists.name = ?;', (artist,))
        command = self.get_sql_command(sql, priority=10)
        for row in command.result_queue.get():
            artist_id = row[0]
            self.execute_sql(
                ('DELETE FROM artists WHERE artists.id = ?;', (artist_id)),
                priority=10)
            self.execute_sql(
                ('DELETE FROM tracks WHERE tracks.artist = ?;', (artist_id)),
                priority=10)

    def get_track_from_filename(self, filename, priority):
        """Get track from database."""
        sql = (
            "SELECT trackid, scms FROM mirage WHERE filename = ?;",
            (filename,))
        command = self.get_sql_command(sql, priority=priority)
        for row in command.result_queue.get():
            return (row[0], instance_from_picklestring(row[1]))
        return None

    def get_track_id(self, filename, priority):
        """Get track id from database."""
        sql = ("SELECT trackid FROM mirage WHERE filename = ?;", (filename,))
        command = self.get_sql_command(sql, priority=priority)
        for row in command.result_queue.get():
            return row[0]
        return None

    def has_scores(self, trackid, no=20, priority=0):
        """Check if the track has sufficient neighbours."""
        sql = (
            'SELECT COUNT(*) FROM distance WHERE track_1 = ?;',
            (trackid,))
        command = self.get_sql_command(sql, priority=priority)
        l1 = command.result_queue.get()[0][0]
        if l1 < no:
            print "Only %d connections found, minimum %d." % (l1, no)
            return False
        sql = (
            "SELECT COUNT(track_1) FROM distance WHERE track_2 = ? AND "
            "distance < (SELECT MAX(distance) FROM distance WHERE track_1 = "
            "?);", (trackid, trackid))
        command = self.get_sql_command(sql, priority=priority)
        l2 = command.result_queue.get()[0][0]
        if l2 > l1:
            print "Found %d incoming connections and only %d outgoing." % (
                l2, l1)
            return False
        return True

    def get_tracks(self, exclude_filenames=None, priority=0):
        """Get tracks from database."""
        if not exclude_filenames:
            exclude_filenames = []
        sql = ("SELECT scms, trackid, filename FROM mirage;",)
        command = self.get_sql_command(sql, priority=priority)
        return [
            (row[0], row[1]) for row in command.result_queue.get()
            if row[2] not in exclude_filenames]

    def add_neighbours(self, trackid, scms, exclude_filenames=None,
                       neighbours=20, priority=0):
        """Add best similarity scores to db."""
        if not exclude_filenames:
            exclude_filenames = []
        to_add = neighbours * 2
        self.execute_sql(
            ("DELETE FROM distance WHERE track_1 = ?;", (trackid,)),
            priority=priority)
        conf = ScmsConfiguration(20)
        best = []
        for buf, otherid in self.get_tracks(
                exclude_filenames=exclude_filenames, priority=priority):
            if trackid == otherid:
                continue
            other = instance_from_picklestring(buf)
            dist = int(distance(scms, other, conf) * 1000)
            if dist < 0:
                continue
            if len(best) > to_add - 1:
                if dist > best[-1][0]:
                    continue
            best.append((dist, trackid, otherid))
            best.sort()
            while len(best) > to_add:
                best.pop()
        added = 0
        if best:
            while best:
                added += 1
                best_tup = best.pop()
                self.execute_sql((
                    "INSERT INTO distance (distance, track_1, track_2) "
                    "VALUES (?, ?, ?);", best_tup), priority=priority)
        print "added %d connections" % added

    def get_neighbours(self, trackid):
        """Get neighbours for track."""
        sql = (
            "SELECT distance, filename FROM distance INNER JOIN MIRAGE ON "
            "distance.track_2 = mirage.trackid WHERE track_1 = ? ORDER BY "
            "distance ASC;",
            (trackid,))
        command = self.get_sql_command(sql, priority=0)
        return command.result_queue.get()

    def get_artist(self, artist_name):
        """Get artist information from the database."""
        artist_name = artist_name.encode("UTF-8")
        sql = ("SELECT * FROM artists WHERE name = ?;", (artist_name,))
        command = self.get_sql_command(sql)
        for row in command.result_queue.get():
            return row
        self.execute_sql((
            "INSERT INTO artists (name) VALUES (?);", (artist_name,)))
        command = self.get_sql_command(sql)
        for row in command.result_queue.get():
            return row

    def get_track_from_artist_and_title(self, artist_name, title):
        """Get track information from the database."""
        title = title.encode("UTF-8")
        artist_id = self.get_artist(artist_name)[0]
        sql = (
            "SELECT * FROM tracks WHERE artist = ? AND title = ?;",
            (artist_id, title))
        command = self.get_sql_command(sql, priority=0)
        for row in command.result_queue.get():
            return row
        self.execute_sql((
            "INSERT INTO tracks (artist, title) VALUES (?, ?);",
            (artist_id, title)), priority=0)
        command = self.get_sql_command(sql, priority=0)
        for row in command.result_queue.get():
            return row

    def get_similar_tracks(self, track_id):
        """Get similar tracks from the database.

        Sorted by descending match score.

        """
        sql = (
            "SELECT track_2_track.match, artists.name, tracks.title"
            " FROM track_2_track INNER JOIN tracks ON"
            " track_2_track.track2 = tracks.id INNER JOIN artists ON"
            " artists.id = tracks.artist WHERE track_2_track.track1"
            " = ? ORDER BY track_2_track.match DESC;",
            (track_id,))
        command = self.get_sql_command(sql, priority=0)
        return command.result_queue.get()

    def get_similar_artists(self, artist_id):
        """Get similar artists from the database.

        Sorted by descending match score.

        """
        sql = (
            "SELECT match, name FROM artist_2_artist INNER JOIN"
            " artists ON artist_2_artist.artist2 = artists.id WHERE"
            " artist_2_artist.artist1 = ? ORDER BY match DESC;",
            (artist_id,))
        command = self.get_sql_command(sql, priority=0)
        return command.result_queue.get()

    def get_artist_match(self, artist1, artist2):
        """Get artist match score from database."""
        sql = (
            "SELECT match FROM artist_2_artist WHERE artist1 = ?"
            " AND artist2 = ?;",
            (artist1, artist2))
        command = self.get_sql_command(sql, priority=2)
        for row in command.result_queue.get():
            return row[0]
        return 0

    def get_track_match(self, track1, track2):
        """Get track match score from database."""
        sql = (
            "SELECT match FROM track_2_track WHERE track1 = ? AND track2 = ?;",
            (track1, track2))
        command = self.get_sql_command(sql, priority=2)
        for row in command.result_queue.get():
            return row[0]
        return 0

    def update_artist_match(self, artist1, artist2, match):
        """Write match score to the database."""
        self.execute_sql((
            "UPDATE artist_2_artist SET match = ? WHERE artist1 = ? AND"
            " artist2 = ?;",
            (match, artist1, artist2)), priority=10)

    def update_track_match(self, track1, track2, match):
        """Write match score to the database."""
        self.execute_sql((
            "UPDATE track_2_track SET match = ? WHERE track1 = ? AND"
            " track2 = ?;",
            (match, track1, track2)), priority=10)

    def insert_artist_match(self, artist1, artist2, match):
        """Write match score to the database."""
        self.execute_sql((
            "INSERT INTO artist_2_artist (artist1, artist2, match) VALUES"
            " (?, ?, ?);",
            (artist1, artist2, match)), priority=10)

    def insert_track_match(self, track1, track2, match):
        """Write match score to the database."""
        self.execute_sql((
            "INSERT INTO track_2_track (track1, track2, match) VALUES"
            " (?, ?, ?);",
            (track1, track2, match)), priority=10)

    def update_artist(self, artist_id):
        """Write artist information to the database."""
        self.execute_sql((
            "UPDATE artists SET updated = DATETIME('now') WHERE id = ?;",
            (artist_id,)), priority=10)

    def update_track(self, track_id):
        """Write track information to the database."""
        self.execute_sql((
            "UPDATE tracks SET updated = DATETIME('now') WHERE id = ?",
            (track_id,)), priority=10)

    def update_similar_artists(self, artists_to_update):
        """Write similar artist information to the database."""
        for artist_id, similar in artists_to_update.items():
            for artist in similar:
                row = self.get_artist(artist['artist'])
                if row:
                    id2 = row[0]
                    if self.get_artist_match(artist_id, id2):
                        self.update_artist_match(
                            artist_id, id2, artist['score'])
                        continue
                    self.insert_artist_match(artist_id, id2, artist['score'])
            self.update_artist(artist_id)

    def update_similar_tracks(self, tracks_to_update):
        """Write similar track information to the database."""
        for track_id, similar in tracks_to_update.items():
            for track in similar:
                row = self.get_track_from_artist_and_title(
                    track['artist'], track['title'])
                if row:
                    id2 = row[0]
                    if self.get_track_match(track_id, id2):
                        self.update_track_match(track_id, id2, track['score'])
                        continue
                    self.insert_track_match(track_id, id2, track['score'])
            self.update_track(track_id)

    def create_db(self):
        """Set up a database for the artist and track similarity scores."""
        self.execute_sql((
            'CREATE TABLE IF NOT EXISTS artists (id INTEGER PRIMARY KEY, name'
            ' VARCHAR(100), updated DATE);',), priority=0)
        self.execute_sql((
            'CREATE TABLE IF NOT EXISTS artist_2_artist (artist1 INTEGER,'
            ' artist2 INTEGER, match INTEGER);',), priority=0)
        self.execute_sql((
            'CREATE TABLE IF NOT EXISTS tracks (id INTEGER PRIMARY KEY, artist'
            ' INTEGER, title VARCHAR(100), updated DATE);',), priority=0)
        self.execute_sql((
            'CREATE TABLE IF NOT EXISTS track_2_track (track1 INTEGER, track2'
            ' INTEGER, match INTEGER);',), priority=0)
        self.execute_sql((
            'CREATE TABLE IF NOT EXISTS mirage (trackid INTEGER PRIMARY KEY, '
            'filename VARCHAR(300), scms BLOB);',), priority=0)
        self.execute_sql((
            "CREATE TABLE IF NOT EXISTS distance (track_1 INTEGER, track_2 "
            "INTEGER, distance INTEGER);",), priority=0)
        self.execute_sql((
            "CREATE INDEX IF NOT EXISTS a2aa1x ON artist_2_artist "
            "(artist1);",), priority=0)
        self.execute_sql((
            "CREATE INDEX IF NOT EXISTS a2aa2x ON artist_2_artist "
            "(artist2);",), priority=0)
        self.execute_sql(
            ("CREATE INDEX IF NOT EXISTS t2tt1x ON track_2_track (track1);",),
            priority=0)
        self.execute_sql(
            ("CREATE INDEX IF NOT EXISTS t2tt2x ON track_2_track (track2);",),
            priority=0)
        self.execute_sql(
            ("CREATE INDEX IF NOT EXISTS mfnx ON mirage (filename);",),
            priority=0)
        self.execute_sql(
            ("CREATE INDEX IF NOT EXISTS dtrack1x ON distance (track_1);",),
            priority=0)
        self.execute_sql(
            ("CREATE INDEX IF NOT EXISTS dtrack2x ON distance (track_2);",),
            priority=0)

    def delete_orphan_artist(self, artist):
        """Delete artists that have no tracks."""
        sql = (
                'SELECT artists.id FROM artists WHERE artists.name = ? AND '
                'artists.id NOT IN (SELECT tracks.artist from tracks);',
                (artist,))
        command = self.get_sql_command(sql, priority=10)
        for row in command.result_queue.get():
            artist_id = row[0]
            self.execute_sql((
                'DELETE FROM artist_2_artist WHERE artist1 = ? OR artist2 = '
                '?;', (artist_id, artist_id)), priority=10)
            self.execute_sql(
                ('DELETE FROM artists WHERE id = ?', (artist_id,)),
                priority=10)

    def log(self, message):
        """Log message."""
        try:
            print message
        except:
            try:
                print message.encode('utf-8')
            except:
                return

    def analyze_track(self, filename, add_neighbours, exclude_filenames,
                      priority):
        """Perform mirage analysis of a track."""
        if not filename:
            return
        trackid_scms = self.get_track_from_filename(
            filename, priority=priority)
        if not trackid_scms:
            self.log("no mirage data found for %s, analyzing track" % filename)
            try:
                scms = self.mir.analyze(filename.encode('utf-8'))
            except (MatrixDimensionMismatchException, MfccFailedException,
                    IndexError), e:
                self.log(repr(e))
                return
            self.add_track(filename, scms, priority=priority)
            trackid = self.get_track_id(filename, priority=priority)
        else:
            trackid, scms = trackid_scms
        if not add_neighbours:
            return
        if self.has_scores(trackid, no=NEIGHBOURS,
                                      priority=priority):
            return
        self.add_neighbours(
            trackid, scms, exclude_filenames=exclude_filenames,
            neighbours=NEIGHBOURS, priority=priority)

    def get_similar_tracks_from_lastfm(self, artist_name, title, track_id):
        """Get similar tracks."""
        try:
            lastfm_track = self.network.get_track(artist_name, title)
        except (WSError, NetworkError), e:
            print e
            return
        tracks_to_update = {}
        results = []
        try:
            for similar in lastfm_track.get_similar():
                match = similar.match
                item = similar.item
                similar_artist = item.artist.get_name()
                similar_title = item.title
                tracks_to_update.setdefault(track_id, []).append({
                    'score': match,
                    'artist': similar_artist,
                    'title': similar_title})
                results.append((match, similar_artist, similar_title))
        except (WSError, NetworkError), e:
            print e
            return
        self.update_similar_tracks(tracks_to_update)
        return results

    def get_similar_artists_from_lastfm(self, artist_name, artist_id):
        """Get similar artists from lastfm."""
        try:
            lastfm_artist = self.network.get_artist(artist_name)
        except WSError:
            return
        artists_to_update = {}
        results = []
        try:
            for similar in lastfm_artist.get_similar():
                match = similar.match
                name = similar.item.get_name()
                artists_to_update.setdefault(artist_id, []).append({
                    'score': match,
                    'artist': name})
                results.append((match, name))
        except WSError:
            return
        self.update_similar_artists(artists_to_update)
        return results

    def get_ordered_mirage_tracks(self, filename):
        """Get similar tracks by mirage acoustic analysis."""
        trackid = self.get_track_id(filename, priority=0)
        return self.get_neighbours(trackid)

    def get_ordered_similar_tracks(self, artist_name, title):
        """Get similar tracks from last.fm/the database.

        Sorted by descending match score.

        """
        now = datetime.now()
        track = self.get_track_from_artist_and_title(
            artist_name, title)
        track_id, updated = track[0], track[3]
        if updated:
            updated = datetime(*strptime(updated, "%Y-%m-%d %H:%M:%S")[0:6])
            if updated + timedelta(self.cache_time) > now:
                self.log("Getting similar tracks from db for: %s - %s" % (
                    artist_name, title))
                return self.get_similar_tracks(track_id)
        return self.get_similar_tracks_from_lastfm(
            artist_name, title, track_id)

    def get_ordered_similar_artists(self, artists):
        """Get similar artists from the database.

        Sorted by descending match score.

        """
        results = []
        now = datetime.now()
        for name in artists:
            artist_name = name
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
                    result = self.get_similar_artists(artist_id)
            if not result:
                result = self.get_similar_artists_from_lastfm(
                    artist_name, artist_id)
            results.extend(result)
        results.sort(reverse=True)
        return results

    def miximize(self, filenames):
        """Return ideally ordered list of filenames."""
        self.log("mirage analysis")
        songs = []
        Song = namedtuple('Song', 'filename scms')
        for filename in filenames:
            trackid_scms = self.get_track_from_filename(filename, priority=10)
            if not trackid_scms:
                try:
                    scms = self.mir.analyze(filename)
                except:
                    return
                self.add_track(filename, scms, priority=10)
            else:
                _, scms = trackid_scms
            songs.append(Song(filename, scms))
        self.log("clustering")
        conf = ScmsConfiguration(20)
        clusterer = Clusterer(
            songs, lambda song1, song2: distance(song1.scms, song2.scms, conf))
        clusterer.cluster()
        qsongs = []
        for cluster in clusterer.clusters:
            qsongs.extend([song.filename for song in cluster])
        return qsongs


class SimilarityService(dbus.service.Object):
    """Service that can be queried for similar songs."""

    def __init__(self, bus_name, object_path):
        import gst
        self.similarity = Similarity()
        super(SimilarityService, self).__init__(
            bus_name=bus_name, object_path=object_path)
        self.loop = gobject.MainLoop()

    @method(dbus_interface=IFACE, in_signature='s')
    def remove_track_by_filename(self, filename):
        """Remove tracks from database."""
        self.similarity.remove_track_by_filename(filename)

    @method(dbus_interface=IFACE, in_signature='ss')
    def remove_track(self, artist, title):
        """Remove tracks from database."""
        self.similarity.remove_track(artist, title)

    @method(dbus_interface=IFACE, in_signature='s')
    def remove_artist(self, artist):
        """Remove tracks from database."""
        self.similarity.remove_artist(artist)

    @method(dbus_interface=IFACE, in_signature='sbasi')
    def analyze_track(self, filename, add_neighbours, exclude_filenames,
                      priority):
        """Perform mirage analysis of a track."""
        self.similarity.analyze_track(
            filename, add_neighbours, exclude_filenames, priority)

    @method(dbus_interface=IFACE, in_signature='s', out_signature='a(is)')
    def get_ordered_mirage_tracks(self, filename):
        """Get similar tracks by mirage acoustic analysis."""
        return self.similarity.get_ordered_mirage_tracks(filename)

    @method(dbus_interface=IFACE, in_signature='ss', out_signature='a(iss)')
    def get_ordered_similar_tracks(self, artist_name, title):
        """Get similar tracks from last.fm/the database.

        Sorted by descending match score.

        """
        return self.similarity.get_ordered_similar_tracks(artist_name, title)

    @method(dbus_interface=IFACE, in_signature='as', out_signature='a(is)')
    def get_ordered_similar_artists(self, artists):
        """Get similar artists from the database.

        Sorted by descending match score.

        """
        return self.similarity.get_ordered_similar_artists(artists)

    @method(dbus_interface=IFACE, in_signature='as', out_signature='as')
    def miximize(self, filenames):
        """Return ideally ordered list of filenames."""
        return self.similarity.miximize(filenames)

    def run(self):
        """Run loop."""
        self.loop.run()


def register_service(bus):
    """Try to register DBus service for making sure we run only one instance.

    Return True if succesfully registered, False if already running.
    """
    name = bus.request_name(DBUS_BUSNAME, dbus.bus.NAME_FLAG_DO_NOT_QUEUE)
    return name != dbus.bus.REQUEST_NAME_REPLY_EXISTS


def publish_service(bus):
    """Publish the service on DBus."""
    print "publishing"
    bus_name = dbus.service.BusName(DBUS_BUSNAME, bus=bus)
    service = SimilarityService(bus_name=bus_name, object_path=DBUS_PATH)
    service.run()


def main():
    """Start the service if it is not already running."""
    DBusGMainLoop(set_as_default=True)
    bus = dbus.SessionBus()
    if register_service(bus):
        publish_service(bus)
