"""
AutoQueue: an automatic queueing plugin for Quod Libet.

version 0.3
Copyright 2007-2012 Eric Casteleijn <thisfred@gmail.com>
                    Naglis Jonaitis <njonaitis@gmail.com>
This program is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License version 2 as
published by the Free Software Foundation
"""
from collections import deque
from datetime import datetime

from autoqueue import AutoQueueBase
from autoqueue.player import PlayerBase, SongBase
from gi.repository import GLib, Gtk
from quodlibet import _, app
from quodlibet.plugins import PluginConfig
from quodlibet.plugins.events import EventPlugin
from quodlibet.qltk.entry import UndoEntry, ValidatingEntry
from quodlibet.util import copool

INT_SETTINGS = {
    'artist_block_time': {
        'value': 1,
        'label': 'block artist (days)'},
    'desired_queue_length': {
        'value': 4440,
        'label': 'queue (seconds)'},
    'number': {
        'value': 40,
        'label': 'number of tracks to look up'}}

BOOL_SETTINGS = {
    'verbose': {
        'value': False,
        'label': 'log to console'},
    'use_gaia': {
        'value': True,
        'label': 'use gaia similarity'},
    'use_lastfm': {
        'value': True,
        'label': 'use last.fm similarity'},
    'use_groupings': {
        'value': True,
        'label': 'use grouping similarity'},
    'contextualize': {
        'value': True,
        'label': 'queue context appropriate tracks first.'},
    'southern_hemisphere': {
        'value': False,
        'label': 'southern hemisphere'},
    'whole_albums': {
        'value': True,
        'label': 'queue whole albums'},
    'favor_new': {
        'value': True,
        'label': 'favor tracks that have never been played'}}

STR_SETTINGS = {
    'restrictions': {
        'value': '',
        'label': 'restrict'},
    'birthdays': {
        'value': '',
        'label': 'birthdays, comma separated list of name:mm/dd values'},
    'location': {
        'value': '',
        'label': 'location ([City], [State] or [City], [Country])'},
    'zipcode': {
        'value': '',
        'label': 'zipcode'},
    'geohash': {
        'value': '',
        'label': 'geohash (see geohash.org)'},
    'extra_context': {
        'value': '',
        'label': 'extra context'}}


plugin_config = PluginConfig("autoqueue")

defaults = plugin_config.defaults
for settings in (BOOL_SETTINGS, INT_SETTINGS, STR_SETTINGS):
    for setting, configuration in settings.items():
        defaults.set(setting, configuration['value'])


def escape(the_string):
    """Double escape quotes."""
    return the_string.replace('"', '\\"').replace("'", "\\'")


def remove_role(artist):
    """Remove performer role from string."""
    if not artist.endswith(')'):
        return artist
    return artist.split('(')[0].strip()


class Song(SongBase):

    """A wrapper object around quodlibet song objects."""

    def get_artist(self):
        """Return lowercase UNICODE name of artist."""
        return self.song.comma("artist").lower()

    def get_artists(self):
        """Return lowercase UNICODE name of artists and performers."""
        artists = [artist.lower() for artist in self.song.list("artist")]
        performers = [artist.lower() for artist in self.song.list("performer")]
        if hasattr(self.song, '_song'):
            for tag in self.song._song:
                if tag.startswith('performer:'):
                    performers.extend(
                        [artist.lower() for artist in self.song.list(tag)])
        else:
            for tag in self.song:
                if tag.startswith('performer:'):
                    performers.extend(
                        [artist.lower() for artist in self.song.list(tag)])
        artists.extend([remove_role(p) for p in performers])
        return list(set(artists))

    def get_title(self, with_version=True):
        """Return lowercase UNICODE title of song."""
        title = self.song.comma("title").lower()
        if with_version:
            version = self.song.comma("version").lower()
            if version:
                return "%s (%s)" % (title, version)
        return title

    def get_album(self):
        """Return lowercase UNICODE album of song."""
        return self.song.comma("album").lower()

    def get_album_artist(self):
        """Return lowercase UNICODE album of song."""
        return self.song.comma("albumartist").lower()

    def get_musicbrainz_albumid(self):
        """Return musicbrainz album_id if any."""
        return self.song.comma('musicbrainz_albumid')

    def get_tracknumber(self):
        """Get integer tracknumber."""
        tracknumber = self.song('tracknumber')
        if isinstance(tracknumber, int):
            return tracknumber
        tracknumber = tracknumber.split('/')
        try:
            return int(tracknumber[0])
        except ValueError:
            return 0

    def get_discnumber(self):
        """Get disc number."""
        try:
            return int(self.song('discnumber').split('/')[0])
        except ValueError:
            return 1

    def get_tags(self):
        """Get a list of tags for the song."""
        return self.song.list("grouping")

    def get_filename(self):
        """Get the filename of the song."""
        return ""
        return self.song("~filename")

    def get_length(self):
        """Get the length in seconds of the song."""
        return self.song("~#length")

    def get_playcount(self):
        """Get the total playcount for the song."""
        try:
            playcount = int(self.song("~#playcount"))
        except ValueError:
            # XXX: WTF: playcount can be an empty string??
            playcount = 0
        try:
            skipcount = int(self.song('~#skipcount'))
        except ValueError:
            # XXX: WTF: skipcount can be an empty string??
            skipcount = 0
        return playcount + skipcount

    def get_added(self):
        """Get the date the song was added to the library."""
        return self.song("~#added")

    def get_last_started(self):
        """Get the datetime the song was last started."""
        return self.song("~#laststarted")

    def get_rating(self):
        """Get the rating for the song."""
        return self.song("~#rating")

    def get_date_string(self):
        """Get the rating for the song."""
        return self.song("date")

    def get_year(self):
        """Get the rating for the song."""
        try:
            return int(self.song("~year"))
        except ValueError:
            return None


