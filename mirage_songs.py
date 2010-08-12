from plugins.songsmenu import SongsMenuPlugin
from autoqueue import SimilarityData, daemon


def get_title(song):
    """return lowercase UNICODE title of song"""
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

    def plugin_songs(self, songs):
        l = len(songs)
        for i, song in enumerate(songs):
            artist_name = song.comma("artist").lower()
            title = get_title(song)
            print "%03d/%03d %s - %s" % (i + 1, l, artist_name, title)
            filename = song("~filename")
            daemon.stdin.write('analyze %s\n' % filename)
        print "done"
