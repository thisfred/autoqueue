"""Add selected songs to the queue in ideal order."""
from __future__ import print_function

import dbus
from dbus.mainloop.glib import DBusGMainLoop
from quodlibet import app
from quodlibet.plugins.songsmenu import SongsMenuPlugin


def no_op(*args, **kwargs):
    pass


DBusGMainLoop(set_as_default=True)


def get_title(song):
    """Return lowercase UNICODE title of song."""
    version = song.comma("version").lower()
    title = song.comma("title").lower()
    if version:
        return "%s (%s)" % (title, version)
    return title


class MiximizePlugin(SongsMenuPlugin):

    """Add selected songs to the queue in ideal order."""

    PLUGIN_ID = "Miximize"
    PLUGIN_NAME = _("Autoqueue Miximize")
    PLUGIN_DESC = _("Add selected songs to the queue in ideal order based on"
                    " acoustic similarity.")
    PLUGIN_ICON = "gtk-find-and-replace"
    PLUGIN_VERSION = "0.1"

    def player_enqueue(self, indices):
        """Put the song at the end of the queue."""
        app.window.playlist.enqueue([self._songs[index] for index in indices])
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
        print([song['~filename'] for song in songs])
        similarity.miximize(
            [song['~filename'] for song in songs],
            reply_handler=self.player_enqueue, error_handler=no_op)
