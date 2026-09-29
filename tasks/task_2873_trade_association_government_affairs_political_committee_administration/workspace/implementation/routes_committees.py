"""Policy committee and seat endpoints (PRD 3.2)."""
from flask import Blueprint

import derive
from constants import ALL_ROLES, API_PREFIX, JURISDICTION_SCOPES, SEAT_ROLES, TIER_WEIGHT
from core import arg, authenticate, body, filtered, insert, respond
from serializers import dump, listing
from validate import get_enum, get_pct, get_str

bp = Blueprint("committees", __name__, url_prefix=API_PREFIX)


@bp.post("/committees")
def create_committee():
    authenticate(["GovAffairsDirector"])
    payload = body()
    name = get_str(payload, "name", max_len=200)
    jurisdiction_scope = get_enum(payload, "jurisdiction_scope", JURISDICTION_SCOPES)
    quorum_threshold_pct = get_pct(payload, "quorum_threshold_pct")
    consensus_threshold_pct = get_pct(payload, "consensus_threshold_pct")
    committee = insert("committees", {
        "name": name,
        "jurisdiction_scope": jurisdiction_scope,
        "quorum_threshold_pct": float(quorum_threshold_pct),
        "consensus_threshold_pct": float(consensus_threshold_pct),
        "seat_count": 0,
        "total_voting_weight": 0,
        "roster_state": "FORMING",
    })
    return respond(dump("committees", committee), status=201)


@bp.get("/committees/<committee_id>")
def read_committee(committee_id):
    authenticate(ALL_ROLES)
    committee = derive.lookup("committees", committee_id, "ERR_COMMITTEE_NOT_FOUND")
    return respond(dump("committees", committee))


@bp.post("/committees/<committee_id>/seats")
def seat_member(committee_id):
    authenticate(["GovAffairsDirector"])
    committee = derive.lookup("committees", committee_id, "ERR_COMMITTEE_NOT_FOUND")
    payload = body()
    member_id = get_str(payload, "member_id")
    seat_role = get_enum(payload, "seat_role", SEAT_ROLES, required=False, default="MEMBER")
    member = derive.lookup("members", member_id, "ERR_MEMBER_NOT_FOUND")
    existing = derive.committee_seats(committee_id)
    for seat in existing:
        if seat["member_id"] == member_id:
            derive.fail("ERR_DUPLICATE_SEAT",
                        "Member %s already holds a seat on this committee." % member_id)
    if seat_role == "CHAIR":
        for seat in existing:
            if seat["seat_role"] == "CHAIR":
                derive.fail("ERR_CHAIR_SEAT_TAKEN", "This committee already has a chair.")
    seat = insert("seats", {
        "committee_id": committee_id,
        "member_id": member_id,
        "seat_role": seat_role,
        "voting_weight": TIER_WEIGHT[member["membership_tier"]],
        "status": "ACTIVE",
        "dissent_strikes": 0,
    })
    snap = derive.snapshot(committee, derive.COMMITTEE_TRACKED)
    derive.compute_committee_roster(committee)
    derive.touch_if_changed(committee, snap)
    return respond(dump("seats", seat), status=201)


@bp.get("/committees/<committee_id>/seats")
def list_seats(committee_id):
    authenticate(ALL_ROLES)
    derive.lookup("committees", committee_id, "ERR_COMMITTEE_NOT_FOUND")
    rows = filtered(derive.committee_seats(committee_id), status=arg("status"))
    return listing("seats", rows)


@bp.get("/committees/<committee_id>/policy-positions")
def list_committee_positions(committee_id):
    authenticate(ALL_ROLES)
    derive.lookup("committees", committee_id, "ERR_COMMITTEE_NOT_FOUND")
    rows = filtered(derive.where("positions", committee_id=committee_id), status=arg("status"))
    return listing("positions", rows)
