"""Conducting the meeting: quorum guards, the roll-call vote and the frozen tally."""

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_agenda_item,
    api_client,
    assert_instant_equals,
    assert_vote_ledger_balances,
    file_disclosure,
    make_board_president_headers,
    open_meeting,
    post_notice,
    read_agenda_item,
    read_disclosure,
    read_meeting,
    read_policy,
    read_policy_version,
    record_vote,
    schedule_meeting,
    seat_board,
    set_clock,
    setup_open_meeting_with_first_reading,
    setup_policy_with_draft,
    setup_second_reading_stage,
    validate_error,
    validate_paginated,
    validate_success,
    vote_payload,
)

PUBLIC = TEST_USERS["public_headers"]
CLERK = TEST_USERS["board_clerk_headers"]


def test_a_trustee_named_twice_across_the_arrays_is_refused():
    """PRD 3.6: "And no trustee may appear more than once across the three arrays, nor
    twice within one array; a double vote is refused with `ERR_DUPLICATE_VOTER`."

    Design: Corner/validations/vote_listing_the_same_trustee_twice_returns_duplicate_voter
    """
    members = seat_board(3)
    ids = [m["id"] for m in members]
    policy, version = setup_policy_with_draft()
    meeting, item = setup_open_meeting_with_first_reading(
        members, version["id"], item_title="First reading BP-4119"
    )

    response = api_client.record_vote(
        item["id"],
        vote_payload(yes_member_ids=[ids[0], ids[1]], abstain_member_ids=[ids[1]]),
        make_board_president_headers(ids[0]),
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_VOTER.value)
    assert response.status_code == 422

    row = read_agenda_item(item["id"])
    assert row["status"] == "POSTED"
    assert row["vote_yes"] == 0
    assert row["vote_outcome"] is None


def test_a_voter_absent_from_the_frozen_roll_is_refused():
    """PRD 3.6: "Every identifier in the three arrays must appear in the meeting's frozen
    `attending_member_ids`, and a stranger is refused with `ERR_VOTER_NOT_IN_ATTENDANCE`."
    PRD 3.6: "Opening stamps `opened_at` from the logical clock, freezes
    `seated_member_count_snapshot` at the count of trustees whose `status` is `SEATED` at
    that instant, and freezes `attending_member_ids` as supplied."

    Design: Corner/validations/vote_naming_a_trustee_who_was_not_present_returns_voter_not_in_attendance
    """
    members = seat_board(3)
    ids = [m["id"] for m in members]
    policy, version = setup_policy_with_draft()
    meeting, item = setup_open_meeting_with_first_reading(
        members, version["id"], item_title="First reading BP-4119", attending=ids[:2]
    )
    assert meeting["seated_member_count_snapshot"] == 3

    response = api_client.record_vote(
        item["id"],
        vote_payload(yes_member_ids=ids[:2], no_member_ids=[ids[2]]),
        make_board_president_headers(ids[0]),
    )
    validate_error(response, ApiErrorId.ERR_VOTER_NOT_IN_ATTENDANCE.value)
    assert response.status_code == 422
    assert read_agenda_item(item["id"])["status"] == "POSTED"


def test_a_recused_trustee_may_not_be_counted_and_the_clean_vote_tallies_them_as_recused():
    """PRD 3.6: "No trustee named in any of the three arrays may hold a disclosure in
    `RECUSAL_REQUIRED` status on the policy behind this item — the policy behind a reading
    item is the policy of its linked version, the policy behind a `WAIVER_DECISION` item is
    the policy of its linked waiver, and evaluation and consent items have no policy behind
    them at all — and a recused trustee appearing in any array is refused with
    `ERR_RECUSED_MEMBER_VOTED`."
    PRD 3.6: "`recused_member_count` is the number of trustees in the meeting's frozen
    `attending_member_ids` who hold a disclosure in `RECUSAL_REQUIRED` status on the policy
    behind this item, measured at the instant the vote is recorded; for an item with no
    linked policy it is zero. `absent_member_count` is the frozen
    `seated_member_count_snapshot` less the sum of `vote_yes`, `vote_no`, `vote_abstain`
    and `recused_member_count`, which means attendees who cast no vote and are not recused
    are counted as absent for ledger purposes."

    Design: Corner/validations/recused_trustee_named_in_the_vote_returns_recused_member_voted
    """
    members = seat_board(3)
    ids = [m["id"] for m in members]
    policy, version = setup_policy_with_draft()
    file_disclosure(ids[1], policy["id"], "FINANCIAL", "Spouse holds equity in the benefits vendor.")
    meeting, item = setup_open_meeting_with_first_reading(
        members, version["id"], item_title="First reading BP-4119"
    )

    refused = api_client.record_vote(
        item["id"],
        vote_payload(yes_member_ids=ids[:2], no_member_ids=[ids[2]]),
        make_board_president_headers(ids[0]),
    )
    validate_error(refused, ApiErrorId.ERR_RECUSED_MEMBER_VOTED.value)
    assert refused.status_code == 422

    accepted = api_client.record_vote(
        item["id"],
        vote_payload(yes_member_ids=[ids[0]], no_member_ids=[ids[2]]),
        make_board_president_headers(ids[0]),
    )
    validate_success(accepted, 200)

    row = read_agenda_item(item["id"])
    assert row["recused_member_count"] == 1
    assert row["vote_yes"] == 1
    assert row["vote_no"] == 1
    assert row["required_yes_votes"] == 2
    assert row["vote_outcome"] == "FAILED"
    assert row["absent_member_count"] == 0
    assert_vote_ledger_balances(row, meeting["seated_member_count_snapshot"])
    assert read_policy_version(version["id"])["status"] == "DRAFT"


