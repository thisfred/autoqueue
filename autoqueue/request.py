import os
import sqlite3

from autoqueue.utilities import player_get_data_dir


class Requests:
    def __init__(self):
        self.path = os.path.join(player_get_data_dir(), "requests.db")
        self.connection = sqlite3.connect(self.path, isolation_level="immediate")
        self.cursor = self.connection.cursor()
        self.create_table()
        self.cached_song = None

    def create_table(self):
        self.cursor.execute(
            "CREATE TABLE IF NOT EXISTS requests (id INTEGER PRIMARY KEY, "
            "filename STRING, added STRING DEFAULT CURRENT_TIMESTAMP);"
        )
        self.connection.commit()

    def add(self, filename):
        self.cursor.execute("INSERT INTO requests (filename) VALUES (?);", (filename,))
        self.connection.commit()

    def has(self, filename):
        self.cursor.execute(
            "SELECT 1 FROM requests WHERE filename = ? LIMIT 1;", (filename,)
        )
        for _ in self.cursor.fetchall():
            return True

        return False

    def get_requests(self):
        self.cursor.execute("SELECT filename FROM requests;")
        return [row[0] for row in self.cursor.fetchall()]

    def pop(self, filename):
        self.cursor.execute(
            "DELETE FROM requests WHERE filename = ?;",
            (filename,),
        )
        self.connection.commit()
