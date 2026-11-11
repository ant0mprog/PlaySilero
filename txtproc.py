import calendar
import os
import re
import sys
from num2words import num2words

from textio import InputError, read_text_file

MONTHS_GENITIVE = {
    1: "января",
    2: "февраля",
    3: "марта",
    4: "апреля",
    5: "мая",
    6: "июня",
    7: "июля",
    8: "августа",
    9: "сентября",
    10: "октября",
    11: "ноября",
    12: "декабря",
}

YEAR_SUFFIX_CASE = {
    "год": "n",
    "года": "g",
    "году": "p",
    "годом": "i",
    "годе": "p",
    "годы": "n",
    "годов": "g",
    "годах": "p",
    "годами": "i",
    "годам": "d",
    "г.": "g",
    "г": "g",
    "гг.": "n",
}

PREPOSITION_CASE = {
    "в": "p",
    "во": "p",
    "о": "p",
    "об": "p",
    "обо": "p",
    "при": "p",
    "к": "d",
    "ко": "d",
    "по": "d",
    "с": "g",
    "со": "g",
    "до": "g",
    "после": "g",
    "из": "g",
    "от": "g",
    "для": "g",
    "за": "a",
    "на": "a",
    "про": "a",
    "через": "a",
    "под": "a",
    "над": "i",
    "перед": "i",
    "между": "i",
    "около": "g",
    "без": "g",
    "кроме": "g",
    "вне": "g",
    "внутри": "g",
    "вокруг": "g",
    "в течение": "g",
    "насчёт": "g",
    "насчет": "g",
}

# Длинные раньше коротких: «во» не должно съедаться как «в».
YEAR_PREPOSITIONS = (
    "в течение|насчёт|насчет|вокруг|внутри|около|кроме|между|перед|после|"
    "через|обо|об|во|ко|со|для|при|под|над|без|вне|до|от|из|по|на|за|про|в|к|о|с"
)

ACRONYMS = {
    "vpn": "ви-пи-эн",
    "ras": "рас",
    "http": "эйч-ти-ти-пи",
    "https": "эйч-ти-ти-пи-эс",
    "www": "ввв",
    "usa": "ю-эс-эй",
    "usb": "ю-эс-би",
    "cpu": "цп-у",
    "gpu": "гп-у",
    "ssd": "эс-эс-ди",
    "hdd": "эйч-ди-ди",
    "ip": "айпи",
    "tv": "ти-ви",
    "ai": "ай",
    "it": "ай-ти",
    "ok": "окей",
    "isw": "ай-эс-дабл-ю",
}

LATIN_DIGRAPHS = (
    ("sch", "щ"),
    ("sh", "ш"),
    ("ch", "ч"),
    ("zh", "ж"),
    ("yo", "ё"),
    ("yu", "ю"),
    ("ya", "я"),
    ("ye", "е"),
    ("ph", "ф"),
    ("th", "т"),
    ("kh", "х"),
)

LATIN_LETTERS = {
    "a": "а",
    "b": "б",
    "c": "к",
    "d": "д",
    "e": "е",
    "f": "ф",
    "g": "г",
    "h": "х",
    "i": "и",
    "j": "дж",
    "k": "к",
    "l": "л",
    "m": "м",
    "n": "н",
    "o": "о",
    "p": "п",
    "q": "к",
    "r": "р",
    "s": "с",
    "t": "т",
    "u": "у",
    "v": "в",
    "w": "в",
    "x": "кс",
    "y": "й",
    "z": "з",
}

# Имена латинских букв. Неизвестные ALLCAPS и «F-16» читаются ими, не транслитом.
LATIN_LETTER_NAME = {
    "a": "эй",
    "b": "би",
    "c": "си",
    "d": "ди",
    "e": "и",
    "f": "эф",
    "g": "джи",
    "h": "эйч",
    "i": "ай",
    "j": "джей",
    "k": "кей",
    "l": "эл",
    "m": "эм",
    "n": "эн",
    "o": "оу",
    "p": "пи",
    "q": "кью",
    "r": "ар",
    "s": "эс",
    "t": "ти",
    "u": "ю",
    "v": "ви",
    "w": "дабл-ю",
    "x": "экс",
    "y": "уай",
    "z": "зед",
}

# Не больше трёх групп после первой (максимум 12 цифр) и дробь не длиннее 12 знаков:
# выше num2words падает, а ряды вроде «100 200 300 …» склеивались в одно число.
MAX_GROUPED_DIGITS = 12
NUM_TOKEN = (
    r"(?:\d{1,3}(?:[ \u00a0]\d{3}){1,3}(?:[.,]\d{1,12})?|\d+(?:[.,]\d{1,12})?)"
)

