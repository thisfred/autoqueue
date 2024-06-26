"""Context awareness filters."""

import re
from datetime import date, datetime, time, timedelta
from os.path import commonprefix
from typing import List, Optional, Pattern, Tuple

from dateutil.easter import easter  # type: ignore[import-untyped]
from dateutil.rrule import TH, YEARLY, rrule  # type: ignore[import-untyped]
from sentence_transformers.cross_encoder import CrossEncoder

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

TIME = re.compile(r"([0-9]{2}):([0-9]{2})")
# remove problematic synsets

static_predicates = []


def static_predicate(cls):
    static_predicates.append(cls())
    return cls


def get_artist_tags(song):
    return song.get_non_geo_tags(prefix="artist:", exclude_prefix="")


def _normalize_title(title):
    return " ".join(
        w
        for w in title.replace("_", " ").replace("-", " ").split()
        if w.lower() != "[unknown]"
    )


class Context(object):

    """Object representing the current context."""

    def __init__(self, context_date, configuration, cache):
        self.date = context_date
        self.configuration = configuration
        self.cache = cache
        self.weather = cache.get_weather(configuration)
        self.predicates = []
        self.build_predicates()
        self.model = CrossEncoder("cross-encoder/stsb-distilroberta-base")

    @staticmethod
    def string_to_datetime(time_string):
        time_string, _, ampm = time_string.partition(" ")
        hour, _, minute = time_string.partition(":")
        hour = int(hour)
        minute = int(minute)
        if ampm == "am":
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
        song = result["song"]
        sentences = []
        for predicate in self.predicates:
            in_context = predicate.applies_in_context(self)
            applies = predicate.applies_to_song(song)
            if applies and in_context:
                if predicate.sentence:
                    sentences.append((predicate.sentence, predicate.scale))
                    continue
                predicate.score(result, applies)

        if sentences:
            title = result["song"].get_title(with_version=False)
            scores = self.model.predict(
                [[sentence, title] for sentence, _ in sentences]
            )
            for score, (sentence, scale) in zip(scores, sentences):
                scaled = 1 / (1 + score * scale)
                result["score"] = result["score"] * scaled

                if score > 0.3:
                    result.setdefault("reasons", []).append(
                        f"{title} :: {sentence} :: {scaled}"
                    )

    def build_predicates(self):
        """Construct predicates to check against the context."""
        self.add_standard_predicates()
        self.add_song_year_predicate()
        self.add_location_predicates()
        self.add_weather_predicates()
        self.add_birthday_predicates()
        self.add_extra_predicates()
        self.add_previous_songs_predicates()

    def add_previous_songs_predicates(self):
        previous_terms: List[Predicate] = []
        bpm = None
        number_of_songs = len(self.cache.previous_songs)
        for i, song in enumerate(self.cache.previous_songs):
            bpm = song.song.get("bpm")
            scale = (i + 1) / number_of_songs
            previous_terms.append(
                String(song.get_title(with_version=False), scale=scale)
            )
            previous_terms.append(Tags(song.get_non_geo_tags(), scale=scale))
            if (year := song.get_year()) and year != self.date.year:
                previous_terms.append(SongYear(year, scale=scale))
            previous_terms.append(Geohash(song.get_geohashes(), scale=scale))

        if bpm:
            try:
                self.predicates.append(BPM(float(bpm)))
            except (ValueError, TypeError):
                pass

        self.predicates.extend(previous_terms)

    def add_extra_predicates(self):
        if self.configuration.extra_context:
            words = (
                word.strip().lower()
                for word in self.configuration.extra_context.split(",")
            )
            self.predicates.append(Tags(t.split(":")[-1] for t in words))

    def add_birthday_predicates(self):
        for name_date in self.configuration.birthdays.split(","):
            if ":" not in name_date:
                continue
            name, _, date_string = name_date.strip().partition(":")
            birth_date = self.get_date(date_string)
            age = self.date.year - birth_date.year
            self.predicates.append(Birthday(birth_date=birth_date, name=name, age=age))

    @staticmethod
    def get_date(date_string):
        date_string = date_string.strip()
        delimiter = "-" if "-" in date_string else "/"
        return date(*[int(i) for i in date_string.split(delimiter)])

    def get_astronomical_times(self, weather):
        sunrise = weather.sunrise_time()
        sunset = weather.sunset_time()
        predicates: List[Predicate] = []
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
        self.predicates.extend(
            [
                Freezing(),
                Cold(),
                Hot(),
                Calm(),
                Breeze(),
                Wind(),
                Storm(),
                Gale(),
                Hurricane(),
                Humid(),
                Cloudy(),
                Rain(),
                Snow(),
                Sleet(),
                Fog(),
            ]
        )
        self.predicates.extend(self.get_astronomical_times(self.weather))
        self.predicates.extend(self.get_other_conditions(self.weather))

    @staticmethod
    def get_other_conditions(weather):
        for condition in weather.detailed_status.lower().split("/"):
            condition = condition.strip()
            with open("weather_conditions.txt", "a") as weather_file:
                weather_file.write("%s\n" % condition)
            if condition:
                results = []
                unmodified = condition.split()[-1]
                if unmodified in {
                    "rain",
                    "rainy",
                    "drizzle",
                    "clouds",
                    "clouds",
                    "fog",
                    "foggy",
                    "mist",
                    "misty",
                    "fair",
                }:
                    continue
                results.append(condition)
        return [String(c) for c in results]

    def add_location_predicates(self):
        if self.configuration.geohash:
            self.predicates.append(Geohash([self.configuration.geohash]))

    def add_song_year_predicate(self):
        self.predicates.append(SongYear(self.date.year))

    def add_standard_predicates(self):
        self.predicates.extend(static_predicates)
        for predicate in (
            Year,
            Date.from_date,
            Now,
            Midnight,
            Noon,
            Spring,
            Summer,
            Fall,
            Winter,
            Evening,
            Morning,
            Afternoon,
            Night,
            DayTime,
            Christmas,
            NewYear,
            Halloween,
            Easter,
            Thanksgiving,
        ):
            self.predicates.append(predicate(self.date))


