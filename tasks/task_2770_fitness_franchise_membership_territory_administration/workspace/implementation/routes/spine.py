"""The franchise spine: logical clock, franchisees, territories, clubs, relocation."""
from flask import Blueprint

import calc
import cascade
import config
import validate as v
from auth import guard, require_owner
from envelope import ok, created
from errors import ApiError
from helpers import (ALL_ROLES, get_club, get_franchisee, get_relocation, get_territory, paged)
from store import db, common_fields, clock_date_str, touch, public

bp = Blueprint("spine", __name__)

ADMIN = ["BrandAdministrator"]
OWNER = ["FranchiseOwner"]


# --------------------------------------------------------------------------
# logical clock (outside the /franchise prefix)
# --------------------------------------------------------------------------
@bp.post("/_clock/set_current_utc")
def set_clock():
    guard(ADMIN)
    b = v.body()
    instant = v.req_datetime(b, "current_utc")
    db.clock = instant
    return ok({"current_utc": b["current_utc"]})


# --------------------------------------------------------------------------
# franchisees
# --------------------------------------------------------------------------
@bp.post("/franchise/franchisees")
def create_franchisee():
    guard(ADMIN)
    b = v.body()
    legal_name = v.req_str(b, "legal_name", min_len=1, max_len=120)
    contact_email = v.req_str(b, "contact_email")
    royalty_rate_bps = v.opt_int(b, "royalty_rate_bps", default=650, minimum=0, maximum=1200)
    eligible = v.opt_bool(b, "national_account_eligible", default=True)

    record = common_fields()
    record.update({
        "legal_name": legal_name,
        "contact_email": contact_email,
        "royalty_rate_bps": royalty_rate_bps,
        "status": "ACTIVE",
        "inspection_fail_streak": 0,
        "collections_watch_club_count": 0,
        "disputed_royalty_count": 0,
        "compliance_score": 100,
        "corporate_allocation_cents": 0,
        "national_account_eligible": eligible,
    })
    db.franchisees[record["id"]] = record
    return created(record)


@bp.post("/franchise/franchisees/<fid>/reinstate")
def reinstate_franchisee(fid):
    guard(ADMIN)
    b = v.body()
    v.opt_str(b, "note")
    franchisee = get_franchisee(fid)
    cascade.recompute_franchisee(franchisee, bump="never")
    if (franchisee["status"] != "PROBATION"
            or franchisee["compliance_score"] < config.PROBATION_SCORE_THRESHOLD):
        raise ApiError("ERR_FRANCHISEE_ON_PROBATION")
    franchisee["status"] = "ACTIVE"
    touch(franchisee)
    return ok(franchisee)


@bp.get("/franchise/franchisees/<fid>")
def read_franchisee(fid):
    guard(ALL_ROLES)
    return ok(get_franchisee(fid))


@bp.get("/franchise/franchisees")
def list_franchisees():
    guard(ALL_ROLES)
    return paged(db.franchisees, "status", "national_account_eligible")


# --------------------------------------------------------------------------
# territories
# --------------------------------------------------------------------------
def _candidate_territories(franchisee_id, exclude_territory_id=None):
    return [t for t in db.territories.values()
            if t["franchisee_id"] != franchisee_id
            and t["status"] in ("RESERVED", "ACTIVE")
            and t["id"] != exclude_territory_id]


@bp.post("/franchise/territories")
def create_territory():
    guard(ADMIN)
    b = v.body()
    franchisee_id = v.req_id(b, "franchisee_id")
    center_lat = v.req_lat(b, "center_lat")
    center_lng = v.req_lng(b, "center_lng")
    radius = v.req_radius(b, "protected_radius_km")
    state_code = v.req_enum(b, "state_code", config.STATE_CODES)

    get_franchisee(franchisee_id)

    clearance = calc.encroachment_clearance(center_lat, center_lng, radius,
                                            _candidate_territories(franchisee_id))
    if clearance is not None and clearance < 0:
        raise ApiError("ERR_TERRITORY_ENCROACHMENT")

    record = common_fields()
    record.update({
        "franchisee_id": franchisee_id,
        "center_lat": float(center_lat),
        "center_lng": float(center_lng),
        "protected_radius_km": float(radius),
        "state_code": state_code,
        "status": "RESERVED",
        "relocation_count": 0,
    })
    db.territories[record["id"]] = record
    return created(record)


@bp.get("/franchise/territories/<tid>")
def read_territory(tid):
    guard(ALL_ROLES)
    return ok(get_territory(tid))


