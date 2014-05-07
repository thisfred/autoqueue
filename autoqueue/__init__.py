"""AutoQueue: an automatic queueing plugin library.

Copyright 2007-2014 Eric Casteleijn <thisfred@gmail.com>,
                    Daniel Nouri <daniel.nouri@gmail.com>
                    Jasper OpdeCoul <jasper.opdecoul@gmail.com>
                    Graham White
                    Naglis Jonaitis <njonaitis@gmail.com>

This program is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation; either version 2, or (at your option)
any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program; if not, write to the Free Software
Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA 02110-1301  USA.
"""
import os
import random
from abc import ABCMeta, abstractmethod
from cPickle import Pickler, Unpickler
from collections import deque

import dbus
from datetime import date, time, datetime, timedelta
from dbus.mainloop.glib import DBusGMainLoop

from autoqueue.context import Context


try:
    import pywapi
    WEATHER = True
except ImportError:
    WEATHER = False

try:
    import geohash
    GEOHASH = True
except ImportError:
    GEOHASH = False

DBusGMainLoop(set_as_default=True)

try:
    import xdg.BaseDirectory
    XDG = True
except ImportError:
    XDG = False

try:
    import requests
    REQUESTS = True
except ImportError:
    REQUESTS = False

# If you change even a single character of code, I would ask that you
# get and use your own (free) last.fm api key from here:
# http://www.last.fm/api/account
API_KEY = "09d0975a99a4cab235b731d31abf0057"

THRESHOLD = .5

TIMEOUT = 3000
FIVE_MINUTES = timedelta(0, 300)
THIRTY_MINUTES = timedelta(0, 1800)

NO_OP = lambda *a, **kw: None

BANNED_ALBUMS = [
    'ep', 'greatest hits', 'demo', 'the best of', 'the very best of', 'live',
    'demos', 'self titled', 'untitled album', '[non-album tracks]', 'single',
    'singles', '7"', 'covers', 'album']


def escape(the_string):
    """Double escape quotes."""
    # TODO: move to utils
    return the_string.replace('"', '\\"').replace("'", "\\'")


def get_artists_playing_nearby(location_geohash, location):
    """Get a list of artists playing nearby venues in the near future."""
    params = {
        'method': 'geo.getevents',
        'limit': 25,
        'api_key': API_KEY,
        'format': 'json'}
    if location_geohash:
        lon, lat = geohash.decode(location_geohash)
        params['long'] = lon
        params['lat'] = lat
    if location:
        params['location'] = location
    nearby_artists = []
    response = requests.get('http://ws.audioscrobbler.com/2.0/', params=params)
    try:
        total_pages = int(response.json['events']['@attr']['totalPages'])
        page = int(response.json['events']['@attr']['page'])
        while True:
            for event in response.json['events']['event']:
                artists = event['artists']['artist']
                if isinstance(artists, list):
                    nearby_artists.extend(artists)
                else:
                    nearby_artists.append(artists)
            if page == total_pages:
                return nearby_artists
            params['page'] = page + 1
            response = requests.get(
                'http://ws.audioscrobbler.com/2.0/', params=params)
            page = int(response.json['events']['@attr']['page'])
    except Exception, e:
        print e
    return nearby_artists


