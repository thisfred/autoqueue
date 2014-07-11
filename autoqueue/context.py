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

ONE_HOUR = timedelta(hours=1)
ONE_DAY = timedelta(days=1)


def escape(the_string):
    """Double escape quotes."""
    # TODO: move to utils
    return the_string.replace('"', '\\"').replace("'", "\\'")

alphanumspace = re.compile(r'([^\s\w]|_)+')


class Context(object):

    """Object representing the current context."""

    def __init__(self, date, location, geohash, birthdays, last_song,
                 nearby_artists, southern_hemisphere, weather, extra_context):
        self.date = date
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
            if predicate.applies_to_song(song, exclusive=False) and in_context:
                predicate.positive_score(result)
                print "%s - %s" % (
                    song.get_artist(), song.get_title(with_version=False))
                print repr(predicate), "adjusted positively", result['score']
            elif predicate.applies_to_song(song, exclusive=True) \
                    and not in_context:
                print "%s - %s" % (
                    song.get_artist(), song.get_title(with_version=False))
                print repr(predicate), "adjusted negatively", result['score']

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
                word for word in alphanumspace.sub(
                    ' ', self.last_song.get_title(with_version=False)).split()
                if len(word) > 3]
            if words:
                self.predicates.append(StringPredicate(words))
            self.predicates.append(
                TagsPredicate(self.last_song.get_non_geo_tags()))
            self.predicates.append(
                GeohashPredicate(self.last_song.get_geohashes()))

    def add_extra_predicates(self):
        if self.extra_context:
            words = [l.strip().lower() for l in self.extra_context.split(',')]
            if words:
                self.predicates.append(StringPredicate(words))

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

    def add_weather_predicates(self):
        if not self.weather:
            return
        self.predicates.extend([
            Freezing(), Cold(), Hot(), Calm(), Breeze(), Wind(), Storm(),
            Gale(), Storm(), Hurricane(), Humid(), Cloudy(), Rain()])
        sunrise = self.weather.get('astronomy', {}).get('sunrise', '')
        sunset = self.weather.get('astronomy', {}).get('sunset', '')
        if sunrise and sunset:
            sunrise = self.string_to_datetime(sunrise)
            if sunrise:
                self.predicates.append(Dawn.from_datetime(sunrise))
            sunset = self.string_to_datetime(sunset)
            if sunset:
                self.predicates.append(Dusk.from_datetime(sunset))
            self.predicates.append(Darkness.from_dates(end=sunrise))
            self.predicates.append(
                Daylight.from_dates(start=sunrise, end=sunset))
            self.predicates.append(Darkness.from_dates(start=sunset))
            self.predicates.append(Sun.from_dates(start=sunrise, end=sunset))
        cs = self.weather.get(
            'condition', {}).get('text', '').lower().strip().split('/')
        for condition in cs:
            condition = condition.strip()
            with open('weather_conditions.txt', 'a') as weather_file:
                weather_file.write('%s\n' % condition)
            if condition:
                conditions = []
                unmodified = condition.split()[-1]
                if unmodified in ('rain', 'drizzle', 'cloudy'):
                    continue
                if unmodified not in conditions:
                    conditions.append(unmodified)
                if unmodified[-1] == 'y':
                    if unmodified[-2] == unmodified[-3]:
                        conditions.append(unmodified[:-2])
                    else:
                        conditions.append(unmodified[:-1])
                if conditions:
                    self.predicates.append(StringPredicate(conditions))

    def add_location_predicates(self):
        if self.location:
            locations = [l.lower() for l in self.location.split(',')]
            if locations:
                self.predicates.append(StringPredicate(locations))
        if self.geohash:
            self.predicates.append(GeohashPredicate([self.geohash]))

    def add_december_predicate(self):
        if self.date.month == 12:
            # December is for retrospection
            self.predicates.append(SongYearPredicate(self.date.year))

    def add_standard_predicates(self):
        self.predicates.extend(
            STATIC_PREDICATES + [
                YearPredicate(self.date.year),
                DatePredicate.from_date(self.date),
                TimePredicate.from_datetime(self.date),
                Midnight.from_date(self.date),
                Noon.from_date(self.date)])


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

    def _build_search(self, term):
        return '%s(e?s)?' % (re.escape(term),)

    def build_title_search(self, term):
        return re.compile(r'\b%s\b' % (self._build_search(term),))

    def build_tag_search(self, term):
        return re.compile(r'(.*:)?%s$' % (self._build_search(term),))

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
        result['score'] /= 2

    def negative_score(self, result):
        pass

    @classmethod
    def get_search_expressions(cls, modifier=''):
        searches = []
        multiples = '(e?s)?' if cls.multiples else ''
        for alternative in cls.get_search_terms():
            searches.extend([
                '%sgrouping=/^%s%s$/' % (modifier, alternative, multiples),
                '%stitle=/\\b%s%s\\b/' % (modifier, alternative, multiples)])
        for alternative in cls.tag_only_terms:
            searches.append(
                '%sgrouping=/^%s%s$/' % (modifier, alternative, multiples))
        return searches

    @classmethod
    def get_negative_search_expressions(cls):
        return cls.get_search_expressions(modifier='!')


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
        result['score'] *= 1.0 / (2 ** longest_common)


