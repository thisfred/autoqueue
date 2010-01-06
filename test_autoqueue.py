# -*- coding: utf-8 -*-
import unittest
from datetime import datetime, timedelta
from xml.dom import minidom
from autoqueue import SongBase, AutoQueueBase, Throttle

WAIT_BETWEEN_REQUESTS = timedelta(0,0,10)

fake_responses = {
    'http://ws.audioscrobbler.com/2.0/?method=track.getsimilar&artist='
    'joni+mitchell&track=carey&api_key=09d0975a99a4cab235b731d31abf0057':
    'testfiles/test1.xml',
    'http://ws.audioscrobbler.com/2.0/?method=artist.getsimilar&artist='
    'nina+simone&api_key=09d0975a99a4cab235b731d31abf0057':
    'testfiles/test2.xml',
    'http://ws.audioscrobbler.com/2.0/?method=track.getsimilar&artist='
    'nina+simone&track=i+think+it%27s+going+to+rain+today'
    '&api_key=09d0975a99a4cab235b731d31abf0057': 'testfiles/test3.xml',
    'http://ws.audioscrobbler.com/2.0/?method=artist.getsimilar&artist='
    'joni+mitchell&api_key=09d0975a99a4cab235b731d31abf0057':
    'testfiles/test4.xml',
    'http://ws.audioscrobbler.com/2.0/?method=artist.getsimilar&artist='
    'habib+koit%C3%A9+%26+bamada&api_key=09d0975a99a4cab235b731d31abf0057':
    'testfiles/test5.xml'
    }

class MockPlayer(object):
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


class MockSong(SongBase):
    def __init__(self, artist, title, tags=None):
        self.artist = artist
        self.title = title
        self.tags = tags

    def get_artist(self):
        return self.artist.lower()

    def get_title(self):
        return self.title.lower()

    def get_tags(self):
        return self.tags


class MockAutoQueue(AutoQueueBase):
    def setUp(self):
        self.player = MockPlayer(self.started)
        self.use_db = True
        self.in_memory = True
        super(MockAutoQueue, self).__init__()
        self.by_tags = True
        self.verbose = True

    def started(self, song):
        self.on_song_started(song)

    def player_construct_track_search(self, artist, title, restrictions=None):
        search = {'artist': artist, 'title': title}
        if restrictions:
            search.update(restrictions)
        return search

    def player_construct_artist_search(self, artist, restrictions=None):
        """construct a search that looks for songs with this artist"""
        search = {'artist': artist}
        if restrictions:
            search.update(restrictions)
        return search

    def player_construct_tag_search(self, tags, restrictions=None):
        """construct a search that looks for songs with these
        tags"""
        exclude_artists = self.get_blocked_artists()
        search = {'tags': tags, 'not_artist': exclude_artists}
        if restrictions:
            search.update(restrictions)
        return search

    def player_construct_restrictions(
        self, track_block_time, relaxors, restrictors):
        """contstruct a search to further modify the searches"""
        return {}

    def player_get_queue_length(self):
        return len(self.player.queue)

    def player_enqueue(self, song):
        self.player.queue.append(song)

    def player_search(self, search):
        return [
            MockSong(*song) for song in self.player.library if
            self.player.satisfies_criteria(song, search)]

    def player_get_songs_in_queue(self):
        return self.player.queue

    def last_fm_request(self, url):
        urlfile = fake_responses.get(url)
        if not urlfile:
            return None
        stream = open(urlfile, 'r')
        try:
            xmldoc = minidom.parse(stream).documentElement
            return xmldoc
        except:
            return None

    def analyze_track(self, song):
        yield

class TestSong(unittest.TestCase):
    def setUp(self):
        songobject = (
            'Joni Mitchell', 'Carey', ['matala', 'crete', 'places', 'villages',
                                       'islands', 'female vocals'])
        self.song = MockSong(*songobject)

    def test_get_artist(self):
        self.assertEqual('joni mitchell', self.song.get_artist())

    def test_get_title(self):
        self.assertEqual('carey', self.song.get_title())

    def test_get_tags(self):
        self.assertEqual(['matala', 'crete', 'places', 'villages', 'islands',
                       'female vocals'], self.song.get_tags())


