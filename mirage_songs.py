"""Mirage songs plugin."""

import dbus
from gi.repository import GLib
from quodlibet.plugins.songsmenu import SongsMenuPlugin
from dbus.mainloop.glib import DBusGMainLoop
DBusGMainLoop(set_as_default=True)

NO_OP = lambda *a, **kw: None


def get_title(song):
    """Return lowercase UNICODE title of song."""
    version = song.comma("version").lower()
    title = song.comma("title").lower()
    if version:
        return "%s (%s)" % (title, version)
    return title


class MirageSongsPlugin(SongsMenuPlugin):
    """Mirage songs analysis."""

    PLUGIN_ID = "Mirage Analysis"
    PLUGIN_NAME = _("Mirage Analysis")  # noqa
    PLUGIN_DESC = _("Perform Mirage Analysis of the selected songs.")  # noqa
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
            filenames, 10, reply_handler=NO_OP, error_handler=NO_OP)
