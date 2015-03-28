"""Context awareness filters."""

import re
from collections import defaultdict
from datetime import datetime, timedelta, date, time
from dateutil.easter import easter
from dateutil.rrule import TH, YEARLY, rrule
import nltk
from nltk import word_tokenize, pos_tag
from nltk.corpus import stopwords, wordnet

nltk.download('punkt')
nltk.download('wordnet')
nltk.download('stopwords')
nltk.download('maxent_treebank_pos_tagger')

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

POS_MAP = {
    'J': wordnet.ADJ,
    'V': wordnet.VERB,
    'N': wordnet.NOUN,
    'R': wordnet.ADV}


def escape(the_string):
    """Double escape quotes."""
    # TODO: move to utils
    return the_string.replace('"', '\\"').replace("'", "\\'")


def get_hypernyms(synset):
    return synset.hypernyms()


def get_wordnet_pos(tag):
    return POS_MAP.get(tag[:1])


def expand_synset(synset):
    yield (synset.name(), 1.0)
    for synset in synset.hypernyms():
        yield (synset.name(), 0.5)
        for lemma in synset.lemmas():
            for form in lemma.derivationally_related_forms():
                yield (form.synset().name(), 0.5)
            for pertainym in lemma.pertainyms():
                yield (pertainym.synset().name(), 0.5)


def expand(word, pos=None):
    stemmed = wordnet.morphy(word, pos=pos)
    if stemmed is None:
        yield (word, 1)
        return

    for synset in wordnet.synsets(stemmed, pos=pos):
        for term_weight in expand_synset(synset):
            yield term_weight


def get_intersection_keys(terms1, terms2):
    return set(terms1.keys()) & set(terms2.keys())


def add_weighted_terms(old_terms, new_terms):
    if old_terms is None:
        return new_terms
    if new_terms is None:
        return None
    for key in new_terms:
        if key in old_terms:
            new_terms[key] += old_terms[key]
    return new_terms


def get_weighted_terms(song):
    weights = defaultdict(float)
    word_tags = pos_tag(word_tokenize(song.get_title(with_version=False)))
    for word, tag in word_tags:
        for term, weight in expand(word, get_wordnet_pos(tag)):
            weights[term] += weight
    for tag in song.get_non_geo_tags():
        weights[tag] += 1
    return weights


