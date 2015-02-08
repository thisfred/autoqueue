""" Add selected songs to the queue in ideal order."""

import dbus
from quodlibet import widgets
from dbus.mainloop.glib import DBusGMainLoop
from quodlibet.plugins.songsmenu import SongsMenuPlugin

NO_OP = lambda *a, **kw: None

DBusGMainLoop(set_as_default=True)

# for backwards compatibility with QL revisions prior to 0d807ac2a1f9
try:
    from quodlibet import app
    NEW_QL = True
except ImportError:
    from quodlibet.widgets import main
    NEW_QL = False

def get_title(song):
    """Return lowercase UNICODE title of song."""
    version = song.comma("version").lower()
    title = song.comma("title").lower()
    if version:
        return "%s (%s)" % (title, version)
    return title


class MiximizePlugin(SongsMenuPlugin):
    """Add selected songs to the queue in ideal order."""

    PLUGIN_ID = "MirageMiximize"
    PLUGIN_NAME = _("Miximize (mirage)")
    PLUGIN_DESC = _("Add selected songs to the queue in ideal order based on"
                    " acoustic similarity.")
    PLUGIN_ICON = "gtk-find-and-replace"
    PLUGIN_VERSION = "0.1"

    def player_enqueue(self, indices):
        """Put the song at the end of the queue."""
        playlist = NEW_QL and app.window.playlist or main.playlist
        playlist.enqueue(
            [self._songs[index] for index in indices])
        self._songs = None

    def plugin_songs(self, songs):
        """Send songs to dbus similarity service."""
        bus = dbus.SessionBus()
        self._songs = songs
        sim = bus.get_object(
            'org.autoqueue', '/org/autoqueue/Similarity',
            follow_name_owner_changes=True)
        similarity = dbus.Interface(
            sim, dbus_interface='org.autoqueue.SimilarityInterface')
        print [song['~filename'] for song in songs]
        similarity.miximize(
            [song['~filename'] for song in songs],
            reply_handler=self.player_enqueue, error_handler=NO_OP)
