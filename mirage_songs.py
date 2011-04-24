"""Mirage songs plugin."""

import dbus
from plugins.songsmenu import SongsMenuPlugin

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
    PLUGIN_NAME = _("Mirage Analysis")
    PLUGIN_DESC = _("Perform Mirage Analysis of the selected songs.")
    PLUGIN_ICON = "gtk-find-and-replace"
    PLUGIN_VERSION = "0.1"


    def __init__(self, *args):
        SongsMenuPlugin.__init__(self, *args)
        bus = dbus.SessionBus()
        sim = bus.get_object(
            'org.autoqueue.Similarity', '/org/autoqueue/Similarity')
        self.similarity = dbus.Interface(
            sim, dbus_interface='org.autoqueue.SimilarityInterface')

    def error_handler(self, *args, **kwargs):
        """Log errors when calling D-Bus methods in a async way."""
        print 'Error handler received: %r, %r' % (args, kwargs)

    def plugin_songs(self, songs):
        """Add the work to the coroutine pool."""
        for song in songs:
            self.similarity.analyze_track(
                song('~filename'), False, [], reply_handler=NO_OP,
                error_handler=self.error_handler)
