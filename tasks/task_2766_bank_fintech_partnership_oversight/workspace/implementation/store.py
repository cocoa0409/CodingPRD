"""In-memory store. Plain dicts keyed by id; nothing is persisted and nothing is seeded."""
from errors import fail
from util import DEFAULT_CLOCK_ISO, fmt_iso, new_id, parse_iso

COLLECTIONS = (
    "partners",
    "diligence_reviews",
    "agreements",
    "marketing_reviews",
    "custody_accounts",
    "ledger_entries",
    "settlement_batches",
    "complaints",
    "alerts",
    "cycles",
    "wind_down_plans",
)

NOT_FOUND = {
    "partners": "ERR_PARTNER_NOT_FOUND",
    "diligence_reviews": "ERR_REVIEW_NOT_FOUND",
    "agreements": "ERR_AGREEMENT_NOT_FOUND",
    "marketing_reviews": "ERR_MARKETING_REVIEW_NOT_FOUND",
    "custody_accounts": "ERR_CUSTODY_ACCOUNT_NOT_FOUND",
    "ledger_entries": "ERR_LEDGER_ENTRY_NOT_FOUND",
    "settlement_batches": "ERR_BATCH_NOT_FOUND",
    "complaints": "ERR_COMPLAINT_NOT_FOUND",
    "alerts": "ERR_ALERT_NOT_FOUND",
    "cycles": "ERR_CYCLE_NOT_FOUND",
    "wind_down_plans": "ERR_PLAN_NOT_FOUND",
}

DB = {name: {} for name in COLLECTIONS}
_STATE = {"clock": parse_iso(DEFAULT_CLOCK_ISO), "seq": 0}


def reset():
    for name in COLLECTIONS:
        DB[name] = {}
    _STATE["clock"] = parse_iso(DEFAULT_CLOCK_ISO)
    _STATE["seq"] = 0


def clock():
    return _STATE["clock"]


def clock_iso():
    return fmt_iso(_STATE["clock"])


def set_clock(dt):
    _STATE["clock"] = dt


def _next_seq():
    _STATE["seq"] += 1
    return _STATE["seq"]


def insert(collection, record, common_fields=True):
    """Assign the identity/system fields and file the record."""
    now = clock()
    record.setdefault("id", new_id())
    record["_seq"] = _next_seq()
    record["created_at"] = now
    if common_fields:
        record["updated_at"] = now
        record["version"] = 1
    DB[collection][record["id"]] = record
    return record


def touch(record):
    record["updated_at"] = clock()
    record["version"] = int(record.get("version", 1)) + 1
    return record


def get(collection, record_id):
    if not isinstance(record_id, str):
        return None
    return DB[collection].get(record_id)


def must(collection, record_id):
    record = get(collection, record_id)
    if record is None:
        fail(NOT_FOUND[collection])
    return record


def rows(collection):
    """Every row in the collection, default order: created_at ASC (PRD 2.3)."""
    return sorted(DB[collection].values(), key=lambda r: (r["created_at"], r["_seq"]))


def where(collection, **equals):
    out = []
    for record in rows(collection):
        if all(record.get(k) == v for k, v in equals.items()):
            out.append(record)
    return out


def next_sequence_no(custody_account_id):
    highest = 0
    for entry in DB["ledger_entries"].values():
        if entry.get("custody_account_id") == custody_account_id:
            highest = max(highest, int(entry.get("sequence_no") or 0))
    return highest + 1
