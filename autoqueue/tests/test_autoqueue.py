# -*- coding: utf-8 -*-
import gobject
import sqlite3
import unittest
from datetime import datetime, timedelta
from xml.dom import minidom
from autoqueue import SongBase, AutoQueueBase, Throttle

# we have to do this or the tests break badly
gobject.threads_init()

WAIT_BETWEEN_REQUESTS = timedelta(0,0,10)

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
        positions = {'artist':0, 'title':1, 'tags':2}
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
                    #print song, criteria
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
        func = self.plugin_on_song_started
        queue_song = self.queue.pop(0)
        func(queue_song)


class FakeSong(SongBase):
    def __init__(self, artist, title, tags=None, performers=None,
                 filename=None):
        self.filename = filename
        self.artist = artist
        self.title = title
        self.tags = tags
        self.performers = performers or []

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


class FakeAutoQueue(AutoQueueBase):
    def __init__(self):
        self.connection = None
        self.player = FakePlayer(self.start)
        super(FakeAutoQueue, self).__init__()
        self.by_tags = True
        self.verbose = True

    def start(self, song):
        """Simulate song start."""
        self.on_song_started(song)

    def get_db_path(self):
        return ":memory:"

    def get_database_connection(self):
        if self.connection:
            return self.connection
        self.connection = sqlite3.connect(":memory:")
        return self.connection

    def close_database_connection(self, connection):
        """Close the database connection."""
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

    def last_fm_request(self, url):
        urlfile = FAKE_RESPONSES.get(url)
        if not urlfile:
            return None
        stream = open(urlfile, 'r')
        try:
            xmldoc = minidom.parse(stream).documentElement
            return xmldoc
        except:
            return None

    def analyze_track(self, song, add_neighbours=False):
        yield


@Throttle(WAIT_BETWEEN_REQUESTS)
def throttled_method():
    return


@Throttle(timedelta(0))
def unthrottled_method():
    return


