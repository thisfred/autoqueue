from nose.tools import assert_equals
from autoqueue import SongBase, AutoQueueBase

class MySong(SongBase):
    def get_artist(self):
        return self.song['artist'].lower()
    def get_title(self):
        return self.song['title'].lower()
    def get_tags(self):
        return self.song['tags']


class MyAutoQueue(AutoQueueBase):
    def __init__(self):
        self.verbose = True
        self.use_db = True
        self.in_memory = True
        self.threaded = False
        super(MyAutoQueue, self).__init__()

class TestSong(object):
    def setup(self):
        songobject = {
            'artist': 'Joni Mitchell',
            'title': 'Carey',
            'tags': ['matala', 'crete', 'places', 'villages', 'islands',
                     'female vocals']}

        self.song = MySong(songobject)
    
    def test_get_artist(self):
        assert_equals('joni mitchell', self.song.get_artist())

    def test_get_title(self):
        assert_equals('carey', self.song.get_title())

    def test_get_tags(self):
        assert_equals(['matala', 'crete', 'places', 'villages', 'islands',
                       'female vocals'], self.song.get_tags())


class TestAutoQueue(object):
    def setup(self):
        self.autoqueue = MyAutoQueue()
    
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
        artist = 'joni mitchell'
        title = 'carey'
        artist_id = self.autoqueue.get_artist(artist)[0]
        row = self.autoqueue.get_track(artist, title)
        assert_equals((artist_id, title, None), row[1:])
       
