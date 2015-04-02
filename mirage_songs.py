"""Acoustic analysis songs plugin."""

import dbus
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib
from quodlibet.plugins.songsmenu import SongsMenuPlugin

DBusGMainLoop(set_as_default=True)


def no_op(*args, **kwargs):
    pass


def get_title(song):
    """Return lowercase UNICODE title of song."""
    version = song.comma("version").lower()
    title = song.comma("title").lower()
    if version:
        return "%s (%s)" % (title, version)
    return title


class AnalyzeSongsPlugin(SongsMenuPlugin):

    """Acoustic song analysis."""

    PLUGIN_ID = "Acoustic Analysis"
    PLUGIN_NAME = _("Acoustic Analysis")  # noqa
    PLUGIN_DESC = _("Perform acoustic analysis of the selected songs.")  # noqa
    PLUGIN_ICON = "gtk-find-and-replace"
    PLUGIN_VERSION = "0.1"

    def __init__(self, *args):
        SongsMenuPlugin.__init__(self, *args)
        bus = dbus.SessionBus()
        sim = bus.get_object(
            'org.autoqueue', '/org/autoqueue/Similarity')
        self.similarity = dbus.Interface(
            sim, dbus_interface='org.autoqueue.SimilarityInterface')

    def plugin_songs(self, songs):
        """Add the work to the coroutine pool."""
        GLib.idle_add(self.doit, songs)

    def doit(self, songs):
        filenames = []
        for song in songs:
            filename = song('~filename')
            if not isinstance(filename, unicode):
                try:
                    filename = unicode(filename, 'utf-8')
                except:
                    print "Could not decode filename: %r" % song('~filename')
                    continue
            filenames.append(filename)
        self.similarity.analyze_tracks(
            filenames, reply_handler=no_op, error_handler=no_op)
