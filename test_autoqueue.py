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
    pass

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
    
