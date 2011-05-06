#!/usr/bin/env python
"""mpd implementation of autoqueue.

Copyright (c) 2008-2011 Rick van Hattem, Eric Casteleijn
"""

import os
import sys
import mpd
import time
import errno
import socket
import signal
import optparse
import autoqueue


def expand_path(path):
    path = os.path.expandvars(os.path.expanduser(path))
    if not os.path.isdir(path):
        os.mkdir(path)
    return path


def expand_file(path):
    path, file_ = os.path.split(path)
    return os.path.join(expand_path(path), file_)

# The settings path automatically expands ~ to the user home directory
# and $VAR to environment variables On most *n?x systems ~/.autoqueue
# will be expanded to /home/username/.autoqueue/ Setting the path to
# $HOME/.autoqueue/ will usually yield the same result

SETTINGS_PATH = '~/.autoqueue/'

# These settings will be overwritten by the MPD_HOST/MPD_PORT
# environment variables and/or by the commandline arguments

MPD_PORT = 6600
MPD_HOST = 'localhost'

# The PID file to see if there are no other instances running

PID_FILE = os.path.join(expand_path(SETTINGS_PATH), 'mpd.pid')

# Send a KILL signal if the process didn't end KILL_TIMEOUT seconds
# after the TERM signal, check every KILL_CHECK_DELAY seconds if it's
# still alive after sending the TERM signal

KILL_TIMEOUT = 10
KILL_CHECK_DELAY = 0.1

# The targets for stdin, stdout and stderr when daemonizing

STDIN = '/dev/null'
STDOUT = SETTINGS_PATH + 'stdout'
STDERR = SETTINGS_PATH + 'stderr'

# The interval to refresh the MPD status, the faster this is set, the
# faster the MPD server will be polled to see if the queue is empty

REFRESH_INTERVAL = 10

# The desired length for the queue, set this to 0 to add a song for
# every finished song or to any other number for the number of seconds
# to keep the queue filled

DESIRED_QUEUE_LENGTH = 0

# Make sure we have a little margin before changing the song so the
# queue won't run empty, keeping this at 15 seconds should be safe Do
# note that when DESIRED_QUEUE_LENGTH = 0 than this would probably
# work better with a value of 0

QUEUE_MARGIN = 0

# When MPD is not running, should we launch? And if MPD exits, should
# we exit?

EXIT_WITH_MPD = False


class Song(autoqueue.SongBase):
    """An MPD song object."""

    # pylint: disable=W0231
    def __init__(self, song_file=None, song_length=0, **kwargs):
        self.title = self.artist = self.album = ''
        self.file = song_file
        self.time = song_length
        self.__dict__.update(**kwargs)
    # pylint: enable=W0231

    def get_artist(self):
        """Return lowercase UNICODE name of artist."""
        return unicode(self.artist.lower(), 'utf-8')

    def get_artists(self):
        """Get list of artists and performers for the song."""
        return [self.get_artist()]

    def get_title(self):
        """Return lowercase UNICODE title of song."""
        return unicode(self.title.lower(), 'utf-8')

    def get_tags(self):
        """Return a list of tags for the song."""
        return []

    def get_filename(self):
        """Return filename for the song."""
        return '/var/lib/mpd/music/' + self.file

    def get_last_started(self):
        """Return the datetime the song was last played."""
        return 0

    def get_rating(self):
        """Return the rating of the song."""
        return 0

    def get_playcount(self):
        """Return the playcount of the song."""
        return 0

    def __repr__(self):
        return '<%s: %s - %s - %s>' % (
            self.__class__.__name__,
            self.album,
            self.artist,
            self.title,
        )

    def __int__(self):
        return self.time

    def __add__(self, other):
        return Song(time=self.time + other.time)

    def __sub__(self, other):
        return Song(time=self.time - other.time)

    def __hash__(self):
        if self.file:
            return hash(self.file)
        else:
            return id(self)

    def __eq__(self, other):
        return hash(self) == hash(other)

    def __ne__(self, other):
        return hash(self) != hash(other)


