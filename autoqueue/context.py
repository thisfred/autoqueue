"""Context awareness filters."""

import re
from collections import OrderedDict
from datetime import date, datetime, time, timedelta

import nltk
from dateutil.easter import easter
from dateutil.rrule import TH, YEARLY, rrule
from nltk import word_tokenize
from nltk.corpus import wordnet

nltk.download('punkt')
nltk.download('wordnet')

HISTORY = 10

HALF_HOUR = timedelta(minutes=30)
ONE_HOUR = timedelta(hours=1)
THREE_HOURS = timedelta(hours=3)
SIX_HOURS = timedelta(hours=6)
ONE_DAY = timedelta(days=1)
THREE_DAYS = timedelta(days=3)
FORTY_FIVE_DAYS = timedelta(days=45)
TWO_MONTHS = timedelta(days=60)
SIX_MONTHS = timedelta(days=182)
ONE_YEAR = timedelta(days=365)

TIME = re.compile(r'([0-9]{2}):([0-9]{2})')
STOPWORDS = {
    '.', ':', '"', "'", ',', '(', ')', '[', ']', '-', '/', "'ll", "'m", "'s",
    'a', 'am', 'an', 'and', 'are', 'be', 'been', 'being', 'de', 'did', 'do',
    'for', 'get', 'go', 'goes', 'going', 'got', 'had', 'have', 'he', 'her',
    'him', 'his', 'i', 'in', 'is', 'it', 'la', 'let', 'made', 'make', 'me',
    'my', "n't", 'no', 'not', 'of', 'on', 'or', 'our', 'she', 'so', 'that',
    'the', 'their', 'them', 'these', 'they', 'this', 'those', 'to', 'us',
    'was', 'we', 'were', 'went', 'y', 'you', 'your', 'daytrotter_sessions'}

# remove problematic synsets
EXCLUSIONS = {
    'air': {'breeze.n.01', 'wind.n.01'},
    'black': {'dark.n.01'},
    'closer': {'person.n.01'},
    'cloud': {'fog.n.02'},
    'clouds': {'fog.n.02'},
    'calm': {'wind.n.01'},
    'days': {'day.n.04'},
    'down': {'eat.v.01'},
    'fall': {'fall.n.01', 'dusky.s.01', 'twilight.n.01'},
    'friday': {'day.n.04'},
    'jan': {'january.n.01'},
    'jul': {'july.n.01'},
    'mar': {'march.n.01'},
    'mars': {'march.n.01'},
    'may': {'may.n.01'},
    'mon': {'monday.n.00'},
    'monday': {'day.n.04'},
    'morning': {'dawn.n.01', 'dawn.n.02', 'dawn.v.02', 'dawn.v.03'},
    'night': {'twilight.n.01', 'dark.n.01'},
    'oh': {'ohio.n.01'},
    'rising': {'ascension.n.04'},
    'rose': {'ascension.n.04'},
    'sat': {'saturday.n.01'},
    'saturday': {'day.n.04'},
    'shadow': {'dark.a.01', 'darkness.n.02'},
    'sun': {'sunday.n.01'},
    'suns': {'sunday.n.01'},
    'sunday': {'day.n.04'},
    'thursday': {'day.n.04'},
    'tue': {'tuesday.n.00'},
    'tuesday': {'day.n.04'},
    'wed': {'wednesday.n.00'},
    'wednesday': {'day.n.04'},
}

GLOBAL_EXCLUSIONS = {
    'be.v.01', 'be.v.03'}

static_predicates = []


def static_predicate(cls):
    static_predicates.append(cls())
    return cls


class LRUCache(object):

    size = 1000

    def __init__(self, function):
        self._function = function
        self._cache = OrderedDict()

    def __call__(self, *args):
        if args in self._cache:
            value = self._cache.pop(args)
        else:
            value = self._function(*args)
        self._cache[args] = value
        while len(self._cache) > self.size:
            self._cache.popitem(last=False)
        return value


def expand_synset(synset):
    yield synset.name()
    for hyper in synset.hypernyms():
        yield hyper.name()
    for lemma in synset.lemmas():
        for form in lemma.derivationally_related_forms():
            yield form.synset().name()
        for pertainym in lemma.pertainyms():
            yield pertainym.synset().name()


def expand(word):
    word = word.replace(' ', '_')
    if word in STOPWORDS:
        return

    yield word

    stemmed = wordnet.morphy(word)
    if stemmed is None:
        return

    for synset in wordnet.synsets(stemmed):
        for term in expand_synset(synset):
            if (term not in GLOBAL_EXCLUSIONS and
                    term not in EXCLUSIONS.get(word, [])):
                yield term


def get_terms(words):
    return {term for word in words for term in expand(word)}


def get_artist_tags(song):
    return song.get_non_geo_tags(prefix='artist:', exclude_prefix='')


@LRUCache
def get_artist_terms_from_song(song):
    tag_terms = get_terms(get_artist_tags(song))
    return tag_terms


@LRUCache
def get_terms_from_song(song):
    title_terms = set()
    words = []
    for word in word_tokenize(song.get_title(with_version=False)):
        terms = {t for t in expand(word)}
        if terms:
            words.append(word)
        title_terms |= terms

    tag_terms = get_terms(
        song.get_non_geo_tags(prefix='', exclude_prefix='artist:'))
    return title_terms | tag_terms