class Context(object):

    """Object representing the current context."""

    def __init__(self, context_date, location, geohash, birthdays, last_song,
                 nearby_artists, southern_hemisphere, weather, extra_context,
                 old_context):
        self.date = context_date
        self.location = location
        self.geohash = geohash
        self.birthdays = birthdays
        self.last_song = last_song
        self.nearby_artists = nearby_artists
        self.southern_hemisphere = southern_hemisphere
        self.weather = weather
        self.predicates = []
        self.extra_context = extra_context
        self.weighted_terms_predicate = None
        self.build_predicates(old_context)

    @staticmethod
    def string_to_datetime(time_string):
        time_string, ampm = time_string.split()
        hour, minute = time_string.split(':')
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
            before_score = result['score']
            if predicate.applies_to_song(song, exclusive=False) and in_context:
                predicate.positive_score(result)
                print "%s - %s " % (
                    song.get_artist(), song.get_title(with_version=False)),
                print "%r adjusted positively %.2f%%" % (
                    predicate,
                    100 * ((before_score - result['score']) / before_score))
            elif predicate.applies_to_song(song, exclusive=True) \
                    and not in_context:
                predicate.negative_score(result)
                print "%s - %s " % (
                    song.get_artist(), song.get_title(with_version=False)),
                print "%r adjusted negatively %.2f" % (
                    predicate,
                    100 * ((result['score'] - before_score) / before_score))

    def build_predicates(self, old_context):
        """Construct predicates to check against the context."""
        self.add_standard_predicates()
        self.add_december_predicate()
        self.add_location_predicates()
        self.add_weather_predicates()
        self.add_birthday_predicates()
        self.add_extra_predicates()
        self.add_last_song_predicates(
            old_context.weighted_terms_predicate if old_context else None)
        self.add_nearby_artist_predicates()

    def add_nearby_artist_predicates(self):
        for artist in set(self.nearby_artists):
            self.predicates.append(ArtistPredicate(artist))

    def add_last_song_predicates(self, old_predicate):
        if old_predicate:
            old_terms = old_predicate.weighted_terms
        else:
            old_terms = None
        if self.last_song:
            new_terms = get_weighted_terms(self.last_song)
            weighted = add_weighted_terms(old_terms, new_terms)
        else:
            weighted = old_terms
        print("*** context weighted terms: ***")
        print(
            sorted([
                (value, key.split('.')[0]) for key, value in weighted.items()],
                reverse=True))
        print("*******************************")
        if weighted:
            predicate = WeightedTermsPredicate(weighted)
            self.predicates.append(predicate)
            self.weighted_terms_predicate = predicate
            self.predicates.append(
                GeohashPredicate(self.last_song.get_geohashes()))

    def add_extra_predicates(self):
        if self.extra_context:
            words = [l.strip().lower() for l in self.extra_context.split(',')]
            if words:
                self.predicates.extend([
                    StringPredicate(word) for word in words])

    def add_birthday_predicates(self):
        for name_date in self.birthdays.split(','):
            if ':' not in name_date:
                continue
            name, bdate = name_date.strip().split(':')
            bdate = bdate.strip()
            if '-' in bdate:
                bdate = [int(i) for i in bdate.split('-')]
            else:
                bdate = [int(i) for i in bdate.split('/')]
            if len(bdate) == 3:
                year, month, day = bdate
                age = self.date.year - year
                self.predicates.append(
                    BirthdayPredicate(
                        year=year, month=month, day=day, name=name, age=age))

    def get_astronomical_times(self, weather):
        sunrise = weather.get('astronomy', {}).get('sunrise', '')
        sunset = weather.get('astronomy', {}).get('sunset', '')
        predicates = []
        if sunrise and sunset:
            sunrise = self.string_to_datetime(sunrise)
            if sunrise:
                predicates.append(Dawn.from_datetime(sunrise))
            sunset = self.string_to_datetime(sunset)
            if sunset:
                predicates.append(Dusk.from_datetime(sunset))
            predicates.append(
                Daylight.from_dates(start=sunrise, end=sunset))
            predicates.append(
                NotDaylight.from_dates(start=sunrise, end=sunset))
            predicates.append(Sun.from_dates(start=sunrise, end=sunset))
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
        for condition in weather.get(
                'condition', {}).get('text', '').lower().strip().split('/'):
            condition = condition.strip()
            with open('weather_conditions.txt', 'a') as weather_file:
                weather_file.write('%s\n' % condition)
            if condition:
                results = []
                unmodified = condition.split()[-1]
                if unmodified in ('rain', 'rainy', 'drizzle', 'cloudy', 'fog',
                                  'foggy', 'mist', 'misty'):
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
                        [StringPredicate(c) for c in results])
        return predicates

    def add_location_predicates(self):
        if self.location:
            locations = [l.lower() for l in self.location.split(',')]
            if locations:
                self.predicates.extend([
                    StringPredicate(location) for location in locations])
        if self.geohash:
            self.predicates.append(GeohashPredicate([self.geohash]))

    def add_december_predicate(self):
        if self.date.month == 12:
            # December is for retrospection
            self.predicates.append(SongYearPredicate(self.date.year))

    def add_standard_predicates(self):
        self.predicates.extend(STATIC_PREDICATES)
        for predicate in (
                YearPredicate, Today, Now, Midnight, Noon,
                Spring, Summer, Autumn, Winter, Evening, Morning, Afternoon,
                Night, Day, Christmas, NewYear, Halloween, Easter,
                Thanksgiving):
            self.predicates.append(predicate.from_datetime(self.date))