class SongBase(object):
    """A wrapper object around player specific song objects."""

    __metaclass__ = ABCMeta

    def __init__(self, song):
        self.song = song

    def __str__(self):
        return "<Song: %s - %s>" % (self.get_artist(), self.get_title())

    @abstractmethod
    def get_artist(self):
        """Return lowercase UNICODE name of artist."""

    @abstractmethod
    def get_artists(self):
        """Return lowercase UNICODE name of artists and performers."""

    @abstractmethod
    def get_title(self, with_version=True):
        """Return lowercase UNICODE title of song."""

    @abstractmethod
    def get_tracknumber(self):
        """Return the tracknumber of the song."""

    @abstractmethod
    def get_album(self):
        """Return the album of the song."""

    @abstractmethod
    def get_album_artist(self):
        """Return the album of the song."""

    @abstractmethod
    def get_musicbrainz_albumid(self):
        """Return the musicbrainz album id, if any."""

    @abstractmethod
    def get_discnumber(self):
        """Return the discnumber of the song."""

    @abstractmethod
    def get_tags(self):
        """Return a list of tags for the song."""

    @abstractmethod
    def get_filename(self):
        """Return filename for the song."""

    @abstractmethod
    def get_last_started(self):
        """Return the datetime the song was last played."""

    @abstractmethod
    def get_rating(self):
        """Return the rating of the song."""

    @abstractmethod
    def get_playcount(self):
        """Return the playcount of the song."""

    @abstractmethod
    def get_date_string(self):
        """Return the playcount of the song."""

    @abstractmethod
    def get_year(self):
        """Return the playcount of the song."""

    def get_play_frequency(self):
        """Return the play frequency of the song (plays / day)."""
        count = self.get_playcount()
        if count is NotImplemented:
            return 0
        if count == 0:
            return 0
        last_started = self.get_last_started()
        if last_started is NotImplemented:
            return 0
        now = datetime.now()
        days = float(max((now - datetime.fromtimestamp(last_started)).days, 1))
        return 1.0 / days

    def get_stripped_tags(self):
        """Return a set of stripped tags."""
        tags = self.get_tags()
        if not tags:
            return []
        tagset = set([])
        for tag in tags:
            if tag.startswith("artist:") or tag.startswith("album:"):
                stripped = ":".join(tag.split(":")[1:])
            else:
                stripped = tag
            tagset.add(stripped)
        return tagset

    def get_non_geo_tags(self):
        """Get all the song tags unrelated to geotagging."""
        song_tags = self.get_stripped_tags()
        return [
            t for t in song_tags if not t.startswith('geohash:')
            and not t == 'geotagged']

    def get_geohashes(self):
        """Get all the geohashes from this song."""
        song_tags = self.get_stripped_tags()
        geohashes = [
            t.split(':')[1] for t in song_tags if t.startswith('geohash:')]
        if GEOHASH:
            for h in geohashes[:]:
                geohashes.extend(geohash.neighbors(h))
        return geohashes


def tag_score(song, tags):
    """Calculate similarity score by tags."""
    if not tags:
        return 0
    song_tags = set(song.get_non_geo_tags())
    if not song_tags:
        return 0
    if song_tags or tags:
        score = (
            len(song_tags & tags) /
            float(len(song_tags | tags) + 1))
        return score
    return 0


