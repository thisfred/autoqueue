"""AutoQueue: an automatic queueing plugin for Quod Libet.
version 0.3
Copyright 2007-2008 Eric Casteleijn <thisfred@gmail.com>

This program is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License version 2 as
published by the Free Software Foundation"""

import const, gtk
from plugins.events import EventPlugin
from widgets import main
from parse import Query
from qltk import Frame
from library import library
import config

from autoqueue import AutoQueueBase, SongBase, SQL

# If you change even a single character of code, I would ask that you
# get and use your own (free) api key from last.fm here:
# http://www.last.fm/api/account
API_KEY = "09d0975a99a4cab235b731d31abf0057"

TRACK_URL = "http://ws.audioscrobbler.com/2.0/?method=track.getsimilar" \
            "&artist=%s&track=%s&api_key=" + API_KEY
ARTIST_URL = "http://ws.audioscrobbler.com/2.0/?method=artist.getsimilar" \
             "&artist=%s&api_key=" + API_KEY
INT_SETTINGS = {
    'artist_block_time': {
        'value': 1,
        'label': 'block artist (days)'},
    'track_block_time':  {
        'value': 90,
        'label': 'block track (days)'},
    'desired_queue_length': {
        'value': 4440,
        'label': 'queue (seconds)'},
    'cache_time': {
        'value': 90,
        'label': 'cache (days)'},}
BOOL_SETTINGS = {
    'cache': {
        'value': SQL and True,
        'label': 'caching'},
    'by_tracks': {
        'value': True,
        'label': 'by track'},
    'by_artists': {
        'value': True,
        'label': 'by artist'},
    'by_tags': {
        'value': True,
        'label': 'by tags'},
    'verbose': {
        'value': False,
        'label': 'log to console'},}
STR_SETTINGS = {
    'restrictors' : {
        'value': '',
        'label': 'restrict',},
    'relaxors' : {
        'value': '',
        'label': 'relax',},
    }

def escape(the_string):
    """double escape quotes"""
    return the_string.replace('"', '\\"')

class Song(SongBase):
    """A wrapper object around quodlibet song objects."""
    def get_artist(self):
        """return lowercase UNICODE name of artist"""
        return self.song.comma("artist").lower()

    def get_title(self):
        """return lowercase UNICODE title of song"""
        version = self.song.comma("version").lower()
        title = self.song.comma("title").lower()
        if version:
            return "%s (%s)" % (title, version)
        return title

    def get_tags(self):
        """return a list of tags for the songs"""
        return self.song.list("grouping")


