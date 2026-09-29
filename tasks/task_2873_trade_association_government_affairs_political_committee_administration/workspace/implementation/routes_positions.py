"""Policy position, ballot round, tally and adoption endpoints (PRD 3.3, 3.4)."""
from flask import Blueprint, g

import derive
from constants import ALL_ROLES, API_PREFIX, BALLOTS, JURISDICTIONS, MAX_BALLOT_ROUNDS
from core import (
    arg, authenticate, body, fail, filtered, format_instant, insert, int_arg, iso_date,
    member_scope, now_dt, respond, touch,
)
from serializers import dump, listing
from validate import get_date, get_enum, get_str

bp = Blueprint("positions", __name__, url_prefix=API_PREFIX)

ACTIVITY_LIST_ROLES = ["GovAffairsDirector", "ComplianceOfficer", "BoardTrustee"]


def _position(position_id):
    return derive.lookup("positions", position_id, "ERR_POSITION_NOT_FOUND")


def _committee_of(position):
    return derive.lookup("committees", position["committee_id"], "ERR_COMMITTEE_NOT_FOUND")


@bp.post("/policy-positions")
def draft_position():
    authenticate(["GovAffairsDirector"])
    payload = body()
    committee_id = get_str(payload, "committee_id")
    title = get_str(payload, "title", max_len=200)
    jurisdiction_code = get_enum(payload, "jurisdiction_code", JURISDICTIONS)
    summary = get_str(payload, "summary", max_len=2000)
    committee = derive.lookup("committees", committee_id, "ERR_COMMITTEE_NOT_FOUND")
    scope = committee["jurisdiction_scope"]
    if scope != "MULTI" and scope != jurisdiction_code:
        fail("ERR_JURISDICTION_SCOPE_MISMATCH",
             "Committee scope %s does not cover jurisdiction %s." % (scope, jurisdiction_code))
    position = insert("positions", {
        "committee_id": committee_id,
        "title": title,
        "jurisdiction_code": jurisdiction_code,
        "summary": summary,
        "status": "DRAFT",
        "round_number": 0,
        "ballot_deadline_date": None,
        "support_weight": 0,
        "oppose_weight": 0,
        "abstain_weight": 0,
        "quorum_pct": 0.0,
        "consensus_pct": 0.0,
        "last_tally_outcome": "NONE",
        "dissent_register_count": 0,
        "adopted_at": None,
    })
    return respond(dump("positions", position), status=201)


@bp.get("/policy-positions/<position_id>")
def read_position(position_id):
    authenticate(ALL_ROLES)
    return respond(dump("positions", _position(position_id)))


@bp.post("/policy-positions/<position_id>/open-ballot")
def open_ballot(position_id):
    authenticate(["GovAffairsDirector"])
    position = _position(position_id)
    payload = body()
    deadline = get_date(payload, "ballot_deadline_date", required=False)
    # Rank 8: FAILED_CONSENSUS is deferred to the rank-25 ballot-bookkeeping gate.
    if position["status"] not in ("DRAFT", "RECONSIDERATION", "FAILED_CONSENSUS"):
        fail("ERR_INVALID_POSITION_STATE",
             "A ballot round cannot be opened from %s." % position["status"])
    committee = _committee_of(position)
    if committee["roster_state"] == "FORMING":
        fail("ERR_COMMITTEE_FORMING", "The committee roster is still forming.")
    if position["status"] == "FAILED_CONSENSUS" or position["round_number"] >= MAX_BALLOT_ROUNDS:
        fail("ERR_MAX_BALLOT_ROUNDS", "This position has exhausted its three ballot rounds.")
    position["round_number"] = position["round_number"] + 1
    if deadline is not None:
        position["ballot_deadline_date"] = iso_date(deadline)
    position["support_weight"] = 0
    position["oppose_weight"] = 0
    position["abstain_weight"] = 0
    position["quorum_pct"] = 0.0
    position["consensus_pct"] = 0.0
    position["last_tally_outcome"] = "NONE"
    position["status"] = "BALLOTING"
    for vote in derive.position_votes(position_id):
        if vote["round_number"] < position["round_number"] and vote["ballot_status"] == "CAST":
            vote["ballot_status"] = "SUPERSEDED"
            touch(vote)
    touch(position)
    return respond(dump("positions", position))