URL_RE = re.compile(r"(?i)\(?\b(?:https?://|www\.)[^\s<>)]+\)?")
EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
IP_RE = re.compile(
    r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d{1,2})\.){3}(?:25[0-5]|2[0-4]\d|1?\d{1,2})\b"
)
_VERSION_BEFORE_RE = re.compile(
    r"(?i)(?:верси(?:я|и|ю|ей)|сборк(?:а|и|е|у)|релиз(?:а|е|у)?|"
    r"release|version|ver\.?|(?:^|[^A-Za-z])v)\s*:?\s*$"
)
DATE_DMY_RE = re.compile(r"\b(\d{1,2})([./-])(\d{1,2})\2(\d{4})\b")
DATE_YMD_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
TIME_HMS_RE = re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d):([0-5]\d)\b")
TIME_HM_RE = re.compile(
    r"(?i)\b(в|ко|к|около|ровно|до|с)\s+([01]?\d|2[0-3]):([0-5]\d)\b(?!\s*[xх×:])"
)
DOT_TIME_RE = re.compile(
    r"(?i)\b(в|к|ко|около|ровно)\s+([01]?\d|2[0-3])\.([0-5]\d)\b"
)
YEAR_RANGE_RE = re.compile(
    rf"(?i)(?:(?P<pre>\b(?:{YEAR_PREPOSITIONS})\s+))?"
    r"(?P<y1>19\d{2}|20\d{2})\s*[-–—]\s*(?P<y2>19\d{2}|20\d{2})"
    r"(?:\s*(?P<suf>годам|годами|годах|годов|года|году|годом|годе|годы|год|гг\.|г\.|г(?![\w.])))?"
)
FROM_TO_RE = re.compile(
    r"(?i)\bс\s+((?:19|20)\d{2})(?:\s+(?:года|году|год|г\.))?\s+по\s+"
    r"((?:19|20)\d{2})(?:\s+(?P<suf>годом|годах|годов|года|году|годе|годы|год|г\.))?"
)
YEAR_ORDINAL_ENDINGS = (
    "ыми|ими|ого|его|ому|ему|ых|их|ые|ие|ый|ий|ой|ая|ое|"
    "го|му|ми|й|е|м|х|ю"
)
YEAR_RE = re.compile(
    rf"(?i)(?:(?P<pre>\b(?:{YEAR_PREPOSITIONS})\s+))?"
    r"(?P<year>\b(?:19|20)\d{2})"
    rf"(?:-(?P<ord>{YEAR_ORDINAL_ENDINGS}))?"
    r"(?:\s*(?P<suf>годам|годами|годах|годов|года|году|годом|годе|годы|год|гг\.|г\.|г(?![\w.])))?"
)
SHORT_DECADE_GG_RE = re.compile(
    rf"(?i)(?:(?P<pre>\b(?:{YEAR_PREPOSITIONS})\s+))?"
    r"(?<!\d)(?P<num>\d{1,3})-(?P<ord>ые|ых|ие|их|е|х)\s+гг\."
)
BETWEEN_YEARS_RE = re.compile(
    r"(?i)\bмежду\s+((?:19|20)\d{2})\s+и\s+((?:19|20)\d{2})\b"
)
LIST_RE = re.compile(r"(?m)^\s*(\d{1,2})[.)]\s+")
ORDINAL_RE = re.compile(
    r"(?<!\d)(\d{1,3}(?:[ \u00a0]\d{3})+|\d+)-(й|ый|ий|ой|ая|я|ое|ье|е|го|му|ми|м|х|ю)\b",
    re.IGNORECASE,
)
CURRENCY_BEFORE_RE = re.compile(rf"([$€₽])\s*({NUM_TOKEN})")
BIG_UNIT_RE = re.compile(
    rf"(?<!\d)([$€₽]?\s*{NUM_TOKEN})\s*(млн|млрд)\b(?:\s*(руб\.?|[$€₽](?!\s*\d)))?",
    re.IGNORECASE,
)
UNIT_RE = re.compile(
    rf"(?<!\d)({NUM_TOKEN})\s*"
    # Порядок альтернатив важен: «°C» до «°», «км/ч» до «км», «Вт» до «В».
    r"(°C|%|\$|€|₽|руб\.?|кг|шт\.?|км|га|Вт|В|л|см|мм|мг|мин|сек|сот\.|т\.?|°|ч|м|г)(?!\w)",
    re.IGNORECASE,
)
# Надстрочные единицы: «5 км²» писать словами проще, чем объяснять моделью.
# «(?![А-Яа-яЁё])» отделяет единицу от слова: «5 км²» — это единица, а «м² в
# квадрате» — уже нет. Точка и запятая после знака мешать не должны.
SUPERSCRIPT_UNIT_RE = re.compile(
    rf"(?<!\d)({NUM_TOKEN})\s*(км|м|см|дм)?([²³])(?![А-Яа-яЁё])"
)
# °C иначе озвучивалось как «°к»: кириллическая «к» не была ни буквой, ни единицей.
DEGREE_C_RE = re.compile(rf"(?<!\d)({NUM_TOKEN})\s*°\s*[Cc](?!\w)")
# Градус после слова: «нагрев до минус пяти °C» — число к этому шагу уже слово,
# цифрового шаблона нет, и «°C» озвучивалось как «°к».
# «(?<= )» обязателен: иначе жадная буква съедает предлог («до пяти °C» →
# «додвадцати»), а знак «минус» к этому шагу уже стал словом.
DEGREE_C_WORDS_RE = re.compile(r"(?<=\s)([А-Яа-яЁё]+)\s*°\s*[Cc](?!\w)")
# Скорость: «40 км/ч» → «сорок километров в час». До UNIT_RE, иначе съест «км».
KMPH_RE = re.compile(rf"(?<!\d)({NUM_TOKEN})\s*(?:км|Км)/\s*ч(?!\w)")
# T9.4: после слов ИНН/КПП/СНИЛС/ОГРН число — идентификатор, а не количество:
# «ИНН 7707083893» читают по одной цифре. Дефисы и пробелы внутри номера допустимы.
ID_KEYWORD = r"(?:ИНН|КПП|СНИЛС|ОГРН)"
ID_NUMBER_RE = re.compile(rf"(?i)\b({ID_KEYWORD})\s+([\d](?:[\d \u00a0-]{{6,22}}\d))")
THOUSANDS_RE = re.compile(
    r"(?<!\d)(\d{1,3}(?:[ \u00a0]\d{3}){1,3})(?:[.,](\d{1,12}))?(?!\d)"
)
DECIMAL_RE = re.compile(r"(?<![\d.,])(\d+)[,.](\d+)(?![\d.,])")
ENUM_RE = re.compile(r"(?<![\d.,])\d+(?:\s*,\s*\d+){2,}(?![\d.,])")
PHONE_RE = re.compile(r"(?<!\w)\+\d[\d\-\s()]{9,}\d")
FRAC_RE = re.compile(r"(?<!\d)(\d{1,2})\s*/\s*(\d{1,2})(?!\d)")
ANNIV_RE = re.compile(
    r"(?<!\d)(\d{1,4})-(летие|летия|летию|летием|летии)\b",
    re.IGNORECASE,
)
LATIN_MODEL_RE = re.compile(r"\b([A-Za-z])-(\d+)\b")
LATIN_NUM_RE = re.compile(r"\b([A-Za-z]+)(\d+)\b")
NUM_LATIN_RE = re.compile(r"\b(\d+)([A-Za-z]+)\b")
NUMBER_RE = re.compile(r"\d+")
LATIN_WORD_RE = re.compile(r"[A-Za-z]+")
_ROMAN_OK = re.compile(
    r"M{0,3}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})"
)
ROMAN_RE = re.compile(
    r"(?:(?P<pre>[А-Яа-яЁё]+)\s+)?"
    r"(?<![A-Za-z0-9])(?P<rom>[IVXLCDM]+)(?![A-Za-z0-9])"
    r"(?:\s+(?P<post>[А-Яа-яЁё]+))?"
)


