"""AutoQueue: an automatic queueing plugin library.
version 0.3

Copyright 2007-2011 Eric Casteleijn <thisfred@gmail.com>,
                    Daniel Nouri <daniel.nouri@gmail.com>
                    Jasper OpdeCoul <jasper.opdecoul@gmail.com>
                    Graham White

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

import dbus
import os
import random

from abc import ABCMeta, abstractmethod
from dbus.mainloop.glib import DBusGMainLoop
from collections import deque
from datetime import datetime, timedelta
from cPickle import Pickler, Unpickler

try:
    import pywapi
    WEATHER = True
except ImportError:
    WEATHER = False

try:
    import geohash
    GEOHASH = True
except:
    GEOHASH = False

DBusGMainLoop(set_as_default=True)

try:
    import xdg.BaseDirectory
    XDG = True
except ImportError:
    XDG = False

THRESHOLD = .5

TIMEOUT = 3000
FIVE_MINUTES = timedelta(0, 300)

NO_OP = lambda *a, **kw: None

BANNED_ALBUMS = [
    'ep', 'greatest hits', 'demo', 'the best of', 'the very best of', 'live',
    'demos', 'self titled', 'untitled album', '[non-album tracks]', 'single',
    '7"', 'covers']

SEASONS = ['winter', 'spring', 'summer', 'autumn']
MONTHS = [
    'january', 'february', 'march', 'april', 'may', 'june', 'july', 'august',
    'september', 'october', 'november', 'december']
DAYS = [
    'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday',
    'sunday']
TIMES = ['night', 'morning', 'afternoon']
EASTERS = [
    datetime(2012, 4, 8), datetime(2013, 3, 31), datetime(2014, 4, 20),
    datetime(2015, 4, 5), datetime(2016, 3, 27), datetime(2017, 4, 16),
    datetime(2018, 4, 1), datetime(2019, 4, 21), datetime(2020, 4, 12),
    datetime(2021, 4, 4), datetime(2022, 4, 17)]


def get_stripped_tags(last_song):
    """Return a set of stripped tags."""
    tags = last_song.get_tags()
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
    def get_title(self):
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


def geo_score(song, tags):
    if not tags:
        return 0
    song_tags = get_stripped_tags(song)
    if not song_tags:
        return 0
    geohashes = [t.split(':')[1] for t in tags if t.startswith('geohash:')]
    if GEOHASH:
        for h in geohashes[:]:
            geohashes.extend(geohash.neighbors(h))
    other_geohashes = [
        t.split(':')[1] for t in song_tags if t.startswith('geohash:')]
    if GEOHASH:
        for h in other_geohashes[:]:
            other_geohashes.extend(geohash.neighbors(h))
    if not (geohashes and other_geohashes):
        return 0
    longest_common = 0
    for ghash in geohashes:
        for other in other_geohashes:
            if ghash[0] != other[0]:
                continue
            shortest = min(len(ghash), len(other))
            i = 0
            while (i < shortest and ghash[i] == other[i]):
                i += 1
            if i > longest_common:
                longest_common = i
    return 1 - (1.0 / (2 ** longest_common))


def tag_score(song, tags):
    """Calculate similarity score by tags."""
    if not tags:
        return 0
    song_tags = get_stripped_tags(song)
    if not song_tags:
        return 0
    ng_tags = {
        t for t in tags if not (t.startswith('geohash:') or t == 'geotagged')}
    ng_song_tags = {
        t for t in song_tags if not
        (t.startswith('geohash:') or t == 'geotagged')}
    if ng_song_tags or ng_song_tags:
        score = (
            len(ng_song_tags & ng_tags) /
            float(len(ng_song_tags | ng_tags) + 1))
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
        self.cached_misses = deque([])
        self.running = False
        self.verbose = False
        self.song = None
        self.restrictions = None
        self.extra_context = None
        self.use_mirage = True
        self.whole_albums = True
        self.shuffle = True
        self.contextualize = True
        self.southern_hemisphere = False
        self.use_lastfm = True
        self.use_groupings = True
        self.get_blocked_artists_pickle()
        self.last_songs = []
        self.last_song = None
        self.found = None
        self.location = ''
        self.geohash = ''
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
        excluded_filenames = []
        for filename in self.get_artists_track_filenames(song.get_artists()):
            if isinstance(filename, unicode):
                excluded_filenames.append(filename)
            else:
                try:
                    excluded_filenames.append(unicode(filename, 'utf-8'))
                except UnicodeDecodeError:
                    self.log('Could not decode filename: %r' % filename)
        filename = song.get_filename()
        try:
            if not isinstance(filename, unicode):
                filename = unicode(filename, 'utf-8')
            excluded_filenames = excluded_filenames or [filename]
            self.log('Analyzing %s' % filename)
            if self.has_mirage:
                self.similarity.analyze_track(
                    filename, True, excluded_filenames, 2,
                    reply_handler=NO_OP, error_handler=NO_OP, timeout=TIMEOUT)
        except UnicodeDecodeError:
            self.log('Could not decode filename: %r' % filename)

    def on_song_started(self, song):
        """Should be called by the plugin when a new song starts.

        If the right conditions apply, we start looking for new songs
        to queue.

        """
        if song is None:
            return
        self.song = song
        if self.running:
            return
        if self.desired_queue_length == 0 or self.queue_needs_songs():
            self.fill_queue()
        self.unblock_artists()

    def queue_needs_songs(self):
        """Determine whether the queue needs more songs added."""
        queue_length = self.player_get_queue_length()
        return queue_length < self.desired_queue_length

    @property
    def eoq(self):
        return datetime.now() + timedelta(0, self.player_get_queue_length())

    def exclusive_search(self, term, terms, alt=None):
        """Return a search that searches for term but not the other terms."""
        search = []
        not_search = []
        not_terms = [t for t in terms if not t == term]
        for nterm in not_terms:
            not_search.extend(
                ['!grouping=/^%ss?$/' % nterm, '!title=/\\b%ss?\\b/' % nterm])
        if alt:
            search.extend([
                'grouping=/^%ss?$/' % term, 'title=/\\b%ss?\\b/' % term,
                'grouping=/^%ss?$/' % alt, 'title=/\\b%ss?\\b/' % alt])
        else:
            search.extend([
                'grouping=/^%ss?$/' % term, 'title=/\\b%ss?\\b/' % term])
        return search, not_search

    def get_context_restrictions(self):
        """Get context filters."""
        eoq = self.eoq
        hour = eoq.hour
        year = eoq.year
        mar_21 = datetime(year, 3, 21)
        jun_21 = datetime(year, 6, 21)
        sep_21 = datetime(year, 9, 21)
        dec_21 = datetime(year, 12, 21)
        month = eoq.month
        weekday = eoq.isoweekday()
        day_name = DAYS[weekday - 1]
        day = eoq.day
        filters = [
            'grouping="%d"' % year,
            'grouping="%d-%02d-%02d"' % (year, month, day),
            'grouping="%02d-%02d"' % (month, day)]
        if month == 12:
            # December is for retrospection
            filters.append('~year=%d' % year)
        not_filters = []
        search, not_search = self.exclusive_search(day_name, DAYS)
        filters.extend(search)
        not_filters.extend(not_search)
        month_name = MONTHS[month - 1]
        search, not_search = self.exclusive_search(month_name, MONTHS)
        filters.extend(search)
        not_filters.extend(not_search)
        if weekday >= 5:
            filters.extend(
                ['grouping=/^weekends?$/', 'title=/\\bweekends?\\b/'])
        if eoq <= mar_21 or eoq >= dec_21:
            if self.southern_hemisphere:
                season = 'summer'
            else:
                season = 'winter'
            search, not_search = self.exclusive_search(season, SEASONS)
            filters.extend(search)
            not_filters.extend(not_search)
        if eoq >= mar_21 and eoq <= jun_21:
            if self.southern_hemisphere:
                season = 'autumn'
            else:
                season = 'spring'
            search, not_search = self.exclusive_search(season, SEASONS)
            filters.extend(search)
            not_filters.extend(not_search)
            filters.extend(search)
            not_filters.extend(not_search)
        if eoq >= jun_21 and eoq <= sep_21:
            if self.southern_hemisphere:
                season = 'winter'
            else:
                season = 'summer'
            search, not_search = self.exclusive_search(season, SEASONS)
            filters.extend(search)
            not_filters.extend(not_search)
        if eoq >= sep_21 and eoq <= dec_21:
            if self.southern_hemisphere:
                season = 'spring'
            else:
                season = 'autumn'
            search, not_search = self.exclusive_search(season, SEASONS)
            filters.extend(search)
            not_filters.extend(not_search)
        if hour <= 6 or hour >= 18:
            search, not_search = self.exclusive_search(
                'night', TIMES, alt='evening')
            filters.extend(search)
            not_filters.extend(not_search)
            if hour >= 18 and hour < 22:
                not_filters.extend(['!title=/\\blate\\b/', '!grouping="late"'])
            else:
                not_filters.extend(
                    ['!title=/\\bearly\\b/', '!grouping="early"'])
        if hour >= 6 and hour < 12:
            search, not_search = self.exclusive_search('morning', TIMES)
            filters.extend(search)
            not_filters.extend(not_search)
            if hour < 10:
                not_filters.extend(['!title=/\\blate\\b/', '!grouping="late"'])
            else:
                not_filters.extend([
                    '!title=/\\bearly\\b/', '!grouping="early"'])
        if hour >= 12 and hour < 18:
            search, not_search = self.exclusive_search('afternoon', TIMES)
            filters.extend(search)
            not_filters.extend(not_search)
            if hour < 16:
                not_filters.extend(['!title=/\\blate\\b/', '!grouping="late"'])
            else:
                not_filters.extend([
                    '!title=/\\bearly\\b/', '!grouping="early"'])
        if month == 12 and day >= 20 and day <= 27:
            filters.extend([
               'grouping="christmas"', 'title=/\\bchristmas\\b/'])
        else:
            not_filters.extend([
               '!grouping="christmas"', '!title=/\\bchristmas\\b/'])
        if (month == 12 and day >= 26) or month == 1 and day == 1:
            filters.extend([
                'grouping="kwanzaa"', 'title=/\\bkwanzaa\\b/'])
        if (month == 12 and day >= 27) or (month == 1 and day <= 7):
            filters.extend([
                'grouping="new year"', 'title="/\\bnew years?\\b/"'])
        if (month == 10 and day >= 27) or (month == 11 and day <= 2):
            filters.extend([
                'grouping="halloween"', 'title=/\\bhalloween\\b/',
                'grouping="hallowe\'en"', 'title=/\\bhallowe\\\'en\\b/',
                'grouping=all hallow\'s', 'title=/\\ball hallow\\\'s\\b/',
                'grouping="monsters"', 'grouping="horror"'])
        for easter in EASTERS:
            delta = eoq - easter
            days_after_easter = delta.days
            if abs(days_after_easter) < 5:
                filters.extend([
                    'grouping="easter"', 'title=/\\beaster\\b/'])
            if days_after_easter == -47:
                filters.extend([
                    'grouping="shrove tuesday"',
                    'grouping="mardi gras"', 'title=/\\bmardi gras\\b/'])
            if days_after_easter == -46:
                filters.extend(['grouping="ash wednesday"'])
            if days_after_easter == -7:
                filters.extend(['grouping="palm sunday"'])
            if days_after_easter == -3:
                filters.extend(['grouping="maundy thursday"'])
            if days_after_easter == -2:
                filters.extend(['grouping="good friday"'])
            if days_after_easter == 39:
                filters.extend([
                    'grouping=ascension', 'title=/\\bascension\\b/'])
            if days_after_easter == 49:
                filters.extend([
                    'grouping=pentecost', 'title=/\\bpentecost\\b/'])
            if days_after_easter == 50:
                filters.extend(['grouping="whit monday"'])
            if days_after_easter == 56:
                filters.extend([
                    'grouping=all saints', 'title=/\\ball saints\\b/'])
        if month == 11 and day == 11:
            filters.extend([
                'grouping="armistice day"', 'title=/\\barmistice day\\b/',
                'grouping="veterans day"', 'title=/\\bveterans?\\b/',
                'grouping="veterans"'])
        elif month == 8 and day == 15:
            filters.extend([
                'grouping=assumption', 'title=/\\bassumption\\b/'])
        elif month == 7 and day == 4:
            filters.extend([
                'grouping="independence"', 'title=/\\bindependence\\b/'])
        elif month == 2 and day == 2:
            filters.extend([
                'grouping="groundhog day"', 'title=/\\bgroundhog day\\b/'])
        elif month == 2 and day == 14:
            filters.extend([
                'grouping=valentine', 'title=valentine'])
        elif month == 4 and day == 1:
            filters.extend([
                'grouping=april fool', 'title=april fool'])
        elif month == 5 and day == 5:
            filters.extend([
                'grouping="cinco de mayo"', 'title=/\\bcinco de mayo\\b/',
                'grouping="mexico"', 'title=/\\bmexico\\b/'])
        elif (month == 6 or month == 12) and day == 21:
            filters.extend([
                'grouping=/solstices?/', 'title=/\\bsolstices?\\b/'])
        elif month == 9 and day == 11:
            filters.extend(['grouping="9/11"', 'title="9/11"'])
        for name_date in self.birthdays.split(','):
            name, date = name_date.strip().split(':')
            if date.strip() == '%02d/%02d' % (month, day):
                filters.extend([
                    'grouping="birthdays"', 'title=/\\bbirthdays?\\b/',
                    'grouping="%s"' % name.strip(), 'title=/\\b%s\\b/' %
                    name.strip()])
        if self.location:
            city, state_country = self.location.split(',')
            city = city.strip().lower()
            state_country = state_country.strip().lower()
            filters.extend([
                'grouping=/^(.*:)?%s$/' % city, 'title=/\\b%s\\b/' % city,
                'grouping=/^(.*:)?%s$/' % state_country, 'title=/\\b%s\\b/' %
                state_country])
            if WEATHER:
                weather_tags = self.get_weather_tags()
                for condition in weather_tags:
                    if condition:
                        filters.extend([
                            'grouping=/\\b%s\\b/' % condition,
                            'title=/\\b%s\\b/' % condition])
        if self.geohash:
            filters.append('grouping=/^geohash:%s/' % (self.geohash[:2],))
        if self.extra_context:
            filters.append(self.extra_context)
        last_song = self.last_song
        for tag in get_stripped_tags(last_song):
            filters.append('grouping=/^(.*:)?%s$/' % tag)
        context_restrictions = '&(|(%s),&(%s))' % (
            ','.join(filters), ','.join(not_filters))
        return context_restrictions

    def get_weather_tags(self):
        if self.cached_weather_tags and (datetime.now() <
                                         self.cached_weather_tags_at +
                                         FIVE_MINUTES):
            return self.cached_weather_tags
        try:
            weather = pywapi.get_weather_from_google(
                'weather=%s' % self.location)
        except Exception, e:
            self.log(e)
            return []
        condition = weather.get(
            'current_conditions', {}).get('condition', '').lower()
        if condition:
            conditions = [condition]
            unmodified = condition.split()[-1]
            if unmodified not in conditions:
                conditions.append(unmodified)
            if unmodified[-1] == 'y':
                if unmodified[-2] == unmodified[-3]:
                    conditions.append(unmodified[:-2] + 's?')
                else:
                    conditions.append(unmodified[:-1] + 's?')
        else:
            conditions = []
        temperature = weather.get('current_conditions', {}).get('temp_c', '')
        temperature_tags = []
        if temperature:
            degrees_c = int(temperature)
            if degrees_c <= 0:
                temperature_tags.extend(['freezing', 'frozen', 'ice'])
            if degrees_c <= 10:
                temperature_tags.extend(['cold'])
            if degrees_c >= 30:
                temperature_tags.extend(['hot', 'heat'])
        wind = weather.get('current_conditions', {}).get('wind_condition', '')
        if wind:
            direction = wind.split()[1]
            if direction[-1] == 'N':
                wind_direction = 'northerly'
            elif direction[-1] == 'E':
                wind_direction = 'easterly'
            elif direction[-1] == 'S':
                wind_direction = 'southerly'
            else:
                wind_direction = 'westerly'
            prefix = ''
            for i in range(len(direction) - 1):
                if direction[i] == 'N':
                    prefix += 'north\W*'
                elif direction[i] == 'E':
                    prefix += 'east\W*'
                elif direction[i] == 'S':
                    prefix += 'south\W*'
                elif direction[i] == 'W':
                    prefix += 'west\W*'
            wind_direction = prefix + wind_direction + ' winds?'
            speed = int(wind.split()[-2])
            if speed < 1:
                wind_direction = ''
                wind_conditions = ['calms?']
            elif speed <= 30:
                wind_conditions = ['breezes?', 'breezy']
            elif speed <= 38:
                wind_conditions = ['winds?', 'windy']
            elif speed <= 54:
                wind_conditions = ['winds?', 'windy', 'gales?']
            elif speed <= 72:
                wind_conditions = [
                    'winds?', 'windy', 'storms?', 'stormy']
            else:
                wind_conditions = [
                    'winds?', 'windy', 'storms?', 'hurricanes?']
        else:
            wind_conditions = []
            wind_direction = ''
        self.cached_weather_tags = (
            conditions + wind_conditions + temperature_tags + [wind_direction])
        self.cached_weather_tags_at = datetime.now()
        print self.cached_weather_tags
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

    def search_and_filter(self, artist=None, title=None, filename=None,
                          tags=None, context_filter=False):
        """Perform a search and filter the results."""
        restrictions = self.restrictions
        if context_filter:
            context_restrictions = self.get_context_restrictions()
            if restrictions:
                restrictions = '&(%s,%s)' % (
                    restrictions, context_restrictions)
            else:
                restrictions = context_restrictions
        cache_key = (artist, title, filename, tags, restrictions)
        if cache_key in self.cached_misses:
            self.cached_misses.remove(cache_key)
            self.cached_misses.append(cache_key)
            return None
        search = self.construct_search(
            artist=artist, title=title, filename=filename, tags=tags,
            restrictions=restrictions)
        songs = self.player_search(search)
        if not songs:
            self.cached_misses.append(cache_key)
            if not restrictions:
                if filename:
                    if not isinstance(filename, unicode):
                        try:
                            filename = filename.decode('utf-8')
                        except UnicodeDecodeError:
                            self.log('failed to decode filename %r' % filename)
                    if self.has_mirage and self.use_mirage:
                        self.log('Remove similarity for %s' % filename)
                        self.similarity.remove_track_by_filename(
                            filename, reply_handler=NO_OP,
                            error_handler=NO_OP)
                elif (artist and title):
                    self.log('Remove %s - %s' % (artist, title))
                    self.similarity.remove_track(
                        artist, title, reply_handler=NO_OP,
                        error_handler=NO_OP)
                elif artist:
                    self.log('Remove %s' % artist)
                    self.similarity.remove_artist(
                        artist, reply_handler=NO_OP,
                        error_handler=NO_OP)
            return
        while songs:
            tag_set = get_stripped_tags(self.last_song)
            song = random.choice(songs)
            songs.remove(song)
            if not self.disallowed(song):
                rating = song.get_rating()
                if rating is NotImplemented:
                    rating = THRESHOLD
                frequency = song.get_play_frequency()
                score = tag_score(song, tag_set)
                if score:
                    rating += (1 - rating) * score
                score2 = geo_score(song, tag_set)
                if score2:
                    rating += (1 - rating) * score2
                if frequency is NotImplemented:
                    frequency = 0
                self.log("rating: %.5f, play frequency %.5f" % (
                    rating, frequency))
                if frequency > 0 and random.random() > rating - frequency:
                    continue
                return song
        self.cached_misses.append(cache_key)
        while len(self.cached_misses) > 5000:
            self.cached_misses.popleft()

    def fill_queue(self):
        """Search for appropriate songs and put them in the queue."""
        if self.queue_needs_songs() or self.desired_queue_length == 0:
            self.queue_song()

    def queue_song(self):
        """Queue a single track."""
        self.running = True
        self.found = None
        self.last_songs = self.get_last_songs()
        song = self.last_song = self.last_songs.pop()
        excluded_filenames = []
        for filename in self.get_artists_track_filenames(song.get_artists()):
            if isinstance(filename, unicode):
                excluded_filenames.append(filename)
            else:
                try:
                    excluded_filenames.append(unicode(filename, 'utf-8'))
                except UnicodeDecodeError:
                    self.log('Could not decode filename: %r' % filename)
        filename = song.get_filename()
        try:
            if not isinstance(filename, unicode):
                filename = unicode(filename, 'utf-8')
            excluded_filenames = excluded_filenames or [filename]
            if self.has_mirage and self.use_mirage:
                self.log('Analyzing: %s' % filename)
                self.similarity.analyze_track(
                    filename, True, excluded_filenames, 3,
                    reply_handler=self.analyzed,
                    error_handler=self.error_handler, timeout=TIMEOUT)
            else:
                self.mirage_reply_handler([])
        except UnicodeDecodeError:
            self.log('Could not decode filename: %r' % filename)

    def analyzed(self):
        """Handler for analyzed track."""
        filename = self.last_song.get_filename()
        try:
            if not isinstance(filename, unicode):
                filename = unicode(filename, 'utf-8')
            if self.has_mirage and self.use_mirage:
                self.log('Get similar tracks for: %s' % filename)
                self.similarity.get_ordered_mirage_tracks(
                    filename,
                    reply_handler=self.mirage_reply_handler,
                    error_handler=self.error_handler, timeout=TIMEOUT)
            else:
                self.mirage_reply_handler([])
        except UnicodeDecodeError:
            self.log('Could not decode filename: %r' % filename)

    def done(self):
        """Analyze the last song and stop."""
        song = self.get_last_songs()[-1]
        excluded_filenames = []
        for filename in self.get_artists_track_filenames(song.get_artists()):
            if isinstance(filename, unicode):
                excluded_filenames.append(filename)
            else:
                try:
                    excluded_filenames.append(unicode(filename, 'utf-8'))
                except UnicodeDecodeError:
                    self.log('Could not decode filename: %r' % filename)
        filename = song.get_filename()
        try:
            if not isinstance(filename, unicode):
                filename = unicode(filename, 'utf-8')
            excluded_filenames = excluded_filenames or [filename]
            self.log('Analyzing: %s' % filename)
            if self.has_mirage and self.use_mirage:
                self.similarity.analyze_track(
                    filename, True, excluded_filenames, 3,
                    reply_handler=NO_OP,
                    error_handler=NO_OP, timeout=TIMEOUT)
        except UnicodeDecodeError:
            self.log('Could not decode filename: %r' % filename)
        self.running = False

    def mirage_reply_handler(self, results):
        """Handler for (mirage) similar tracks returned from dbus."""
        self.player_execute_async(
            self._mirage_reply_handler, results=results)

    def _mirage_reply_handler(self, results=None):
        """Exexute processing asynchronous."""
        if results:
            for _ in self.process_results([
                    {'score': match, 'filename': filename} for match, filename
                    in results]):
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
        for _ in self.process_results([
                {'score': match, 'artist': artist, 'title': title} for
                match, artist, title in results]):
            yield
        if self.found:
            if not self.queue_needs_songs():
                self.done()
                return
            self.queue_song()
            return
        artists = self.last_song.get_artists()
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
        if results:
            for _ in self.process_results([
                    {'score': match, 'artist': artist} for
                    match, artist in results]):
                yield
        if self.found:
            if not self.queue_needs_songs():
                self.done()
                return
            self.queue_song()
            return
        if self.use_groupings:
            for _ in self.process_results(
                    self.get_ordered_similar_by_tag(self.last_song)):
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
        excluded_filenames = []
        for filename in self.get_artists_track_filenames(song.get_artists()):
            if isinstance(filename, unicode):
                excluded_filenames.append(filename)
            else:
                try:
                    excluded_filenames.append(unicode(filename, 'utf-8'))
                except UnicodeDecodeError:
                    self.log('Could not decode filename: %r' % filename)
        filename = song.get_filename()
        try:
            if not isinstance(filename, unicode):
                filename = unicode(filename, 'utf-8')
            excluded_filenames = excluded_filenames or [filename]
            self.log('Analyzing: %s' % filename)
            if self.has_mirage and self.use_mirage:
                self.similarity.analyze_track(
                    filename, True, excluded_filenames, 3,
                    reply_handler=self.analyzed,
                    error_handler=self.error_handler, timeout=TIMEOUT)
            else:
                self.mirage_reply_handler([])
        except UnicodeDecodeError:
            self.log('Could not decode filename: %r' % filename)

    def process_results(self, results):
        """Process similarity results from dbus."""
        if self.contextualize:
            if self.shuffle:
                random.shuffle(results)
            self.log("Context search.")
            for result in self._process_results(results, context_filter=True):
                yield
            if self.found:
                return
            self.log("Context free search.")
        if self.shuffle:
            random.shuffle(results)
        for result in self._process_results(results):
            yield

    def _process_results(self, results, context_filter=False):
        """Process and possibly filter results."""
        for number, result in enumerate(results):
            if self.shuffle and number >= 40:
                break
            if not result:
                continue
            yield
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
            artist = unicode(result.get('artist', ''))
            if artist:
                if artist in self.get_blocked_artists():
                    continue
            filename = unicode(result.get("filename", ''))
            tags = result.get("tags")
            if filename:
                self.found = self.search_and_filter(
                    filename=filename, context_filter=context_filter)
            elif tags:
                self.found = self.search_and_filter(
                    tags=tags, context_filter=context_filter)
            else:
                self.found = self.search_and_filter(
                    artist=unicode(result.get("artist", '')),
                    title=unicode(result.get("title", '')),
                    context_filter=context_filter)
            if self.found:
                break
        if self.found:
            if self.whole_albums:
                if self.found.get_tracknumber() == 1:
                    album = self.found.get_album()
                    album_artist = self.found.get_album_artist()
                    album_id = self.found.get_musicbrainz_albumid()
                    if album and album.lower() not in BANNED_ALBUMS:
                        search = self.player_construct_album_search(
                            album=album, album_artist=album_artist,
                            album_id=album_id)
                        songs = sorted(
                                [(song.get_discnumber(),
                                  song.get_tracknumber(), song)for song in
                                  self.player_search(search)])
                        if songs and not any([self.disallowed(song[2]) for song
                                              in songs]):
                            for _, _, song in songs:
                                self.player_enqueue(song)
                            return
            self.player_enqueue(self.found)

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
        tag_set = get_stripped_tags(last_song)
        search = self.construct_search(
            tags=list(tag_set), restrictions=self.restrictions)
        songs = sorted(
            [(tag_score(song, tag_set), song) for song in
             self.player_search(search)], reverse=True)
        return [
            {'score': score, 'filename': song.get_filename()} for
            score, song in songs]
