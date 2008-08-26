# -*- coding: utf-8 -*-
from datetime import datetime, timedelta
from xml.dom import minidom
from nose.tools import assert_equals
from autoqueue import SongBase, AutoQueueBase, Throttle

WAIT_BETWEEN_REQUESTS = timedelta(0,0,10)

fake_responses = {
    'http://ws.audioscrobbler.com/2.0/?method=track.getsimilar&artist='
    'joni+mitchell&track=carey&api_key=09d0975a99a4cab235b731d31abf0057':
    'test1.xml',
    'http://ws.audioscrobbler.com/2.0/?method=artist.getsimilar&artist='
    'nina+simone&api_key=09d0975a99a4cab235b731d31abf0057':
    'test2.xml',
    'http://ws.audioscrobbler.com/2.0/?method=track.getsimilar&artist='
    'nina+simone&track=i+think+it%27s+going+to+rain+today'
    '&api_key=09d0975a99a4cab235b731d31abf0057': 'test3.xml',
    'http://ws.audioscrobbler.com/2.0/?method=artist.getsimilar&artist='
    'joni+mitchell&api_key=09d0975a99a4cab235b731d31abf0057':
    'test4.xml',
    'http://ws.audioscrobbler.com/2.0/?method=artist.getsimilar&artist='
    'habib+koit%C3%A9+%26+bamada&api_key=09d0975a99a4cab235b731d31abf0057':
    'test5.xml'
    }