class Predicate(object):

    terms = tuple()
    non_exclusive_terms = tuple()
    tag_only_terms = tuple()
    title_searches = None
    title_searches_non_exclusive = None
    tag_searches = None
    tag_searches_non_exclusive = None

    def __init__(self):
        self.build_searches()

    def build_searches(self):
        """Construct all the searches for this predicate."""
        self.title_searches = [
            self.build_title_search(term) for term in self.terms]
        self.title_searches_non_exclusive = [
            self.build_title_search(term) for term in self.non_exclusive_terms]
        self.tag_searches = [
            self.build_tag_search(term)
            for term in self.terms + self.tag_only_terms]
        self.tag_searches_non_exclusive = [
            self.build_tag_search(term) for term in self.non_exclusive_terms]

    @staticmethod
    def _build_search(term):
        return '%s(e?s)?' % (term,)

    def build_title_search(self, term):
        return re.compile(r'\b%s\b' % (self._build_search(term),))

    def build_tag_search(self, term):
        return re.compile(r'^%s$' % (self._build_search(term),))

    def get_title_searches(self, exclusive):
        """Get title searches for this predicate."""
        return self.title_searches if exclusive else (
            self.title_searches + self.title_searches_non_exclusive)

    def get_tag_searches(self, exclusive):
        """Get tag searches for this predicate."""
        return self.tag_searches if exclusive else (
            self.tag_searches + self.tag_searches_non_exclusive)

    def applies_to_song(self, song, exclusive):
        """Determine whether the predicate applies to the song."""
        title = song.get_title(with_version=False).lower()
        for search in self.get_tag_searches(exclusive=exclusive):
            for tag in song.get_non_geo_tags():
                if search.match(tag):
                    return True

        for search in self.get_title_searches(exclusive=exclusive):
            if search.search(title):
                return True

        return False

    def applies_in_context(self, context):
        return True

    def positive_score(self, result):
        result['score'] /= 2.0

    def negative_score(self, result):
        pass


class ExclusivePredicate(Predicate):

    def negative_score(self, result):
        result['score'] *= 2.0


class Period(ExclusivePredicate):

    period = ONE_YEAR
    decay = None

    def __init__(self, peak):
        super(Period, self).__init__()
        self.diff = None
        self.peak = peak

    def get_diff(self, context_datetime):
        if not isinstance(self.peak, datetime):
            context_datetime = context_datetime.date()
        self.diff = abs(context_datetime - self.peak)
        if self.diff.total_seconds() > self.period.total_seconds() / 2:
            self.diff = self.period - self.diff
        return self.diff

    def applies_in_context(self, context):
        return self.get_diff(context.date) < self.decay

    def positive_score(self, result):
        result['score'] /= 1.0 + (
            1.0 - (self.diff.total_seconds() / self.decay.total_seconds()))

    def negative_score(self, result):
        result['score'] *= min(
            2.0, (self.diff.total_seconds() / self.decay.total_seconds()))


class DayPeriod(Period):

    period = ONE_DAY


class ArtistPredicate(Predicate):

    def __init__(self, artist):
        self.artist = artist

    def applies_to_song(self, song, exclusive):
        if self.artist.lower().strip() == song.get_artist().strip():
            return True
        return False


class GeohashPredicate(Predicate):

    def __init__(self, geohashes):
        self.geohashes = geohashes
        super(GeohashPredicate, self).__init__()

    def applies_to_song(self, song, exclusive):
        for self_hash in self.geohashes:
            for other_hash in song.get_geohashes():
                if other_hash.startswith(self_hash[:2]):
                    return True

        return False

    def __repr__(self):
        return '<GeohashPredicate %r>' % self.geohashes

    def positive_score(self, result):
        longest_common = 0
        for self_hash in self.geohashes:
            for other_hash in result['song'].get_geohashes():
                if self_hash[0] != other_hash[0]:
                    continue

                for i, character in enumerate(self_hash):
                    if i >= len(other_hash):
                        break

                    if character != other_hash[i]:
                        break

                    if i > longest_common:
                        longest_common = i
        result['score'] *= 1.0 / (1.1 ** longest_common)


class YearPredicate(Predicate):

    def __init__(self, year):
        self.year = year
        self.tag_only_terms = (str(year),)
        super(YearPredicate, self).__init__()

    @classmethod
    def from_datetime(cls, datetime):
        new = cls(datetime.year)
        new.build_searches()
        return new


class SongYearPredicate(YearPredicate):

    def applies_to_song(self, song, exclusive):
        return self.year == song.get_year()


class StringPredicate(Predicate):

    def __init__(self, term):
        self.terms = (term,)
        super(StringPredicate, self).__init__()

    def __repr__(self):
        return '<StringPredicate %r>' % self.terms


