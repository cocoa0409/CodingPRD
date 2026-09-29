"""In-memory data store, logical clock and row bookkeeping helpers.

NOTHING is seeded here. Every collection starts empty on every boot; all
entities are created exclusively through the declared HTTP surface.
"""
import re
import threading
import uuid
from datetime import datetime, timedelta, timezone

from flask import g

from constants import CLOCK_START_UTC
from errors import ApiError

UTC = timezone.utc

_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2}))?(\.\d+)?"
    r"([Zz]|[+-]\d{2}:?\d{2})?$"
)


def parse_instant(value):
    """Parse an RFC 3339 UTC instant. Returns an aware datetime or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    m = _ISO_RE.match(text)
    if not m:
        return None
    year, month, day, hour, minute = (int(m.group(i)) for i in range(1, 6))
    second = int(m.group(6) or 0)
    frac = m.group(7)
    micro = 0
    if frac:
        digits = (frac[1:] + "000000")[:6]
        micro = int(digits)
    offset = m.group(8)
    try:
        naive = datetime(year, month, day, hour, minute, second, micro)
    except ValueError:
        return None
    if offset is None or offset in ("Z", "z"):
        return naive.replace(tzinfo=UTC)
    sign = 1 if offset[0] == "+" else -1
    body = offset[1:].replace(":", "")
    delta = timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
    return (naive - sign * delta).replace(tzinfo=UTC)


def fmt_instant(value):
    """Canonical ISO-8601 UTC instant with exactly three fractional digits."""
    if value is None:
        return None
    if isinstance(value, str):
        parsed = parse_instant(value)
        if parsed is None:
            return value
        value = parsed
    value = value.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        value.year,
        value.month,
        value.day,
        value.hour,
        value.minute,
        value.second,
        value.microsecond // 1000,
    )


class Store(object):
    """Plain in-memory dictionaries -- one per entity collection."""

    def __init__(self):
        self.lock = threading.RLock()
        self.titles = {}
        self.market_plans = {}
        self.string_keys = {}
        self.translation_units = {}
        self.booths = {}
        self.voice_talents = {}
        self.talent_contracts = {}
        self.voice_sessions = {}
        self.qa_passes = {}
        self.lqa_bugs = {}
        self.rating_submissions = {}
        self.content_edits = {}
        self.clock = parse_instant(CLOCK_START_UTC)
        self._last_wall = None

    # -- logical clock ------------------------------------------------------
    def now(self):
        """The logical clock. There is no wall-clock fallback anywhere."""
        return self.clock

    def set_clock(self, moment):
        self.clock = moment

    # -- row-stamp clock ---------------------------------------------------
    def next_wall(self):
        """Strictly increasing millisecond stamp used for created_at/updated_at.

        Rows created inside one request share a single stamp (see request_now),
        which is what makes the natural-key tie-breaks of PRD SS2.3 observable.
        """
        moment = datetime.now(UTC).replace(microsecond=(datetime.now(UTC).microsecond // 1000) * 1000)
        if self._last_wall is not None and moment <= self._last_wall:
            moment = self._last_wall + timedelta(milliseconds=1)
        self._last_wall = moment
        return moment


db = Store()


def new_id():
    return str(uuid.uuid4())


def request_now():
    """The single row-stamp used for every write in the current request."""
    stamp = getattr(g, "row_stamp", None)
    if stamp is None:
        stamp = db.next_wall()
        g.row_stamp = stamp
    return stamp


def touch(row):
    """Mutate bookkeeping: +1 version and a fresh updated_at, once per request."""
    touched = getattr(g, "touched", None)
    if touched is None:
        touched = set()
        g.touched = touched
    if row["id"] in touched:
        return row
    touched.add(row["id"])
    row["version"] = row["version"] + 1
    row["updated_at"] = request_now()
    return row


def base_row():
    stamp = request_now()
    return {
        "id": new_id(),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
    }


# --------------------------------------------------------------- lookups
_NOT_FOUND = {
    "titles": "ERR_TITLE_NOT_FOUND",
    "market_plans": "ERR_MARKET_PLAN_NOT_FOUND",
    "string_keys": "ERR_STRING_KEY_NOT_FOUND",
    "translation_units": "ERR_TRANSLATION_UNIT_NOT_FOUND",
    "booths": "ERR_BOOTH_NOT_FOUND",
    "voice_talents": "ERR_TALENT_NOT_FOUND",
    "talent_contracts": "ERR_CONTRACT_NOT_FOUND",
    "voice_sessions": "ERR_SESSION_NOT_FOUND",
    "qa_passes": "ERR_QA_PASS_NOT_FOUND",
    "lqa_bugs": "ERR_BUG_NOT_FOUND",
    "rating_submissions": "ERR_SUBMISSION_NOT_FOUND",
    "content_edits": "ERR_CONTENT_EDIT_NOT_FOUND",
}


def fetch(collection, row_id):
    table = getattr(db, collection)
    row = table.get(row_id) if isinstance(row_id, str) else None
    if row is None:
        raise ApiError(_NOT_FOUND[collection])
    return row


def rows(collection):
    return list(getattr(db, collection).values())


def insert(collection, row):
    getattr(db, collection)[row["id"]] = row
    return row
