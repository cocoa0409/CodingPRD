"""Declared transitions, terminal states and the edges that are refused."""
from test_helpers import (
    COMPLIANCE,
    DEFAULT_CLOCK_STAMP,
    DIRECTOR,
    api_client,
    assert_candidate_accumulator_split,
    assert_fund_terms,
    assert_instant_equals,
    canonicalize_instant,
    cast_ballot,
    cast_vote_payload,
    create_receipt_payload,
    create_registration_payload,
    credit_receipt,
    dispatch_alert_payload,
    draft_position,
    draft_registration,
    enroll_member,
    grant_prior_approval_payload,
    make_member_delegate_headers,
    read_campaign,
    read_candidate,
    read_contribution,
    read_fund,
    read_member,
    read_position,
    read_registration,
    read_vote,
    request_prior_approval,
    set_clock,
    setup_active_registration,
    setup_campaign_on_adopted_position,
    setup_funded_fund,
    setup_position_in_balloting,
    setup_quorate_committee,
    setup_suspended_contribution,
    tally_round,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_filing_a_registration_stamps_the_logical_clock_and_bumps_the_version():
    """The happy-path filing edge leaves the coverage window untouched.

    PRD 3.5: "Filing moves the registration `DRAFT → ACTIVE`, stamps `filed_at` with
    the logical clock instant, and is the moment the overlap rule bites."
    PRD 3.5: "Every one of these four transitions — file, amend, certify-amendment,
    terminate — increments the registration's `version` by one, which matters for the
    concurrency rule of §2.9."

    Design: Corner/State Machines/file_registration_moves_draft_to_active_and_stamps_filed_at
    """
    draft = draft_registration(
        registrant_name="National Metals Association",
        coverage_start_date="2026-01-01",
        coverage_end_date="2026-12-31",
    )
    assert draft["version"] == 1

    filed = validate_success(api_client.file_registration(draft["id"], COMPLIANCE), 200)
    assert filed["status"] == "ACTIVE"
    assert_instant_equals(filed["filed_at"], DEFAULT_CLOCK_STAMP, "filed_at")
    assert filed["coverage_start_date"] == "2026-01-01"
    assert filed["coverage_end_date"] == "2026-12-31"
    assert filed["amendment_round"] == 0
    assert filed["ytd_reportable_cents"] == 0
    assert float(filed["ytd_reportable_hours"]) == 0.000
    assert filed["version"] == 2


def test_a_new_registration_starts_in_draft_and_is_not_auto_filed():
    """Creation never files, which is what makes activity logging refuse it later.

    PRD 3.5: "A draft starts in `DRAFT` with `amendment_round` at 0, `filed_at` and
    `terminated_at` null, and both year-to-date accumulators at 0."
    PRD 3.5: "Nothing about overlap is checked at draft time."

    Design: Corner/State Machines/new_registration_starts_in_draft
    """
    set_clock(DEFAULT_CLOCK_STAMP)
    payload = create_registration_payload(
        jurisdiction_code="STATE_NY",
        registrant_name="National Metals Association",
        coverage_start_date="2026-01-01",
        coverage_end_date="2026-12-31",
    )
    draft = validate_success(api_client.create_lobbying_registration(payload, COMPLIANCE), 201)

    assert draft["status"] == "DRAFT"
    assert draft["filed_at"] is None
    assert draft["terminated_at"] is None
    assert draft["amendment_round"] == 0
    assert draft["version"] == 1


def test_a_second_terminate_is_refused_and_keeps_the_first_timestamp():
    """TERMINATED is terminal, so the repeat is an error and not a silent no-op.

    PRD 3.5: "Termination moves `ACTIVE → TERMINATED` and stamps `terminated_at`; it
    is blocked while any expenditure report of this registration is still `OPEN`, which
    is refused with `ERR_OPEN_REPORT_BLOCKS_TERMINATION`."
    PRD 3.5: "Once terminated, no further activity may be logged and no further report
    may be opened, and the state is terminal."

    Design: Corner/State Machines/terminating_an_already_terminated_registration_rejected
    """
    registration = setup_active_registration(registrant_name="National Metals Association")

    terminated = validate_success(
        api_client.terminate_registration(registration["id"], COMPLIANCE), 200
    )
    assert terminated["status"] == "TERMINATED"
    assert_instant_equals(terminated["terminated_at"], DEFAULT_CLOCK_STAMP, "terminated_at")

    validate_error(
        api_client.terminate_registration(registration["id"], COMPLIANCE),
        "ERR_INVALID_REGISTRATION_STATE",
        409,
    )

    after = read_registration(registration["id"])
    assert canonicalize_instant(after["terminated_at"]) == canonicalize_instant(
        terminated["terminated_at"]
    )
    assert after["version"] == terminated["version"]


def test_certifying_an_amendment_that_was_never_opened_is_refused():
    """The certify edge is declared only from AMENDMENT_PENDING.

    PRD 3.5: "Opening an amendment on a registration that is not `ACTIVE`, or
    certifying one on a registration that is not `AMENDMENT_PENDING`, gives
    `ERR_INVALID_REGISTRATION_STATE`."
    PRD 3.5: "Certifying an amendment has a second, less obvious effect described
    below: raising `amendment_round` above zero permanently disarms the automatic
    threshold amendment."

    Design: Corner/State Machines/certify_amendment_on_an_active_registration_rejected
    """
    registration = setup_active_registration(registrant_name="National Metals Association")

    validate_error(
        api_client.certify_registration_amendment(registration["id"], COMPLIANCE),
        "ERR_INVALID_REGISTRATION_STATE",
        409,
    )

    after = read_registration(registration["id"])
    assert after["status"] == "ACTIVE"
    assert after["amendment_round"] == 0


def test_a_closed_campaign_refuses_both_a_second_close_and_a_new_alert():
    """CLOSED is terminal on both outgoing edges and the accumulators stay frozen.

    PRD 3.7: "Closing an already-`CLOSED` campaign is refused with
    `ERR_INVALID_CAMPAIGN_STATE`."
    PRD 3.7: "Closure freezes `cumulative_cost_cents` and `disclosure_required` at
    their current values and bars any further alert."

    Design: Corner/State Machines/closed_campaign_refuses_both_a_second_close_and_a_new_alert
    """
    state = setup_campaign_on_adopted_position(
        campaign_overrides={"name": "Tariff Scope Action"},
        position_overrides={"title": "Oppose Section 232 Expansion"},
    )
    campaign_id = state["campaign"]["id"]

    closed = validate_success(api_client.close_campaign(campaign_id, DIRECTOR), 200)
    assert closed["status"] == "CLOSED"

    validate_error(
        api_client.close_campaign(campaign_id, DIRECTOR), "ERR_INVALID_CAMPAIGN_STATE", 409
    )
    validate_error(
        api_client.dispatch_alert(
            campaign_id,
            dispatch_alert_payload(message_subject="Call your representative"),
            DIRECTOR,
        ),
        "ERR_INVALID_CAMPAIGN_STATE",
        409,
    )

    campaign = read_campaign(campaign_id)
    assert campaign["alert_count"] == 0
    assert campaign["cumulative_cost_cents"] == 0
    assert campaign["disclosure_required"] is False
    assert campaign["last_alert_at"] is None

    rows, meta = validate_paginated(api_client.list_campaign_alerts(campaign_id, DIRECTOR))
    assert rows == []
    assert meta["total_count"] == 0


def test_withdrawing_a_dissent_that_was_never_filed_is_refused():
    """The dissent axis starts at NONE and the ballot axis is left alone.

    PRD 3.3: "Three conditions apply: the ballot's `dissent_status` must currently be
    `FILED`, and a `NONE`, `WITHDRAWN` or `RECORDED` dissent is refused with
    `ERR_DISSENT_NOT_FILED`; the position must still be inside the ballot cycle, in either
    `BALLOTING` or `RECONSIDERATION`, since a dissent may not be rewritten once the position
    has left it, and any other position state yields `ERR_INVALID_POSITION_STATE`; and the
    caller must be the dissenting member itself, enforced as described in §2.1."
    PRD 3.3: "Its `dissent_status` is `FILED` when a non-empty `dissent_statement` was
    supplied and `NONE` when it was not; a dissent statement is only meaningful
    alongside an opposing ballot, so supplying one together with `SUPPORT` or `ABSTAIN`
    is refused with `ERR_DISSENT_REQUIRES_OPPOSE`."

    Design: Corner/State Machines/withdraw_dissent_on_a_vote_with_no_filed_dissent_rejected
    """
    state = setup_position_in_balloting(
        position_overrides={"title": "Oppose Section 232 Expansion"}
    )
    position_id = state["position"]["id"]
    member = state["members"][0]
    vote = cast_ballot(position_id, member["id"], "SUPPORT")
    assert vote["dissent_status"] == "NONE"

    validate_error(
        api_client.withdraw_dissent(
            position_id, vote["id"], make_member_delegate_headers(member["id"])
        ),
        "ERR_DISSENT_NOT_FILED",
        409,
    )

    after = read_vote(position_id, vote["id"])
    assert after["ballot_status"] == "CAST"
    assert after["ballot"] == "SUPPORT"
    assert after["dissent_status"] == "NONE"


def test_a_receipt_that_restores_the_reserve_reinstates_the_suspended_row():
    """The reverse posture edge un-suspends the row and re-adds its pending total.

    PRD 3.8: "If the new balance has reached `min_reserve_cents`, the fund flips
    `RESTRICTED → OPEN`, and that flip reinstates every contribution of this fund
    sitting in `SUSPENDED` back to `PENDING_BOARD`, restoring each affected candidate's
    `pending_support_cents` by that contribution's `amount_cents`."
    PRD 3.8: "And `posture` is a pure function of that balance: it reads `RESTRICTED`
    whenever `available_balance_cents` is strictly below `min_reserve_cents`, and `OPEN`
    otherwise."

    Design: Corner/State Machines/receipt_reinstates_a_suspended_contribution_when_posture_returns_to_open
    """
    state = setup_suspended_contribution(
        first_amount_cents=250_000,
        second_amount_cents=200_000,
        min_reserve_cents=400_000,
        receipt_amount_cents=600_000,
    )
    fund_id = state["fund"]["id"]

    assert_fund_terms(
        read_fund(fund_id),
        receipts=600_000,
        committed=250_000,
        disbursed=0,
        fees=0,
        available=350_000,
        posture="RESTRICTED",
    )
    assert state["contribution_y"]["status"] == "SUSPENDED"
    assert_candidate_accumulator_split(
        read_candidate(state["candidate_b"]["id"]), pending=0, committed=0, disbursed=0
    )

    fund = credit_receipt(
        fund_id, state["member"]["id"], amount_cents=100_000, received_date="2026-08-01"
    )
    assert_fund_terms(
        fund,
        receipts=700_000,
        committed=250_000,
        disbursed=0,
        fees=0,
        available=450_000,
        posture="OPEN",
    )

    reinstated = read_contribution(state["contribution_y"]["id"])
    assert reinstated["status"] == "PENDING_BOARD"
    assert_candidate_accumulator_split(
        read_candidate(state["candidate_b"]["id"]),
        pending=200_000,
        committed=0,
        disbursed=0,
    )

    assert read_contribution(state["contribution_x"]["id"])["status"] == "BOARD_APPROVED"
    assert_candidate_accumulator_split(
        read_candidate(state["candidate_a"]["id"]),
        pending=0,
        committed=250_000,
        disbursed=0,
    )


def test_revoking_a_prior_approval_blocks_the_very_next_receipt():
    """The eligibility gate reads live approval state, not a snapshot.

    PRD 3.8: "Revocation is the mirror image and also belongs to the member: `GRANTED
    → REVOKED`, stamping `revoked_at`, and recomputing `pac_solicitable` back to false
    unless some other `GRANTED` approval of that member still covers the clock date."
    PRD 3.8: "Eligibility is checked against the prior-approval record: that member
    must have an approval in `GRANTED` status whose window contains the logical clock's
    date, and a member with no such approval — including one whose approval was revoked
    or expired — is refused with `ERR_PRIOR_APPROVAL_NOT_GRANTED`."

    Design: Corner/State Machines/revoking_a_prior_approval_blocks_the_next_receipt
    """
    state = setup_funded_fund(min_reserve_cents=0, receipt_amount_cents=100_000)
    fund_id = state["fund"]["id"]
    member_id = state["member"]["id"]

    revoked = validate_success(
        api_client.revoke_prior_approval(
            state["approval"]["id"], make_member_delegate_headers(member_id)
        ),
        200,
    )
    assert revoked["status"] == "REVOKED"
    assert_instant_equals(revoked["revoked_at"], DEFAULT_CLOCK_STAMP, "revoked_at")
    assert read_member(member_id)["pac_solicitable"] is False

    validate_error(
        api_client.create_fund_receipt(
            fund_id,
            create_receipt_payload(member_id, amount_cents=50_000, received_date="2026-08-01"),
            COMPLIANCE,
        ),
        "ERR_PRIOR_APPROVAL_NOT_GRANTED",
        409,
    )

    fund = read_fund(fund_id)
    assert fund["receipts_total_cents"] == 100_000
    assert fund["available_balance_cents"] == 100_000


def test_granting_an_approval_whose_window_has_already_elapsed_is_refused():
    """The grant edge compares the logical clock date against expires_at_date.

    PRD 3.8: "The delegate's own member record must be `ACTIVE`, or the grant is
    refused with `ERR_MEMBER_NOT_ACTIVE`; and the logical clock's date must not have
    passed `expires_at_date`, or it is refused with `ERR_PRIOR_APPROVAL_EXPIRED` — an
    approval whose window has already elapsed cannot be resurrected by signing it
    late."
    PRD 3.8: "`REQUESTED → EXPIRED` and `GRANTED → EXPIRED` are the only transitions
    the sweep performs, and no other endpoint performs them."

    Design: Corner/State Machines/grant_prior_approval_after_its_window_expired_rejected
    """
    member = enroll_member(
        legal_name="Alpha Steel Co", membership_tier="PREMIER", restricted_class_size=25
    )
    approval = request_prior_approval(
        member["id"],
        solicitable_class_size=5,
        effective_date="2026-01-01",
        expires_at_date="2026-06-30",
    )

    validate_error(
        api_client.grant_prior_approval(
            approval["id"],
            grant_prior_approval_payload(authorized_by_name="A. Steel, CFO"),
            make_member_delegate_headers(member["id"]),
        ),
        "ERR_PRIOR_APPROVAL_EXPIRED",
        409,
    )

    rows, _ = validate_paginated(
        api_client.list_member_prior_approvals(member["id"], COMPLIANCE)
    )
    stored = next(row for row in rows if row["id"] == approval["id"])
    assert stored["status"] == "REQUESTED"
    assert stored["granted_at"] is None
    assert read_member(member["id"])["pac_solicitable"] is False


def test_recasting_a_ballot_in_the_same_round_supersedes_only_the_earlier_row():
    """The later ballot is the live one and the tally counts it alone.

    PRD 3.3: "A delegate may change its mind within the same round simply by casting
    again: the earlier ballot of that same member in that same round flips from `CAST`
    to `SUPERSEDED` — again leaving its `dissent_status` exactly as it was — and the new
    ballot becomes the live one."
    PRD 3.4: "The input set for scoring is narrow and must be read literally: ballots
    of this position whose `round_number` equals the position's current `round_number`
    and whose `ballot_status` is `CAST`."

    Design: Corner/State Machines/recasting_a_ballot_in_the_same_round_supersedes_the_first_row
    """
    state = setup_position_in_balloting(
        position_overrides={"title": "Oppose Section 232 Expansion"}
    )
    position_id = state["position"]["id"]
    premier, full = state["members"][0], state["members"][1]

    first = cast_ballot(position_id, premier["id"], "SUPPORT")
    second = cast_ballot(position_id, full["id"], "SUPPORT")
    third = validate_success(
        api_client.cast_vote(
            position_id,
            cast_vote_payload("OPPOSE"),
            make_member_delegate_headers(premier["id"]),
        ),
        201,
    )
    assert third["ballot_status"] == "CAST"
    assert third["ballot"] == "OPPOSE"
    assert third["round_number"] == 1
    assert third["weight_snapshot"] == 3

    rows, meta = validate_paginated(api_client.list_position_votes(position_id, DIRECTOR))
    assert meta["total_count"] == 3
    by_id = {row["id"]: row for row in rows}
    assert by_id[first["id"]]["ballot_status"] == "SUPERSEDED"
    assert by_id[second["id"]]["ballot_status"] == "CAST"
    assert by_id[third["id"]]["ballot_status"] == "CAST"

    tallied = tally_round(position_id)
    assert tallied["support_weight"] == 2
    assert tallied["oppose_weight"] == 3
    assert tallied["abstain_weight"] == 0
    assert float(tallied["quorum_pct"]) == 83.33
    assert float(tallied["consensus_pct"]) == 40.00
    assert tallied["last_tally_outcome"] == "DISSENSUS"
    assert tallied["status"] == "RECONSIDERATION"


def test_tallying_a_draft_position_reports_the_state_gate():
    """The generic state gate answers before the ballot-bookkeeping gate.

    PRD 3.4: "Closing a round is a `GovAffairsDirector` act, permitted only while the
    position is `BALLOTING` — any other state gives `ERR_INVALID_POSITION_STATE` — and only
    when at least one ballot of the **current** round still has `ballot_status` `CAST`."
    PRD 3.3: "A freshly drafted position sits in `DRAFT` with `round_number` at 0,
    every weight and percentage field at 0, `last_tally_outcome` at `NONE`,
    `dissent_register_count` at 0, and `adopted_at` null."

    Design: Corner/State Machines/tally_on_a_draft_position_rejected
    """
    roster = setup_quorate_committee()
    position = draft_position(
        roster["committee"]["id"], title="Oppose Section 232 Expansion"
    )

    validate_error(
        api_client.tally_position(position["id"], DIRECTOR), "ERR_INVALID_POSITION_STATE", 409
    )

    after = read_position(position["id"])
    assert after["status"] == "DRAFT"
    assert after["round_number"] == 0
    assert after["last_tally_outcome"] == "NONE"
    assert float(after["quorum_pct"]) == 0.00
    assert float(after["consensus_pct"]) == 0.00
