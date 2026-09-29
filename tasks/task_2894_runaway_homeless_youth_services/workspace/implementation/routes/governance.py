"""Youth voice in program governance: proposals, votes and the adoption tally.

PRD 3.9. Opening and listing a program's proposals live on the program-scoped
routes; this module owns the proposal read, the ballot and the close-out.
"""

from flask import Blueprint

import authz
import calc
import envelope
import find
import serial
import shape
import store
from errors import fail

bp = Blueprint("governance", __name__)

STANCES = ("SUPPORT", "OPPOSE")
VOTE_STATUSES = ("COUNTED", "RETRACTED")
VOTE_READERS = (
    authz.PROGRAM_ADMIN,
    authz.SHELTER_CASE_MANAGER,
    authz.TLP_COORDINATOR,
    authz.REUNIFICATION_SPECIALIST,
    authz.YOUTH_MEMBER,
)


def _count_field(stance):
    return "support_vote_count" if stance == "SUPPORT" else "oppose_vote_count"


@bp.get("/ryhs/governance-proposals/<proposal_id>")
def read_proposal(proposal_id):
    authz.require(*(authz.STAFF_READ_ALL + (authz.YOUTH_MEMBER,)))
    proposal = find.proposal(proposal_id)
    return envelope.ok(serial.proposal(proposal))


@bp.post("/ryhs/governance-proposals/<proposal_id>/votes")
def cast_vote(proposal_id):
    user_id, _role = authz.require(authz.YOUTH_MEMBER)
    proposal = find.proposal(proposal_id)
    body = shape.body()
    stance = shape.need_enum(body, "stance", STANCES)

    # Ladder 17.
    if proposal["status"] != "OPEN_FOR_VOTE":
        fail("ERR_PROPOSAL_ALREADY_DECIDED")
    # Ladder 38 - a retracted vote does not block a fresh one.
    for vote in store.governance_votes.values():
        if (
            vote["proposal_id"] == proposal["id"]
            and vote["youth_id"] == user_id
            and vote["status"] == "COUNTED"
        ):
            fail("ERR_DUPLICATE_VOTE")
    # Ladder 39 - the voter must be a vote-eligible resident of the program.
    youth = store.youths.get(user_id)
    if (
        youth is None
        or not youth["governance_vote_eligible"]
        or not calc.is_resident(youth["id"], proposal["program_id"])
    ):
        fail("ERR_YOUTH_NOT_VOTE_ELIGIBLE")
    # Ladder 40 - the deadline is inclusive; only a clock strictly past it closes.
    if store.now() > proposal["voting_closes_at"]:
        fail("ERR_PROPOSAL_VOTE_CLOSED")

    vote = store.stamp_new(
        {
            "proposal_id": proposal["id"],
            "youth_id": user_id,
            "stance": stance,
            "status": "COUNTED",
            "cast_at": store.now(),
            "retracted_at": None,
        }
    )
    store.governance_votes[vote["id"]] = vote

    proposal[_count_field(stance)] += 1
    store.touch(proposal)
    return envelope.created(serial.vote(vote))


@bp.get("/ryhs/governance-proposals/<proposal_id>/votes")
def list_proposal_votes(proposal_id):
    authz.require(*VOTE_READERS)
    proposal = find.proposal(proposal_id)
    status = envelope.enum_filter("status", VOTE_STATUSES)
    envelope.page_args()
    rows = [
        v
        for v in store.governance_votes.values()
        if v["proposal_id"] == proposal["id"] and (status is None or v["status"] == status)
    ]
    return envelope.listing(store.ordered(rows), serial.vote)


@bp.post("/ryhs/governance-votes/<vote_id>/retract")
def retract_vote(vote_id):
    user_id, role = authz.require(authz.YOUTH_MEMBER)
    vote = find.vote(vote_id)
    # Ladder 3 - "a vote may only be retracted by the youth who cast it".
    authz.own_youth(user_id, role, vote["youth_id"])

    proposal = store.governance_proposals.get(vote["proposal_id"])
    if proposal is not None:
        # Ladder 17 then 40 - the same gates as casting.
        if proposal["status"] != "OPEN_FOR_VOTE":
            fail("ERR_PROPOSAL_ALREADY_DECIDED")
        if store.now() > proposal["voting_closes_at"]:
            fail("ERR_PROPOSAL_VOTE_CLOSED")

    if vote["status"] != "COUNTED":
        # Already retracted: the tally is already restored, so nothing moves.
        return envelope.ok(serial.vote(vote))

    vote["status"] = "RETRACTED"
    vote["retracted_at"] = store.now()
    store.touch(vote)
    if proposal is not None:
        field = _count_field(vote["stance"])
        proposal[field] = max(0, proposal[field] - 1)
        store.touch(proposal)
    return envelope.ok(serial.vote(vote))


@bp.post("/ryhs/governance-proposals/<proposal_id>/close-vote")
def close_vote(proposal_id):
    user_id, _role = authz.require(authz.PROGRAM_ADMIN)
    proposal = find.proposal(proposal_id)

    # Ladder 17 - a second close attempt is refused.
    if proposal["status"] != "OPEN_FOR_VOTE":
        fail("ERR_PROPOSAL_ALREADY_DECIDED")

    support, oppose = calc.proposal_tally(proposal)
    electorate = calc.electorate_size(proposal["program_id"])
    # Ladder 41 - "an empty electorate is not a decision at all": nothing is frozen,
    # nothing is changed, and the proposal remains OPEN_FOR_VOTE.
    if electorate <= 0:
        fail("ERR_NO_ELIGIBLE_ELECTORATE")

    support_ratio_bp = calc.floor_div(support * 10000, electorate)
    proposal["support_vote_count"] = support
    proposal["oppose_vote_count"] = oppose
    proposal["eligible_electorate_size"] = electorate
    proposal["support_ratio_bp"] = support_ratio_bp
    proposal["decided_by_user_id"] = user_id
    if support_ratio_bp >= calc.ADOPTION_RATIO_BP and support >= calc.ADOPTION_MIN_SUPPORT:
        proposal["status"] = "ADOPTED"
        proposal["adopted_at"] = store.now()
    else:
        proposal["status"] = "REJECTED"
    store.touch(proposal)
    return envelope.ok(serial.proposal(proposal))
