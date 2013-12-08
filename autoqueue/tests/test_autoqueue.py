# -*- coding: utf-8 -*-
"""Tests for autoqueue."""
from gi.repository import GObject
import unittest
from datetime import datetime
from xml.dom import minidom
from collections import deque
from autoqueue import SongBase, AutoQueueBase


# we have to do this or the tests break badly
GObject.threads_init()


FAKE_RESPONSES = {
    'http://ws.audioscrobbler.com/2.0/?method=track.getsimilar&artist='
    'joni+mitchell&track=carey&api_key=09d0975a99a4cab235b731d31abf0057':
    '../autoqueue/tests/testfiles/test1.xml',
    'http://ws.audioscrobbler.com/2.0/?method=artist.getsimilar&artist='
    'nina+simone&api_key=09d0975a99a4cab235b731d31abf0057':
    '../autoqueue/tests/testfiles/test2.xml',
    'http://ws.audioscrobbler.com/2.0/?method=track.getsimilar&artist='
    'nina+simone&track=i+think+it%27s+going+to+rain+today'
    '&api_key=09d0975a99a4cab235b731d31abf0057':
    '../autoqueue/tests/testfiles/test3.xml',
    'http://ws.audioscrobbler.com/2.0/?method=artist.getsimilar&artist='
    'joni+mitchell&api_key=09d0975a99a4cab235b731d31abf0057':
    '../autoqueue/tests/testfiles/test4.xml',
    'http://ws.audioscrobbler.com/2.0/?method=artist.getsimilar&artist='
    'habib+koit%C3%A9+%26+bamada&api_key=09d0975a99a4cab235b731d31abf0057':
    '../autoqueue/tests/testfiles/test5.xml'}


class FakePlayer(object):
    """Fake music player object."""
    def __init__(self, plugin_on_song_started):
        self.queue = []
        self.library = [
            ('nina simone', "i think it's going to rain today",
             ['forecasts', 'predictions', 'today', 'female vocals',
              'weather', 'rain']),
            ('joni mitchell', 'carey'),
            ('joanna newsom', 'peach, plum, pear'),
            ('leonard cohen', 'suzanne'),
            ('simon & garfunkel', 'song for the asking'),
            ('bob dylan', "the times they are a-changin'"),
            ('simon & garfunkel', 'keep the customer satisfied'),
            ('joanna newsom', 'sprout and the bean'),
            ('bob dylan', "blowin' in the wind",
             ['weather', 'wind', 'blowing', 'male vocals']),
            ('james taylor', 'fire and rain'),
            ('leonard cohen', 'famous blue raincoat'),
            ('al jarreau', 'jacaranda bougainvillea'),
            ('jimmy smith and wes montgomery', 'mellow mood'),
            ('marlena shaw', 'will i find my love today?'),
            ('minnie riperton', 'reasons'),
            ]
        self.plugin_on_song_started = plugin_on_song_started

    def satisfies_criteria(self, song, criteria):
        """Check that song satisfies search criteria."""
        positions = {'artist': 0, 'title': 1, 'tags': 2}
        for criterium in criteria:
            if criterium.startswith('not_'):
                ncriterium = criterium.split("_")[1]
                if ncriterium == 'tags':
                    if len(song) < 3:
                        continue
                    if set(criteria[ncriterium]) < set(
                        song[positions[ncriterium]]):
                        return False
                else:
                    if song[positions[ncriterium]] in criteria[criterium]:
                        return False
            else:
                if criterium == 'tags':
                    if len(song) < 3:
                        return False
                    if not set(criteria[criterium]) < set(
                        song[positions[criterium]]):
                        return False
                else:
                    if criteria[criterium] != song[positions[criterium]]:
                        return False
        return True

    def play_song_from_queue(self):
        """Fake playing a song from the queue."""
        func = self.plugin_on_song_started
        queue_song = self.queue.pop(0)
        func(queue_song)


class FakeSong(SongBase):
    """Fake song object."""

    # pylint: disable=W0231
    def __init__(self, artist, title, tags=None, performers=None,
                 filename=None):
        self.filename = filename
        self.artist = artist
        self.title = title
        self.tags = tags
        self.performers = performers or []
    # pylint: enable=W0231

    def get_artist(self):
        return self.artist.lower()

    def get_artists(self):
        return [self.artist.lower()] + [
            performer.lower() for performer in self.performers]

    def get_title(self):
        return self.title.lower()

    def get_tags(self):
        return self.tags

    def get_filename(self):
        return "/home/eric/ogg/%s/%s-%s.ogg" % (
            self.get_artist(), self.get_artist(), self.get_title())

    def get_length(self):
        return 180

    def get_playcount(self):
        return 0

    def get_last_started(self):
        return 0

    def get_rating(self):
        return .5