class Predicate(object):
    sentence: Optional[str] = None
    scale = 1.0

    def applies_to_song(self, song):
        raise NotImplementedError

    def applies_in_context(self, context):
        return True

    def get_factor(self, song):
        return 1.0

    def scaled(self, factor):
        if factor > 1:
            factor *= self.scale
        elif factor < 1:
            factor = 1 - ((1 - factor) * self.scale)
        return factor

    def score(self, result, applies):
        factor = 1 / (1 + self.get_factor(result["song"]) * self.scale)
        result["score"] *= factor
        result.setdefault("reasons", []).append((self, applies, factor))

    def __repr__(self):
        return "<%s>" % self.__class__.__name__


class Tags(Predicate):
    def __init__(self, tags, scale=1.0):
        self.tags = set(tags)
        self.scale = scale

    def applies_to_song(self, song):
        return self.tags & set(song.get_non_geo_tags())

    def get_factor(self, song):
        song_tags = set(song.get_non_geo_tags())
        return len(self.tags & song_tags) / len(self.tags | song_tags)


class BPM(Predicate):
    def __init__(self, bpm: float):
        self.bpm = bpm

    def applies_to_song(self, song):
        try:
            return float(song.song.get("bpm"))
        except (ValueError, TypeError):
            return False

    def score(self, result, applies):
        factor = self.scaled(self.get_factor(result["song"]))
        result["score"] *= factor
        result.setdefault("reasons", []).append((self, applies, factor))

    def get_factor(self, song):
        try:
            return abs(float(song.song.get("bpm")) - self.bpm) / 5
        except (ValueError, TypeError):
            return 1


class Terms(Predicate):
    regex_terms: Tuple[Pattern, ...] = tuple()
    song = None

    def applies_to_song(self, song):
        return bool(self.sentence) or self.regex_terms_match(song)

    def regex_terms_match(self, song):
        """Determine whether the predicate applies to the song."""

        for search in self.regex_terms:
            for tag in song.get_non_geo_tags():
                if search.match(tag):
                    return True

        return False

    def __repr__(self):
        song = self.song
        if not song:
            return super(Terms, self).__repr__()

        return "<%s: %s - %s>" % (
            self.__class__.__name__,
            song.get_artist(),
            song.get_title(),
        )


