"""Add selected songs to the queue in ideal order based on mirage distances."""

import dbus
import widgets
from dbus.mainloop.glib import DBusGMainLoop
from plugins.songsmenu import SongsMenuPlugin
NO_OP = lambda *a, **kw: None

DBusGMainLoop(set_as_default=True)


def get_title(song):
    """Return lowercase UNICODE title of song."""
    version = song.comma("version").lower()
    title = song.comma("title").lower()
    if version:
        return "%s (%s)" % (title, version)
    return title


class MirageMiximizePlugin(SongsMenuPlugin):
    """Add selected songs to the queue in ideal order."""

    PLUGIN_ID = "Mirage Miximize"
    PLUGIN_NAME = _("Mirage Miximize")
    PLUGIN_DESC = _("Add selected songs to the queue in ideal order based on"
                    " mirage distances.")
    PLUGIN_ICON = "gtk-find-and-replace"
    PLUGIN_VERSION = "0.1"

    def player_enqueue(self, filenames):
        """Put the song at the end of the queue."""
        if widgets.main is None:
            reload(widgets)
        widgets.main.playlist.enqueue(
            (self._songs[filename] for filename in filenames))
        self._songs = None

    def plugin_songs(self, songs):
        """Send songs to dbus similarity service."""
        bus = dbus.SessionBus()
        self._songs = dict(((song('~filename'), song) for song in songs))
        sim = bus.get_object(
            'org.autoqueue', '/org/autoqueue/Similarity',
            follow_name_owner_changes=True)
        similarity = dbus.Interface(
            sim, dbus_interface='org.autoqueue.SimilarityInterface')
        similarity.miximize(
            songs, reply_handler=self.player_enqueue, error_handler=NO_OP)
