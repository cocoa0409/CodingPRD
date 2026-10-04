"""In-memory object store.

Every dict below starts EMPTY on each boot.  Nothing here seeds, preloads or
hardcodes an entity: a fresh `bash start.sh` wipes every byte of state, and all
rows are produced by the declared endpoints.  Storage is process memory only —
no SQLite file, no JSON dump, no /tmp cache, no external persistence.
"""

import uuid
from datetime import datetime, timezone

branches = {}
membership_plans = {}
campaigns = {}
pricebook_tasks = {}
technicians = {}
revenue_ledger_entries = {}
appointments = {}
appointment_lines = {}
override_requests = {}
membership_agreements = {}
membership_visits = {}
call_records = {}

# insertion order of appointment lines as they were added to their appointment;
# the household load trace is ordered by that payload order (PRD 3.4).
LINE_ADD_SEQ = {}
_line_seq_counter = {"n": 0}


def new_id():
    return str(uuid.uuid4())


def now_utc():
    from constants import clock
    return clock.now()


def iso(dt):
    """ISO 8601 UTC instant with exactly three fractional digits."""
    if dt is None:
        return None
    if isinstance(dt, str):
        dt = parse_iso(dt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_iso(value, field="timestamp"):
    from errors import invalid_request
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str):
        raise invalid_request("%s must be an ISO 8601 instant" % field)
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise invalid_request("%s must be an ISO 8601 instant" % field)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def next_line_seq():
    _line_seq_counter["n"] += 1
    return _line_seq_counter["n"]


def rows(mapping):
    return list(mapping.values())


def by_created(mapping):
    return sorted(mapping.values(), key=lambda r: (r["created_at"], r.get("id", "")))


def new_row(entity_type, **fields):
    """Allocate a row with the identity quartet (PRD 2.4)."""
    stamp = now_utc()
    row = {
        "id": new_id(),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "_type": entity_type,
    }
    row.update(fields)
    return row


def new_child_row(**fields):
    """Append-mostly rows carry only id and created_at (PRD 2.4)."""
    row = {
        "id": new_id(),
        "created_at": now_utc(),
    }
    row.update(fields)
    return row


def touch(row):
    """Record a write: the version advances by exactly one."""
    row["updated_at"] = now_utc()
    row["version"] = row.get("version", 1) + 1
    return row