class TestAutoQueue(unittest.TestCase):
    def setUp(self):
        self.autoqueue = FakeAutoQueue()

    def test_get_database_connection(self):
        connection = self.autoqueue.get_database_connection()
        cursor = connection.cursor()
        cursor.execute("SELECT * FROM tracks;")
        rows = cursor.fetchall()
        self.assertEqual([], rows)

    def test_get_artist(self):
        artist = 'joni mitchell'
        row = self.autoqueue.get_artist(artist)
        self.assertEqual((artist, None), row[1:])

    def test_get_track(self):
        artist = "nina simone"
        title = "i think it's going to rain today"
        artist_id = self.autoqueue.get_artist(artist)[0]
        row = self.autoqueue.get_track(artist, title)
        self.assertEqual((artist_id, title, None), row[1:])

    def test_get_similar_artists_from_lastfm(self):
        artist = 'joni mitchell'
        artist_id = self.autoqueue.get_artist(artist)
        similar_artists = self.autoqueue.get_similar_artists_from_lastfm(
            artist, artist_id)
        td = [
            {'score': 10000, 'artist': u'rickie lee jones'},
            {'score': 9271, 'artist': u'carole king'},
            {'score': 8669, 'artist': u'ani difranco'},
            {'score': 8127, 'artist': u'joan baez'},
            {'score': 7473, 'artist': u'neil young'},
            {'score': 7051, 'artist': u'martha wainwright'},
            {'score': 7044, 'artist': u'indigo girls'},
            {'score': 6880, 'artist': u'james taylor'},
            {'score': 6705, 'artist': u'paul simon'},
            {'score': 6677, 'artist': u'dar williams'},
            {'score': 6404, 'artist': u'crosby, stills, nash & young'},
            {'score': 6229, 'artist': u'k.d. lang'},
            {'score': 6151, 'artist': u'simon & garfunkel'},
            {'score': 6064, 'artist': u'joan armatrading'},
            {'score': 5959, 'artist': u'patty griffin'},
            {'score': 5883, 'artist': u'leonard cohen'},
            {'score': 5840, 'artist': u'tim buckley'},
            {'score': 5702, 'artist': u'suzanne vega'},
            {'score': 5649, 'artist': u'janis ian'},
            {'score': 5591, 'artist': u'kate bush'},
            {'score': 5555, 'artist': u'cat stevens'},
            {'score': 5477, 'artist': u'neil young & crazy horse'}]
        sim = [track for track in similar_artists][:22]
        self.assertEqual(td, sim)
        artist = u'habib koité & bamada'
        row = self.autoqueue.get_artist(artist)
        artist_id = row[0]
        similar_artists = self.autoqueue.get_similar_artists_from_lastfm(
            artist, artist_id)
        sim = [track for track in similar_artists][:22]
        td = [
            {'score': 10000, 'artist': u'salif keita'},
            {'score': 9536, 'artist': u'mamou sidib\xe9'},
            {'score': 9330, 'artist': u'k\xe9l\xe9tigui diabat\xe9'},
            {'score': 9058, 'artist': u'ali farka tour\xe9'},
            {'score': 8917, 'artist': u'habib koit\xe9'},
            {'score': 8569, 'artist': u'amadou & mariam'},
            {'score': 5950, 'artist': u'tinariwen'},
            {'score': 5826, 'artist': u'boubacar traor\xe9'},
            {'score': 5371, 'artist': u'oliver mtukudzi'},
            {'score': 381, 'artist': u'super rail band'},
            {'score': 359, 'artist': u'lobi traor\xe9'},
            {'score': 358,
              'artist': u'ali farka tour\xe9 & toumani diabat\xe9'},
            {'score': 358, 'artist': u'tartit'},
            {'score': 355, 'artist': u'issa bagayogo'},
            {'score': 349, 'artist': u'kasse mady diabate'},
            {'score': 347, 'artist': u'rokia traor\xe9'},
            {'score': 346, 'artist': u'daby tour\xe9'},
            {'score': 346, 'artist': u'oumou sangar\xe9'},
            {'score': 340, 'artist': u'luciana souza'},
            {'score': 337, 'artist': u'kandia kouyate'},
            {'score': 326,
              'artist': u'ali farka tour\xe9 and ry cooder'},
            {'score': 318, 'artist': u'sali sidibe'}]
        self.assertEqual(td, sim)

    def test_get_similar_tracks_from_lastfm(self):
        artist = 'nina simone'
        title = "i think it's going to rain today"
        track = self.autoqueue.get_track(artist, title)
        track_id = track[0]
        similar_tracks = self.autoqueue.get_similar_tracks_from_lastfm(
            artist, title, track_id)
        td = [{'title': u'how long has this been going o',
                'score': 447, 'artist': u'ella fitzgerald'},
               {'title': u'our love is here to stay', 'score': 446,
                'artist': u'dinah washington'},
               {'title': u'love for sale', 'score': 444,
                'artist': u'dinah washington'},
               {'title': u'will i find my love today?', 'score': 443,
                'artist': u'marlena shaw'},
               {'title': u'a couple of loosers', 'score': 443,
                'artist': u'marlena shaw'},
               {'title': u'reasons', 'score': 438,
                'artist': u'minnie riperton'},
               {'title': u'sorry (digitally remastered 02)',
                'score': 438,
                'artist': u'natalie cole'},
               {'title': u'stand by (digitally remastered 02)',
                'score': 438, 'artist': u'natalie cole'},
               {'title': u'adventures in paradise', 'score': 436,
                'artist': u'minnie riperton'},
               {'title': u"i've got my love to keep me wa", 'score': 436,
                'artist': u'ella fitzgerald'},
               {'title': u'find him', 'score': 428,
                'artist': u'cassandra wilson'},
               {'title': u'almost like being in love (lp version)',
                'score': 428, 'artist': u'della reese'},
               {'title': u'jacaranda bougainvillea', 'score': 426,
                'artist': u'al jarreau'},
               {'title': u'mellow mood', 'score': 426,
                'artist': u'jimmy smith and wes montgomery'}]
        sim = [track for track in similar_tracks][:14]
        self.assertEqual(td, sim)

    def test_get_ordered_similar_artists(self):
        song = FakeSong('nina simone', 'ne me quitte pas')
        artist = song.get_artist()
        similar_artists = self.autoqueue.get_ordered_similar_artists(song)
        td = [
            {'score': 10000, 'artist': u'billie holiday'},
            {'score': 7934, 'artist': u'ella fitzgerald'},
            {'score': 7402, 'artist': u'sarah vaughan'},
            {'score': 6731, 'artist': u'dinah washington'},
            {'score': 6518, 'artist': u'madeleine peyroux'},
            {'score': 6042, 'artist': u'etta james'},
            {'score': 5065, 'artist': u'peggy lee'},
            {'score': 4984, 'artist': u'julie london'},
            {'score': 4905,
                     'artist': u'ella fitzgerald & louis armstrong'},
            {'score': 4887, 'artist': u'blossom dearie'}]
        for i, item in enumerate(td):
            self.assertEqual(td[i], similar_artists.next())
        row = self.autoqueue.get_artist(artist)
        self.assertEqual((artist, None), row[1:])
        artist = 'dionne warwick'
        row = self.autoqueue.get_artist(artist)
        self.assertEqual((artist, None), row[1:])

    def test_get_ordered_similar_tracks(self):
        song = FakeSong('joni mitchell', 'carey')
        artist = song.get_artist()
        title = song.get_title()
        similar_tracks = self.autoqueue.get_ordered_similar_tracks(song)
        td = [
            {'title': u'things behind the sun', 'score': 838,
             'artist': u'nick drake'},
            {'title': u'horn', 'score': 807, 'artist': u'nick drake'},
            {'title': u'peach, plum, pear', 'score': 715,
             'artist': u'joanna newsom'},
            {'title': u'suzanne', 'score': 700,
             'artist': u'leonard cohen'},
            {'title': u'sprout and the bean', 'score': 691,
             'artist': u'joanna newsom'},
            {'title': u"blowin' in the wind", 'score': 664,
             'artist': u'bob dylan'},
            {'title': u'famous blue raincoat', 'score': 635,
             'artist': u'leonard cohen'},
            {'title': u'song for the asking', 'score': 598,
             'artist': u'simon & garfunkel'},
            {'title': u"the times they are a-changin'", 'score': 593,
             'artist': u'bob dylan'},
            {'title': u'keep the customer satisfied', 'score': 535,
             'artist': u'simon & garfunkel'},
            {'title': u'peace train', 'score': 520,
             'artist': u'cat stevens'},
            {'title': u'fire and rain', 'score': 511,
             'artist': u'james taylor'},
            {'title': u'enough to be on your way', 'score': 451,
             'artist': u'james taylor'},
            {'title': u"that's the spirit", 'score': 449,
             'artist': u'judee sill'}]
        sim = [track for track in similar_tracks][:14]
        self.assertEqual(td, sim)
        artist_id = self.autoqueue.get_artist(artist)[0]
        row = self.autoqueue.get_track(artist, title)
        self.assertEqual((artist_id, title, None), row[1:])
        artist = 'leonard cohen'
        title = 'suzanne'
        artist_id = self.autoqueue.get_artist(artist)[0]
        row = self.autoqueue.get_track(artist, title)
        self.assertEqual((artist_id, title, None), row[1:])

    def test_queue_needs_songs(self):
        self.autoqueue.desired_queue_length = 4
        self.assertEqual(True, self.autoqueue.queue_needs_songs())
        test_song = FakeSong('Joni Mitchell', 'Carey')
        for i in range(4):
            self.autoqueue.player_enqueue(test_song)
        self.assertEqual(False, self.autoqueue.queue_needs_songs())

    def test_on_song_started(self):
        test_song = FakeSong('Joni Mitchell', 'Carey')
        self.autoqueue.start(test_song)
        songs_in_queue = self.autoqueue.player_get_songs_in_queue()
        self.assertEqual('joanna newsom', songs_in_queue[0].get_artist())
        self.assertEqual('peach, plum, pear', songs_in_queue[0].get_title())


class TestThrottle(unittest.TestCase):
    """Test the throttle decorator."""

    def test_throttle(self):
        """Test throttling."""
        now = datetime.now()
        times = 0
        while True:
            throttled_method()
            times += 1
            if datetime.now() > (now + timedelta(0, 0, 1000)):
                break
        self.assertEqual(True, times < 100)