class Context(object):

    """Object representing the current context."""

    def __init__(self, context_date, configuration, cache, request):
        self.date = context_date
        self.configuration = configuration
        self.cache = cache
        self.request = request
        self.weather = cache.get_weather(configuration)
        self.predicates = []
        self.build_predicates()

    @staticmethod
    def string_to_datetime(time_string):
        time_string, _, ampm = time_string.partition(' ')
        hour, _, minute = time_string.partition(':')
        hour = int(hour)
        minute = int(minute)
        if ampm == 'am':
            if hour == 12:
                delta = -12
            else:
                delta = 0
        else:
            if hour == 12:
                delta = 0
            else:
                delta = 12
        return datetime.combine(date.today(), time(hour + delta, minute))

    def adjust_score(self, result):
        """Adjust the score for the result if appropriate."""
        song = result['song']
        for predicate in self.predicates:
            in_context = predicate.applies_in_context(self)
            applies = predicate.applies_to_song(song, exclusive=False)
            if applies and in_context:
                predicate.positive_score(result, applies)
            elif predicate.applies_to_song(song, exclusive=True) \
                    and not in_context:
                predicate.negative_score(result)

    def build_predicates(self):
        """Construct predicates to check against the context."""
        self.add_standard_predicates()
        self.add_song_year_predicate()
        self.add_location_predicates()
        self.add_weather_predicates()
        self.add_birthday_predicates()
        self.add_extra_predicates()
        self.add_last_song_predicates()
        self.add_nearby_artist_predicates()

    def add_nearby_artist_predicates(self):
        for artist in set(self.cache.nearby_artists):
            self.predicates.append(Artist(artist))

    def _add_common_terms(self):
        common = Terms(self.cache.previous_terms.terms)
        self.predicates.append(common)

    def _add_artist_predicate_from_song(self, song):
        if not song:
            return
        self.predicates.append(ArtistTerms.from_song(song))

    def _add_artist_predicate(self):
        self._add_artist_predicate_from_song(self.cache.last_song)
        self._add_artist_predicate_from_song(self.request)

    def _add_terms_from_song(self, song):
        if not song:
            return
        self.predicates.append(Terms.from_song(song))

    def _add_terms(self):
        self._add_terms_from_song(self.cache.last_song)
        self._add_terms_from_song(self.request)

    def _add_geohash(self):
        self.predicates.append(Geohash(self.cache.last_song.get_geohashes()))

    def add_last_song_predicates(self):
        if not self.cache.last_song:
            return
        self._add_common_terms()
        self._add_artist_predicate()
        self._add_terms()
        self._add_geohash()

    def add_extra_predicates(self):
        if self.configuration.extra_context:
            words = (
                l.strip().lower()
                for l in self.configuration.extra_context.split(','))
            self.predicates.extend([String(word) for word in words])

    def add_birthday_predicates(self):
        for name_date in self.configuration.birthdays.split(','):
            if ':' not in name_date:
                continue
            name, _, date_string = name_date.strip().partition(':')
            birth_date = self.get_date(date_string)
            age = self.date.year - birth_date.year
            self.predicates.append(
                Birthday(birth_date=birth_date, name=name, age=age))

    @staticmethod
    def get_date(date_string):
        date_string = date_string.strip()
        delimiter = '-' if '-' in date_string else '/'
        return date(*[int(i) for i in date_string.split(delimiter)])

    def get_astronomical_times(self, weather):
        sunrise = weather.get_sunrise_time()
        sunset = weather.get_sunset_time()
        predicates = []
        if sunrise and sunset:
            sunrise = datetime.fromtimestamp(sunrise)
            predicates.append(Dawn(sunrise))
            sunset = datetime.fromtimestamp(sunset)
            predicates.append(Dusk(sunset))
            predicates.append(Daylight(start=sunrise, end=sunset))
            predicates.append(NotDaylight(start=sunrise, end=sunset))
            predicates.append(Sun(start=sunrise, end=sunset))
        return predicates

    def add_weather_predicates(self):
        if not self.weather:
            return
        self.predicates.extend([
            Freezing(), Cold(), Hot(), Calm(), Breeze(), Wind(), Storm(),
            Gale(), Hurricane(), Humid(), Cloudy(), Rain(), Snow(), Sleet(),
            Fog()])
        self.predicates.extend(self.get_astronomical_times(self.weather))
        self.predicates.extend(self.get_other_conditions(self.weather))

    @staticmethod
    def get_other_conditions(weather):
        predicates = []
        for condition in weather.get_detailed_status().lower().split('/'):
            condition = condition.strip()
            with open('weather_conditions.txt', 'a') as weather_file:
                weather_file.write('%s\n' % condition)
            if condition:
                results = []
                unmodified = condition.split()[-1]
                if unmodified in ('rain', 'rainy', 'drizzle', 'clouds',
                                  'clouds', 'fog', 'foggy', 'mist', 'misty',
                                  'fair'):
                    continue
                if unmodified not in results:
                    results.append(unmodified)
                if unmodified[-1] == 'y':
                    if unmodified[-2] == unmodified[-3]:
                        results.append(unmodified[:-2])
                    else:
                        results.append(unmodified[:-1])
                if results:
                    predicates.extend(
                        [String(c) for c in results])
        return predicates

    def add_location_predicates(self):
        if self.configuration.location:
            locations = (
                l.lower() for l in self.configuration.location.split(','))
            self.predicates.extend(
                [String(location) for location in locations])
        if self.configuration.geohash:
            self.predicates.append(Geohash([self.configuration.geohash]))

    def add_song_year_predicate(self):
        self.predicates.append(SongYear(self.date.year))

    def add_standard_predicates(self):
        self.predicates.extend(static_predicates)
        for predicate in (Year, Date.from_date, Now, Midnight, Noon, Spring,
                          Summer, Fall, Winter, Evening, Morning, Afternoon,
                          Night, DayTime, Christmas, NewYear, Halloween,
                          Easter, Thanksgiving):
            self.predicates.append(predicate(self.date))


class Predicate(object):

    def applies_to_song(self, song, exclusive):
        raise NotImplementedError

    def applies_in_context(self, context):
        return True

    def get_factor(self, song, exclusive):
        return 1.0

    def positive_score(self, result, applies):
        result['score'] /= 1 + self.get_factor(result['song'], exclusive=False)
        result.setdefault('reasons', []).append((self, applies))

    def negative_score(self, result):
        pass

    def __repr__(self):
        return '<%s>' % self.__class__.__name__


