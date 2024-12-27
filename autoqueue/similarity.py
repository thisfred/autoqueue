"""Autoqueue similarity service.

Copyright 2011-2020 Eric Casteleijn <thisfred@gmail.com>,
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

import json
import os
import sqlite3
import subprocess
from dataclasses import dataclass
from functools import total_ordering
from pathlib import Path
from queue import Empty, LifoQueue, PriorityQueue, Queue
from threading import Thread
from time import sleep, time
from typing import Callable, List, Optional, Sequence, Tuple
from uuid import uuid4

import dbus
import dbus.service
from dbus.mainloop.glib import DBusGMainLoop
from dbus.service import method
from gi.repository import GObject

from autoqueue.utilities import player_get_data_dir

try:
    import yaml
    from gaia2 import (
        DataSet,
        DistanceFunction,
        DistanceFunctionFactory,
        Point,
        View,
        transform,
    )

    GAIA = True
except ImportError:
    GAIA = False
print("Gaia installed:", GAIA)


DBusGMainLoop(set_as_default=True)

DBUS_BUSNAME = "org.autoqueue"
IFACE = "org.autoqueue.SimilarityInterface"
DBUS_PATH = "/org/autoqueue/Similarity"

# XXX: make this configurable
ESSENTIA_EXTRACTOR_PATH = "streaming_extractor_music"

ADD = "add"
REMOVE = "remove"

FRAGMENT_SECONDS = 30


@dataclass
class GaiaDB:
    path: Path
    transformed: bool = False
    _dataset: DataSet | None = None
    _metric: DistanceFunction | None = None

    @property
    def dataset(self):
        if self._dataset is None:
            self._dataset = DataSet()
            if self.path.exists():
                self._dataset.load(str(self.path))
                self.transformed = True
        return self._dataset

    @property
    def metric(self):
        if self._metric is None:
            try:
                self._metric = DistanceFunctionFactory.create(
                    "euclidean", self.dataset.layout()
                )
            except Exception as e:
                print(repr(e))
                self.transform()
                self._metric = DistanceFunctionFactory.create(
                    "euclidean", self.dataset.layout()
                )

        return self._metric

    def transform(self):
        """Transform dataset for distance computations."""
        dataset = transform(self.dataset, "fixlength")
        dataset = transform(dataset, "cleaner")
        dataset = transform(dataset, "remove", {"descriptorNames": "*beats_position*"})
        dataset = transform(dataset, "remove", {"descriptorNames": "*mfcc*"})
        dataset = transform(dataset, "normalize")
        dataset = transform(
            dataset,
            "pca",
            {
                "dimension": 30,
                "descriptorNames": ["*.mean", "*.var"],
                "resultName": "pca30",
            },
        )
        self._dataset = dataset
        self.transformed = True

    def transform_and_save(self) -> DataSet:
        """Transform dataset and save to disk."""

        if not self.transformed:
            self.transform()
            self._metric = DistanceFunctionFactory.create(
                "euclidean", self.dataset.layout()
            )
            self.transformed = True
        self.dataset.save(str(self.path))
        return self

    def __contains__(self, filename):
        return self.dataset.contains(filename)

    def __getitem__(self, filename) -> Point:
        if not self.dataset.contains(filename):
            raise KeyError(filename)

        return self.dataset.point(filename)

    def __setitem__(self, filename: str, point: Point) -> None:
        point.setName(filename)
        self.dataset.addPoint(point)

    def get(self, filename: str) -> Point | None:
        try:
            return self[filename]
        except KeyError:
            return None


@total_ordering
class SQLCommand(object):

    """A SQL command object."""

    def __init__(self, sql_statements):
        self.sql = sql_statements
        self.result_queue: Queue = Queue()

    def __eq__(self, other):
        return self.sql == other.sql

    def __ne__(self, other):
        return not self == other

    def __lt__(self, other):
        return self.sql < other.sql


FFMPEG_ARGS = (
    ("-ss", "0", "-t", str(FRAGMENT_SECONDS)),
    ("-sseof", str(-FRAGMENT_SECONDS)),
)


def tmp_path(suffix) -> Path:
    return (Path("/tmp") / Path(str(uuid4()))).with_suffix(suffix)


class GaiaAnalysis(Thread):

    """Gaia acoustic analysis and comparison."""

    def __init__(self, queue):
        super(GaiaAnalysis, self).__init__()
        data_dir = player_get_data_dir()
        self.transformed = False
        self.gaia_db_new = GaiaDB(
            Path(data_dir) / "new_gaia.db",
        )
        print("songs in db: %d" % self.gaia_db_new.dataset.size())

        self.commands = {ADD: self._analyze, REMOVE: self._remove_point}
        self.queue = queue
        self.seen = set()
        self.analyzed = 0
        self.factor = 2

    def _analyze(self, filename: str) -> None:
        """Analyze an audio file."""

        for i, ffmpeg_args in enumerate(FFMPEG_ARGS):
            suffix = str(i)
            if filename + suffix in self.gaia_db_new:
                continue

            new_path = tmp_path(Path(filename).suffix)

            env = os.environ.copy()
            try:
                subprocess.check_call(
                    [
                        "ffmpeg",
                        *ffmpeg_args,
                        "-i",
                        filename,
                        "-c:a",
                        "copy",
                        str(new_path),
                        "-loglevel",
                        "error",
                        "-hide_banner",
                    ],
                    env=env,
                    stderr=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                )
            except subprocess.CalledProcessError:
                pass

            if not new_path.exists():
                print("ffmpeg failed to extract")

            sig_path = tmp_path(".sig")
            if not (
                self.essentia_analyze(self.gaia_db_new.dataset, new_path, sig_path)
            ):
                try:
                    new_path.unlink()
                except FileNotFoundError:
                    pass
                return

            try:
                new_path.unlink()
            except FileNotFoundError:
                pass
            try:
                point = self.load_point(sig_path)
                self.gaia_db_new[filename + suffix] = point
                self.analyzed += 1
            except Exception as e:
                print(e)

            try:
                sig_path.unlink()
            except FileNotFoundError:
                pass

        print("{} songs left to analyze.".format(self.queue.qsize()))

    def _remove_point(self, filename: str) -> None:
        """Remove a point from the gaia database."""
        try:
            self.gaia_db_new.dataset.removePoint(filename + "0")
        except Exception as exc:
            print(exc)
        try:
            self.gaia_db_new.dataset.removePoint(filename + "1")
        except Exception as exc:
            print(exc)

    def load_point(self, signame: Path) -> Point:
        """Load point data from JSON file."""
        point = Point()

        with signame.open() as sig:
            jsonsig = json.load(sig)
            if jsonsig.get("metadata", {}).get("tags"):
                del jsonsig["metadata"]["tags"]
            yamlsig = yaml.dump(jsonsig)
        point.loadFromString(yamlsig)
        return point

    @staticmethod
    def essentia_analyze(gaia_db, file_path: Path, signame: Path) -> bool:
        """Perform essentia analysis of an audio file."""
        filename = str(file_path)

        env = os.environ.copy()
        try:
            subprocess.check_call(
                [ESSENTIA_EXTRACTOR_PATH, filename, str(signame)],
                env=env,
                stderr=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
            )
            return True

        except subprocess.CalledProcessError:
            # It always returns with a non-zero exit value now :(
            return True

        except Exception as e:
            print(e)
            return False

    def run(self) -> None:
        """Run main loop for gaia analysis thread."""
        print("STARTING GAIA ANALYSIS THREAD")
        while True:
            cmd, filename = self.queue.get()
            print(cmd, filename)
            while filename:
                self.commands[cmd](filename)
                try:
                    cmd, filename = self.queue.get(block=False)
                except Empty:
                    self.gaia_db_new = self.gaia_db_new.transform_and_save()
                    break
                if self.analyzed >= 500:
                    self.analyzed = 0
                    self.gaia_db_new = self.gaia_db_new.transform_and_save()
            print(
                "songs in db after processing queue: %d"
                % self.gaia_db_new.dataset.size()
            )
            for sig_file in Path("/tmp").glob("*.sig"):
                try:
                    sig_file.unlink()
                except OSError as e:
                    print(f"Error: {sig_file}: {e}")

    def analyze_and_wait(self, filenames: Sequence[str]) -> None:
        self.queue_filenames(filenames)
        size = self.queue.qsize()
        while self.queue.qsize() > max(0, size - len(filenames)):
            print("waiting for analysis")
            sleep(10)

    def queue_filenames(self, filenames: Sequence[str]) -> None:
        for name in filenames:
            if name in self.seen:
                continue
            self.seen.add(name)
            self.queue.put((ADD, name))

    def get_best_match(self, filename: str, filenames: List[str]) -> Optional[str]:
        self.queue_filenames([filename] + filenames)
        point = self.gaia_db_new.get(filename + "1") or self.gaia_db_new.get(
            filename + "0"
        )
        if point is None:
            if filenames:
                return filenames[0] or ""

            return ""

        best, best_name = None, None
        for name in filenames:
            if not (other_point := self.contains_or_add(name)[0]):
                continue
            distance = self.gaia_db_new.metric(point, other_point)
            print("%s, %s" % (distance, name))
            if best is None or distance < best:
                best, best_name = distance, name

        return best_name or ""

    def get_ordered_matches(
        self, filename: str, filenames: List[str]
    ) -> List[Tuple[float, str]]:
        self.queue_filenames([filename] + filenames)
        point = self.gaia_db_new.get(filename + "1") or self.gaia_db_new.get(
            filename + "0"
        )
        if point is None:
            if filenames:
                return [(1, filenames[0])]

            return []

        result = sorted(
            (self.gaia_db_new.metric(point, other_point) * 1000, name)
            for name in filenames
            if (other_point := self.contains_or_add(name)[0])
        )

        if not result:
            return [(0, filename) for filename in filenames]

        return result

    def get_tracks(self, filename: str, number: int) -> List[Tuple[float, str]]:
        """Get most similar tracks from the gaia database."""
        if not self.contains_or_add(filename):
            return []
        neighbours = self.get_neighbours(filename, number)
        if neighbours:
            print(f"{len(neighbours)} tracks found, considered {self.factor * number}.")
            print(neighbours[0][0], neighbours[-1][0])
        return neighbours

    def get_neighbours(self, filename: str, number: int) -> List[Tuple[float, str]]:
        """Get a number of nearest neighbours."""
        view = View(self.gaia_db_new.dataset)

        point = self.gaia_db_new.get(filename + "1") or self.gaia_db_new.get(
            filename + "0"
        )
        if point is None:
            return []

        self_name = filename + "0"
        result = []
        while len(result) < number:
            to_get = number * self.factor
            try:
                total = view.nnSearch(point, self.gaia_db_new.metric).get(to_get)

            except Exception as e:
                print(e)
                return []

            result = sorted(
                [
                    (score * 1000, name[:-1])
                    for name, score in total
                    if name.endswith("0") and (name != self_name)
                ]
            )
            if len(total) < to_get:
                return result
            if len(result) < number:
                self.factor += 1
                print(f"Increasing search factor to {self.factor}")

        if len(result) > (number * 2):
            self.factor -= 1
            print(f"Decreasing search factor to {self.factor}")
        return result[:number]

    def contains_or_add(self, filename: str) -> tuple[Point | None, Point | None]:
        """Check if the filename exists in the database, queue it up if not."""
        start_point = self.gaia_db_new.get(filename + "0")
        end_point = self.gaia_db_new.get(filename + "1")
        if not (start_point and end_point):
            print(f"{filename} not found in gaia db starts or ends")
            if filename in self.seen:
                print("already seen")
                return None, None

            self.seen.add(filename)
            self.queue.put((ADD, filename))
            return None, None

        return start_point, end_point


class DatabaseWrapper(Thread):

    """Process to handle all database access."""

    def set_path(self, path: str) -> None:
        """Set the database path."""
        self.path = path

    def set_queue(self, queue: Queue) -> None:
        """Set the queue to use."""
        self.queue = queue

    def run(self) -> None:
        print("STARTING DATABASE WRAPPER THREAD")
        connection = sqlite3.connect(self.path, isolation_level="immediate")
        cursor = connection.cursor()
        commit_needed = False
        while True:
            _, cmd = self.queue.get()
            sql = cmd.sql
            if sql == ("STOP",):
                cmd.result_queue.put(None)
                connection.close()
                break
            result = []
            commit_needed = False
            try:
                cursor.execute(*sql)
            except Exception as e:
                print(e, repr(sql))
            if not sql[0].upper().startswith("SELECT"):
                commit_needed = True
            for row in cursor.fetchall():
                result.append(row)
            if commit_needed:
                connection.commit()
            cmd.result_queue.put(result)


class Pair:

    """A pair of songs."""

    def __init__(self, song1: str, song2: str, song_distance: float):
        self.song1 = song1
        self.song2 = song2
        self.distance = song_distance

    def other(self, song: str) -> str:
        """Return the song paired with @song."""
        if self.song1 == song:
            return self.song2
        return self.song1

    def songs(self) -> List[str]:
        """Return both songs."""
        return [self.song1, self.song2]

    def __eq__(self, other) -> bool:
        return self.song1 == other.song1 and self.song2 == other.song2

    def __repr__(self) -> str:
        return "<Pair {song1}, {song2}: {distance}>".format(
            song1=self.song1, song2=self.song2, distance=self.distance
        )


class Clusterer(object):

    """Build a list of songs in optimized order."""

    def __init__(
        self, songs: Sequence[str], comparison_function: Callable[[str, str], float]
    ):
        self.clusters: List[List[str]] = []
        self.ends: List[str] = []
        self.similarities: List[Pair] = []
        self.build_similarity_matrix(songs, comparison_function)

    def build_similarity_matrix(
        self, songs: Sequence[str], comparison_function: Callable[[str, str], float]
    ) -> None:
        """Build the similarity matrix."""
        for song1 in songs:
            for song2 in songs[songs.index(song1) + 1 :]:
                self.similarities.append(
                    Pair(song1, song2, comparison_function(song1, song2))
                )
        # sort in reverse, since we'll be popping off the end
        self.similarities.sort(reverse=True, key=lambda x: x.distance)

    def join(self, cluster1: List[str], cluster2: List[str]) -> List[str]:
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

    def pop_cluster_ending_in(self, song: str) -> List[str]:
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

        return []

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

    def clean(self, found: str) -> None:
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
        self.db_queue: PriorityQueue = PriorityQueue()
        self._db_wrapper = DatabaseWrapper()
        self._db_wrapper.daemon = True
        self._db_wrapper.set_path(self.db_path)
        self._db_wrapper.set_queue(self.db_queue)
        self._db_wrapper.start()
        self.create_db()
        self.cache_time = 90
        if GAIA:
            self.gaia_queue: LifoQueue = LifoQueue()
            self.gaia_analyser = GaiaAnalysis(self.gaia_queue)
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

    def get_ordered_gaia_tracks_from_list(self, filename, filenames):
        start_time = time()
        tracks = self.gaia_analyser.get_ordered_matches(filename, filenames)
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

    def get_track_from_artist_and_title(self, artist_name: str, title: str):
        """Get track information from the database."""
        artist_id = self.get_artist(artist_name)[0]
        sql = (
            "SELECT * FROM tracks WHERE artist = ? AND title = ?;",
            (artist_id, title),
        )
        command = self.get_sql_command(sql, priority=3)
        for row in command.result_queue.get():
            return row
        sql2 = ("INSERT INTO tracks (artist, title) VALUES (?, ?);", (artist_id, title))
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
            (track_id, track_id),
        )
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
            (artist_id, artist_id),
        )
        command = self.get_sql_command(sql, priority=0)
        return command.result_queue.get()

    def get_artist_match(self, artist1, artist2):
        """Get artist match score from database."""
        sql = (
            "SELECT match FROM artist_2_artist WHERE artist1 = ?" " AND artist2 = ?;",
            (artist1, artist2),
        )
        command = self.get_sql_command(sql, priority=2)
        for row in command.result_queue.get():
            return row[0]
        return 0

    def get_track_match(self, track1, track2):
        """Get track match score from database."""
        sql = (
            "SELECT match FROM track_2_track WHERE track1 = ? AND track2 = ?;",
            (track1, track2),
        )
        command = self.get_sql_command(sql, priority=2)
        for row in command.result_queue.get():
            return row[0]
        return 0

    def update_artist_match(self, artist1, artist2, match):
        """Write match score to the database."""
        self.execute_sql(
            (
                "UPDATE artist_2_artist SET match = ? WHERE artist1 = ? AND"
                " artist2 = ?;",
                (match, artist1, artist2),
            ),
            priority=10,
        )

    def update_track_match(self, track1, track2, match):
        """Write match score to the database."""
        self.execute_sql(
            (
                "UPDATE track_2_track SET match = ? WHERE track1 = ? AND"
                " track2 = ?;",
                (match, track1, track2),
            ),
            priority=10,
        )

    def insert_artist_match(self, artist1, artist2, match):
        """Write match score to the database."""
        self.execute_sql(
            (
                "INSERT INTO artist_2_artist (artist1, artist2, match) VALUES"
                " (?, ?, ?);",
                (artist1, artist2, match),
            ),
            priority=10,
        )

    def insert_track_match(self, track1, track2, match):
        """Write match score to the database."""
        self.execute_sql(
            (
                "INSERT INTO track_2_track (track1, track2, match) VALUES"
                " (?, ?, ?);",
                (track1, track2, match),
            ),
            priority=10,
        )

    def update_artist(self, artist_id):
        """Write artist information to the database."""
        self.execute_sql(
            (
                "UPDATE artists SET updated = DATETIME('now') WHERE id = ?;",
                (artist_id,),
            ),
            priority=10,
        )

    def update_track(self, track_id):
        """Write track information to the database."""
        self.execute_sql(
            ("UPDATE tracks SET updated = DATETIME('now') WHERE id = ?", (track_id,)),
            priority=10,
        )

    def update_similar_artists(self, artists_to_update):
        """Write similar artist information to the database."""
        for artist_id, similar in list(artists_to_update.items()):
            for artist in similar:
                row = self.get_artist(artist["artist"])
                if row:
                    id2 = row[0]
                    if self.get_artist_match(artist_id, id2):
                        self.update_artist_match(artist_id, id2, artist["score"])
                        continue
                    self.insert_artist_match(artist_id, id2, artist["score"])
            self.update_artist(artist_id)

    def update_similar_tracks(self, tracks_to_update):
        """Write similar track information to the database."""
        for track_id, similar in list(tracks_to_update.items()):
            for track in similar:
                row = self.get_track_from_artist_and_title(
                    track["artist"], track["title"]
                )
                if row:
                    id2 = row[0]
                    if self.get_track_match(track_id, id2):
                        self.update_track_match(track_id, id2, track["score"])
                        continue
                    self.insert_track_match(track_id, id2, track["score"])
            self.update_track(track_id)

    def create_db(self):
        """Set up a database for the artist and track similarity scores."""
        self.execute_sql(
            (
                "CREATE TABLE IF NOT EXISTS artists (id INTEGER PRIMARY KEY, name"
                " VARCHAR(100), updated DATE, UNIQUE(name));",
            ),
            priority=0,
        )
        self.execute_sql(
            (
                "CREATE TABLE IF NOT EXISTS artist_2_artist (artist1 INTEGER,"
                " artist2 INTEGER, match INTEGER, UNIQUE(artist1, artist2));",
            ),
            priority=0,
        )
        self.execute_sql(
            (
                "CREATE TABLE IF NOT EXISTS tracks (id INTEGER PRIMARY KEY, artist"
                " INTEGER, title VARCHAR(100), updated DATE, "
                "UNIQUE(artist, title));",
            ),
            priority=0,
        )
        self.execute_sql(
            (
                "CREATE TABLE IF NOT EXISTS track_2_track (track1 INTEGER, track2"
                " INTEGER, match INTEGER, UNIQUE(track1, track2));",
            ),
            priority=0,
        )
        self.execute_sql(
            ("CREATE INDEX IF NOT EXISTS a2aa1x ON artist_2_artist " "(artist1);",),
            priority=0,
        )
        self.execute_sql(
            ("CREATE INDEX IF NOT EXISTS a2aa2x ON artist_2_artist " "(artist2);",),
            priority=0,
        )
        self.execute_sql(
            ("CREATE INDEX IF NOT EXISTS t2tt1x ON track_2_track (track1);",),
            priority=0,
        )
        self.execute_sql(
            ("CREATE INDEX IF NOT EXISTS t2tt2x ON track_2_track (track2);",),
            priority=0,
        )

    def delete_orphan_artist(self, artist):
        """Delete artists that have no tracks."""
        sql = (
            "SELECT artists.id FROM artists WHERE artists.name = ? AND "
            "artists.id NOT IN (SELECT tracks.artist from tracks);",
            (artist,),
        )
        command = self.get_sql_command(sql, priority=10)
        for row in command.result_queue.get():
            artist_id = row[0]
            self.execute_sql(
                (
                    "DELETE FROM artist_2_artist WHERE artist1 = ? OR artist2 = " "?;",
                    (artist_id, artist_id),
                ),
                priority=10,
            )
            self.execute_sql(
                ("DELETE FROM artists WHERE id = ?", (artist_id,)), priority=10
            )

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

    def get_best_match(self, filename, filenames):
        if not GAIA:
            return

        return self.gaia_analyser.get_best_match(filename, filenames)


class SimilarityService(dbus.service.Object):

    """Service that can be queried for similar songs."""

    def __init__(self, bus_name, object_path):
        self.similarity = Similarity()
        dbus.service.Object.__init__(self, bus_name=bus_name, object_path=object_path)
        self.loop = GObject.MainLoop()

    @method(dbus_interface=IFACE, in_signature="s")
    def remove_track_by_filename(self, filename):
        """Remove tracks from database."""
        self.similarity.remove_track_by_filename(filename)

    @method(dbus_interface=IFACE, in_signature="s")
    def analyze_track(self, filename):
        """Perform analysis of a track."""
        self.similarity.analyze_track(filename)

    @method(dbus_interface=IFACE, in_signature="as")
    def analyze_tracks(self, filenames):
        """Perform analysis of multiple tracks."""
        self.similarity.analyze_tracks([filename for filename in filenames])

    @method(dbus_interface=IFACE, in_signature="sx", out_signature="a(xs)")
    def get_ordered_gaia_tracks(self, filename, number):
        """Get similar tracks by gaia acoustic analysis."""
        return self.similarity.get_ordered_gaia_tracks(filename, number)

    @method(dbus_interface=IFACE, in_signature="sas", out_signature="a(xs)")
    def get_ordered_gaia_tracks_from_list(self, filename, filenames):
        return self.similarity.get_ordered_gaia_tracks_from_list(
            filename, [filename for filename in filenames]
        )

    @method(dbus_interface=IFACE, out_signature="b")
    def has_gaia(self):
        """Get gaia installation status."""
        return GAIA

    @method(dbus_interface=IFACE, in_signature="sas", out_signature="s")
    def get_best_match(self, filename, filenames):
        return self.similarity.get_best_match(filename, filenames)

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