class Search(object):
    """
    Search object which keeps track of all search parameters.

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
    """
    ALLOWED_FIELDS = ('artist', 'album', 'title', 'track', 'name', 'genre',
        'date', 'composer', 'performer', 'comment', 'disc', 'filename', 'any')

    def __init__(self, field=None, value=None, **parameters):
        """
        Create a search object.

        >>> search = Search(artist='test')
        >>> search.parameters
        {'artist': set(['test'])}

        >>> search = Search()
        >>> search.parameters
        {}

        >>> search = Search('artist', 'test')
        >>> search.parameters
        {'artist': set(['test'])}
        """
        self.parameters = {}
        if field and value:
            self.add_parameter(field, value)
        self.add_parameters(**parameters)

    def add_parameters(self, **parameters):
        """
        Add one or more parameters to the search query.

        Use with named arguments, the key must be in ALLOWED_FIELDS

        >>> search = Search()
        >>> search.add_parameters(artist='test1', title='test2')
        >>> search.parameters
        {'artist': set(['test1']), 'title': set(['test2'])}
        """
        [self.add_parameter(k, v) for k, v in parameters.iteritems()]

    def add_parameter(self, field, value):
        """
        Add a parameter to the search query.

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
        """
        if field in self.ALLOWED_FIELDS:
            self.parameters.setdefault(field, set()).add(value.lower().strip())
        else:
            raise TypeError, '"%s" is not a valid field, please choose ' \
                'on from ALLOWED_FIELDS' % field

    def get_parameters(self):
        """
        Return a list of parameters for the MPDClient.search method.

        >>> search = Search(artist='test1', title='test2')
        >>> search.get_parameters()
        ['title', 'test2', 'artist', 'test1']

        >>> from mpd_autoqueue import *
        >>> search = Search()
        >>> search.get_parameters()
        Traceback (most recent call last):
        ...
        ValueError: Empty search queries are not allowed
        """
        ret = []
        for k, vs in self.parameters.iteritems():
            ret += [[k, v.encode('utf-8')] for v in vs]

        if not ret:
            raise ValueError, 'Empty search queries are not allowed'
        return sum(ret, [])


class Daemon(object):
    """
    Class to easily create a daemon which transparently handles the
    saving and removing of the PID file.

    """

    def __init__(self, pid_file):
        """Create a new Daemon.

        pid_file -- The file to save the PID in
        """
        self._pid_file = None
        self.pid_file = pid_file
        signal.signal(signal.SIGTERM, lambda *args: self.exit())
        signal.signal(signal.SIGINT, lambda *args: self.exit())
        signal.signal(signal.SIGQUIT, lambda *args: self.exit())

    def set_pid_file(self, pid_file):
        """Set pid file."""
        self._pid_file = pid_file
        open(pid_file, 'w').write('%d' % os.getpid())

    def get_pid_file(self):
        """Get pid file."""
        return self._pid_file

    def del_pid_file(self):
        """Delete pid file."""
        try:
            os.unlink(self._pid_file)
            print >> sys.stderr, 'Removed PID file'
        except OSError:
            print >> sys.stderr, 'Trying to remove non-existing PID file'

    pid_file = property(get_pid_file, set_pid_file, del_pid_file,
        'The PID file will be written when set and deleted when unset')

    def exit(self):
        """Kill the daemon and remove the PID file

        This method will be called automatically when the process is
        terminated"""
        del self.pid_file
        raise SystemExit

    @classmethod
    def is_running(cls, pid):
        """Check whether we're already running.'"""
        if not pid:
            return False
        try:
            os.kill(pid, signal.SIG_DFL)
            return True
        except OSError, err:
            return err.errno == errno.EPERM

    @classmethod
    def kill(cls, pid, pid_file=None):
        """Kill process."""
        try:
            pid = int(pid)
        except (TypeError, ValueError):
            pid = None

        if cls.is_running(pid):
            print >> sys.stderr, 'Sending TERM signal to process %d' % pid
            os.kill(pid, signal.SIGTERM)
            i = KILL_TIMEOUT
            while i > 0 and cls.is_running(pid):
                i -= KILL_CHECK_DELAY
                time.sleep(KILL_CHECK_DELAY)

            if cls.is_running(pid):
                print >> sys.stderr, 'Sending KILL signal to process %d' % pid
                os.kill(pid, signal.SIGKILL)

            time.sleep(1)
            if cls.is_running(pid):
                print >> sys.stderr, 'Unable to kill process %d, still running'
        else:
            if isinstance(pid, int):
                print >> sys.stderr, 'Process %d not running' % pid
            if pid_file:
                print >> sys.stderr, 'Removing stale PID file'
                os.unlink(pid_file)

    @classmethod
    def daemonize(cls):
        """
        Daemonize using the double fork method so the process keeps
        running Even after the original shell exits.

        """
        stdin_file = expand_file(STDIN)
        stdout_file = expand_file(STDOUT)
        stderr_file = expand_file(STDERR)
        try:
            pid = os.fork()
            if pid > 0:
                sys.exit(0)
        except OSError, e:
            print >> sys.stderr, 'Unable to fork: %s' % e
            sys.exit(1)

        os.chdir('/')
        os.setsid()
        os.umask(0)

        try:
            pid = os.fork()
            if pid > 0:
                sys.exit(0)
        except OSError, e:
            print >> sys.stderr, 'Unable to fork: %s' % e
            sys.exit(1)

        # Redirect stdout, stderr and stdin
        stdin = file(stdin_file, 'r')
        stdout = file(stdout_file, 'a+')
        stderr = file(stderr_file, 'a+', 0)
        os.dup2(stdin.fileno(), sys.stdin.fileno())
        os.dup2(stdout.fileno(), sys.stdout.fileno())
        os.dup2(stderr.fileno(), sys.stderr.fileno())


