"""In-memory data store. Empty on every boot; nothing is ever seeded."""

from errors import ApiError
from util import fmt_instant, new_id, now_dt, now_iso

COLLECTIONS = (
    "products",
    "customer_specs",
    "grower_lots",
    "raw_receipts",
    "lines",
    "wash_systems",
    "readings",
    "process_runs",
    "lot_consumptions",
    "finished_cases",
    "hold_records",
    "sanitation_events",
    "environmental_swabs",
    "corrective_actions",
)

STORE = {name: {} for name in COLLECTIONS}

_SEQ = {"n": 0}

NOT_FOUND_ERRORS = {
    "products": "ERR_PRODUCT_NOT_FOUND",
    "customer_specs": "ERR_CUSTOMER_SPEC_NOT_FOUND",
    "grower_lots": "ERR_GROWER_LOT_NOT_FOUND",
    "raw_receipts": "ERR_RAW_RECEIPT_NOT_FOUND",
    "lines": "ERR_LINE_NOT_FOUND",
    "wash_systems": "ERR_WASH_SYSTEM_NOT_FOUND",
    "readings": "ERR_WASH_SYSTEM_NOT_FOUND",
    "process_runs": "ERR_PROCESS_RUN_NOT_FOUND",
    "lot_consumptions": "ERR_LOT_CONSUMPTION_NOT_FOUND",
    "finished_cases": "ERR_FINISHED_CASE_NOT_FOUND",
    "hold_records": "ERR_HOLD_RECORD_NOT_FOUND",
    "sanitation_events": "ERR_SANITATION_EVENT_NOT_FOUND",
    "environmental_swabs": "ERR_ENVIRONMENTAL_SWAB_NOT_FOUND",
    "corrective_actions": "ERR_CORRECTIVE_ACTION_NOT_FOUND",
}


def next_seq():
    _SEQ["n"] += 1
    return _SEQ["n"]


def stamp(row, name, dt):
    """Write a server-stamped instant in the canonical three-fraction-digit form."""
    row[name] = fmt_instant(dt)
    row["_dt_" + name] = dt


def set_instant(row, name, instant):
    """Write a client-supplied instant verbatim, keeping the parsed value beside it."""
    if instant is None:
        row[name] = None
        row["_dt_" + name] = None
    else:
        row[name] = instant.raw
        row["_dt_" + name] = instant.dt


def dt_of(row, name):
    return row.get("_dt_" + name)


def new_row(collection, fields, common=True):
    row = {"id": new_id()}
    row.update(fields)
    now = now_dt()
    stamp(row, "created_at", now)
    if common:
        stamp(row, "updated_at", now)
        row["version"] = 1
    row["_seq"] = next_seq()
    STORE[collection][row["id"]] = row
    return row


def touch(row):
    """Any row a write or a cascade changes is a mutation (PRD 2.5 / 2.11)."""
    if "version" in row:
        row["version"] = row["version"] + 1
    stamp(row, "updated_at", now_dt())
    return row


def rows(collection):
    return sorted(STORE[collection].values(), key=lambda r: r["_seq"])


def find(collection, row_id):
    if not isinstance(row_id, str):
        return None
    return STORE[collection].get(row_id)


def get_or_404(collection, row_id, error_id=None):
    row = find(collection, row_id)
    if row is None:
        raise ApiError(error_id or NOT_FOUND_ERRORS[collection])
    return row


def where(collection, **kw):
    out = []
    for row in rows(collection):
        ok = True
        for key, value in kw.items():
            if row.get(key) != value:
                ok = False
                break
        if ok:
            out.append(row)
    return out


def public(row):
    return {k: v for k, v in row.items() if not k.startswith("_")}