class AutoQueue(EventPlugin, AutoQueueBase):
    """The actual plugin class"""
    PLUGIN_ID = "AutoQueue"
    PLUGIN_NAME = _("Auto Queue")
    PLUGIN_VERSION = "0.1"

    __enabled = False
  
    def __init__(self):
        self.use_db = True
        self.store_blocked_artists = True
        self.threaded = True
        EventPlugin.__init__(self)
        AutoQueueBase.__init__(self)
               
    def enabled(self):
        """user enabled the plugin"""
        self.log("enabled")
        self.__enabled = True

    def disabled(self):
        """user disabled the plugin"""
        self.log("disabled")
        self.__enabled = False

    def plugin_on_song_started(self, song):
        """Triggered when a song start. If the right conditions apply,
        we start looking for new songs to queue."""
        if song:
            song = Song(song)
            self.on_song_started(song)
        
    def PluginPreferences(self, parent):
        def bool_changed(widget):
            if widget.get_active():
                setattr(self, widget.get_name(), True)
            else:
                setattr(self, widget.get_name(), False)
            config.set(
                'plugins',
                'autoqueue_%s' % widget.get_name(),
                widget.get_active() and 'true' or 'false')
            
        def str_changed(entry, key):
            value = entry.get_text()
            config.set('plugins', 'autoqueue_%s' % key, value)
            setattr(self, key, value)

        def int_changed(entry, key):
            value = entry.get_text()
            if value:
                config.set('plugins', 'autoqueue_%s' % key, value)
                setattr(self, key, int(value))
            
        table = gtk.Table()
        table.set_col_spacings(3)
        i = 0
        j = 0
        for setting in BOOL_SETTINGS:
            button = gtk.CheckButton(label=BOOL_SETTINGS[setting]['label'])
            button.set_name(setting)
            button.set_active(
                config.get(
                "plugins", "autoqueue_%s" % setting).lower() == 'true')
            button.connect('toggled', bool_changed)
            table.attach(button, i, i+1, j, j+1)
            if i == 1:
                i = 0
                j += 1
            else:
                i += 1
        for setting in INT_SETTINGS:
            j += 1
            label = gtk.Label('%s:' % INT_SETTINGS[setting]['label'])
            entry = gtk.Entry()
            table.attach(label, 0, 1, j, j+1, xoptions=gtk.FILL | gtk.SHRINK)
            table.attach(entry, 1, 2, j, j+1, xoptions=gtk.FILL | gtk.SHRINK)
            entry.connect('changed', int_changed, setting)
            try:
                entry.set_text(
                    config.get('plugins', 'autoqueue_%s' % setting))
            except:
                pass
        for setting in STR_SETTINGS:
            j += 1
            label = gtk.Label('%s:' % STR_SETTINGS[setting]['label'])
            entry = gtk.Entry()
            table.attach(label, 0, 1, j, j+1, xoptions=gtk.FILL | gtk.SHRINK)
            table.attach(entry, 1, 2, j, j+1, xoptions=gtk.FILL | gtk.SHRINK)
            entry.connect('changed', str_changed, setting)
            try:
                entry.set_text(config.get('plugins', 'autoqueue_%s' % setting))
            except:
                pass
            
        return table

    # Implement the player specific methods needed by autoqueue

    def player_get_userdir(self):
        """get the application user directory to store files"""
        try:
            return const.USERDIR
        except AttributeError:
            return const.DIR
    
    def player_construct_track_search(self, artist, title, restrictions):
        """construct a search that looks for songs with this artist
        and title"""
        search = '&(artist = "%s", title = "%s")' % (
            escape(artist), escape(title))
        versioned = ""
        if "(" in title:
            split = title.split("(")
            vtitle = "(".join(split[:-1]).strip()
            version =  split[-1].strip()[:-1]
            versioned = '&(artist = "%s", title = "%s", version="%s")' % (
                escape(artist),
                escape(title),
                escape(version))
        if versioned:
            search = "|(%s, %s)" % (search, versioned)
        if search:
            search = "&(%s, %s)" % (search, restrictions)
        return search
    
    def player_construct_tag_search(self, tags, exclude_artists, restrictions):
        """construct a search that looks for songs with these
        tags"""
        search = ''
        search_tags = []
        excluding = '&(%s)' % ', '.join(
            ["!artist ='%s'" % escape(a) for a in exclude_artists])
        for tag in tags:
            if tag.startswith("artist:") or tag.startswith(
                "album:"):
                stripped = ":".join(tag.split(":")[1:])
            else:
                stripped = tag
            stripped = escape(stripped)
            search_tags.extend([
                'grouping = "%s"' % stripped,
                'grouping = "artist:%s"' % stripped,
                'grouping = "album:%s"' % stripped])
        search = "&(|(%s),%s,%s)" % (
            ",".join(search_tags), excluding, restrictions)
        return search
    
    def player_construct_artist_search(self, artist, restrictions):
        """construct a search that looks for songs with this artist"""
        search = 'artist = "%s"' % escape(artist)
        search = "&(%s, %s)" % (search, restrictions)
        return search

    def player_construct_restrictions(
        self, track_block_time, relaxors, restrictors):
        """contstruct a search to further modify the searches"""
        restrictions = "#(laststarted > %s days)" % track_block_time
        if relaxors:
            restrictions = "|(%s, %s)" % (restrictions, relaxors)
        if restrictors:
            restrictions = "&(%s, %s)" % (restrictions, restrictors)
        return restrictions

    def player_set_variables_from_config(self):
        """Initialize user settings from the configuration storage"""
        for key, vdict in INT_SETTINGS.items():
            try:
                setattr(self, key, config.getint(
                    "plugins", "autoqueue_%s" % key))
            except:
                setattr(self, key, vdict['value'])
                config.set("plugins", "autoqueue_%s" % key, vdict['value'])
        for key, vdict in BOOL_SETTINGS.items():
            try:
                setattr(self, key, config.get(
                    "plugins", "autoqueue_%s" % key).lower() == 'true')
            except:
                setattr(self, key, vdict['value'])
                config.set("plugins", "autoqueue_%s" %
                           key, vdict['value'] and 'true' or 'false')
        for key, vdict in STR_SETTINGS.items():
            try:
                setattr(
                    self, key, config.get("plugins", "autoqueue_%s" % key))
            except:
                setattr(self, key, vdict['value'])
                config.set("plugins", "autoqueue_%s" % key, vdict['value'])

    def player_get_queue_length(self):
        """Get the current length of the queue"""
        return sum([row.get("~#length", 0) for row in main.playlist.q.get()])

    def player_enqueue(self, song):
        """Put the song at the end of the queue"""
        gtk.gdk.threads_enter()
        main.playlist.enqueue([song.song])
        gtk.gdk.threads_leave()

    def player_search(self, search):
        """perform a player search"""
        try:
            myfilter = Query(search).search
            songs = filter(myfilter, library.itervalues())
        except (Query.error, RuntimeError):
            self.log("error in: %s" % search)
            return []
        return [Song(song) for song in songs]

    def player_get_songs_in_queue(self):
        """return (wrapped) song objects for the songs in the queue"""
        return [Song(song) for song in main.playlist.q.get()]