class Terms(Predicate):

    terms = tuple()
    non_exclusive_terms = tuple()
    regex_terms = tuple()
    terms_expanded = frozenset()
    non_exclusive_terms_expanded = frozenset()
    song = None

    def __init__(self, ne_expanded_terms=frozenset()):
        ne_expanded_terms = frozenset(ne_expanded_terms)
        ne_expanded_terms = (
            self.non_exclusive_terms_expanded | ne_expanded_terms)
        if self.terms_expanded or ne_expanded_terms:
            self.non_exclusive_terms_expanded = ne_expanded_terms
        else:
            self.terms_expanded = frozenset(get_terms(self.terms))
            self.non_exclusive_terms_expanded = frozenset(get_terms(
                self.non_exclusive_terms))

    def get_intersection(self, song_terms, exclusive=True):
        if exclusive:
            return song_terms & self.terms_expanded

        return song_terms & (
            self.terms_expanded | self.non_exclusive_terms_expanded)

    def applies_to_song(self, song, exclusive):
        return (
            self.regex_terms_match(song, exclusive) or
            self.get_intersection(self._get_song_terms(song), exclusive))

    def regex_terms_match(self, song, exclusive):
        """Determine whether the predicate applies to the song."""
        if exclusive:
            return False

        for search in self.regex_terms:
            for tag in song.get_non_geo_tags():
                if search.match(tag):
                    return True

        return False

    @classmethod
    def from_song(cls, song):
        terms = cls._get_song_terms(song)
        new = cls(ne_expanded_terms=frozenset(terms))
        new.song = song
        return new

    @staticmethod
    def _get_song_terms(song):
        return get_terms_from_song(song)

    def __repr__(self):
        song = self.song
        if not song:
            return super(Terms, self).__repr__()

        return '<%s: %s - %s>' % (
            self.__class__.__name__, song.get_artist(), song.get_title())


class ArtistTerms(Terms):

    @staticmethod
    def _get_song_terms(song):
        return get_artist_terms_from_song(song)


class ExclusiveTerms(Terms):

    def negative_score(self, result):
        result['score'] *= 1 + self.get_factor(result['song'], exclusive=True)


class Period(ExclusiveTerms):

    period = ONE_YEAR
    decay = None

    def __init__(self, peak):
        self.diff = None
        self.peak = peak
        super(Period, self).__init__()

    def get_peak(self, context):
        return self.peak

    def get_diff(self, context):
        context_datetime = context.date
        peak = self.get_peak(context)
        return self.get_diff_between_dates(context_datetime, peak)

    def get_diff_between_dates(self, context_datetime, peak):
        if not isinstance(peak, datetime):
            context_datetime = context_datetime.date()
        self.diff = abs(context_datetime - peak)
        if self.diff.total_seconds() > (self.period.total_seconds() / 2):
            self.diff = self.period - self.diff
        return self.diff

    def applies_in_context(self, context):
        return self.get_diff(context) < self.decay

    def get_factor(self, song, exclusive=False):
        factor = super(Period, self).get_factor(song, exclusive)
        if exclusive:
            return factor

        return factor * (
            1.0 - min(
                1, (self.diff.total_seconds() / self.decay.total_seconds())))


class Artist(Predicate):

    def __init__(self, artist):
        self.artist = artist

    def applies_to_song(self, song, exclusive):
        if self.artist.lower().strip() == song.get_artist().strip():
            return True
        return False

    def get_factor(self, song, exclusive):
        return 1.0


class Geohash(Predicate):

    def __init__(self, geohashes):
        self.geohashes = geohashes

    def applies_to_song(self, song, exclusive):
        for self_hash in self.geohashes:
            for other_hash in song.get_geohashes():
                if other_hash.startswith(self_hash[:2]):
                    return True

        return False

    def __repr__(self):
        return '<Geohash %r>' % self.geohashes

    def get_factor(self, song, exclusive):
        best_score = 0
        for self_hash in self.geohashes:
            for other_hash in song.get_geohashes():
                if self_hash[0] != other_hash[0]:
                    continue

                shortest = min(len(self_hash), len(other_hash))
                for i, character in enumerate(self_hash):
                    if i >= len(other_hash):
                        break

                    if character != other_hash[i]:
                        break

                    score = i / shortest
                    if score > best_score:
                        best_score = score

        return best_score


class Year(Terms):

    def __init__(self, timestamp):
        self.terms = (str(timestamp.year),)
        super(Year, self).__init__()


class SongYear(Predicate):

    def __init__(self, year):
        self.year = year

    def applies_to_song(self, song, exclusive):
        return self.was_released(song) or self.artist_died(song)

    def was_released(self, song):
        return self.year == song.get_year()

    def artist_died(self, song):
        year = str(self.year)
        artist_tags = get_artist_tags(song)
        return (
            'dead' in artist_tags and
            any(t.startswith(year) for t in artist_tags))


class String(Terms):

    def __init__(self, term):
        self.terms = (term,)
        super(String, self).__init__()

    def __repr__(self):
        return '<String %r>' % self.terms


class Weather(ExclusiveTerms):

    @staticmethod
    def get_weather_conditions(context):
        return context.weather.get_detailed_status().lower().strip().split('/')

    @staticmethod
    def get_temperature(context):
        return context.weather.get_temperature('celsius').get('temp')

    @staticmethod
    def get_wind_speed(context):
        return context.weather.get_wind().get('speed')

    @staticmethod
    def get_humidity(context):
        return context.weather.get_humidity() or 0


class Freezing(Weather):

    non_exclusive_terms_expanded = frozenset([
        u'frost.n.03', u'frost.n.01', u'ice.n.01', u'ice.n.02', u'frost.v.02',
        u'frost.v.03', u'frost.v.01', u'frost.v.04', u'freeze.v.10',
        u'freeze.n.02', u'freeze.n.01', u'freeze.v.06', u'freeze.v.07',
        u'freeze.v.04', u'freeze.v.02', u'freeze.v.08', u'snow.n.01',
        u'snow.n.02'])

    def applies_in_context(self, context):
        temperature = self.get_temperature(context)
        if temperature is None:
            return False

        if temperature > 0:
            return False

        return True


