"""DistrictOffice endpoints (§1.5; PRD §2.11)."""

from flask import Blueprint, request

from db import db
from errors import (
    err,
    ERR_DISTRICT_OFFICE_NOT_FOUND,
    ERR_DUPLICATE_NATURAL_KEY,
    ERR_OFFICE_HAS_LIVE_ADVISORS,
    ERR_INVALID_STATE,
    ERR_ALREADY_TERMINAL,
)
from middleware import body, required, pagination, page, as_str, as_int
from response import ok, ok_list
from routes._shared import authed
from services import calc, serialize

bp = Blueprint("offices", __name__)
WRITE = ["ManagingDirector"]
READ = ["Any"]

LIVE_CONTRACT_STATES = ("ACTIVE_TRAINING", "VALIDATING", "AT_RISK")


def get(office_id):
    row = db.district_offices.get(office_id)
    if row is None:
        raise err(ERR_DISTRICT_OFFICE_NOT_FOUND,
                  "no district office with id %s" % office_id)
    return row


@bp.post("/agency/district-offices")
@authed(WRITE)
def create(user_id, role):
    data = body()
    office_code = required(data, "office_code")
    name = required(data, "name")
    region_code = required(data, "region_code")
    state_code = required(data, "state_code")
    if not isinstance(office_code, str) or not isinstance(name, str) or \
            not isinstance(region_code, str) or not isinstance(state_code, str):
        from errors import ERR_INVALID_REQUEST
        raise err(ERR_INVALID_REQUEST, "office fields must be strings")
    for existing in db.district_offices.values():
        if existing["office_code"] == office_code:
            raise err(ERR_DUPLICATE_NATURAL_KEY,
                      "office_code %s is already in use" % office_code)
    rate = data.get("override_rate_pct")
    cap = data.get("override_cap_cents")
    row = {
        "office_code": office_code,
        "name": name,
        "region_code": region_code,
        "state_code": state_code,
        "override_rate_pct": float(calc.d(rate)) if rate is not None else 0.05,
        "override_cap_cents": int(cap) if cap is not None else calc.DEFAULT_OVERRIDE_CAP_CENTS,
        "override_paid_cents": 0,
        "status": "ACTIVE",
    }
    db.stamp_create(row)
    db.insert(db.district_offices, row)
    return ok(serialize.office(row), 201)


@bp.get("/agency/district-offices")
@authed(READ)
def list_offices(user_id, role):
    limit, offset = pagination()
    region_code = request.args.get("region_code")
    status = request.args.get("status")
    items = [o for o in db.district_offices.values()
             if (region_code is None or o["region_code"] == region_code)
             and (status is None or o["status"] == status)]
    selected = page(items, limit, offset)
    return ok_list([serialize.office(o) for o in selected], limit, offset, len(items))


@bp.get("/agency/district-offices/<office_id>")
@authed(READ)
def get_office(user_id, role, office_id):
    return ok(serialize.office(get(office_id)))


@bp.post("/agency/district-offices/<office_id>/suspend")
@authed(WRITE)
def suspend(user_id, role, office_id):
    office = get(office_id)
    if office["status"] == "CLOSED":
        raise err(ERR_ALREADY_TERMINAL, "a closed office admits no further transition")
    if office["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "the office is not ACTIVE")
    office["status"] = "SUSPENDED"
    db.touch(office)
    return ok(serialize.office(office))


@bp.post("/agency/district-offices/<office_id>/reactivate")
@authed(WRITE)
def reactivate(user_id, role, office_id):
    office = get(office_id)
    if office["status"] == "CLOSED":
        raise err(ERR_ALREADY_TERMINAL, "a closed office admits no further transition")
    if office["status"] != "SUSPENDED":
        raise err(ERR_INVALID_STATE, "the office is not SUSPENDED")
    office["status"] = "ACTIVE"
    db.touch(office)
    return ok(serialize.office(office))


@bp.post("/agency/district-offices/<office_id>/close")
@authed(WRITE)
def close(user_id, role, office_id):
    office = get(office_id)
    if office["status"] == "CLOSED":
        raise err(ERR_ALREADY_TERMINAL, "the office is already closed")
    if office["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "the transition to CLOSED is declared only from ACTIVE")
    for advisor in db.advisors.values():
        if advisor["district_office_id"] == office_id and \
                advisor["contract_status"] in LIVE_CONTRACT_STATES:
            raise err(ERR_OFFICE_HAS_LIVE_ADVISORS,
                      "the office still holds advisors with live contracts")
    office["status"] = "CLOSED"
    db.touch(office)
    return ok(serialize.office(office))


@bp.get("/agency/district-offices/<office_id>/advisors")
@authed(READ)
def office_advisors(user_id, role, office_id):
    get(office_id)
    limit, offset = pagination()
    contract_status = request.args.get("contract_status")
    items = [a for a in db.advisors.values()
             if a["district_office_id"] == office_id
             and (contract_status is None or a["contract_status"] == contract_status)]
    selected = page(items, limit, offset)
    return ok_list([serialize.advisor(a) for a in selected], limit, offset, len(items))


@bp.get("/agency/district-offices/<office_id>/recruiting-candidates")
@authed(READ)
def office_candidates(user_id, role, office_id):
    get(office_id)
    limit, offset = pagination()
    stage = request.args.get("stage")
    items = [c for c in db.candidates.values()
             if c["district_office_id"] == office_id
             and (stage is None or c["stage"] == stage)]
    selected = page(items, limit, offset)
    return ok_list([serialize.candidate(c) for c in selected], limit, offset, len(items))