def ru_num(n, to="cardinal", **kwargs) -> str:
    return num2words(n, lang="ru", to=to, **kwargs)


def _decimal_by_digits(whole: str, frac: str) -> str:
    """Запасной путь без float: длинная дробь иначе роняет num2words."""
    n = int(whole or "0")
    if n == 0:
        whole_words, cel = "ноль", "целых"
    elif n % 10 == 1 and n % 100 != 11:
        whole_words = ru_num(n, gender="f") if n < 1000 else ru_num(n)
        cel = "целая"
    elif n % 10 == 2 and n % 100 != 12 and n < 100:
        whole_words, cel = ru_num(n, gender="f"), "целых"
    else:
        whole_words, cel = ru_num(n), "целых"
    frac_words = " ".join(ru_num(int(ch)) for ch in frac)
    return f"{whole_words} {cel} {frac_words}"


def decimal_words(whole: str, frac: str) -> str:
    """Дробь по записанным цифрам, без float. Миллион не становится «одна миллион»."""
    if len(frac) > 12 or len(whole) > 15:
        return _decimal_by_digits(whole, frac)
    try:
        if int(whole) >= 1_000_000:
            tail = ru_num(f"0.{frac}")
            tail = tail.split(" целых ", 1)[-1]
            return f"{ru_num(int(whole))} целых {tail}"
        return ru_num(f"{whole}.{frac}")
    except (ValueError, OverflowError):
        return _decimal_by_digits(whole, frac)


def ru_plural(n: int, one: str, few: str, many: str) -> str:
    n = abs(int(n)) % 100
    if 11 <= n <= 14:
        return many
    n %= 10
    if n == 1:
        return one
    if 2 <= n <= 4:
        return few
    return many


def is_valid_date(day: int, month: int, year: int) -> bool:
    if not (1 <= month <= 12 and 1 <= year <= 9999):
        return False
    try:
        last = calendar.monthrange(year, month)[1]
    except calendar.IllegalMonthError:
        return False
    return 1 <= day <= last


def speak_dotted(parts) -> str:
    spoken = []
    for token in parts:
        if len(token) > 1 and token.startswith("0"):
            spoken.append(" ".join(ru_num(int(ch)) for ch in token))
        else:
            spoken.append(ru_num(int(token)))
    return " точка ".join(spoken)


def date_to_words(day: int, month: int, year: int) -> str:
    day_words = ru_num(day, to="ordinal", gender="n")
    year_words = ru_num(year, to="ordinal", case="g")
    return f"{day_words} {MONTHS_GENITIVE[month]} {year_words} года"


def time_to_words(hour: int, minute: int, second=None) -> str:
    parts = [
        f"{ru_num(hour)} {ru_plural(hour, 'час', 'часа', 'часов')}",
        f"{ru_num(minute)} {ru_plural(minute, 'минута', 'минуты', 'минут')}",
    ]
    if second is not None:
        parts.append(
            f"{ru_num(second)} {ru_plural(second, 'секунда', 'секунды', 'секунд')}"
        )
    return " ".join(parts)


def year_to_words(year: int, case: str = "n", plural: bool = False) -> str:
    # animate=False: винительный муж. совпадает с именительным («на … третий год»)
    return ru_num(
        year, to="ordinal", case=case, gender="m", plural=plural, animate=False
    )


# «году» — и дательный, и предложный; падеж берём у предлога.
AMBIGUOUS_YEAR_SUFFIXES = {"году"}
PLURAL_YEAR_SUFFIXES = {"годы", "годов", "годах", "годами", "годам"}
# «в 1990-е» без существительного читается как «в девяностые», не «в девяностых».
ACCUSATIVE_LOOKALIKE_PREPOSITIONS = {"в", "во", "на", "за", "про", "через", "под"}


ORDINAL_ENDING_CASE = {
    "й": ("n", False),
    "ый": ("n", False),
    "ий": ("n", False),
    "ой": ("n", False),
    "ая": ("n", False),
    "ое": ("n", False),
    "е": ("n", True),
    "ие": ("n", True),
    "ые": ("n", True),
    "х": ("g", True),
    "ых": ("g", True),
    "их": ("g", True),
    "го": ("g", False),
    "ого": ("g", False),
    "его": ("g", False),
    "му": ("d", False),
    "ому": ("d", False),
    "ему": ("d", False),
    "м": ("p", False),
    "ми": ("i", True),
    "ыми": ("i", True),
    "ими": ("i", True),
    "ю": ("a", False),
}


def year_inflection(pre, suf, ord_sfx):
    pre_l = (pre or "").strip().lower()
    suf_l = (suf or "").strip().lower()
    ord_l = (ord_sfx or "").lower()
    ord_case, ord_plural = ORDINAL_ENDING_CASE.get(ord_l, (None, False))
    if suf_l == "гг.":
        # «1990-е гг.» — именительный «годы»; «-х» при «в» — «годах».
        if ord_l in {"е", "ые", "ие"}:
            return "n", True
        if ord_l in {"х", "ых", "их"}:
            if pre_l in {"в", "во", "о", "об", "обо", "при", "на"}:
                return "p", True
            return "g", True
        return "n", True
    if suf_l and suf_l not in AMBIGUOUS_YEAR_SUFFIXES:
        case = YEAR_SUFFIX_CASE.get(suf_l, "n")
        plural = suf_l in PLURAL_YEAR_SUFFIXES or ord_plural
    elif suf_l == "году":
        case = PREPOSITION_CASE.get(pre_l, "p") if pre_l else "p"
        plural = False
    elif ord_case and pre_l in ACCUSATIVE_LOOKALIKE_PREPOSITIONS and ord_l in {"е", "ие", "ые"}:
        case, plural = "n", True
    elif ord_case and pre_l and ord_l in {"х", "ых", "их"}:
        case, plural = "p", True
    elif ord_case and not pre_l:
        case, plural = ord_case, ord_plural
    elif pre_l:
        case = PREPOSITION_CASE.get(pre_l, "n")
        plural = ord_plural
    else:
        case, plural = "n", ord_plural
    return case, plural


def ends_sentence(text: str, pos: int) -> bool:
    """Точка сокращения была концом фразы: конец строки или пробел и заглавная."""
    rest = text[pos:]
    if re.match(r"[ \t]*$", rest):
        return True
    if re.match(r"[ \t]*\n", rest):
        return True
    if re.match(r"[ \t]+[А-ЯЁ]", rest):
        return True
    return False


