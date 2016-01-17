import os
import sqlite3

from autoqueue.utilities import player_get_data_dir


class Requests(object):

    def __init__(self):
        self.path = os.path.join(player_get_data_dir(), 'requests.db')
        self.connection = sqlite3.connect(
            self.path, isolation_level='immediate')
        self.cursor = self.connection.cursor()
        self.create_table()
        self.cached_song = None

    @staticmethod
    def _decode(filename):
        if isinstance(filename, unicode):
            return filename

        try:
            return filename.decode('utf-8')

        except UnicodeDecodeError:
            pass

    def create_table(self):
        self.cursor.execute(
            "CREATE TABLE IF NOT EXISTS requests (id INTEGER PRIMARY KEY, "
            "filename STRING);")
        self.connection.commit()

    def add(self, filename):
        filename = self._decode(filename)
        if filename is None:
            return
        self.cursor.execute(
            "INSERT INTO requests (filename) VALUES (?);", (filename,))
        self.connection.commit()

    def has(self, filename):
        filename = self._decode(filename)
        if filename is None:
            return
        self.cursor.execute(
            "SELECT 1 FROM requests WHERE filename = ? LIMIT 1;",
            (filename,))
        for _ in self.cursor.fetchall():
            return True

        return False

    def get_first(self):
        self.cursor.execute(
            "SELECT filename FROM requests ORDER BY id DESC LIMIT 1;")
        for row in self.cursor.fetchall():
            return row[0]

    def get_requests(self):
        self.cursor.execute("SELECT filename FROM requests;")
        return [row[0] for row in self.cursor.fetchall()]

    def pop(self, filename):
        filename = self._decode(filename)
        if filename is None:
            return
        self.cursor.execute(
            "DELETE FROM requests WHERE filename = ? ORDER BY id LIMIT 1;",
            (filename,))
        self.connection.commit()