class AutoQueuePlugin(autoqueue.AutoQueueBase, Daemon):
    """Mpd implementation of autoqueue."""

    def __init__(self, host, port, pid_file):
        self.host, self.port = host, port
        self.client = mpd.MPDClient()
        self.connect()
        autoqueue.AutoQueueBase.__init__(self)
        self.verbose = True
        self.desired_queue_length = DESIRED_QUEUE_LENGTH
        Daemon.__init__(self, pid_file)
        self._current_song = None
        self._host = None

    def run(self):
        """Run."""
        running = True
        while running or not EXIT_WITH_MPD:
            interval = REFRESH_INTERVAL
            if running:
                try:
                    song = self.player_current_song()
                    if song != self._current_song:
                        self._current_song = song
                        self.on_song_started(song)

                    interval = min(
                        REFRESH_INTERVAL,
                        int(self.player_get_queue_length()) - QUEUE_MARGIN)
                    running = True
                except mpd.ConnectionError:
                    print "disconnecting"
                    self.running = False
                    running = False
                    self.disconnect()
            else:
                print "reconnecting"
                running = True
                self.connect()
            time.sleep(interval)
        self.exit()

    def connect(self):
        """Connect."""
        try:
            self.client.connect(self.host, self.port)
            return True
        except socket.error:
            return False

    def disconnect(self):
        """Disconnect."""
        try:
            self.client.disconnect()
            return True
        except (socket.error, mpd.ConnectionError):
            return False

    def get_host(self):
        """Get host."""
        return self._host

    def set_host(self, host):
        """Set host."""
        self._host = socket.gethostbyname(host)

    host = property(
        get_host, set_host, doc='MPD ip (can be set by ip and hostname)')

    def player_construct_track_search(self, artist, title, restrictions=None):
        """Construct a search that looks for songs with this artist
        and title."""
        return Search(artist=artist, title=title)

    def player_construct_tag_search(self, tags, exclude_artists,
                                    restrictions=None):
        """Construct a search that looks for songs with these tags."""
        return None

    def player_construct_artist_search(self, artist, restrictions=None):
        """Construct a search that looks for songs with this artist."""
        return Search(artist=artist)

    def player_set_variables_from_config(self):
        """Initialize user settings from the configuration storage."""
        pass

    def player_search(self, search):
        """perform a player search"""

        results = self.client.search(*search.get_parameters())

        # Make all search results lowercase and strip whitespace
        for result in results:
            for key, value in result.items():
                if isinstance(value, basestring):
                    result['%s_search' % key] = unicode(
                        value, 'utf-8').strip().lower()

        # Filter all non-exact matches
        for key, values in search.parameters.iteritems():
            for value in values:
                results = [
                    r for r in results if r.get('%s_search' % key) == value]

        # Convert all rows to song objects
        return [Song(**x) for x in results]

    def player_enqueue(self, song):
        """Put the song at the end of the queue"""
        self.client.add(song.file)

    def player_get_userdir(self):
        """get the application user directory to store files"""
        return expand_path(SETTINGS_PATH)

    def player_current_song(self):
        return Song(**self.client.currentsong())

    def player_song(self, song_id):
        return Song(**self.client.playlistid(song_id)[0])

    def player_status(self):
        return self.client.status()

    def player_playlist(self):
        return (Song(**x) for x in self.client.playlistid())

    def player_get_songs_in_queue(self):
        """return (wrapped) song objects for the songs in the queue"""
        id = self.player_current_song_id()
        return [s for i, s in enumerate(self.player_playlist()) if i >= id]

    def player_get_queue_length(self):
        length = sum(self.player_get_songs_in_queue(), Song(time=0))
        return int(length) - self.player_current_song_time()

    def player_current_song_id(self):
        return int(self.player_status().get('song', 0))

    def player_current_song_time(self):
        return int(self.player_status().get('time', '0:').split(':')[0])