def replace_ips(text: str) -> str:
    def repl(match):
        before = text[max(0, match.start() - 40) : match.start()]
        if _VERSION_BEFORE_RE.search(before):
            return match.group(0)
        return "айпи-адрес"

    return IP_RE.sub(repl, text)


def replace_dates(text: str) -> str:
    def dmy(match):
        day_s, _sep, month_s, year_s = match.groups()
        day, month, year = int(day_s), int(month_s), int(year_s)
        if not is_valid_date(day, month, year):
            return speak_dotted((day_s, month_s, year_s))
        return date_to_words(day, month, year)

    def ymd(match):
        year_s, month_s, day_s = match.groups()
        year, month, day = int(year_s), int(month_s), int(day_s)
        if not is_valid_date(day, month, year):
            return speak_dotted((year_s, month_s, day_s))
        return date_to_words(day, month, year)

    text = DATE_DMY_RE.sub(dmy, text)
    text = DATE_YMD_RE.sub(ymd, text)
    return text


def replace_times(text: str) -> str:
    def colon_repl(match):
        hour = int(match.group(1))
        minute = int(match.group(2))
        second = match.group(3)
        second = int(second) if second is not None else None
        return time_to_words(hour, minute, second)

    def hm_repl(match):
        pre = match.group(1)
        return f"{pre} {time_to_words(int(match.group(2)), int(match.group(3)))}"

    def dot_repl(match):
        pre = match.group(1)
        return f"{pre} {time_to_words(int(match.group(2)), int(match.group(3)))}"

    text = DOT_TIME_RE.sub(dot_repl, text)
    text = TIME_HMS_RE.sub(colon_repl, text)
    return TIME_HM_RE.sub(hm_repl, text)


def replace_phones(text: str) -> str:
    def repl(match):
        digits = re.sub(r"\D", "", match.group(0))
        if not 10 <= len(digits) <= 15:
            return match.group(0)
        if digits[0] == "7" and len(digits) == 11:
            groups = [digits[0], digits[1:4], digits[4:7], digits[7:9], digits[9:11]]
        else:
            groups = [digits[0]]
            rest = digits[1:]
            while rest:
                groups.append(rest[:3])
                rest = rest[3:]
        spoken = [" ".join(ru_num(int(ch)) for ch in group) for group in groups]
        return "плюс " + ", ".join(spoken)

    return PHONE_RE.sub(repl, text)


def expand_year_suffix(suf: str, case: str) -> str:
    """«г.» не оставлять с точкой: иначе silero10 режет фразу посередине."""
    low = suf.lower()
    if low == "гг.":
        return {
            "n": "годы",
            "g": "годов",
            "d": "годам",
            "a": "годы",
            "i": "годами",
            "p": "годах",
        }.get(case, "годы")
    if low in {"г.", "г"}:
        return {
            "n": "год",
            "g": "года",
            "d": "году",
            "a": "год",
            "i": "годом",
            "p": "году",
        }.get(case, "года")
    return suf


def _with_sentence_dot(spoken: str, suf: str, text: str, end: int) -> str:
    if suf and "." in suf and ends_sentence(text, end):
        return spoken + "."
    return spoken


def replace_years(text: str) -> str:
    # «2026 г.г.» — опечатка «г.»; «1990-е г.г.» — то же, что «гг.».
    text = re.sub(
        r"(?i)(\b(?:19|20)\d{2})\s+г\.г\.",
        r"\1 г.",
        text,
    )
    text = re.sub(r"(?i)(?<!\w)г\.г\.", "гг.", text)

    def from_to_repl(match):
        left = year_to_words(int(match.group(1)), "g")
        suf = match.group("suf")
        if suf and suf.lower() not in {"год", "г.", "г"}:
            case, _plural = year_inflection("", suf, "")
            right = year_to_words(int(match.group(2)), case, plural=False)
            spoken = _with_sentence_dot(
                expand_year_suffix(suf, case), suf, match.string, match.end()
            )
            return f"с {left} по {right} {spoken}"
        right = year_to_words(int(match.group(2)), "a")
        if suf:
            spoken = _with_sentence_dot(
                expand_year_suffix(suf, "n"), suf, match.string, match.end()
            )
            return f"с {left} по {right} {spoken}"
        return f"с {left} по {right}"

    def range_repl(match):
        pre = match.group("pre")
        suf = match.group("suf")
        if suf:
            case, _plural = year_inflection(pre, suf, "")
        elif pre:
            case = PREPOSITION_CASE.get(pre.strip().lower(), "n")
        else:
            case = "g"
        w1 = year_to_words(int(match.group("y1")), case, plural=False)
        w2 = year_to_words(int(match.group("y2")), case, plural=False)
        parts = []
        if pre:
            parts.append(pre.strip())
        parts.append(f"{w1} — {w2}")
        if suf:
            parts.append(
                _with_sentence_dot(
                    expand_year_suffix(suf, case), suf, match.string, match.end()
                )
            )
        return " ".join(parts)

    def between_repl(match):
        start = year_to_words(int(match.group(1)), "i")
        end = year_to_words(int(match.group(2)), "i")
        return f"между {start} и {end}"

    def decade_repl(match):
        pre = match.group("pre")
        number = int(match.group("num"))
        ord_sfx = match.group("ord")
        case, plural = year_inflection(pre, "гг.", ord_sfx)
        words = year_to_words(number, case, plural=plural)
        parts = []
        if pre:
            parts.append(pre.strip())
        parts.append(words)
        spoken = _with_sentence_dot(
            expand_year_suffix("гг.", case), "гг.", match.string, match.end()
        )
        parts.append(spoken)
        return " ".join(parts)

    text = FROM_TO_RE.sub(from_to_repl, text)
    text = YEAR_RANGE_RE.sub(range_repl, text)
    text = BETWEEN_YEARS_RE.sub(between_repl, text)
    text = SHORT_DECADE_GG_RE.sub(decade_repl, text)

    def year_repl(match):
        pre = match.group("pre")
        year = int(match.group("year"))
        suf = match.group("suf")
        ord_sfx = match.group("ord") or ""
        case, plural = year_inflection(pre, suf, ord_sfx)
        words = year_to_words(year, case, plural=plural)
        parts = []
        if pre:
            parts.append(pre.strip())
        parts.append(words)
        if suf:
            parts.append(
                _with_sentence_dot(
                    expand_year_suffix(suf, case), suf, match.string, match.end()
                )
            )
        return " ".join(parts)

    text = YEAR_RE.sub(year_repl, text)

    def short_year_repl(match):
        pre = match.group("pre")
        number = int(match.group("num"))
        suf = match.group("suf")
        case, plural = year_inflection(pre, suf, "")
        words = year_to_words(number, case, plural=plural)
        parts = []
        if pre:
            parts.append(pre.strip())
        parts.append(words)
        parts.append(suf)
        return " ".join(parts)

    text = re.sub(
        rf"(?i)(?:(?P<pre>\b(?:{YEAR_PREPOSITIONS})\s+))?"
        r"(?P<num>\b\d{1,3})\s+"
        r"(?P<suf>годами|годах|годов|года|году|годом|годе|годы|год)\b",
        short_year_repl,
        text,
    )
    # «гг.» без стоящего перед ним года не превращать в «годов».
    text = re.sub(r"(?i)(?<![\w])гг\.", "годы", text)
    return text


