"""Mirage integration for autoqueue.
version 0.3

Copyright 2007-2010 Eric Casteleijn <thisfred@gmail.com>,
                    Paolo Tranquilli <redsun82@gmail.com>


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

import os, sys
import cPickle as pickle
from cStringIO import StringIO
import sqlite3
import xdg.BaseDirectory
from mirage import (
    Mir, MatrixDimensionMismatchException, MfccFailedException,
    ScmsConfiguration, distance)

DEBUG = True
NEIGHBOURS = 10


class Db(object):
    def __init__(self, path=None, connection=None):
        if path is None:
            data_dir = os.path.join(
                xdg.BaseDirectory.xdg_data_home, 'autoqueue')
            if not os.path.exists(data_dir):
                os.makedirs(data_dir)
            self.dbpath = os.path.join(data_dir, "similarity.db")
        else:
            self.dbpath = path
        self.create_db()
        self.connection = connection
        self.mir = Mir()
        self._cache = []

    def create_db(self):
        """ Set up a database for the artist and track similarity scores
        """
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

    def close_database_connection(self, connection):
        if self.dbpath == ':memory:':
            return
        connection.close()

    def get_database_connection(self):
        if self.dbpath == ':memory:':
            if not self.connection:
                self.connection = sqlite3.connect(':memory:')
                self.connection.text_factory = str
            return self.connection
        connection = sqlite3.connect(
            self.dbpath, timeout=5.0, isolation_level="immediate")
        connection.text_factory = str
        return connection

    def add_artist(self, artist_name):
        connection = self.get_database_connection()
        connection.execute(
            "INSERT INTO artists (name) VALUES (?)", (artist_name,))
        connection.commit()
        self.close_database_connection(connection)

    def update_artist(self, artist_id):
        connection = self.get_database_connection()
        connection.execute(
            "UPDATE artists SET updated = DATETIME('now') WHERE id = ?",
            (artist_id,))
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
            'DELETE FROM artist_2_artist WHERE artist1 NOT IN (SELECT '
            'artists.id FROM artists) OR artist2 NOT IN (SELECT artists.id '
            'FROM artists);')
        connection.commit()
        connection.close()

    def add_track(self, artist_id, title):
        connection = self.get_database_connection()
        connection.execute(
            "INSERT INTO tracks (artist, title) VALUES (?, ?)",
            (artist_id, title))
        connection.commit()
        self.close_database_connection(connection)

    def update_track(self, track_id):
        connection = self.get_database_connection()
        connection.execute(
            "UPDATE tracks SET updated = DATETIME('now') WHERE id = ?",
            (track_id,))
        connection.commit()
        self.close_database_connection(connection)

    def update_artist_match(self, artist1, artist2, match):
        connection = self.get_database_connection()
        connection.execute(
            "UPDATE artist_2_artist SET match = ? WHERE artist1 = ? AND"
            " artist2 = ?",
            (match, artist1, artist2))
        connection.commit()
        self.close_database_connection(connection)

    def update_track_match(self, track1, track2, match):
        connection = self.get_database_connection()
        connection.execute(
            "UPDATE track_2_track SET match = ? WHERE track1 = ? AND"
            " track2 = ?",
            (match, track1, track2))
        connection.commit()
        self.close_database_connection(connection)

    def insert_artist_match(self, artist1, artist2, match):
        connection = self.get_database_connection()
        connection.execute(
            "INSERT INTO artist_2_artist (artist1, artist2, match) VALUES"
            " (?, ?, ?)",
            (artist1, artist2, match))
        connection.commit()
        self.close_database_connection(connection)

    def insert_track_match(self, track1, track2, match):
        connection = self.get_database_connection()
        connection.execute(
            "INSERT INTO track_2_track (track1, track2, match) VALUES"
            " (?, ?, ?)",
            (track1, track2, match))
        connection.commit()
        self.close_database_connection(connection)

    def add_file(self, filename, scms):
        connection = self.get_database_connection()
        connection.execute("INSERT INTO mirage (filename, scms) VALUES (?, ?)",
                       (filename,
                        sqlite3.Binary(instance_to_picklestring(scms))))
        connection.commit()
        self.close_database_connection(connection)
        if self._cache:
            file_id = self.get_file_id(filename)
            self._cache.append((scms, file_id))

    def remove_file(self, trackid):
        connection = self.get_database_connection()
        connection.execute("DELETE FROM mirage WHERE trackid = ?", (trackid,))
        connection.commit()
        self.close_database_connection(connection)

    def remove_files(self, trackids):
        connection = self.get_database_connection()
        connection.execute("DELETE FROM mirage WHERE trackid IN (%s);" % (
            ','.join(trackids),))
        connection.commit()
        self.close_database_connection(connection)

    def prune_filenames(self, filenames):
        connection = self.get_database_connection()
        connection.execute(
            'DELETE FROM mirage WHERE filename IN (%s);' % ','.join(filenames))
        connection.execute(
            'DELETE FROM distance WHERE track_1 NOT IN (SELECT trackid '
            'FROM mirage) OR track_2 NOT IN (SELECT trackid FROM '
            'mirage);')
        connection.commit()
        self.close_database_connection(connection)

    def prune_delete(self, track_ids):
        track_ids = ','.join(track_ids)
        connection = self.get_database_connection()
        connection.execute(
            'DELETE FROM track_2_track WHERE track1 IN (%s) OR track2 IN (%s);'
            % (track_ids, track_ids))
        connection.execute(
            'DELETE FROM tracks WHERE id IN (%s);' % track_ids)
        connection.commit()
        self.close_database_connection(connection)

    def get_file(self, filename):
        connection = self.get_database_connection()
        rows = connection.execute(
            "SELECT trackid, scms FROM mirage WHERE filename = ?", (filename,))
        for row in rows:
            self.close_database_connection(connection)
            return (row[0], instance_from_picklestring(row[1]))
        self.close_database_connection(connection)
        return None

    def get_or_add_file(self, filename):
        trackid_scms = self.get_file(filename)
        if not trackid_scms:
            try:
                scms = self.mir.analyze(filename)
            except (MatrixDimensionMismatchException, MfccFailedException):
                return
            self.add_file(filename, scms)
            trackid = self.get_file_id(filename)
        else:
            trackid, scms = trackid_scms
        return trackid, scms

    def get_file_id(self, filename):
        connection = self.get_database_connection()
        rows = connection.execute(
            "SELECT trackid FROM mirage WHERE filename = ?", (filename,))
        for row in rows:
            self.close_database_connection(connection)
            return row[0]
        self.close_database_connection(connection)
        return None

    def get_ids_for_filenames(self, filenames):
        connection = self.get_database_connection()
        rows = connection.execute(
            'SELECT trackid FROM mirage WHERE filename IN (%s)' %
            (','.join(['"%s"' % filename for filename in filenames]), ))
        result = [row[0] for row in rows]
        self.close_database_connection(connection)
        return result

    def get_file_scms(self, track_id):
        connection = self.get_database_connection()
        rows = connection.execute(
            "SELECT scms FROM mirage WHERE trackid = ?", (track_id,))
        for row in rows:
            self.close_database_connection(connection)
            return row[0]
        self.close_database_connection(connection)
        return None

    def has_scores(self, trackid, no=20):
        min_connections = no
        connection = self.get_database_connection()
        cursor = connection.execute(
            'SELECT COUNT(*) FROM distance WHERE track_1 = ?',
            (trackid,))
        outgoing_connections = cursor.fetchone()[0]
        self.close_database_connection(connection)
        if outgoing_connections < min_connections:
            return False
        connection = self.get_database_connection()
        cursor = connection.execute(
            "SELECT COUNT(track_1) FROM distance WHERE track_2 = ? AND "
            "distance < (SELECT MAX(distance) FROM distance WHERE track_1 = ?);"
            , (trackid, trackid))
        incoming_connections = cursor.fetchone()[0]
        self.close_database_connection(connection)
        if incoming_connections > outgoing_connections:
            return False
        return True

    def get_files(self, exclude_ids=None):
        if not exclude_ids:
            exclude_ids = []
        if not self._cache:
            connection = self.get_database_connection()
            rows = connection.execute("SELECT scms, trackid FROM mirage;")
            for row in rows:
                self._cache.append((instance_from_picklestring(row[0]), row[1]))
            self.close_database_connection(connection)
        for row in self._cache:
            if row[1] not in exclude_ids:
                yield row

    def get_all_file_ids(self):
        connection = self.get_database_connection()
        rows = connection.execute("SELECT trackid FROM mirage")
        result = [row[0] for row in rows]
        self.close_database_connection(connection)
        return result

    def reset(self):
        connection = self.get_database_connection()
        connection.execute("DELETE FROM mirage")
        connection.commit()
        self.close_database_connection(connection)

    def add_neighbours(self, trackid, scms, exclude_ids=None, neighbours=20):
        # add more than we need so we don't have to recompute so often
        neighbours *= 4
        connection = self.get_database_connection()
        connection.execute(
            "DELETE FROM distance WHERE track_1 = ?", (trackid,))
        connection.commit()
        self.close_database_connection(connection)
        if not exclude_ids:
            exclude_ids = []
        c = ScmsConfiguration(20)
        best = []
        for other_scms, otherid in self.get_files(exclude_ids=exclude_ids):
            if trackid == otherid:
                continue
            dist = int(distance(scms, other_scms, c) * 1000)
            if len(best) >= neighbours:
                if dist > best[-1][0]:
                    continue
            best.append((dist, otherid))
            best.sort()
            while len(best) > neighbours:
                best.pop()
        added = 0
        if best:
            connection = self.get_database_connection()
            while best:
                added += 1
                dist, track_2 = best.pop()
                connection.execute(
                    "INSERT INTO distance (distance, track_1, track_2) "
                    "VALUES (?, ?, ?)", (dist, trackid, track_2))
            connection.commit()
            self.close_database_connection(connection)
        print "%s connections added." % str(added)

    def compare(self, id1, id2):
        c = ScmsConfiguration(20)
        t1 = self.get_file(id1)[1]
        t2 = self.get_file(id2)[1]
        return int(distance(t1, t2, c) * 1000)

    def get_filename(self, trackid):
        connection = self.get_database_connection()
        rows = connection.execute(
            'SELECT filename FROM mirage WHERE trackid = ?', (trackid, ))
        filename = None
        for row in rows:
            try:
                filename = unicode(row[0], 'utf-8')
            except UnicodeDecodeError:
                break
            break
        connection.close()
        return filename

    def get_neighbours(self, trackid):
        connection = self.get_database_connection()
        neighbours = [row for row in connection.execute(
            "SELECT distance, track_2 FROM distance WHERE track_1 = ? "
            "ORDER BY distance ASC",
            (trackid,))]
        self.close_database_connection(connection)
        return neighbours


def instance_from_picklestring(picklestring):
    f = StringIO(picklestring)
    return pickle.load(f)

def instance_to_picklestring(instance):
    f = StringIO()
    pickle.dump(instance, f)
    return f.getvalue()

def parse_command(line):
    split = line.split(' ')
    return split[0], ' '.join(split[1:]).strip()

def readlines():
    lines = []
    line = sys.stdin.readline()
    while line != 'done\n':
        lines.append(line.strip())
        line = sys.stdin.readline()
    return lines

def main():
    db = Db()
    while True:
        line = sys.stdin.readline()
        if line.startswith('exit'):
            sys.exit(0)
        if line.startswith('prune_filenames'):
            filenames = readlines()
            db.prune_filenames(filenames)
            continue
        if line.startswith('create_db'):
            db.create_db()
            continue
        command, args = parse_command(line)
        if command == 'analyze':
            filename = args
            track_id, scms = db.get_or_add_file(filename)
        elif command == 'add_neighbours':
            filename = args
            excludes = readlines()
            track_id, scms = db.get_or_add_file(filename)
            if excludes:
                exclude_ids = db.get_ids_for_filenames(excludes)
            else:
                exclude_ids = []
            if not db.has_scores(track_id, no=NEIGHBOURS):
                db.add_neighbours(
                    track_id, scms, exclude_ids=exclude_ids,
                    neighbours=NEIGHBOURS)
        elif command == 'add_artist':
            db.add_artist(args)
        elif command == 'update_artist':
            db.update_artist(args)
        elif command == 'add_track':
            split = args.split(' ')
            artist_id = split[0]
            title = ' '.join(split[1:])
            db.add_track(artist_id, title)
        elif command == 'update_artist_match':
            db.update_artist_match(*args.split())
        elif command == 'update_track_match':
            db.update_track_match(*args.split())
        elif command == 'insert_artist_match':
            db.insert_artist_match(*args.split())
        elif command == 'insert_track_match':
            db.insert_track_match(*args.split())
        elif command == 'delete_orphans':
            db.delete_orphan_artists(args.split())

if __name__ == '__main__':
    main()