class Period(Terms):
    period = ONE_YEAR
    decay: Optional[timedelta] = None

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

    def get_factor(self, song):
        factor = super(Period, self).get_factor(song)

        return factor * (
            1.0
            - min(
                1,
                (
                    self.diff.total_seconds()
                    if self.diff
                    else 1 / self.decay.total_seconds()
                    if self.decay
                    else 1
                ),
            )
        )


class Geohash(Predicate):
    def __init__(self, geohashes, scale=1.0):
        self.geohashes = geohashes
        self.scale = scale

    def applies_to_song(self, song):
        for self_hash in self.geohashes:
            for other_hash in song.get_geohashes():
                prefix = commonprefix((self_hash, other_hash))
                if prefix:
                    return prefix

        return False

    def __repr__(self):
        return "<Geohash %r>" % self.geohashes

    def score(self, result, applies):
        factor = self.scaled(self.get_factor(result["song"]))
        result["score"] *= factor
        result.setdefault("reasons", []).append((self, applies, factor))

    def get_factor(self, song):
        best_score = 1.0
        for self_hash in self.geohashes:
            if not self_hash:
                continue
            for other_hash in song.get_geohashes():
                if not other_hash:
                    continue

                prefix = commonprefix((self_hash, other_hash))

                score = 1 / (len(prefix) + 1)

                if score < best_score:
                    best_score = score

        return best_score


class Year(Terms):
    def __init__(self, timestamp):
        self.terms = (str(timestamp.year),)
        super(Year, self).__init__()


class SongYear(Predicate):
    def __init__(self, year, scale=1.0):
        self.year = year
        self.scale = scale

    def applies_to_song(self, song):
        return self.was_released(song) or self.artist_died(song)

    def was_released(self, song):
        if not song.get_year():
            return False

        return abs(self.year - song.get_year()) <= 5

    def artist_died(self, song):
        year = str(self.year)
        artist_tags = get_artist_tags(song)
        return "dead" in artist_tags and any(t.startswith(year) for t in artist_tags)

    def get_factor(self, song):
        if self.was_released(song):
            return 1.0 / (1.0 + abs(self.year - song.get_year()))
        else:
            return 1.0


class String(Terms):
    def __init__(self, term, scale=1.0):
        super(String, self).__init__()
        self.terms = (term,)
        self.sentence = term
        self.scale = scale

    def __repr__(self):
        return "<String %r>" % self.terms


class Weather(Terms):
    @staticmethod
    def get_weather_conditions(context):
        return context.weather.detailed_status.lower().strip().split("/")

    @staticmethod
    def get_temperature(context):
        return context.weather.temperature().get("temp")

    @staticmethod
    def get_wind_speed(context):
        return context.weather.wind().get("speed")

    @staticmethod
    def get_humidity(context):
        return context.weather.humidity or 0


class Freezing(Weather):
    sentence = "It is below freezing"

    def applies_in_context(self, context):
        temperature = self.get_temperature(context)
        if temperature is None:
            return False

        if temperature > 0:
            return False

        return True


class Cold(Weather):
    sentence = "It is cold"

    def applies_in_context(self, context):
        temperature = self.get_temperature(context)
        if temperature is None:
            return False

        if temperature > 10:
            return False

        return True


class Hot(Weather):
    sentence = "It is hot"

    def applies_in_context(self, context):
        temperature = self.get_temperature(context)
        if temperature is None:
            return False

        if temperature < 25:
            return False

        return True


class Calm(Weather):
    sentence = "There is no wind"

    def applies_in_context(self, context):
        return self.get_wind_speed(context) < 1


class Breeze(Weather):
    sentence = "There is a breeze"

    def applies_in_context(self, context):
        speed = self.get_wind_speed(context)
        return speed > 0


class Wind(Weather):
    sentence = "It is windy"

    def applies_in_context(self, context):
        return self.get_wind_speed(context) > 30


class Gale(Weather):
    sentence = "There is a gale"

    def applies_in_context(self, context):
        return self.get_wind_speed(context) > 38


class Storm(Weather):
    sentence = "There is a storm"

    def applies_in_context(self, context):
        return self.get_wind_speed(context) > 54