def replace_numeric_ranges(text: str) -> str:
    """Дефис между числами — пауза, не склейка слов. Годы к этому шагу уже слова."""
    text = re.sub(r"(?<=[%\d])\s*[-–—−]\s*(?=\d)", " — ", text)
    return text


def replace_signs(text: str) -> str:
    text = re.sub(r"±\s*(?=\d)", "плюс-минус ", text)
    text = re.sub(r"(?<![\w])[-−](?=\d)", "минус ", text)
    text = re.sub(r"№\s*(?=\d)", "номер ", text)
    return text


def replace_fractions(text: str) -> str:
    def repl(match):
        n, d = int(match.group(1)), int(match.group(2))
        if d == 0:
            return match.group(0)
        special = {
            (1, 2): "половина",
            (1, 3): "одна треть",
            (2, 3): "две трети",
            (1, 4): "одна четверть",
            (3, 4): "три четверти",
        }
        if (n, d) in special:
            return special[(n, d)]
        num = ru_num(n, gender="f")
        last = n % 100
        if last % 10 == 1 and last != 11:
            den = ru_num(d, to="ordinal", gender="f")
        else:
            den = ru_num(d, to="ordinal", gender="f", case="g", plural=True)
        return f"{num} {den}"

    return FRAC_RE.sub(repl, text)


def anniversary_stem(n: int) -> str:
    if n == 100:
        return "сто"
    if n == 1000:
        return "тысяче"
    stem = ru_num(n, case="g")
    if " " not in stem:
        return stem
    stem = stem.replace(" ", "")
    return stem.replace("одной", "одно").replace("одного", "одно").replace("одну", "одно")


def replace_anniversaries(text: str) -> str:
    def repl(match):
        n = int(match.group(1))
        ending = match.group(2).lower()
        return anniversary_stem(n) + ending

    return ANNIV_RE.sub(repl, text)


def replace_latin_model_numbers(text: str) -> str:
    def repl(match):
        name = LATIN_LETTER_NAME[match.group(1).lower()]
        return f"{name} {match.group(2)}"

    text = LATIN_MODEL_RE.sub(repl, text)

    def letter_before_digit(match):
        return LATIN_LETTER_NAME[match.group(1).lower()] + " "

    # «v1.2.3.4»: одиночная буква — именем, не фонетическим «в».
    return re.sub(r"\b([A-Za-z])(?=\d)", letter_before_digit, text)


def replace_list_markers(text: str) -> str:
    def repl(match):
        return ru_num(int(match.group(1)), to="ordinal").capitalize() + ". "

    return LIST_RE.sub(repl, text)


def replace_hyphen_ordinals(text: str) -> str:
    suffix_map = {
        "й": ("n", "m"),
        "ый": ("n", "m"),
        "ий": ("n", "m"),
        "ой": ("n", "m"),
        "я": ("n", "f"),
        "ая": ("n", "f"),
        "е": ("n", "n"),
        "ое": ("n", "n"),
        "ье": ("n", "n"),
        "го": ("g", "m"),
        "му": ("d", "m"),
        "м": ("p", "m"),
        "ю": ("a", "f"),
        "ми": ("i", "m"),
        "х": ("g", "m"),
    }

    def repl(match):
        number = int(re.sub(r"\D", "", match.group(1)))
        suffix = match.group(2).lower()
        # 90-е → девяностые (десятилетия), 2-е → второе
        if suffix == "е" and number >= 20 and number % 10 == 0:
            return ru_num(number, to="ordinal", plural=True)
        case, gender = suffix_map.get(suffix, ("n", "m"))
        plural = suffix in {"ми", "х"}
        return ru_num(
            number, to="ordinal", case=case, gender=gender, plural=plural
        )

    return ORDINAL_RE.sub(repl, text)


def _number_token(value: str) -> str:
    return value.replace("\u00a0", "").replace(" ", "").replace(",", ".")


def number_and_unit(value: str, unit_key: str) -> str:
    unit_key = unit_key.lower()
    if unit_key in {"руб.", "руб"}:
        unit_key = "руб"
    elif unit_key in {"шт.", "шт"}:
        unit_key = "шт"
    elif unit_key in {"сот.", "сот"}:
        unit_key = "сот"
    elif unit_key in {"т.", "т"}:
        unit_key = "т"
    value = _number_token(value)
    has_frac = "." in value
    if has_frac:
        whole, frac = value.split(".", 1)
        number_words = decimal_words(whole, frac)
        n_for_plural = int(whole or "0")
    else:
        n_for_plural = int(value)
        number_words = ru_num(n_for_plural)

    units = {
        "%": ("процент", "процента", "процентов"),
        "$": ("доллар", "доллара", "долларов"),
        "€": ("евро", "евро", "евро"),
        "₽": ("рубль", "рубля", "рублей"),
        "руб": ("рубль", "рубля", "рублей"),
        "кг": ("килограмм", "килограмма", "килограммов"),
        "шт": ("штука", "штуки", "штук"),
        "км": ("километр", "километра", "километров"),
        "м": ("метр", "метра", "метров"),
        "см": ("сантиметр", "сантиметра", "сантиметров"),
        "мм": ("миллиметр", "миллиметра", "миллиметров"),
        "г": ("грамм", "грамма", "граммов"),
        "мг": ("миллиграмм", "миллиграмма", "миллиграммов"),
        "ч": ("час", "часа", "часов"),
        "мин": ("минута", "минуты", "минут"),
        "сек": ("секунда", "секунды", "секунд"),
        "°": ("градус", "градуса", "градусов"),
        "сот": ("сотня", "сотни", "сотен"),
        "т": ("тонна", "тонны", "тонн"),
        # T9.2: единицы, которых в таблице не было.
        "га": ("гектар", "гектара", "гектаров"),
        "л": ("литр", "литра", "литров"),
        "вт": ("ватт", "ватта", "ватт"),
        "в": ("вольт", "вольта", "вольт"),
        "км/ч": ("километр в час", "километра в час", "километров в час"),
    }
    if unit_key == "°c":
        # «пять градусов Цельсия», «один градус Цельсия», «два градуса Цельсия».
        return f"{number_words} {ru_plural(n_for_plural, 'градус', 'градуса', 'градусов')} Цельсия"

    one, few, many = units[unit_key]
    # Дробь: «две целых пять десятых километра», не именительный по целой части 1.
    if has_frac:
        form = few
    else:
        form = ru_plural(n_for_plural, one, few, many)
    return f"{number_words} {form}"


