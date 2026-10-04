"""Rule proposals, ballots, tallying, and the promulgation pipeline —
PRD §2.1, §3.3, §3.4.
"""

from test_helpers import (
    ApiErrorId,
    cast_ballot,
    close_ballot,
    compute_ballot_outcome,
    create_active_participant,
    create_participant,
    create_passed_proposal,
    create_proposal_in_balloting,
    create_rule_proposal,
    create_web_transaction_code,
    make_participant_officer_headers,
    make_voting_delegate_headers,
    open_comment_period,
    recast_ballot,
    set_clock,
    transition_proposal,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_rule_proposal_rework_cycle_resets_tallies(api, admin_headers):
    """PRD §3.3: "Moving from `COMMENT_OPEN` to `BALLOTING` then requires the
    comment period to have run its course: the logical date must be at least
    thirty days after the date the comment period opened, and an early move is
    rejected with `ERR_COMMENT_PERIOD_TOO_SHORT`."
    PRD §3.4: "A proposal in `BALLOTING` may instead be sent back as
    `RETURNED_FOR_REWORK`, which likewise locks all of its `CAST` ballots; a
    reworked proposal returning from `RETURNED_FOR_REWORK` to `DRAFT` has its
    `yea_count`, `nay_count`, and `abstain_count` reset to zero and its
    `outcome` reset to null, ready to run the pipeline again."

    Design: Difficulty/non_linear_state_machine/rule_proposal_rework_cycle_resets_tallies
    """
    set_clock("2026-09-01T09:00:00Z")
    voter = create_active_participant(participant_type="BOTH", routing_number="111000025")
    code = create_web_transaction_code()
    proposal = create_rule_proposal(code, effective_date="2027-01-01")
    proposal = open_comment_period(proposal)

    set_clock("2026-09-15T09:00:00Z")
    early = api.transition_rule_proposal(
        proposal["id"], {"to_state": "BALLOTING"}, admin_headers
    )
    validate_error(early, ApiErrorId.ERR_COMMENT_PERIOD_TOO_SHORT)

    set_clock("2026-10-01T09:00:00Z")
    transition_proposal(proposal["id"], "BALLOTING")
    ballot = cast_ballot(proposal["id"], voter, "YEA")

    transition_proposal(proposal["id"], "RETURNED_FOR_REWORK")
    reworked = transition_proposal(proposal["id"], "DRAFT")
    assert reworked["status"] == "DRAFT"
    assert reworked["yea_count"] == 0
    assert reworked["nay_count"] == 0
    assert reworked["abstain_count"] == 0
    assert reworked["outcome"] is None

    set_clock("2026-10-02T09:00:00Z")
    reopened = transition_proposal(proposal["id"], "COMMENT_OPEN")
    assert reopened["status"] == "COMMENT_OPEN"

    locked = validate_success(api.get_ballot(ballot["id"], admin_headers))
    assert locked["status"] == "LOCKED"


def test_cast_then_recast_conserves_ballot_count(api, admin_headers):
    """PRD §3.3: "A successful recast refreshes `cast_at`, decrements the old
    vote's counter and increments the new vote's counter on the proposal (the
    total number of cast ballots is unchanged), and increments the ballot's
    `version` by one."

    Design: Difficulty/compensating_invariant/cast_then_recast_conserves_ballot_count
    """
    set_clock("2026-09-01T09:00:00Z")
    voter = create_active_participant(participant_type="BOTH", routing_number="111000025")
    code = create_web_transaction_code()
    proposal = create_proposal_in_balloting(code, effective_date="2027-01-01")

    ballot = cast_ballot(proposal["id"], voter, "YEA")
    mid = validate_success(api.get_rule_proposal(proposal["id"], admin_headers))
    assert (mid["yea_count"], mid["nay_count"], mid["abstain_count"]) == (1, 0, 0)

    recast = recast_ballot(ballot["id"], voter, "ABSTAIN")
    assert recast["vote"] == "ABSTAIN"
    assert recast["version"] == ballot["version"] + 1

    after = validate_success(api.get_rule_proposal(proposal["id"], admin_headers))
    assert (after["yea_count"], after["nay_count"], after["abstain_count"]) == (0, 0, 1)
    assert (
        after["yea_count"] + after["nay_count"] + after["abstain_count"]
        == mid["yea_count"] + mid["nay_count"] + mid["abstain_count"]
        == 1
    )

    ballots, meta = validate_paginated(
        api.list_ballots(
            admin_headers,
            params={"rule_proposal_id": proposal["id"], "participant_id": voter["id"]},
        )
    )
    assert len(ballots) == 1 and meta["total_count"] == 1


def test_proposal_close_ballot_before_period_rejected(api, admin_headers):
    """PRD §3.4: "Closing the ballot is the decisive act of the rulemaking
    pipeline, and it cannot happen early: the logical date must be at least
    fourteen days after the date balloting opened, and a premature close is
    rejected with `ERR_BALLOT_PERIOD_NOT_CLOSED`."

    Design: Corner/state_machines/proposal_close_ballot_before_period_rejected
    """
    set_clock("2026-09-01T09:00:00Z")
    code = create_web_transaction_code()
    proposal = create_proposal_in_balloting(code, effective_date="2027-01-01")

    set_clock("2026-10-10T09:00:00Z")
    resp = api.close_ballot(proposal["id"], admin_headers)
    validate_error(resp, ApiErrorId.ERR_BALLOT_PERIOD_NOT_CLOSED)

    after = validate_success(api.get_rule_proposal(proposal["id"], admin_headers))
    assert after["status"] == "BALLOTING"
    assert after["outcome"] is None


def test_proposal_effective_before_date_rejected(api, admin_headers):
    """PRD §3.4: "Promulgation — moving from `PASSED` to `EFFECTIVE` — is gated
    on the calendar: the logical date must be on or after the proposal's
    `effective_date`, otherwise the transition is rejected with
    `ERR_EFFECTIVE_DATE_NOT_REACHED`."

    Design: Corner/state_machines/proposal_effective_before_date_rejected
    """
    set_clock("2026-09-01T09:00:00Z")
    voter = create_active_participant(participant_type="BOTH", routing_number="111000025")
    code = create_web_transaction_code()
    proposal = create_passed_proposal(
        code, votes=[(voter, "YEA")], effective_date="2026-10-20"
    )
    assert proposal["status"] == "PASSED"
    assert proposal["outcome"] == "PASSED_QUORUM"

    set_clock("2026-10-16T09:00:00Z")
    resp = api.transition_rule_proposal(
        proposal["id"], {"to_state": "EFFECTIVE"}, admin_headers
    )
    validate_error(resp, ApiErrorId.ERR_EFFECTIVE_DATE_NOT_REACHED)

    after = validate_success(api.get_rule_proposal(proposal["id"], admin_headers))
    assert after["status"] == "PASSED"


def test_ballot_after_close_cast_and_recast_rejected(api, admin_headers):
    """PRD §3.3: "The voting participant must be `ACTIVE` at cast time — a
    suspended or onboarding participant's ballot attempt fails with
    `ERR_PARTICIPANT_NOT_ACTIVE` — and casting against a proposal that is not
    in `BALLOTING` fails with `ERR_INVALID_STATE`."
    PRD §3.3: "A delegate may recast — change an existing ballot's `vote` — but
    only while the parent proposal remains in `BALLOTING` (otherwise
    `ERR_INVALID_STATE`)"
    PRD §3.4: "Either way, every ballot of the proposal still in `CAST` status
    transitions to `LOCKED` and the tallies freeze."

    Design: Corner/state_machines/ballot_after_close_cast_and_recast_rejected
    """
    set_clock("2026-09-01T09:00:00Z")
    voter1 = create_active_participant(participant_type="BOTH", routing_number="111000025")
    voter2 = create_active_participant(participant_type="ODFI", routing_number="222000039")
    code = create_web_transaction_code()
    proposal = create_proposal_in_balloting(code, effective_date="2027-01-01")
    ballot = cast_ballot(proposal["id"], voter1, "YEA")
    closed = close_ballot(proposal)
    assert closed["status"] == "PASSED"

    late_cast = api.cast_ballot(
        proposal["id"], {"vote": "NAY"}, make_voting_delegate_headers(voter2["id"])
    )
    validate_error(late_cast, ApiErrorId.ERR_INVALID_STATE)

    recast = api.recast_ballot(
        ballot["id"], {"vote": "NAY"}, make_voting_delegate_headers(voter1["id"])
    )
    validate_error(recast, ApiErrorId.ERR_INVALID_STATE)

    locked = validate_success(api.get_ballot(ballot["id"], admin_headers))
    assert locked["status"] == "LOCKED"
    assert locked["vote"] == "YEA"


def test_ballot_duplicate_cast_rejected(api, admin_headers):
    """PRD §3.3: "One ballot exists per (proposal, participant) pair: a second
    cast by the same participant on the same proposal is rejected with
    `ERR_DUPLICATE_RESOURCE`."

    Design: Corner/state_machines/ballot_duplicate_cast_rejected
    """
    set_clock("2026-09-01T09:00:00Z")
    voter = create_active_participant(participant_type="BOTH", routing_number="111000025")
    code = create_web_transaction_code()
    proposal = create_proposal_in_balloting(code, effective_date="2027-01-01")
    cast_ballot(proposal["id"], voter, "YEA")

    duplicate = api.cast_ballot(
        proposal["id"], {"vote": "NAY"}, make_voting_delegate_headers(voter["id"])
    )
    validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_RESOURCE)

    after = validate_success(api.get_rule_proposal(proposal["id"], admin_headers))
    assert after["yea_count"] == 1
    assert after["nay_count"] == 0


