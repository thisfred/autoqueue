"""Abstract Base Classes for interaction with music player."""

from abc import ABCMeta, abstractmethod
from datetime import datetime

try:
    import geohash
    GEOHASH = True
except ImportError:
    GEOHASH = False


class SongBase(metaclass=ABCMeta):

    """A wrapper object around player specific song objects."""

    def __init__(self, song):
        self.song = song

    def __str__(self):
        return "<Song: %s - %s>" % (self.get_artist(), self.get_title())

    @abstractmethod
    def get_artist(self):
        """Return lowercase UNICODE name of artist."""

    @abstractmethod
    def get_artists(self):
        """Return lowercase UNICODE name of artists and performers."""

    @abstractmethod
    def get_title(self, with_version=True):
        """Return lowercase UNICODE title of song."""

    @abstractmethod
    def get_tracknumber(self):
        """Return the tracknumber of the song."""

    @abstractmethod
    def get_album(self):
        """Return the album of the song."""

    @abstractmethod
    def get_album_artist(self):
        """Return the album of the song."""

    @abstractmethod
    def get_musicbrainz_albumid(self):
        """Return the musicbrainz album id, if any."""

    @abstractmethod
    def get_discnumber(self):
        """Return the discnumber of the song."""

    @abstractmethod
    def get_tags(self):
        """Return a list of tags for the song."""

    @abstractmethod
    def get_filename(self):
        """Return filename for the song."""

    @abstractmethod
    def get_last_started(self):
        """Return the datetime the song was last played."""

    @abstractmethod
    def get_rating(self):
        """Return the rating of the song."""

    @abstractmethod
    def get_playcount(self):
        """Return the playcount of the song."""

    @abstractmethod
    def get_date_string(self):
        """Return the playcount of the song."""

    @abstractmethod
    def get_year(self):
        """Return the playcount of the song."""

    def get_play_frequency(self):
        """Return the play frequency of the song (plays / day)."""
        count = self.get_playcount()
        if count is NotImplemented:
            return 0
        if count == 0:
            return 0
        last_started = self.get_last_started()
        if last_started is NotImplemented:
            return 0
        now = datetime.now()
        days = float(max((now - datetime.fromtimestamp(last_started)).days, 1))
        return 1 / days

    def get_stripped_tags(self, prefix='', exclude_prefix=''):
        """Return a set of stripped tags."""
        tags = self.get_tags()
        if not tags:
            return []
        tagset = set([])
        for tag in tags:
            if exclude_prefix and tag.startswith(exclude_prefix):
                continue
            if prefix and not tag.startswith(prefix):
                continue
            if tag.startswith("artist:") or tag.startswith("album:"):
                stripped = ":".join(tag.split(":")[1:])
            else:
                stripped = tag
            tagset.add(stripped)
        return tagset

    def get_non_geo_tags(self, prefix='', exclude_prefix=''):
        """Get all the song tags unrelated to geotagging."""
        song_tags = self.get_stripped_tags(
            prefix=prefix, exclude_prefix=exclude_prefix)
        return [
            t for t in song_tags if
            not t.startswith('geohash:') and
            not t == 'geotagged']

    def get_geohashes(self):
        """Get all the geohashes from this song."""
        song_tags = self.get_stripped_tags()
        geohashes = [
            t.split(':')[1] for t in song_tags if t.startswith('geohash:')]
        if GEOHASH:
            for ghash in geohashes[:]:
                try:
                    geohashes.extend(geohash.neighbors(ghash))
                except ValueError:
                    # invalid geohash
                    print(
                        "Invalid geohash: %s in %s - %s" % (
                            ghash, self.get_artist(), self.get_title()))
        return geohashes


class PlayerBase(metaclass=ABCMeta):

    @abstractmethod
    def construct_album_search(self, album, album_artist=None, album_id=None):
        """Construct a search for songs from this album."""

    @abstractmethod
    def construct_file_search(self, filename):
        """Construct a search for songs with this filename."""

    @abstractmethod
    def construct_files_search(self, filenames):
        """Construct search for songs with any of these filenames."""

    @abstractmethod
    def construct_track_search(self, artist, title):
        """Construct a search for songs with this artist and title."""

    @abstractmethod
    def construct_artist_search(self, artist):
        """Construct a search for songs with this artist."""

    @abstractmethod
    def construct_tag_search(self, tags):
        """Construct a search for songs with these tags."""

    @abstractmethod
    def set_variables_from_config(self, configuration):
        """Initialize user settings from the configuration storage."""

    @abstractmethod
    def get_queue_length(self):
        """Get the current length of the queue."""

    @abstractmethod
    def enqueue(self, song):
        """Put the song at the end of the queue."""

    @abstractmethod
    def search(self, search, restrictions=None):
        """Perform a player search."""

    @abstractmethod
    def get_songs_in_queue(self):
        """Return (wrapped) song objects for the songs in the queue."""

    @staticmethod
    def execute_async(method, *args, **kwargs):
        """Override this if the player can execute methods asynchronously."""
        if 'funcid' in kwargs:
            del kwargs['funcid']
        for _ in method(*args, **kwargs):
            pass