class Cold(Weather):

    non_exclusive_terms_expanded = frozenset([
        u'coldness.n.03', u'cold.a.01', u'cold.a.02', u'chill.n.01',
        u'chilliness.n.01', u'cold.s.11', u'cold.s.10', u'cold.s.13',
        u'cold.s.12', u'chilly.s.03', u'cold.s.08', u'chilly.s.01',
        u'cold.s.03', u'cold.n.03', u'cold.s.07', u'cold.s.04', u'cold.s.05'])

    def applies_in_context(self, context):
        temperature = self.get_temperature(context)
        if temperature is None:
            return False

        if temperature > 10:
            return False

        return True


class Hot(Weather):

    non_exclusive_terms_expanded = frozenset([
        u'hot.s.21', u'hot.a.01', u'hot.a.03', u'hotness.n.01', u'hot.s.19',
        u'hot.s.18', u'hot.s.15', u'hot.s.14', u'hot.s.17', u'hot.s.16',
        u'hot.s.11', u'hot.s.10', u'hot.s.13', u'hot.s.12', u'heat.n.01',
        u'blistering.s.03', u'heat.n.03', u'hot.s.08', u'hot.s.02',
        u'hot.s.06', u'hot.s.04', u'hot.s.05'])

    def applies_in_context(self, context):
        temperature = self.get_temperature(context)
        if temperature is None:
            return False

        if temperature < 25:
            return False

        return True


class Calm(Weather):

    non_exclusive_terms_expanded = frozenset([
        u'calm.a.02', u'calm_air.n.01', u'calmness.n.02', u'calm.s.01'])

    def applies_in_context(self, context):
        return self.get_wind_speed(context) < 1


class Breeze(Weather):

    non_exclusive_terms_expanded = frozenset([
        'breeze.n.01', u'breeze.v.02', u'breeziness.n.01', u'breezy.s.01',
        u'blow.v.02'])

    def applies_in_context(self, context):
        speed = self.get_wind_speed(context)
        return speed > 0


class Wind(Weather):

    non_exclusive_terms_expanded = frozenset([
        u'wind.n.01', u'gust.n.01', u'windy.s.03', u'blowy.s.01'])

    def applies_in_context(self, context):
        return self.get_wind_speed(context) > 30


class Gale(Weather):

    non_exclusive_terms_expanded = frozenset(['gale.n.01'])

    def applies_in_context(self, context):
        return self.get_wind_speed(context) > 38


class Storm(Weather):

    non_exclusive_terms_expanded = frozenset([
        u'stormy.s.02', u'stormy.a.01', u'storminess.n.02', u'storminess.n.01',
        u'storm.n.01', u'storm.n.02'])

    def applies_in_context(self, context):
        return self.get_wind_speed(context) > 54


class Hurricane(Weather):

    non_exclusive_terms_expanded = frozenset([
        'cyclonic.a.01', u'cyclonic.a.02', u'cyclone.n.02', u'hurricane.n.01'])

    def applies_in_context(self, context):
        return self.get_wind_speed(context) > 72


class Humid(Weather):

    non_exclusive_terms_expanded = frozenset(['humid.s.01', u'humidity.n.01'])

    def applies_in_context(self, context):
        return self.get_humidity(context) > 65


class Now(Period):

    period = ONE_DAY
    decay = HALF_HOUR

    def applies_to_song(self, song, exclusive):
        song_tags = song.get_non_geo_tags()
        for tag in song_tags:
            match = TIME.match(tag)
            if match:
                hour, minute = match.groups()
                song_datetime = datetime.now().replace(
                    hour=int(hour), minute=int(minute))
                if self.get_diff_between_dates(song_datetime,
                                               self.peak) < self.decay:
                    return True

        return False

    def __repr__(self):
        return '<Now %s>' % (self.peak,)


class TimeRange(ExclusiveTerms):

    def __init__(self, start, end):
        self.start = start
        self.end = end
        super(TimeRange, self).__init__()

    def applies_in_context(self, context):
        if self.start and context.date < self.start:
            return False

        if self.end and context.date > self.end:
            return False

        return True


class Daylight(TimeRange):

    terms_expanded = frozenset(['daylight.n.02'])


class NegativeTimeRange(TimeRange):

    def applies_in_context(self, context):
        return not super(
            NegativeTimeRange, self).applies_in_context(context)


class NotDaylight(NegativeTimeRange):

    terms_expanded = frozenset([
        'dark.s.03', u'dark.s.05', u'dark.s.08', u'dark.a.02', u'dark.a.01',
        u'dark.n.05', u'dark.n.01', u'dark.s.11', u'darkness.n.05',
        u'darkness.n.02'])


class Sun(TimeRange, Weather):

    non_exclusive_terms_expanded = frozenset([
        u'sun.v.01', u'sun.v.02', u'sunlight.n.01', u'fair_weather.n.01',
        u'sun.n.04', u'sun.n.01'])

    def applies_in_context(self, context):
        if super(Sun, self).applies_in_context(context):
            conditions = self.get_weather_conditions(context)
            for condition in conditions:
                if 'few clouds' in condition or 'fair' in condition:
                    return True

        return False


class Fog(Weather):

    non_exclusive_terms_expanded = frozenset([
        u'brumous.s.01', u'fogged.s.01', u'haze.n.01', u'mist.v.03',
        u'mist.n.01', u'misty.s.02', u'haziness.n.02', u'fog.n.01',
        u'fog.n.02', u'mist.v.01'])

    def applies_in_context(self, context):
        conditions = self.get_weather_conditions(context)
        for condition in conditions:
            if 'mist' in condition or 'fog' in condition\
                    or 'foggy' in condition or 'misty' in condition:
                return True

        return False


class Cloudy(Weather):

    non_exclusive_terms_expanded = frozenset([
        u'overcast.v.01', u'cloud.n.01', u'cloud.n.02', u'cloud-covered.s.01',
        u'cloudiness.n.02', u'cloudiness.n.01', u'gloom.n.01',
        u'cloudiness.n.03', u'cloudy.a.02', u'cloudy.s.03', u'cloudy.s.01'])

    def applies_in_context(self, context):
        conditions = self.get_weather_conditions(context)
        for condition in conditions:
            if 'clouds' in condition or 'overcast' in condition:
                return True

        return False


