import sqlite3, os
import const, gtk
from widgets import main
from plugins.songsmenu import SongsMenuPlugin
from autoqueue.mirage import Mir, Db
from autoqueue.autoqueue import get_track, get_artist_tracks
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

    def player_enqueue(self, songs):
        """Put the song at the end of the queue"""
        gtk.gdk.threads_enter()
        # XXX: main is None here sometimes, for some reason I haven't
        # yet figured out. This stops execution completely, so I put
        # in this ugly hack.
        if main:
            main.playlist.enqueue(songs)
            print songs
            gtk.gdk.threads_leave()

    def plugin_songs(self, songs):
        copool.add(self.do_stuff, songs)

    def do_stuff(self, songs):
        db = Db()
        l = len(songs)
        print "mirage analysis"
        for i, song in enumerate(songs):
            artist_name = song.comma("artist").lower()
            title = get_title(song)
            print "%03d/%03d %s - %s" % (i + 1, l, artist_name, title)
            filename = song("~filename")
            track = get_track(artist_name, title)
            track_id, artist_id = track[0], track[1]
            if db.get_track(track_id):
                continue
            exclude_ids = get_artist_tracks(artist_id)
            try:
                scms = self.mir.analyze(filename)
            except:
                return
            db.add_and_compare(track_id, scms,exclude_ids=exclude_ids)
            yield True
        print "done"
        ids_and_songs = [
            (get_track(song.comma("artist").lower(), get_title(song))[0],
             song) for song in songs]
        clusterer = Clusterer(ids_and_songs, db.compare)
        qsongs = []
        for cluster in clusterer.clusters:
            qsongs.extend([c for id, c in cluster])
        self.player_enqueue(qsongs)


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