class YearPredicate(Predicate):

    def __init__(self, year):
        self.tag_only_terms = (str(year),)
        super(YearPredicate, self).__init__()


class SongYearPredicate(YearPredicate):

    def applies_to_song(self, song, exclusive):
        return self.year == song.get_year()


class ExclusivePredicate(Predicate):

    def negative_score(self, result):
        result['score'] *= 1.5


class StringPredicate(Predicate):

    def __init__(self, term):
        self.terms = (term,)
        super(StringPredicate, self).__init__()

    def __repr__(self):
        return '<StringPredicate %r>' % self.terms


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
        return float(context.weather.get('wind', {}).get('speed', '0'))

    def get_humidity(self, context):
        return float(context.weather.get('atmosphere', {}).get('humidity', '0'))


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

        if temperature < 30:
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


class TimePredicate(ExclusivePredicate):

    time_tag = re.compile('^([0-9]{2}):([0-9]{2})$')
    max_diff = 30

    def applies_in_context(self, context):
        return self._close_enough(context.date.hour, context.date.minute)

    def _close_enough(self, hour, minute):
        other_date = datetime(
            self.date.year, self.date.month, self.date.day, hour, minute)
        other_dates = [other_date, other_date + ONE_DAY, other_date - ONE_DAY]
        for date in other_dates:
            difference = abs(date - self.date)
            if difference <= timedelta(minutes=self.max_diff):
                return True
        return False

    def applies_to_song(self, song, exclusive):
        song_tags = song.get_non_geo_tags()
        for tag in song_tags:
            match = self.time_tag.match(tag)
            if match:
                hour, minute = match.groups()
                if self._close_enough(int(hour), int(minute)):
                    return True

        return super(TimePredicate, self).applies_to_song(song, exclusive)

    @classmethod
    def from_datetime(cls, datetime):
        new = cls()
        new.date = datetime
        new.build_searches()
        return new

    def __repr__(self):
        return '<TimePredicate %s>' % (self.date,)


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
        return new


class Daylight(TimeRangePredicate):

    terms = ('daylight',)


class Darkness(TimeRangePredicate):

    terms = ('dark', 'darkness')


class Sun(TimeRangePredicate, WeatherPredicate):

    terms = ('sun', 'sunny', 'sunlight', 'sunshine')

    def applies_in_context(self, context):
        if super(Sun, self).applies_in_context(context):
            conditions = self.get_weather_conditions(context)
            for condition in conditions:
                if 'partly cloudy' in condition or 'fair' in condition:
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

    def applies_in_context(self, context):
        conditions = self.get_weather_conditions(context)
        for condition in conditions:
            if 'rain' in condition or 'shower' in condition or\
                    'drizzle' in condition:
                return True

        return False


class Dawn(TimePredicate):

    max_diff = 60
    terms = (
        'sunrise', 'dawn', 'aurora', 'break of day', 'dawning', 'daybreak',
        'sunup')


class Dusk(TimePredicate):

    max_diff = 60
    terms = (
        'sunset', 'dusk', 'gloaming', 'nightfall', 'sundown', 'twilight',
        'eventide', 'close of day')


class Noon(TimePredicate):

    terms = ('noon',)

    @classmethod
    def from_date(cls, date):
        new = cls()
        new.date = datetime(date.year, date.month, date.day, 12, 0)
        new.build_searches()
        return new


class Midnight(TimePredicate):

    terms = ('midnight',)

    @classmethod
    def from_date(cls, date):
        new = cls()
        new.date = datetime(date.year, date.month, date.day, 0, 0)
        new.build_searches()
        return new


