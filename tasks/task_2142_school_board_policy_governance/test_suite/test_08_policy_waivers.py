"""Site waiver requests: the window checks, committee review, board grant and revocation."""

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_agenda_item,
    adjourn_meeting,
    api_client,
    assert_instant_equals,
    charter_committee,
    file_speaker_card,
    file_waiver,
    make_board_member_headers,
    open_meeting,
    post_notice,
    read_agenda_item,
    read_committee,
    read_meeting,
    read_policy,
    read_speaker_card,
    read_waiver,
    recommend_waiver,
    record_vote,
    register_policy,
    run_sweep,
    schedule_meeting,
    seat_board,
    seat_on_committee,
    set_clock,
    setup_active_committee,
    setup_granted_waiver,
    validate_error,
    validate_paginated,
    validate_success,
    waiver_request_payload,
)

PRINCIPAL = TEST_USERS["school_principal_headers"]
SUPT = TEST_USERS["superintendent_headers"]
PUBLIC = TEST_USERS["public_headers"]
CLERK = TEST_USERS["board_clerk_headers"]


def test_revoking_a_waiver_that_was_never_granted_is_refused():
    """PRD 3.8: "**Revocation** is available to the superintendent and to the president,
    and only on a waiver whose `status` is `GRANTED` — otherwise `ERR_WAIVER_NOT_IN_REVIEW`."
    PRD 3.8: "A filed request opens `SUBMITTED` with `committee_recommendation`,
    `denial_stage`, `granted_start_date`, `granted_end_date` and `revoked_on` all null and
    `granted_days` 0."

    Design: Corner/state_machines/revoke_a_waiver_that_was_never_granted_returns_waiver_not_in_review
    """
    committee = charter_committee()
    policy = register_policy("BP-6155", "Homework and Grading", "INSTRUCTION", "RECOMMENDED", "6000.55")
    waiver = file_waiver(policy["id"], committee["id"])

    response = api_client.revoke_waiver_request(waiver["id"], SUPT)
    validate_error(response, ApiErrorId.ERR_WAIVER_NOT_IN_REVIEW.value)
    assert response.status_code == 409

    row = read_waiver(waiver["id"])
    assert row["status"] == "SUBMITTED"
    assert row["revoked_on"] is None
    assert row["granted_start_date"] is None


def test_granting_after_the_requested_start_clips_the_window_forward():
    """PRD 3.8: "A passing vote takes the waiver `BOARD_PENDING → GRANTED` and writes the
    effective window. `granted_start_date` is the later of the requested start and the
    logical clock at the moment of the grant; `granted_end_date` is the requested end
    unchanged; and `granted_days` is the whole number of days between them, never below
    zero."
    PRD 3.8: "Two shapes follow from that rule: when the board grants before the requested
    start has arrived, the grant is forward-dated, `granted_start_date` equals
    `requested_start_date` and `granted_days` covers the full requested span; when the board
    grants on or after the requested start, the window is clipped forward to the clock and
    `granted_days` is strictly less than the requested span."

    Design: Corner/calculations/waiver_granted_start_is_clipped_forward_to_the_clock
    """
    members = seat_board(3)
    committee_setup = setup_active_committee(members)
    policy = register_policy("BP-6155", "Homework and Grading", "INSTRUCTION", "RECOMMENDED", "6000.55")
    scenario = setup_granted_waiver(
        members,
        policy,
        committee_setup["committee"],
        committee_setup["chair"]["id"],
        requested_start_date="2026-09-01T00:00:00Z",
        requested_end_date="2026-11-01T00:00:00Z",
    )

    assert scenario["item"]["required_yes_votes"] == 2
    assert scenario["item"]["vote_outcome"] == "PASSED"

    waiver = scenario["waiver"]
    assert waiver["status"] == "GRANTED"
    assert waiver["max_allowed_days"] == 180
    assert_instant_equals(
        waiver["granted_start_date"], "2026-09-10T18:00:00Z", "WaiverRequest.granted_start_date"
    )
    assert_instant_equals(
        waiver["granted_end_date"], "2026-11-01T00:00:00Z", "WaiverRequest.granted_end_date"
    )
    assert waiver["granted_days"] == 51
    assert read_policy(policy["id"])["active_waiver_count"] == 1