def _scale_number(token: str, mult: int) -> int:
    token = _number_token(token)
    if "." not in token:
        return int(token) * mult
    whole, frac = token.split(".", 1)
    frac = "".join(ch for ch in frac if ch.isdigit())[:6]
    if not frac:
        return int(whole or "0") * mult
    scale = 10 ** len(frac)
    return int(whole or "0") * mult + int(frac) * mult // scale


# T9.1: надстрочные единицы. «5 км²» проще сказать словами, чем надеяться, что
# модель прочитает «км²»; °C иначе озвучивалось как «°к».
_SUPERSCRIPT_ADJ = {"²": ("квадратный", "квадратных"), "³": ("кубический", "кубических")}
_SUPERSCRIPT_NOUN = {
    "км": ("километр", "километра", "километров"),
    "м": ("метр", "метра", "метров"),
    "см": ("сантиметр", "сантиметра", "сантиметров"),
}


def _is_singular(n: int) -> bool:
    n = abs(int(n)) % 100
    return n % 10 == 1 and not 11 <= n <= 14


def _superscript_words(value: str, mark: str, base: str) -> str:
    """«5 км²» → «пять квадратных километров», «1 км²» → «один квадратный километр».

    Числительное берётся из `number_and_unit` (там уже есть падеж по счёту и
    чтение дробей), прилагательное и существительное подставляются в том же
    роде и числе: «ноль целых пять десятых кубического метра».
    """
    noun_key = base if base in _SUPERSCRIPT_NOUN else "м"
    forms = _SUPERSCRIPT_NOUN[noun_key]
    token = _number_token(value)

    if "." in token:
        number_words = number_and_unit(token, noun_key)      # «ноль целых пять десятых метра»
        head, _, tail = number_words.rpartition(" ")
        adjective = "квадратного" if mark == "²" else "кубического"
        return f"{head} {adjective} {tail}"

    count = int(token)
    number_words = number_and_unit(token, noun_key)          # «пять метров» / «один метр»
    head = number_words.rpartition(" ")[0] or number_words
    adjective = _SUPERSCRIPT_ADJ[mark][0] if _is_singular(count) else _SUPERSCRIPT_ADJ[mark][1]
    noun = forms[0] if _is_singular(count) else number_words.rpartition(" ")[2]
    return f"{head} {adjective} {noun}"


def replace_superscript_units(text: str) -> str:
    """T9.1: надстрочные ² и ³. Стоит после replace_units и до replace_thousands."""

    def repl(match):
        return _superscript_words(match.group(1), match.group(3), (match.group(2) or "").lower())

    return SUPERSCRIPT_UNIT_RE.sub(repl, text)


# T9.1: градус после слова. «до минус пяти °C» к этому шагу уже словесное, и
# цифровое правило до него не достаёт — на выходе оставалось «°к». Падеж
# числительного менять нельзя (его выбрал replace_years/replace_units), поэтому
# существительное ставим в родительный: «до пяти градусов Цельсия». Составные
# слова («двадцати», «сорока») перечислять невозможно — их не трогаем.
DEGREE_C_GENITIVE_WORDS = {
    # Именительный оставлен намеренно: «плюс пять °C» → «пяти градусов» ломает
    # согласование, такие формы обрабатывает цифровое правило DEGREE_C_RE.
    "ноль", "нуля", "пяти", "шести", "семи",
    "восьми", "девяти", "десяти", "одиннадцати", "двенадцати", "тринадцати",
    "четырнадцати", "пятнадцати", "шестнадцати", "семнадцати", "восемнадцати",
    "девятнадцати", "двадцати", "тридцати", "сорока", "пятидесяти",
    "шестидесяти", "семидесяти", "восьмидесяти", "девяноста", "ста", "одной",
}


def replace_degree_c_words(text: str) -> str:
    """«минус пяти °C» → «минус пяти градусов Цельсия», число не трогаем."""

    def repl(match):
        word = match.group(1)
        if word.lower() not in DEGREE_C_GENITIVE_WORDS:
            return match.group(0)
        return f"{word} градусов Цельсия"

    return DEGREE_C_WORDS_RE.sub(repl, text)


def replace_id_numbers(text: str) -> str:
    """T9.4: номера документов читаются по одной цифре («семь семь ноль семь …»)."""

    def repl(match):
        keyword, digits = match.group(1), match.group(2)
        words = " ".join(ru_num(int(ch)) for ch in re.sub(r"\D", "", digits))
        return f"{keyword} {words}"

    return ID_NUMBER_RE.sub(repl, text)


def replace_units(text: str) -> str:
    def big_repl(match):
        mult = 1_000_000_000 if match.group(2).lower() == "млрд" else 1_000_000
        lead = match.group(1)
        cur = (match.group(3) or "").lower()
        # Знак вырезаем до int(): иначе int("$5") падает.
        value = _scale_number(re.sub(r"[$€₽]\s*", "", lead.strip()), mult)
        if not cur and lead.strip()[:1] in {"$", "€", "₽"}:
            cur = lead.strip()[:1]
        # Пробел перед числом ("выручка 1,5 млрд ₽") сохраняем, иначе слова слипнутся.
        space = " " if lead[:1].isspace() else ""
        if cur:
            return space + number_and_unit(str(value), "руб" if cur.startswith("руб") else cur)
        return space + ru_num(value)

    text = BIG_UNIT_RE.sub(big_repl, text)
    text = CURRENCY_BEFORE_RE.sub(
        lambda m: number_and_unit(m.group(2), m.group(1)), text
    )

    def repl(match):
        return number_and_unit(match.group(1), match.group(2))

    return UNIT_RE.sub(repl, text)


