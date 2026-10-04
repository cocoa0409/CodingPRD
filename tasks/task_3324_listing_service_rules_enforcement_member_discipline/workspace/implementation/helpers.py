"""Shared helpers: ids, timestamps, entity minting, lookups, pagination,
payload validation per PRD §2."""

import uuid
from flask import request

from db import store, now, _fmt_iso, _parse_iso
from errors import raise_err, ERR_NOT_FOUND, ERR_INVALID_REQUEST


def new_id():
    return str(uuid.uuid4())


def now_iso_str():
    return _fmt_iso(now())


def parse_dt(value, field):
    """Parse a request datetime field; ERR_INVALID_REQUEST on bad input."""
    if value is None:
        return None
    try:
        return _parse_iso(value)
    except Exception:
        raise_err(ERR_INVALID_REQUEST, "Field '%s' is not a valid ISO 8601 datetime" % field)


def body():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise_err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return data


def require_fields(data, fields):
    for f in fields:
        if f not in data or data[f] is None:
            raise_err(ERR_INVALID_REQUEST, "Missing required field '%s'" % f)


def require_int(data, field, minimum=None, allow_zero=True):
    v = data.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise_err(ERR_INVALID_REQUEST, "Field '%s' must be an integer" % field)
    if minimum is not None and v < minimum:
        raise_err(ERR_INVALID_REQUEST, "Field '%s' must be >= %d" % (field, minimum))
    if not allow_zero and v == 0:
        raise_err(ERR_INVALID_REQUEST, "Field '%s' must be non-zero" % field)
    return v


def require_enum(data, field, choices):
    v = data.get(field)
    if v not in choices:
        raise_err(ERR_INVALID_REQUEST,
                  "Field '%s' must be one of %s" % (field, ", ".join(choices)))
    return v


def mint_common(entity):
    """Attach id + created_at/updated_at/version (common_fields entities)."""
    ts = now_iso_str()
    entity["id"] = new_id()
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    return entity


def mint_consolidation(entity):
    """ConsolidationEvent carries only id and created_at (PRD §2.4)."""
    entity["id"] = new_id()
    entity["created_at"] = now_iso_str()
    return entity


def touch(entity):
    """Bump version by exactly 1 and refresh updated_at (PRD §2.4)."""
    entity["version"] = entity.get("version", 1) + 1
    entity["updated_at"] = now_iso_str()


# ---------------------------------------------------------------------------
# Lookup helpers (priority 3: existence; left-to-right nesting)
# ---------------------------------------------------------------------------

def get_association(assoc_id):
    a = store.associations.get(assoc_id)
    if a is None:
        raise_err(ERR_NOT_FOUND, "Association %s not found" % assoc_id)
    return a


def get_member(member_id, assoc_id=None):
    m = store.members.get(member_id)
    if m is None or (assoc_id is not None and m["association_id"] != assoc_id):
        raise_err(ERR_NOT_FOUND, "Member %s not found" % member_id)
    return m


def get_office(office_id, assoc_id=None):
    o = store.offices.get(office_id)
    if o is None or (assoc_id is not None and o["association_id"] != assoc_id):
        raise_err(ERR_NOT_FOUND, "Office %s not found" % office_id)
    return o


def get_listing(listing_id, office_id=None):
    l = store.listings.get(listing_id)
    if l is None or (office_id is not None and l["office_id"] != office_id):
        raise_err(ERR_NOT_FOUND, "Listing %s not found" % listing_id)
    return l


def get_dues_period(period_id, assoc_id=None):
    p = store.dues_periods.get(period_id)
    if p is None or (assoc_id is not None and p["association_id"] != assoc_id):
        raise_err(ERR_NOT_FOUND, "DuesPeriod %s not found" % period_id)
    return p


def get_invoice(invoice_id, assoc_id=None):
    inv = store.dues_invoices.get(invoice_id)
    if inv is None:
        raise_err(ERR_NOT_FOUND, "DuesInvoice %s not found" % invoice_id)
    if assoc_id is not None:
        period = store.dues_periods.get(inv["dues_period_id"])
        if period is None or period["association_id"] != assoc_id:
            raise_err(ERR_NOT_FOUND, "DuesInvoice %s not found" % invoice_id)
    return inv


def get_citation(citation_id, assoc_id=None):
    c = store.citations.get(citation_id)
    if c is None or (assoc_id is not None and c["association_id"] != assoc_id):
        raise_err(ERR_NOT_FOUND, "Citation %s not found" % citation_id)
    return c


def get_fine_schedule(schedule_id, assoc_id=None):
    s = store.fine_schedules.get(schedule_id)
    if s is None or (assoc_id is not None and s["association_id"] != assoc_id):
        raise_err(ERR_NOT_FOUND, "FineSchedule %s not found" % schedule_id)
    return s


def get_ethics_case(case_id, assoc_id=None):
    c = store.ethics_cases.get(case_id)
    if c is None or (assoc_id is not None and c["association_id"] != assoc_id):
        raise_err(ERR_NOT_FOUND, "EthicsCase %s not found" % case_id)
    return c


def get_arbitration_case(case_id, assoc_id=None):
    c = store.arbitration_cases.get(case_id)
    if c is None or (assoc_id is not None and c["association_id"] != assoc_id):
        raise_err(ERR_NOT_FOUND, "ArbitrationCase %s not found" % case_id)
    return c


def get_panel(panel_id, assoc_id=None):
    p = store.hearing_panels.get(panel_id)
    if p is None or (assoc_id is not None and p["association_id"] != assoc_id):
        raise_err(ERR_NOT_FOUND, "HearingPanel %s not found" % panel_id)
    return p


def get_license(license_id, assoc_id=None):
    lic = store.data_licenses.get(license_id)
    if lic is None or (assoc_id is not None and lic["association_id"] != assoc_id):
        raise_err(ERR_NOT_FOUND, "DataLicense %s not found" % license_id)
    return lic


def get_policy_revision(revision_id, assoc_id=None):
    r = store.policy_revisions.get(revision_id)
    if r is None or (assoc_id is not None and r["association_id"] != assoc_id):
        raise_err(ERR_NOT_FOUND, "PolicyRevision %s not found" % revision_id)
    return r


def get_consolidation(event_id):
    e = store.consolidation_events.get(event_id)
    if e is None:
        raise_err(ERR_NOT_FOUND, "ConsolidationEvent %s not found" % event_id)
    return e


def get_status_change(sc_id):
    sc = store.status_changes.get(sc_id)
    if sc is None:
        raise_err(ERR_NOT_FOUND, "StatusChange %s not found" % sc_id)
    return sc


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3): limit default 10, min 1, max 100; offset default 0;
# sort by created_at ascending.
# ---------------------------------------------------------------------------

def pagination_params():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except ValueError:
        raise_err(ERR_INVALID_REQUEST, "limit must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except ValueError:
        raise_err(ERR_INVALID_REQUEST, "offset must be an integer")
    if limit < 1 or limit > 100:
        raise_err(ERR_INVALID_REQUEST, "limit must be between 1 and 100")
    if offset < 0:
        raise_err(ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset


def sort_created(items):
    # PRD §2.3: "Results are sorted by `created_at` ascending." Python's sort
    # is stable, so entities minted in the same logical instant keep their
    # insertion order (dicts iterate in insertion order) rather than being
    # scrambled by random UUIDs.
    return sorted(items, key=lambda e: e.get("created_at", ""))


def page(items):
    limit, offset = pagination_params()
    items = sort_created(items)
    total = len(items)
    return items[offset:offset + limit], limit, offset, total