def test_ballot_recast_same_vote_rejected(api, admin_headers):
    """PRD §3.3: "A delegate may recast — change an existing ballot's `vote` —
    but only while the parent proposal remains in `BALLOTING` (otherwise
    `ERR_INVALID_STATE`), only for the ballot whose `participant_id` equals the
    delegate's `X-User-ID` (otherwise `ERR_FORBIDDEN`), and only to a vote that
    actually differs from the ballot's current one; a recast to the same vote
    is rejected with `ERR_VOTE_UNCHANGED`."

    Design: Corner/state_machines/ballot_recast_same_vote_rejected
    """
    set_clock("2026-09-01T09:00:00Z")
    voter = create_active_participant(participant_type="BOTH", routing_number="111000025")
    code = create_web_transaction_code()
    proposal = create_proposal_in_balloting(code, effective_date="2027-01-01")
    ballot = cast_ballot(proposal["id"], voter, "YEA")

    same = api.recast_ballot(
        ballot["id"], {"vote": "YEA"}, make_voting_delegate_headers(voter["id"])
    )
    validate_error(same, ApiErrorId.ERR_VOTE_UNCHANGED)

    after = validate_success(api.get_ballot(ballot["id"], admin_headers))
    assert after["version"] == ballot["version"]


def test_proposal_superseded_by_newer_effective(api, admin_headers):
    """PRD §3.4: "When a proposal becomes `EFFECTIVE`, every other proposal
    governing the same transaction code that is currently `EFFECTIVE`
    transitions to `SUPERSEDED`, so at most one effective rule exists per entry
    class; `SUPERSEDED` is terminal."

    Design: Corner/state_machines/proposal_superseded_by_newer_effective
    """
    set_clock("2026-09-01T09:00:00Z")
    voter = create_active_participant(participant_type="BOTH", routing_number="111000025")
    code = create_web_transaction_code()

    rp1 = open_comment_period(create_rule_proposal(code, effective_date="2026-10-20"))
    rp2 = open_comment_period(create_rule_proposal(code, effective_date="2026-11-15"))

    set_clock("2026-10-01T09:00:00Z")
    rp1 = transition_proposal(rp1["id"], "BALLOTING")
    rp2 = transition_proposal(rp2["id"], "BALLOTING")
    cast_ballot(rp1["id"], voter, "YEA")
    cast_ballot(rp2["id"], voter, "YEA")

    close_ballot(rp1)
    close_ballot(rp2)

    set_clock("2026-10-20T09:00:00Z")
    first_effective = transition_proposal(rp1["id"], "EFFECTIVE")
    assert first_effective["status"] == "EFFECTIVE"

    set_clock("2026-11-15T09:00:00Z")
    second_effective = transition_proposal(rp2["id"], "EFFECTIVE")
    assert second_effective["status"] == "EFFECTIVE"

    rp1_after = validate_success(api.get_rule_proposal(rp1["id"], admin_headers))
    assert rp1_after["status"] == "SUPERSEDED"


