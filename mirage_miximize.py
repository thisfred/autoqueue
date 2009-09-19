import sqlite3, os
import const, gtk
from plugins.songsmenu import SongsMenuPlugin
from mirage import Mir, Db
from quodlibet.util import copool
from scipy import *

def get_title(song):
    """return lowercase UNICODE title of song"""
    version = song.comma("version").lower()
    title = song.comma("title").lower()
    if version:
        return "%s (%s)" % (title, version)
    return title


class MirageMiximizePlugin(SongsMenuPlugin):
    PLUGIN_ID = "Mirage Miximize"
    PLUGIN_NAME = _("Mirage Miximize")
    PLUGIN_DESC = _("Add selected songs to the queue in ideal order based on"
                    " mirage distances.")
    PLUGIN_ICON = "gtk-find-and-replace"
    PLUGIN_VERSION = "0.1"

    def __init__(self, *args):
        super(MirageMiximizePlugin, self).__init__(*args)
        self.mir = Mir()
        self.dbpath = os.path.join(self.player_get_userdir(), "similarity.db")

    def player_get_userdir(self):
        """get the application user directory to store files"""
        try:
            return const.USERDIR
        except AttributeError:
            return const.DIR

    def player_enqueue(self, songs):
        """Put the song at the end of the queue"""
        # XXX: main is None here sometimes, for some reason I haven't
        # yet figured out. This stops execution completely, so I put
        # in this ugly hack.
        from widgets import main
        if main:
            main.playlist.enqueue(songs)

    def plugin_songs(self, songs):
        copool.add(self.do_stuff, songs)

    def do_stuff(self, songs):
        db = Db(self.dbpath)
        l = len(songs)
        print "mirage analysis"
        for i, song in enumerate(songs):
            artist_name = song.comma("artist").lower()
            title = get_title(song)
            print "%03d/%03d %s - %s" % (i + 1, l, artist_name, title)
            filename = song("~filename")
            track = self.get_track(artist_name, title)
            track_id, artist_id = track[0], track[1]
            if db.has_scores(track_id):
                continue
            scms = db.get_track(track_id)
            if not scms:
                try:
                    scms = self.mir.analyze(filename)
                except:
                    return
                db.add_track(track_id, scms)
            yield
        yield
        print "done"
        ids_and_songs = [
            (self.get_track(song.comma("artist").lower(), get_title(song))[0],
             song) for song in songs]
        clusterer = Clusterer(ids_and_songs, db.compare)
        qsongs = []
        for cluster in clusterer.clusters:
            qsongs.extend([c for id, c in cluster])
            yield
        self.player_enqueue(qsongs)

    def get_track(self, artist_name, title):
        """get track information from the database"""
        connection = sqlite3.connect(
            self.dbpath, timeout=5.0, isolation_level="immediate")
        connection.text_factory = str
        title = title.encode("UTF-8")
        artist_id = self.get_artist(artist_name)[0]
        rows = connection.execute(
            "SELECT * FROM tracks WHERE artist = ? AND title = ?",
            (artist_id, title))
        for row in rows:
            return row
        connection.execute(
            "INSERT INTO tracks (artist, title) VALUES (?, ?)",
            (artist_id, title))
        connection.commit()
        rows = connection.execute(
            "SELECT * FROM tracks WHERE artist = ? AND title = ?",
            (artist_id, title))
        for row in rows:
            connection.close()
            return row
        connection.close()

    def get_artist(self, artist_name):
        """get artist information from the database"""
        connection = sqlite3.connect(
            self.dbpath, timeout=5.0, isolation_level="immediate")
        connection.text_factory = str
        artist_name = artist_name.encode("UTF-8")
        rows = connection.execute(
            "SELECT * FROM artists WHERE name = ?", (artist_name,))
        for row in rows:
            return row
        connection.execute(
            "INSERT INTO artists (name) VALUES (?)", (artist_name,))
        connection.commit()
        rows = connection.execute(
            "SELECT * FROM artists WHERE name = ?", (artist_name,))
        for row in rows:
            connection.close()
            return row
        connection.close()

    def get_artist_tracks(self, artist_id):
        connection = sqlite3.connect(
            self.dbpath, timeout=5.0, isolation_level="immediate")
        connection.text_factory = str
        rows = connection.execute(
            "SELECT tracks.id FROM tracks INNER JOIN artists"
            " ON tracks.artist = artists.id WHERE artists.id = ?",
            (artist_id, ))
        return [row[0] for row in rows]

