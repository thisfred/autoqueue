"""Context awareness filters."""

import re
from datetime import datetime, timedelta, date, time

EASTERS = {
    2014: datetime(2014, 4, 20),
    2015: datetime(2015, 4, 5),
    2016: datetime(2016, 3, 27),
    2017: datetime(2017, 4, 16),
    2018: datetime(2018, 4, 1),
    2019: datetime(2019, 4, 21),
    2020: datetime(2020, 4, 12),
    2021: datetime(2021, 4, 4),
    2022: datetime(2022, 4, 17)}

MAR21 = lambda year: datetime(year, 3, 21)
JUN21 = lambda year: datetime(year, 6, 21)
SEP21 = lambda year: datetime(year, 9, 21)
DEC21 = lambda year: datetime(year, 12, 21)

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


def escape(the_string):
    """Double escape quotes."""
    # TODO: move to utils
    return the_string.replace('"', '\\"').replace("'", "\\'")

ALPHANUMSPACE = re.compile(r'([^\s\w]|_)+')


class Context(object):

    """Object representing the current context."""

    def __init__(self, context_date, location, geohash, birthdays, last_song,
                 nearby_artists, southern_hemisphere, weather, extra_context):
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
        self.build_predicates()

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
                print "%s - %s" % (
                    song.get_artist(), song.get_title(with_version=False))
                print "%r adjusted positively %d -> %d" % (
                    predicate, before_score, result['score'])
            elif predicate.applies_to_song(song, exclusive=True) \
                    and not in_context:
                predicate.negative_score(result)
                print "%s - %s" % (
                    song.get_artist(), song.get_title(with_version=False))
                print "%r adjusted negatively %d -> %d" % (
                    predicate, before_score, result['score'])

    def build_predicates(self):
        """Construct predicates to check against the context."""
        self.add_standard_predicates()
        self.add_december_predicate()
        self.add_location_predicates()
        self.add_weather_predicates()
        self.add_birthday_predicates()
        self.add_extra_predicates()
        self.add_last_song_predicates()
        self.add_nearby_artist_predicates()

    def add_nearby_artist_predicates(self):
        for artist in self.nearby_artists:
            self.predicates.append(ArtistPredicate(artist))

    def add_last_song_predicates(self):
        if self.last_song:
            words = [
                word for word in ALPHANUMSPACE.sub(
                    ' ', self.last_song.get_title(with_version=False)).split()
                if word]
            if words:
                self.predicates.append(WordsPredicate(words))
            self.predicates.append(
                TagsPredicate(self.last_song.get_non_geo_tags()))
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
            Gale(), Hurricane(), Humid(), Cloudy(), Rain(), Fog()])
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
                Night, Day, Christmas, NewYear, Halloween, Easter):
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
        result['score'] /= 3

    def negative_score(self, result):
        pass


class ExclusivePredicate(Predicate):

    def negative_score(self, result):
        result['score'] *= 1.5


class Period(ExclusivePredicate):

    period = ONE_YEAR
    decay = None

    def __init__(self, peak):
        super(Period, self).__init__()
        self.diff = None
        self.peak = peak

    def get_diff(self, datetime):
        self.diff = abs(datetime - self.peak)
        if self.diff.total_seconds() > self.period.total_seconds() / 2:
            self.diff = self.period - self.diff
        return self.diff

    def applies_in_context(self, context):
        return self.get_diff(context.date) < self.decay

    def positive_score(self, result):
        result['score'] /= 1 + (
            2 - (2 * self.diff.total_seconds() / self.decay.total_seconds()))

    def negative_score(self, result):
        result['score'] *= min(
            1.5,
            ((self.diff.total_seconds() / self.decay.total_seconds()) * 1.5))


class DayPeriod(Period):

    period = ONE_DAY


class ArtistPredicate(Predicate):

    def __init__(self, artist):
        self.artist = artist
        self.terms = (artist,)
        super(ArtistPredicate, self).__init__()

    def applies_to_song(self, song, exclusive):
        if self.artist.strip().lower() in [a.strip().lower()
                                           for a in song.get_artists()]:
            return True
        return super(ArtistPredicate, self).applies_to_song(song, exclusive)