class Snow(Weather):

    non_exclusive_terms_expanded = (
        Cloudy.non_exclusive_terms_expanded | frozenset([
            u'snow.n.01', u'snow.n.02', u'snow.n.03', u'precipitation.n.03',
            u'precipitation.n.01', u'precipitate.v.03', u'snow.v.01']))

    def applies_in_context(self, context):
        conditions = self.get_weather_conditions(context)
        for condition in conditions:
            if 'snow' in condition:
                return True

        return False


class Sleet(Weather):

    non_exclusive_terms_expanded = (
        Cloudy.non_exclusive_terms_expanded | frozenset([
            'sleet.n.01', u'sleet.v.01', u'precipitation.n.03',
            u'precipitation.n.01', u'precipitate.v.03']))

    def applies_in_context(self, context):
        conditions = self.get_weather_conditions(context)
        for condition in conditions:
            if 'sleet' in condition:
                return True

        return False


class Rain(Weather):

    non_exclusive_terms_expanded = (
        Cloudy.non_exclusive_terms_expanded | frozenset([
            u'drizzle.n.01', u'drizzle.v.01', u'drizzle.v.02', u'rain.n.01',
            u'rain.n.02', u'rain.n.03', u'rain.v.01', u'raindrop.n.01',
            'rainy.s.01', u'shower.v.04', u'showery.s.01', u'shower.n.03',
            u'drop.n.02', u'droplet.n.01', u'precipitate.v.03',
            u'precipitation.n.01', u'precipitation.n.03']))

    def applies_in_context(self, context):
        conditions = self.get_weather_conditions(context)
        for condition in conditions:
            if 'rain' in condition or 'shower' in condition or\
                    'drizzle' in condition:
                return True

        return False


class Dawn(Period):

    period = ONE_DAY
    decay = ONE_HOUR

    terms_expanded = frozenset([
        u'sunrise.n.03', u'sunrise.n.02', u'aurora.n.03', u'dawn.v.03',
        u'dawn.v.02', u'sunrise.s.01', u'aurora.n.02', u'dawn.n.01',
        u'dawn.n.03', u'dawn.n.02'])


class Dusk(Period):

    period = ONE_DAY
    decay = ONE_HOUR

    terms_expanded = frozenset([
        u'sunset.s.01', u'sunset.s.02', u'sunset.n.03', u'sunset.n.02',
        u'sunset.n.01', u'twilight.n.03', u'twilight.n.02', u'twilight.n.01',
        u'dusky.s.01', u'dusk.v.01'])


class Noon(Period):

    period = ONE_DAY
    decay = HALF_HOUR
    terms_expanded = frozenset(['noon.n.01'])

    def __init__(self, now):
        super(Noon, self).__init__(
            peak=now.replace(hour=12, minute=0, second=0))


class Midnight(Period):

    period = ONE_DAY
    decay = HALF_HOUR
    terms_expanded = frozenset(['midnight.n.01'])

    def __init__(self, now):
        super(Midnight, self).__init__(
            peak=now.replace(hour=0, minute=0, second=0))


class Date(ExclusiveTerms):

    day = None
    month = None

    def __init__(self):
        self.set_regex()
        super(Date, self).__init__()

    def set_regex(self):
        if self.month and self.day:
            self.regex_terms = (
                re.compile(r"([0-9]{4}-)?%02d-%02d" % (self.month, self.day)),)

    @classmethod
    def from_date(cls, from_date):
        instance = cls()
        instance.month = from_date.month
        instance.day = from_date.day
        instance.set_regex()
        return instance

    def applies_in_context(self, context):
        return (
            context.date.day == self.day and
            context.date.month == self.month)


class Season(Period):

    decay = TWO_MONTHS

    def __init__(self, peak):
        self.terms_expanded = frozenset([
            '%s.n.01' % self.__class__.__name__.lower()])
        super(Season, self).__init__(peak=peak)

    def get_peak(self, context):
        if context.configuration.southern_hemisphere:
            return self.peak + SIX_MONTHS

        return self.peak


class Winter(Season):

    def __init__(self, now):
        super(Winter, self).__init__(
            peak=datetime(now.year - 1, 12, 21) + FORTY_FIVE_DAYS)


class Spring(Season):

    def __init__(self, now):
        super(Spring, self).__init__(
            peak=datetime(now.year, 3, 21) + FORTY_FIVE_DAYS)


class Summer(Season):

    def __init__(self, now):
        super(Summer, self).__init__(
            peak=datetime(now.year, 6, 21) + FORTY_FIVE_DAYS)


class Fall(Season):

    def __init__(self, now):
        super(Fall, self).__init__(
            peak=datetime(now.year, 9, 21) + FORTY_FIVE_DAYS)


class Month(ExclusiveTerms):

    month = 0

    def __init__(self):
        self.terms_expanded = frozenset([
            '%s.n.01' % self.__class__.__name__.lower()])
        super(Month, self).__init__()

    def applies_in_context(self, context):
        return context.date.month == self.month


@static_predicate
class January(Month):

    month = 1


@static_predicate
class February(Month):

    month = 2


@static_predicate
class March(Month):

    month = 3


@static_predicate
class April(Month):

    month = 4


@static_predicate
class May(Month):

    month = 5


@static_predicate
class June(Month):

    month = 6


@static_predicate
class July(Month):

    month = 7


@static_predicate
class August(Month):

    month = 8


@static_predicate
class September(Month):

    month = 9


@static_predicate
class October(Month):

    month = 10


@static_predicate
class November(Month):

    month = 11


@static_predicate
class December(Month):

    month = 12


class Day(ExclusiveTerms):

    day_index = 0

    def __init__(self):
        self.terms_expanded = frozenset([
            '%s.n.01' % self.__class__.__name__.lower()])
        super(Day, self).__init__()

    def applies_in_context(self, context):
        return (
            context.date.isoweekday() == self.day_index and
            context.date.hour >= 4) or (
                context.date.isoweekday() == self.day_index + 1 and
                context.date.hour < 4)


@static_predicate
class Monday(Day):

    day_index = 1


@static_predicate
class Tuesday(Day):

    day_index = 2


@static_predicate
class Wednesday(Day):

    day_index = 3


