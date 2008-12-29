import sqlite3, os
import const
from plugins.songsmenu import SongsMenuPlugin
from autoqueue.mirage import Mir, MirDb
from quodlibet.util import copool
from autoqueue.autoqueue import get_track, get_artist_tracks

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

    def player_get_userdir(self):
        """get the application user directory to store files"""
        try:
            return const.USERDIR
        except AttributeError:
            return const.DIR

    def do_stuff(self, songs):
        dbpath = os.path.join(self.player_get_userdir(), "similarity.db")
        db = MirDb(dbpath)
        l = len(songs)
        for i, song in enumerate(songs):
            artist_name = song.comma("artist").lower()
            title = get_title(song)
            print "%03d/%03d %s - %s" % (i + 1, l, artist_name, title)
            filename = song("~filename")
            track = get_track(artist_name, title)
            track_id, artist_id = track[0], track[1]
            if db.get_track(track_id):
                continue
            exclude_ids = get_artist_tracks(artist_id)
            try:
                scms = self.mir.analyze(filename)
            except:
                return
            db.add_and_compare(track_id, scms,exclude_ids=exclude_ids)
            yield True
        print "done"
        
    def plugin_songs(self, songs):
        copool.add(self.do_stuff, songs)