class AutoQueueBase(object):
    """Generic base class for autoqueue plugins."""

    def __init__(self):
        self.artist_block_time = 1
        self._blocked_artists = deque([])
        self._blocked_artists_times = deque([])
        self._cache_dir = None
        self.desired_queue_length = 15 * 60
        self.running = False
        self.verbose = False
        self.song = None
        self.number = 40
        self.restrictions = None
        self.extra_context = None
        self.present = []
        self.use_mirage = True
        self.whole_albums = True
        self.contextualize = True
        self.southern_hemisphere = False
        self.use_lastfm = True
        self.use_groupings = True
        self.get_blocked_artists_pickle()
        self.last_songs = []
        self.last_song = None
        self.location = ''
        self.geohash = ''
        self.nearby_artists = []
        self.cached_weather_tags = None
        self.cached_weather_tags_at = None
        self.birthdays = ''
        bus = dbus.SessionBus()
        sim = bus.get_object(
            'org.autoqueue', '/org/autoqueue/Similarity',
            follow_name_owner_changes=True)
        self.similarity = dbus.Interface(
            sim, dbus_interface='org.autoqueue.SimilarityInterface')
        self.has_mirage = self.similarity.has_mirage()
        self.player_set_variables_from_config()
        self.set_presence()
        if self.location or self.geohash:
            self.nearby_artists = get_artists_playing_nearby(
                self.geohash, self.location)

    def set_presence(self):
        for user in self.present.split(','):
            self.similarity.join(user.strip(), timeout=TIMEOUT)

    def log(self, msg):
        """Print debug messages."""
        # TODO replace with real logging.
        if not self.verbose:
            return
        try:
            print "[autoqueue]", msg.encode('utf-8')
        except UnicodeDecodeError:
            print "[autoqueue]", msg

    def error_handler(self, *args, **kwargs):
        """Log errors when calling D-Bus methods in a async way."""
        self.log('Error handler received: %r, %r' % (args, kwargs))

    def get_cache_dir(self):
        """Get the directory to store temporary data.

        Defaults to $XDG_CACHE_HOME/autoqueue on Gnome.
        """
        if self._cache_dir:
            return self._cache_dir
        if not XDG:
            return NotImplemented
        cache_dir = os.path.join(xdg.BaseDirectory.xdg_cache_home, 'autoqueue')
        if not os.path.exists(cache_dir):
            os.makedirs(cache_dir)
        self._cache_dir = cache_dir
        return cache_dir

    def get_blocked_artists_pickle(self):
        """Read the list of blocked artists from disk."""
        dump = os.path.join(
            self.get_cache_dir(), "autoqueue_block_cache")
        try:
            pickle = open(dump, 'r')
            try:
                unpickler = Unpickler(pickle)
                artists, times = unpickler.load()
                if isinstance(artists, list):
                    artists = deque(artists)
                if isinstance(times, list):
                    times = deque(times)
                self._blocked_artists = artists
                self._blocked_artists_times = times
            finally:
                pickle.close()
        except IOError:
            pass

    def block_artist(self, artist_name):
        """Block songs by artist from being played for a while."""
        now = datetime.now()
        self._blocked_artists.append(artist_name)
        self._blocked_artists_times.append(now)
        self.log("Blocked artist: %s (%s)" % (
            artist_name,
            len(self._blocked_artists)))
        dump = os.path.join(
            self.get_cache_dir(), "autoqueue_block_cache")
        try:
            os.remove(dump)
        except OSError:
            pass
        if len(self._blocked_artists) == 0:
            return
        pickle_file = open(dump, 'w')
        pickler = Pickler(pickle_file, -1)
        to_dump = (self._blocked_artists,
                   self._blocked_artists_times)
        pickler.dump(to_dump)
        pickle_file.close()

    def unblock_artists(self):
        """Unblock expired blocked artists."""
        now = datetime.now()
        while self._blocked_artists_times:
            if self._blocked_artists_times[
                    0] + timedelta(self.artist_block_time) > now:
                break
            self.log("Unblocked %s (%s)" % (
                self._blocked_artists.popleft(),
                self._blocked_artists_times.popleft()))

    def get_artists_track_filenames(self, artist_names):
        """Get all known file ids for this artist."""
        filenames = []
        for artist_name in artist_names:
            search = self.player_construct_artist_search(artist_name)
            filenames.extend([
                song.get_filename() for song in self.player_search(search)])
        return filenames

    def player_construct_album_search(self, album, album_artist=None,
                                      album_id=None, restrictions=None):
        """Construct a search that looks for songs from this album."""

    def player_construct_file_search(self, filename, restrictions=None):
        """Construct a search that looks for songs with this filename."""

    def player_construct_track_search(self, artist, title, restrictions=None):
        """Construct a search that looks for songs with this artist
        and title.
        """

    def player_construct_artist_search(self, artist, restrictions=None):
        """Construct a search that looks for songs with this artist."""

    def player_construct_tag_search(self, tags, restrictions=None):
        """Construct a search that looks for songs with these tags."""

    def player_set_variables_from_config(self):
        """Initialize user settings from the configuration storage."""

    def player_get_queue_length(self):
        """Get the current length of the queue."""

    def player_enqueue(self, song):
        """Put the song at the end of the queue."""

    def player_search(self, search):
        """Perform a player search."""

    def player_get_songs_in_queue(self):
        """Return (wrapped) song objects for the songs in the queue."""

    def player_execute_async(self, method, *args, **kwargs):
        """Override this if the player has a way to execute methods
        asynchronously, like the copooling in autoqueue.

        """
        if 'funcid' in kwargs:
            del kwargs['funcid']
        for dummy in method(*args, **kwargs):
            pass

    def disallowed(self, song):
        """Check whether a song is not allowed to be queued."""
        for artist in song.get_artists():
            if artist in self.get_blocked_artists():
                return True
        for qsong in self.get_last_songs():
            if qsong.get_filename() == song.get_filename():
                return True
        return False

    def on_song_ended(self, song, skipped):
        """Should be called by the plugin when a song ends or is skipped."""
        if song is None:
            return
        if skipped:
            return
        artist_names = song.get_artists()
        title = song.get_title()
        if not (artist_names and title):
            return
        # add the artist to the blocked list, so their songs won't be
        # played for a determined time
        for artist_name in artist_names:
            self.block_artist(artist_name)

    def on_song_started(self, song):
        """Should be called by the plugin when a new song starts.

        If the right conditions apply, we start looking for new songs
        to queue.

        """
        if song is None:
            return
        self.song = song
        if self.has_mirage and self.use_mirage:
            artist = song.get_artist()
            self.similarity.start_song(
                song.get_filename(), artist, song.get_title(), timeout=TIMEOUT)
        if self.running:
            return
        if self.desired_queue_length == 0 or self.queue_needs_songs():
            self.fill_queue()
        self.unblock_artists()

    def on_removed(self, songs):
        if not self.has_mirage and self.use_mirage:
            return
        for song in songs:
            filename = song.get_filename()
            self.log('Remove similarity for %s' % filename)
            self.similarity.remove_track_by_filename(
                filename, reply_handler=NO_OP,
                error_handler=NO_OP, timeout=TIMEOUT)

    def queue_needs_songs(self):
        """Determine whether the queue needs more songs added."""
        queue_length = self.player_get_queue_length()
        return queue_length < self.desired_queue_length

    @property
    def eoq(self):
        return datetime.now() + timedelta(0, self.player_get_queue_length())

    @staticmethod
    def string_to_datetime(time_string):
        time_string, ampm = time_string.split()
        hour, minute = time_string.split(':')
        hour = int(hour)
        minute = int(minute)
        if ampm == 'am':
            if hour == 12:
                delta = -12
            else:
                delta = 0
        else:
            if hour == 12:
                delta = 0
            else:
                delta = 12
        return datetime.combine(date.today(), time(hour + delta, minute))

    def get_weather_tags(self):
        now = datetime.now()
        if not WEATHER:
            return []
        if self.cached_weather_tags and (now < self.cached_weather_tags_at +
                                         FIVE_MINUTES):
            return self.cached_weather_tags
        if self.zipcode:
            try:
                weather = pywapi.get_weather_from_yahoo(self.zipcode)
            except Exception, e:
                self.log(repr(e))
                return []
        else:
            return []
        conditions = []
        eoq = self.eoq
        sunset = weather.get('astronomy', {}).get('sunset', '')
        sunrise = weather.get('astronomy', {}).get('sunrise', '')
        if sunrise and sunset:
            sunrise = self.string_to_datetime(sunrise)
            sunset = self.string_to_datetime(sunset)
            if abs(sunrise - eoq) < THIRTY_MINUTES:
                conditions.extend([
                    'sunrise', 'dawn', 'aurora', 'break of day', 'dawning',
                    'daybreak', 'sunup'])
            elif abs(sunset - eoq) < THIRTY_MINUTES:
                conditions.extend([
                    'sunset', 'dusk', 'gloaming', 'nightfall',
                    'sundown', 'twilight', 'eventide', 'close of day'])
            if eoq > sunrise and eoq < sunset:
                conditions.extend(['daylight'])
            else:
                conditions.extend(['dark', 'darkness'])
        cs = weather.get(
            'condition', {}).get('text', '').lower().strip().split('/')
        for condition in cs:
            condition = condition.strip()
            if condition:
                conditions.append(condition)
                unmodified = condition.split()[-1]
                if unmodified not in conditions:
                    conditions.append(unmodified)
                if unmodified[-1] == 'y':
                    if unmodified[-2] == unmodified[-3]:
                        conditions.append(unmodified[:-2])
                    else:
                        conditions.append(unmodified[:-1])
                if eoq > sunrise and eoq < sunset and condition == 'fair':
                    conditions.extend(['sun', 'sunny', 'sunlight'])
        temperature = weather.get('condition', {}).get('temp', '')
        temperature_tags = []
        if temperature:
            degrees_c = int(temperature)
            if degrees_c <= 0:
                temperature_tags.extend(['freezing', 'frozen', 'ice'])
            if degrees_c <= 10:
                temperature_tags.extend(['cold'])
            if degrees_c >= 30:
                temperature_tags.extend(['hot', 'heat'])
        speed = float(weather.get('wind', {}).get('speed', '0') or '0')
        if speed < 1:
            wind_conditions = ['calm']
        elif speed <= 30:
            wind_conditions = ['breeze', 'breezy']
        elif speed <= 38:
            wind_conditions = ['wind', 'windy']
        elif speed <= 54:
            wind_conditions = ['wind', 'windy', 'gale']
        elif speed <= 72:
            wind_conditions = [
                'wind', 'windy', 'storm', 'stormy']
        else:
            wind_conditions = [
                'wind', 'windy', 'storm', 'stormy', 'hurricane']
        humidity = float(
            weather.get('atmosphere', {}).get('humidity', '0') or '0')
        if humidity > 65:
            if 'hot' in temperature_tags:
                conditions.extend(['muggy', 'oppressive'])
            conditions.append('humid(ity)?')
        self.cached_weather_tags = (
            conditions + wind_conditions + temperature_tags)
        self.cached_weather_tags_at = datetime.now()
        return self.cached_weather_tags

    def construct_search(self, artist=None, title=None, tags=None,
                         filename=None, restrictions=None):
        """Construct a search based on several criteria."""
        if filename:
            return self.player_construct_file_search(
                filename, restrictions)
        if title:
            return self.player_construct_track_search(
                artist, title, restrictions)
        if artist:
            return self.player_construct_artist_search(
                artist, restrictions)
        if tags:
            return self.player_construct_tag_search(
                tags, restrictions)

    def fill_queue(self):
        """Search for appropriate songs and put them in the queue."""
        if self.queue_needs_songs() or self.desired_queue_length == 0:
            self.queue_song()

    def queue_song(self):
        """Queue a single track."""
        self.running = True
        self.last_songs = self.get_last_songs()
        song = self.last_song = self.last_songs.pop()
        filename = song.get_filename()
        try:
            if not isinstance(filename, unicode):
                filename = unicode(filename, 'utf-8')
            if self.has_mirage and self.use_mirage:
                self.log('Analyzing: %s' % filename)
                self.similarity.analyze_track(
                    filename, 3, reply_handler=self.analyzed,
                    error_handler=self.error_handler, timeout=TIMEOUT)
            else:
                self.mirage_reply_handler([])
        except UnicodeDecodeError:
            self.log('Could not decode filename: %r' % filename)

    def analyzed(self):
        """Handler for analyzed track."""
        song = self.last_song
        excluded_filenames = []
        for other in self.get_artists_track_filenames(song.get_artists()):
            if isinstance(other, unicode):
                excluded_filenames.append(other)
            else:
                try:
                    excluded_filenames.append(unicode(other, 'utf-8'))
                except UnicodeDecodeError:
                    self.log('Could not decode filename: %r' % other)
        filename = song.get_filename()
        try:
            if not isinstance(filename, unicode):
                filename = unicode(filename, 'utf-8')
            if self.has_mirage and self.use_mirage:
                self.log('Get similar tracks for: %s' % filename)
                self.similarity.get_ordered_mirage_tracks(
                    filename, excluded_filenames, self.number,
                    reply_handler=self.mirage_reply_handler,
                    error_handler=self.error_handler, timeout=TIMEOUT)
            else:
                self.mirage_reply_handler([])
        except UnicodeDecodeError:
            self.log('Could not decode filename: %r' % filename)

    def done(self):
        """Analyze the last song and stop."""
        song = self.get_last_songs()[-1]
        filename = song.get_filename()
        try:
            if not isinstance(filename, unicode):
                filename = unicode(filename, 'utf-8')
            self.log('Analyzing: %s' % filename)
            if self.has_mirage and self.use_mirage:
                self.similarity.analyze_track(
                    filename, 3, reply_handler=NO_OP, error_handler=NO_OP,
                    timeout=TIMEOUT)
        except UnicodeDecodeError:
            self.log('Could not decode filename: %r' % filename)
        self.running = False

    def mirage_reply_handler(self, results):
        """Handler for (mirage) similar tracks returned from dbus."""
        self.player_execute_async(
            self._mirage_reply_handler, results=results)

    def _mirage_reply_handler(self, results=None):
        """Exexute processing asynchronous."""
        self.found = False
        if results:
            for _ in self.process_results([{'score': match,
                                            'filename': filename,
                                            'loved': l}
                                           for match, filename, l in results]):
                yield
        if self.found:
            if not self.queue_needs_songs():
                self.done()
                return
            self.queue_song()
            return
        artist_name = self.last_song.get_artist()
        title = self.last_song.get_title()
        if self.use_lastfm:
            if artist_name and title:
                self.log(
                    'Get similar tracks for: %s - %s' % (artist_name, title))
                self.similarity.get_ordered_similar_tracks(
                    artist_name, title,
                    reply_handler=self.similar_tracks_handler,
                    error_handler=self.error_handler, timeout=TIMEOUT)
            else:
                self.similar_tracks_handler([])
        else:
            self.similar_artists_handler([])

    def similar_tracks_handler(self, results):
        """Handler for similar tracks returned from dbus."""
        self.player_execute_async(
            self._similar_tracks_handler, results=results)

    def _similar_tracks_handler(self, results=None):
        """Exexute processing asynchronous."""
        self.found = False
        for _ in self.process_results([{'score': match, 'artist': artist,
                                        'title': title} for match, artist,
                                       title in results], invert_scores=True):
            yield
        if self.found:
            if not self.queue_needs_songs():
                self.done()
                return
            self.queue_song()
            return
        artists = [a.encode('utf-8') for a in self.last_song.get_artists()]
        self.log('Get similar artists for %s' % artists)
        self.similarity.get_ordered_similar_artists(
            artists,
            reply_handler=self.similar_artists_handler,
            error_handler=self.error_handler, timeout=TIMEOUT)

    def similar_artists_handler(self, results):
        """Handler for similar artists returned from dbus."""
        self.player_execute_async(
            self._similar_artists_handler, results=results)

    def _similar_artists_handler(self, results=None):
        """Exexute processing asynchronous."""
        self.found = False
        if results:
            for _ in self.process_results([{'score': match, 'artist': artist}
                                           for match, artist in results],
                                          invert_scores=True):
                yield
        if self.found:
            if not self.queue_needs_songs():
                self.done()
                return
            self.queue_song()
            return
        if self.use_groupings:
            for _ in self.process_results(
                    self.get_ordered_similar_by_tag(self.last_song),
                    invert_scores=True):
                yield
            if self.found:
                if not self.queue_needs_songs():
                    self.done()
                    return
                self.queue_song()
                return
        if not self.last_songs:
            self.running = False
            return
        song = self.last_song = self.last_songs.pop()
        filename = song.get_filename()
        try:
            if not isinstance(filename, unicode):
                filename = unicode(filename, 'utf-8')
            self.log('Analyzing: %s' % filename)
            if self.has_mirage and self.use_mirage:
                self.similarity.analyze_track(
                    filename, 3, reply_handler=self.analyzed,
                    error_handler=self.error_handler, timeout=TIMEOUT)
            else:
                self.mirage_reply_handler([])
        except UnicodeDecodeError:
            self.log('Could not decode filename: %r' % filename)

    def satisfies(self, song, criteria):
        """Check whether the song satisfies any of the criteria."""
        filename = criteria.get('filename')
        if filename:
            return filename == song.get_filename()
        title = criteria.get('title')
        artist = criteria.get('artist')
        if title:
            return (
                song.get_title().lower() == title.lower()
                and song.get_artist().lower() == artist.lower())
        if artist:
            return artist.lower() in [a.lower() for a in song.get_artists()]
        tags = criteria.get('tags')
        song_tags = song.get_tags()
        for tag in tags:
            if (tag in song_tags
                    or 'artist:%s' % (tag,) in song_tags
                    or 'album:%s' % (tag,) in song_tags):
                return True
        return False

    def search_database(self, results):
        """Do a batch search for several songs at once."""
        searches = [
            self.construct_search(
                artist=result.get('artist'), title=result.get('title'),
                filename=result.get('filename'), tags=result.get('tags'))
            for result in results]
        for search in searches:
            if self.restrictions:
                search = '&(%s,%s)' % (search, self.restrictions)
            songs = self.player_search(search)
            for song in songs:
                for result in results:
                    if self.satisfies(song, result):
                        result['song'] = song
                        yield

    def adjust_scores(self, results, invert_scores):
        """Adjust scores based on similarity with previous song and context."""
        context = Context(
            date=self.eoq,
            location=self.location,
            geohash=self.geohash,
            birthdays=self.birthdays,
            last_song=self.last_song,
            nearby_artists=self.nearby_artists,
            southern_hemisphere=self.southern_hemisphere,
            weather_tags=self.get_weather_tags(),
            extra_context=self.extra_context)
        maximum_score = max(result['score'] for result in results) + 1
        for result in results[:]:
            if not 'song' in result:
                results.remove(result)
                continue
            if invert_scores:
                result['score'] = maximum_score - result['score']
            context.adjust_score(result)
            yield

    def process_results(self, results, invert_scores=False):
        """Process results and queue best one(s)."""
        if not results:
            return
        for _ in self.search_database(results):
            yield
        for _ in self.adjust_scores(results, invert_scores):
            yield
        if not results:
            return
        for number, result in enumerate(sorted(results,
                                               key=lambda x: x['score'])):
            song = result['song']
            self.log_lookup(number, result)
            frequency = song.get_play_frequency()
            if frequency is NotImplemented:
                frequency = 1
            rating = song.get_rating()
            if rating is NotImplemented:
                rating = THRESHOLD
            self.log("score: %.5f, play frequency %.5f" % (rating, frequency))
            if frequency > 0 and random.random() > rating - frequency:
                continue

            if self.maybe_enqueue_album(song):
                self.found = True
                return

            if not self.disallowed(song):
                self.player_enqueue(song)
                self.found = True
                return


    def log_lookup(self, number, result):
        look_for = unicode(result.get('artist', ''))
        if look_for:
            title = unicode(result.get('title', ''))
            if title:
                look_for += ' - ' + title
        elif 'filename' in result:
            look_for = unicode(result['filename'])
        elif 'tags' in result:
            look_for = result['tags']
        else:
            self.log(repr(result))
            look_for = unicode(result)
        self.log('%03d: %06d %s' % (
            number + 1, result.get('score', 0), look_for))

    def maybe_enqueue_album(self, song):
        """Determine if a whole album should be queued, and do so."""
        if (self.whole_albums and song.get_tracknumber() == 1
                and random.random() > .5):
            album = song.get_album()
            album_artist = song.get_album_artist()
            album_id = song.get_musicbrainz_albumid()
            if album and album.lower() not in BANNED_ALBUMS:
                return self.enqueue_album(album, album_artist, album_id)

        return False

    def enqueue_album(self, album, album_artist, album_id):
        """Try to enqueue whole album."""
        search = self.player_construct_album_search(
            album=album, album_artist=album_artist, album_id=album_id)
        songs = sorted(
            [(song.get_discnumber(), song.get_tracknumber(),
                song)for song in self.player_search(search)])
        if songs and not any([self.disallowed(song[2]) for song in songs]):
            for _, _, song in songs:
                self.player_enqueue(song)
            return True
        return False

    def get_blocked_artists(self):
        """Get a list of blocked artists."""
        blocked = self.song.get_artists()
        for song in self.get_last_songs():
            blocked.extend(song.get_artists())
        return list(self._blocked_artists) + blocked

    def get_last_songs(self):
        """Return the currently playing song plus the songs in the queue."""
        queue = self.player_get_songs_in_queue() or []
        return [self.song] + queue

    def get_ordered_similar_by_tag(self, last_song):
        """Get similar tracks by tag."""
        tag_set = set(last_song.get_non_geo_tags())
        if not tag_set:
            return []
        search = self.construct_search(
            tags=list(tag_set), restrictions=self.restrictions)
        songs = sorted(
            [(tag_score(song, tag_set), song) for song in
             self.player_search(search)], reverse=True)
        return [
            {'score': score, 'filename': song.get_filename()} for
            score, song in songs]
