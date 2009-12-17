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
            file_id = self.get_file_id(filename)
            if db.has_scores(file_id):
                continue
            scms = db.get_track(file_id)
            if not scms:
                try:
                    scms = self.mir.analyze(filename)
                except:
                    return
                db.add_track(file_id, scms)
            yield
        yield
        print "done"

    def plugin_songs(self, songs):
        fid = "mirage_songs" + str(datetime.now())
        copool.add(self.do_stuff, songs, funcid=fid)

    def get_file_id(self, filename):
        """get file id from the database"""
        connection = sqlite3.connect(
            self.dbpath, timeout=5.0, isolation_level="immediate")
        filename = filename[-300:]
        rows = connection.execute(
            "SELECT * FROM files WHERE filename = ?", (filename,))
        for row in rows:
            connection.close()
            return row[0]
        connection.execute(
            "INSERT INTO files (filename) VALUES (?)",
            (filename,))
        connection.commit()
        rows = connection.execute(
            "SELECT * FROM files WHERE filename = ?", (filename,))
        for row in rows:
            connection.close()
            return row[0]
        connection.close()

