"""Rhythmbox version of the autoqueue plugin."""

# Copyright (C) 2007-20011 - Eric Casteleijn, Alexandre Rosenfeld, Graham White
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2, or (at your option)
# any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA 02110-1301  USA.

import urllib
from time import time
import gconf
import gobject
import gtk
from gtk import gdk
import rb
import rhythmdb
from collections import deque
from autoqueue import AutoQueueBase, SongBase

GCONFPATH = '/apps/rhythmbox/plugins/rhythmbox_autoqueue/'

GCONF_BOOLS = {
    'use_lastfm': {
        'GCONF': GCONFPATH + 'use_lastfm',
        'value': True},
    'verbose': {
        'GCONF': GCONFPATH + 'verbose',
        'value': False},
    'use_groupings': {
        'GCONF': GCONFPATH + 'use_groupings',
        'value': True},
    'use_mirage': {
        'GCONF': GCONFPATH + 'use_mirage',
        'value': True}}

GCONF_INTS = {
    'artist_block_time': {
        'GCONF': GCONFPATH + 'artist_block_time',
        'value': 1,
        'range_lo': 1,
        'range_hi': 999},
    'desired_queue_length': {
        'GCONF': GCONFPATH + 'desired_queue_length',
        'value': 600,
        'range_lo': 1,
        'range_hi': 1000000}}

GCONF_STRINGS = {
    'restrictions': {
        'GCONF': GCONFPATH + 'restrictions',
        'value': ''}}

AUTOQUEUE_UI = """
<ui>
    <toolbar name="ToolBar">
        <toolitem name="Autoqueue" action="ToggleAutoqueue" />
    </toolbar>
</ui>
"""


class Song(SongBase):
    """A wrapper object around rhythmbox song objects."""

    def __init__(self, song, db):       # pylint: disable=W0231
        self.song = song
        self.db = db

    def get_artist(self):
        """Get lowercase UNICODE name of artist."""
        return unicode(
            self.db.entry_get(self.song, rhythmdb.PROP_ARTIST).lower(),
            'utf-8')

    def get_artists(self):
        """Get a list of all artists and performers for the song."""
        return [self.get_artist()]

    def get_title(self):
        """Get lowercase UNICODE title of song."""
        return unicode(
            self.db.entry_get(self.song, rhythmdb.PROP_TITLE).lower(), 'utf-8')

    def get_tags(self):
        """Get a list of tags for the songs."""
        return []

    def get_length(self):
        """Get length in seconds for the song."""
        return self.db.entry_get(self.song, rhythmdb.PROP_DURATION)

    def get_filename(self):
        """Get the filename for the song."""
        location = self.db.entry_get(self.song, rhythmdb.PROP_LOCATION)
        if location.startswith("file://"):
            return urllib.unquote(location[7:])
        return None

    def get_last_started(self):
        """Get the datetime the song was last started."""
        return self.db.entry_get(self.song, rhythmdb.PROP_LAST_PLAYED)

    def get_rating(self):
        """Get the rating of the song."""
        rating = self.db.entry_get(self.song, rhythmdb.PROP_RATING)
        return rating / 5.0

    def get_playcount(self):
        """Get the playcount for the song."""
        return self.db.entry_get(self.song, rhythmdb.PROP_PLAY_COUNT)


