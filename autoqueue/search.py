from datetime import datetime

mar_21 = lambda year: datetime(year, 3, 21)
jun_21 = lambda year: datetime(year, 6, 21)
sep_21 = lambda year: datetime(year, 9, 21)
dec_21 = lambda year: datetime(year, 12, 21)


class Search(object):

    multiples = True
    search_terms = tuple()
    tag_only_terms = tuple()

    def __init__(self, terms, multiples=True):
        self.search_terms = terms
        self.multiples = multiples

    @classmethod
    def from_string(cls, term, multiples=True):
        return cls(tuple(term), multiples)

    @classmethod
    def get_search_terms(cls):
        return cls.search_terms

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


class TimeSearch(Search):

    non_exclusive_terms = tuple()

    @classmethod
    def applies(cls, date):
        return date.day == cls.day and date.month == cls.month

    @classmethod
    def get_search_terms(cls):
        if cls.applies:
            return cls.search_terms + cls.non_exclusive_terms

        return cls.search_terms

    @classmethod
    def get_search_expressions_for_date(cls, date):
        if cls.applies(date):
            return cls.get_search_expressions()

        return []

    @classmethod
    def get_negative_search_expressions_for_date(cls, date):
        if cls.applies(date):
            return []
        return cls.get_negative_search_expressions()


class Winter(Search):

    search_terms = ('winter', 'wintertime')

    @staticmethod
    def applies(date, southern_hemisphere):
        if (date >= dec_21(date.year) or date <= mar_21(date.year)
                and not southern_hemisphere):
            return True

        if (date >= jun_21(date.year) and date <= sep_21(date.year)
                and southern_hemisphere):
            return True

        return False


class Spring(Search):

    search_terms = ('spring', 'springtime')

    @staticmethod
    def applies(date, southern_hemisphere):
        if (date >= mar_21(date.year) and date <= jun_21(date.year)
                and not southern_hemisphere):
            return True

        if (date >= sep_21(date.year) and date <= dec_21(date.year)
                and southern_hemisphere):
            return True

        return False


class Summer(Search):

    search_terms = ('summer', 'summertime')

    @staticmethod
    def applies(date, southern_hemisphere):
        if (date >= jun_21(date.year) and date <= sep_21(date.year)
                and not southern_hemisphere):
            return True

        if (date >= dec_21(date.year) or date <= mar_21(date.year)
                and southern_hemisphere):
            return True

        return False


class Autumn(Search):

    search_terms = ('autumn',)
    tag_only_terms = ('fall',)

    @staticmethod
    def applies(date, southern_hemisphere):
        if (date >= sep_21(date.year) and date <= dec_21(date.year)
                and not southern_hemisphere):
            return True

        if (date >= mar_21(date.year) and date <= jun_21(date.year)
                and southern_hemisphere):
            return True

        return False


SEASONS = [Winter, Spring, Summer, Autumn]


def get_season_search(date, southern_hemisphere=False):
    for season in SEASONS:
        if season.applies(date, southern_hemisphere):
            return season


def get_negative_season_searches(date, positive, southern_hemisphere=False):
    return [season for season in SEASONS if season is not positive]


class January(Search):

    search_terms = ('january',)


class February(Search):

    search_terms = ('february',)


class March(Search):

    tag_only_terms = ('march',)


class April(Search):

    search_terms = ('april',)


class May(Search):

    tag_only_terms = ('may',)


class June(Search):

    search_terms = ('june',)


class July(Search):

    search_terms = ('july',)


class August(Search):

    search_terms = ('august',)


class September(Search):

    search_terms = ('september',)


class October(Search):

    search_terms = ('october',)


class November(Search):

    search_terms = ('november',)


class December(Search):

    search_terms = ('december',)


MONTHS = [
    January, February, March, April, May, June, July, August,
    September, October, November, December]


class Monday(Search):

    search_terms = ('monday',)


class Tuesday(Search):

    search_terms = ('tuesday',)


class Wednesday(Search):

    search_terms = ('wednesday',)


class Thursday(Search):

    search_terms = ('thursday',)


class Friday(Search):

    search_terms = ('friday',)


