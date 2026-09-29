"""In-memory data store and the logical factory clock (PRD 2.4, 2.5).

Storage is plain Python dicts held in this module.  Nothing is persisted and
nothing is seeded: every boot of the process starts with a completely empty
estate and all rows are created through the declared API surface.
"""
import datetime as _dt
import random
import string
import uuid

CLOCK_DEFAULT = _dt.datetime(2026, 8, 1, 0, 0, 0, 0, tzinfo=_dt.timezone.utc)

# --------------------------------------------------------------------------
# tables (all empty at import time -- never seeded)
# --------------------------------------------------------------------------
TABLES = {
    "customers": {},
    "machine_models": {},
    "product_trials": {},
    "machine_orders": {},
    "production_lines": {},
    "build_slots": {},
    "long_lead_components": {},
    "acceptance_tests": {},
    "installed_machines": {},
    "format_kits": {},
    "service_contracts": {},
    "field_engineers": {},
    "pm_visits": {},
    "warranty_claims": {},
    "claim_lines": {},
    "stocking_recommendations": {},
}

_STATE = {"clock": CLOCK_DEFAULT, "seq": 0}


# --------------------------------------------------------------------------
# logical clock
# --------------------------------------------------------------------------
def now():
    """Current logical-clock instant (never wall-clock time)."""
    return _STATE["clock"]


def set_now(value):
    _STATE["clock"] = value
    return value


def today():
    return now().date()


def iso_ms(value):
    """ISO 8601 UTC with exactly three fractional-second digits."""
    if value.tzinfo is not None:
        value = value.astimezone(_dt.timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        value.year, value.month, value.day,
        value.hour, value.minute, value.second,
        value.microsecond // 1000,
    )


def now_iso():
    return iso_ms(now())


# --------------------------------------------------------------------------
# calendar helpers -- plain day counting, no timezone offsets (PRD 2.5)
# --------------------------------------------------------------------------
def fmt_date(value):
    return "%04d-%02d-%02d" % (value.year, value.month, value.day)


def parse_date(text):
    return _dt.date(int(text[0:4]), int(text[5:7]), int(text[8:10]))


def add_days(date_text, days):
    return fmt_date(parse_date(date_text) + _dt.timedelta(days=days))


def day_start(date_text):
    d = parse_date(date_text)
    return _dt.datetime(d.year, d.month, d.day, 0, 0, 0, 0, tzinfo=_dt.timezone.utc)


def day_end(date_text):
    d = parse_date(date_text)
    return _dt.datetime(d.year, d.month, d.day, 23, 59, 59, 999000,
                        tzinfo=_dt.timezone.utc)


# --------------------------------------------------------------------------
# identity / row lifecycle
# --------------------------------------------------------------------------
def new_id():
    return str(uuid.uuid4())


def next_seq():
    _STATE["seq"] += 1
    return _STATE["seq"]


def request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def insert(table, row, common_fields=True):
    row["id"] = new_id()
    row["created_at"] = now_iso()
    if common_fields:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    row["_seq"] = next_seq()
    TABLES[table][row["id"]] = row
    return row


def touch(row):
    """Refresh updated_at and increment version (PRD 2.4)."""
    row["updated_at"] = now_iso()
    row["version"] = int(row.get("version", 0)) + 1
    return row


def get(table, row_id):
    if not isinstance(row_id, str):
        return None
    return TABLES[table].get(row_id)


def rows(table):
    """All rows of a table in ascending created_at order (stable)."""
    return sorted(TABLES[table].values(), key=lambda r: (r["created_at"], r["_seq"]))


def reset():
    for table in TABLES.values():
        table.clear()
    _STATE["clock"] = CLOCK_DEFAULT
    _STATE["seq"] = 0