@Throttle(WAIT_BETWEEN_REQUESTS)
def throttled_method():
    return

@Throttle(timedelta(0))
def unthrottled_method():
    return

class TestAutoQueue(unittest.TestCase):
    def setUp(self):
        self.autoqueue = MockAutoQueue()

    def test_in_memory(self):
        self.assertEqual(True, self.autoqueue.in_memory)

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
            (10000, {'lastfm_match': 10000, 'artist': u'rickie lee jones'}),
            (10728, {'lastfm_match': 9271, 'artist': u'carole king'}),
            (11331, {'lastfm_match': 8669, 'artist': u'ani difranco'}),
            (11873, {'lastfm_match': 8127, 'artist': u'joan baez'}),
            (12527, {'lastfm_match': 7473, 'artist': u'neil young'}),
            (12949, {'lastfm_match': 7051, 'artist': u'martha wainwright'}),
            (12955, {'lastfm_match': 7044, 'artist': u'indigo girls'}),
            (13120, {'lastfm_match': 6880, 'artist': u'james taylor'}),
            (13295, {'lastfm_match': 6705, 'artist': u'paul simon'}),
            (13323, {'lastfm_match': 6677, 'artist': u'dar williams'}),
            (13596,
             {'lastfm_match': 6404, 'artist': u'crosby, stills, nash & young'}),
            (13771, {'lastfm_match': 6229, 'artist': u'k.d. lang'}),
            (13849, {'lastfm_match': 6151, 'artist': u'simon & garfunkel'}),
            (13935, {'lastfm_match': 6064, 'artist': u'joan armatrading'}),
            (14041, {'lastfm_match': 5959, 'artist': u'patty griffin'}),
            (14117, {'lastfm_match': 5883, 'artist': u'leonard cohen'}),
            (14160, {'lastfm_match': 5840, 'artist': u'tim buckley'}),
            (14298, {'lastfm_match': 5702, 'artist': u'suzanne vega'}),
            (14351, {'lastfm_match': 5649, 'artist': u'janis ian'}),
            (14409, {'lastfm_match': 5591, 'artist': u'kate bush'}),
            (14445, {'lastfm_match': 5555, 'artist': u'cat stevens'}),
            (14523,
             {'lastfm_match': 5477, 'artist': u'neil young & crazy horse'})]
        sim = [track for track in similar_artists][:22]
        self.assertEqual(td, sim)
        artist = u'habib koité & bamada'
        row = self.autoqueue.get_artist(artist)
        artist_id = row[0]
        similar_artists = self.autoqueue.get_similar_artists_from_lastfm(
            artist, artist_id)
        sim = [track for track in similar_artists][:22]
        td = [
            (10000, {'lastfm_match': 10000, 'artist': u'salif keita'}),
            (10463, {'lastfm_match': 9536, 'artist': u'mamou sidib\xe9'}),
            (10669,
             {'lastfm_match': 9330, 'artist': u'k\xe9l\xe9tigui diabat\xe9'}),
            (10941, {'lastfm_match': 9058, 'artist': u'ali farka tour\xe9'}),
            (11082, {'lastfm_match': 8917, 'artist': u'habib koit\xe9'}),
            (11431, {'lastfm_match': 8569, 'artist': u'amadou & mariam'}),
            (14050, {'lastfm_match': 5950, 'artist': u'tinariwen'}),
            (14174, {'lastfm_match': 5826, 'artist': u'boubacar traor\xe9'}),
            (14629, {'lastfm_match': 5371, 'artist': u'oliver mtukudzi'}),
            (19619, {'lastfm_match': 381, 'artist': u'super rail band'}),
            (19641, {'lastfm_match': 359, 'artist': u'lobi traor\xe9'}),
            (19642,
             {'lastfm_match': 358,
              'artist': u'ali farka tour\xe9 & toumani diabat\xe9'}),
            (19642, {'lastfm_match': 358, 'artist': u'tartit'}),
            (19645, {'lastfm_match': 355, 'artist': u'issa bagayogo'}),
            (19651, {'lastfm_match': 349, 'artist': u'kasse mady diabate'}),
            (19653, {'lastfm_match': 347, 'artist': u'rokia traor\xe9'}),
            (19654, {'lastfm_match': 346, 'artist': u'daby tour\xe9'}),
            (19654, {'lastfm_match': 346, 'artist': u'oumou sangar\xe9'}),
            (19660, {'lastfm_match': 340, 'artist': u'luciana souza'}),
            (19663, {'lastfm_match': 337, 'artist': u'kandia kouyate'}),
            (19674,
             {'lastfm_match': 326,
              'artist': u'ali farka tour\xe9 and ry cooder'}),
            (19682, {'lastfm_match': 318, 'artist': u'sali sidibe'})]
        self.assertEqual(td, sim)

    def test_get_similar_tracks_from_lastfm(self):
        artist = 'nina simone'
        title = "i think it's going to rain today"
        track = self.autoqueue.get_track(artist, title)
        track_id = track[0]
        similar_tracks = self.autoqueue.get_similar_tracks_from_lastfm(
            artist, title, track_id)
        td = [(9553,
               {'title': u'how long has this been going o',
                'lastfm_match': 447, 'artist': u'ella fitzgerald'}),
              (9554,
               {'title': u'our love is here to stay', 'lastfm_match': 446,
                'artist': u'dinah washington'}),
              (9556,
               {'title': u'love for sale', 'lastfm_match': 444,
                'artist': u'dinah washington'}),
              (9557,
               {'title': u'will i find my love today?', 'lastfm_match': 443,
                'artist': u'marlena shaw'}),
              (9557,
               {'title': u'a couple of loosers', 'lastfm_match': 443,
                'artist': u'marlena shaw'}),
              (9562,
               {'title': u'reasons', 'lastfm_match': 438,
                'artist': u'minnie riperton'}),
              (9562,
               {'title': u'sorry (digitally remastered 02)',
                'lastfm_match': 438,
                'artist': u'natalie cole'}),
              (9562,
               {'title': u'stand by (digitally remastered 02)',
                'lastfm_match': 438, 'artist': u'natalie cole'}),
              (9564,
               {'title': u'adventures in paradise', 'lastfm_match': 436,
                'artist': u'minnie riperton'}),
              (9564,
               {'title': u"i've got my love to keep me wa", 'lastfm_match': 436,
                'artist': u'ella fitzgerald'}),
              (9572,
               {'title': u'find him', 'lastfm_match': 428,
                'artist': u'cassandra wilson'}),
              (9572,
               {'title': u'almost like being in love (lp version)',
                'lastfm_match': 428, 'artist': u'della reese'}),
              (9574,
               {'title': u'jacaranda bougainvillea', 'lastfm_match': 426,
                'artist': u'al jarreau'}),
              (9574,
               {'title': u'mellow mood', 'lastfm_match': 426,
                'artist': u'jimmy smith and wes montgomery'})]
        sim = [track for track in similar_tracks][:14]
        self.assertEqual(td, sim)

    def test_get_ordered_similar_artists(self):
        song = MockSong('nina simone', 'ne me quitte pas')
        artist = song.get_artist()
        similar_artists = self.autoqueue.get_ordered_similar_artists(song)
        td = [
            (10000, {'lastfm_match': 10000, 'artist': u'billie holiday'}),
            (12066, {'lastfm_match': 7934, 'artist': u'ella fitzgerald'}),
            (12598, {'lastfm_match': 7402, 'artist': u'sarah vaughan'}),
            (13268, {'lastfm_match': 6731, 'artist': u'dinah washington'}),
            (13481, {'lastfm_match': 6518, 'artist': u'madeleine peyroux'}),
            (13958, {'lastfm_match': 6042, 'artist': u'etta james'}),
            (14935, {'lastfm_match': 5065, 'artist': u'peggy lee'}),
            (15016, {'lastfm_match': 4984, 'artist': u'julie london'}),
            (15095, {'lastfm_match': 4905,
                     'artist': u'ella fitzgerald & louis armstrong'}),
            (15113, {'lastfm_match': 4887, 'artist': u'blossom dearie'})]
        for i, item in enumerate(td):
            self.assertEqual(td[i], similar_artists.next())
        row = self.autoqueue.get_artist(artist)
        self.assertEqual((artist, None), row[1:])
        artist = 'dionne warwick'
        row = self.autoqueue.get_artist(artist)
        self.assertEqual((artist, None), row[1:])

    def test_get_ordered_similar_tracks(self):
        song = MockSong('joni mitchell', 'carey')
        artist = song.get_artist()
        title = song.get_title()
        similar_tracks = self.autoqueue.get_ordered_similar_tracks(song)
        td = [
            (9162,
             {'title': u'things behind the sun', 'lastfm_match': 838,
              'artist': u'nick drake'}),
            (9193,
             {'title': u'horn', 'lastfm_match': 807, 'artist': u'nick drake'}),
            (9285,
             {'title': u'peach, plum, pear', 'lastfm_match': 715,
              'artist': u'joanna newsom'}),
            (9300,
             {'title': u'suzanne', 'lastfm_match': 700,
              'artist': u'leonard cohen'}),
            (9309,
             {'title': u'sprout and the bean', 'lastfm_match': 691,
              'artist': u'joanna newsom'}),
            (9336,
             {'title': u"blowin' in the wind", 'lastfm_match': 664,
              'artist': u'bob dylan'}),
            (9365,
             {'title': u'famous blue raincoat', 'lastfm_match': 635,
              'artist': u'leonard cohen'}),
            (9402,
             {'title': u'song for the asking', 'lastfm_match': 598,
              'artist': u'simon & garfunkel'}),
            (9407,
             {'title': u"the times they are a-changin'", 'lastfm_match': 593,
              'artist': u'bob dylan'}),
            (9465,
             {'title': u'keep the customer satisfied', 'lastfm_match': 535,
              'artist': u'simon & garfunkel'}),
            (9480,
             {'title': u'peace train', 'lastfm_match': 520,
              'artist': u'cat stevens'}),
            (9489,
             {'title': u'fire and rain', 'lastfm_match': 511,
              'artist': u'james taylor'}),
            (9549,
             {'title': u'enough to be on your way', 'lastfm_match': 451,
              'artist': u'james taylor'}),
            (9551,
             {'title': u"that's the spirit", 'lastfm_match': 449,
              'artist': u'judee sill'})]
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
        test_song = MockSong('Joni Mitchell', 'Carey')
        for i in range(4):
            self.autoqueue.player_enqueue(test_song)
        self.assertEqual(False, self.autoqueue.queue_needs_songs())

    def test_on_song_started(self):
        test_song = MockSong('Joni Mitchell', 'Carey')
        self.autoqueue.started(test_song)
        songs_in_queue = self.autoqueue.player_get_songs_in_queue()
        self.assertEqual('joanna newsom', songs_in_queue[0].get_artist())
        self.assertEqual('peach, plum, pear', songs_in_queue[0].get_title())

    def test_block_artist(self):
        artist_name = 'joni mitchell'
        self.autoqueue.block_artist(artist_name)
        self.assertEqual(True, self.autoqueue.is_blocked(artist_name))
        self.assertEqual([artist_name], self.autoqueue.get_blocked_artists())

    def test_get_last_song(self):
        test_song = MockSong('Nina Simone', "I Think It's Going to Rain Today",
                             ['forecasts', 'predictions', 'today',
                              'female vocals', 'weather', 'rain'])
        self.autoqueue.player_enqueue(test_song)
        self.assertEqual(
            'nina simone', self.autoqueue.get_last_song().get_artist())
        self.assertEqual(
            "i think it's going to rain today",
            self.autoqueue.get_last_song().get_title())
        self.autoqueue.player.play_song_from_queue()
        self.assertEqual(
            'marlena shaw', self.autoqueue.get_last_song().get_artist())
        self.assertEqual(
            'will i find my love today?',
            self.autoqueue.get_last_song().get_title())


class TestThrottle(unittest.TestCase):
    def test_throttle(self):
        now = datetime.now()
        times = 0
        while True:
            throttled_method()
            times += 1
            if datetime.now() > (now + timedelta(0,0,1000)):
                break
        self.assertEqual(True, times < 100)

