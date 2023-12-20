"""
AutoQueue: an automatic queueing plugin library.

Copyright 2007-2016 Eric Casteleijn <thisfred@gmail.com>,
                    Daniel Nouri <daniel.nouri@gmail.com>
                    Jasper OpdeCoul <jasper.opdecoul@gmail.com>
                    Graham White
                    Naglis Jonaitis <njonaitis@gmail.com>

This program is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation; either version 2, or (at your option)
any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program; if not, write to the Free Software
Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA 02110-1301  USA.


This place is a message... and part of a system of messages... pay attention to it!

Sending this message was important to us. We considered ourselves to be a powerful
culture.

This place is not a place of honor... no highly esteemed deed is commemorated here...
nothing valued is here.

What is here was dangerous and repulsive to us. This message is a warning about danger.

The danger is in a particular location... it increases towards a center... the center of
danger is here... of a particular size and shape, and below us.

The danger is still present, in your time, as it was in ours.

The danger is to the body, and it can kill.

The form of the danger is an emanation of energy.

The danger is unleashed only if you substantially disturb this place physically. This
place is best shunned and left uninhabited.
"""

import random
import re
from collections import Counter
from datetime import datetime, timedelta
from typing import List, Optional

import dbus
import requests
from dbus.mainloop.glib import DBusGMainLoop

from autoqueue.blocking import Blocking
from autoqueue.context import Context, get_terms_from_song
from autoqueue.request import Requests
from time import time

try:
    import pyowm

    WEATHER = True
except ImportError:
    WEATHER = False
try:
    import pygeohash

    GEOHASH = True
except ImportError:
    GEOHASH = False


DBusGMainLoop(set_as_default=True)

# If you change even a single character of code, I would ask that you
# get and use your own (free) last.fm api key from here:
# http://www.last.fm/api/account
API_KEY = "09d0975a99a4cab235b731d31abf0057"
THRESHOLD = 0.5
TIMEOUT = 3000
FIVE_MINUTES = timedelta(minutes=5)
DEFAULT_NUMBER = 20
DEFAULT_LENGTH = 15 * 60
SCDL = "scdl"
PODCAST = "podcast"
BANNED_ALBUMS = [
    "[non-album tracks]",
    "album",
    "covers",
    "b-sides",
    "demos",
    "b-sides & demos",
    "demo",
    "demos",
    "ep",
    "greatest hits",
    "live",
    PODCAST,
    "s/t",
    "self titled",
    "single",
    "singles",
    "the best of",
    "the greatest hits",
    "the very best of",
    "untitled album",
    '7"',
    'split 7"',
]
ONE_DAY = 86400


def no_op(*args, **kwargs):
    pass


def tag_score(song, tags):
    """Calculate similarity score by tags."""
    if not tags:
        return 0
    song_tags = set(song.get_non_geo_tags())
    if not song_tags:
        return 0
    return len(song_tags & tags) / min(len(song_tags), len(tags))


