"""Block artists's songs from being picked for a period after playing."""


from pickle import Pickler, Unpickler
from collections import deque
from datetime import datetime, timedelta
import os

try:
    import xdg.BaseDirectory
    XDG = True
except ImportError:
    XDG = False


class Blocking(object):

    def __init__(self):
        self.artist_block_time = 1
        self._blocked_artists = deque([])
        self._blocked_artists_times = deque([])
        self._cache_dir = None
        self._load_blocked_artists()

    def get_cache_dir(self):
        """Get the directory to store temporary data.

        Defaults to $XDG_CACHE_HOME/autoqueue on Gnome.
        """
        if self._cache_dir:
            return self._cache_dir
        if not XDG:
            return "tmp"
        cache_dir = os.path.join(xdg.BaseDirectory.xdg_cache_home, 'autoqueue')
        if not os.path.exists(cache_dir):
            os.makedirs(cache_dir)
        self._cache_dir = cache_dir
        return cache_dir

    def block_artist(self, artist_name):
        """Block songs by artist from being played for a while."""
        self._add_to_blocked(artist_name)
        self._dump_blocked()

    def unblock_artists(self):
        """Unblock expired blocked artists."""
        now = datetime.now()
        while self._blocked_artists_times:
            if self._blocked_artists_times[0] + timedelta(
                    self.artist_block_time) > now:
                break
            print("Unblocked %s (%s)" % (
                self._blocked_artists.popleft(),
                self._blocked_artists_times.popleft()))

    def get_blocked_artists(self, songs):
        """Get a list of blocked artists."""
        blocked = []
        for song in songs:
            blocked.extend(song.get_artists())
        return list(self._blocked_artists) + blocked

    def _load_blocked_artists(self):
        """Read the list of blocked artists from disk."""
        dump = os.path.join(self.get_cache_dir(), "autoqueue_block_cache")
        try:
            with open(dump, 'r') as pickle:
                unpickler = Unpickler(pickle)
                artists, times = unpickler.load()
                if isinstance(artists, list):
                    artists = deque(artists)
                if isinstance(times, list):
                    times = deque(times)
                self._blocked_artists = artists
                self._blocked_artists_times = times
        except IOError:
            pass

    def _add_to_blocked(self, artist_name):
        now = datetime.now()
        self._blocked_artists.append(artist_name)
        self._blocked_artists_times.append(now)
        print("Blocked artist: %s (%s)" % (
            artist_name, len(self._blocked_artists)))

    def _dump_blocked(self):
        dump = os.path.join(
            self.get_cache_dir(), "autoqueue_block_cache")
        try:
            os.remove(dump)
        except OSError:
            pass
        if not self._blocked_artists:
            return
        with open(dump, 'r') as pickle_file:
            pickler = Pickler(pickle_file, -1)
            to_dump = (self._blocked_artists, self._blocked_artists_times)
            pickler.dump(to_dump)
