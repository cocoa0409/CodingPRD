"""Jurisdictions, statutory law changes and the logical clock."""

from decimal import Decimal

from flask import Blueprint

import auth
import cascades
import listing
import serialize
import validation as v
from auth import authorize
from envelope import created, ok
from errors import ApiError
from store import db, base_row, touch
from validation import MISSING, as_bool, as_decimal, as_enum, as_instant, as_string, field, parse_body

bp = Blueprint("jurisdictions", __name__)

POSTURES = ("PERMISSIVE", "MONITORED", "RESTRICTIVE")
FLAG_FIELDS = ("cash_discount_permitted", "price_posting_required",
               "disclosure_signage_required", "receipt_line_item_required")


def _cap(value):
    dec = as_decimal(value, "surcharge_cap_pct", minimum=Decimal(0), maximum=Decimal(100),
                     exclusive_min=True, max_decimals=4)
    return dec


def _check_cap_coherence(surcharge_permitted, cap):
    """Ladder step 9."""
    if surcharge_permitted and cap is None:
        raise ApiError("ERR_JURISDICTION_CAP_REQUIRED")
    if not surcharge_permitted and cap is not None:
        raise ApiError("ERR_JURISDICTION_CAP_REQUIRED")


@bp.post("/jurisdictions")
def create_jurisdiction():
    authorize(["PlatformAdmin"])
    body, malformed = parse_body()
    if malformed:
        raise v.bad("The request body must be a JSON object.")
    v.require_present(body, ["state_code", "surcharge_permitted", "cash_discount_permitted",
                            "price_posting_required", "disclosure_signage_required",
                            "receipt_line_item_required", "ag_enforcement_posture"])
    state_code = as_string(body["state_code"], "state_code", 2, 2)
    if not v.STATE_CODE.match(state_code):
        raise v.bad("state_code must be exactly two uppercase letters.")
    surcharge_permitted = as_bool(body["surcharge_permitted"], "surcharge_permitted")
    cap_raw = field(body, "surcharge_cap_pct")
    cap = None if cap_raw is MISSING or cap_raw is None else _cap(cap_raw)
    flags = {name: as_bool(body[name], name) for name in FLAG_FIELDS}
    posture = as_enum(body["ag_enforcement_posture"], "ag_enforcement_posture", POSTURES)

    _check_cap_coherence(surcharge_permitted, cap)

    for row in db.jurisdictions.values():
        if row["state_code"] == state_code:
            raise ApiError("ERR_DUPLICATE_JURISDICTION_STATE",
                           "A jurisdiction for state_code %s already exists." % state_code)

    row = base_row()
    row.update({
        "state_code": state_code,
        "surcharge_permitted": surcharge_permitted,
        "surcharge_cap_pct": cap,
        "ag_enforcement_posture": posture,
        "law_change_count": 0,
        "last_law_change_at": None,
    })
    row.update(flags)
    db.jurisdictions[row["id"]] = row
    return created(serialize.jurisdiction(row))


@bp.get("/jurisdictions/<jurisdiction_id>")
def read_jurisdiction(jurisdiction_id):
    authorize(auth.READ_ROLES)
    return ok(serialize.jurisdiction(auth.get_jurisdiction(jurisdiction_id)))


@bp.get("/jurisdictions")
def list_jurisdictions():
    authorize(auth.READ_ROLES)
    rows = listing.filtered(list(db.jurisdictions.values()), [
        (listing.arg("state_code"), "state_code"),
        (listing.bool_arg("surcharge_permitted"), "surcharge_permitted"),
    ])
    return listing.list_response(rows, serialize.jurisdiction)


@bp.post("/jurisdictions/<jurisdiction_id>/law-changes")
def apply_law_change(jurisdiction_id):
    authorize(["StateRegulator"])
    jur = auth.get_jurisdiction(jurisdiction_id)
    body, malformed = parse_body()
    if malformed:
        raise v.bad("The request body must be a JSON object.")
    v.require_present(body, ["surcharge_permitted"])
    surcharge_permitted = as_bool(body["surcharge_permitted"], "surcharge_permitted")

    cap_raw = field(body, "surcharge_cap_pct")
    if cap_raw is MISSING:
        cap = jur["surcharge_cap_pct"]
    elif cap_raw is None:
        cap = None
    else:
        cap = _cap(cap_raw)

    updates = {}
    for name in FLAG_FIELDS:
        raw = field(body, name)
        if raw is MISSING:
            continue
        updates[name] = as_bool(raw, name)
    posture_raw = field(body, "ag_enforcement_posture")
    if posture_raw is not MISSING:
        updates["ag_enforcement_posture"] = as_enum(posture_raw, "ag_enforcement_posture", POSTURES)

    _check_cap_coherence(surcharge_permitted, cap)

    was_permitted = jur["surcharge_permitted"]
    jur["surcharge_permitted"] = surcharge_permitted
    jur["surcharge_cap_pct"] = cap
    jur.update(updates)
    jur["law_change_count"] = jur["law_change_count"] + 1
    jur["last_law_change_at"] = db.now()
    touch(jur)

    if was_permitted and not surcharge_permitted:
        cascades.prohibition_cascade(jur)
    elif (not was_permitted) and surcharge_permitted:
        cascades.repermission_cascade(jur)

    return ok(serialize.jurisdiction(jur))


@bp.post("/_clock/set_current_utc")
def set_clock():
    authorize(["PlatformAdmin"])
    body, malformed = parse_body()
    if malformed:
        raise v.bad("The request body must be a JSON object.")
    v.require_present(body, ["to_iso8601"])
    instant = as_instant(body["to_iso8601"], "to_iso8601")
    db.clock = instant
    from store import fmt_ts
    return ok({"current_utc": fmt_ts(instant)})