class Hurricane(Weather):
    sentence = "There is a hurricane"

    def applies_in_context(self, context):
        return self.get_wind_speed(context) > 72


class Humid(Weather):
    sentence = "It is humid"

    def applies_in_context(self, context):
        return self.get_humidity(context) > 65


class Now(Period):
    period = ONE_DAY
    decay = HALF_HOUR

    def applies_to_song(self, song):
        song_tags = song.get_non_geo_tags()
        for tag in song_tags:
            match = TIME.match(tag)
            if match:
                hour, minute = match.groups()
                song_datetime = datetime.now().replace(
                    hour=int(hour), minute=int(minute)
                )
                if self.get_diff_between_dates(song_datetime, self.peak) < self.decay:
                    return True

        return False

    def __repr__(self):
        return "<Now %s>" % (self.peak,)


class TimeRange(Terms):
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
    sentence = "There is daylight"


class NegativeTimeRange(TimeRange):
    def applies_in_context(self, context):
        return not super(NegativeTimeRange, self).applies_in_context(context)


class NotDaylight(NegativeTimeRange):
    sentence = "It is dark"


class Sun(TimeRange, Weather):
    sentence = "it is sunny"

    def applies_in_context(self, context):
        if super(Sun, self).applies_in_context(context):
            conditions = self.get_weather_conditions(context)
            for condition in conditions:
                if "few clouds" in condition or "fair" in condition:
                    return True

        return False


class Fog(Weather):
    sentence = "it is foggy"

    def applies_in_context(self, context):
        conditions = self.get_weather_conditions(context)
        for condition in conditions:
            if (
                "mist" in condition
                or "fog" in condition
                or "foggy" in condition
                or "misty" in condition
            ):
                return True

        return False


class Cloudy(Weather):
    sentence = "It is cloudy"

    def applies_in_context(self, context):
        conditions = self.get_weather_conditions(context)
        for condition in conditions:
            if "clouds" in condition or "overcast" in condition:
                return True

        return False


class Snow(Weather):
    sentence = "it is snowing"

    def applies_in_context(self, context):
        conditions = self.get_weather_conditions(context)
        for condition in conditions:
            if "snow" in condition:
                return True

        return False


class Sleet(Weather):
    sentence = "it is sleeting"

    def applies_in_context(self, context):
        conditions = self.get_weather_conditions(context)
        for condition in conditions:
            if "sleet" in condition:
                return True

        return False


class Rain(Weather):
    sentence = "it is raining"

    def applies_in_context(self, context):
        conditions = self.get_weather_conditions(context)
        for condition in conditions:
            if "rain" in condition or "shower" in condition or "drizzle" in condition:
                return True

        return False


class Dawn(Period):
    period = ONE_DAY
    decay = ONE_HOUR
    sentence = "the sun is rising"


class Dusk(Period):
    period = ONE_DAY
    decay = ONE_HOUR
    sentence = "the sun is setting"


class Noon(Period):
    period = ONE_DAY
    decay = HALF_HOUR
    sentence = "it is noon"

    def __init__(self, now):
        super(Noon, self).__init__(peak=now.replace(hour=12, minute=0, second=0))


class Midnight(Period):
    period = ONE_DAY
    decay = HALF_HOUR
    sentence = "it is midnight"

    def __init__(self, now):
        super(Midnight, self).__init__(peak=now.replace(hour=0, minute=0, second=0))


class Date(Terms):
    day = None
    month = None

    def __init__(self):
        self.set_regex()
        super(Date, self).__init__()

    def set_regex(self):
        if self.month and self.day:
            self.regex_terms = (
                re.compile(r"([0-9]{4}-)?%02d-%02d" % (self.month, self.day)),
            )

    @classmethod
    def from_date(cls, from_date):
        instance = cls()
        instance.month = from_date.month
        instance.day = from_date.day
        instance.set_regex()
        return instance

    def applies_in_context(self, context):
        return context.date.day == self.day and context.date.month == self.month


class Season(Period):
    decay = TWO_MONTHS

    def get_peak(self, context):
        if context.configuration.southern_hemisphere:
            return self.peak + SIX_MONTHS

        return self.peak


