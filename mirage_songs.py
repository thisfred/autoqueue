
from datetime import datetime
from plugins.songsmenu import SongsMenuPlugin
from mirage import Mir, Db
from autoqueue import SimilarityData

from quodlibet.util import copool

import faulthandler
import widgets

faulthandler.enable()


def get_title(song):
    """Return lowercase UNICODE title of song."""
    version = song.comma("version").lower()
    title = song.comma("title").lower()
    if version:
        return "%s (%s)" % (title, version)
    return title


class MirageSongsPlugin(SongsMenuPlugin, SimilarityData):
    PLUGIN_ID = "Mirage Analysis"
    PLUGIN_NAME = _("Mirage Analysis")
    PLUGIN_DESC = _("Perform Mirage Analysis of the selected songs.")
    PLUGIN_ICON = "gtk-find-and-replace"
    PLUGIN_VERSION = "0.1"

    def __init__(self, *args):
        super(MirageSongsPlugin, self).__init__(*args)

    @property
    def mir(self):
        if widgets.main is None:
            reload(widgets)
        if hasattr(widgets.main, 'mir'):
            return widgets.main.mir
        widgets.main.mir = Mir()
        return widgets.main.mir

    def do_stuff(self, songs):
        """Do the actual work."""
        db = Db(self.get_db_path())
        l = len(songs)
        for i, song in enumerate(songs):
            artist_name = song.comma("artist").lower()
            title = get_title(song)
            print "%03d/%03d %s - %s" % (i + 1, l, artist_name, title)
            filename = song("~filename")
            trackid_scms = db.get_track(filename)
            if not trackid_scms:
                scms = self.mir.analyze(filename)
                db.add_track(filename, scms)
            yield
        print "done"

    def plugin_songs(self, songs):
        """Add the work to the coroutine pool."""
        fid = "mirage_songs" + str(datetime.now())
        copool.add(self.do_stuff, songs, funcid=fid)