class WeightedTermsPredicate(Predicate):

    def __init__(self, weighted_terms):
        self.weighted_terms = weighted_terms
        super(WeightedTermsPredicate, self).__init__()

    def decay(self):
        to_delete = []
        for key, value in self.weighted_terms.items():
            new_value = value - self._decay
            self.weighted_terms[key] = new_value
            if new_value <= 0:
                to_delete.append(key)
        for key in to_delete:
            del self.weighted_terms[key]

    def get_intersection_keys(self, song_terms):
        return get_intersection_keys(self.weighted_terms, song_terms)

    def applies_to_song(self, song, exclusive):
        return self.get_intersection_keys(get_weighted_terms(song))

    def positive_score(self, result):
        song_terms = get_weighted_terms(result['song'])
        intersection_score = sum([
            self.weighted_terms[k] + song_terms[k] for k in
            self.get_intersection_keys(song_terms)])
        score = intersection_score / max(
            1, sum(self.weighted_terms.values()) + sum(song_terms.values()))
        result['score'] /= 1 + score


class WeatherPredicate(ExclusivePredicate):

    @staticmethod
    def get_weather_conditions(context):
        return context.weather.get(
            'condition', {}).get('text', '').lower().strip().split('/')

    @staticmethod
    def get_temperature(context):
        temperature = context.weather.get('condition', {}).get('temp', '')
        if not temperature:
            return None

        return int(temperature)

    @staticmethod
    def get_wind_speed(context):
        return float(
            context.weather.get('wind', {}).get('speed', '').strip() or '0')

    @staticmethod
    def get_humidity(context):
        return float(
            context.weather.get('atmosphere', {}).get(
                'humidity', '').strip() or '0')


class Freezing(WeatherPredicate):

    terms = ('freezing', 'frozen', 'ice', 'frost')
    non_exclusive_terms = ('snow',)

    def applies_in_context(self, context):
        temperature = self.get_temperature(context)
        if temperature is None:
            return False

        if temperature > 0:
            return False

        return True


class Cold(WeatherPredicate):

    terms = ('cold', 'chill', 'chilly')

    def applies_in_context(self, context):
        temperature = self.get_temperature(context)
        if temperature is None:
            return False

        if temperature > 10:
            return False

        return True


class Hot(WeatherPredicate):

    terms = ('hot', 'heat')

    def applies_in_context(self, context):
        temperature = self.get_temperature(context)
        if temperature is None:
            return False

        if temperature < 25:
            return False

        return True


class Calm(WeatherPredicate):

    terms = ('calm',)

    def applies_in_context(self, context):
        return self.get_wind_speed(context) < 1


class Breeze(WeatherPredicate):

    terms = ('breeze', 'breezy')

    def applies_in_context(self, context):
        speed = self.get_wind_speed(context)
        return speed <= 30 and speed > 0


class Wind(WeatherPredicate):

    terms = ('wind', 'windy')

    def applies_in_context(self, context):
        return self.get_wind_speed(context) > 30


class Gale(WeatherPredicate):

    terms = ('gale',)

    def applies_in_context(self, context):
        return self.get_wind_speed(context) > 38


class Storm(WeatherPredicate):

    terms = ('storm', 'stormy')

    def applies_in_context(self, context):
        return self.get_wind_speed(context) > 54


class Hurricane(WeatherPredicate):

    terms = ('hurricane',)

    def applies_in_context(self, context):
        return self.get_wind_speed(context) > 72


class Humid(WeatherPredicate):

    terms = ('humid', 'humidity')

    def applies_in_context(self, context):
        return self.get_humidity(context) > 65


class Now(DayPeriod):

    time_tag = re.compile('^([0-9]{2}):([0-9]{2})$')
    decay = HALF_HOUR

    def applies_in_context(self, context):
        return True

    def applies_to_song(self, song, exclusive):
        song_tags = song.get_non_geo_tags()
        for tag in song_tags:
            match = self.time_tag.match(tag)
            if match:
                hour, minute = match.groups()
                song_date = datetime.now().replace(
                    hour=int(hour), minute=int(minute))
                if self.get_diff(song_date) < self.decay:
                    return True

        return False

    @classmethod
    def from_datetime(cls, datetime):
        new = cls(peak=datetime)
        new.build_searches()
        return new

    def __repr__(self):
        return '<Now %s>' % (self.peak,)


class TimePredicate(DayPeriod):

    time_tag = re.compile('^([0-9]{2}):([0-9]{2})$')
    decay = HALF_HOUR

    @classmethod
    def from_datetime(cls, datetime):
        new = cls(peak=datetime)
        new.build_searches()
        return new

    def __repr__(self):
        return '<TimePredicate %s>' % (self.peak,)


