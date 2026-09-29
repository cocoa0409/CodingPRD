"""Logical clock (PRD Section 2.6) plus date / ISO-week helpers."""
import datetime
import re

DEFAULT_INSTANT = datetime.datetime(2026, 8, 1, 0, 0, 0, tzinfo=datetime.timezone.utc)

_state = {"now": DEFAULT_INSTANT}

_INSTANT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2}))?(?:\.(\d{1,9}))?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)
_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
ISO_WEEK_RE = re.compile(r"^\d{4}-W\d{2}$")


def now():
    return _state["now"]


def set_now(instant):
    _state["now"] = instant


def reset():
    _state["now"] = DEFAULT_INSTANT


def format_instant(instant):
    instant = instant.astimezone(datetime.timezone.utc)
    return instant.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (instant.microsecond // 1000)


def now_iso():
    return format_instant(now())


def parse_instant(raw):
    """Parse an ISO-8601 instant. Returns a tz-aware UTC datetime or None."""
    if not isinstance(raw, str):
        return None
    m = _INSTANT_RE.match(raw.strip())
    if not m:
        return None
    year, month, day, hour, minute = (int(m.group(i)) for i in range(1, 6))
    second = int(m.group(6) or 0)
    frac = m.group(7) or ""
    micro = int((frac + "000000")[:6]) if frac else 0
    tz = m.group(8)
    try:
        base = datetime.datetime(year, month, day, hour, minute, second, micro,
                                 tzinfo=datetime.timezone.utc)
    except ValueError:
        return None
    if tz and tz not in ("Z", "z"):
        sign = 1 if tz[0] == "+" else -1
        tz = tz[1:].replace(":", "")
        offset = datetime.timedelta(hours=int(tz[:2]), minutes=int(tz[2:4]))
        base = base - sign * offset
    return base


def parse_date(raw):
    """Parse a YYYY-MM-DD calendar date. Returns datetime.date or None."""
    if not isinstance(raw, str):
        return None
    m = _DATE_RE.match(raw.strip())
    if not m:
        return None
    try:
        return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def format_date(value):
    return value.isoformat()


def today():
    return now().astimezone(datetime.timezone.utc).date()


def iso_week_label(day):
    year, week, _ = day.isocalendar()
    return "%04d-W%02d" % (year, week)


def week_monday(label):
    """Monday date of an ISO week label, or None when the label is not a real week."""
    if not isinstance(label, str) or not ISO_WEEK_RE.match(label.strip()):
        return None
    label = label.strip()
    year = int(label[0:4])
    week = int(label[6:8])
    if week < 1 or week > 53:
        return None
    try:
        return datetime.date.fromisocalendar(year, week, 1)
    except ValueError:
        return None


def week_index(label):
    """Monotonic integer ordinal for an ISO week label (Mondays are 1 mod 7)."""
    monday = week_monday(label)
    if monday is None:
        return None
    return monday.toordinal() // 7


def week_dates(label):
    monday = week_monday(label)
    if monday is None:
        return []
    return [monday + datetime.timedelta(days=i) for i in range(7)]


def weeks_touched(start_date, end_date):
    """Every ISO week label touched by the closed date interval, in order."""
    labels = []
    cursor = start_date
    while cursor <= end_date:
        label = iso_week_label(cursor)
        if label not in labels:
            labels.append(label)
        cursor = cursor + datetime.timedelta(days=7)
    end_label = iso_week_label(end_date)
    if end_label not in labels:
        labels.append(end_label)
    return labels


def current_week_label():
    return iso_week_label(today())