class AutoQueue(AutoQueueBase, EventPlugin):

    """The actual plugin class."""

    PLUGIN_ID = "AutoQueue"
    PLUGIN_NAME = _("Auto Queue")  # noqa
    PLUGIN_VERSION = "0.2"
    PLUGIN_DESC = ("Queue similar songs.")

    def __init__(self):
        self._enabled = False
        AutoQueueBase.__init__(self, Player())
        self._generators = deque()

    def enabled(self):
        """Handle user enabling the plugin."""
        self.__enabled = True

    def disabled(self):
        """Handle user disabling the plugin."""
        self.__enabled = False

    def plugin_on_song_ended(self, song, skipped):
        """Triggered when a song ends or is skipped."""
        if not song:
            return
        ssong = Song(song)
        GLib.idle_add(self.on_song_ended, ssong, skipped)

    def plugin_on_song_started(self, song):
        """Triggered when a song starts."""
        if not song:
            return
        ssong = Song(song)
        GLib.idle_add(self.on_song_started, ssong)

    def plugin_on_removed(self, songs):
        """Triggered when songs are removed from the library."""
        GLib.idle_add(self.on_removed, [Song(s) for s in songs])

    def PluginPreferences(self, parent):
        """Set and unset preferences from gui or config file."""

        def changed(entry, key):
            if entry.get_property('sensitive'):
                plugin_config.set(key, entry.get_text())

        table = Gtk.Table(n_columns=2)
        table.set_col_spacings(3)
        table.props.expand = False
        for (j, (setting, configuration)) in enumerate(BOOL_SETTINGS.items()):

            button = plugin_config.ConfigCheckButton(
                    configuration['label'],
                    setting, populate=True)
            i = j % 2
            table.attach(button, i, i + 1, j, j + 1)
            last = j
        for (j, (setting, configuration)) in enumerate(
                list(INT_SETTINGS.items()) + list(STR_SETTINGS.items())):
            index = last + j + 1
            label = Gtk.Label(label='%s:' % configuration['label'])
            label.set_alignment(0.0, 0.5)
            label.set_use_underline(True)
            table.attach(
                label, 0, 1, index, index + 1,
                xoptions=Gtk.AttachOptions.FILL | Gtk.AttachOptions.SHRINK)

            entry = UndoEntry()
            entry.set_text(plugin_config.get(setting))
            entry.connect('changed', changed, setting)
            table.attach(entry, 1, 2, index, index + 1)

        return table


class Player(PlayerBase):

    def execute_async(self, method, *args, **kwargs):
        """Execute a method asynchronously."""
        if 'funcid' not in kwargs:
            kwargs['funcid'] = method.__name__ + str(datetime.now())
        copool.add(method, *args, **kwargs)

    def construct_album_search(self, album, album_artist=None, album_id=None):
        """"Construct a search that looks for songs from this album."""
        if not album:
            return
        search = 'album="%s"' % escape(album)
        if album_artist:
            search = '&(%s, albumartist="%s")' % (search, escape(album_artist))
        if album_id:
            search = (
                '&(%s, |(musicbrainz_albumid="%s", musicbrainz_albumid=""))' %
                (search, album_id))
        return search

    def construct_files_search(self, filenames):
        """Construct a search for songs with any of these filenames."""
        return '~filename=|(%s)' % (
            ','.join(['"%s"' % escape(f) for f in filenames]),)

    def construct_file_search(self, filename):
        """Construct a search that looks for songs with this filename."""
        if not filename:
            return
        search = '~filename="%s"' % (escape(filename),)
        return search

    def construct_track_search(self, artist, title):
        """Construct an artist and title search."""
        search = '&(artist = "%s", title = "%s", version="")' % (
            escape(artist), escape(title))
        if "(" in title:
            split = title.split("(")
            if not split[0]:
                # (something) title [(version)]
                nsplit = ["(".join(split[:2])]
                nsplit.extend(split[2:])
                split = nsplit
            # title (version [(something)])
            vtitle = split[0].strip()
            version = "(".join(split[1:]).strip()[:-1]
            versioned = '&(artist = "%s", title = "%s", version="%s")' % (
                escape(artist),
                escape(vtitle),
                escape(version))
            search = "|(%s, %s)" % (search, versioned)
        return search

    def construct_tag_search(self, tags):
        """Construct a tags search."""
        search = ''
        search_tags = []
        for tag in tags:
            stripped = escape(tag)
            search_tags.append(
                '|(grouping = "%s",grouping = "artist:%s",'
                'grouping = "album:%s")' % (stripped, stripped, stripped))
        search = "|(%s)" % (",".join(search_tags))
        return search

    def construct_artist_search(self, artist):
        """Construct a search that looks for songs with this artist."""
        search = '|(artist = "%s",performer="%s")' % (
            escape(artist), escape(artist))
        return search

    def get_queue_length(self):
        """Get the current length of the queue."""
        if app.window is None:
            return 0
        playlist = app.window.playlist
        return sum(
            [row.get("~#length", 0) for row in playlist.q.get()])

    def enqueue(self, song):
        """Put the song at the end of the queue."""
        app.window.playlist.enqueue([song.song])

    def search(self, search, restrictions=None):
        """Perform a player search."""
        if restrictions:
            search = '&(%s,%s)' % (search, restrictions)
        try:
            songs = app.library.query(search)
        except Exception as e:
            return []
        return [Song(song) for song in songs]

    def get_songs_in_queue(self):
        """Return (wrapped) song objects for the songs in the queue."""
        if app.window is None:
            return []
        return [Song(song) for song in app.window.playlist.q.get()]