class DatePredicate(ExclusivePredicate):

    day = None
    month = None

    @classmethod
    def from_date(cls, date):
        """Construct a DatePredicate from a datetime object."""
        new = cls()
        new.month = date.month
        new.day = date.day
        new.build_searches()
        return new

    def applies_in_context(self, context):
        date = context.date
        return date.day == self.day and date.month == self.month

    def build_searches(self):
        super(DatePredicate, self).build_searches()
        if self.month and self.day:
            self.tag_searches.append(
                self.build_tag_search(
                    r"(\d{4}-)?%02d-%02d" % (self.month, self.day)))


class SeasonPredicate(ExclusivePredicate):

    pass


class Winter(SeasonPredicate):

    terms = ('winter', 'wintertime')

    def applies_in_context(self, context):
        date = context.date
        southern_hemisphere = context.southern_hemisphere
        if (date >= DEC21(date.year) or date <= MAR21(date.year)
                and not southern_hemisphere):
            return True

        if (date >= JUN21(date.year) and date <= SEP21(date.year)
                and southern_hemisphere):
            return True

        return False


class Spring(SeasonPredicate):

    terms = ('spring', 'springtime')

    def applies_in_context(self, context):
        date = context.date
        southern_hemisphere = context.southern_hemisphere
        if (date >= MAR21(date.year) and date <= JUN21(date.year)
                and not southern_hemisphere):
            return True

        if (date >= SEP21(date.year) and date <= DEC21(date.year)
                and southern_hemisphere):
            return True

        return False


class Summer(SeasonPredicate):

    terms = ('summer', 'summertime')

    def applies_in_context(self, context):
        date = context.date
        southern_hemisphere = context.southern_hemisphere
        if (date >= JUN21(date.year) and date <= SEP21(date.year)
                and not southern_hemisphere):
            return True

        if (date >= DEC21(date.year) or date <= MAR21(date.year)
                and southern_hemisphere):
            return True

        return False


class Autumn(SeasonPredicate):

    terms = ('autumn',)
    tag_only_terms = ('fall',)

    def applies_in_context(self, context):
        date = context.date
        southern_hemisphere = context.southern_hemisphere
        if (date >= SEP21(date.year) and date <= DEC21(date.year)
                and not southern_hemisphere):
            return True

        if (date >= MAR21(date.year) and date <= JUN21(date.year)
                and southern_hemisphere):
            return True

        return False


class MonthPredicate(ExclusivePredicate):

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


class Night(ExclusivePredicate):

    terms = ('night',)

    def applies_in_context(self, context):
        date = context.date
        return date.hour >= 21 or date.hour < 4


class Evening(ExclusivePredicate):

    terms = ('evening',)

    def applies_in_context(self, context):
        date = context.date
        return date.hour >= 18 and date.hour < 21


class Morning(ExclusivePredicate):

    terms = ('morning',)

    def applies_in_context(self, context):
        date = context.date
        return date.hour >= 4 and date.hour < 12


class Afternoon(ExclusivePredicate):

    terms = ('afternoon',)

    def applies_in_context(self, context):
        date = context.date
        return date.hour >= 12 and date.hour < 18


class Weekend(ExclusivePredicate):

    terms = ('weekend',)

    def applies_in_context(self, context):
        date = context.date
        weekday = date.isoweekday()
        return weekday == 6 or weekday == 7 or (
            weekday == 5 and date.hour >= 17)


class Christmas(ExclusivePredicate):

    terms = ('christmas', 'santa claus', 'xmas')

    non_exclusive_terms = (
        'reindeer', 'sled', 'santa', 'snow', 'bell', 'jesus', 'eggnoc',
        'mistletoe', 'carol', 'nativity', 'mary', 'joseph', 'manger')

    def applies_in_context(self, context):
        date = context.date
        return date.month == 12 and date.day >= 20 and date.day <= 29


class Kwanzaa(ExclusivePredicate):

    terms = ('kwanzaa',)

    def applies_in_context(self, context):
        date = context.date
        return (date.month == 12 and date.day >= 26) or (
            date.month == 1 and date.day == 1)


class NewYear(ExclusivePredicate):

    terms = ('new year',)

    def applies_in_context(self, context):
        date = context.date
        return (date.month == 12 and date.day >= 27) or (
            date.month == 1 and date.day <= 7)


