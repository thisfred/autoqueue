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

    def get_similar_artists(self, artist_name):
        similar_artists = {
            'joni mitchell': [
            (10000, u'carole king'), (9144, u'kate bush'),
            (8834, u'rickie lee jones'), (7709, u'van morrison'),
            (7459, u'crosby, stills, nash & young'), (7215, u'neil young'),
            (7168, u'nick drake'), (7026, u'joan baez'),
            (6958, u'james taylor'), (6695, u'paul simon'),
            (6335, u'suzanne vega'), (6311, u'patti smith'),
            (6281, u'the band'), (6151, u'bob dylan'),
            (6065, u'crosby, stills & nash'), (6033, u'joan armatrading'),
            (5978, u'marianne faithfull'), (5921, u'aimee mann'),
            (5823, u'dusty springfield'), (5734, u'tim buckley'),
            (5728, u'nina simone'), (5717, u'vashti bunyan'),
            (5656, u'the byrds'), (5477, u'leonard cohen'),
            (5264, u'rufus wainwright'), (5242, u'simon & garfunkel'),
            (5224, u'cat power'), (5207, u'indigo girls'), (5195, u'nico'),
            (5097, u'natalie merchant'), (5062, u'stevie wonder')],
            'nina simone': [
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
            (3206, u'mahalia jackson'), (3064, u'bill withers'),
            (2720, u'amy winehouse'), (2606, u'dusty springfield'),
            (2501, u'al green'), (2326, u'joni mitchell'),
            (2288, u'ray charles'), (2226, u'sam cooke')]}
        return similar_artists.get(artist_name)

    def get_similar_tracks(self, artist_name, title):
        similar_tracks = {
            ('joni mitchell', 'carey'): 
            [(838, u'nick drake', u'things behind the sun'),
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
             (449, u'judee sill', u"that's the spirit"),
             (449, u'joan baez', u'asimbonanga')],
            ('nina simone', "i think it's going to rain today"):
            [(446, u'dinah washington', u'our love is here to stay'),
             (444, u'dinah washington', u'love for sale'),
             (443, u'marlena shaw', u'will i find my love today?'),
             (438, u'minnie riperton', u'reasons'),
             (436, u'minnie riperton', u'adventures in paradise'),
             (428, u'cassandra wilson', u'find him'),
             (426, u'al jarreau', u'jacaranda bougainvillea'),
             (426, u'jimmy smith and wes montgomery', u'mellow mood'),
             (421, u'alice russell', u"i'm just here"),
             (419, u'aretha franklin', u'love for sale'),
             (419, u'al jarreau', u'better than anything (live version)'),
             (418, u'natalie williams', u'remember the day'),
             (418, u'natalie williams', u'girlfriend'),
             (415, u'sarah vaughan', u'i could write a book'),
             (415, u'sarah vaughan', u'honeysuckle rose'),]}
        return similar_tracks.get((artist_name, title))
        
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
        artist = 'nina simone'
        title = "i think it's going to rain today"
        artist_id = self.autoqueue.get_artist(artist)[0]
        row = self.autoqueue.get_track(artist, title)
        assert_equals((artist_id, title, None), row[1:])