def test_a_granted_waiver_expires_only_when_the_sweep_runs():
    """PRD 3.9: "expires every waiver whose `status` is `GRANTED` and whose
    `granted_end_date` the clock has reached or passed, taking it `GRANTED → EXPIRED`,
    recomputing the policy's `active_waiver_count` and `compliance_state`, and withdrawing
    every agenda item referencing it in `PROPOSED` or `POSTED` status while releasing those
    items' speaker cards and crediting their minutes back"
    PRD 3.9: "`waivers_expired` counts the waivers this sweep moved into `EXPIRED`."

    Design: Corner/calculations/granted_waiver_expires_on_the_sweep_after_its_end_date
    """
    members = seat_board(3)
    committee_setup = setup_active_committee(members)
    policy = register_policy("BP-6155", "Homework and Grading", "INSTRUCTION", "RECOMMENDED", "6000.55")
    scenario = setup_granted_waiver(
        members, policy, committee_setup["committee"], committee_setup["chair"]["id"]
    )
    assert scenario["waiver"]["granted_days"] == 31

    set_clock("2026-11-01T00:00:00Z")
    result = validate_success(api_client.run_compliance_sweep(CLERK), 200)
    assert result["waivers_expired"] == 1

    assert read_waiver(scenario["waiver"]["id"])["status"] == "EXPIRED"
    assert read_policy(policy["id"])["active_waiver_count"] == 0
    assert read_agenda_item(scenario["item"]["id"])["status"] == "ACTED"


def test_a_waiver_longer_than_the_policy_cap_is_refused():
    """PRD 3.8: "Third, that same whole-day count may not exceed the cap the linked
    policy's `legal_requirement_level` imposes, which is recorded on the request as
    `max_allowed_days` at creation: 90 days for a `REQUIRED_BY_LAW` policy, 180 days for a
    `RECOMMENDED` one, and a full 365 days for one at `LOCAL_DISCRETION`. Exceeding the cap
    is refused with `ERR_WAIVER_DURATION_EXCEEDS_CAP`."

    Design: Corner/validations/waiver_longer_than_the_policy_cap_returns_duration_exceeds_cap
    """
    committee = charter_committee()
    policy = register_policy()

    response = api_client.create_waiver_request(
        waiver_request_payload(
            policy["id"],
            committee["id"],
            requesting_school_code="HS-01",
            justification="Whole-year pilot",
            requested_start_date="2026-10-15T00:00:00Z",
            requested_end_date="2027-06-15T00:00:00Z",
        ),
        PRINCIPAL,
    )
    validate_error(response, ApiErrorId.ERR_WAIVER_DURATION_EXCEEDS_CAP.value)
    assert response.status_code == 422

    _rows, meta = validate_paginated(
        api_client.list_waiver_requests(PUBLIC, {"policy_id": policy["id"]})
    )
    assert meta["total_count"] == 0


def test_a_waiver_window_shorter_than_one_whole_day_is_refused():
    """PRD 3.8: "Second, the window must be at least one whole day long, measured as the
    difference between the two instants in seconds divided by 86400 with the remainder
    discarded; anything shorter is refused with `ERR_INVALID_WAIVER_WINDOW`."
    PRD 2.8: "Every duration in days is computed as an integer by taking the difference
    between two instants in seconds and dividing by 86400 seconds, discarding any remainder."

    Design: Corner/validations/waiver_window_shorter_than_one_day_returns_invalid_waiver_window
    """
    committee = charter_committee()
    policy = register_policy("BP-6155", "Homework and Grading", "INSTRUCTION", "RECOMMENDED", "6000.55")

    response = api_client.create_waiver_request(
        waiver_request_payload(
            policy["id"],
            committee["id"],
            requesting_school_code="HS-01",
            justification="Half-day exception",
            requested_start_date="2026-10-01T00:00:00Z",
            requested_end_date="2026-10-01T12:00:00Z",
        ),
        PRINCIPAL,
    )
    error = validate_error(response, ApiErrorId.ERR_INVALID_WAIVER_WINDOW.value)
    assert response.status_code == 422
    assert error["error_id"] != ApiErrorId.ERR_INVALID_REQUEST.value