class Saturday(Search):

    search_terms = ('saturday',)


class Sunday(Search):

    search_terms = ('sunday',)


DAYS = [
    Monday, Tuesday, Wednesday, Thursday, Friday, Saturday, Sunday]


def get_day_search(date):
    return DAYS[date.isoweekday() - 1]


def get_negative_day_searches(date, positive):
    return [day for day in DAYS if day is not positive]


class Night(Search):

    search_terms = ('night')

    @staticmethod
    def applies(date):
        return date.hour >= 21 or date.hour < 4


class Evening(Search):

    search_terms = ('evening')

    @staticmethod
    def applies(date):
        return date.hour >= 18 and date.hour < 21


class Morning(Search):

    search_terms = ('morning',)

    @staticmethod
    def applies(date):
        return date.hour >= 4 and date.hour < 12


class Afternoon(Search):

    search_terms = ('afternoon',)

    @staticmethod
    def applies(date):
        return date.hour >= 12 and date.hour < 18


TIMES = [Evening, Morning, Afternoon, Night]


class Weekend(Search):

    search_terms = ('weekend',)


def get_time_of_day_search(date):
    for time_of_day in TIMES:
        if time_of_day.applies(date):
            return time_of_day


def get_negative_time_of_day_searches(date, positive):
    return [
        time_of_day for time_of_day in TIMES if time_of_day is not positive]


def get_month_search(date):
    return MONTHS[date.month - 1]


def get_negative_month_searches(date, positive):
    return [month for month in MONTHS if month is not positive]


def get_location_searches(location):
    if not location:
        return []

    return [
        Search.from_string(name.strip().lower())
        for name in location.split(',')]


def get_searches(terms, multiples=True):
    return [Search.from_string(term, multiples) for term in terms]


class Christmas(TimeSearch):

    search_terms = ('christmas', 'santa claus', 'xmas')

    non_exclusive_terms = (
        'reindeer', 'sled', 'santa', 'snow', 'bell', 'jesus', 'eggnoc',
        'mistletoe', 'carol', 'nativity', 'mary', 'joseph', 'manger')

    @classmethod
    def applies(cls, date):
        return date.month == 12 and date.day >= 20 and date.day <= 29


class Kwanzaa(TimeSearch):

    search_terms = ('kwanzaa',)

    @classmethod
    def applies(cls, date):
        return (date.month == 12 and date.day >= 26) or (
            date.month == 1 and date.day == 1)


class NewYear(TimeSearch):

    search_terms = ('new year',)

    @classmethod
    def applies(cls, date):
        return (date.month == 12 and date.day >= 27) or (
            date.month == 1 and date.day <= 7)


class Halloween(TimeSearch):

    search_terms = ('halloween', 'hallowe\'en', 'all hallow\'s')
    non_exclusive_terms = (
        'haunt', 'haunting', 'haunted', 'ghost', 'monster', 'horror', 'devil',
        'witch', 'pumkin', 'bone', 'skeleton', 'ghosts', 'zombie', 'werewolf',
        'werewolves', 'vampire', 'evil', 'scare', 'scary', 'scaring', 'fear',
        'fright', 'blood', 'bat', 'dracula', 'spider', 'costume', 'satan',
        'hell', 'undead', 'dead', 'death', 'grave')

    @classmethod
    def applies(cls, date):
        return (date.month == 10 and date.day >= 25) or (
            date.month == 11 and date.day < 2)


class EasterBased(TimeSearch):

    @classmethod
    def applies(cls, date):
        easter = EASTERS[date.year]
        if cls.easter_offset(date, easter):
            return True

        return False

    @classmethod
    def easter_offset(cls, date, easter):
        return (date - easter).days == cls.days_after_easter


class Easter(EasterBased):

    search_terms = ('easter',)
    non_exclusive_terms = ('egg', 'bunny', 'bunnies', 'rabbit')

    @classmethod
    def easter_offset(cls, date, easter):
        return abs(date - easter).days < 5


class MardiGras(EasterBased):

    search_terms = ('mardi gras', 'shrove tuesday', 'fat tuesday')
    days_after_easter = -47


