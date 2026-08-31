"""In-memory data store, logical UTC clock, and id/timestamp helpers.

Everything lives in plain Python dicts keyed by id.  The store starts EMPTY on
every boot: nothing is seeded, preloaded or hardcoded here.
"""

import uuid
from datetime import datetime, timedelta, timezone

from errors import ApiError

# ---------------------------------------------------------------------------
# Collections (all empty at boot)
# ---------------------------------------------------------------------------
wards = {}
patients = {}
diet_rules = {}
diet_orders = {}
meal_periods = {}
menu_items = {}
meal_orders = {}
meal_order_lines = {}
procedure_holds = {}
consults = {}
supplement_orders = {}
surveys = {}

_seq = {"n": 0}

# ---------------------------------------------------------------------------
# Logical UTC clock -- never falls back to wall-clock time.
# ---------------------------------------------------------------------------
CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock = {"now": CLOCK_EPOCH}


def now():
    """Current logical-clock instant (timezone-aware UTC datetime)."""
    return _clock["now"]


def set_clock(dt):
    _clock["now"] = dt
    return _clock["now"]


# ---------------------------------------------------------------------------
# Time formatting / parsing
# ---------------------------------------------------------------------------
def iso(dt):
    """ISO 8601 UTC with exactly three fractional-second digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_iso(value):
    """Parse an ISO 8601 instant.  Returns an aware UTC datetime or None on failure."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("z") or text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    """Parse a YYYY-MM-DD calendar date, returning a date or None."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def minutes(n):
    return timedelta(minutes=n)


# ---------------------------------------------------------------------------
# Entity lifecycle helpers
# ---------------------------------------------------------------------------
def new_id():
    return str(uuid.uuid4())


def next_seq():
    _seq["n"] += 1
    return _seq["n"]


def stamp_new(entity, versioned=True):
    """Attach id / created_at / updated_at / version to a fresh entity dict."""
    entity["id"] = new_id()
    entity["created_at"] = now()
    entity["_seq"] = next_seq()
    if versioned:
        entity["updated_at"] = entity["created_at"]
        entity["version"] = 1
    return entity


def touch(entity):
    """Record a mutation: refresh updated_at to the logical clock and bump version."""
    entity["updated_at"] = now()
    entity["version"] = entity.get("version", 1) + 1
    return entity


def sort_rows(rows):
    """Default ordering: created_at ascending, insertion sequence as a stable tie-break."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


# ---------------------------------------------------------------------------
# Existence helpers -- each entity type has its own not-found error id
# ---------------------------------------------------------------------------
def _get(collection, entity_id, error_id):
    if not isinstance(entity_id, str):
        raise ApiError(error_id)
    row = collection.get(entity_id)
    if row is None:
        raise ApiError(error_id)
    return row


def get_ward(i):
    return _get(wards, i, "ERR_WARD_NOT_FOUND")


def get_patient(i):
    return _get(patients, i, "ERR_PATIENT_NOT_FOUND")


def get_diet_rule(i):
    return _get(diet_rules, i, "ERR_DIET_RULE_NOT_FOUND")


def get_diet_order(i):
    return _get(diet_orders, i, "ERR_DIET_ORDER_NOT_FOUND")


def get_meal_period(i):
    return _get(meal_periods, i, "ERR_MEAL_PERIOD_NOT_FOUND")


def get_menu_item(i):
    return _get(menu_items, i, "ERR_MENU_ITEM_NOT_FOUND")


def get_meal_order(i):
    return _get(meal_orders, i, "ERR_MEAL_ORDER_NOT_FOUND")


def get_meal_order_line(i):
    return _get(meal_order_lines, i, "ERR_MEAL_ORDER_LINE_NOT_FOUND")


def get_procedure_hold(i):
    return _get(procedure_holds, i, "ERR_PROCEDURE_HOLD_NOT_FOUND")


def get_consult(i):
    return _get(consults, i, "ERR_CONSULT_NOT_FOUND")


def get_supplement_order(i):
    return _get(supplement_orders, i, "ERR_SUPPLEMENT_ORDER_NOT_FOUND")


def get_survey(i):
    return _get(surveys, i, "ERR_SURVEY_NOT_FOUND")


# ---------------------------------------------------------------------------
# Relationship helpers
# ---------------------------------------------------------------------------
def lines_of(meal_order_id):
    return sort_rows([l for l in meal_order_lines.values()
                      if l["meal_order_id"] == meal_order_id])


def orders_of_period(period_id):
    return sort_rows([o for o in meal_orders.values()
                      if o["meal_period_id"] == period_id])


def orders_of_patient(patient_id):
    return sort_rows([o for o in meal_orders.values()
                      if o["patient_id"] == patient_id])


def active_diet_order_of(patient_id):
    for row in sort_rows(list(diet_orders.values())):
        if row["patient_id"] == patient_id and row["status"] == "ACTIVE":
            return row
    return None


def active_hold_of(patient_id):
    for row in sort_rows(list(procedure_holds.values())):
        if row["patient_id"] == patient_id and row["status"] == "ACTIVE":
            return row
    return None


def ward_census(ward_id):
    return sum(1 for p in patients.values()
               if p["ward_id"] == ward_id
               and p["status"] == "ADMITTED"
               and p["npo_status"] == "NONE")