def test_voting_on_a_proposed_item_reports_the_item_state_first():
    """PRD 3.6: "The item must be `POSTED`, and a vote on an item in any other status is
    refused with `ERR_AGENDA_ITEM_NOT_POSTED`; the item's parent meeting must be `OPEN`,
    and otherwise the vote is refused with `ERR_MEETING_NOT_OPEN`."
    PRD 2.7: "10. State preconditions on the resource named in the path
    (`ERR_INVALID_MEETING_STATE`, `ERR_INVALID_MINUTES_STATE`, `ERR_AGENDA_ITEM_NOT_POSTED`,
    `ERR_POLICY_VERSION_NOT_ELIGIBLE`, `ERR_WAIVER_NOT_IN_REVIEW`,
    `ERR_EVALUATION_STAGE_INVALID`, `ERR_PUBLICATION_ALREADY_PUBLISHED`,
    `ERR_MEMBER_NOT_SEATED`, `ERR_ASSIGNMENT_STATE_INVALID`,
    `ERR_DISCLOSURE_ALREADY_CLEARED`)."
    PRD 2.7: "11. The parent meeting of a voted item is open (`ERR_MEETING_NOT_OPEN`)."

    Design: Corner/validations/voting_on_a_proposed_item_returns_agenda_item_not_posted
    """
    members = seat_board(3)
    ids = [m["id"] for m in members]
    policy, version = setup_policy_with_draft()
    meeting = schedule_meeting()
    item = add_agenda_item(
        meeting["id"],
        meeting["version"],
        item_type="POLICY_FIRST_READING",
        title="First reading BP-4119",
        policy_version_id=version["id"],
    )

    response = api_client.record_vote(
        item["id"],
        vote_payload(yes_member_ids=ids[:2], no_member_ids=[ids[2]]),
        make_board_president_headers(ids[0]),
    )
    error = validate_error(response, ApiErrorId.ERR_AGENDA_ITEM_NOT_POSTED.value)
    assert response.status_code == 409
    assert error["error_id"] != ApiErrorId.ERR_MEETING_NOT_OPEN.value
    assert read_agenda_item(item["id"])["status"] == "PROPOSED"


def test_emergency_first_reading_short_of_near_unanimity_stops_at_first_reading_passed():
    """PRD 3.7: "At a meeting whose `meeting_type` is `EMERGENCY`, a
    `POLICY_FIRST_READING` item that passes with `vote_yes` reaching at least one fewer
    than the frozen `seated_member_count_snapshot` — that is, near unanimity of the seated
    board — waives the second reading entirely."
    PRD 3.7: "At an emergency meeting where the passing margin falls short of that
    near-unanimous bar, and at every `REGULAR` or `SPECIAL` meeting regardless of margin, a
    passing first reading takes the ordinary `DRAFT → FIRST_READING_PASSED` route."
    PRD 3.6: "For `POLICY_FIRST_READING`, `SUPERINTENDENT_EVALUATION` and `CONSENT` items,
    the threshold is a simple majority of the votes actually cast: votes cast halved with
    the remainder discarded, plus one."

    Design: Corner/state_machines/emergency_first_reading_below_unanimity_minus_one_stops_at_first_reading_passed
    """
    members = seat_board(5)
    ids = [m["id"] for m in members]
    policy, version = setup_policy_with_draft()
    meeting, item = setup_open_meeting_with_first_reading(
        members,
        version["id"],
        meeting_type="EMERGENCY",
        scheduled_start_utc="2026-08-02T18:00:00Z",
        meeting_title="Emergency Board Meeting",
        item_title="Emergency first reading BP-4119",
    )

    voted = record_vote(item["id"], ids[0], yes_member_ids=ids[:3], no_member_ids=ids[3:5])
    assert voted["required_yes_votes"] == 3
    assert voted["vote_outcome"] == "PASSED"

    row = read_policy_version(version["id"])
    assert row["status"] == "FIRST_READING_PASSED"
    assert row["reading_count"] == 1
    assert row["adopted_at"] is None
    assert row["adopting_meeting_id"] is None
    assert row["first_reading_meeting_id"] == meeting["id"]
    assert read_policy(policy["id"])["status"] == "UNADOPTED"