class MockPlayer(object):
    def __init__(self, plugin_on_song_started):
        self.queue = []
        self.library = [
            ('nina simone', "i think it's going to rain today", '',
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
                    if song[positions[criterium]] in criteria[criterium]:
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
    
    def player_construct_tag_search(self, tags, exclude_artists, restrictions):
        """construct a search that looks for songs with these
        tags"""
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
        similar_artists = self.autoqueue.get_similar_artists_from_lastfm(artist)
        td = [
            (10000, u'rickie lee jones'), (9271, u'carole king'),
            (8669, u'ani difranco'), (8127, u'joan baez'),
            (7473, u'neil young'), (7051, u'martha wainwright'),
            (7044, u'indigo girls'), (6880, u'james taylor'),
            (6705, u'paul simon'), (6677, u'dar williams'),
            (6404, u'crosby, stills, nash & young'), (6229, u'k.d. lang'),
            (6151, u'simon & garfunkel'), (6064, u'joan armatrading'),
            (5959, u'patty griffin'), (5883, u'leonard cohen'),
            (5840, u'tim buckley'), (5702, u'suzanne vega'),
            (5649, u'janis ian'), (5591, u'kate bush'),
            (5555, u'cat stevens'), (5477, u'neil young & crazy horse')]
        assert_equals(td, similar_artists[:22])
        artist = u'habib koité & bamada'
        similar_artists = self.autoqueue.get_similar_artists_from_lastfm(artist)
        td = [
            (10000, u'salif keita'), (9536, u'mamou sidib\xe9'),
            (9330, u'k\xe9l\xe9tigui diabat\xe9'),
            (9058, u'ali farka tour\xe9'), (8917, u'habib koit\xe9'),
            (8569, u'amadou & mariam'), (5950, u'tinariwen'),
            (5826, u'boubacar traor\xe9'), (5371, u'oliver mtukudzi'),
            (381, u'super rail band'), (359, u'lobi traor\xe9'),
            (358, u'ali farka tour\xe9 & toumani diabat\xe9'),
            (358, u'tartit'), (355, u'issa bagayogo'),
            (349, u'kasse mady diabate'), (347, u'rokia traor\xe9'),
            (346, u'daby tour\xe9'), (346, u'oumou sangar\xe9'),
            (340, u'luciana souza'), (337, u'kandia kouyate'),
            (326, u'ali farka tour\xe9 and ry cooder'), (318, u'sali sidibe')]
        assert_equals(td, similar_artists[:22])
        
    def test_get_similar_tracks_from_lastfm(self):
        artist = 'nina simone'
        title = "i think it's going to rain today"
        similar_tracks = self.autoqueue.get_similar_tracks_from_lastfm(
            artist, title)
        td = [
            (447, u'ella fitzgerald', u'how long has this been going o'),
            (446, u'dinah washington', u'our love is here to stay'),
            (444, u'dinah washington', u'love for sale'),
            (443, u'marlena shaw', u'will i find my love today?'),
            (443, u'marlena shaw', u'a couple of loosers'),
            (438, u'minnie riperton', u'reasons'),
            (438, u'natalie cole', u'sorry (digitally remastered 02)'),
            (438, u'natalie cole', u'stand by (digitally remastered 02)'),
            (436, u'minnie riperton', u'adventures in paradise'),
            (436, u'ella fitzgerald', u"i've got my love to keep me wa"),
            (428, u'cassandra wilson', u'find him'),
            (428, u'della reese', u'almost like being in love (lp version)'),
            (426, u'al jarreau', u'jacaranda bougainvillea'),
            (426, u'jimmy smith and wes montgomery', u'mellow mood')]
        assert_equals(td, similar_tracks[:14])
        
    def test_get_sorted_similar_artists(self):
        artist = 'nina simone'
        similar_artists = self.autoqueue.get_sorted_similar_artists(artist)
        td = [
            (10000, u'billie holiday'), (7934, u'ella fitzgerald'),
            (7402, u'sarah vaughan'), (6731, u'dinah washington'),
            (6518, u'madeleine peyroux'), (6042, u'etta james'),
            (5065, u'peggy lee'), (4984, u'julie london'),
            (4905, u'ella fitzgerald & louis armstrong'),
            (4887, u'blossom dearie'), (4743, u'cassandra wilson'),
            (4651, u'aretha franklin'), (4488, u'bessie smith'),
            (4435, u'carmen mcrae'), (4380, u"anita o'day"),
            (4367, u'nat king cole'), (4311, u'lisa ekdahl'),
            (3896, u'diana krall'), (3738, u'louis armstrong'),
            (3385, u'dionne warwick'), (3243, u'corinne bailey rae'),
            (3206, u'mahalia jackson'), (3064, u'bill withers')]
        assert_equals(td, similar_artists[:23])
        row = self.autoqueue.get_artist(artist)
        assert_equals((artist, None), row[1:])
        artist = 'dionne warwick'
        row = self.autoqueue.get_artist(artist)
        assert_equals((artist, None), row[1:])

    def test_get_sorted_similar_tracks(self):
        artist = 'joni mitchell'
        title = 'carey'
        similar_tracks = self.autoqueue.get_sorted_similar_tracks(
            artist, title)
        td = [(838, u'nick drake', u'things behind the sun'),
              (807, u'nick drake', u'horn'),
              (715, u'joanna newsom', u'peach, plum, pear'),
              (700, u'leonard cohen', u'suzanne'),
              (691, u'joanna newsom', u'sprout and the bean'),
              (664, u'bob dylan', u"blowin' in the wind"),
              (635, u'leonard cohen', u'famous blue raincoat'),
              (598, u'simon & garfunkel', u'song for the asking'),
              (593, u'bob dylan', u"the times they are a-changin'"),
              (535, u'simon & garfunkel', u'keep the customer satisfied'),
              (520, u'cat stevens', u'peace train'),
              (511, u'james taylor', u'fire and rain'),
              (451, u'james taylor', u'enough to be on your way'),
              (449, u'judee sill', u"that's the spirit")]
        assert_equals(td, similar_tracks[:14])
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
        assert_equals('leonard cohen', backup_songs[0].get_artist())
        assert_equals('suzanne', backup_songs[0].get_title())

    def test_backup_songs(self):
        test_song = MockSong('Joni Mitchell', 'Carey')
        self.autoqueue.player_enqueue(test_song)
        self.autoqueue.player.play_song_from_queue()
        songs_in_queue = self.autoqueue.player_get_songs_in_queue()
        assert_equals('joanna newsom', songs_in_queue[0].get_artist())
        assert_equals('peach, plum, pear', songs_in_queue[0].get_title())
        backup_songs = self.autoqueue._songs
        assert_equals('leonard cohen', backup_songs[0].get_artist())
        assert_equals('suzanne', backup_songs[0].get_title())
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
        artist2 = 'joanna newsom'
        title2 = 'peach, plum, pear'
        assert_equals(
            715,
            self.autoqueue.get_track_match(artist, title, artist2, title2))

    def test_get_artist_match(self):
        test_song = MockSong('Joni Mitchell', 'The Last Time I Saw Richard')
        artist = 'joni mitchell'
        artist2 =  'cat power'
        self.autoqueue.on_song_started(test_song)
        assert_equals(
            4541,
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
        