class TimeRangePredicate(ExclusivePredicate):

    start = None
    end = None

    def applies_in_context(self, context):
        if self.start and context.date < self.start:
            return False

        if self.end and context.date > self.end:
            return False

        return True

    @classmethod
    def from_dates(cls, start=None, end=None):
        new = cls()
        new.start = start
        new.end = end
        new.build_searches()
        return new


class Daylight(TimeRangePredicate):

    terms = ('daylight',)


class NegativeTimeRangePredicate(TimeRangePredicate):

    def applies_in_context(self, context):
        return not super(
            NegativeTimeRangePredicate, self).applies_in_context(context)


class NotDaylight(NegativeTimeRangePredicate):

    terms = ('dark', 'darkness')


class Sun(TimeRangePredicate, WeatherPredicate):

    terms = ('sun', 'sunny', 'sunlight', 'sunshine', 'blue sky', 'blue skies')

    def applies_in_context(self, context):
        if super(Sun, self).applies_in_context(context):
            conditions = self.get_weather_conditions(context)
            for condition in conditions:
                if 'partly cloudy' in condition or 'fair' in condition:
                    return True

        return False


class Fog(WeatherPredicate):

    terms = ('mist', 'misty', 'fog', 'foggy')

    def applies_in_context(self, context):
        conditions = self.get_weather_conditions(context)
        for condition in conditions:
            if 'mist' in condition or 'fog' in condition\
                    or 'foggy' in condition or 'misty' in condition:
                return True

        return False


class Cloudy(WeatherPredicate):

    terms = ('cloud', 'cloudy', 'overcast', 'gloom', 'gloomy')

    def applies_in_context(self, context):
        conditions = self.get_weather_conditions(context)
        for condition in conditions:
            if 'cloudy' in condition or 'overcast' in condition:
                return True

        return False


class Snow(WeatherPredicate):

    non_exclusive_terms = ('snow',) + Cloudy.terms

    def applies_in_context(self, context):
        conditions = self.get_weather_conditions(context)
        for condition in conditions:
            if 'snow' in condition:
                return True

        return False


class Sleet(WeatherPredicate):

    terms = ('sleet',)
    non_exclusive_terms = Cloudy.terms

    def applies_in_context(self, context):
        conditions = self.get_weather_conditions(context)
        for condition in conditions:
            if 'sleet' in condition:
                return True

        return False


class Rain(WeatherPredicate):

    terms = ('rain', 'rainy', 'shower', 'drizzle', 'raining', 'raindrop')
    non_exclusive_terms = Cloudy.terms

    def applies_in_context(self, context):
        conditions = self.get_weather_conditions(context)
        for condition in conditions:
            if 'rain' in condition or 'shower' in condition or\
                    'drizzle' in condition:
                return True

        return False


class Dawn(TimePredicate):

    decay = ONE_HOUR
    terms = (
        'sunrise', 'dawn', 'aurora', 'break of day', 'dawning', 'daybreak',
        'sunup')


class Dusk(TimePredicate):

    decay = ONE_HOUR
    terms = (
        'sunset', 'dusk', 'gloaming', 'nightfall', 'sundown', 'twilight',
        'eventide', 'close of day')


class Noon(TimePredicate):

    terms = ('noon',)

    @classmethod
    def from_datetime(cls, date):
        new = cls(peak=date.replace(hour=12, minute=0, second=0))
        new.build_searches()
        return new


class Midnight(TimePredicate):

    terms = ('midnight',)

    @classmethod
    def from_datetime(cls, date):
        new = cls(peak=date.replace(hour=0, minute=0, second=0))
        new.build_searches()
        return new


class DatePredicateBase(ExclusivePredicate):

    day = None
    month = None

    @classmethod
    def from_datetime(cls, date):
        """Construct a DatePredicate from a datetime object."""
        new = cls()
        new.month = date.month
        new.day = date.day
        new.build_searches()
        return new

    def applies_in_context(self, context):
        context_date = context.date
        return (
            context_date.day == self.day and context_date.month == self.month)

    def build_searches(self):
        super(DatePredicateBase, self).build_searches()
        if self.month and self.day:
            self.tag_searches_non_exclusive.append(
                self.build_tag_search(
                    "([0-9]{4}-)?%02d-%02d" % (self.month, self.day)))


