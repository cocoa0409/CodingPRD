"""Council quorum arithmetic and proposal auto-resolution."""
from test_helpers import (
    validate_error, get_success_data,
    setup_submitted_proposal, cast_votes,
    ApiErrorId, TEST_USERS, make_franchisee_admin_headers,
)

OPS = TEST_USERS["franchisor_ops_headers"]


def test_third_approve_at_quorum_five_flips_proposal_to_approved(api):
    """PRD §3.6: "The council's `quorum_votes` is derived as the floor of half
    the seat count plus one, recomputed whenever `seat_count` changes"
    PRD §3.6: "Resolution is automatic at quorum: the moment `approvals` reaches
    the council's `quorum_votes` the proposal transitions `SUBMITTED` →
    `APPROVED`, and the moment `rejections` reaches that same quorum it
    transitions `SUBMITTED` → `REJECTED`. The comparison is inclusive — a
    proposal resolves at exactly quorum, never only beyond it."

    Design: Difficulty/combinatorial_formula/quorum_threshold_branching_on_odd_seats
    """
    ctx = setup_submitted_proposal(seat_count=5, amount_cents=1_000_000)
    assert ctx["council"]["quorum_votes"] == 3

    proposal_id = ctx["proposal"]["id"]
    members = [b["id"] for b in ctx["brokerages"]]
    first = get_success_data(
        api.cast_vote(proposal_id, {"vote": "APPROVE"}, make_franchisee_admin_headers(members[0]))
    )
    assert first["approvals"] == 1 and first["status"] == "SUBMITTED"
    second = get_success_data(
        api.cast_vote(proposal_id, {"vote": "APPROVE"}, make_franchisee_admin_headers(members[1]))
    )
    assert second["approvals"] == 2 and second["status"] == "SUBMITTED"
    third = get_success_data(
        api.cast_vote(proposal_id, {"vote": "APPROVE"}, make_franchisee_admin_headers(members[2]))
    )
    assert third["approvals"] == 3
    assert third["status"] == "APPROVED", "proposal must resolve at exactly quorum"


def test_votes_rejected_once_proposal_reached_terminal_state(api):
    """PRD §3.6: "Resolution is automatic at quorum: the moment `approvals` reaches
    the council's `quorum_votes` the proposal transitions `SUBMITTED` →
    `APPROVED`, and the moment `rejections` reaches that same quorum it
    transitions `SUBMITTED` → `REJECTED`."

    Design: Difficulty/combinatorial_formula/quorum_threshold_branching_on_odd_seats
    """
    ctx = setup_submitted_proposal(seat_count=5, amount_cents=1_000_000)
    proposal_id = ctx["proposal"]["id"]
    members = [b["id"] for b in ctx["brokerages"]]
    cast_votes(proposal_id, members[:3], "APPROVE")  # resolves at quorum 3

    resp = api.cast_vote(
        proposal_id, {"vote": "APPROVE"}, make_franchisee_admin_headers(members[3])
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_rejected_proposal_locks_further_votes(api):
    """PRD §3.6: "the moment `rejections` reaches that same quorum it transitions
    `SUBMITTED` → `REJECTED`. The comparison is inclusive — a proposal resolves
    at exactly quorum, never only beyond it."

    Design: Corner/state_machines/terminal_proposal_rejected_locks_further_votes
    """
    ctx = setup_submitted_proposal(seat_count=3, amount_cents=1_000)
    proposal_id = ctx["proposal"]["id"]
    members = [b["id"] for b in ctx["brokerages"]]
    last = cast_votes(proposal_id, members[:2], "REJECT")[-1]
    assert last["status"] == "REJECTED"

    resp = api.cast_vote(
        proposal_id, {"vote": "APPROVE"}, make_franchisee_admin_headers(members[2])
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
