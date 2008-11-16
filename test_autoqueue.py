# -*- coding: utf-8 -*-
import random
from collections import deque
from datetime import datetime, timedelta
from xml.dom import minidom
from nose.tools import assert_equals, assert_not_equals
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
            ('bob dylan', "blowin' in the wind", '',
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
        positions = {'artist':0, 'title':1, 'tags':3}
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
                    print song, criteria
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
        song = func(queue_song)


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
    def __init__(self):
        self.player = MockPlayer(self.on_song_started)
        self.use_db = True
        self.in_memory = True
        self.threaded = False
        super(MockAutoQueue, self).__init__() 
        self.by_tags = True
        self.verbose = True
   
    def player_construct_track_search(self, artist, title, restrictions):
        search = {'artist': artist, 'title': title}
        search.update(restrictions)
        return search

    def player_construct_artist_search(self, artist, restrictions):
        """construct a search that looks for songs with this artist"""
        search = {'artist': artist}
        search.update(restrictions)
        return search
    
    def player_construct_tag_search(self, tags, restrictions):
        """construct a search that looks for songs with these
        tags"""
        exclude_artists = self.get_blocked_artists()
        search = {'tags': tags, 'not_artist': exclude_artists}
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
        
class TestSong(object):
    def setup(self):
        songobject = (
            'Joni Mitchell', 'Carey', ['matala', 'crete', 'places', 'villages',
                                       'islands', 'female vocals'])
        self.song = MockSong(*songobject)
   
    def test_get_artist(self):
        assert_equals('joni mitchell', self.song.get_artist())

    def test_get_title(self):
        assert_equals('carey', self.song.get_title())

    def test_get_tags(self):
        assert_equals(['matala', 'crete', 'places', 'villages', 'islands',
                       'female vocals'], self.song.get_tags())
        
        
@Throttle(WAIT_BETWEEN_REQUESTS)
def throttled_method():
    return

@Throttle(timedelta(0))
def unthrottled_method():
    return

class TestAutoQueue(object):
    def setup(self):
        self.autoqueue = MockAutoQueue()
    
    def test_in_memory(self):
        assert_equals(True, self.autoqueue.in_memory)

    def test_get_database_connection(self):
        connection = self.autoqueue.get_database_connection()
        cursor = connection.cursor()
        cursor.execute("SELECT * FROM tracks;")
        rows = cursor.fetchall()
        assert_equals([], rows)

    def test_get_artist(self):
        artist = 'joni mitchell'
        row = self.autoqueue.get_artist(artist)
        assert_equals((artist, None), row[1:])

    def test_get_track(self):
        artist = 'nina simone'
        title = "i think it's going to rain today"
        artist_id = self.autoqueue.get_artist(artist)[0]
        row = self.autoqueue.get_track(artist, title)
        assert_equals((artist_id, title, None), row[1:])

    def test_get_similar_artists_from_lastfm(self):
        artist = 'joni mitchell'
        artist_id = self.autoqueue.get_artist(artist)
        similar_artists = self.autoqueue.get_similar_artists_from_lastfm(
            artist, artist_id)
        td = [
            (10000, {'match': 10000, 'artist': u'rickie lee jones'}),
            (10728, {'match': 9271, 'artist': u'carole king'}),
            (11331, {'match': 8669, 'artist': u'ani difranco'}),
            (11873, {'match': 8127, 'artist': u'joan baez'}),
            (12527, {'match': 7473, 'artist': u'neil young'}),
            (12949, {'match': 7051, 'artist': u'martha wainwright'}),
            (12955, {'match': 7044, 'artist': u'indigo girls'}),
            (13120, {'match': 6880, 'artist': u'james taylor'}),
            (13295, {'match': 6705, 'artist': u'paul simon'}),
            (13323, {'match': 6677, 'artist': u'dar williams'}),
            (13596,
             {'match': 6404, 'artist': u'crosby, stills, nash & young'}),
            (13771, {'match': 6229, 'artist': u'k.d. lang'}),
            (13849, {'match': 6151, 'artist': u'simon & garfunkel'}),
            (13935, {'match': 6064, 'artist': u'joan armatrading'}),
            (14041, {'match': 5959, 'artist': u'patty griffin'}),
            (14117, {'match': 5883, 'artist': u'leonard cohen'}),
            (14160, {'match': 5840, 'artist': u'tim buckley'}),
            (14298, {'match': 5702, 'artist': u'suzanne vega'}),
            (14351, {'match': 5649, 'artist': u'janis ian'}),
            (14409, {'match': 5591, 'artist': u'kate bush'}),
            (14445, {'match': 5555, 'artist': u'cat stevens'}),
            (14523, {'match': 5477, 'artist': u'neil young & crazy horse'})]
        sim = [track for track in similar_artists][:22]
        assert_equals(td, sim)
        artist = u'habib koité & bamada'
        row = self.autoqueue.get_artist(artist)
        artist_id = row[0]
        similar_artists = self.autoqueue.get_similar_artists_from_lastfm(
            artist, artist_id)
        sim = [track for track in similar_artists][:22]
        td = [
            (10000, {'match': 10000, 'artist': u'salif keita'}),
            (10463, {'match': 9536, 'artist': u'mamou sidib\xe9'}),
            (10669, {'match': 9330, 'artist': u'k\xe9l\xe9tigui diabat\xe9'}),
            (10941, {'match': 9058, 'artist': u'ali farka tour\xe9'}),
            (11082, {'match': 8917, 'artist': u'habib koit\xe9'}),
            (11431, {'match': 8569, 'artist': u'amadou & mariam'}),
            (14050, {'match': 5950, 'artist': u'tinariwen'}),
            (14174, {'match': 5826, 'artist': u'boubacar traor\xe9'}),
            (14629, {'match': 5371, 'artist': u'oliver mtukudzi'}),
            (19619, {'match': 381, 'artist': u'super rail band'}),
            (19641, {'match': 359, 'artist': u'lobi traor\xe9'}),
            (19642, {'match': 358, 'artist': u'ali farka tour\xe9 & toumani diabat\xe9'}),
            (19642, {'match': 358, 'artist': u'tartit'}),
            (19645, {'match': 355, 'artist': u'issa bagayogo'}),
            (19651, {'match': 349, 'artist': u'kasse mady diabate'}),
            (19653, {'match': 347, 'artist': u'rokia traor\xe9'}),
            (19654, {'match': 346, 'artist': u'daby tour\xe9'}),
            (19654, {'match': 346, 'artist': u'oumou sangar\xe9'}),
            (19660, {'match': 340, 'artist': u'luciana souza'}),
            (19663, {'match': 337, 'artist': u'kandia kouyate'}),
            (19674, {'match': 326, 'artist': u'ali farka tour\xe9 and ry cooder'}),
            (19682, {'match': 318, 'artist': u'sali sidibe'})]
        assert_equals(td, sim)
        
    def test_get_similar_tracks_from_lastfm(self):
        artist = 'nina simone'
        title = "i think it's going to rain today"
        track = self.autoqueue.get_track(artist, title)
        track_id = track[0]
        similar_tracks = self.autoqueue.get_similar_tracks_from_lastfm(
            artist, title, track_id)
        td = [(9553,
               {'title': u'how long has this been going o',
                'match': 447, 'artist': u'ella fitzgerald'}),
              (9554,
               {'title': u'our love is here to stay', 'match': 446,
                'artist': u'dinah washington'}),
              (9556,
               {'title': u'love for sale', 'match': 444,
                'artist': u'dinah washington'}),
              (9557,
               {'title': u'will i find my love today?', 'match': 443,
                'artist': u'marlena shaw'}),
              (9557,
               {'title': u'a couple of loosers', 'match': 443,
                'artist': u'marlena shaw'}),
              (9562,
               {'title': u'reasons', 'match': 438,
                'artist': u'minnie riperton'}),
              (9562,
               {'title': u'sorry (digitally remastered 02)', 'match': 438,
                'artist': u'natalie cole'}),
              (9562,
               {'title': u'stand by (digitally remastered 02)',
                'match': 438, 'artist': u'natalie cole'}),
              (9564,
               {'title': u'adventures in paradise', 'match': 436,
                'artist': u'minnie riperton'}),
              (9564,
               {'title': u"i've got my love to keep me wa", 'match': 436,
                'artist': u'ella fitzgerald'}),
              (9572,
               {'title': u'find him', 'match': 428,
                'artist': u'cassandra wilson'}),
              (9572,
               {'title': u'almost like being in love (lp version)',
                'match': 428, 'artist': u'della reese'}),
              (9574,
               {'title': u'jacaranda bougainvillea', 'match': 426,
                'artist': u'al jarreau'}),
              (9574,
               {'title': u'mellow mood', 'match': 426,
                'artist': u'jimmy smith and wes montgomery'})]
        sim = [track for track in similar_tracks][:14]
        assert_equals(td, sim)

    def test_get_ordered_similar_artists(self):
        song = MockSong('nina simone', 'ne me quitte pas')
        artist = song.get_artist()
        similar_artists = self.autoqueue.get_ordered_similar_artists(song)
        td = [
            (10000, {'match': 10000, 'artist': u'billie holiday'}),
            (12066, {'match': 7934, 'artist': u'ella fitzgerald'}),
            (12598, {'match': 7402, 'artist': u'sarah vaughan'}),
            (13268, {'match': 6731, 'artist': u'dinah washington'}),
            (13481, {'match': 6518, 'artist': u'madeleine peyroux'}),
            (13958, {'match': 6042, 'artist': u'etta james'}),
            (14935, {'match': 5065, 'artist': u'peggy lee'}),
            (15016, {'match': 4984, 'artist': u'julie london'}),
            (15095, {'match': 4905, 'artist': u'ella fitzgerald & louis armstrong'}),
            (15113, {'match': 4887, 'artist': u'blossom dearie'})]
        for i, item in enumerate(td):
            assert_equals(td[i], similar_artists.next())
        row = self.autoqueue.get_artist(artist)
        assert_equals((artist, None), row[1:])
        artist = 'dionne warwick'
        row = self.autoqueue.get_artist(artist)
        assert_equals((artist, None), row[1:])

    def test_get_ordered_similar_tracks(self):
        song = MockSong('joni mitchell', 'carey')
        artist = song.get_artist()
        title = song.get_title()
        similar_tracks = self.autoqueue.get_ordered_similar_tracks(song)
        td = [
            (9162,
             {'title': u'things behind the sun', 'match': 838,
              'artist': u'nick drake'}),
            (9193,
             {'title': u'horn', 'match': 807, 'artist': u'nick drake'}),
            (9285,
             {'title': u'peach, plum, pear', 'match': 715,
              'artist': u'joanna newsom'}),
            (9300,
             {'title': u'suzanne', 'match': 700, 'artist': u'leonard cohen'}),
            (9309,
             {'title': u'sprout and the bean', 'match': 691,
              'artist': u'joanna newsom'}),
            (9336,
             {'title': u"blowin' in the wind", 'match': 664,
              'artist': u'bob dylan'}),
            (9365,
             {'title': u'famous blue raincoat', 'match': 635,
              'artist': u'leonard cohen'}),
            (9402,
             {'title': u'song for the asking', 'match': 598,
              'artist': u'simon & garfunkel'}),
            (9407,
             {'title': u"the times they are a-changin'", 'match': 593,
              'artist': u'bob dylan'}),
            (9465,
             {'title': u'keep the customer satisfied', 'match': 535,
              'artist': u'simon & garfunkel'}),
            (9480,
             {'title': u'peace train', 'match': 520,
              'artist': u'cat stevens'}),
            (9489,
             {'title': u'fire and rain', 'match': 511,
              'artist': u'james taylor'}),
            (9549,
             {'title': u'enough to be on your way', 'match': 451,
              'artist': u'james taylor'}),
            (9551,
             {'title': u"that's the spirit", 'match': 449,
              'artist': u'judee sill'})]
        sim = [track for track in similar_tracks][:14]
        assert_equals(td, sim)
        artist_id = self.autoqueue.get_artist(artist)[0]
        row = self.autoqueue.get_track(artist, title)
        assert_equals((artist_id, title, None), row[1:])
        artist = 'leonard cohen'
        title = 'suzanne'
        artist_id = self.autoqueue.get_artist(artist)[0]
        row = self.autoqueue.get_track(artist, title)
        assert_equals((artist_id, title, None), row[1:])

    def test_queue_needs_songs(self):
        self.autoqueue.desired_queue_length = 4
        assert_equals(True, self.autoqueue.queue_needs_songs())
        test_song = MockSong('Joni Mitchell', 'Carey')
        for i in range(4):
            self.autoqueue.player_enqueue(test_song)
        assert_equals(False, self.autoqueue.queue_needs_songs())
        
    def test_on_song_started(self):
        test_song = MockSong('Joni Mitchell', 'Carey')
        self.autoqueue.on_song_started(test_song)
        songs_in_queue = self.autoqueue.player_get_songs_in_queue()
        assert_equals('joanna newsom', songs_in_queue[0].get_artist())
        assert_equals('peach, plum, pear', songs_in_queue[0].get_title())
        backup_songs = self.autoqueue._songs
        score, song = backup_songs[0]
        assert_equals(9300, score)
        assert_equals('leonard cohen', song.get_artist())
        assert_equals('suzanne', song.get_title())

    def test_backup_songs(self):
        test_song = MockSong('Joni Mitchell', 'Carey')
        test_song2 = MockSong(
            'Nina Simone', "I Think It's Going to Rain Today",
            ['forecasts', 'predictions', 'today',
             'female vocals', 'weather', 'rain'])
        test_song3 = MockSong('nick drake', 'things behind the sun')

        self.autoqueue.player_enqueue(test_song)
        self.autoqueue.player.play_song_from_queue()
        songs_in_queue = self.autoqueue.player_get_songs_in_queue()
        assert_equals('joanna newsom', songs_in_queue[0].get_artist())
        assert_equals('peach, plum, pear', songs_in_queue[0].get_title())
        backup_songs = self.autoqueue._songs
        assert_equals('leonard cohen', backup_songs[0][1].get_artist())
        assert_equals('suzanne', backup_songs[0][1].get_title())
        self.autoqueue.player.play_song_from_queue()
        songs_in_queue = self.autoqueue.player_get_songs_in_queue()
        assert_equals('leonard cohen', songs_in_queue[0].get_artist())
        assert_equals('suzanne', songs_in_queue[0].get_title())
        assert_equals(0, len(self.autoqueue._songs))
        
    def test_block_artist(self):
        artist_name = 'joni mitchell'
        self.autoqueue.block_artist(artist_name)
        assert_equals(True, self.autoqueue.is_blocked(artist_name))
        assert_equals([artist_name], self.autoqueue.get_blocked_artists())

    def test_get_last_song(self):
        test_song = MockSong('Nina Simone', "I Think It's Going to Rain Today",
                             ['forecasts', 'predictions', 'today',
                              'female vocals', 'weather', 'rain'])
        self.autoqueue.player_enqueue(test_song)
        assert_equals(
            'nina simone', self.autoqueue.get_last_song().get_artist())
        assert_equals(
            "i think it's going to rain today",
            self.autoqueue.get_last_song().get_title())
        self.autoqueue.player.play_song_from_queue()
        assert_equals(
            'marlena shaw', self.autoqueue.get_last_song().get_artist())
        assert_equals(
            'will i find my love today?',
            self.autoqueue.get_last_song().get_title())
        self.autoqueue.player.play_song_from_queue()
        assert_equals(
            'minnie riperton', self.autoqueue.get_last_song().get_artist())
        assert_equals(
            'reasons', self.autoqueue.get_last_song().get_title())

    def test_get_track_match(self):
        test_song = MockSong('Joni Mitchell', 'Carey')
        self.autoqueue.on_song_started(test_song)
        artist = 'joni mitchell'
        title = 'carey'
        artist2 = 'nick drake'
        title2 = 'things behind the sun'
        assert_equals(
            838,
            self.autoqueue.get_track_match(artist, title, artist2, title2))

    def test_get_artist_match(self):
        test_song = MockSong('Joni Mitchell', 'The Last Time I Saw Richard')
        artist = 'joni mitchell'
        artist2 =  'paul simon'
        self.autoqueue.on_song_started(test_song)
        ## cursor = self.autoqueue.connection.cursor()
        ## cursor.execute("SELECT * FROM artist_2_artist INNER JOIN artists ON artists.id = artist_2_artist.artist2;")
        ## for row in cursor:
        ##     print row
        assert_equals(
            6705,
            self.autoqueue.get_artist_match(artist, artist2))

    def test_get_tag_match(self):
        tags1 = [
            'artist:lowlands 2006', 'artist:sxsw 2005', 'modernity', 'love']
        tags2 = ['covers', 'bloc party', 'modernity', 'love', 'live']
        assert_equals(2, self.autoqueue.get_tag_match(tags1, tags2))

        
class TestThrottle(object):
    def test_throttle(self):
        now = datetime.now()
        times = 0
        while True:
            throttled_method()
            times += 1
            if datetime.now() > (now + timedelta(0,0,1000)):
                break
        assert_equals(True, times < 100)
        