class AutoQueuePlugin(rb.Plugin, AutoQueueBase):
    """Plugin implementation."""

    def __init__(self):
        rb.Plugin.__init__(self)
        self.action_group = None
        self.action = None
        self.ui_id = None
        self.builder = None
        self.gconf = gconf.client_get_default()
        self.verbose = True
        self.by_mirage = True
        self.log("initialized")
        self._generators = deque()
        self.pec_id = None
        self.rdb = None
        self.shell = None
        self.plugin_on = False
        self.entry = None
        AutoQueueBase.__init__(self)

    def activate(self, shell):
        """Called on activation of the plugin."""
        self.shell = shell
        self.rdb = shell.get_property('db')

        # Icon
        icon_factory = gtk.IconFactory()
        icon_factory.add(
            "autoqueue", gtk.IconSet(gtk.gdk.pixbuf_new_from_file(
                self.find_file("autoqueue.png"))))
        icon_factory.add_default()
        # Add on/off toggle button
        self.action = gtk.ToggleAction(
            'ToggleAutoqueue', _('Toggle Autoqueue'),
            _('Turn auto queueing on/off'), 'autoqueue')
        self.action.connect('activate', self.toggle_autoqueue)
        self.action_group = gtk.ActionGroup('AutoqueuePluginActions')
        self.action_group.add_action(self.action)
        uim = shell.get_ui_manager()
        uim.insert_action_group(self.action_group, 0)
        self.ui_id = uim.add_ui_from_string(AUTOQUEUE_UI)
        uim.ensure_update()

    def deactivate(self, shell):
        """Called on deactivation of the plugin."""

        if self.plugin_on:
            self.toggle_autoqueue()

        # Remove on/off toggle button
        uim = shell.get_ui_manager()
        uim.remove_ui(self.ui_id)
        uim.remove_action_group(self.action_group)

        self.action_group = None
        self.action = None
        self.rdb = None
        self.shell = None

    def toggle_autoqueue(self, action=None):
        """Toggle the plugin on or off."""
        sp = self.shell.get_player()
        if self.plugin_on:
            sp.disconnect(self.pec_id)
            self.plugin_on = False
        else:
            self.pec_id = sp.connect(
                'playing-song-changed', self.playing_entry_changed)
            self.plugin_on = True

    def create_configure_dialog(self, dialog=None):
        """Create configuration dialog."""
        # set up the UI
        ui_file = self.find_file("autoqueue-config.ui")
        self.builder = gtk.Builder()
        self.builder.add_from_file(ui_file)

        # set up the check boxes
        for key in GCONF_BOOLS:
            # can't use gconf.get_bool here as that function returns false
            # if no value is set which is useless for setting up a default
            value = self.gconf.get(GCONF_BOOLS[key]['GCONF'])
            if value is None:
                self.builder.get_object(key).set_active(
                    GCONF_BOOLS[key]['value'])
            else:
                self.builder.get_object(key).set_active(value.get_bool())

        # don't provide mirage settings if we don't have mirage
        if not self.has_mirage:
            self.builder.get_object('use_lastfm').set_active(True)
            self.builder.get_object('use_lastfm').set_sensitive(False)
            self.builder.get_object('use_mirage').set_active(False)
            self.builder.get_object('use_mirage').set_sensitive(False)

        # set up spinners
        for key in GCONF_INTS:
            spin = self.builder.get_object(key)
            spin.set_range(GCONF_INTS[key]['range_lo'],
                           GCONF_INTS[key]['range_hi'])
            spin.set_increments(1, 10)
            value = self.gconf.get_int(GCONF_INTS[key]['GCONF'])
            if not value:
                value = GCONF_INTS[key]['value']
            spin.set_value(value)

        # set up the entry box(s)
        for key in GCONF_STRINGS:
            value = self.gconf.get_string(GCONF_STRINGS[key]['GCONF'])
            if not value:
                value = GCONF_STRINGS[key]['value']
            self.builder.get_object(key).set_text(value)

        # set up and return the dialog box
        dialog = self.builder.get_object("config_dialog")
        dialog.connect('response', self.config_dialog_response_cb)
        return dialog

    def config_dialog_response_cb(self, dialog, response):
        """Callback for dialog response."""
        if response is 1:
            for key in GCONF_BOOLS:
                self.gconf.set_bool(GCONF_BOOLS[key]['GCONF'],
                    self.builder.get_object(key).get_active())

            for key in GCONF_INTS:
                self.gconf.set_int(GCONF_INTS[key]['GCONF'],
                    self.builder.get_object(key).get_value_as_int())

            for key in GCONF_STRINGS:
                self.gconf.set_string(GCONF_STRINGS[key]['GCONF'],
                    self.builder.get_object(key).get_text())

            self.player_set_variables_from_config()

        dialog.hide()

    def _idle_callback(self):
        """Callback that performs task asynchronously."""
        gdk.threads_enter()
        while self._generators:
            if self._generators[0] is None:
                self._generators.popleft()
                continue
            for dummy in self._generators[0]:
                gdk.threads_leave()
                return True
            self._generators.popleft()
        gdk.threads_leave()
        return False

    def player_execute_async(self, method, *args, **kwargs):
        """Execute method asynchronously."""
        add_callback = False
        if not self._generators:
            add_callback = True
        self._generators.append(method(*args, **kwargs))
        if add_callback:
            gobject.idle_add(self._idle_callback)

    def log(self, msg):
        """Print debug messages."""
        # TODO: replace with real logging
        if not self.verbose:
            return
        print msg

    def playing_entry_changed(self, sp, entry):
        """Handler for song change."""
        if self.entry:
            self.on_song_ended(Song(self.entry, self.rdb), False)
        self.entry = entry
        if entry:
            self.on_song_started(Song(entry, self.rdb))

    def player_construct_file_search(self, filename, restrictions=None):
        """construct a search that looks for songs with this filename"""
        if not filename:
            return
        result = (
            rhythmdb.QUERY_PROP_EQUALS, rhythmdb.PROP_LOCATION,
            'file://' + filename.encode('utf-8'))
        if restrictions:
            result += restrictions
        return result

    def player_construct_track_search(self, artist, title, restrictions=None):
        """construct a search that looks for songs with this artist
        and title"""
        result = (rhythmdb.QUERY_PROP_EQUALS, rhythmdb.PROP_ARTIST_FOLDED,
                  artist.encode('utf-8'), rhythmdb.QUERY_PROP_EQUALS,
                  rhythmdb.PROP_TITLE_FOLDED, title.encode('utf-8'))
        if restrictions:
            result += restrictions
        return result

    def player_construct_tag_search(self, tags, restrictions=None):
        """construct a search that looks for songs with these
        tags"""
        return None

    def player_construct_artist_search(self, artist, restrictions=None):
        """construct a search that looks for songs with this artist"""
        result = (rhythmdb.QUERY_PROP_EQUALS, rhythmdb.PROP_ARTIST_FOLDED,
                  artist.encode('utf-8'))
        if restrictions:
            result += restrictions
        return result

    def player_construct_restrictions(
        self, track_block_time, relaxors, restrictors):
        """contstruct a search to further modify the searches"""
        seconds = track_block_time * 24 * 60 * 60
        now = time()
        cutoff = now - seconds
        return (
            rhythmdb.QUERY_PROP_LESS, rhythmdb.PROP_LAST_PLAYED, cutoff)

    def player_set_variables_from_config(self):
        """Initialize user settings from the configuration storage"""
        # save the boolean values
        for key in GCONF_BOOLS:
            value = self.gconf.get(GCONF_BOOLS[key]['GCONF'])
            if value is None:
                setattr(self, key, GCONF_BOOLS[key]['value'])
            else:
                setattr(self, key, value.get_bool())

        # override settings if mirage isn't available
        if not self.has_mirage:
            setattr(self, 'use_lastfm', True)
            setattr(self, 'use_mirage', False)

        # save the integer values
        for key in GCONF_INTS:
            value = self.gconf.get_int(GCONF_INTS[key]['GCONF'])
            if not value:
                value = GCONF_INTS[key]['value']
            setattr(self, key, value)

        # save the text string
        for key in GCONF_STRINGS:
            value = self.gconf.get_string(GCONF_STRINGS[key]['GCONF'])
        if not value:
            value = GCONF_STRINGS[key]['value']
        setattr(self, key, value)

    def player_get_queue_length(self):
        """Get the current length of the queue"""
        return sum([
            self.rdb.entry_get(
            row[0], rhythmdb.PROP_DURATION) for row in
            self.shell.props.queue_source.props.query_model])

    def player_enqueue(self, song):
        """Put the song at the end of the queue"""
        self.shell.add_to_queue(
            self.rdb.entry_get(song.song, rhythmdb.PROP_LOCATION))

    def player_search(self, search):
        """perform a player search"""
        query = self.rdb.query_new()
        self.rdb.query_append(query, search)
        query_model = self.rdb.query_model_new_empty()
        self.rdb.do_full_query_parsed(query_model, query)
        result = []
        for row in query_model:
            result.append(Song(row[0], self.rdb))
        return result

    def player_get_songs_in_queue(self):
        """return (wrapped) song objects for the songs in the queue"""
        return [
            Song(row[0], self.rdb) for row in
            self.shell.props.queue_source.props.query_model]