def replace_thousands(text: str) -> str:
    def repl(match):
        whole = re.sub(r"\D", "", match.group(1))
        frac = match.group(2)
        if frac:
            return decimal_words(whole, frac)
        # Страховка: классы выше 10^60 у num2words кончаются, читаем по цифре.
        if len(whole) > MAX_GROUPED_DIGITS:
            return " ".join(ru_num(int(ch)) for ch in whole)
        return ru_num(int(whole))

    return THOUSANDS_RE.sub(repl, text)


def separate_comma_lists(text: str) -> str:
    def repl(match):
        parts = [part.strip() for part in match.group(0).split(",")]
        return ", ".join(parts)

    return ENUM_RE.sub(repl, text)


def replace_decimals(text: str) -> str:
    def repl(match):
        return decimal_words(match.group(1), match.group(2))

    return DECIMAL_RE.sub(repl, text)


def replace_remaining_numbers(text: str) -> str:
    def repl(match):
        raw = match.group(0)
        if len(raw) > 12:
            return " ".join(ru_num(int(ch)) for ch in raw)
        return ru_num(int(raw))

    return NUMBER_RE.sub(repl, text)


def transliterate_word(word: str) -> str:
    key = word.lower()
    if key in ACRONYMS:
        return ACRONYMS[key]
    if word.isupper() and 2 <= len(word) <= 4:
        return "-".join(LATIN_LETTER_NAME[ch.lower()] for ch in word)

    lower = word.lower()
    result = []
    i = 0
    while i < len(lower):
        matched = False
        for src, dst in LATIN_DIGRAPHS:
            if lower.startswith(src, i):
                result.append(dst)
                i += len(src)
                matched = True
                break
        if matched:
            continue
        ch = lower[i]
        if ch == "c" and i + 1 < len(lower) and lower[i + 1] in "eiy":
            result.append("с")
        else:
            result.append(LATIN_LETTERS.get(ch, ch))
        i += 1
    return "".join(result)


CYR_LETTER_NAME = {
    "а": "а", "б": "бэ", "в": "вэ", "г": "гэ", "д": "дэ", "е": "е", "ё": "ё",
    "ж": "жэ", "з": "зэ", "и": "и", "й": "и краткое", "к": "ка", "л": "эль",
    "м": "эм", "н": "эн", "о": "о", "п": "пэ", "р": "эр", "с": "эс", "т": "тэ",
    "у": "у", "ф": "эф", "х": "ха", "ц": "цэ", "ч": "че", "ш": "ша", "щ": "ща",
    "ы": "ы", "э": "э", "ю": "ю", "я": "я",
}

# (шаблон, замена, оставлять точку на границе предложения).
# «ул. Ленина» — заглавная это имя, не новое предложение. «т.д. Она» — новое.
ABBREVIATION_RES = (
    (r"(?<!\w)т\.\s*д\.", "так далее", True),
    (r"(?<!\w)т\.\s*е\.", "то есть", True),
    (r"(?<!\w)т\.\s*п\.", "тому подобное", True),
    (r"(?<!\w)т\.\s*к\.", "так как", True),
    (r"(?<!\w)т\.\s*н\.", "так называемый", True),
    (r"(?<!\w)до\s+н\.\s*э\.", "до нашей эры", True),
    (r"(?<!\w)н\.\s*э\.", "нашей эры", True),
    (r"(?<!\w)и\s+др\.", "и другие", True),
    (r"(?<!\w)и\s+пр\.", "и прочее", True),
    (r"(?<!\w)ул\.", "улица", False),
    (r"(?<!\w)проф\.", "профессор", False),
    (r"(?<!\w)рис\.", "рисунок", False),
    (r"(?<!\d)(?<!\d\s)(?<!\w)см\.", "смотри", False),
    (r"(?<!\w)стр\.", "страница", False),
    (r"(?<!\w)пр\.(?=\s*[А-ЯЁ])", "проспект", False),
    (r"(?<!\d)(?<!\d\s)(?<!\w)д\.(?=\s*\d)", "дом", False),
    (r"(?<!\d)(?<!\d\s)(?<!\w)т\.(?=\s*\d)", "том", False),
    (r"(?<![\w\d])[Гг]\.(?=\s*[А-ЯЁ])", "город ", False),
    # T9.3: сокращения без точек на границе предложения — silero10 резал фразу
    # посередине («ул. Ленина» → «улица.» / «Ленина»). Точку оставляем только
    # когда после сокращения действительно конец предложения (см. ends_sentence).
    (r"(?<!\w)тел\.", "телефон", False),
    (r"(?<!\w)корп\.(?=\s*\d)", "корпус", False),
    (r"(?<!\w)коэф\.", "коэффициент", False),
    (r"(?<!\w)бульв\.", "бульвар", False),
    # Область и республика читаются только перед именем собственным: «обл.» в
    # конце предложения — это «область», и точка остаётся.
    (r"(?<!\w)обл\.(?=\s*[А-ЯЁ])", "область", False),
    (r"(?<!\w)респ\.(?=\s*[А-ЯЁ])", "республика", False),
)
INITIALS_RE = re.compile(
    r"(?<![\w])((?:[А-ЯЁа-яё]\.\s*){2,3})(?!\s*[А-ЯЁа-яё]\.)"
)


def replace_initials(text: str) -> str:
    def repl(match):
        letters = re.findall(r"[А-ЯЁа-яё]", match.group(1))
        if not letters or all(ch.islower() for ch in letters):
            return match.group(0)
        if not any(ch.isupper() for ch in letters):
            return match.group(0)
        names = " ".join(CYR_LETTER_NAME[ch.lower()] for ch in letters)
        return names + " "

    return INITIALS_RE.sub(repl, text)


