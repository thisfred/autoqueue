'''
Copyright (c) 2008, Rick van Hattem
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are
met:

    * Redistributions of source code must retain the above copyright
      notice, this list of conditions and the following disclaimer.

    * Redistributions in binary form must reproduce the above
      copyright notice, this list of conditions and the following
      disclaimer in the documentation and/or other materials provided
      with the distribution.

    * The names of the contributors may not be used to endorse or
      promote products derived from this software without specific
      prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
'AS IS' AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
(INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
'''

import os
import sys
import mpd
import time
import optparse
import autoqueue

'''The settings path automatically expands ~ to the user home directory
and $VAR to environment variables
On most *n?x systems ~/.autoqueue will be expanded to /home/username/.autoqueue/
Setting the path to $HOME/.autoqueue/ will usually yield the same result
'''
SETTINGS_PATH = '~/.autoqueue/'

class Song(autoqueue.SongBase):
    '''A MPD song object'''
    def __init__(self, **kwargs):
        self.title = self.artist = self.album = ''
        self.time = 0
        self.__dict__.update(**kwargs)
        
    def get_artist(self):
        '''return lowercase UNICODE name of artist'''
        return self.artist.lower()

    def get_title(self):
        '''return lowercase UNICODE title of song'''
        return self.title.lower()

    def get_album(self):
        '''return lowercase UNICODE album of song'''
        return self.album.lower()

    def get_tags(self):
        '''return a list of tags for the songs'''
        return []

    def __repr__(self):
        return '<%s: %s - %s - %s (%s)>' % (
            self.__class__.__name__,
            self.album,
            self.artist,
            self.title,
            self.duration,
        )

    @property
    def duration(self):
        t = time.gmtime(int(self.time))
        if t.tm_hour:
            fmt = '%H:%M:%S'
        else:
            fmt = '%M:%S'
        return time.strftime(fmt, t)

class Search(object):
    '''
    Search object which keeps track of all search parameters

    ALLOWED_FIELDS - list of allowed search fields

    >>> search = Search(artist='test')
    >>> search.get_parameters()
    ['artist', 'test']
    >>> search.add_parameter('title', 'test2')
    >>> search.get_parameters()
    ['title', 'test2', 'artist', 'test']
    >>> search.add_parameters(any='test3', album='test4')
    >>> search.get_parameters()
    ['album', 'test4', 'title', 'test2', 'any', 'test3', 'artist', 'test']
    '''
    ALLOWED_FIELDS = ('artist', 'album', 'title', 'track', 'name', 'genre',
        'date', 'composer', 'performer', 'comment', 'disc', 'filename', 'any')

    def __init__(self, field=None, value=None, **parameters):
        '''
        Create a search object

        >>> search = Search(artist='test')
        >>> search.parameters
        {'artist': set(['test'])}
        
        >>> search = Search()
        >>> search.parameters
        {}
        
        >>> search = Search('artist', 'test')
        >>> search.parameters
        {'artist': set(['test'])}
        '''
        self.parameters = {}
        if field and value:
            self.add_parameter(field, value)
        self.add_parameters(**parameters)

    def add_parameters(self, **parameters):
        '''
        Add one or more parameters to the search query
        
        Use with named arguments, the key must be in ALLOWED_FIELDS

        >>> search = Search()
        >>> search.add_parameters(artist='test1', title='test2')
        >>> search.parameters
        {'artist': set(['test1']), 'title': set(['test2'])}
        '''
        [self.add_parameter(k, v) for k, v in parameters.iteritems()]

    def add_parameter(self, field, value):
        '''
        Add a parameter to the search query
        
        field - must be in ALLOWED_FIELDS
        value - a literal string to be searched for

        >>> search = Search()
        >>> search.add_parameter('artist', 'test')
        >>> search.parameters
        {'artist': set(['test'])}

        >>> search = Search()
        >>> search.add_parameter('spam', 'eggs')
        Traceback (most recent call last):
        ...
        TypeError: "spam" is not a valid field, please choose on from ALLOWED_FIELDS
        '''
        if field in self.ALLOWED_FIELDS:
            self.parameters.setdefault(field, set()).add(value)
        else:
            raise TypeError, '"%s" is not a valid field, please choose ' \
                'on from ALLOWED_FIELDS' % field

    def get_parameters(self):
        '''
        Return a list of parameters for the MPDClient.search method

        >>> search = Search(artist='test1', title='test2')
        >>> search.get_parameters()
        ['title', 'test2', 'artist', 'test1']

        >>> from mpd_autoqueue import *
        >>> search = Search()
        >>> search.get_parameters()
        Traceback (most recent call last):
        ...
        ValueError: Empty search queries are not allowed
        '''
        ret = []
        for k, vs in self.parameters.iteritems():
            ret += [[k, v] for v in vs]

        if not ret:
            raise ValueError, 'Empty search queries are not allowed'
        return sum(ret, [])

class AutoQueuePlugin(autoqueue.AutoQueueBase):
    def __init__(self, host, port):
        self.host, self.port = host, port
        self.client = mpd.MPDClient()
        self.client.connect(host, port)
        self.use_db = True
        self.store_blocked_artists = True
        autoqueue.AutoQueueBase.__init__(self)
        self.verbose = True
        
    def player_construct_track_search(self, artist, title, restrictions):
        '''construct a search that looks for songs with this artist
        and title'''
        return Search(artist=artist, title=title)
    
    def player_construct_tag_search(self, tags, exclude_artists, restrictions):
        '''construct a search that looks for songs with these tags'''
        return None

    def player_construct_artist_search(self, artist, restrictions):
        '''construct a search that looks for songs with this artist'''
        return Search(artist=artist)
        
    def player_construct_restrictions(
        self, track_block_time, relaxors, restrictors):
        '''construct a search to further modify the searches'''
        return None

    def player_search(self, search):
        '''perform a player search'''
        return (Song(**x) for x in self.client.search(*search.get_parameters()))

    def player_get_userdir(self):
        '''get the application user directory to store files'''
        path = os.path.expandvars(os.path.expanduser(SETTINGS_PATH))
        if not os.path.isdir(path):
            os.mkdir(path)
        return path

def main():
    parser = optparse.OptionParser()
    port = os.environ.get('MPD_PORT', '6600')
    os.environ['MPD_HOST'] = 'localhost'
    host = os.environ.get('MPD_HOST', 'localhost')
    parser.add_option('-p', '--port', dest='port', type='int',
        help='The MPD port, defaults to the MPD_PORT environment variable ' \
        'or 6600 if not available', default=port)
    parser.add_option('--host', dest='host', type='string',
        help='The MPD host (ip or hostname), defaults to the MPD_HOST ' \
        'environment variable or localhost if not available', default=host)

    options, args = parser.parse_args()
    '''Example of how to use the system
    >>> queue = AutoQueuePlugin(options.host, options.port)
    >>> search = queue.player_construct_artist_search('vangelis', None)
    >>> print [s for s in queue.player_search(search)]
    '''

def test():
    import doctest
    doctest.testmod(verbose=True)

if __name__ == '__main__':
    main()