class FakeSimilarityService(object):
    """Fake similarity Service implementation."""

    def analyze_track(self, filename, add_neighbours, exclude_filenames,
                      priority, reply_handler=None, error_handler=None,
                      timeout=0):
        """Fake analyze."""
        reply_handler()

    def get_ordered_mirage_tracks(self, filename, reply_handler=None,
                                  error_handler=None, timeout=0):
        """Fake get_ordered_mirage_tracks."""
        reply_handler([])

    def get_ordered_similar_tracks(self, artist_name, title,
                                   reply_handler=None, error_handler=None,
                                   timeout=0):
        """Fake get similar tracks."""
        reply_handler([(715, 'joanna newsom', 'peach, plum, pear')])

    def last_fm_request(self, url):
        """Fake last.fm request."""
        urlfile = FAKE_RESPONSES.get(url)
        if not urlfile:
            return None
        stream = open(urlfile, 'r')
        try:
            xmldoc = minidom.parse(stream).documentElement
            return xmldoc
        except:  # pylint: disable=W0702
            return None


class FakeAutoQueue(AutoQueueBase):
    """Fake autoqueue plugin implementation."""

    def __init__(self):                 # pylint: disable=W0231
        self.connection = None
        self.player = FakePlayer(self.start)
        self.artist_block_time = 1
        self._blocked_artists = deque([])
        self._blocked_artists_times = deque([])
        self._cache_dir = None
        self.desired_queue_length = 0
        self.cached_misses = deque([])
        self.by_mirage = False
        self.by_tracks = True
        self.by_artists = True
        self.by_tags = True
        self.running = False
        self.verbose = False
        self.weed = False
        self.song = None
        self.restrictions = None
        self.prune_artists = []
        self.prune_titles = []
        self.prune_filenames = []
        self._rows = []
        self._nrows = []
        self.last_songs = []
        self.last_song = None
        self.found = None
        self.similarity = FakeSimilarityService()
        self.by_tags = True
        self.verbose = True

    def start(self, song):
        """Simulate song start."""
        self.on_song_started(song)

    def block_artist(self, artist_name):
        """Block songs by artist from being played for a while."""
        now = datetime.now()
        self._blocked_artists.append(artist_name)
        self._blocked_artists_times.append(now)
        self.log("Blocked artist: %s (%s)" % (
            artist_name,
            len(self._blocked_artists)))

    def player_set_variables_from_config(self):
        """Set configuration variables."""
        pass

    def player_construct_file_search(self, filename, restrictions=None):
        """Construct a search that looks for songs with this artist
        and title.

        """
        return NotImplemented

    def player_construct_track_search(self, artist, title, restrictions=None):
        """Construct a search that looks for songs with this artist
        and title.

        """
        search = {'artist': artist, 'title': title}
        if restrictions:
            search.update(restrictions)
        return search

    def player_construct_artist_search(self, artist, restrictions=None):
        """Construct a search that looks for songs with this artist."""
        search = {'artist': artist}
        if restrictions:
            search.update(restrictions)
        return search

    def player_construct_tag_search(self, tags, restrictions=None):
        """Construct a search that looks for songs with these
        tags.

        """
        exclude_artists = self.get_blocked_artists()
        search = {'tags': tags, 'not_artist': exclude_artists}
        if restrictions:
            search.update(restrictions)
        return search

    def player_get_queue_length(self):
        """Get the current length of the queue."""
        return sum([song.get_length() for song in self.player.queue])

    def player_enqueue(self, song):
        """Put the song at the end of the queue."""
        self.player.queue.append(song)

    def player_search(self, search):
        """Perform a player search."""
        return [
            FakeSong(*song) for song in self.player.library if
            self.player.satisfies_criteria(song, search)]

    def player_get_songs_in_queue(self):
        """Return (wrapped) song objects for the songs in the queue."""
        return self.player.queue


class TestAutoQueue(unittest.TestCase):
    """Test autoqueue functionality."""

    def setUp(self):
        self.autoqueue = FakeAutoQueue()

    def test_queue_needs_songs(self):
        """Test the queue_needs_songs method."""
        self.autoqueue.desired_queue_length = 4
        self.assertEqual(True, self.autoqueue.queue_needs_songs())
        test_song = FakeSong('Joni Mitchell', 'Carey')
        for _ in range(4):
            self.autoqueue.player_enqueue(test_song)
        self.assertEqual(False, self.autoqueue.queue_needs_songs())

    def test_on_song_started(self):
        """Test the on_song_started handler."""
        test_song = FakeSong('Joni Mitchell', 'Carey')
        self.autoqueue.start(test_song)
        songs_in_queue = self.autoqueue.player_get_songs_in_queue()
        self.assertEqual('joanna newsom', songs_in_queue[0].get_artist())
        self.assertEqual('peach, plum, pear', songs_in_queue[0].get_title())
