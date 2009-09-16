# Copyright (C) 2007-2008 - Eric Casteleijn, Alexandre Rosenfeld
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

import os
import urllib
from time import time
import gconf
import rb, rhythmdb

from autoqueue import AutoQueueBase, SongBase

GCONFPATH = '/apps/rhythmbox/plugins/autoqueue/'

class Song(SongBase):
    """A wrapper object around rhythmbox song objects."""
    def __init__(self, song, db):
        self.song = song
        self.db = db

    def get_artist(self):
        """return lowercase UNICODE name of artist"""
        return unicode(
            self.db.entry_get(self.song, rhythmdb.PROP_ARTIST).lower(), 'utf-8')

    def get_title(self):
        """return lowercase UNICODE title of song"""
        return unicode(
            self.db.entry_get(self.song, rhythmdb.PROP_TITLE).lower(), 'utf-8')

    def get_tags(self):
        """return a list of tags for the songs"""
        return []

    def get_length(self):
        return self.db.entry_get(self.song, rhythmdb.PROP_DURATION)

    def get_filename(self):
        location = self.db.entry_get(self.song, rhythmdb.PROP_LOCATION)
        if location.startswith("file://"):
            return urllib.unquote(location[7:])
        return None


class AutoQueuePlugin(rb.Plugin, AutoQueueBase):
    def __init__(self):
        rb.Plugin.__init__(self)
        self.use_db = True
        self.store_blocked_artists = True
        AutoQueueBase.__init__(self)
        self.gconfclient = gconf.client_get_default()
        self.verbose = False
        self.by_mirage = False

    def activate(self, shell):
        self.shell = shell
        self.rdb = shell.get_property('db')
        sp = shell.get_player ()
        self.pec_id = sp.connect(
            'playing-song-changed', self.playing_entry_changed)

    def deactivate(self, shell):
        self.rdb = None
        self.shell = None
        sp = shell.get_player()
        sp.disconnect(self.pec_id)

    def log(self, msg):
        """print debug messages"""
        if not self.verbose:
            return
        print msg

    def playing_entry_changed(self, sp, entry):
        if entry:
            self.on_song_started(Song(entry, self.rdb))

    def player_get_userdir(self):
        """get the application user directory to store files"""
        folder = os.path.join(
            os.getenv('HOME'), '.gnome2', 'rhythmbox', 'autoqueue')
        if not os.path.isdir(folder):
            os.mkdir(folder)
        return folder

    def player_construct_track_search(self, artist, title, restrictions):
        """construct a search that looks for songs with this artist
        and title"""
        result = (rhythmdb.QUERY_PROP_EQUALS, rhythmdb.PROP_ARTIST_FOLDED,
                  artist.encode('utf-8'), rhythmdb.QUERY_PROP_EQUALS,
                  rhythmdb.PROP_TITLE_FOLDED, title.encode('utf-8'))
        if restrictions:
            result += restrictions
        return result

    def player_construct_tag_search(self, tags, exclude_artists, restrictions):
        """construct a search that looks for songs with these
        tags"""
        return None

    def player_construct_artist_search(self, artist, restrictions):
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
        #XXX Still to do
        pass

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