def main():
    parser = optparse.OptionParser()
    port = os.environ.get('MPD_PORT', MPD_PORT)
    host = os.environ.get('MPD_HOST', MPD_HOST)

    parser.set_defaults(host=host, port=port, daemonic=True, pid_file=PID_FILE)

    parser.add_option('-p', '--port', dest='port', type='int',
        help='The MPD port, defaults to the MPD_PORT environment variable ' \
        'or %d if not available' % MPD_PORT)
    parser.add_option('--host', dest='host', type='string',
        help='The MPD host (ip or hostname), defaults to the MPD_HOST ' \
        'environment variable or %s if not available' % MPD_HOST)
    parser.add_option('-d', '--daemonic', dest='daemonic',
        action='store_true', help='Run as a daemon')
    parser.add_option('-f', '--foreground', dest='daemonic',
        action='store_false', help='Run as a daemon')
    parser.add_option('-P', '--pid-file', dest='pid_file',
        type='string', help='Run as a daemon')
    parser.add_option('-k', '--kill', dest='kill',
        action='store_true', help='Kill the old process (if available)')

    options, args = parser.parse_args()
    options.pid_file = os.path.abspath(options.pid_file)

    if os.path.isfile(options.pid_file):
        try:
            pid = open(options.pid_file).readline()
            pid = int(pid)
        except (ValueError, TypeError):
            print >>sys.stderr, 'PID "%s" invalid, ignoring' % pid
            pid = None

        if Daemon.is_running(pid) and not options.kill:
            print >>sys.stderr, '%s already running (PID: %d)' % (sys.argv[0], pid)
            sys.exit(2)
        else:
            Daemon.kill(pid, options.pid_file)
            if options.kill:
                sys.exit(0)
    elif options.kill:
        print >>sys.stderr, 'No PID file found, unable to kill'
        sys.exit(3)

    try:
        file(options.pid_file, 'a')
        os.unlink(options.pid_file)
    except IOError, e:
        print >>sys.stderr, 'Error: PID file "%s" not writable: %s' % (options.pid_file, e)
        sys.exit(3)

    if options.daemonic:
        Daemon.daemonize()
    plugin = AutoQueuePlugin(options.host, options.port, options.pid_file)
    plugin.run()

def test():
    import doctest
    doctest.testmod(verbose=True)

if __name__ == '__main__':
    main()