class Today(DatePredicateBase):

    def applies_in_context(self, context):
        return True

    def applies_to_song(self, song, exclusive):
        """Determine whether the predicate applies to the song."""
        title = song.get_title(with_version=False).lower()
        for search in self.get_tag_searches(exclusive=exclusive):
            for tag in song.get_non_geo_tags():
                if search.match(tag):
                    return True

        for search in self.get_title_searches(exclusive=exclusive):
            if search.search(title):
                return True

        return False


class Season(Period):

    decay = TWO_MONTHS

    def applies_in_context(self, context):
        # TODO: this probably doesn't work
        if context.southern_hemisphere:
            original_date = context.date
            context.date += SIX_MONTHS
        result = super(Season, self).applies_in_context(context)
        if context.southern_hemisphere:
            context.date = original_date
        return result


class Winter(Season):

    terms = ('winter', 'wintertime')

    @classmethod
    def from_datetime(cls, now):
        new = cls(peak=datetime(now.year - 1, 12, 21) + FORTY_FIVE_DAYS)
        new.build_searches()
        return new


class Spring(Season):

    terms = ('spring', 'springtime')

    @classmethod
    def from_datetime(cls, now):
        new = cls(peak=datetime(now.year, 3, 21) + FORTY_FIVE_DAYS)
        new.build_searches()
        return new


class Summer(Season):

    terms = ('summer', 'summertime')

    @classmethod
    def from_datetime(cls, now):
        new = cls(peak=datetime(now.year, 6, 21) + FORTY_FIVE_DAYS)
        new.build_searches()
        return new


class Autumn(Season):

    terms = ('autumn',)
    tag_only_terms = ('fall',)

    @classmethod
    def from_datetime(cls, now):
        new = cls(peak=datetime(now.year, 9, 21) + FORTY_FIVE_DAYS)
        new.build_searches()
        return new


class MonthPredicate(ExclusivePredicate):

    month = 0

    def applies_in_context(self, context):
        return context.date.month == self.month


class January(MonthPredicate):

    month = 1
    terms = ('january',)


class February(MonthPredicate):

    month = 2
    terms = ('february',)


class March(MonthPredicate):

    month = 3
    tag_only_terms = ('march',)


class April(MonthPredicate):

    month = 4
    terms = ('april',)


class May(MonthPredicate):

    month = 5
    tag_only_terms = ('may',)


class June(MonthPredicate):

    month = 6
    terms = ('june',)


class July(MonthPredicate):

    month = 7
    terms = ('july',)


class August(MonthPredicate):

    month = 8
    terms = ('august',)


class September(MonthPredicate):

    month = 9
    terms = ('september',)


class October(MonthPredicate):

    month = 10
    terms = ('october',)


class November(MonthPredicate):

    month = 11
    terms = ('november',)


class December(MonthPredicate):

    month = 12
    terms = ('december',)


class DayPredicate(ExclusivePredicate):

    day_index = 0

    def applies_in_context(self, context):
        return (
            context.date.isoweekday() == self.day_index and
            context.date.hour >= 4) or (
                context.date.isoweekday() == self.day_index + 1 and
                context.date.hour < 4)


class Monday(DayPredicate):

    day_index = 1
    terms = ('monday',)


class Tuesday(DayPredicate):

    day_index = 2
    terms = ('tuesday',)


class Wednesday(DayPredicate):

    day_index = 3
    terms = ('wednesday',)


class Thursday(DayPredicate):

    day_index = 4
    terms = ('thursday',)


class Friday(DayPredicate):

    day_index = 5
    terms = ('friday',)


class Saturday(DayPredicate):

    day_index = 6
    terms = ('saturday',)


class Sunday(DayPredicate):

    day_index = 7
    terms = ('sunday',)


class Night(DayPeriod):

    terms = ('night',)
    decay = SIX_HOURS

    @classmethod
    def from_datetime(cls, datetime):
        new = cls(
            peak=datetime.replace(hour=0, minute=0, second=0, microsecond=0))
        new.build_searches()
        return new


class Day(DayPeriod):

    terms = ('daytime',)
    decay = SIX_HOURS

    @classmethod
    def from_datetime(cls, datetime):
        new = cls(
            peak=datetime.replace(hour=12, minute=0, second=0, microsecond=0))
        new.build_searches()
        return new