class Configuration(object):
    def __init__(self):
        self.contextualize = True
        self.desired_queue_length = DEFAULT_LENGTH
        self.number = DEFAULT_NUMBER
        self.restrictions = None
        self.extra_context = None
        self.whole_albums = True
        self.southern_hemisphere = False
        self.favor_new = True
        self.use_lastfm = True
        self.use_groupings = True
        self.location = ""
        self.geohash = ""
        self.birthdays = ""
        self.use_gaia = True

    def get_weather(self):
        if WEATHER and self.geohash:
            return self._get_weather()

        return {}

    def get_performing_artists(self):
        """Get a list of found playing nearby venues in the near future."""
        nearby_artists = []
        for page in self._get_pages():
            nearby_artists.extend(self._get_artists(page))
        return nearby_artists

    def _get_pages(self):
        parameters = self._build_parameters()
        while True:
            page = self._get_page(parameters)
            if "events" not in page:
                print(page)
                return
            total_pages = int(page["events"]["@attr"]["totalPages"])
            page_number = int(page["events"]["@attr"]["page"])
            yield page
            if page_number == total_pages:
                return
            parameters["page"] = page_number + 1
            page = self._get_page(parameters)

    @staticmethod
    def _get_artists(page):
        artists = []
        for event in page["events"]["event"]:
            if not isinstance(event, dict):
                continue
            found = event["artists"]["artist"]
            if not isinstance(found, list):
                found = [found]
            artists.extend(found)
        return artists

    @staticmethod
    def _get_page(parameters):
        response = None
        try:
            response = requests.get(
                "http://ws.audioscrobbler.com/2.0/", params=parameters
            )
            page = response.json()
        except Exception as ex:
            print(ex)
            print(response)
            return {}
        return page

    def _build_parameters(self):
        parameters = {
            "method": "geo.getevents",
            "limit": 25,
            "api_key": API_KEY,
            "format": "json",
        }
        if self.geohash and GEOHASH:
            lat, lon = pygeohash.decode(self.geohash)[:2]
            parameters["long"] = lon
            parameters["lat"] = lat
        if self.location:
            parameters["location"] = self.location
        return parameters

    def _get_weather(self):
        try:
            # If you use this code for anything else, please register for your
            # own OWM API key for free, here:
            #
            # https://home.openweathermap.org/users/sign_up
            owm = pyowm.OWM("35c8c197224e0fb5f7a771facb4243ae")
            lat, lon = [float(v) for v in pygeohash.decode(self.geohash)[:2]]
            manager = owm.weather_manager()
            location = manager.one_call(lat=lat, lon=lon, units="metric")
            return location.current
        except Exception as exception:
            global WEATHER
            WEATHER = False
            print(repr(exception))
        return {}


class PreviousTerms(object):
    def __init__(self):
        self._terms = Counter()

    def add(self, song):
        terms = get_terms_from_song(song)
        for term in terms:
            if term in self._terms:
                self._terms[term] += 1
            else:
                self._terms[term] += 5
        for key in list(self._terms.keys()):
            if key in terms:
                continue
            self._terms[key] -= 1
            if self._terms[key] < 1:
                del self._terms[key]

    @property
    def terms(self):
        return {k for k, v in self._terms.items() if v > 1}


class Cache(object):
    def __init__(self):
        self.song = None
        self.running = False
        self.last_songs = []
        self.last_song = None
        self.nearby_artists = []
        self.weather = None
        self.weather_at = None
        self.found = False
        self.previous_terms = PreviousTerms()
        self.miss_factor = 1
        self.last_closest = -1
        self.new_time = 0
        self.old_time = 0
        self.current_request = None
        self.played_number = 0
        self.played_duration = 0

    @property
    def prefer_newly_added(self):
        print(f"new time: {self.new_time} old time {self.old_time}")
        return self.new_time < self.old_time

    def adjust_time(self, song, *, is_new):
        duration = song.get_length()
        if is_new:
            print("enqueued new song")
            self.new_time += duration
        else:
            print("enqueued old song")
            self.old_time += duration
        smallest = min(self.new_time, self.old_time)
        self.new_time -= smallest
        self.old_time -= smallest
        self.played_duration += duration
        self.played_number += 1

    def enqueue_song(self, song, *, is_new):
        self.adjust_time(song, is_new=is_new)
        self.previous_terms.add(song)

    def get_weather(self, configuration):
        if not WEATHER:
            return None

        if (
            self.weather
            and self.weather_at
            and datetime.now() < (self.weather_at + FIVE_MINUTES)
        ):
            return self.weather
        self.weather = configuration.get_weather()
        self.weather_at = datetime.now()
        return self.weather

    def set_nearby_artist(self, configuration):
        if configuration.location or configuration.geohash:
            self.nearby_artists = configuration.get_performing_artists()

    def reset_closest(self):
        self.last_closest = -1
        self.miss_factor = 1
        self.current_request = None

    def process_closest(self, match):
        if match == 0:
            self.reset_closest()
        elif match < self.last_closest or self.last_closest == -1:
            self.miss_factor = 1
            self.last_closest = match
        else:
            self.miss_factor *= 2
        print("* last closest * %s" % self.last_closest)
        print("* miss factor * %s" % self.miss_factor)