def test_policy_versions_are_discoverable_by_the_meeting_that_heard_them():
    """PRD 3.7: "A `POLICY_FIRST_READING` item that passes carries its linked version
    `DRAFT → FIRST_READING_PASSED`, sets `reading_count` to 1, records the hosting meeting
    in `first_reading_meeting_id`, raises the version row's own `version` by 1 and refreshes
    its `updated_at`."
    PRD 3.3: "Versions can be listed and filtered by `policy_id`, by `status`, by
    `first_reading_meeting_id`, or by `adopting_meeting_id`; policies themselves can be
    listed and filtered by `status`, by `category`, or by `compliance_state`."

    Design: Corner/endpoints/policy_versions_list_filters_by_first_reading_meeting_id
    """
    members = seat_board(3)
    ids = [m["id"] for m in members]
    policy, version = setup_policy_with_draft()
    meeting, item = setup_open_meeting_with_first_reading(
        members, version["id"], item_title="First reading BP-4119"
    )
    record_vote(item["id"], ids[0], yes_member_ids=ids[:2], no_member_ids=ids[2:3])

    rows, meta = validate_paginated(
        api_client.list_policy_versions(PUBLIC, {"first_reading_meeting_id": meeting["id"]})
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == version["id"]

    _filtered, filtered_meta = validate_paginated(
        api_client.list_policy_versions(
            PUBLIC, {"policy_id": policy["id"], "status": "FIRST_READING_PASSED"}
        )
    )
    assert filtered_meta["total_count"] == 1

    stored = read_policy_version(version["id"])
    assert stored["first_reading_meeting_id"] == meeting["id"]
    assert stored["adopting_meeting_id"] is None


def _noticed_meeting_with_recused_voter():
    members = seat_board(3)
    ids = [m["id"] for m in members]
    policy, version = setup_policy_with_draft()
    disclosure = file_disclosure(
        ids[1], policy["id"], "FINANCIAL", "Spouse holds equity in the benefits vendor named in this policy."
    )
    meeting = schedule_meeting()
    item = add_agenda_item(
        meeting["id"],
        meeting["version"],
        item_type="POLICY_FIRST_READING",
        title="First reading BP-4119",
        policy_version_id=version["id"],
    )
    post_notice(meeting["id"])
    return members, ids, disclosure, meeting, item


def test_a_meeting_that_never_opened_outranks_the_recusal_safety_check():
    """PRD 3.6: "The item must be `POSTED`, and a vote on an item in any other status is
    refused with `ERR_AGENDA_ITEM_NOT_POSTED`; the item's parent meeting must be `OPEN`,
    and otherwise the vote is refused with `ERR_MEETING_NOT_OPEN`."
    PRD 2.7: "11. The parent meeting of a voted item is open (`ERR_MEETING_NOT_OPEN`)."
    PRD 2.7: "14. Open-meeting safety, in this internal order: notice lead time
    (`ERR_NOTICE_PERIOD_TOO_SHORT`), recused voter (`ERR_RECUSED_MEMBER_VOTED`), quorum
    (`ERR_QUORUM_NOT_MET`), same-meeting second reading (`ERR_SECOND_READING_SAME_MEETING`),
    unapproved first-reading minutes (`ERR_MINUTES_NOT_APPROVED`), voter not in attendance
    (`ERR_VOTER_NOT_IN_ATTENDANCE`)."

    Design: Difficulty/priority_pair_validation_conflict/vote_meeting_state_beats_recusal_safety_check
    """
    members, ids, disclosure, meeting, item = _noticed_meeting_with_recused_voter()

    response = api_client.record_vote(
        item["id"],
        vote_payload(yes_member_ids=ids[:2], no_member_ids=ids[2:3]),
        make_board_president_headers(ids[0]),
    )
    error = validate_error(response, ApiErrorId.ERR_MEETING_NOT_OPEN.value)
    assert response.status_code == 409
    assert error["error_id"] != ApiErrorId.ERR_RECUSED_MEMBER_VOTED.value


def test_the_refused_vote_leaves_the_item_ledger_and_the_disclosure_untouched():
    """PRD 3.2: "A `FINANCIAL` or `VENDOR` interest is categorically disqualifying and
    lands as `RECUSAL_REQUIRED` regardless of which policy it touches."
    PRD 3.6: "`vote_outcome` is `PASSED` when `vote_yes` has reached `required_yes_votes`
    and `FAILED` otherwise. Recording the vote moves the item `POSTED → ACTED`, stamps
    `acted_at` from the logical clock, and freezes the whole ledger."

    Design: Difficulty/priority_pair_validation_conflict/vote_meeting_state_beats_recusal_safety_check
    """
    members, ids, disclosure, meeting, item = _noticed_meeting_with_recused_voter()
    api_client.record_vote(
        item["id"],
        vote_payload(yes_member_ids=ids[:2], no_member_ids=ids[2:3]),
        make_board_president_headers(ids[0]),
    )

    assert read_disclosure(disclosure["id"])["status"] == "RECUSAL_REQUIRED"
    row = read_agenda_item(item["id"])
    assert row["status"] == "POSTED"
    assert row["vote_outcome"] is None


def test_required_by_law_second_reading_needs_the_two_thirds_ceiling():
    """PRD 3.6: "For a `POLICY_SECOND_READING` item on a policy whose
    `legal_requirement_level` is `REQUIRED_BY_LAW`, the threshold is a two-thirds
    supermajority of the whole seated body: two times the frozen
    `seated_member_count_snapshot`, divided by three, rounded **up** to the next whole
    trustee."
    PRD 3.6: "`vote_outcome` is `PASSED` when `vote_yes` has reached `required_yes_votes`
    and `FAILED` otherwise. Recording the vote moves the item `POSTED → ACTED`, stamps
    `acted_at` from the logical clock, and freezes the whole ledger."

    Design: Difficulty/boundary_precision_check/supermajority_threshold_at_exactly_ceil_two_thirds_of_seated_body
    """
    members = seat_board(5)
    ids = [m["id"] for m in members]
    policy, version = setup_policy_with_draft()
    stage = setup_second_reading_stage(
        members,
        policy,
        version,
        first_yes=ids[:3],
        first_no=ids[3:4],
        first_abstain=ids[4:5],
    )

    voted = record_vote(
        stage["ai2"]["id"], ids[0], yes_member_ids=ids[:4], no_member_ids=ids[4:5]
    )
    assert voted["required_yes_votes"] == 4
    assert voted["vote_yes"] == 4
    assert voted["vote_outcome"] == "PASSED"
    assert voted["absent_member_count"] == 0
    assert_vote_ledger_balances(voted, stage["m2"]["seated_member_count_snapshot"])


def test_clearing_the_supermajority_adopts_the_version_with_the_thirty_day_delay():
    """PRD 3.7: "When the second reading passes, the full adoption cascade fires, and every
    hop of it must land inside the same request. The version's `reading_count` becomes 2,
    `adopting_meeting_id` records the hosting meeting, `adopted_at` is stamped from the
    logical clock, and `effective_date` is set to 30 days after `adopted_at` — the standard
    delay before a regularly adopted policy takes force."
    PRD 3.7: "the policy's `status` becomes `ADOPTED`, its `adopted_version_no` becomes
    this version's `version_no`, its `last_review_date` is set to `adopted_at`, and its
    `version` rises by 1."

    Design: Difficulty/boundary_precision_check/supermajority_threshold_at_exactly_ceil_two_thirds_of_seated_body
    """
    members = seat_board(5)
    ids = [m["id"] for m in members]
    policy, version = setup_policy_with_draft()
    stage = setup_second_reading_stage(
        members,
        policy,
        version,
        first_yes=ids[:3],
        first_no=ids[3:4],
        first_abstain=ids[4:5],
    )
    record_vote(stage["ai2"]["id"], ids[0], yes_member_ids=ids[:4], no_member_ids=ids[4:5])

    version_row = read_policy_version(version["id"])
    assert version_row["status"] == "ADOPTED"
    assert version_row["reading_count"] == 2
    assert_instant_equals(
        version_row["effective_date"], "2026-10-24T18:00:00Z", "PolicyVersion.effective_date"
    )
    policy_row = read_policy(policy["id"])
    assert policy_row["status"] == "ADOPTED"
    assert policy_row["adopted_version_no"] == 1
