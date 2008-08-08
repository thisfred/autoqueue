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

import rb

from autoqueue import AutoQueueBase, SongBase

GCONFPATH = '/apps/rhythmbox/plugins/autoqueue/'

class Song(SongBase):
    """A wrapper object around rhythmbox song objects."""
    def get_artist(self):
        """return lowercase UNICODE name of artist"""
        raise NotImplemented

    def get_title(self):
        """return lowercase UNICODE title of song"""
        raise NotImplemented

    def get_tags(self):
        """return a list of tags for the songs"""
        raise NotImplemented
    

class AutoQueuePlugin(rb.Plugin, AutoQueueBase):
    def __init__(self):
        rb.Plugin.__init__(self)
        #AutoQueueBase.__init__(self)

    def activate(self, shell):
        self.shell = shell
        
    def deactivate(self, shell):
        self.shell = None

    def player_get_userdir(self):
        """get the application user directory to store files"""
        return GCONFPATH
    
    def player_construct_track_search(self, artist, title, restrictions):
        """construct a search that looks for songs with this artist
        and title"""
        return True
    
    def player_construct_tag_search(self, tags, exclude_artists, restrictions):
        """construct a search that looks for songs with these
        tags"""
        return True

    
    def player_construct_artist_search(self, artist, restrictions):
        """construct a search that looks for songs with this artist"""
        return True

        
    def player_construct_restrictions(
        self, track_block_time, relaxors, restrictors):
        """contstruct a search to further modify the searches"""
        return True


    def player_set_variables_from_config(self):
        """Initialize user settings from the configuration storage"""
        return True


    def player_get_queue_length(self):
        """Get the current length of the queue"""
        return True


    def player_enqueue(self, song):
        """Put the song at the end of the queue"""
        return True


    def player_search(self, search):
        """perform a player search"""
        return True


    def player_get_songs_in_queue(self):
        """return (wrapped) song objects for the songs in the queue"""
        return True