@static_predicate
class Thursday(Day):

    day_index = 4


@static_predicate
class Friday(Day):

    day_index = 5


@static_predicate
class Saturday(Day):

    day_index = 6


@static_predicate
class Sunday(Day):

    day_index = 7


class Night(Period):

    period = ONE_DAY
    decay = SIX_HOURS
    terms_expanded = frozenset([
        'night.n.01', 'night.n.02', 'night.n.03', 'night.n.07'])

    def __init__(self, now):
        super(Night, self).__init__(
            peak=now.replace(hour=0, minute=0, second=0, microsecond=0))


class DayTime(Period):

    period = ONE_DAY
    decay = SIX_HOURS
    terms_expanded = frozenset(['day.n.04'])

    def __init__(self, now):
        super(DayTime, self).__init__(
            peak=now.replace(hour=12, minute=0, second=0, microsecond=0))


class Evening(Period):

    period = ONE_DAY
    decay = THREE_HOURS
    terms_expanded = frozenset([
        'evening.n.01', 'evening.n.02', 'evening.n.03'])

    def __init__(self, now):
        super(Evening, self).__init__(peak=now.replace(hour=20))


class Morning(Period):

    period = ONE_DAY
    decay = THREE_HOURS
    terms_expanded = frozenset(['morning.n.01'])

    def __init__(self, now):
        super(Morning, self).__init__(peak=now.replace(hour=9))


class Afternoon(Period):

    period = ONE_DAY
    decay = THREE_HOURS
    terms_expanded = frozenset(['afternoon.n.01'])

    def __init__(self, now):
        super(Afternoon, self).__init__(peak=now.replace(hour=15))


@static_predicate
class Weekend(ExclusiveTerms):

    terms_expanded = frozenset([u'weekend.n.01', u'weekend.v.01'])

    def applies_in_context(self, context):
        context_date = context.date
        weekday = context_date.isoweekday()
        return weekday in (6, 7) or (weekday == 5 and context_date.hour >= 17)


class Thanksgiving(Period):

    decay = THREE_DAYS
    terms_expanded = frozenset(['thanksgiving.n.01'])
    non_exclusive_terms_expanded = frozenset([
        u'grateful.a.01', u'acknowledgment.n.03', u'thank.v.01',
        u'eating.n.01', u'gluttony.n.01', u'gluttony.n.02',
        u'consumption.n.01', u'gratefulness.n.01', u'turkey.n.01',
        u'turkey.n.04', u'gratitude.n.01', u'stuffing.n.01', u'stuffing.n.02',
        u'grateful.s.02', u'gorge.v.01', u'acknowledge.v.06',
        u'acknowledge.v.04', u'food.n.03', u'food.n.02', u'food.n.01',
        u'eat.v.01', u'eat.v.02', u'thanks.n.01', u'thanks.n.02'])

    def __init__(self, now):
        super(Thanksgiving, self).__init__(
            peak=rrule(YEARLY, byweekday=TH(4), bymonth=11).after(
                datetime(now.year, 1, 1)))


class Christmas(Period):

    decay = THREE_DAYS
    terms_expanded = frozenset(['christmas.n.01', u'christmas.n.02'])
    non_exclusive_terms_expanded = frozenset([
        'santa_claus.n.01', 'mistletoe.n.02', u'mistletoe.n.03',
        u'mistletoe.n.01', u'birth.n.02', u'bell.n.03', u'bell.n.01',
        u'joseph.n.03', u'sled.n.01', u'joseph.n.02', u'carol.v.01',
        u'mary.n.01', u'snow.n.01', u'snow.n.02', u'snow.n.03', u'sled.v.01',
        u'christian.a.02', u'christian.a.01', u'virgin_birth.n.02',
        u'bell.v.01', u'carol.n.01', u'carol.n.02', 'caribou.n.01',
        u'manger.n.01', u'jesus.n.01', u'snow.v.01'])

    def __init__(self, now):
        super(Christmas, self).__init__(peak=now.replace(day=25, month=12))


@static_predicate
class Kwanzaa(ExclusiveTerms):

    terms_expanded = frozenset(['kwanzaa.n.01'])

    def applies_in_context(self, context):
        context_date = context.date
        return (context_date.month == 12 and context_date.day >= 26) or (
            context_date.month == 1 and context_date.day == 1)


class NewYear(Period):

    decay = THREE_DAYS

    terms_expanded = frozenset(['new_year.n.01', "new_year's_eve.n.01"])
    non_exclusive_terms_expanded = frozenset([
        'champagne.n.01', u'sparkling_wine.n.01', u'champagne.n.02',
        'new.a.01', u'newness.n.01', u'fresh.s.04', u'novelty.n.02',
        u'new.s.04', u'new.s.05', u'new.a.06', u'new.s.08', u'new.s.10',
        u'new.s.11', u'newly.r.01', u'year.n.01', u'year.n.02', u'year.n.03',
        'resolution.n.01', u'resolution.n.04', u'resolution.n.06',
        u'resolution.n.07', u'resolution.n.08', u'resolution.n.09',
        u'resolution.n.11', u'decision.n.01'])

    def __init__(self, now):
        super(NewYear, self).__init__(peak=now.replace(day=31, month=12))