def match(cluster1, cluster2):
    return (
        cluster1[0] == cluster2[0] or cluster1[-1] == cluster2[0] or
        cluster1[0] == cluster2[-1] or cluster1[-1] == cluster2[-1])

def in_the_middle(song1, song2, cluster):
    if song1 in cluster:
        index = cluster.index(song1)
        if index > 0 and index < len(cluster) - 1:
            return True
    if song2 in cluster:
        index = cluster.index(song2)
        if index > 0 and index < len(cluster) - 1:
            return True
    return False

def at_the_ends(song1, song2, cluster):
    return (cluster[0] == song1 and cluster[-1] == song2) or (
        cluster[-1] == song1 and cluster[0] == song2)


class Pair():
    def __init__(self, song1, song2, score):
        self.song1 = song1
        self.song2 = song2
        self.score = score

    def other(self, song):
        if self.song1 == song:
            return self.song2
        return self.song1

    def songs(self):
        return [self.song1, self.song2]

    def __cmp__(self, other):
        if self.score < other.score:
            return -1
        if self.score > other.score:
            return 1
        return 0


class Clusterer(object):
    def __init__(self, songs, comparison_function):
        self.clusters = []
        self.similarities = []
        self.build_similarity_matrix(songs, comparison_function)
        self.build_clusters()

    def build_similarity_matrix(self, songs, comparison_function):
        for song in songs:
            for song2 in songs[songs.index(song) + 1:]:
                self.similarities.append(
                    Pair(song, song2, comparison_function(song[0], song2[0])))
        self.similarities.sort()

    def join(self, cluster1, cluster2):
        if cluster1[0] == cluster2[0]:
            cluster2.reverse()
            result = cluster2  + cluster1[1:]
        elif cluster1[-1] == cluster2[0]:
            result = cluster1 + cluster2[1:]
        elif cluster1[0] == cluster2[-1]:
            result = cluster2 + cluster1[1:]
        else:
            cluster2.reverse()
            result = cluster1[:-1] + cluster2
        self.clean_similarities(result)
        return result

    def merge_clusters(self):
        new = []
        clusters = self.clusters
        while clusters:
            cluster1 = clusters.pop(0)
            found = False
            for cluster in clusters[:]:
                if match(cluster, cluster1):
                    new.append(self.join(cluster1, cluster))
                    clusters.remove(cluster)
                    found = True
                    break
            if not found:
                new.append(cluster1)
        self.clusters = new

    def build_clusters(self):
        sim = self.similarities.pop(0)
        self.clusters = [sim.songs()]
        while self.similarities:
            sim = self.similarities.pop(0)
            new = []
            found = None
            new = []
            for cluster in self.clusters[:]:
                if not found:
                    if cluster[0] in sim.songs():
                        found = cluster[0]
                        cluster = [sim.other(found)] + cluster
                        self.clean_similarities(cluster)
                    elif cluster[-1] in sim.songs():
                        found = cluster[-1]
                        cluster = cluster + [sim.other(found)]
                        self.clean_similarities(cluster)
                new.append(cluster)
            self.clusters = new
            if found is None:
                self.clusters.append(sim.songs())
            self.merge_clusters()

    def clean_similarities(self, cluster):
        new = []
        for sim in self.similarities:
            song1, song2 = sim.songs()
            if in_the_middle(song1, song2, cluster):
                continue
            elif at_the_ends(song1, song2, cluster):
                continue
            new.append(sim)
        self.similarities = new