class TagsPredicate(Predicate):

    def __init__(self, tags):
        self.tags = set(tags)
        super(TagsPredicate, self).__init__()

    def applies_to_song(self, song, exclusive):
        return set(song.get_non_geo_tags()) & self.tags

    def positive_score(self, result):
        song_tags = set(result['song'].get_non_geo_tags())
        score = (
            len(song_tags & self.tags) /
            float(len(song_tags | self.tags) + 1))
        result['score'] /= 1 + score

    def __repr__(self):
        return '<TagsPredicate %r>' % self.tags


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


class WordsPredicate(Predicate):

    def __init__(self, words):
        self.words = set(words)
        super(WordsPredicate, self).__init__()

    def get_song_words(self, song):
        return set(
            word for word in ALPHANUMSPACE.sub(
                ' ', song.get_title(with_version=False)).split())

    def applies_to_song(self, song, exclusive):
        return self.get_song_words(song) & self.words

    def positive_score(self, result):
        song_words = self.get_song_words(result['song'])
        score = (
            len(song_words & self.words) /
            float(len(song_words | self.words) + 1))
        result['score'] /= 1 + score

    def __repr__(self):
        return '<WordsPredicate %r>' % self.words


class WeatherPredicate(ExclusivePredicate):

    def get_weather_conditions(self, context):
        return context.weather.get(
            'condition', {}).get('text', '').lower().strip().split('/')

    def get_temperature(self, context):
        temperature = context.weather.get('condition', {}).get('temp', '')
        if not temperature:
            return None

        return int(temperature)

    def get_wind_speed(self, context):
        return float(
            context.weather.get('wind', {}).get('speed', '').strip() or '0')

    def get_humidity(self, context):
        return float(
            context.weather.get('atmosphere', {}).get('humidity', '').strip()
            or '0')


class Freezing(WeatherPredicate):

    terms = ('freezing', 'frozen', 'ice', 'frost')

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

    # XXX: remove
    def applies_to_song(self, song, exclusive):
        """Determine whether the predicate applies to the song."""
        title = song.get_title(with_version=False).lower()
        for search in self.get_tag_searches(exclusive=exclusive):
            for tag in song.get_non_geo_tags():
                if search.match(tag):
                    print "*" * 50
                    print search.pattern, tag
                    print "*" * 50
                    return True

        for search in self.get_title_searches(exclusive=exclusive):
            if search.search(title):
                return True

        return False


class Season(Period):

    decay = TWO_MONTHS

    def applies_in_context(self, context):
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
        new = cls(peak=DEC21(now.year - 1) + FORTY_FIVE_DAYS)
        new.build_searches()
        return new


class Spring(Season):

    terms = ('spring', 'springtime')

    @classmethod
    def from_datetime(cls, now):
        new = cls(peak=MAR21(now.year) + FORTY_FIVE_DAYS)
        new.build_searches()
        return new


class Summer(Season):

    terms = ('summer', 'summertime')

    @classmethod
    def from_datetime(cls, now):
        new = cls(peak=JUN21(now.year) + FORTY_FIVE_DAYS)
        new.build_searches()
        return new


class Autumn(Season):

    terms = ('autumn',)
    tag_only_terms = ('fall',)

    @classmethod
    def from_datetime(cls, now):
        new = cls(peak=SEP21(now.year) + FORTY_FIVE_DAYS)
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

    terms = ('day',)
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
        date = context.date
        weekday = date.isoweekday()
        return weekday == 6 or weekday == 7 or (
            weekday == 5 and date.hour >= 17)


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
        easter = EASTERS[context_date.year]
        if self.easter_offset(context_date, easter):
            return True

        return False

    def easter_offset(self, from_date, easter):
        return (from_date - easter).days == self.days_after_easter


class Easter(Period):

    terms = ('easter',)
    non_exclusive_terms = (
        'resurrect', 'resurrection', 'jesus', 'egg', 'bunny', 'bunnies',
        'rabbit')
    decay = THREE_DAYS

    @classmethod
    def from_datetime(cls, datetime):
        new = cls(peak=EASTERS[datetime.year])
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