class Halloween(Period):

    decay = THREE_DAYS
    terms_expanded = frozenset(['halloween.n.01'])
    non_exclusive_terms_expanded = frozenset([
        u'bone.s.01', u'evil.s.02', u'dead.n.01', u'grave.n.01', u'grave.n.02',
        u'evil.a.01', u'mischief.n.01', u'frighten.v.01', u'frighten.v.02',
        u'apparition.n.03', u'dead.a.01', u'satanic.a.02', u'trick.n.01',
        u'delusive.s.01', u'haunt.v.01', u'haunt.v.02', u'creepy.s.01',
        u'wicked.a.01', u'dead_person.n.01', u'spell.n.04', u'creepy.s.02',
        u'scare.n.02', u'delusion.n.02', u'delusion.n.03', u'delusion.n.01',
        u'dead.s.14', u'dead.s.17', u'dead.s.16', u'dead.s.11', u'dead.s.10',
        u'dead.s.13', u'dead.s.12', u'satan.n.01', u'mutant.n.01',
        u'scaremonger.n.01', u'kill.v.10', u'coffin.n.01', u'bone.n.01',
        u'bone.n.02', u'killing.n.02', u'panic.n.02', u'panic.n.01',
        u'spider.n.01', u'fear.v.01', u'fear.v.03', u'fear.v.02', u'fear.v.04',
        u'bony.a.03', u'zombi.n.03', u'hellion.n.01', 'undead', u'shock.v.02',
        u'enchantress.n.02', u'devil.n.02', u'malefic.s.01', u'dracula.n.01',
        u'dracula.n.02', u'hag.n.01', u'zombi.n.01', u'wiccan.n.01',
        u'fearful.s.01', u'costume.n.01', u'costume.n.03', u'costume.n.04',
        u'occultism.n.01', u'death.n.02', u'occultism.n.02', u'die.v.01',
        u'death.n.01', u'blood.n.01', u'horror.n.01', u'horror.n.02',
        u'death.n.08', u'skeleton.n.04', u'daunt.v.01', u'costume.n.02',
        u'haunt.n.01', u'apprehension.n.01', u'dead.s.06', u'dead.s.07',
        u'dead.s.04', u'dead.s.05', u'sin.n.06', u'dead.s.08', u'dead.s.09',
        u'monster.n.01', u'monster.n.04', u'dead.a.02', u'zombie.n.05',
        u'impishness.n.01', u'ghost.n.03', u'ghost.n.01', u'pagan.n.02',
        u'devilish.s.02', u'fear.n.01', u'fear.n.03', u'hell.n.01',
        u'hell.n.02', u'hell.n.03', u'hell.n.04', u'zombi.n.02', u'hell.n.06',
        u'psychic.s.01', u'evil.n.01', u'evil.n.03', u'evil.n.02', u'die.v.02',
        u'spirit.n.04', u'mischievous.s.02', u'malevolence.n.02',
        u'shadowy.s.03', u'soul.n.01', u'terror.n.03', u'terror.n.02',
        u'pumpkin.n.02', u'pumpkin.n.01', u'trick.n.03', u'trick.n.02',
        u'lamp.n.01', u'terror.n.04', u'trick.n.07', u'die.v.10', u'hex.v.01',
        u'mythical_monster.n.01', u'occultist.n.01', u'nefariousness.n.01',
        u'werewolf.n.01', u'mutant.a.01', u'death.n.03', u'death.n.06',
        u'death.n.04', u'death.n.05', u'apparitional.s.01', u'deadness.n.02',
        u'deadness.n.03', u'witch.n.02', u'creepiness.n.01', u'malignity.n.02',
        u'chilling.s.01', u'magic_trick.n.01', u'imp.n.02', u'lantern.n.01',
        u'freak.n.01', u'prankishness.n.01', u'kill.v.01', u'creep.n.01',
        u'unholiness.n.01', u'evil_spirit.n.01', u'vampire.n.01', u'bat.n.05',
        u'bat.n.01', u'terrorization.n.01', u'transgression.n.01',
        u'kill.v.04', u'kill.v.09', u'skull.n.01'])

    def __init__(self, now):
        super(Halloween, self).__init__(peak=now.replace(day=31, month=10))


class EasterBased(ExclusiveTerms):

    days_after_easter = 0

    def applies_in_context(self, context):
        context_date = context.date
        if self.easter_offset(context_date, easter(context_date.year)):
            return True

        return False

    def easter_offset(self, from_date, easter_date):
        return (from_date.date() - easter_date).days == self.days_after_easter


class Easter(Period):

    decay = THREE_DAYS
    terms_expanded = frozenset(['easter.n.01'])
    non_exclusive_terms_expanded = frozenset([
        u'bunny.n.02', u'rabbit.n.01', u'rabbit.n.03', u'return.n.05',
        u'return.n.02', u'egg.n.02', u'egg.n.01', u'resurrect.v.03',
        u'resurrect.v.01', u'renewing.s.01', u'return.v.01', u'jesus.n.01',
        u'revival.n.01', u'resurrection.n.01', u'resurrection.n.02',
        u'revive.v.04', u'revive.v.03'])

    def __init__(self, now):
        super(Easter, self).__init__(peak=easter(now.year))


@static_predicate
class MardiGras(EasterBased):

    days_after_easter = -47
    terms_expanded = frozenset(['mardi_gras.n.01', 'mardi_gras.n.02'])
    non_exclusive_terms_expanded = frozenset([
        'carnival.n.01', 'pancake.n.01', u'fat.s.05', u'fatness.n.01',
        u'feast.n.02', u'fat.n.01', u'fete.n.01', u'fat.s.04', u'shrive.v.01',
        u'fat.s.02', u'party.n.04', u'feast.v.01', u'forgive.v.01',
        u'party.v.01', u'fat.a.01'])


@static_predicate
class AshWednesday(EasterBased):

    days_after_easter = -46
    terms_expanded = frozenset(['ash_wednesday.n.01'])
    non_exclusive_terms_expanded = frozenset([u'lent.n.01', u'ash.n.01'])


@static_predicate
class PalmSunday(EasterBased):

    days_after_easter = -7
    terms_expanded = frozenset(['palm_sunday.n.01'])
    non_exclusive_terms_expanded = frozenset([
        u'palm.n.03', u'jerusalem.n.01', u'jesus.n.01'])


@static_predicate
class MaundyThursday(EasterBased):

    days_after_easter = -3
    terms_expanded = frozenset(['maundy_thursday.n.01'])
    non_exclusive_terms_expanded = frozenset([
        'last_supper.n.01', 'discipleship.n.01', 'disciple.n.01', 'jesus.n.01',
        'apostle.n.01', 'apostle.n.02', 'apostle.n.03'])