class AshWednesday(EasterBased):

    search_terms = ('ash wednesday',)
    non_exclusive_terms = ('ash',)
    days_after_easter = -46


class PalmSunday(EasterBased):

    search_terms = ('palm sunday',)
    non_exclusive_terms = ('palms',)
    days_after_easter = -7


class MaundyThursday(EasterBased):

    search_terms = ('maundy thursday',)
    days_after_easter = -3


class GoodFriday(EasterBased):

    search_terms = ('good friday',)
    days_after_easter = -2


class Ascension(EasterBased):

    search_terms = ('ascension',)
    days_after_easter = 39


class Pentecost(EasterBased):

    search_terms = ('pentecost',)
    days_after_easter = 49


class WhitMonday(EasterBased):

    search_terms = ('whit monday',)
    days_after_easter = 50


class AllSaints(EasterBased):

    search_terms = ('all saints',)
    days_after_easter = 56


class VeteransDay(TimeSearch):

    search_terms = ('armistice day', 'veterans day')
    non_exclusive_terms = ('peace', 'armistice', 'veteran')
    month = 11
    day = 11


class Assumption(TimeSearch):

    search_terms = ('assumption',)
    month = 8
    day = 15


class IndependenceDay(TimeSearch):

    search_terms = ('independence day',)
    non_exclusive_terms = (
        'independence', 'united states', 'independant', 'usa', 'u.s.a.')
    month = 7
    day = 4


class GroundhogDay(TimeSearch):

    search_terms = ('groundhog day',)
    non_exclusive_terms = ('groundhog',)
    month = 2
    day = 2


class ValentinesDay(TimeSearch):

    search_terms = ('valentine',)
    non_exclusive_terms = ('heart', 'love')
    month = 2
    day = 14


class AprilFools(TimeSearch):

    search_terms = ('april fool',)
    non_exclusive_terms = ('prank', 'joke', 'fool', 'hoax')
    month = 4
    day = 1


class CincoDeMayo(TimeSearch):

    search_terms = ('cinco de mayo',)
    non_exclusive_terms = ('mexico',)
    month = 5
    day = 5


class Solstice(TimeSearch):

    search_terms = ('solstice',)

    @classmethod
    def applies(cls, date):
        return date.day == 21 and (date.month == 6 or date.month == 12)


class Friday13(TimeSearch):

    search_terms = ('friday the 13th',)
    non_exclusive_terms = ('bad luck', 'superstition')

    @classmethod
    def applies(cls, date):
        return date.day == 13 and date.isoweekday() == 5


class BirthdaySearch(TimeSearch):

    def __init__(self, year, month, day, name):
        self.non_exclusive_terms = ('birthday', name)
        self.year = year
        self.month = month
        self.day = day

    def get_search_expressions(self):
        searches = super(BirthdaySearch, self).get_search_expressions()
        return searches + [
            'grouping=%s' % self.year,
            '~year=%d' % self.year]

    def get_search_expressions_for_date(self, date):
        searches = super(BirthdaySearch, self).get_search_expressions_for_date(
            date)
        return searches + ['grouping="%s"' % (date.year - self.year)]


def get_birthday_searches(birthdays, date):
    if not birthdays:
        return []

    if not ':' in birthdays:
        return []

    searches = []
    for name_date in birthdays.split(','):
        name, bdate = name_date.strip().split(':')
        bdate = bdate.strip()
        if '-' in bdate:
            bdate = [int(i) for i in bdate.split('-')]
        else:
            bdate = [int(i) for i in bdate.split('/')]
        if len(bdate) == 3:
            if date.month == bdate[-2] and date.day == bdate[-1]:
                searches.append(
                    BirthdaySearch(bdate[0], bdate[1], bdate[2], name))
    return searches


HOLIDAYS = (
    Christmas, Kwanzaa, NewYear, Halloween, Easter, MardiGras, AshWednesday,
    PalmSunday, MaundyThursday, GoodFriday, Ascension, Pentecost, WhitMonday,
    AllSaints, VeteransDay, Assumption, IndependenceDay, GroundhogDay,
    ValentinesDay, AprilFools, CincoDeMayo, Solstice, Friday13)

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