class Evening(DayPeriod):

    terms = ('evening',)
    decay = THREE_HOURS

    @classmethod
    def from_datetime(cls, datetime):
        new = cls(peak=datetime.replace(hour=20))
        new.build_searches()
        return new


class Morning(DayPeriod):

    terms = ('morning',)
    decay = THREE_HOURS

    @classmethod
    def from_datetime(cls, datetime):
        new = cls(peak=datetime.replace(hour=9))
        new.build_searches()
        return new


class Afternoon(DayPeriod):

    terms = ('afternoon',)
    decay = THREE_HOURS

    @classmethod
    def from_datetime(cls, datetime):
        new = cls(peak=datetime.replace(hour=15))
        new.build_searches()
        return new


class Weekend(ExclusivePredicate):

    terms = ('weekend',)

    def applies_in_context(self, context):
        context_date = context.date
        weekday = context_date.isoweekday()
        return weekday == 6 or weekday == 7 or (
            weekday == 5 and context_date.hour >= 17)


class Thanksgiving(Period):

    terms = ('thanksgiving',)
    non_exclusive_terms = (
        'thanks', 'thank', 'grateful', 'gratitude', 'turkey', 'stuffing',
        'gluttony', 'eating', 'food')
    decay = THREE_DAYS

    @classmethod
    def from_datetime(cls, context_datetime):
        thxgiving = rrule(YEARLY, byweekday=TH(4), bymonth=11).after(
            datetime(context_datetime.year, 1, 1))
        new = cls(peak=thxgiving)
        new.build_searches()
        return new


class Christmas(Period):

    terms = ('christmas', 'santa claus', 'xmas')
    non_exclusive_terms = (
        'reindeer', 'sled', 'santa', 'snow', 'bell', 'jesus', 'eggnoc',
        'mistletoe', 'carol', 'nativity', 'mary', 'joseph', 'manger')
    decay = THREE_DAYS

    @classmethod
    def from_datetime(cls, datetime):
        new = cls(peak=datetime.replace(day=25, month=12))
        new.build_searches()
        return new


class Kwanzaa(ExclusivePredicate):

    terms = ('kwanzaa',)

    def applies_in_context(self, context):
        date = context.date
        return (date.month == 12 and date.day >= 26) or (
            date.month == 1 and date.day == 1)


class NewYear(Period):

    terms = ('new year',)
    decay = THREE_DAYS

    @classmethod
    def from_datetime(cls, datetime):
        new = cls(peak=datetime.replace(day=31, month=12))
        new.build_searches()
        return new


class Halloween(Period):

    terms = ('halloween', 'hallowe\'en', 'all hallow\'s')
    non_exclusive_terms = (
        'haunt', 'haunting', 'haunted', 'ghost', 'monster', 'horror', 'devil',
        'witch', 'pumkin', 'bone', 'skeleton', 'ghosts', 'zombie', 'werewolf',
        'werewolves', 'vampire', 'evil', 'scare', 'scary', 'scaring', 'fear',
        'fright', 'frightening', 'blood', 'bat', 'dracula', 'spider',
        'costume', 'satan', 'hell', 'undead', 'dead', 'death', 'grave',
        'skull', 'terror', 'coffin', 'tomb', 'creepy', 'wicked', 'lantern',
        'pumpkin', 'trick', 'treat')
    decay = THREE_DAYS

    @classmethod
    def from_datetime(cls, datetime):
        new = cls(peak=datetime.replace(day=31, month=10))
        new.build_searches()
        return new


class EasterBased(ExclusivePredicate):

    days_after_easter = 0

    def applies_in_context(self, context):
        context_date = context.date
        if self.easter_offset(context_date, easter(context_date.year)):
            return True

        return False

    def easter_offset(self, from_date, easter):
        return (from_date.date() - easter).days == self.days_after_easter


class Easter(Period):

    terms = ('easter',)
    non_exclusive_terms = (
        'resurrect', 'resurrection', 'jesus', 'egg', 'bunny', 'bunnies',
        'rabbit')
    decay = THREE_DAYS

    @classmethod
    def from_datetime(cls, datetime):
        new = cls(peak=easter(datetime.year))
        new.build_searches()
        return new


class MardiGras(EasterBased):

    terms = ('mardi gras', 'shrove tuesday', 'fat tuesday')
    non_exclusive_terms = ('pancake',)
    days_after_easter = -47


