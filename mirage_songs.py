import sqlite3, os
import const
from datetime import datetime
from plugins.songsmenu import SongsMenuPlugin
from mirage import Mir, Db
from quodlibet.util import copool


def get_title(song):
    """return lowercase UNICODE title of song"""
    version = song.comma("version").lower()
    title = song.comma("title").lower()
    if version:
        return "%s (%s)" % (title, version)
    return title


class MirageSongsPlugin(SongsMenuPlugin):
    PLUGIN_ID = "Mirage Analysis"
    PLUGIN_NAME = _("Mirage Analysis")
    PLUGIN_DESC = _("Perform Mirage Analysis of the selected songs.")
    PLUGIN_ICON = "gtk-find-and-replace"
    PLUGIN_VERSION = "0.1"

    def __init__(self, *args):
        super(MirageSongsPlugin, self).__init__(*args)
        self.mir = Mir()
        self.dbpath = os.path.join(self.player_get_userdir(), "similarity.db")

    def player_get_userdir(self):
        """get the application user directory to store files"""
        try:
            return const.USERDIR
        except AttributeError:
            return const.DIR

    def do_stuff(self, songs):
        db = Db(self.dbpath)
        l = len(songs)
        for i, song in enumerate(songs):
            artist_name = song.comma("artist").lower()
            title = get_title(song)
            print "%03d/%03d %s - %s" % (i + 1, l, artist_name, title)
            filename = song("~filename")
            track = self.get_track(artist_name, title)
            track_id, artist_id = track[0], track[1]
            if db.has_scores(track_id):
                continue
            scms = db.get_track(track_id)
            if not scms:
                try:
                    scms = self.mir.analyze(filename)
                except:
                    return
                db.add_track(track_id, scms)
            yield
        yield
        print "done"

    def plugin_songs(self, songs):
        fid = "mirage_songs" + str(datetime.now())
        copool.add(self.do_stuff, songs, funcid=fid)

    def get_track(self, artist_name, title):
        """get track information from the database"""
        connection = sqlite3.connect(
            self.dbpath, timeout=5.0, isolation_level="immediate")
        connection.text_factory = str
        title = title.encode("UTF-8")
        artist_id = self.get_artist(artist_name)[0]
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
            connection.close()
            return row
        connection.close()

    def get_artist(self, artist_name):
        """get artist information from the database"""
        connection = sqlite3.connect(
            self.dbpath, timeout=5.0, isolation_level="immediate")
        connection.text_factory = str
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
            connection.close()
            return row
        connection.close()

    def get_artist_tracks(self, artist_id):
        connection = sqlite3.connect(
            self.dbpath, timeout=5.0, isolation_level="immediate")
        rows = connection.execute(
            "SELECT tracks.id FROM tracks INNER JOIN artists"
            " ON tracks.artist = artists.id WHERE artists.id = ?",
            (artist_id, ))
        return [row[0] for row in rows]