@bp.get("/franchise/territories")
def list_territories():
    guard(ALL_ROLES)
    return paged(db.territories, "franchisee_id", "state_code", "status")


# --------------------------------------------------------------------------
# clubs
# --------------------------------------------------------------------------
@bp.post("/franchise/clubs")
def create_club():
    uid, role = guard(["BrandAdministrator", "FranchiseOwner"])
    b = v.body()

    # band 3: ownership of the named territory, resolved silently
    if role == "FranchiseOwner":
        raw = b.get("territory_id")
        parent = db.territories.get(raw) if isinstance(raw, str) else None
        if parent is not None:
            require_owner(parent["franchisee_id"] == uid)

    territory_id = v.req_id(b, "territory_id")
    name = v.req_str(b, "name")
    opened_on = v.req_date(b, "opened_on")
    guest_fee = v.opt_int(b, "guest_fee_cents", default=1250, minimum=0, maximum=5000)

    territory = get_territory(territory_id)
    if territory["status"] != "RESERVED":
        raise ApiError("ERR_INVALID_TERRITORY_STATE")
    if any(c["territory_id"] == territory_id for c in db.clubs.values()):
        raise ApiError("ERR_TERRITORY_OCCUPIED")

    record = common_fields()
    record.update({
        "territory_id": territory_id,
        "franchisee_id": territory["franchisee_id"],
        "name": name,
        "state_code": territory["state_code"],
        "lat": territory["center_lat"],
        "lng": territory["center_lng"],
        "opened_on": opened_on,
        "guest_fee_cents": guest_fee,
        "status": "PRE_OPENING",
        "equipment_compliance_state": "COMPLIANT",
        "last_inspection_score": None,
        "active_agreement_count": 0,
        "delinquent_member_count": 0,
        "collections_watch": False,
        "settlement_ledger_cents": 0,
    })
    db.clubs[record["id"]] = record
    return created(record)


@bp.post("/franchise/clubs/<cid>/open")
def open_club(cid):
    uid, role = guard(OWNER)
    club = db.clubs.get(cid)
    if club is not None:
        require_owner(club["franchisee_id"] == uid)
    b = v.body()
    v.opt_str(b, "note")
    club = get_club(cid)

    if club["status"] != "PRE_OPENING":
        raise ApiError("ERR_CLUB_NOT_OPERATIONAL")
    if any(r["club_id"] == cid and r["status"] in config.OPEN_RELOCATION_STATES
           for r in db.relocation_requests.values()):
        raise ApiError("ERR_RELOCATION_PENDING")

    club["status"] = "OPEN"
    touch(club)
    territory = db.territories.get(club["territory_id"])
    if territory is not None and territory["status"] == "RESERVED":
        territory["status"] = "ACTIVE"
        touch(territory)
    return ok(club)


@bp.get("/franchise/clubs/<cid>")
def read_club(cid):
    guard(ALL_ROLES)
    return ok(get_club(cid))


@bp.get("/franchise/clubs")
def list_clubs():
    guard(ALL_ROLES)
    return paged(db.clubs, "territory_id", "franchisee_id", "state_code", "status",
                 "equipment_compliance_state")


# --------------------------------------------------------------------------
# relocation requests
# --------------------------------------------------------------------------
def _clearance_for(request_record, club):
    territory = db.territories.get(club["territory_id"])
    exclude = territory["id"] if territory else None
    candidates = _candidate_territories(club["franchisee_id"], exclude_territory_id=exclude)
    return calc.encroachment_clearance(request_record["requested_lat"],
                                       request_record["requested_lng"],
                                       request_record["requested_radius_km"],
                                       candidates)


@bp.post("/franchise/relocation-requests")
def create_relocation():
    uid, role = guard(OWNER)
    b = v.body()

    raw = b.get("club_id")
    parent = db.clubs.get(raw) if isinstance(raw, str) else None
    if parent is not None:
        require_owner(parent["franchisee_id"] == uid)

    club_id = v.req_id(b, "club_id")
    lat = v.req_lat(b, "requested_lat")
    lng = v.req_lng(b, "requested_lng")
    radius = v.req_radius(b, "requested_radius_km")
    justification = v.req_str(b, "justification")

    get_club(club_id)
    if any(r["club_id"] == club_id and r["status"] in config.OPEN_RELOCATION_STATES
           for r in db.relocation_requests.values()):
        raise ApiError("ERR_RELOCATION_PENDING")

    record = common_fields()
    record.update({
        "club_id": club_id,
        "requested_lat": float(lat),
        "requested_lng": float(lng),
        "requested_radius_km": float(radius),
        "justification": justification,
        "status": "DRAFT",
        "revision_count": 0,
        "encroachment_km": None,
        "submitted_by_user_id": None,
        "decided_by_user_id": None,
        "reviewer_note": None,
    })
    db.relocation_requests[record["id"]] = record
    return created(record)