def replace_abbreviations(text: str) -> str:
    """Снимает точки у сокращений, которые silero10 режет как конец предложения."""
    for pattern, replacement, keep_dot in ABBREVIATION_RES:
        cre = re.compile(pattern)

        def repl(match, replacement=replacement, keep_dot=keep_dot):
            out = replacement
            if keep_dot and ends_sentence(match.string, match.end()):
                out += "."
            rest = match.string[match.end():]
            if out and not out[-1].isspace() and rest and not rest[0].isspace():
                out += " "
            return out

        text = cre.sub(repl, text)
    return text


def drop_dots_before_digits(text: str) -> str:
    """«кв.5» не должно стать «кв точка пять» после перевода цифры в слово."""
    return re.sub(r"(?<!\w)([А-Яа-яЁё]{1,6})\.(?=\d)", r"\1 ", text)


ROMAN_NOUN = {
    "век": ("n", "m"),
    "века": ("g", "m"),
    "веку": ("d", "m"),
    "веком": ("i", "m"),
    "веке": ("p", "m"),
    "столетие": ("n", "n"),
    "столетия": ("g", "n"),
    "столетии": ("p", "n"),
    "столетию": ("d", "n"),
    "статья": ("n", "f"),
    "статьи": ("g", "f"),
    "статье": ("d", "f"),
    "статью": ("a", "f"),
    "часть": ("n", "f"),
    "части": ("g", "f"),
    "частью": ("i", "f"),
    "глава": ("n", "f"),
    "главы": ("g", "f"),
    "главе": ("d", "f"),
    "главу": ("a", "f"),
    "том": ("n", "m"),
    "тома": ("g", "m"),
    "томе": ("p", "m"),
    "тому": ("d", "m"),
}
_ROMAN_VAL = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}


def roman_to_int(token: str):
    token = token.upper()
    if not token or _ROMAN_OK.fullmatch(token) is None:
        return None
    total = 0
    prev = 0
    for ch in reversed(token):
        value = _ROMAN_VAL[ch]
        if value < prev:
            total -= value
        else:
            total += value
            prev = value
    return total or None


def replace_romans(text: str) -> str:
    """Римские числа только рядом с век/глава/статья/часть/том/столетие."""

    def repl(match):
        pre = match.group("pre")
        post = match.group("post")
        pre_l = (pre or "").lower()
        post_l = (post or "").lower()
        info = ROMAN_NOUN.get(post_l) or ROMAN_NOUN.get(pre_l)
        if info is None:
            return match.group(0)
        value = roman_to_int(match.group("rom"))
        if value is None:
            return match.group(0)
        case, gender = info
        words = ru_num(value, to="ordinal", case=case, gender=gender, animate=False)
        if pre and pre_l in ROMAN_NOUN and not post:
            return f"{pre} {words}"
        if pre:
            return f"{pre} {words} {post}".strip() if post else f"{pre} {words}"
        return f"{words} {post}" if post else words

    return ROMAN_RE.sub(repl, text)


def transliterate_latin(text: str) -> str:
    text = text.replace("\\", " ")
    return LATIN_WORD_RE.sub(lambda m: transliterate_word(m.group(0)), text)


def cleanup(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # «один.два» после номеров версий, не конец предложения.
    # Оставшееся «16:30» (не время) — «шестнадцать к тридцать», не склейка.
    text = re.sub(r"(?<=[А-Яа-яЁё])\.(?=[А-Яа-яЁё])", " точка ", text)
    text = re.sub(r"(?<=[А-Яа-яЁё]):(?=[А-Яа-яЁё])", " к ", text)
    text = re.sub(r"\(\s*\)", "", text)
    text = re.sub(r"\[\s*\]", "", text)
    # Одиночный знак валюты без числа («у него $ и €») в озвучке только шуршит.
    # Знак при числе (в том числе «300$») тут уже превращён в слово.
    text = re.sub(r"(?<![\d.,])[$€₽](?!\s*\d)", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+([,.;:!?])", r"\1", text)
    text = re.sub(r"\(\s+", "(", text)
    text = re.sub(r"\s+\)", ")", text)
    text = re.sub(r" {2,}", " ", text)
    return text.strip()


def normalize_text(text: str) -> str:
    """Нормализация текста для Silero TTS: даты, годы, время, числа, латиница.

    Узкие шаблоны раньше «всех оставшихся цифр». Переводы строк сохраняются:
    silero10 режет по ним абзацы.
    """
    text = URL_RE.sub("", text)
    text = EMAIL_RE.sub("", text)
    text = replace_ips(text)
    text = replace_dates(text)
    text = replace_times(text)
    text = replace_phones(text)
    text = replace_id_numbers(text)
    text = replace_years(text)
    text = replace_numeric_ranges(text)
    text = replace_signs(text)
    text = replace_fractions(text)
    text = replace_anniversaries(text)
    text = replace_latin_model_numbers(text)
    text = replace_list_markers(text)
    text = replace_hyphen_ordinals(text)
    text = replace_initials(text)
    text = replace_abbreviations(text)
    text = drop_dots_before_digits(text)
    text = KMPH_RE.sub(lambda m: number_and_unit(m.group(1), "км/ч"), text)
    text = replace_units(text)
    text = replace_superscript_units(text)
    text = replace_degree_c_words(text)
    text = replace_thousands(text)
    text = separate_comma_lists(text)
    text = replace_decimals(text)
    text = LATIN_NUM_RE.sub(lambda m: f"{m.group(1)} {m.group(2)}", text)
    text = NUM_LATIN_RE.sub(lambda m: f"{m.group(1)} {m.group(2)}", text)
    text = replace_remaining_numbers(text)
    text = replace_romans(text)
    text = transliterate_latin(text)
    return cleanup(text)


def preprocess_text(file_path: str) -> str:
    """Нормализация файла. Ошибки входа — `InputError` (нет файла, не UTF-8)."""
    return normalize_text(read_text_file(file_path))


if __name__ == "__main__":
    input_file = os.environ.get("TTS_INPUT", "input.txt")
    output_file = os.environ.get("SILERO_INPUT", "silero_input.txt")

    try:
        processed_text = preprocess_text(input_file)
    except InputError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)

    if not processed_text.strip():
        print(f"Пустой вход: {input_file}, выход {output_file} будет пустым", file=sys.stderr)

    with open(output_file, "w", encoding="utf-8") as f:
        f.write(processed_text)

    print(f"Текст обработан и сохранён в {output_file}")