class Winter(Season):
    sentence = "It is winter"

    def __init__(self, now):
        super(Winter, self).__init__(
            peak=datetime(now.year - 1, 12, 21) + FORTY_FIVE_DAYS
        )


class Spring(Season):
    sentence = "It is spring"

    def __init__(self, now):
        super(Spring, self).__init__(peak=datetime(now.year, 3, 21) + FORTY_FIVE_DAYS)


class Summer(Season):
    sentence = "It is summer"

    def __init__(self, now):
        super(Summer, self).__init__(peak=datetime(now.year, 6, 21) + FORTY_FIVE_DAYS)


class Fall(Season):
    sentence = "It is autumn"

    def __init__(self, now):
        super(Fall, self).__init__(peak=datetime(now.year, 9, 21) + FORTY_FIVE_DAYS)


class Month(Terms):
    month = 0

    def applies_in_context(self, context):
        return context.date.month == self.month


@static_predicate
class January(Month):
    sentence = "It is January"
    month = 1


@static_predicate
class February(Month):
    sentence = "It is February"
    month = 2


@static_predicate
class March(Month):
    sentence = "It is March"
    month = 3


@static_predicate
class April(Month):
    sentence = "It is April"
    month = 4


@static_predicate
class May(Month):
    sentence = "It is May"
    month = 5


@static_predicate
class June(Month):
    sentence = "It is June"
    month = 6


@static_predicate
class July(Month):
    sentence = "It is July"
    month = 7


@static_predicate
class August(Month):
    sentence = "It is August"
    month = 8


@static_predicate
class September(Month):
    sentence = "It is September"
    month = 9


@static_predicate
class October(Month):
    sentence = "It is October"
    month = 10


@static_predicate
class November(Month):
    sentence = "It is November"
    month = 11


@static_predicate
class December(Month):
    sentence = "It is December"
    month = 12


class Day(Terms):
    day_index = 0

    def applies_in_context(self, context):
        return (
            context.date.isoweekday() == self.day_index and context.date.hour >= 4
        ) or (context.date.isoweekday() == self.day_index + 1 and context.date.hour < 4)


@static_predicate
class Monday(Day):
    sentence = "It is Monday"
    day_index = 1


@static_predicate
class Tuesday(Day):
    sentence = "It is Tuesday"
    day_index = 2


@static_predicate
class Wednesday(Day):
    sentence = "It is Wednesday"
    day_index = 3


@static_predicate
class Thursday(Day):
    sentence = "It is Thursday"
    day_index = 4


@static_predicate
class Friday(Day):
    sentence = "It is Friday"
    day_index = 5


@static_predicate
class Saturday(Day):
    sentence = "It is Saturday"
    day_index = 6


@static_predicate
class Sunday(Day):
    sentence = "It is Sunday"
    day_index = 7


class Night(Period):
    period = ONE_DAY
    decay = SIX_HOURS
    sentence = "It is night"

    def __init__(self, now):
        super(Night, self).__init__(
            peak=now.replace(hour=0, minute=0, second=0, microsecond=0)
        )


class DayTime(Period):
    period = ONE_DAY
    decay = SIX_HOURS
    sentence = "It is daytime"

    def __init__(self, now):
        super(DayTime, self).__init__(
            peak=now.replace(hour=12, minute=0, second=0, microsecond=0)
        )


class Evening(Period):
    period = ONE_DAY
    decay = THREE_HOURS
    sentence = "It is evening"

    def __init__(self, now):
        super(Evening, self).__init__(peak=now.replace(hour=20))


class Morning(Period):
    period = ONE_DAY
    decay = THREE_HOURS
    sentence = "It is morning"

    def __init__(self, now):
        super(Morning, self).__init__(peak=now.replace(hour=9))


class Afternoon(Period):
    period = ONE_DAY
    decay = THREE_HOURS
    sentence = "It is afternoon"

    def __init__(self, now):
        super(Afternoon, self).__init__(peak=now.replace(hour=15))


@static_predicate
class Weekend(Terms):
    sentence = "It is weekend"

    def applies_in_context(self, context):
        context_date = context.date
        weekday = context_date.isoweekday()
        return weekday in (6, 7) or (weekday == 5 and context_date.hour >= 17)