class Halloween(ExclusivePredicate):

    terms = ('halloween', 'hallowe\'en', 'all hallow\'s')
    non_exclusive_terms = (
        'haunt', 'haunting', 'haunted', 'ghost', 'monster', 'horror', 'devil',
        'witch', 'pumkin', 'bone', 'skeleton', 'ghosts', 'zombie', 'werewolf',
        'werewolves', 'vampire', 'evil', 'scare', 'scary', 'scaring', 'fear',
        'fright', 'blood', 'bat', 'dracula', 'spider', 'costume', 'satan',
        'hell', 'undead', 'dead', 'death', 'grave')

    def applies_in_context(self, context):
        date = context.date
        return (date.month == 10 and date.day >= 25) or (
            date.month == 11 and date.day < 2)


class EasterBased(ExclusivePredicate):

    def applies_in_context(self, context):
        date = context.date
        easter = EASTERS[date.year]
        if self.easter_offset(date, easter):
            return True

        return False

    def easter_offset(self, date, easter):
        return (date - easter).days == self.days_after_easter


class Easter(EasterBased):

    terms = ('easter',)
    non_exclusive_terms = ('egg', 'bunny', 'bunnies', 'rabbit')

    def easter_offset(self, date, easter):
        return abs(date - easter).days < 5


class MardiGras(EasterBased):

    terms = ('mardi gras', 'shrove tuesday', 'fat tuesday')
    days_after_easter = -47


class AshWednesday(EasterBased):

    terms = ('ash wednesday',)
    non_exclusive_terms = ('ash',)
    days_after_easter = -46


class PalmSunday(EasterBased):

    terms = ('palm sunday',)
    non_exclusive_terms = ('palms',)
    days_after_easter = -7


class MaundyThursday(EasterBased):

    terms = ('maundy thursday',)
    days_after_easter = -3


class GoodFriday(EasterBased):

    terms = ('good friday',)
    days_after_easter = -2


class Ascension(EasterBased):

    terms = ('ascension',)
    days_after_easter = 39


class Pentecost(EasterBased):

    terms = ('pentecost',)
    days_after_easter = 49


class WhitMonday(EasterBased):

    terms = ('whit monday',)
    days_after_easter = 50


class AllSaints(EasterBased):

    terms = ('all saints',)
    days_after_easter = 56


class VeteransDay(DatePredicate):

    terms = ('armistice day', 'veterans day')
    non_exclusive_terms = ('peace', 'armistice', 'veteran')
    month = 11
    day = 11


class Assumption(DatePredicate):

    terms = ('assumption',)
    month = 8
    day = 15


class IndependenceDay(DatePredicate):

    terms = ('independence day',)
    non_exclusive_terms = (
        'independence', 'united states', 'independant', 'usa', 'u.s.a.')
    month = 7
    day = 4


class GroundhogDay(DatePredicate):

    terms = ('groundhog day',)
    non_exclusive_terms = ('groundhog',)
    month = 2
    day = 2


class ValentinesDay(DatePredicate):

    terms = ('valentine',)
    non_exclusive_terms = ('heart', 'love')
    month = 2
    day = 14


class AprilFools(DatePredicate):

    terms = ('april fool',)
    non_exclusive_terms = ('prank', 'joke', 'fool', 'hoax')
    month = 4
    day = 1


class CincoDeMayo(DatePredicate):

    terms = ('cinco de mayo',)
    non_exclusive_terms = ('mexico',)
    month = 5
    day = 5


class Solstice(ExclusivePredicate):

    terms = ('solstice',)

    def applies_in_context(self, context):
        date = context.date
        return date.day == 21 and (date.month == 6 or date.month == 12)


class Friday13(ExclusivePredicate):

    terms = ('friday the 13th',)
    non_exclusive_terms = ('bad luck', 'superstition')

    def applies_in_context(self, context):
        date = context.date
        return date.day == 13 and date.isoweekday() == 5


class BirthdayPredicate(DatePredicate):

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
    Christmas(), Kwanzaa(), NewYear(), Halloween(), Easter(),
    MardiGras(), AshWednesday(), PalmSunday(), MaundyThursday(),
    GoodFriday(), Ascension(), Pentecost(), WhitMonday(), AllSaints(),
    VeteransDay(), Assumption(), IndependenceDay(), GroundhogDay(),
    ValentinesDay(), AprilFools(), CincoDeMayo(), Solstice(),
    Friday13(), January(), February(), March(), April(), May(), June(),
    July(), August(), September(), October(), November(), December(),
    Monday(), Tuesday(), Wednesday(), Thursday(), Friday(), Saturday(),
    Sunday(), Weekend(), Spring(), Summer(), Autumn(), Winter(),
    Evening(), Morning(), Afternoon(), Night(),]
