"""Autoqueue similarity service.

Copyright 2011-2013 Eric Casteleijn <thisfred@gmail.com>,
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

# TODO: real logging

import dbus
import dbus.service
import functools
from gi.repository import GObject
import os
import random
import json

import subprocess
from threading import Thread
from Queue import Queue, PriorityQueue, Empty
from time import strptime, time
from datetime import datetime, timedelta
from collections import namedtuple
from dbus.mainloop.glib import DBusGMainLoop
from dbus.service import method

import sqlite3

from pylast import LastFMNetwork, WSError, NetworkError

from mirage import (
    Mir, MatrixDimensionMismatchException, MfccFailedException,
    instance_from_picklestring, instance_to_picklestring,
    ScmsConfiguration, distance)
MIRAGE = True

try:
    from gaia2 import DataSet, transform, DistanceFunctionFactory, View, Point
    import yaml
    GAIA = True
except ImportError:
    GAIA = False


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
FIFTEEN_MINUTES = timedelta(minutes=15)

Track = namedtuple('Track', 'id filename loved hated artist title')

# XXX: obviously make this configurable
ESSENTIA_EXTRACTOR_PATH = \
    '/home/eric/essentia-2.0.1/build/src/examples/streaming_extractor'

DEFAULT_TRACK = Track(
    id=None,
    filename=None,
    loved=False,
    hated=False,
    artist=None,
    title=None)

ADD = 'add'
REMOVE = 'remove'


def memoize(f):
    cache = {}

    @functools.wraps(f)
    def memoizer(*args):
        if args not in cache:
            cache[args] = f(*args)
        return cache[args]
    return memoizer


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


class GaiaAnalysis(Thread):

    def __init__(self, db_path, queue):
        super(GaiaAnalysis, self).__init__()
        self.gaia_db_path = db_path
        self.gaia_db = self.load_gaia()
        self.gaia_db_transformed = self.transform_gaia_db(self.gaia_db)
        self.metric = DistanceFunctionFactory.create(
            'euclidean', self.gaia_db_transformed.layout())
        self.commands = {
            ADD: self._add_point,
            REMOVE: self._remove_point}
        self.queue = queue

    def transform_gaia_db(self, original):
        ds = transform(original, 'fixlength')
        ds = transform(ds, 'cleaner')
        ds = transform(ds, 'remove', {'descriptorNames': '*mfcc*'})
        ds = transform(ds, 'remove', {'descriptorNames': '*beats_position*'})
        ds = transform(ds, 'remove', {'descriptorNames': '*bpm_estimates*'})
        ds = transform(ds, 'remove', {'descriptorNames': '*bpm_intervals*'})
        ds = transform(ds, 'remove', {'descriptorNames': '*onset_times*'})
        ds = transform(ds, 'normalize')
        ds = transform(
            ds, 'pca', {
                'dimension': 30,
                'descriptorNames': ['*.mean', '*.var'],
                'resultName': 'pca30'})
        ds.setReferenceDataSet(original)
        return ds

    def load_gaia(self):
        if os.path.exists(self.gaia_db_path):
            ds = DataSet()
            ds.load(self.gaia_db_path)
        else:
            db = {}
            for directory in self.music_dirs:
                filename = self.index_sig_files(directory)
                db.update({
                    k.encode('utf-8'): v.encode('utf-8')
                    for k, v in yaml.load(open(filename).read()).items()})
            ds = DataSet.mergeFiles(db)
            ds.save(self.gaia_db_path)

        return ds

    @staticmethod
    def get_db_filename(directory):
        return '%s.yaml' % (directory.replace('/', '_'),)

    def index_sig_files(self, directory):
        filename = self.get_db_filename(directory)
        files = [
            f for f in subprocess.check_output(
                "find -L %s -iname '*.sig'" % directory, shell=True).split('\n')
            if f]

        with open(filename, 'w') as output:
            for sig_file in files:
                if isinstance(sig_file, unicode):
                    sig_file = sig_file.encode('utf-8')
                output.write(
                    '"%s": "%s"\n' % (
                        '.'.join(sig_file.split('.')[:-1]), sig_file))
        return filename


    def _add_point(self, filename):
        encoded = filename.encode('utf-8')
        if self.gaia_db.contains(encoded):
            return 0
        signame = self.get_signame(encoded)
        if not os.path.exists(signame):
            if not self.essentia_analyze(encoded, signame):
                return 0
        point = Point()
        point.load(signame)
        point.setName(encoded)
        self.gaia_db.addPoint(point)
        return 1

    def _remove_point(self, filename):
        encoded = filename.encode('utf-8')
        try:
            self.gaia_db.removePoint(encoded)
            dirty = 1
        except:
            dirty = 0
        signame = self.get_signame(encoded)
        if os.path.isfile(signame):
            os.remove(signame)
        return dirty

    @staticmethod
    def get_signame(filename):
        """Get the path for the analysis data file for this filename."""
        return filename + '.sig'

    def essentia_analyze(self, filename, signame):
        try:
            subprocess.check_call(
                ['timeout', '120', ESSENTIA_EXTRACTOR_PATH, filename, signame])
            return True
        except Exception as e:
            print e
            return False

    def run(self):
        print "STARTING GAIA ANALYSIS THREAD"
        while True:
            cmd, filename = self.queue.get()
            done = 0
            while filename:
                done += self.commands[cmd](filename)
                if done and (done % 100 == 0):
                    self.rebuild()
                    done = 0
                try:
                    cmd, filename = self.queue.get(block=False)
                except Empty:
                    break
            if done:
                self.rebuild()

    def rebuild(self):
        self.gaia_db_transformed = self.transform_gaia_db(self.gaia_db)
        self.gaia_db.save(self.gaia_db_path)

    def get_tracks(self, filename, excluded_artists, number, cutoff):
        encoded = filename.encode('utf-8')
        if not self.gaia_db.contains(encoded):
            self.queue.put((ADD, filename))
            return []

        view = View(self.gaia_db_transformed)
        if excluded_artists:
            filt = 'WHERE label.metadata.tags.artist NOT IN (%s)' % (
                ','.join([
                    '"%s", "%s"' % (
                        artist.encode('utf-8'),
                        artist.encode('utf-8').title())
                    for artist in excluded_artists]))
        else:
            filt = ""
        try:
            return [
                (score * 1000, name) for name, score
                in view.nnSearch(encoded, self.metric, filt).get(number)[1:]
                if score * 1000 < cutoff]
        except:
            return []

class DatabaseWrapper(Thread):
    """Process to handle all database access."""

    def set_path(self, path):
        """Set the database path."""
        self.path = path                # pylint: disable=W0201

    def set_queue(self, queue):
        """Set the queue to use."""
        self.queue = queue              # pylint: disable=W0201

    def run(self):
        print "STARTING DATABASE WRAPPER THREAD"
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
            except Exception, e:        # pylint: disable=W0703
                print e, repr(sql)
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
        self.music_dirs = []
        self.db_path = os.path.join(
            self.player_get_data_dir(), "similarity.db")
        self.gaia_db_path = os.path.join(
            self.player_get_data_dir(), "gaia.db")
        self.db_queue = PriorityQueue()
        self._db_wrapper = DatabaseWrapper()
        self._db_wrapper.daemon = True
        self._db_wrapper.set_path(self.db_path)
        self._db_wrapper.set_queue(self.db_queue)
        self._db_wrapper.start()
        self.create_db()
        if MIRAGE:
            self.mir = Mir()
        self.network = LastFMNetwork(api_key=API_KEY)
        self.cache_time = 90
        self.users = {}
        self.absent = {}
        self.last_seen = {}
        self.history = []
        self.now_playing = None
        if GAIA:
            self.gaia_queue = Queue()
            self.gaia_analyser = GaiaAnalysis(
                self.gaia_db_path, self.gaia_queue)
            self.gaia_analyser.daemon = True
            self.gaia_analyser.start()

    def join(self, name):
        user_id = self.get_user_id(name)
        if user_id not in self.users:
            if user_id in self.absent:
                self.users[user_id] = self.absent[user_id]
                del self.absent[user_id]
            else:
                self.users[user_id] = {}
        self.last_seen[user_id] = datetime.utcnow()
        return user_id

    def leave(self, user_id):
        if user_id not in self.users:
            return
        self.absent[user_id] = self.users[user_id]
        del self.users[user_id]

    @memoize
    def get_user_id(self, name):
        sql = ("SELECT users.id FROM users WHERE users.name = ?;", (name,),)
        command = self.get_sql_command(sql, priority=1)
        for row in command.result_queue.get():
            return row[0]
        self.execute_sql(
            ("INSERT INTO users (name) VALUES (?);", (name,)), priority=0)
        command = self.get_sql_command(sql, priority=1)
        for row in command.result_queue.get():
            return row[0]

    def get_lovers_and_haters(self, track_id):
        sql = ("SELECT user, loved FROM users_2_tracks WHERE track = ?;", (
            track_id,))
        command = self.get_sql_command(sql, priority=0)
        lovers = set([])
        haters = set([])
        for row in command.result_queue.get():
            if row[1]:
                lovers.add(row[0])
            else:
                haters.add(row[0])
        return lovers, haters

    def get_filename(self, track_id):
        sql = (
            "SELECT filename FROM mirage WHERE mirage.trackid = ?;",
            (track_id,))
        command = self.get_sql_command(sql, priority=0)
        for row in command.result_queue.get():
            return row[0]

    def get_user_tracks(self, user_id):
        sql = (
            "SELECT mirage.trackid, mirage.filename, users_2_tracks.loved "
            "FROM users_2_tracks INNER JOIN mirage ON users_2_tracks.track = "
            "mirage.trackid WHERE users_2_tracks.user = ?;", (user_id,))
        command = self.get_sql_command(sql, priority=0)
        for row in command.result_queue.get():
            if row[2]:
                yield DEFAULT_TRACK._replace(
                    id=row[0],
                    filename=row[1],
                    loved=True)
            else:
                yield DEFAULT_TRACK._replace(
                    id=row[0],
                    filename=row[1],
                    hated=True)

    def get_player_info(self):
        return {
            'history': [t._asdict() for t in self.history],
            'now_playing': self.now_playing and self.now_playing._asdict(),
            'requests': list(self.get_requests())}

    def get_user_info(self, user_id):
        user = self.users[user_id]
        self.last_seen[user_id] = datetime.utcnow()
        if 'loved' not in user:
            for track in self.get_user_tracks(user_id):
                if track.loved:
                    user.setdefault('loved', {})[
                        track.filename] = track._asdict()
                elif track.hated:
                    user.setdefault('hated', {})[
                        track.filename] = track._asdict()
        return user

    def love(self, user_id, track_id):
        user = self.users[user_id]
        self.last_seen[user_id] = datetime.utcnow()
        self.execute_sql(
            ("INSERT INTO users_2_tracks (user, track, loved) VALUES "
             "(?, ?, ?);", (user_id, track_id, True)))
        filename = self.get_filename(track_id)
        user.setdefault('loved', {})[filename] = DEFAULT_TRACK._replace(
            id=track_id,
            filename=filename)

    def hate(self, user_id, track_id):
        user = self.users[user_id]
        self.last_seen[user_id] = datetime.utcnow()
        self.execute_sql(
            ("INSERT INTO users_2_tracks (user, track, loved) VALUES "
             "(?, ?, ?);", (user_id, track_id, False)))
        filename = self.get_filename(track_id)
        user.setdefault('hated', {})[filename] = DEFAULT_TRACK._replace(
            id=track_id,
            filename=filename)
        if self.now_playing.id == track_id:
            subprocess.call(['quodlibet', '--next'])

    def meh(self, user_id, track_id):
        user = self.users[user_id]
        self.last_seen[user_id] = datetime.utcnow()
        self.execute_sql(
            ("DELETE FROM users_2_tracks WHERE users_2_tracks.user = ? AND "
             "users_2_tracks.track = ?", (user_id, track_id)))
        for filename, track in user.setdefault('hated', {}).items():
            if track['id'] == track_id:
                del user['hated'][filename]
                return
        for filename, track in user.setdefault('loved', {}).items():
            if track['id'] == track_id:
                del user['loved'][filename]
                return

    def add_request(self, user_id, filename):
        self.users[user_id].setdefault('requests', []).append(filename)
        self.analyze_track(filename, priority=0)

    def start_song(self, filename, artist, title):
        self.remove_request(filename)
        if self.now_playing:
            self.history.append(self.now_playing)
            self.history = self.history[-5:]
        self.now_playing = DEFAULT_TRACK._replace(
            id=self.get_track_id(filename),
            filename=filename,
            artist=artist,
            title=title)

    def remove_request(self, filename):
        for user in self.users.values():
            requests = user.get('requests', [])
            if filename in requests:
                requests.remove(filename)

    @property
    def present(self):
        return set(self.users.keys())

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

    def player_get_data_dir(self):
        """Get the directory to store user data.

        Defaults to $XDG_DATA_HOME/autoqueue on Gnome.

        """
        if not XDG:
            data_dir = os.path.join(os.path.expanduser('~'), '.autoqueue')
        else:
            data_dir = os.path.join(
                xdg.BaseDirectory.xdg_data_home, 'autoqueue')
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
        # TODO: remove likes/dislikes from users_2_tracks
        self.execute_sql(
            ('DELETE FROM mirage WHERE filename = ?', (filename,)),
            priority=10)
        self.gaia_queue.put((REMOVE, filename))

    def remove_track(self, artist, title):
        """Delete missing track."""
        sql = (
            'SELECT tracks.id FROM tracks WHERE tracks.title = ? AND '
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
            self.execute_sql(
                "DELETE FROM users_2_tracks WHERE users_2_tracks.track = ?",
                (track_id,))
        self.delete_orphan_artist(artist)

    def remove_artist(self, artist):
        """Delete missing artist."""
        sql = ('SELECT id from artists WHERE artists.name = ?;', (artist,))
        command = self.get_sql_command(sql, priority=10)
        for row in command.result_queue.get():
            artist_id = row[0]
            self.execute_sql(
                ('DELETE FROM artists WHERE artists.id = ?;', (artist_id,)),
                priority=10)
            self.execute_sql(
                ('DELETE FROM tracks WHERE tracks.artist = ?;', (artist_id,)),
                priority=10)

    def get_scms_from_filename(self, filename, priority=10):
        """Get track from database."""
        sql = (
            "SELECT scms FROM mirage WHERE filename = ?;",
            (filename,))
        command = self.get_sql_command(sql, priority=priority)
        for row in command.result_queue.get():
            return instance_from_picklestring(row[0])
        return None

    @memoize
    def get_track_id(self, filename):
        """Get track id from database."""
        sql = ("SELECT trackid FROM mirage WHERE filename = ?;", (filename,))
        command = self.get_sql_command(sql, priority=0)
        for row in command.result_queue.get():
            return row[0]
        self.analyze_track(filename, priority=0)
        sql = ("SELECT trackid FROM mirage WHERE filename = ?;", (filename,))
        command = self.get_sql_command(sql, priority=0)
        for row in command.result_queue.get():
            return row[0]

    def get_tracks(self, priority=0):
        """Get tracks from database."""
        sql = ("SELECT trackid, scms, filename FROM mirage;",)
        command = self.get_sql_command(sql, priority=priority)
        return command.result_queue.get()

    def get_ordered_gaia_tracks(self, filename, excluded_artists, number,
                                cutoff=500):
        """Get neighbours for track."""
        if not excluded_artists:
            excluded_artists = []
        # XXX: move to init, if the view updates when new keys are added.
        return self.gaia_analyser.get_tracks(
            filename, excluded_artists, number, cutoff)

    def get_ordered_mirage_tracks(self, filename, excluded_filenames, number,
                                  cutoff=20000):
        """Get neighbours for track."""
        start_time = time()
        if not excluded_filenames:
            excluded_filenames = []
        conf = ScmsConfiguration(20)
        best = []
        scms = self.get_scms_from_filename(filename)
        if scms is None:
            try:
                scms = self.mir.analyze(filename)
            except:
                return []
            self.add_track(filename, scms, priority=11)
        tries = 0
        tracks = self.get_tracks()
        total = len(tracks)
        tried = set([])
        misses = 0
        miss_target = total / 200
        while len(tried) < total:
            entry = random.randrange(0, total)
            while entry in tried and len(tried) < total:
                entry = random.randrange(0, total)
            tried.add(entry)
            track_id, buf, other_filename = tracks[entry]
            if other_filename in excluded_filenames:
                continue
            if filename == other_filename:
                continue
            other = instance_from_picklestring(buf)
            dist = int(distance(scms, other, conf) * 1000)
            if dist < 0:
                continue
            if len(best) >= number:
                tries += 1
                if dist > best[-1][0]:
                    misses += 1
                    if misses > miss_target:
                        break
                    continue
                misses = 0
            lovers, haters = self.get_lovers_and_haters(track_id)
            if self.present & haters:
                continue
            best.append((dist, other_filename, len(self.present & lovers)))
            best.sort()
            while len(best) > number:
                best.pop()
        for filename in self.get_requests():
            other = self.get_scms_from_filename(filename, priority=0)
            dist = int(distance(scms, other, conf) * 1000)
            best.append((dist, filename, 1))
        best.sort()
        print "%d tries in %f s" % (tries, time() - start_time)
        if best:
            cutoff = min(cutoff, best[0][0] * 2)
        return [r for r in best if r[0] < cutoff]

    def get_requests(self):
        for user_id in self.present:
            for filename in self.users.get(user_id, {}).get('requests', []):
                yield filename

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
            'CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, name'
            ' VARCHAR(100), UNIQUE(name));',), priority=0)
        self.execute_sql((
            'CREATE TABLE IF NOT EXISTS users_2_tracks (user INTEGER, track'
            ' INTEGER, loved BOOLEAN);',), priority=0)
        self.execute_sql((
            'CREATE TABLE IF NOT EXISTS artists (id INTEGER PRIMARY KEY, name'
            ' VARCHAR(100), updated DATE, UNIQUE(name));',), priority=0)
        self.execute_sql((
            'CREATE TABLE IF NOT EXISTS artist_2_artist (artist1 INTEGER,'
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
            'CREATE TABLE IF NOT EXISTS mirage (trackid INTEGER PRIMARY KEY, '
            'filename VARCHAR(300), scms BLOB, UNIQUE(filename));',),
            priority=0)
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

    def analyze_track(self, filename, priority):
        """Perform mirage analysis of a track."""
        if not filename:
            return
        if GAIA:
            self.gaia_queue.put((ADD, filename))
        if MIRAGE:
            scms = self.get_scms_from_filename(filename, priority=priority)
            if scms:
                return
            else:
                self.log(
                    "no mirage data found for %s, analyzing track" % filename)
                try:
                    scms = self.mir.analyze(filename)
                except (MatrixDimensionMismatchException, MfccFailedException,
                        IndexError), e:
                    self.log(repr(e))
                    return
                self.add_track(filename, scms, priority=priority - 1)

    def analyze_tracks(self, filenames, priority):
        if not filenames:
            return
        if GAIA:
            for filename in filenames:
                self.gaia_queue.put((ADD, filename))
        if MIRAGE:
            for filename in filenames:
                scms = self.get_scms_from_filename(filename, priority=priority)
                if scms:
                    return
                else:
                    self.log(
                        "no mirage data found for %s, analyzing track" % (
                            filename,))
                    try:
                        scms = self.mir.analyze(filename)
                    except (MatrixDimensionMismatchException,
                            MfccFailedException, IndexError), e:
                        self.log(repr(e))
                        return
                    self.add_track(filename, scms, priority=priority - 1)

    def get_similar_tracks_from_lastfm(self, artist_name, title, track_id,
                                       cutoff=0):
        """Get similar tracks."""
        try:
            lastfm_track = self.network.get_track(artist_name, title)
        except (WSError, NetworkError), e:
            print e
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
        except (WSError, NetworkError), e:
            print e
            return []
        self.update_similar_tracks(tracks_to_update)
        return results

    def get_similar_artists_from_lastfm(self, artist_name, artist_id,
                                        cutoff=0):
        """Get similar artists from lastfm."""
        try:
            lastfm_artist = self.network.get_artist(artist_name)
        except (WSError, NetworkError), e:
            print e
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
        except (WSError, NetworkError), e:
            print e
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
            scms = self.get_scms_from_filename(filename, priority=10)
            if not scms:
                try:
                    scms = self.mir.analyze(filename)
                except:
                    continue
                self.add_track(filename, scms, priority=10)
            songs.append(Song(filename, scms))
        self.log("clustering")
        conf = ScmsConfiguration(20)
        clusterer = Clusterer(
            songs, lambda song1, song2: distance(song1.scms, song2.scms, conf))
        clusterer.cluster()
        qsongs = []
        for cluster in clusterer.clusters:
            qsongs.extend([filenames.index(song.filename) for song in cluster])
        return qsongs


class SimilarityService(dbus.service.Object):
    """Service that can be queried for similar songs."""

    def __init__(self, bus_name, object_path):
        self.similarity = Similarity()
        super(SimilarityService, self).__init__(
            bus_name=bus_name, object_path=object_path)
        self.loop = GObject.MainLoop()

    @method(dbus_interface=IFACE, in_signature='s', out_signature='i')
    def join(self, name):
        return self.similarity.join(unicode(name))

    @method(dbus_interface=IFACE, in_signature='i')
    def leave(self, user_id):
        self.similarity.leave(user_id)

    @method(dbus_interface=IFACE, in_signature='is')
    def add_request(self, user_id, filename):
        self.similarity.add_request(int(user_id), unicode(filename))

    @method(dbus_interface=IFACE, in_signature='s')
    def end_song(self, filename):
        self.similarity.end_song(unicode(filename))

    @method(dbus_interface=IFACE, in_signature='sss')
    def start_song(self, filename, artist, title):
        self.similarity.start_song(
            unicode(filename), unicode(artist), unicode(title))

    @method(dbus_interface=IFACE, in_signature='ii')
    def love(self, user_id, track_id):
        self.similarity.love(int(user_id), int(track_id))

    @method(dbus_interface=IFACE, in_signature='ii')
    def hate(self, user_id, track_id):
        self.similarity.hate(int(user_id), int(track_id))

    @method(dbus_interface=IFACE, in_signature='ii')
    def meh(self, user_id, track_id):
        self.similarity.meh(int(user_id), int(track_id))

    @method(dbus_interface=IFACE, in_signature='i', out_signature='s')
    def get_user_info(self, user_id):
        return json.dumps(self.similarity.get_user_info(int(user_id)))

    @method(dbus_interface=IFACE, out_signature='s')
    def get_player_info(self):
        return json.dumps(self.similarity.get_player_info())

    @method(dbus_interface=IFACE, in_signature='s')
    def remove_track_by_filename(self, filename):
        """Remove tracks from database."""
        self.similarity.remove_track_by_filename(unicode(filename))

    @method(dbus_interface=IFACE, in_signature='ss')
    def remove_track(self, artist, title):
        """Remove tracks from database."""
        self.similarity.remove_track(unicode(artist), unicode(title))

    @method(dbus_interface=IFACE, in_signature='s')
    def remove_artist(self, artist):
        """Remove tracks from database."""
        self.similarity.remove_artist(unicode(artist))

    @method(dbus_interface=IFACE, in_signature='si')
    def analyze_track(self, filename, priority):
        """Perform mirage analysis of a track."""
        self.similarity.analyze_track(unicode(filename), priority)

    @method(dbus_interface=IFACE, in_signature='asi')
    def analyze_tracks(self, filenames, priority):
        """Perform analysis of multiple tracks."""
        self.similarity.analyze_tracks(
            [unicode(filename) for filename in filenames], priority)

    @method(dbus_interface=IFACE, in_signature='sasi', out_signature='a(isi)')
    def get_ordered_mirage_tracks(self, filename, exclude_filenames, number):
        """Get similar tracks by mirage acoustic analysis."""
        return self.similarity.get_ordered_mirage_tracks(
            unicode(filename), [unicode(e) for e in exclude_filenames], number)

    @method(dbus_interface=IFACE, in_signature='sasi', out_signature='a(is)')
    def get_ordered_gaia_tracks(self, filename, exclude_artists, number):
        """Get similar tracks by mirage acoustic analysis."""
        return self.similarity.get_ordered_gaia_tracks(
            unicode(filename), [unicode(e) for e in exclude_artists], number)

    @method(dbus_interface=IFACE, in_signature='ss', out_signature='a(iss)')
    def get_ordered_similar_tracks(self, artist_name, title):
        """Get similar tracks from last.fm/the database.

        Sorted by descending match score.

        """
        return self.similarity.get_ordered_similar_tracks(
            unicode(artist_name), unicode(title))

    @method(dbus_interface=IFACE, in_signature='as', out_signature='a(is)')
    def get_ordered_similar_artists(self, artists):
        """Get similar artists from the database.

        Sorted by descending match score.

        """
        return self.similarity.get_ordered_similar_artists(
            [unicode(a) for a in artists])

    @method(dbus_interface=IFACE, in_signature='as', out_signature='ai')
    def miximize(self, filenames):
        """Return ideally ordered list of filenames."""
        return self.similarity.miximize([unicode(f) for f in filenames])

    @method(dbus_interface=IFACE, out_signature='b')
    def has_mirage(self):
        """Get mirage installation status."""
        return MIRAGE

    @method(dbus_interface=IFACE, out_signature='b')
    def has_gaia(self):
        """Get mirage installation status."""
        return GAIA

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
