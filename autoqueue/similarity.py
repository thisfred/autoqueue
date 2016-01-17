"""Autoqueue similarity service.

Copyright 2011-2016 Eric Casteleijn <thisfred@gmail.com>,
                    Graham White

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
from __future__ import absolute_import, print_function

import json
import os
import sqlite3
import subprocess
from datetime import datetime, timedelta
from threading import Thread
from time import sleep, strptime, time
from queue import Empty, LifoQueue, PriorityQueue, Queue
from builtins import object, str

import dbus
import dbus.service
from dbus.mainloop.glib import DBusGMainLoop
from dbus.service import method
from future import standard_library
from gi.repository import GObject
from pylast import LastFMNetwork, MalformedResponseError, NetworkError, WSError

try:
    from gaia2 import DataSet, transform, DistanceFunctionFactory, View, Point
    import yaml
    GAIA = True
except ImportError:
    GAIA = False

from autoqueue.utilities import player_get_data_dir

standard_library.install_aliases()


DBusGMainLoop(set_as_default=True)

DBUS_BUSNAME = 'org.autoqueue'
IFACE = 'org.autoqueue.SimilarityInterface'
DBUS_PATH = '/org/autoqueue/Similarity'

# If you change even a single character of code, I would ask that you
# get and use your own (free) last.fm api key from here:
# http://www.last.fm/api/account
API_KEY = "09d0975a99a4cab235b731d31abf0057"

# XXX: obviously make this configurable
ESSENTIA_EXTRACTOR_PATH = \
    '/home/eric/github/essentia/build/src/examples/streaming_extractor_music'

ADD = 'add'
REMOVE = 'remove'


class SQLCommand(object):

    """A SQL command object."""

    def __init__(self, sql_statements):
        self.sql = sql_statements
        self.result_queue = Queue()


class GaiaAnalysis(Thread):

    """Gaia acoustic analysis and comparison."""

    def __init__(self, db_path, queue):
        super(GaiaAnalysis, self).__init__()
        self.gaia_db_path = db_path
        self.gaia_db = None
        self.commands = {
            ADD: self._analyze,
            REMOVE: self._remove_point}
        self.queue = queue
        self.transformed = False
        self.metric = None

    def initialize(self):
        """Handle more expensive initialization."""
        self.gaia_db = self.initialize_gaia_db()
        try:
            self.metric = DistanceFunctionFactory.create(
                'euclidean', self.gaia_db.layout())
        except Exception as ex:
            print(repr(ex))
            self.gaia_db = self.transform(self.gaia_db)
            self.metric = DistanceFunctionFactory.create(
                'euclidean', self.gaia_db.layout())
            self.transformed = True

    def initialize_gaia_db(self):
        """Load or initialize the gaia database."""
        if not os.path.isfile(self.gaia_db_path):
            dataset = DataSet()
        else:
            dataset = self.load_gaia_db()
            self.transformed = True
        print("songs in db: %d" % dataset.size())
        return dataset

    @staticmethod
    def transform(dataset):
        """Transform dataset for distance computations."""
        dataset = transform(dataset, 'fixlength')
        dataset = transform(dataset, 'cleaner')
        # dataset = transform(dataset, 'remove', {'descriptorNames': '*mfcc*'})
        for field in ('*beats_position*', '*bpm_estimates*', '*bpm_intervals*',
                      '*onset_times*', '*oddtoevenharmonicenergyratio*'):
            try:
                dataset = transform(
                    dataset, 'remove', {'descriptorNames': field})
            except Exception as ex:
                print(repr(ex))
        dataset = transform(dataset, 'normalize')
        dataset = transform(
            dataset, 'pca', {
                'dimension': 30,
                'descriptorNames': ['*'],
                'resultName': 'pca30'})
        return dataset

    def load_gaia_db(self):
        """Load the gaia database from disk."""
        dataset = DataSet()
        dataset.load(self.gaia_db_path)
        return dataset

    def _analyze(self, filename):
        """Analyze an audio file."""
        encoded = filename.encode('utf-8')
        if self.gaia_db.contains(encoded):
            return
        signame = self.get_signame(encoded)
        if not (os.path.exists(signame) or
                self.essentia_analyze(encoded, signame)):
            return
        try:
            point = self.load_point(signame)
            point.setName(encoded)
            self.gaia_db.addPoint(point)
            os.remove(signame)
        except Exception as exc:
            print(exc)

    def _remove_point(self, filename):
        """Remove a point from the gaia database."""
        encoded = filename.encode('utf-8')
        print('removing %s' % encoded)
        try:
            self.gaia_db.removePoint(encoded)
            signame = self.get_signame(encoded)
            os.remove(signame)
        except Exception as exc:
            print(exc)

    @staticmethod
    def load_point(signame):
        """Load point data from JSON file."""
        point = Point()
        with open(signame, 'r') as sig:
            jsonsig = json.load(sig)
            if jsonsig.get('metadata', {}).get('tags'):
                del jsonsig['metadata']['tags']
            yamlsig = yaml.dump(jsonsig)
        point.loadFromString(yamlsig)
        return point

    @staticmethod
    def get_signame(full_path):
        """Get the path for the analysis data file for this filename."""
        filename = os.path.split(full_path)[-1]
        return os.path.join('/tmp', filename + '.sig')

    @staticmethod
    def essentia_analyze(filename, signame):
        """Perform essentia analysis of an audio file."""
        try:
            subprocess.check_call([ESSENTIA_EXTRACTOR_PATH, filename, signame])
            return True
        except Exception as e:
            print(e)
            return False

    def transform_and_save(self, dataset, path):
        """Transform dataset and save to disk."""
        if not self.transformed:
            dataset = self.transform(dataset)
            self.metric = DistanceFunctionFactory.create(
                'euclidean', dataset.layout())
            self.transformed = True
        dataset.save(path)
        return dataset

    def run(self):
        """Run main loop for gaia analysis thread."""
        self.initialize()
        print("STARTING GAIA ANALYSIS THREAD")
        while True:
            cmd, filename = self.queue.get()
            while filename:
                self.commands[cmd](filename)
                try:
                    cmd, filename = self.queue.get(block=False)
                except Empty:
                    self.gaia_db = self.transform_and_save(
                        self.gaia_db, self.gaia_db_path)
                    break
            print(
                "songs in db after processing queue: %d" %
                self.gaia_db.size())

    def get_miximized_tracks(self, filenames):
        """Get list of tracks in ideal order."""
        self.analyze_and_wait(filenames)
        encoded = [f.encode('utf-8') for f in filenames]
        dataset = DataSet()
        number_of_tracks = len(filenames)
        for filename in encoded:
            if not self.gaia_db.contains(filename):
                continue
            point = self.gaia_db.point(filename)
            dataset.addPoint(point)
        dataset = self.transform(dataset)
        matrix = {}
        for filename in encoded:
            matrix[filename] = {
                name: score for score, name in self.get_neighbours(
                    dataset, filename, number_of_tracks)}
        clusterer = Clusterer(encoded, lambda f1, f2: matrix[f1][f2])
        clusterer.cluster()
        result = []
        for cluster in clusterer.clusters:
            result.extend([encoded.index(filename) for filename in cluster])
        return result

    def analyze_and_wait(self, filenames):
        for name in filenames:
            self.queue.put((ADD, name))
        size = self.queue.qsize()
        while self.queue.qsize() > max(0, size - len(filenames)):
            print("waiting for analysis")
            sleep(10)

    def get_best_match(self, filename, filenames):
        self.analyze_and_wait([filename] + filenames)
        encoded_filename = filename.encode('utf-8')
        encoded = [f.encode('utf-8') for f in filenames]
        point = self.gaia_db.point(encoded_filename)

        best, best_name = None, None
        for name in encoded:
            if not self.contains_or_add(name):
                continue
            distance = self.metric(point, self.gaia_db.point(name))
            print("%s, %s" % (distance, name))
            if best is None or distance < best:
                best, best_name = distance, name

        return best_name

    def get_tracks(self, filename, number, request=None):
        """Get most similar tracks from the gaia database."""
        while self.gaia_db is None:
            sleep(.1)
        encoded = filename.encode('utf-8')
        if not self.contains_or_add(encoded):
            return []
        encoded_request = None
        if request:
            encoded_request = request.encode('utf-8')
            if not self.contains_or_add(encoded_request):
                encoded_request = None
        neighbours = self.get_neighbours(
            self.gaia_db, encoded, number, encoded_request=encoded_request)
        print("total found %d" % len(neighbours))
        print(neighbours[0][0], neighbours[-1][0])
        return neighbours

    def get_neighbours(self, dataset, encoded_filename, number,
                       encoded_request=None):
        """Get a number of nearest neighbours."""
        view = View(dataset)
        request_point = self.gaia_db.point(
            encoded_request) if encoded_request else None
        try:
            total = view.nnSearch(
                encoded_filename, self.metric).get(number + 1)[1:]
        except Exception as e:
            print(e)
            return []

        result = sorted([
            (self.compute_score(
                score, name, request_point=request_point) * 1000,
             name)
            for name, score in total])
        if request_point:
            # Filter out the worst matches for the requested track
            return result[:max(1, number / 4)]
        return result

    def compute_score(self, score, name, request_point=None):
        """If there is a request, score by distance to that instead."""
        if request_point is None:
            return score
        return self.metric(request_point, self.gaia_db.point(name))

    def contains_or_add(self, encoded_filename):
        """Check if the filename exists in the database, queue it up if not.

        """
        if not self.gaia_db.contains(encoded_filename):
            print("%s not found in gaia db" % encoded_filename)
            self.queue.put((ADD, str(encoded_filename)))
            return False

        return True


class DatabaseWrapper(Thread):

    """Process to handle all database access."""

    def set_path(self, path):
        """Set the database path."""
        self.path = path

    def set_queue(self, queue):
        """Set the queue to use."""
        self.queue = queue

    def run(self):
        print("STARTING DATABASE WRAPPER THREAD")
        connection = sqlite3.connect(self.path, isolation_level='immediate')
        cursor = connection.cursor()
        commit_needed = False
        while True:
            _, cmd = self.queue.get()
            sql = cmd.sql
            if sql == ('STOP',):
                cmd.result_queue.put(None)
                connection.close()
                break
            result = []
            commit_needed = False
            try:
                cursor.execute(*sql)
            except Exception as e:
                print(e, repr(sql))
            if not sql[0].upper().startswith('SELECT'):
                commit_needed = True
            for row in cursor.fetchall():
                result.append(row)
            if commit_needed:
                connection.commit()
            cmd.result_queue.put(result)


class Pair(object):

    """A pair of songs."""

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
        # sort in reverse, since we'll be popping off the end
        self.similarities.sort(reverse=True, key=lambda x: x.distance)

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
        data_dir = player_get_data_dir()
        self.db_path = os.path.join(data_dir, "similarity.db")
        self.gaia_db_path = os.path.join(data_dir, "gaia.db")
        self.db_queue = PriorityQueue()
        self._db_wrapper = DatabaseWrapper()
        self._db_wrapper.daemon = True
        self._db_wrapper.set_path(self.db_path)
        self._db_wrapper.set_queue(self.db_queue)
        self._db_wrapper.start()
        self.create_db()
        self.network = LastFMNetwork(api_key=API_KEY)
        self.cache_time = 90
        if GAIA:
            self.gaia_queue = LifoQueue()
            self.gaia_analyser = GaiaAnalysis(
                self.gaia_db_path, self.gaia_queue)
            self.gaia_analyser.daemon = True
            self.gaia_analyser.start()

    def execute_sql(self, sql=None, priority=1, command=None):
        """Put sql command on the queue to be executed."""
        if command is None:
            command = SQLCommand(sql)
        self.db_queue.put((priority, command))

    def get_sql_command(self, sql, priority=1):
        """Build a SQLCommand, put it on the queue and return it."""
        command = SQLCommand(sql)
        self.execute_sql(command=command, priority=priority)
        return command

    def remove_track_by_filename(self, filename):
        if not filename:
            return
        if GAIA:
            self.gaia_queue.put((REMOVE, filename))

    def get_ordered_gaia_tracks_by_request(self, filename, number, request):
        start_time = time()
        tracks = self.gaia_analyser.get_tracks(
            filename, number, request=request)
        print("finding gaia matches took %f s" % (time() - start_time,))
        return tracks

    def get_ordered_gaia_tracks(self, filename, number):
        """Get neighbours for track."""
        start_time = time()
        tracks = self.gaia_analyser.get_tracks(filename, number)
        print("finding gaia matches took %f s" % (time() - start_time,))
        return tracks

    def get_artist(self, artist_name):
        """Get artist information from the database."""
        sql = ("SELECT * FROM artists WHERE name = ?;", (artist_name,))
        command = self.get_sql_command(sql, priority=1)
        for row in command.result_queue.get():
            return row
        sql2 = ("INSERT INTO artists (name) VALUES (?);", (artist_name,))
        command = self.get_sql_command(sql2, priority=0)
        command.result_queue.get()
        command = self.get_sql_command(sql, priority=1)
        for row in command.result_queue.get():
            return row

    def get_track_from_artist_and_title(self, artist_name, title):
        """Get track information from the database."""
        artist_id = self.get_artist(artist_name)[0]
        sql = (
            "SELECT * FROM tracks WHERE artist = ? AND title = ?;",
            (artist_id, title))
        command = self.get_sql_command(sql, priority=3)
        for row in command.result_queue.get():
            return row
        sql2 = (
            "INSERT INTO tracks (artist, title) VALUES (?, ?);",
            (artist_id, title))
        command = self.get_sql_command(sql2, priority=2)
        command.result_queue.get()
        command = self.get_sql_command(sql, priority=3)
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
            " artists.id = tracks.artist WHERE track_2_track.track1 = ? UNION "
            "SELECT track_2_track.match, artists.name, tracks.title"
            " FROM track_2_track INNER JOIN tracks ON"
            " track_2_track.track1 = tracks.id INNER JOIN artists ON"
            " artists.id = tracks.artist WHERE track_2_track.track2"
            " = ? ORDER BY track_2_track.match DESC;",
            (track_id, track_id))
        command = self.get_sql_command(sql, priority=0)
        return command.result_queue.get()

    def get_similar_artists(self, artist_id):
        """Get similar artists from the database.

        Sorted by descending match score.

        """
        sql = (
            "SELECT match, name FROM artist_2_artist INNER JOIN"
            " artists ON artist_2_artist.artist2 = artists.id WHERE"
            " artist_2_artist.artist1 = ? UNION "
            "SELECT match, name FROM artist_2_artist INNER JOIN"
            " artists ON artist_2_artist.artist1 = artists.id WHERE"
            " artist_2_artist.artist2 = ? ORDER BY match DESC;",
            (artist_id, artist_id))
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
        for artist_id, similar in list(artists_to_update.items()):
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
        for track_id, similar in list(tracks_to_update.items()):
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
            ' VARCHAR(100), updated DATE, UNIQUE(name));',), priority=0)
        self.execute_sql(
            ('CREATE TABLE IF NOT EXISTS artist_2_artist (artist1 INTEGER,'
             ' artist2 INTEGER, match INTEGER, UNIQUE(artist1, artist2));',),
            priority=0)
        self.execute_sql((
            'CREATE TABLE IF NOT EXISTS tracks (id INTEGER PRIMARY KEY, artist'
            ' INTEGER, title VARCHAR(100), updated DATE, '
            'UNIQUE(artist, title));',), priority=0)
        self.execute_sql((
            'CREATE TABLE IF NOT EXISTS track_2_track (track1 INTEGER, track2'
            ' INTEGER, match INTEGER, UNIQUE(track1, track2));',), priority=0)
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

    def analyze_track(self, filename):
        """Perform gaia analysis of a track."""
        if not filename:
            return
        if GAIA:
            self.gaia_queue.put((ADD, filename))

    def analyze_tracks(self, filenames):
        """Analyze audio files."""
        if not filenames:
            return
        if GAIA:
            for filename in filenames:
                self.gaia_queue.put((ADD, filename))

    def get_similar_tracks_from_lastfm(self, artist_name, title, track_id,
                                       cutoff=0):
        """Get similar tracks."""
        try:
            lastfm_track = self.network.get_track(artist_name, title)
        except (WSError, NetworkError, MalformedResponseError) as e:
            print(e)
            return []
        tracks_to_update = {}
        results = []
        try:
            for similar in lastfm_track.get_similar():
                match = int(100 * similar.match)
                if match <= cutoff:
                    continue
                item = similar.item
                similar_artist = item.artist.get_name()
                similar_title = item.title
                tracks_to_update.setdefault(track_id, []).append({
                    'score': match,
                    'artist': similar_artist,
                    'title': similar_title})
                results.append((match, similar_artist, similar_title))
        except (WSError, NetworkError, MalformedResponseError) as e:
            print(e)
            return []
        self.update_similar_tracks(tracks_to_update)
        return results

    def get_similar_artists_from_lastfm(self, artist_name, artist_id,
                                        cutoff=0):
        """Get similar artists from lastfm."""
        try:
            lastfm_artist = self.network.get_artist(artist_name)
        except (WSError, NetworkError, MalformedResponseError) as e:
            print(e)
            return []
        artists_to_update = {}
        results = []
        try:
            for similar in lastfm_artist.get_similar():
                match = int(100 * similar.match)
                if match <= cutoff:
                    continue
                name = similar.item.get_name()
                artists_to_update.setdefault(artist_id, []).append({
                    'score': match,
                    'artist': name})
                results.append((match, name))
        except (WSError, NetworkError, MalformedResponseError) as e:
            print(e)
            return []
        self.update_similar_artists(artists_to_update)
        return results

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
                print(
                    "Getting similar tracks from db for: %s - %s" % (
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
                    print(
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
        if not GAIA:
            return []

        return self.gaia_analyser.get_miximized_tracks(filenames)

    def get_best_match(self, filename, filenames):
        if not GAIA:
            return

        return self.gaia_analyser.get_best_match(filename, filenames)


class SimilarityService(dbus.service.Object):

    """Service that can be queried for similar songs."""

    def __init__(self, bus_name, object_path):
        self.similarity = Similarity()
        dbus.service.Object.__init__(
            self, bus_name=bus_name, object_path=object_path)
        self.loop = GObject.MainLoop()

    @method(dbus_interface=IFACE, in_signature='s')
    def remove_track_by_filename(self, filename):
        """Remove tracks from database."""
        self.similarity.remove_track_by_filename(str(filename))

    @method(dbus_interface=IFACE, in_signature='s')
    def analyze_track(self, filename):
        """Perform analysis of a track."""
        self.similarity.analyze_track(str(filename))

    @method(dbus_interface=IFACE, in_signature='as')
    def analyze_tracks(self, filenames):
        """Perform analysis of multiple tracks."""
        self.similarity.analyze_tracks([
            str(filename) for filename in filenames])

    @method(dbus_interface=IFACE, in_signature='si', out_signature='a(is)')
    def get_ordered_gaia_tracks(self, filename, number):
        """Get similar tracks by gaia acoustic analysis."""
        return self.similarity.get_ordered_gaia_tracks(
            str(filename), number)

    @method(dbus_interface=IFACE, in_signature='sis', out_signature='a(is)')
    def get_ordered_gaia_tracks_by_request(self, filename, number, request):
        """Get similar tracks by gaia acoustic analysis."""
        return self.similarity.get_ordered_gaia_tracks_by_request(
            str(filename), number, str(request))

    @method(dbus_interface=IFACE, in_signature='ss', out_signature='a(iss)')
    def get_ordered_similar_tracks(self, artist_name, title):
        """Get similar tracks from last.fm/the database.

        Sorted by descending match score.

        """
        return self.similarity.get_ordered_similar_tracks(
            str(artist_name), str(title))

    @method(dbus_interface=IFACE, in_signature='as', out_signature='a(is)')
    def get_ordered_similar_artists(self, artists):
        """Get similar artists from the database.

        Sorted by descending match score.

        """
        return self.similarity.get_ordered_similar_artists(
            [str(a) for a in artists])

    @method(dbus_interface=IFACE, in_signature='as', out_signature='ai')
    def miximize(self, filenames):
        """Return ideally ordered list of filenames."""
        return self.similarity.miximize([str(f) for f in filenames])

    @method(dbus_interface=IFACE, out_signature='b')
    def has_gaia(self):
        """Get gaia installation status."""
        return GAIA

    @method(dbus_interface=IFACE, in_signature='sas', out_signature='s')
    def get_best_match(self, filename, filenames):
        return self.similarity.get_best_match(
            str(filename), [str(f) for f in filenames])

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
    print("publishing")
    bus_name = dbus.service.BusName(DBUS_BUSNAME, bus=bus)
    service = SimilarityService(bus_name=bus_name, object_path=DBUS_PATH)
    service.run()


def main():
    """Start the service if it is not already running."""
    DBusGMainLoop(set_as_default=True)
    bus = dbus.SessionBus()
    if register_service(bus):
        publish_service(bus)