@static_predicate
class GoodFriday(EasterBased):

    days_after_easter = -2
    terms_expanded = frozenset(['good_friday.n.01'])
    non_exclusive_terms_expanded = frozenset([
        u'cross.n.01', u'cross.n.03 ', u'cross.n.04', u'crucifixion.n.01',
        u'crucifixion.n.03', u'crucifixion.n.02', u'execute.v.01',
        u'jesus.n.01', u'torture.v.02', u'execution.n.01', u'torture.n.05'])


@static_predicate
class Ascension(EasterBased):

    days_after_easter = 39
    terms_expanded = frozenset([
        'ascension.n.03', u'ascension.n.01', u'ascension.n.04'])
    non_exclusive_terms_expanded = frozenset([
        'rise.n.02', 'rise.n.04', 'heaven.n.02', 'jesus.n.01'])


@static_predicate
class Pentecost(EasterBased):

    days_after_easter = 49
    terms_expanded = frozenset(['shavous.n.01', u'pentecost.n.01'])
    non_exclusive_terms_expanded = frozenset(['holy_ghost.n.01'])


@static_predicate
class WhitMonday(EasterBased):

    days_after_easter = 50
    terms_expanded = frozenset(['shavous.n.01', u'pentecost.n.01'])
    non_exclusive_terms_expanded = frozenset(['holy_ghost.n.01'])


@static_predicate
class AllSaints(EasterBased):

    days_after_easter = 56
    terms_expanded = frozenset(["all_saints'_day.n.01"])
    non_exclusive_terms_expanded = frozenset([
        u'venerator.n.01', u'good_person.n.01', u'godly.s.01', u'saint.n.01',
        u'saint.n.02', u'enshrine.v.02', u'ideal.n.02', u'reverence.v.01',
        u'model.n.06', u'deify.v.01', u'canonize.v.01', u'reverent.a.01',
        u'reverence.n.02', u'divine.s.03'])


@static_predicate
class VeteransDay(Date):

    month = 11
    day = 11
    terms_expanded = frozenset(['veterans_day.n.01'])
    non_exclusive_terms_expanded = frozenset([
        u'armistice.n.01', u'veteran.n.02', u'serviceman.n.01', u'peace.n.02',
        u'peace.n.03', u'peace.n.01', u'peace.n.04', u'peace.n.05',
        u'veteran.n.01'])


@static_predicate
class Assumption(Date):

    month = 8
    day = 15
    terms_expanded = frozenset([u'assumption.n.04', u'assumption.n.05'])
    non_exclusive_terms_expanded = frozenset([
        u'miracle.n.02', u'heaven.n.02', u'holy_day_of_obligation.n.01',
        u'mary.n.01'])


@static_predicate
class IndependenceDay(Date):

    month = 7
    day = 4
    terms_expanded = frozenset(['independence_day.n.01'])
    non_exclusive_terms_expanded = frozenset([
        u'freedom.n.01', u'independent.s.04', u'independence.n.01',
        u'independence.n.03', u'independence.n.02', u'autonomous.s.01',
        u'independent.a.01', u'independent.a.03', u'autonomy.n.01',
        u'american.a.01'])


@static_predicate
class GroundhogDay(Date):

    month = 2
    day = 2
    terms_expanded = frozenset(['groundhog_day.n.01'])
    non_exclusive_terms_expanded = frozenset([
        u'marmot.n.01', u'groundhog.n.01'])


@static_predicate
class ValentinesDay(Date):

    month = 2
    day = 14
    terms_expanded = frozenset([u'valentine.n.02', u'valentine.n.01'])
    non_exclusive_terms_expanded = frozenset([
        u'sweetheart.n.01', u'greeting_card.n.01', 'love.v.03', u'love.v.02',
        u'love.v.01', u'heart.n.06', u'heart.n.07', u'heart.n.01',
        u'heart.n.02', u'mate.n.03', u'love.n.02', u'love.n.01', u'love.n.04',
        u'couple.n.02', u'lover.n.01', u'affection.n.01', u'beloved.n.01'])


@static_predicate
class AprilFools(Date):

    month = 4
    day = 1
    terms_expanded = frozenset(["april_fools'.n.01"])
    non_exclusive_terms_expanded = frozenset([
        u'butt.n.03', u'stooge.v.02', u'deceptive.s.01', u'humorous.a.01',
        u'deceive.v.02', u'crafty.s.01', u'deception.n.02', u'trickery.n.02',
        u'gull.v.02', u'fool.v.01', u'hoax.v.01', u'jest.n.02', u'joke.n.01',
        u'clown.v.01', u'chump.n.01', u'delusive.s.01', u'fool.n.01',
        u'misrepresentation.n.01', u'jester.n.01', u'joke.v.02',
        u'flim-flam.v.01', u'clown.n.02'])


@static_predicate
class CincoDeMayo(Date):

    month = 5
    day = 5
    terms_expanded = frozenset(['cinco_de_mayo.n.01'])
    non_exclusive_terms_expanded = frozenset([u'mexican.a.01', u'mexico.n.01'])


@static_predicate
class Solstice(ExclusiveTerms):

    terms_expanded = frozenset(['solstice.n.01'])

    def applies_in_context(self, context):
        context_date = context.date
        return context_date.day == 21 and (
            context_date.month == 6 or context_date.month == 12)


@static_predicate
class Friday13(ExclusiveTerms):

    terms_expanded = frozenset(['friday the 13th'])
    non_exclusive_terms_expanded = frozenset([
        'misfortune.n.02', 'bad_luck.n.02', 'misfortune.n.01', 'thirteen.n.01',
        u'superstition.n.01', u'unlucky.a.01', u'doomed.s.03',
        u'thirteen.s.01'])

    def applies_in_context(self, context):
        context_date = context.date
        return context_date.day == 13 and context_date.isoweekday() == 5


class Birthday(Date):

    def __init__(self, birth_date, name, age):
        self.non_exclusive_terms = (
            'birthday', name, str(birth_date.year), str(age))
        self.year = birth_date.year
        self.month = birth_date.month
        self.day = birth_date.day
        super(Birthday, self).__init__()

    def applies_to_song(self, song, exclusive):
        if exclusive:
            return False

        if self.year == song.get_year():
            return True

        return super(Birthday, self).applies_to_song(song, exclusive)
