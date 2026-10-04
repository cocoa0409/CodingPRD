"""Storage helpers: entity lookup, serialization, pagination, mutation stamping."""

from datetime import datetime, timezone

from db import DB
from errors import fail, fmt

HIDDEN_PREFIX = "_"

NOT_FOUND = {
    "buyer": "ERR_BUYER_NOT_FOUND",
    "order": "ERR_ORDER_NOT_FOUND",
    "appointment": "ERR_APPOINTMENT_NOT_FOUND",
    "appraisal": "ERR_APPRAISAL_NOT_FOUND",
    "application": "ERR_APPLICATION_NOT_FOUND",
    "batch": "ERR_BATCH_NOT_FOUND",
    "unit": "ERR_UNIT_NOT_FOUND",
    "vehicle": "ERR_VEHICLE_NOT_FOUND",
    "visit": "ERR_VISIT_NOT_FOUND",
    "report": "ERR_REPORT_NOT_FOUND",
    "entitlement": "ERR_ENTITLEMENT_NOT_FOUND",
    "jurisdiction": "ERR_JURISDICTION_NOT_FOUND",
    "center": "ERR_CENTER_NOT_FOUND",
    "configuration": "ERR_CONFIGURATION_NOT_FOUND",
    "option": "ERR_OPTION_NOT_FOUND",
    "estimate": "ERR_ESTIMATE_NOT_FOUND",
    "note": "ERR_NOTE_NOT_FOUND",
}

TABLES = {
    "buyer": "buyers",
    "order": "orders",
    "appointment": "appointments",
    "appraisal": "appraisals",
    "application": "applications",
    "batch": "batches",
    "unit": "units",
    "vehicle": "vehicles",
    "visit": "visits",
    "report": "reports",
    "entitlement": "entitlements",
    "jurisdiction": "jurisdictions",
    "center": "centers",
    "configuration": "configurations",
    "option": "options",
    "estimate": "estimates",
    "note": "notes",
    "service_appointment": "service_appointments",
    "ledger": "ledger",
}


def table(kind):
    return getattr(DB, TABLES[kind])


def get(kind, entity_id, error_id=None):
    row = table(kind).get(entity_id)
    if row is None:
        fail(error_id or NOT_FOUND[kind])
    return row


def find(kind, entity_id):
    return table(kind).get(entity_id)


def serialize(row):
    now = DB.now
    out = {}
    for key, value in row.items():
        if key.startswith(HIDDEN_PREFIX):
            continue
        if isinstance(value, datetime):
            out[key] = fmt(value)
        elif isinstance(value, list):
            out[key] = [fmt(v) if isinstance(v, datetime) else v for v in value]
        else:
            out[key] = value
    return out


def serialize_all(rows):
    return [serialize(r) for r in rows]


def touch(row):
    """Any recalculation of a derived attribute refreshes updated_at and bumps version."""
    if "version" in row:
        row["version"] = row.get("version", 1) + 1
        row["updated_at"] = fmt(DB.now)


def created_at_key(row):
    return row.get("created_at") or ""


def read_paging(args):
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    try:
        limit = 10 if raw_limit in (None, "") else int(raw_limit)
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = 0 if raw_offset in (None, "") else int(raw_offset)
    except (TypeError, ValueError):
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def listed(rows, args):
    """Filter by created_at ascending then slice for pagination."""
    ordered = sorted(rows, key=created_at_key)
    limit, offset = read_paging(args)
    return ordered[offset:offset + limit], ordered, limit, offset


def matches(args, field, value):
    wanted = args.get(field)
    if wanted in (None, ""):
        return True
    return str(value) == str(wanted)


def matches_bool(args, field, value):
    wanted = args.get(field)
    if wanted in (None, ""):
        return True
    text = str(wanted).strip().lower()
    truthy = text in ("true", "1", "yes")
    return bool(value) is truthy