def test_only_the_active_chair_may_record_the_committee_recommendation():
    """PRD 2.1: "a committee recommendation is only accepted from the trustee whose
    `X-User-ID` holds a committee seat with `status` `ACTIVE` and `role_on_committee`
    `CHAIR` on the waiver's reviewing committee. Any of these mismatches — including a
    `BoardPresident` caller who is not the seated president — is rejected with
    `ERR_IDENTITY_MISMATCH` (HTTP 403)."

    Design: Corner/rbac/non_chair_committee_member_cannot_record_the_recommendation_returns_identity_mismatch
    """
    members = seat_board(3)
    committee_setup = setup_active_committee(members)
    policy = register_policy("BP-6155", "Homework and Grading", "INSTRUCTION", "RECOMMENDED", "6000.55")
    waiver = file_waiver(policy["id"], committee_setup["committee"]["id"])

    response = api_client.record_committee_recommendation(
        waiver["id"],
        {"recommendation": "RECOMMEND_GRANT"},
        make_board_member_headers(committee_setup["member"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_IDENTITY_MISMATCH.value)
    assert response.status_code == 403

    row = read_waiver(waiver["id"])
    assert row["status"] == "SUBMITTED"
    assert row["committee_recommendation"] is None
    assert committee_setup["member_assignment"]["role_on_committee"] == "MEMBER"


def _two_branch_scenario():
    """Two SUBMITTED waivers on the same policy from different schools, each listed on a
    still-DRAFT agenda, so the two recommendation branches can be compared side by side."""
    members = seat_board(3)
    committee_setup = setup_active_committee(members)
    policy = register_policy("BP-6155", "Homework and Grading", "INSTRUCTION", "RECOMMENDED", "6000.55")
    first = file_waiver(
        policy["id"],
        committee_setup["committee"]["id"],
        requesting_school_code="HS-01",
        justification="Block schedule pilot",
    )
    second = file_waiver(
        policy["id"],
        committee_setup["committee"]["id"],
        requesting_school_code="HS-02",
        justification="Standards-based grading pilot",
    )
    meeting = schedule_meeting()
    first_item = add_agenda_item(
        meeting["id"],
        meeting["version"],
        item_type="WAIVER_DECISION",
        title="Waiver HS-01",
        waiver_request_id=first["id"],
    )
    second_item = add_agenda_item(
        meeting["id"],
        first_item["meeting_version_after"],
        item_type="WAIVER_DECISION",
        title="Waiver HS-02",
        waiver_request_id=second["id"],
    )
    chair_id = committee_setup["chair"]["id"]
    recommend_waiver(first["id"], chair_id, "RECOMMEND_GRANT")
    recommend_waiver(second["id"], chair_id, "RECOMMEND_DENY")
    return {
        "committee": committee_setup["committee"],
        "granted_waiver": first,
        "denied_waiver": second,
        "granted_item": first_item,
        "denied_item": second_item,
    }


def test_recommend_grant_advances_the_waiver_and_touches_no_agenda_item():
    """PRD 3.8: "`RECOMMEND_GRANT` records `committee_recommendation` and advances the
    waiver `SUBMITTED → BOARD_PENDING`; nothing else moves."

    Design: Difficulty/non_linear_state_machine/waiver_committee_recommendation_branches_to_two_side_effect_sets
    """
    scenario = _two_branch_scenario()
    waiver = read_waiver(scenario["granted_waiver"]["id"])
    assert waiver["status"] == "BOARD_PENDING"
    assert waiver["committee_recommendation"] == "RECOMMEND_GRANT"
    assert waiver["denial_stage"] is None
    assert read_agenda_item(scenario["granted_item"]["id"])["status"] == "PROPOSED"


def test_recommend_deny_kills_the_waiver_at_committee_and_withdraws_its_item():
    """PRD 3.8: "`RECOMMEND_DENY` records `committee_recommendation`, sets `denial_stage`
    to `COMMITTEE`, and takes the waiver straight to the terminal `DENIED` state — and
    because the waiver is now terminal, every agenda item referencing it in `PROPOSED` or
    `POSTED` status moves to `WITHDRAWN`, and every speaker card on those items in
    `REQUESTED` or `GRANTED` status moves to `RELEASED` with `denial_reason`
    `ITEM_WITHDRAWN`, `allotted_minutes` reset to 0, and any granted minutes credited back
    to the meeting's `public_comment_minutes_remaining`."

    Design: Difficulty/non_linear_state_machine/waiver_committee_recommendation_branches_to_two_side_effect_sets
    """
    scenario = _two_branch_scenario()
    waiver = read_waiver(scenario["denied_waiver"]["id"])
    assert waiver["status"] == "DENIED"
    assert waiver["committee_recommendation"] == "RECOMMEND_DENY"
    assert waiver["denial_stage"] == "COMMITTEE"
    assert read_agenda_item(scenario["denied_item"]["id"])["status"] == "WITHDRAWN"

    committee = read_committee(scenario["committee"]["id"])
    assert committee["status"] == "ACTIVE"
    assert committee["voting_seat_count"] == 2


def _inquorate_scenario():
    members = seat_board(3)
    committee = charter_committee()
    seat_on_committee(committee["id"], members[1]["id"], "CHAIR")
    policy = register_policy("BP-6155", "Homework and Grading", "INSTRUCTION", "RECOMMENDED", "6000.55")
    waiver = file_waiver(policy["id"], committee["id"])
    return members, committee, waiver


def test_an_inquorate_reviewing_committee_cannot_record_a_recommendation():
    """PRD 3.8: "The waiver must be `SUBMITTED` — anything else is refused with
    `ERR_WAIVER_NOT_IN_REVIEW` — and the reviewing committee's `status` must be `ACTIVE`,
    with an inquorate committee refused by `ERR_COMMITTEE_INQUORATE`."
    PRD 3.1: "A committee's `status` is derived, not set: it flips to `ACTIVE` the moment
    `voting_seat_count` reaches `quorum_size` and back to `INQUORATE` when it falls below."

    Design: Difficulty/cross_entity_state_dependency/waiver_committee_recommendation_blocked_while_committee_inquorate
    """
    members, committee, waiver = _inquorate_scenario()
    assert read_committee(committee["id"])["status"] == "INQUORATE"

    response = api_client.record_committee_recommendation(
        waiver["id"],
        {"recommendation": "RECOMMEND_GRANT"},
        make_board_member_headers(members[1]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_COMMITTEE_INQUORATE.value)
    assert response.status_code == 409
    assert read_waiver(waiver["id"])["status"] == "SUBMITTED"


def test_seating_a_second_member_restores_quorum_and_the_identical_call_succeeds():
    """PRD 3.1: "The seat is created `ACTIVE` with `assigned_on` stamped from the logical
    clock and `removed_on` left null; the committee's `filled_seat_count` and
    `voting_seat_count` each rise by one and `vacant_seat_count` falls by one, the committee
    may flip `INQUORATE → ACTIVE`, and the trustee's `active_committee_count` is recomputed."
    PRD 3.8: "`RECOMMEND_GRANT` records `committee_recommendation` and advances the waiver
    `SUBMITTED → BOARD_PENDING`; nothing else moves."

    Design: Difficulty/cross_entity_state_dependency/waiver_committee_recommendation_blocked_while_committee_inquorate
    """
    members, committee, waiver = _inquorate_scenario()
    api_client.record_committee_recommendation(
        waiver["id"],
        {"recommendation": "RECOMMEND_GRANT"},
        make_board_member_headers(members[1]["id"]),
    )

    seat_on_committee(committee["id"], members[2]["id"], "MEMBER")
    refreshed = read_committee(committee["id"])
    assert refreshed["voting_seat_count"] == 2
    assert refreshed["status"] == "ACTIVE"
    assert refreshed["filled_seat_count"] == 2
    assert refreshed["vacant_seat_count"] == 1

    accepted = api_client.record_committee_recommendation(
        waiver["id"],
        {"recommendation": "RECOMMEND_GRANT"},
        make_board_member_headers(members[1]["id"]),
    )
    data = validate_success(accepted, 200)
    assert data["status"] == "BOARD_PENDING"
    assert data["committee_recommendation"] == "RECOMMEND_GRANT"


def test_a_live_window_overlap_outranks_the_duration_cap():
    """PRD 3.8: "Three checks run on the window, and they run in the order given. First, no
    live waiver for the same policy and the same school may already cover part of it."
    PRD 3.8: "Because the intervals are half-open, exact adjacency — where one window's end
    is the same instant as the next window's start — is permitted; a genuine overlap is
    refused with `ERR_WAIVER_WINDOW_OVERLAP`."

    Design: Difficulty/priority_pair_validation_conflict/waiver_overlap_temporal_beats_duration_cap_constraint
    """
    committee = charter_committee()
    policy = register_policy()
    file_waiver(
        policy["id"],
        committee["id"],
        requesting_school_code="HS-01",
        justification="Pilot period one",
    )

    response = api_client.create_waiver_request(
        waiver_request_payload(
            policy["id"],
            committee["id"],
            requesting_school_code="HS-01",
            justification="Extended pilot that both overlaps and overruns",
            requested_start_date="2026-10-15T00:00:00Z",
            requested_end_date="2027-06-15T00:00:00Z",
        ),
        PRINCIPAL,
    )
    error = validate_error(response, ApiErrorId.ERR_WAIVER_WINDOW_OVERLAP.value)
    assert response.status_code == 409
    assert error["error_id"] != ApiErrorId.ERR_WAIVER_DURATION_EXCEEDS_CAP.value


def test_the_refused_overlapping_request_leaves_the_live_waiver_alone():
    """PRD 3.8: "Third, that same whole-day count may not exceed the cap the linked
    policy's `legal_requirement_level` imposes, which is recorded on the request as
    `max_allowed_days` at creation: 90 days for a `REQUIRED_BY_LAW` policy, 180 days for a
    `RECOMMENDED` one, and a full 365 days for one at `LOCAL_DISCRETION`."
    PRD 3.8: "Waiver requests can be listed and filtered by `policy_id`, by
    `reviewing_committee_id`, by `status`, or by `requesting_school_code`."

    Design: Difficulty/priority_pair_validation_conflict/waiver_overlap_temporal_beats_duration_cap_constraint
    """
    committee = charter_committee()
    policy = register_policy()
    live = file_waiver(
        policy["id"],
        committee["id"],
        requesting_school_code="HS-01",
        justification="Pilot period one",
    )
    api_client.create_waiver_request(
        waiver_request_payload(
            policy["id"],
            committee["id"],
            requesting_school_code="HS-01",
            justification="Extended pilot that both overlaps and overruns",
            requested_start_date="2026-10-15T00:00:00Z",
            requested_end_date="2027-06-15T00:00:00Z",
        ),
        PRINCIPAL,
    )

    row = read_waiver(live["id"])
    assert row["max_allowed_days"] == 90
    assert row["status"] == "SUBMITTED"
    _rows, meta = validate_paginated(
        api_client.list_waiver_requests(PUBLIC, {"policy_id": policy["id"]})
    )
    assert meta["total_count"] == 1


def test_a_window_beginning_exactly_where_the_previous_one_ends_is_accepted():
    """PRD 3.8: "the half-open window the relief would cover: `requested_start_date`
    inclusive and `requested_end_date` exclusive, where the end must be strictly after the
    start."
    PRD 3.8: "Because the intervals are half-open, exact adjacency — where one window's end
    is the same instant as the next window's start — is permitted; a genuine overlap is
    refused with `ERR_WAIVER_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/waiver_window_half_open_adjacency_allowed_but_overlap_rejected
    """
    committee = charter_committee()
    policy = register_policy("BP-6155", "Homework and Grading", "INSTRUCTION", "RECOMMENDED", "6000.55")
    file_waiver(
        policy["id"],
        committee["id"],
        requesting_school_code="HS-01",
        justification="Pilot period one",
    )

    response = api_client.create_waiver_request(
        waiver_request_payload(
            policy["id"],
            committee["id"],
            requesting_school_code="HS-01",
            justification="Pilot period two, starts the instant period one ends",
            requested_start_date="2026-11-01T00:00:00Z",
            requested_end_date="2026-12-01T00:00:00Z",
        ),
        PRINCIPAL,
    )
    data = validate_success(response, 201)
    assert data["status"] == "SUBMITTED"


def test_a_window_sharing_an_interior_day_with_a_live_waiver_is_refused():
    """PRD 3.8: "First, no live waiver for the same policy and the same school may already
    cover part of it. A waiver is live for this purpose when its `status` is `SUBMITTED`,
    `BOARD_PENDING` or `GRANTED`, and the windows overlap when the existing window's start
    falls before the new window's end **and** the new window's start falls before the
    existing window's end."

    Design: Difficulty/resource_temporal_overlap/waiver_window_half_open_adjacency_allowed_but_overlap_rejected
    """
    committee = charter_committee()
    policy = register_policy("BP-6155", "Homework and Grading", "INSTRUCTION", "RECOMMENDED", "6000.55")
    file_waiver(
        policy["id"],
        committee["id"],
        requesting_school_code="HS-01",
        justification="Pilot period one",
    )
    file_waiver(
        policy["id"],
        committee["id"],
        requesting_school_code="HS-01",
        justification="Pilot period two, starts the instant period one ends",
        requested_start_date="2026-11-01T00:00:00Z",
        requested_end_date="2026-12-01T00:00:00Z",
    )

    response = api_client.create_waiver_request(
        waiver_request_payload(
            policy["id"],
            committee["id"],
            requesting_school_code="HS-01",
            justification="Overlapping window",
            requested_start_date="2026-10-15T00:00:00Z",
            requested_end_date="2026-11-15T00:00:00Z",
        ),
        PRINCIPAL,
    )
    validate_error(response, ApiErrorId.ERR_WAIVER_WINDOW_OVERLAP.value)
    assert response.status_code == 409

    _rows, meta = validate_paginated(
        api_client.list_waiver_requests(PUBLIC, {"policy_id": policy["id"]})
    )
    assert meta["total_count"] == 2


def _revocation_scenario():
    """A GRANTED waiver still listed on a second, OPEN meeting whose speaker cards have
    already been allotted the whole five-minute budget."""
    members = seat_board(3)
    ids = [m["id"] for m in members]
    committee_setup = setup_active_committee(members)
    policy = register_policy("BP-6155", "Homework and Grading", "INSTRUCTION", "RECOMMENDED", "6000.55")
    waiver = file_waiver(
        policy["id"],
        committee_setup["committee"]["id"],
        requesting_school_code="HS-01",
        justification="Block schedule pilot",
        requested_start_date="2026-10-01T00:00:00Z",
        requested_end_date="2026-12-01T00:00:00Z",
    )
    recommend_waiver(waiver["id"], committee_setup["chair"]["id"], "RECOMMEND_GRANT")

    decision_meeting = schedule_meeting(
        title="September Regular Meeting", scheduled_start_utc="2026-09-10T18:00:00Z"
    )
    decision_item = add_agenda_item(
        decision_meeting["id"],
        decision_meeting["version"],
        item_type="WAIVER_DECISION",
        title="Waiver HS-01 decision",
        waiver_request_id=waiver["id"],
    )
    follow_up = schedule_meeting(
        title="Special Follow-up Meeting",
        meeting_type="SPECIAL",
        scheduled_start_utc="2026-09-24T18:00:00Z",
    )
    follow_up_item = add_agenda_item(
        follow_up["id"],
        follow_up["version"],
        item_type="WAIVER_DECISION",
        title="Waiver HS-01 follow-up",
        waiver_request_id=waiver["id"],
    )
    first_card = file_speaker_card(follow_up_item["id"], "Iris Vega", "PARENT", 3)
    set_clock("2026-08-01T01:00:00Z")
    second_card = file_speaker_card(follow_up_item["id"], "Jonah Park", "STAFF", 3)

    post_notice(decision_meeting["id"])
    post_notice(follow_up["id"])
    set_clock("2026-09-10T18:00:00Z")
    open_meeting(decision_meeting["id"], ids, ids[0])
    record_vote(decision_item["id"], ids[0], yes_member_ids=ids[:2], no_member_ids=ids[2:3])
    adjourn_meeting(decision_meeting["id"])
    set_clock("2026-09-24T18:00:00Z")
    open_meeting(follow_up["id"], ids, ids[0])

    return {
        "policy": policy,
        "waiver": waiver,
        "decision_item": decision_item,
        "follow_up": follow_up,
        "follow_up_item": follow_up_item,
        "cards": [first_card, second_card],
    }


def test_revocation_rewrites_the_granted_window_and_drops_the_active_waiver_count():
    """PRD 3.8: "It is a four-hop cascade that leaves the waiver in the terminal `REVOKED`
    state. `revoked_on` is stamped from the logical clock, `granted_end_date` is rewritten
    to that same instant, and `granted_days` is recomputed as the whole number of days from
    `granted_start_date` to the new end, never below zero. Because the waiver is no longer
    live, the policy's `active_waiver_count` is recomputed and phase 2 rewrites
    `compliance_state`."

    Design: Difficulty/transitive_cascade/waiver_revocation_four_hop_speaker_minute_release_cascade
    """
    scenario = _revocation_scenario()
    validate_success(api_client.revoke_waiver_request(scenario["waiver"]["id"], SUPT), 200)

    waiver = read_waiver(scenario["waiver"]["id"])
    assert waiver["status"] == "REVOKED"
    assert_instant_equals(waiver["revoked_on"], "2026-09-24T18:00:00Z", "WaiverRequest.revoked_on")
    assert_instant_equals(
        waiver["granted_start_date"], "2026-10-01T00:00:00Z", "WaiverRequest.granted_start_date"
    )
    assert_instant_equals(
        waiver["granted_end_date"], "2026-09-24T18:00:00Z", "WaiverRequest.granted_end_date"
    )
    assert waiver["granted_days"] == 0
    assert read_policy(scenario["policy"]["id"])["active_waiver_count"] == 0


def test_revocation_withdraws_the_live_item_and_credits_its_speaker_minutes_back():
    """PRD 3.8: "Because the waiver is now terminal, every agenda item referencing it in
    `PROPOSED` or `POSTED` status moves to `WITHDRAWN`. And because those items were
    withdrawn, every speaker card on them in `REQUESTED` or `GRANTED` status moves to
    `RELEASED` with `denial_reason` `ITEM_WITHDRAWN`, `allotted_minutes` reset to 0, and
    exactly the released total credited back to the meeting's
    `public_comment_minutes_remaining`."
    PRD 3.6: "`vote_outcome` is `PASSED` when `vote_yes` has reached `required_yes_votes`
    and `FAILED` otherwise. Recording the vote moves the item `POSTED → ACTED`, stamps
    `acted_at` from the logical clock, and freezes the whole ledger."

    Design: Difficulty/transitive_cascade/waiver_revocation_four_hop_speaker_minute_release_cascade
    """
    scenario = _revocation_scenario()
    api_client.revoke_waiver_request(scenario["waiver"]["id"], SUPT)

    assert read_agenda_item(scenario["decision_item"]["id"])["status"] == "ACTED"
    assert read_agenda_item(scenario["follow_up_item"]["id"])["status"] == "WITHDRAWN"

    item_id = scenario["follow_up_item"]["id"]
    first = read_speaker_card(item_id, scenario["cards"][0]["id"])
    second = read_speaker_card(item_id, scenario["cards"][1]["id"])
    assert first["status"] == "RELEASED"
    assert first["allotted_minutes"] == 0
    assert first["denial_reason"] == "ITEM_WITHDRAWN"
    assert second["status"] == "RELEASED"
    assert second["allotted_minutes"] == 0

    meeting = read_meeting(scenario["follow_up"]["id"])
    assert meeting["public_comment_minutes_remaining"] == 5
    assert meeting["public_comment_minutes_budget"] == 5