class AshWednesday(EasterBased):

    terms = ('ash wednesday',)
    non_exclusive_terms = ('ash', 'lent')
    days_after_easter = -46


class PalmSunday(EasterBased):

    terms = ('palm sunday',)
    non_exclusive_terms = ('palms', 'jerusalem', 'jesus', 'christ')
    days_after_easter = -7


class MaundyThursday(EasterBased):

    terms = ('maundy thursday',)
    non_exclusive_terms = ('last supper', 'apostles', 'jesus', 'christ')
    days_after_easter = -3


class GoodFriday(EasterBased):

    terms = ('good friday',)
    non_exclusive_terms = (
        'crucifixion', 'cross', 'crosses', 'jesus', 'christ')
    days_after_easter = -2


class Ascension(EasterBased):

    terms = ('ascension',)
    non_exclusive_terms = ('heaven', 'jesus', 'christ')
    days_after_easter = 39


class Pentecost(EasterBased):

    terms = ('pentecost',)
    non_exclusive_terms = ('holy spirit',)
    days_after_easter = 49


class WhitMonday(EasterBased):

    terms = ('whit monday',)
    non_exclusive_terms = ('holy spirit',)
    days_after_easter = 50


class AllSaints(EasterBased):

    terms = ('all saints',)
    non_exclusive_terms = ('saint',)
    days_after_easter = 56


class VeteransDay(DatePredicateBase):

    terms = ('armistice day', 'veterans day')
    non_exclusive_terms = ('peace', 'armistice', 'veteran')
    month = 11
    day = 11


class Assumption(DatePredicateBase):

    terms = ('assumption',)
    non_exclusive_terms = ('mary', 'heaven')
    month = 8
    day = 15


class IndependenceDay(DatePredicateBase):

    terms = ('independence day',)
    non_exclusive_terms = (
        'independence', 'united states', 'independant', 'usa', 'u.s.a.')
    month = 7
    day = 4


class GroundhogDay(DatePredicateBase):

    terms = ('groundhog day',)
    non_exclusive_terms = ('groundhog',)
    month = 2
    day = 2


class ValentinesDay(DatePredicateBase):

    terms = ('valentine',)
    non_exclusive_terms = ('heart', 'love')
    month = 2
    day = 14


class AprilFools(DatePredicateBase):

    terms = ('april fool',)
    non_exclusive_terms = ('prank', 'joke', 'fool', 'hoax')
    month = 4
    day = 1


class CincoDeMayo(DatePredicateBase):

    terms = ('cinco de mayo',)
    non_exclusive_terms = ('mexico',)
    month = 5
    day = 5


class Solstice(ExclusivePredicate):

    terms = ('solstice',)

    def applies_in_context(self, context):
        context_date = context.date
        return context_date.day == 21 and (
            context_date.month == 6 or context_date.month == 12)


class Friday13(ExclusivePredicate):

    terms = ('friday the 13th',)
    non_exclusive_terms = ('bad luck', 'superstition')

    def applies_in_context(self, context):
        context_date = context.date
        return context_date.day == 13 and context_date.isoweekday() == 5


class BirthdayPredicate(DatePredicateBase):

    def __init__(self, year, month, day, name, age):
        self.non_exclusive_terms = ('birthday', name, str(year), str(age))
        self.year = year
        self.month = month
        self.day = day
        self.non_exclusive_terms = (str(year),)
        super(BirthdayPredicate, self).__init__()

    def applies_to_song(self, song, exclusive):
        if not exclusive and self.year == song.get_year():
            return True
        return super(BirthdayPredicate, self).applies_to_song(song, exclusive)


STATIC_PREDICATES = [
    Kwanzaa(), MardiGras(), AshWednesday(), PalmSunday(), MaundyThursday(),
    GoodFriday(), Ascension(), Pentecost(), WhitMonday(), AllSaints(),
    VeteransDay(), Assumption(), IndependenceDay(), GroundhogDay(),
    ValentinesDay(), AprilFools(), CincoDeMayo(), Solstice(), Friday13(),
    January(), February(), March(), April(), May(), June(), July(), August(),
    September(), October(), November(), December(), Monday(), Tuesday(),
    Wednesday(), Thursday(), Friday(), Saturday(), Sunday(), Weekend()]