class AutoQueueBase(object):

    """Generic base class for autoqueue plugins."""

    def __init__(self, player):
        self._cache_dir = None
        self.blocking = Blocking()
        self.configuration = Configuration()
        self.context = None
        self.cache = Cache()
        bus = dbus.SessionBus()
        sim = bus.get_object(
            "org.autoqueue", "/org/autoqueue/Similarity", follow_name_owner_changes=True
        )
        self.similarity = dbus.Interface(
            sim, dbus_interface="org.autoqueue.SimilarityInterface"
        )
        self.has_gaia = self.similarity.has_gaia()
        self.player = player
        self.cache.set_nearby_artist(self.configuration)
        self.requests = Requests()

    @property
    def use_gaia(self):
        return self.configuration.use_gaia and self.has_gaia

    @staticmethod
    def error_handler(*args, **kwargs):
        """Log errors when calling D-Bus methods in a async way."""
        print("Error handler received: %r, %r" % (args, kwargs))

    def is_playing_or_in_queue(self, filename):
        for qsong in self.get_last_songs():
            if qsong.get_filename() == filename:
                return True
        return False

    def allowed(self, song, blocked_artists):
        """Check whether a song is allowed to be queued."""
        filename = song.get_filename()

        if self.requests.has(filename):
            return True

        for artist in song.get_artists():
            if artist in blocked_artists:
                print("artist blocked")
                return False

        date_search = re.compile(
            "([0-9]{4}-)?%02d-%02d" % (self.eoq.month, self.eoq.day)
        )
        for tag in song.get_stripped_tags():
            if date_search.match(tag):
                return True

        return True

    def wrong_duration(self, song):
        duration = song.get_length()
        target = 300

        if not self.cache.played_number:
            return False

        average = (self.cache.played_duration / self.cache.played_number)
        print(f'>>> {duration=}, {average=}')
        if  average > target  and duration > average:
            print(f'Song too long')
            return True

        if  average < target and duration < average:
            print(f'Song too short')
            return True

        return False

    def on_song_ended(self, song, skipped):
        """Should be called by the plugin when a song ends or is skipped."""
        if song is None:
            return

        if skipped:
            return

        for artist_name in song.get_artists():
            self.blocking.block_artist(artist_name)

    def on_song_started(self, song):
        """Should be called by the plugin when a new song starts.

        If the right conditions apply, we start looking for new songs
        to queue.

        """
        if song is None:
            return
        self.cache.song = song
        if self.cache.running:
            return
        if self.configuration.desired_queue_length == 0 or self.queue_needs_songs():
            self.queue_song()
        self.blocking.unblock_artists()
        self.pop_request(song)

    def pop_request(self, song):
        filename = song.get_filename()
        if self.requests.has(filename):
            self.requests.pop(filename)
            if self.cache.current_request == filename:
                self.cache.current_request = None

    def on_removed(self, songs):
        if not self.use_gaia:
            return
        for song in songs:
            self.remove_missing_track(song.get_filename())
            self.pop_request(song)

    def queue_needs_songs(self):
        """Determine whether the queue needs more songs added."""
        queue_length = self.player.get_queue_length()
        return queue_length < self.configuration.desired_queue_length

    @property
    def eoq(self):
        return datetime.now() + timedelta(seconds=self.player.get_queue_length())

    def construct_filenames_search(self, filenames):
        return self.player.construct_files_search(filenames)

    def construct_search(self, artist=None, title=None, tags=None, filename=None):
        """Construct a search based on several criteria."""
        if filename:
            return self.player.construct_file_search(filename)
        if title:
            return self.player.construct_track_search(artist, title)
        if artist:
            return self.player.construct_artist_search(artist)
        if tags:
            return self.player.construct_tag_search(tags)

    def queue_song(self):
        """Queue a single track."""
        self.cache.running = True
        self.cache.last_songs = self.get_last_songs()
        song = self.cache.last_song = self.cache.last_songs.pop()
        self.analyze_and_callback(
            song.get_filename(),
            reply_handler=self.analyzed,
            empty_handler=self.gaia_reply_handler,
        )

    def get_best_track(self, filename):
        all_requests = [
            f
            for f in self.requests.get_requests()
            if not self.is_playing_or_in_queue(f)
        ]
        if not all_requests:
            newly_added = list(self.get_newest(days=1)) if self.cache.prefer_newly_added else []
            if newly_added:
                print(f"{len(newly_added)} newly added songs found.")
                print("Looking for recently added songs:")
                self.similarity.get_ordered_gaia_tracks_from_list(
                    filename,
                    newly_added,
                    reply_handler=self.gaia_reply_handler,
                    error_handler=self.gaia_error_handler,
                    timeout=TIMEOUT,
                )
            else:
                self.similarity.get_ordered_gaia_tracks(
                    filename,
                    self.configuration.number,
                    reply_handler=self.gaia_reply_handler,
                    error_handler=self.gaia_error_handler,
                    timeout=TIMEOUT,
                )
        elif len(all_requests) == 1:
            self.best_request_handler(all_requests[0])
        else:
            print("{} requests left in queue.".format(len(all_requests)))
            self.similarity.get_best_match(
                filename,
                all_requests,
                reply_handler=self.best_request_handler,
                error_handler=self.best_request_error_handler,
                timeout=TIMEOUT,
            )

    def best_request_error_handler(self, *args, **kwargs):
        self.error_handler(*args, **kwargs)
        all_requests = [
            filename
            for filename in self.requests.get_requests()
            if not self.is_playing_or_in_queue(filename)
        ]
        self.gaia_reply_handler([(0, all_requests[0])])

    def best_request_handler(self, request):
        song = self.cache.last_song
        if not song:
            return

        filename = song.get_filename()
        if not filename:
            return

        if request:
            print("*****" + request)
            if request in self.requests.get_requests() or request in self.get_newest():
                self.gaia_reply_handler([(0, request)])
                return

            self.cache.current_request = request
            self.similarity.get_ordered_gaia_tracks_by_request(
                filename,
                self.configuration.number * self.cache.miss_factor,
                self.cache.current_request,
                reply_handler=self.gaia_reply_handler,
                error_handler=self.gaia_error_handler,
                timeout=TIMEOUT,
            )
            return
        else:
            print("***** no requests")
        self.similarity.get_ordered_gaia_tracks(
            filename,
            self.configuration.number,
            reply_handler=self.gaia_reply_handler,
            error_handler=self.gaia_error_handler,
            timeout=TIMEOUT,
        )

    def analyzed(self):
        song = self.cache.last_song
        filename = song.get_filename()
        if not filename:
            return
        if self.use_gaia:
            print("Get similar tracks for: %s" % filename)
            self.get_best_track(filename)
        else:
            self.gaia_reply_handler([])

    def gaia_reply_handler(self, results):
        """Handler for (gaia) similar tracks returned from dbus."""
        self.player.execute_async(self._gaia_reply_handler, results=results)

    def gaia_error_handler(self, *args, **kwargs):
        self.error_handler(*args, **kwargs)
        self.player.execute_async(self._gaia_reply_handler)

    def continue_queueing(self):
        if not self.queue_needs_songs():
            self.done()
        else:
            self.queue_song()

    def _gaia_reply_handler(self, results=None):
        """Exexute processing asynchronous."""
        self.cache.found = False
        if results:
            if self.cache.current_request:
                self.cache.process_closest(results[0][0])

            for _ in self.process_filename_results(
                [
                    {"score": match, "filename": filename}
                    for match, filename in results[: self.configuration.number]
                ]
            ):
                yield

        if self.cache.found:
            self.continue_queueing()
            return

        if self.cache.current_request:
            song = self.cache.last_song
            filename = song.get_filename()
            if not filename:
                return
            self.cache.current_request = None
            self.similarity.get_ordered_gaia_tracks(
                filename,
                self.configuration.number,
                reply_handler=self.gaia_reply_handler,
                error_handler=self.gaia_error_handler,
                timeout=TIMEOUT,
            )
            return

    def done(self):
        """Analyze the last song and stop."""
        song = self.get_last_songs()[-1]
        self.analyze_and_callback(song.get_filename())
        self.cache.running = False

    def analyze_and_callback(self, filename, reply_handler=no_op, empty_handler=no_op):
        if not filename:
            return
        if self.use_gaia:
            print("Analyzing: %s" % filename)
            self.similarity.analyze_track(
                filename,
                reply_handler=reply_handler,
                error_handler=self.gaia_error_handler,
                timeout=TIMEOUT,
            )
        else:
            empty_handler([])

    @staticmethod
    def satisfies(song, criteria):
        """Check whether the song satisfies any of the criteria."""
        filename = criteria.get("filename")
        if filename:
            return filename == song.get_filename()
        title = criteria.get("title")
        artist = criteria.get("artist")
        if title:
            return (
                song.get_title().lower() == title.lower()
                and song.get_artist().lower() == artist.lower()
            )
        if artist:
            artist_lower = artist.lower()
            for song_artist in song.get_artists():
                if song_artist.lower() == artist_lower:
                    return True
            return False
        tags = criteria.get("tags", [])
        song_tags = song.get_tags()
        for tag in tags:
            if (
                tag in song_tags
                or "artist:%s" % (tag,) in song_tags
                or "album:%s" % (tag,) in song_tags
            ):
                return True
        return False

    def search_filenames(self, results):
        filenames = [r["filename"] for r in results]
        search = self.construct_filenames_search(filenames)
        self.perform_search(search, results)

    def search_database(self, results):
        """Search for songs in results."""
        searches = [
            self.construct_search(
                artist=result.get("artist"),
                title=result.get("title"),
                filename=result.get("filename"),
                tags=result.get("tags"),
            )
            for result in results
        ]

        combined_searches = "|(" ",".join(searches) + ")"

        self.perform_search(combined_searches, results)

    def get_current_request(self):
        filename = self.cache.current_request
        if not filename:
            return

        search = self.construct_filenames_search([filename])
        songs = self.player.search(search)
        if not songs:
            return

        return songs[0]

    def perform_search(self, search, results):
        start_time = time()
        songs = {
            song.get_filename(): song for song in
            self.player.search(search, restrictions=self.configuration.restrictions)
        }
        song_values = set(songs.values())
        found = set()
        for result in results:
            filename = str(result.get('filename'))
            song = None
            if filename:
                song = songs.get(filename)
                if song:
                    result['song'] = song
                    found.add(song)
                    continue
                print(f'>>>>> song with {filename=} not found <<<<')
            if not song:
                for song in song_values - found:
                    if self.satisfies(song, result):
                        result["song"] = song
                        found.add(song)
                        break
        print("quodlibet search took %f s" % (time() - start_time,))

    def remove_missing_track(self, filename):
        print("Remove similarity for %s" % filename)
        if not isinstance(filename, str):
            filename = str(filename, "utf-8")
        self.similarity.remove_track_by_filename(
            filename,
            reply_handler=no_op,
            error_handler=self.error_handler,
            timeout=TIMEOUT,
        )

    def adjust_scores(self, results, invert_scores):
        """Adjust scores based on similarity with previous song and context."""
        if self.configuration.contextualize:
            self.context = Context(
                context_date=self.eoq,
                configuration=self.configuration,
                cache=self.cache,
                request=self.get_current_request(),
            )
            maximum_score = max(result["score"] for result in results) + 1
            for result in results[:]:
                if "song" not in result:
                    results.remove(result)
                    continue
                if invert_scores:
                    result["score"] = maximum_score - result["score"]
                self.context.adjust_score(result)
                yield

    def pick_result(self, results):
        current_requests = self.requests.get_requests()
        newest = self.get_newest()
        blocked_artists = self.blocking.get_blocked_artists(self.get_last_songs())
        self.pick(results, newest, current_requests, blocked_artists)
        if not self.cache.found:
            self.pick(results, newest, current_requests, blocked_artists, relax=True)

    def pick(self, results, newest, current_requests, blocked_artists, relax=False):
        number_of_results = len(results)
        for number, result in enumerate(sorted(results, key=lambda x: x["score"])):
            song = result.get("song")
            if not song:
                print("'song' not found in %s" % result)
                continue
            self.log_lookup(number, result)
            filename = song.get_filename()
            if self.is_playing_or_in_queue(filename):
                continue
            is_new = filename in newest
            if filename not in current_requests:
                rating = song.get_rating()
                if rating is NotImplemented:
                    rating = THRESHOLD
                for reason in result.get("reasons", []):
                    print("  %s" % (reason,))

                if number_of_results > 1:
                    wait_seconds = (1 + (song.get_length() / 6)) * ONE_DAY - (
                        self.eoq - datetime.fromtimestamp(song.get_last_started())
                    ).total_seconds()
                    if wait_seconds > 0:
                        # a 60 minute track will be played at most once every 60 days.
                        print(
                            "played too recently. (need to wait %s more days)"
                            % (wait_seconds / ONE_DAY,)
                        )
                        continue
                    print("score: %03.2f" % (rating,))
                    if not relax and self.wrong_duration(song):
                        continue
                    if (
                        not is_new
                        and not relax
                        and not current_requests
                        and random.random() > rating
                        and not (
                            self.configuration.favor_new and song.get_playcount() == 0
                        )
                    ):
                        print("randomly skipped")
                        continue
                if not relax and not self.allowed(song, blocked_artists):
                    continue

            if self.maybe_enqueue_album(song, is_new=is_new):
                self.cache.found = True
                return

            self.enqueue_song(song, is_new=is_new)
            self.cache.found = True
            return

    def get_newest(self, days: Optional[int] = None) -> List[str]:
        results = set()
        days = days or 7
        while not results:
            print(f"{days=}")
            search = self.player.construct_recently_added_search(days=days)
            results = {
                song.get_filename()
                for song in sorted(
                    self.player.search(search),
                    key=lambda s: s.get_added(),
                    reverse=True,
                )
                if song
                and song.get_filename()
                and not self.is_playing_or_in_queue(song.get_filename())
            }
            days *= 2
        print(f"{len(results)=}")

        return results

    def process_filename_results(self, results):
        if not results:
            return
        self.search_filenames(results)
        if not self.cache.current_request:
            for _ in self.adjust_scores(results, invert_scores=False):
                yield
        if not results:
            return
        self.pick_result(results)

    @staticmethod
    def log_lookup(number, result):
        look_for = str(result.get("artist", ""))
        if look_for:
            title = str(result.get("title", ""))
            if title:
                look_for += " - " + title
        elif "filename" in result:
            look_for = str(result["filename"])
        elif "tags" in result:
            look_for = result["tags"]
        else:
            print(repr(result))
            look_for = str(result)
        print("%03d: %06d %s" % (number + 1, result.get("score", 0), look_for))

    def maybe_enqueue_album(self, song, *, is_new):
        """Determine if a whole album should be queued, and do so."""
        current_requests = self.requests.get_requests()
        if (
            self.configuration.whole_albums
            and song.get_tracknumber() == 1
            and (
                song.get_filename() in current_requests
                or (song.get_playcount() == 0 or random.random() > 0.5)
            )
        ):
            album = song.get_album()
            album_artist = song.get_album_artist()
            album_id = song.get_musicbrainz_albumid()
            if (
                album
                and album.lower() not in BANNED_ALBUMS
                and PODCAST not in song.get_filename()
                and SCDL not in song.get_filename()
            ):
                return self.enqueue_album(
                    album,
                    album_artist,
                    album_id,
                    is_new=is_new,
                )

        return False

    def enqueue_song(self, song, *, is_new):
        self.cache.enqueue_song(song, is_new=is_new)
        self.player.enqueue(song)

    def enqueue_album(self, album, album_artist, album_id, *, is_new):
        """Try to enqueue whole album."""
        search = self.player.construct_album_search(
            album=album, album_artist=album_artist, album_id=album_id
        )
        songs = sorted(
            [
                (song.get_discnumber(), song.get_tracknumber(), i, song)
                for i, song in enumerate(self.player.search(search))
                if song.get_tracknumber()
            ]
        )
        if songs:
            for _, _, _, song in songs:
                self.enqueue_song(song, is_new=is_new)
            return True
        return False

    def get_last_songs(self):
        """Return the currently playing song plus the songs in the queue."""
        queue = self.player.get_songs_in_queue() or []
        return [self.cache.song] + queue

    def get_ordered_similar_by_tag(self, last_song):
        """Get similar tracks by tag."""
        tag_set = set(last_song.get_non_geo_tags())
        if not tag_set:
            return []
        search = self.construct_search(tags=list(tag_set))
        songs = sorted(
            [
                (tag_score(song, tag_set), song.get_filename())
                for song in self.player.search(search)
            ],
            reverse=True,
        )
        return [{"score": score, "filename": filename} for score, filename in songs]