@bp.post("/franchise/relocation-requests/<rid>/submit")
def submit_relocation(rid):
    uid, role = guard(OWNER)
    record = db.relocation_requests.get(rid)
    if record is not None:
        club = db.clubs.get(record["club_id"])
        if club is not None:
            require_owner(club["franchisee_id"] == uid)

    b = v.body()
    lat = v.opt_decimal(b, "requested_lat", minimum=-90, maximum=90)
    lng = v.opt_decimal(b, "requested_lng", minimum=-180, maximum=180)
    radius = None
    if v.present(b, "requested_radius_km"):
        radius = v.req_radius(b, "requested_radius_km")

    record = get_relocation(rid)
    if record["status"] not in ("DRAFT", "CHANGES_REQUESTED"):
        raise ApiError("ERR_INVALID_RELOCATION_STATE")

    resubmission = record["status"] == "CHANGES_REQUESTED"
    if resubmission and record["revision_count"] + 1 > config.RELOCATION_REVISION_LIMIT:
        raise ApiError("ERR_RELOCATION_REVISION_LIMIT")

    if lat is not None:
        record["requested_lat"] = float(lat)
    if lng is not None:
        record["requested_lng"] = float(lng)
    if radius is not None:
        record["requested_radius_km"] = float(radius)

    if resubmission:
        record["revision_count"] += 1

    club = get_club(record["club_id"])
    clearance = _clearance_for(record, club)
    record["encroachment_km"] = None if clearance is None else float(clearance)
    record["status"] = "SUBMITTED"
    record["submitted_by_user_id"] = uid
    touch(record)
    return ok(record)


@bp.post("/franchise/relocation-requests/<rid>/request-changes")
def request_changes_relocation(rid):
    guard(ADMIN)
    b = v.body()
    note = v.req_str(b, "reviewer_note")
    record = get_relocation(rid)
    if record["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_RELOCATION_STATE")
    record["status"] = "CHANGES_REQUESTED"
    record["reviewer_note"] = note
    touch(record)
    return ok(record)


@bp.post("/franchise/relocation-requests/<rid>/decide")
def decide_relocation(rid):
    uid, role = guard(ADMIN)
    b = v.body()
    decision = v.req_enum(b, "decision", ("APPROVE", "REJECT"))
    note = v.opt_str(b, "reviewer_note")
    record = get_relocation(rid)

    if record["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_RELOCATION_STATE")
    if record["submitted_by_user_id"] is not None and record["submitted_by_user_id"] == uid:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    club = get_club(record["club_id"])

    if decision == "APPROVE":
        clearance = _clearance_for(record, club)
        if clearance is not None and clearance < 0:
            raise ApiError("ERR_TERRITORY_ENCROACHMENT")
        territory = db.territories.get(club["territory_id"])
        if territory is not None:
            territory["center_lat"] = record["requested_lat"]
            territory["center_lng"] = record["requested_lng"]
            territory["protected_radius_km"] = record["requested_radius_km"]
            territory["relocation_count"] += 1
            touch(territory)
        club["lat"] = record["requested_lat"]
        club["lng"] = record["requested_lng"]
        touch(club)
        record["status"] = "APPROVED"
    else:
        record["status"] = "REJECTED"

    record["decided_by_user_id"] = uid
    if note is not None:
        record["reviewer_note"] = note
    touch(record)
    return ok(record)


@bp.post("/franchise/relocation-requests/<rid>/withdraw")
def withdraw_relocation(rid):
    uid, role = guard(OWNER)
    record = db.relocation_requests.get(rid)
    if record is not None:
        club = db.clubs.get(record["club_id"])
        if club is not None:
            require_owner(club["franchisee_id"] == uid)
    b = v.body()
    v.opt_str(b, "reason")
    record = get_relocation(rid)
    if record["status"] not in ("DRAFT", "CHANGES_REQUESTED"):
        raise ApiError("ERR_INVALID_RELOCATION_STATE")
    record["status"] = "WITHDRAWN"
    touch(record)
    return ok(record)


@bp.get("/franchise/relocation-requests/<rid>")
def read_relocation(rid):
    guard(ALL_ROLES)
    return ok(get_relocation(rid))


@bp.get("/franchise/relocation-requests")
def list_relocations():
    guard(ALL_ROLES)
    return paged(db.relocation_requests, "club_id", "status")