class Thanksgiving(Period):
    decay = THREE_DAYS
    sentence = "It is Thanksgiving"

    def __init__(self, now):
        super(Thanksgiving, self).__init__(
            peak=rrule(YEARLY, byweekday=TH(4), bymonth=11).after(
                datetime(now.year, 1, 1)
            )
        )


class Christmas(Period):
    decay = THREE_DAYS
    sentence = "It is Christmas"

    def __init__(self, now):
        super(Christmas, self).__init__(peak=now.replace(day=25, month=12))


@static_predicate
class Kwanzaa(Terms):
    sentence = "It is Kwanzaa"

    def applies_in_context(self, context):
        context_date = context.date
        return (context_date.month == 12 and context_date.day >= 26) or (
            context_date.month == 1 and context_date.day == 1
        )


class NewYear(Period):
    decay = THREE_DAYS
    sentence = "It is New Year's Eve"

    def __init__(self, now):
        super(NewYear, self).__init__(peak=now.replace(day=31, month=12))


class Halloween(Period):
    decay = THREE_DAYS
    sentence = "It is Halloween"

    def __init__(self, now):
        super(Halloween, self).__init__(peak=now.replace(day=31, month=10))


class EasterBased(Terms):
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
    sentence = "It is Easter"

    def __init__(self, now):
        super(Easter, self).__init__(peak=easter(now.year))


@static_predicate
class MardiGras(EasterBased):
    days_after_easter = -47
    sentence = "It is Mardi Gras"


@static_predicate
class AshWednesday(EasterBased):
    days_after_easter = -46
    sentence = "It is Ash Wednesday"


@static_predicate
class PalmSunday(EasterBased):
    days_after_easter = -7
    sentence = "It is Palm Sunday"


@static_predicate
class MaundyThursday(EasterBased):
    days_after_easter = -3
    sentence = "It is Maundy Thursday"


@static_predicate
class GoodFriday(EasterBased):
    days_after_easter = -2
    sentence = "It is Good Friday"


@static_predicate
class Ascension(EasterBased):
    days_after_easter = 39
    sentence = "It is Ascension Day"


@static_predicate
class Pentecost(EasterBased):
    days_after_easter = 49
    sentence = "It is Pentecost"


@static_predicate
class WhitMonday(EasterBased):
    days_after_easter = 50
    sentence = "It is Whit Monday"


@static_predicate
class AllSaints(EasterBased):
    days_after_easter = 56
    sentence = "It is All Saints"


@static_predicate
class VeteransDay(Date):
    month = 11
    day = 11
    sentence = "It is Veterans Day"


@static_predicate
class Assumption(Date):
    month = 8
    day = 15
    sentence = "It is Assumption Day"


@static_predicate
class IndependenceDay(Date):
    month = 7
    day = 4
    sentence = "It is US Independence Day"


@static_predicate
class GroundhogDay(Date):
    month = 2
    day = 2
    sentence = "It is Groundhog Day"


@static_predicate
class ValentinesDay(Date):
    month = 2
    day = 14
    sentence = "It is Valentines Day"


@static_predicate
class AprilFools(Date):
    month = 4
    day = 1
    sentence = "It is April Fools"


@static_predicate
class CincoDeMayo(Date):
    month = 5
    day = 5
    sentence = "It is Cinco de Mayo"


@static_predicate
class Solstice(Terms):
    def applies_in_context(self, context):
        context_date = context.date
        return context_date.day == 21 and (
            context_date.month == 6 or context_date.month == 12
        )

    sentence = "It is Solstice"


@static_predicate
class Friday13(Terms):
    sentence = "It is Friday the Thirteenth"

    def applies_in_context(self, context):
        context_date = context.date
        return context_date.day == 13 and context_date.isoweekday() == 5


class Birthday(Date):
    def __init__(self, birth_date, name, age):
        self.year = birth_date.year
        self.month = birth_date.month
        self.day = birth_date.day
        super(Birthday, self).__init__()
        self.sentence = "It is {name}'s birthday."

    def applies_to_song(self, song):
        if self.year == song.get_year():
            return True

        return super(Birthday, self).applies_to_song(song)