def test_ballot_quorum_failure_rejects_no_quorum(api, admin_headers):
    """PRD §3.4: "Quorum requires the cast count to be at least half of the
    eligible electorate, with halves rounded up — for instance, five eligible
    participants demand at least three cast ballots. If quorum fails, the
    proposal's `outcome` is set to `REJECTED_NO_QUORUM` and the proposal moves
    to `REJECTED`."
    PRD §3.4: "Either way, every ballot of the proposal still in `CAST` status
    transitions to `LOCKED` and the tallies freeze."

    Design: Corner/state_machines/ballot_quorum_failure_rejects_no_quorum
    """
    set_clock("2026-09-01T09:00:00Z")
    voters = [
        create_active_participant(routing_number=f"11100002{i}")
        for i in range(5)
    ]
    code = create_web_transaction_code()
    proposal = create_proposal_in_balloting(code, effective_date="2027-01-01")
    b1 = cast_ballot(proposal["id"], voters[0], "YEA")
    b2 = cast_ballot(proposal["id"], voters[1], "YEA")

    closed = close_ballot(proposal)
    assert closed["status"] == "REJECTED"
    assert closed["outcome"] == "REJECTED_NO_QUORUM"
    assert closed["outcome"] == compute_ballot_outcome(5, 2, 0, 0)

    for ballot in (b1, b2):
        locked = validate_success(api.get_ballot(ballot["id"], admin_headers))
        assert locked["status"] == "LOCKED"