@bp.post("/policy-positions/<position_id>/votes")
def cast_ballot(position_id):
    authenticate(["MemberDelegate"])
    position = _position(position_id)
    payload = body()
    ballot = get_enum(payload, "ballot", BALLOTS)
    dissent_statement = get_str(payload, "dissent_statement", required=False, max_len=1000,
                                allow_blank=True)
    if position["status"] != "BALLOTING":
        fail("ERR_INVALID_POSITION_STATE",
             "Ballots may only be cast while the position is BALLOTING.")
    seat = derive.seat_for(position["committee_id"], g.user_id)
    if seat is None or seat["status"] not in ("ACTIVE", "DAMPENED"):
        fail("ERR_MEMBER_NOT_SEATED", "The caller holds no seat on this position's committee.")
    member = derive.lookup("members", g.user_id, "ERR_MEMBER_NOT_SEATED")
    if member["status"] != "ACTIVE":
        fail("ERR_MEMBER_NOT_ACTIVE", "The acting member is not ACTIVE.")
    has_dissent = bool(dissent_statement and dissent_statement.strip())
    if has_dissent and ballot != "OPPOSE":
        fail("ERR_DISSENT_REQUIRES_OPPOSE",
             "A dissent statement is only meaningful alongside an OPPOSE ballot.")
    for vote in derive.position_votes(position_id):
        if (vote["member_id"] == g.user_id
                and vote["round_number"] == position["round_number"]
                and vote["ballot_status"] == "CAST"):
            vote["ballot_status"] = "SUPERSEDED"
            touch(vote)
    vote = insert("votes", {
        "position_id": position_id,
        "member_id": g.user_id,
        "ballot": ballot,
        "dissent_statement": dissent_statement,
        "round_number": position["round_number"],
        "weight_snapshot": seat["voting_weight"],
        "ballot_status": "CAST",
        "dissent_status": "FILED" if has_dissent else "NONE",
    })
    return respond(dump("votes", vote), status=201)


@bp.get("/policy-positions/<position_id>/votes")
def list_votes(position_id):
    authenticate(ALL_ROLES)
    _position(position_id)
    rows = filtered(derive.position_votes(position_id),
                    round_number=int_arg("round_number"),
                    ballot_status=arg("ballot_status") or arg("status"))
    return listing("votes", rows)


@bp.post("/policy-positions/<position_id>/votes/<vote_id>/withdraw-dissent")
def withdraw_dissent(position_id, vote_id):
    authenticate(["MemberDelegate"])
    position = _position(position_id)
    vote = derive.lookup("votes", vote_id, "ERR_VOTE_NOT_FOUND")
    if vote["position_id"] != position_id:
        fail("ERR_VOTE_NOT_FOUND", "Ballot %s does not belong to this position." % vote_id)
    member_scope(vote["member_id"])
    if vote["dissent_status"] != "FILED":
        fail("ERR_DISSENT_NOT_FILED", "This ballot carries no FILED dissent.")
    if position["status"] not in ("BALLOTING", "RECONSIDERATION"):
        fail("ERR_INVALID_POSITION_STATE",
             "A dissent may only be withdrawn while the position is inside the ballot cycle.")
    vote["dissent_status"] = "WITHDRAWN"
    touch(vote)
    return respond(dump("votes", vote))


@bp.post("/policy-positions/<position_id>/tally")
def tally_round(position_id):
    authenticate(["GovAffairsDirector"])
    position = _position(position_id)
    if position["status"] != "BALLOTING":
        fail("ERR_INVALID_POSITION_STATE", "Only a BALLOTING position can be tallied.")
    if not derive.current_round_cast_votes(position):
        fail("ERR_NO_BALLOTS_CAST", "No ballot of the current round is still CAST.")
    committee = _committee_of(position)
    outcome = derive.compute_tally(position, committee)
    if outcome == "CONSENSUS":
        position["status"] = "CONSENSUS_REACHED"
    elif position["round_number"] < MAX_BALLOT_ROUNDS:
        position["status"] = "RECONSIDERATION"
    else:
        position["status"] = "FAILED_CONSENSUS"
    touch(position)
    return respond(dump("positions", position))


@bp.post("/policy-positions/<position_id>/adopt")
def adopt_position(position_id):
    authenticate(["BoardTrustee"])
    position = _position(position_id)
    if position["status"] != "CONSENSUS_REACHED":
        fail("ERR_INVALID_POSITION_STATE",
             "Only a position that reached consensus can be adopted.")
    committee = _committee_of(position)
    if committee["roster_state"] != "QUORATE":
        fail("ERR_COMMITTEE_NOT_QUORATE", "Adoption requires a QUORATE committee roster.")
    position["status"] = "ADOPTED"
    position["adopted_at"] = format_instant(now_dt())
    derive.adopt_cascade(position, committee)
    touch(position)
    snap = derive.snapshot(committee, derive.COMMITTEE_TRACKED)
    derive.compute_committee_roster(committee)
    derive.touch_if_changed(committee, snap)
    return respond(dump("positions", position))


@bp.get("/policy-positions/<position_id>/lobbying-activities")
def list_position_activities(position_id):
    authenticate(ACTIVITY_LIST_ROLES)
    _position(position_id)
    rows = filtered(derive.where("activities", position_id=position_id), status=arg("status"))
    return listing("activities", rows)


@bp.get("/policy-positions/<position_id>/grassroots-campaigns")
def list_position_campaigns(position_id):
    authenticate(ALL_ROLES)
    _position(position_id)
    rows = filtered(derive.where("campaigns", position_id=position_id), status=arg("status"))
    return listing("campaigns", rows)
