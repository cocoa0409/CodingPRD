"""In-memory data store, the logical clock, and id/timestamp helpers.

Everything lives in process memory only: the store starts completely empty on
every boot and nothing is ever persisted anywhere.
"""

import itertools
import re
import uuid
from datetime import datetime, timedelta, timezone

from errors import ApiError

# PRD 2.4: at startup the logical clock reads exactly 2026-08-01T00:00:00Z.
CLOCK_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "campaigns",
    "build_zones",
    "service_addresses",
    "accounts",
    "mdu_agreements",
    "permit_applications",
    "pole_requests",
    "preorders",
    "install_crews",
    "install_appointments",
    "damage_claims",
    "ledger_entries",
    "fallback_options",
    "fallback_offers",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.current_utc = CLOCK_START
        self._seq = itertools.count(1)


db = Store()


def now():
    """The logical clock instant."""
    return db.current_utc


def set_clock(instant):
    db.current_utc = instant


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(db._seq)


# --------------------------------------------------------------------------
# timestamps
# --------------------------------------------------------------------------

_ISO_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[Tt ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?"
    r"([Zz]|[+-]\d{2}:?\d{2})?$"
)


def fmt_dt(value):
    """ISO 8601 UTC with exactly three fractional digits."""
    if value is None:
        return None
    value = value.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        value.year,
        value.month,
        value.day,
        value.hour,
        value.minute,
        value.second,
        value.microsecond // 1000,
    )


def try_parse_dt(raw):
    """Parse an ISO 8601 instant, returning None when it does not parse."""
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text or not _ISO_RE.match(text):
        return None
    if text[-1] in ("Z", "z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def add_days(instant, days):
    return instant + timedelta(days=int(days))


def add_minutes(instant, minutes):
    return instant + timedelta(minutes=int(minutes))


# --------------------------------------------------------------------------
# rows
# --------------------------------------------------------------------------


def new_row(fields, versioned=True):
    """Create a row with its system columns. `version` starts at 1."""
    row = {"id": new_id(), "created_at": now(), "_seq": next_seq()}
    if versioned:
        row["updated_at"] = now()
        row["version"] = 1
    row.update(fields)
    return row


def bump(row):
    """One mutation of a row: refresh updated_at and increase version by 1."""
    row["updated_at"] = now()
    row["version"] = row.get("version", 1) + 1
    return row


def ordered(rows):
    """Default list order: created_at ascending (insertion order breaks ties)."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


# --------------------------------------------------------------------------
# lookups
# --------------------------------------------------------------------------

NOT_FOUND = {
    "campaigns": "ERR_CAMPAIGN_NOT_FOUND",
    "build_zones": "ERR_BUILD_ZONE_NOT_FOUND",
    "service_addresses": "ERR_SERVICE_ADDRESS_NOT_FOUND",
    "accounts": "ERR_ACCOUNT_NOT_FOUND",
    "mdu_agreements": "ERR_MDU_AGREEMENT_NOT_FOUND",
    "permit_applications": "ERR_PERMIT_APPLICATION_NOT_FOUND",
    "pole_requests": "ERR_POLE_REQUEST_NOT_FOUND",
    "preorders": "ERR_PREORDER_NOT_FOUND",
    "install_crews": "ERR_INSTALL_CREW_NOT_FOUND",
    "install_appointments": "ERR_INSTALL_APPOINTMENT_NOT_FOUND",
    "damage_claims": "ERR_DAMAGE_CLAIM_NOT_FOUND",
    "ledger_entries": "ERR_LEDGER_ENTRY_NOT_FOUND",
    "fallback_options": "ERR_FALLBACK_OPTION_NOT_FOUND",
    "fallback_offers": "ERR_FALLBACK_OFFER_NOT_FOUND",
}


def find(collection, row_id):
    if not isinstance(row_id, str):
        return None
    return getattr(db, collection).get(row_id)


def must_find(collection, row_id):
    row = find(collection, row_id)
    if row is None:
        raise ApiError(NOT_FOUND[collection], "%s not found" % collection[:-1])
    return row


def insert(collection, row):
    getattr(db, collection)[row["id"]] = row
    return row


def rows(collection):
    return list(getattr(db, collection).values())