def test_ballot_exact_two_thirds_passes_and_majority_against_fails(api, admin_headers):
    """PRD §3.4: "Otherwise the proposal passes when the yea tally amounts to at
    least two-thirds of the non-abstaining count — compared by
    cross-multiplication, so three times the yea count must be at least twice
    the non-abstaining count — yielding `outcome` `PASSED_QUORUM` and status
    `PASSED`; falling short yields `REJECTED_VOTE` and `REJECTED`."

    Design: Corner/state_machines/ballot_exact_two_thirds_passes_and_majority_against_fails
    """
    set_clock("2026-09-01T09:00:00Z")
    voter1 = create_active_participant(participant_type="BOTH", routing_number="111000025")
    voter2 = create_active_participant(participant_type="ODFI", routing_number="222000039")
    voter3 = create_active_participant(participant_type="RDFI", routing_number="333000041")
    code = create_web_transaction_code()

    rp1 = create_proposal_in_balloting(code, effective_date="2027-01-01")
    rp2 = create_proposal_in_balloting(code, effective_date="2027-01-01")

    cast_ballot(rp1["id"], voter1, "YEA")
    cast_ballot(rp1["id"], voter2, "YEA")
    cast_ballot(rp1["id"], voter3, "NAY")
    cast_ballot(rp2["id"], voter1, "YEA")
    cast_ballot(rp2["id"], voter2, "NAY")
    cast_ballot(rp2["id"], voter3, "NAY")

    closed1 = close_ballot(rp1)
    closed2 = close_ballot(rp2)

    assert closed1["status"] == "PASSED"
    assert closed1["outcome"] == "PASSED_QUORUM"
    assert closed1["outcome"] == compute_ballot_outcome(3, 2, 1, 0)
    assert closed2["status"] == "REJECTED"
    assert closed2["outcome"] == "REJECTED_VOTE"
    assert closed2["outcome"] == compute_ballot_outcome(3, 1, 2, 0)


def test_ballot_cast_by_participant_officer_forbidden(api, admin_headers):
    """PRD §2.1: "Access to specific operations is restricted by role per §4; a
    request whose role is not listed for the endpoint it targets is rejected
    with `ERR_FORBIDDEN` (HTTP 403)."

    PRD §4 lists POST /network/rule-proposals/{id}/ballots under VotingDelegate
    only, so the ParticipantOfficer credential is not authorized for it.

    Design: Corner/rbac/ballot_cast_by_participant_officer_forbidden
    """
    set_clock("2026-09-01T09:00:00Z")
    participant = create_active_participant(participant_type="BOTH", routing_number="111000025")
    code = create_web_transaction_code()
    proposal = create_proposal_in_balloting(code, effective_date="2027-01-01")

    resp = api.cast_ballot(
        proposal["id"],
        {"vote": "YEA"},
        make_participant_officer_headers(participant["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    after = validate_success(api.get_rule_proposal(proposal["id"], admin_headers))
    assert after["yea_count"] == 0


def test_ballot_cast_by_inactive_participant_rejected(api, admin_headers):
    """PRD §3.3: "The voting participant must be `ACTIVE` at cast time — a
    suspended or onboarding participant's ballot attempt fails with
    `ERR_PARTICIPANT_NOT_ACTIVE`"

    Design: Corner/validations/ballot_cast_by_inactive_participant_rejected
    """
    set_clock("2026-09-01T09:00:00Z")
    participant = create_participant(participant_type="BOTH", routing_number="111000025")
    code = create_web_transaction_code()
    proposal = create_proposal_in_balloting(code, effective_date="2027-01-01")

    resp = api.cast_ballot(
        proposal["id"],
        {"vote": "YEA"},
        make_voting_delegate_headers(participant["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_PARTICIPANT_NOT_ACTIVE)

    ballots, meta = validate_paginated(
        api.list_ballots(
            admin_headers,
            params={"rule_proposal_id": proposal["id"], "participant_id": participant["id"]},
        )
    )
    assert ballots == [] and meta["total_count"] == 0
