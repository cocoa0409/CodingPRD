"""Scheduling meetings, posting the statutory notice, building and locking the agenda."""

import pytest

from test_helpers import (
    ApiErrorId,
    CLOCK_START,
    TEST_USERS,
    add_agenda_item,
    adjourn_meeting,
    api_client,
    approve_minutes,
    assert_instant_equals,
    assert_meeting,
    charter_committee,
    draft_minutes,
    file_waiver,
    meeting_payload,
    open_meeting,
    post_notice,
    read_agenda_item,
    read_meeting,
    read_policy_version,
    register_policy,
    schedule_meeting,
    seat_board,
    set_clock,
    setup_policy_with_draft,
    validate_error,
    validate_paginated,
    validate_success,
    withdraw_version,
)

CLERK = TEST_USERS["board_clerk_headers"]
PUBLIC = TEST_USERS["public_headers"]


def test_meeting_defaults_to_first_come_capped_with_the_regular_budget():
    """PRD 3.4: "The presiding officer may also select the `public_comment_rule` that will
    govern speaker time, choosing `FIRST_COME_CAPPED` or `EQUAL_SPLIT`; when omitted it
    defaults to `FIRST_COME_CAPPED`."
    PRD 3.4: "A newly scheduled meeting opens with `status` `DRAFT` and `minutes_status`
    `NOT_DRAFTED` — two independent axes on the same record — and with `notice_posted_at`,
    `agenda_locked_at`, `opened_at`, `adjourned_at`, `minutes_approved_at_meeting_id` and
    `public_comment_allocation_variant` all null, `seated_member_count_snapshot` 0, and
    `attending_member_ids` an empty array. Its `public_comment_minutes_budget` is fixed at
    creation from the `meeting_type`: a regular meeting carries half an hour of public
    comment, thirty minutes; a special meeting carries five minutes; an emergency meeting
    carries none at all. `public_comment_minutes_remaining` starts equal to the budget and
    stays there until the meeting is called to order."

    Design: Corner/entities/create_meeting_without_public_comment_rule_applies_first_come_capped_default
    """
    response = api_client.create_meeting(
        meeting_payload(
            title="September Regular Meeting",
            scope="FULL_BOARD",
            meeting_type="REGULAR",
            scheduled_start_utc="2026-09-10T18:00:00Z",
        ),
        CLERK,
    )
    data = validate_success(response, 201)
    assert_meeting(data)
    assert data["public_comment_rule"] == "FIRST_COME_CAPPED"
    assert data["public_comment_minutes_budget"] == 30
    assert data["public_comment_minutes_remaining"] == 30
    assert data["status"] == "DRAFT"
    assert data["minutes_status"] == "NOT_DRAFTED"
    assert data["public_comment_allocation_variant"] is None
    assert data["committee_id"] is None


def test_committee_scoped_meeting_without_a_committee_is_malformed():
    """PRD 3.4: "A `committee_id` must be supplied exactly when `scope` is `COMMITTEE` and
    must be omitted or null when `scope` is `FULL_BOARD`; getting that combination wrong
    is a malformed request."

    Design: Corner/entities/committee_meeting_without_committee_id_returns_invalid_request
    """
    response = api_client.create_meeting(
        meeting_payload(
            title="Policy Committee Meeting",
            scope="COMMITTEE",
            meeting_type="REGULAR",
            scheduled_start_utc="2026-09-10T18:00:00Z",
        ),
        CLERK,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)
    assert response.status_code == 400


def test_adjourning_a_meeting_that_never_opened_is_refused():
    """PRD 3.4: "Attempting to post notice on a meeting whose `status` is not `DRAFT` —
    like attempting to open one that is not `NOTICED`, or adjourn one that is not `OPEN` —
    is refused with `ERR_INVALID_MEETING_STATE`."

    Design: Corner/state_machines/adjourn_meeting_that_is_still_noticed_returns_invalid_meeting_state
    """
    meeting = schedule_meeting()
    post_notice(meeting["id"])

    response = api_client.adjourn_meeting(meeting["id"], CLERK)
    validate_error(response, ApiErrorId.ERR_INVALID_MEETING_STATE.value)
    assert response.status_code == 409

    row = read_meeting(meeting["id"])
    assert row["status"] == "NOTICED"
    assert row["adjourned_at"] is None


def test_posting_the_notice_a_second_time_is_refused_and_keeps_the_first_stamp():
    """PRD 3.4: "Posting notice stamps `notice_posted_at` from the logical clock and
    stamps `agenda_locked_at` with that same instant, and it moves every agenda item on
    the meeting from `PROPOSED` to `POSTED` without renumbering anything, because
    `sequence_no` was fixed at creation."
    PRD 3.4: "Attempting to post notice on a meeting whose `status` is not `DRAFT` — like
    attempting to open one that is not `NOTICED`, or adjourn one that is not `OPEN` — is
    refused with `ERR_INVALID_MEETING_STATE`."

    Design: Corner/state_machines/posting_notice_twice_returns_invalid_meeting_state
    """
    meeting = schedule_meeting()
    post_notice(meeting["id"])
    set_clock("2026-08-02T00:00:00Z")

    response = api_client.post_meeting_notice(meeting["id"], CLERK)
    validate_error(response, ApiErrorId.ERR_INVALID_MEETING_STATE.value)
    assert response.status_code == 409

    row = read_meeting(meeting["id"])
    assert_instant_equals(row["notice_posted_at"], CLOCK_START, "Meeting.notice_posted_at")
    assert_instant_equals(row["agenda_locked_at"], CLOCK_START, "Meeting.agenda_locked_at")


def test_notice_posts_every_proposed_item_without_renumbering():
    """PRD 3.4: "Posting notice stamps `notice_posted_at` from the logical clock and
    stamps `agenda_locked_at` with that same instant, and it moves every agenda item on
    the meeting from `PROPOSED` to `POSTED` without renumbering anything, because
    `sequence_no` was fixed at creation."
    PRD 3.4: "On creation the item receives a `sequence_no` assigned sequentially per
    meeting starting at 1 in ascending `created_at` order and never reused when an item is
    later withdrawn, a `status` of `PROPOSED`, and a `requires_public_comment` flag that is
    true exactly when `item_type` is one of `POLICY_FIRST_READING`, `POLICY_SECOND_READING`
    or `WAIVER_DECISION` and false for the other two."

    Design: Corner/state_machines/notice_posts_every_proposed_agenda_item
    """
    meeting = schedule_meeting()
    first = add_agenda_item(meeting["id"], meeting["version"], "CONSENT", "Approve warrants")
    second = add_agenda_item(
        meeting["id"], first["meeting_version_after"], "CONSENT", "Approve field trips"
    )

    post_notice(meeting["id"])

    first_row = read_agenda_item(first["id"])
    second_row = read_agenda_item(second["id"])
    assert first_row["status"] == "POSTED"
    assert second_row["status"] == "POSTED"
    assert first_row["sequence_no"] == 1
    assert second_row["sequence_no"] == 2
    assert first_row["requires_public_comment"] is False
    assert read_meeting(meeting["id"])["status"] == "NOTICED"


def test_notice_one_second_short_of_the_lead_time_is_refused():
    """PRD 3.4: "It is permitted only when the difference between `scheduled_start_utc`
    and the logical clock is at least the notice lead time for the meeting's
    `meeting_type`: 72 hours — three full days — for a `REGULAR` meeting, 48 hours for a
    `SPECIAL` meeting, and 24 hours for an `EMERGENCY` meeting. The boundary is inclusive:
    a notice posted at exactly the lead time is good, and anything shorter is refused with
    `ERR_NOTICE_PERIOD_TOO_SHORT`."

    Design: Corner/validations/notice_one_second_short_of_the_lead_time_is_rejected
    """
    meeting = schedule_meeting(
        title="Boundary Notice Meeting", scheduled_start_utc="2026-08-04T00:00:00Z"
    )
    set_clock("2026-08-01T00:00:01Z")

    response = api_client.post_meeting_notice(meeting["id"], CLERK)
    validate_error(response, ApiErrorId.ERR_NOTICE_PERIOD_TOO_SHORT.value)
    assert response.status_code == 422

    row = read_meeting(meeting["id"])
    assert row["status"] == "DRAFT"
    assert row["notice_posted_at"] is None
    assert row["agenda_locked_at"] is None


def test_notice_at_exactly_seventy_two_hours_is_accepted():
    """PRD 3.4: "It is permitted only when the difference between `scheduled_start_utc`
    and the logical clock is at least the notice lead time for the meeting's
    `meeting_type`: 72 hours — three full days — for a `REGULAR` meeting, 48 hours for a
    `SPECIAL` meeting, and 24 hours for an `EMERGENCY` meeting. The boundary is inclusive:
    a notice posted at exactly the lead time is good, and anything shorter is refused with
    `ERR_NOTICE_PERIOD_TOO_SHORT`."

    Design: Difficulty/boundary_precision_check/notice_lead_time_at_exactly_seventy_two_hours_is_accepted
    """
    meeting = schedule_meeting(
        title="Boundary Notice Meeting", scheduled_start_utc="2026-08-04T00:00:00Z"
    )
    assert meeting["status"] == "DRAFT"

    response = api_client.post_meeting_notice(meeting["id"], CLERK)
    data = validate_success(response, 200)
    assert data["status"] == "NOTICED"


def test_notice_at_the_lead_time_boundary_stamps_both_clock_marks():
    """PRD 3.4: "Posting notice stamps `notice_posted_at` from the logical clock and
    stamps `agenda_locked_at` with that same instant, and it moves every agenda item on
    the meeting from `PROPOSED` to `POSTED` without renumbering anything, because
    `sequence_no` was fixed at creation."
    PRD 2.4: "The clock starts at exactly `2026-08-01T00:00:00.000Z` when the server
    starts and never falls back to real wall-clock time."

    Design: Difficulty/boundary_precision_check/notice_lead_time_at_exactly_seventy_two_hours_is_accepted
    """
    meeting = schedule_meeting(
        title="Boundary Notice Meeting", scheduled_start_utc="2026-08-04T00:00:00Z"
    )
    post_notice(meeting["id"])

    row = read_meeting(meeting["id"])
    assert row["status"] == "NOTICED"
    assert_instant_equals(row["notice_posted_at"], CLOCK_START, "Meeting.notice_posted_at")
    assert_instant_equals(row["agenda_locked_at"], CLOCK_START, "Meeting.agenda_locked_at")


def test_meeting_exactly_two_hundred_forty_minutes_later_is_permitted():
    """PRD 3.4: "Before a meeting is created, the system looks for another meeting with
    the same `scope` and the same `committee_id` — where a null committee matches a null
    committee — whose `status` is `DRAFT`, `NOTICED` or `OPEN`, and whose
    `scheduled_start_utc` sits strictly less than four hours away from the proposed start
    in either direction. Because the buffer is symmetric around the instant and measured
    as 240 minutes, two meetings exactly four hours apart are permitted, while anything
    closer is refused with `ERR_MEETING_SEPARATION_VIOLATION`."

    Design: Difficulty/resource_temporal_overlap/meeting_calendar_separation_buffer_at_exactly_240_minutes
    """
    schedule_meeting(title="Board Meeting A", scheduled_start_utc="2026-09-10T18:00:00Z")

    response = api_client.create_meeting(
        meeting_payload(
            title="Board Meeting B",
            scope="FULL_BOARD",
            meeting_type="REGULAR",
            scheduled_start_utc="2026-09-10T22:00:00Z",
        ),
        CLERK,
    )
    data = validate_success(response, 201)
    assert data["status"] == "DRAFT"

    _rows, meta = validate_paginated(api_client.list_meetings(PUBLIC, {"limit": 100}))
    assert meta["total_count"] == 2


def test_meeting_two_hundred_thirty_nine_minutes_later_collides():
    """PRD 3.4: "Because the buffer is symmetric around the instant and measured as 240
    minutes, two meetings exactly four hours apart are permitted, while anything closer is
    refused with `ERR_MEETING_SEPARATION_VIOLATION`."

    Design: Difficulty/resource_temporal_overlap/meeting_calendar_separation_buffer_at_exactly_240_minutes
    """
    schedule_meeting(title="Board Meeting A", scheduled_start_utc="2026-09-10T18:00:00Z")
    schedule_meeting(title="Board Meeting B", scheduled_start_utc="2026-09-10T22:00:00Z")

    response = api_client.create_meeting(
        meeting_payload(
            title="Board Meeting C",
            scope="FULL_BOARD",
            meeting_type="REGULAR",
            scheduled_start_utc="2026-09-11T01:59:00Z",
        ),
        CLERK,
    )
    validate_error(response, ApiErrorId.ERR_MEETING_SEPARATION_VIOLATION.value)
    assert response.status_code == 409

    _rows, meta = validate_paginated(api_client.list_meetings(PUBLIC, {"limit": 100}))
    assert meta["total_count"] == 2


def test_agenda_lock_outranks_the_linked_version_eligibility_check():
    """PRD 3.4: "Once `agenda_locked_at` is set, no further item may be added and the
    attempt is refused with `ERR_AGENDA_LOCKED`."
    PRD 2.7: "15. Temporal rules, in this internal order: agenda lock (`ERR_AGENDA_LOCKED`),
    waiver window overlap (`ERR_WAIVER_WINDOW_OVERLAP`), meeting separation
    (`ERR_MEETING_SEPARATION_VIOLATION`), meeting not yet due (`ERR_MEETING_NOT_YET_DUE`),
    invalid approving meeting (`ERR_INVALID_APPROVING_MEETING`)."
    PRD 2.7: "17. Referential eligibility, in this internal order: linked-object
    eligibility at agenda-build time (`ERR_POLICY_VERSION_NOT_ELIGIBLE`,
    `ERR_WAIVER_NOT_IN_REVIEW`), version on a live agenda (`ERR_VERSION_ON_LIVE_AGENDA`),
    no adopted policies to publish (`ERR_NO_ADOPTED_POLICIES`), no ratings submitted
    (`ERR_NO_RATINGS_SUBMITTED`)."

    Design: Difficulty/priority_pair_validation_conflict/agenda_lock_temporal_beats_withdrawn_version_referential
    """
    policy, version = setup_policy_with_draft()
    withdraw_version(version["id"], "Superseded by counsel guidance before first reading.")
    meeting = schedule_meeting()
    noticed = post_notice(meeting["id"])

    response = api_client.create_agenda_item(
        {
            "meeting_id": meeting["id"],
            "item_type": "POLICY_FIRST_READING",
            "title": "First reading of a withdrawn draft",
            "expected_meeting_version": noticed["version"],
            "policy_version_id": version["id"],
        },
        CLERK,
    )
    error = validate_error(response, ApiErrorId.ERR_AGENDA_LOCKED.value)
    assert response.status_code == 422
    assert error["error_id"] != ApiErrorId.ERR_POLICY_VERSION_NOT_ELIGIBLE.value


def test_a_locked_agenda_accepts_no_item_and_keeps_the_withdrawn_version_untouched():
    """PRD 3.4: "Once `agenda_locked_at` is set, no further item may be added and the
    attempt is refused with `ERR_AGENDA_LOCKED`."
    PRD 3.4: "agenda items can be listed and filtered by `meeting_id`, by
    `policy_version_id`, by `waiver_request_id`, or by `status`."

    Design: Difficulty/priority_pair_validation_conflict/agenda_lock_temporal_beats_withdrawn_version_referential
    """
    policy, version = setup_policy_with_draft()
    withdraw_version(version["id"], "Superseded by counsel guidance before first reading.")
    meeting = schedule_meeting()
    noticed = post_notice(meeting["id"])
    assert_instant_equals(noticed["agenda_locked_at"], CLOCK_START, "Meeting.agenda_locked_at")

    api_client.create_agenda_item(
        {
            "meeting_id": meeting["id"],
            "item_type": "POLICY_FIRST_READING",
            "title": "First reading of a withdrawn draft",
            "expected_meeting_version": noticed["version"],
            "policy_version_id": version["id"],
        },
        CLERK,
    )

    assert read_policy_version(version["id"])["status"] == "WITHDRAWN"
    _rows, meta = validate_paginated(
        api_client.list_agenda_items(PUBLIC, {"meeting_id": meeting["id"]})
    )
    assert meta["total_count"] == 0


def test_stale_expected_meeting_version_is_refused_with_precondition_failed():
    """PRD 2.6: "Adding an item to an agenda requires a non-optional
    `expected_meeting_version` field in the request body, carrying the client's last
    observed `version` of the target meeting. If that value does not equal the meeting's
    current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_meeting_version_returns_precondition_failed
    """
    meeting = schedule_meeting()
    first = validate_success(
        api_client.create_agenda_item(
            {
                "meeting_id": meeting["id"],
                "item_type": "CONSENT",
                "title": "Approve warrants",
                "expected_meeting_version": meeting["version"],
            },
            CLERK,
        ),
        201,
    )
    assert first["meeting_version_after"] == 2

    stale = api_client.create_agenda_item(
        {
            "meeting_id": meeting["id"],
            "item_type": "CONSENT",
            "title": "Approve field trips",
            "expected_meeting_version": meeting["version"],
        },
        CLERK,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION.value)
    assert stale.status_code == 412

    assert read_meeting(meeting["id"])["version"] == 2
    _rows, meta = validate_paginated(
        api_client.list_agenda_items(PUBLIC, {"meeting_id": meeting["id"]})
    )
    assert meta["total_count"] == 1
    assert read_agenda_item(first["id"])["sequence_no"] == 1


def test_stale_version_is_the_only_precondition_failed_response():
    """PRD 2.6: "No other endpoint in this system takes a version field, and no other
    endpoint may reject a request for concurrency reasons."
    PRD 2.6: "Adding an item to an agenda requires a non-optional
    `expected_meeting_version` field in the request body, carrying the client's last
    observed `version` of the target meeting. If that value does not equal the meeting's
    current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/errors/stale_version_error_returns_precondition_failed_on_agenda_write
    """
    meeting = schedule_meeting()
    first = add_agenda_item(meeting["id"], meeting["version"], "CONSENT", "Approve warrants")

    response = api_client.create_agenda_item(
        {
            "meeting_id": meeting["id"],
            "item_type": "CONSENT",
            "title": "Approve field trips",
            "expected_meeting_version": first["meeting_version_after"] - 1,
        },
        CLERK,
    )
    validate_error(response, ApiErrorId.ERR_STALE_VERSION.value)
    assert response.status_code == 412
    assert response.json()["response_type"] == "error"

    _rows, meta = validate_paginated(
        api_client.list_agenda_items(PUBLIC, {"meeting_id": meeting["id"]})
    )
    assert meta["total_count"] == 1


def test_agenda_items_are_reachable_by_the_waiver_they_list():
    """PRD 3.4: "agenda items can be listed and filtered by `meeting_id`, by
    `policy_version_id`, by `waiver_request_id`, or by `status`."
    PRD 3.4: "a `requires_public_comment` flag that is true exactly when `item_type` is
    one of `POLICY_FIRST_READING`, `POLICY_SECOND_READING` or `WAIVER_DECISION` and false
    for the other two."

    Design: Corner/endpoints/agenda_items_list_filters_by_waiver_request_id
    """
    committee = charter_committee()
    policy = register_policy("BP-6155", "Homework and Grading", "INSTRUCTION", "RECOMMENDED", "6000.55")
    waiver = file_waiver(policy["id"], committee["id"])
    meeting = schedule_meeting()
    waiver_item = add_agenda_item(
        meeting["id"],
        meeting["version"],
        item_type="WAIVER_DECISION",
        title="Waiver HS-01",
        waiver_request_id=waiver["id"],
    )
    consent_item = add_agenda_item(
        meeting["id"], waiver_item["meeting_version_after"], "CONSENT", "Approve warrants"
    )

    rows, meta = validate_paginated(
        api_client.list_agenda_items(PUBLIC, {"waiver_request_id": waiver["id"]})
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == waiver_item["id"]

    _all_rows, all_meta = validate_paginated(
        api_client.list_agenda_items(PUBLIC, {"meeting_id": meeting["id"]})
    )
    assert all_meta["total_count"] == 2

    assert read_agenda_item(waiver_item["id"])["requires_public_comment"] is True
    consent_row = read_agenda_item(consent_item["id"])
    assert consent_row["requires_public_comment"] is False
    assert consent_row["waiver_request_id"] is None


def test_meeting_may_not_be_opened_before_its_scheduled_start():
    """PRD 3.6: "The meeting may not be opened before its own start time — the logical
    clock must have reached or passed `scheduled_start_utc`, and an early attempt is
    refused with `ERR_MEETING_NOT_YET_DUE`."

    Design: Corner/validations/opening_a_meeting_before_its_scheduled_start_returns_not_yet_due
    """
    members = seat_board(3)
    meeting = schedule_meeting()
    post_notice(meeting["id"])

    from test_helpers import make_board_president_headers

    response = api_client.open_meeting(
        meeting["id"],
        {"attending_member_ids": [m["id"] for m in members]},
        make_board_president_headers(members[0]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_MEETING_NOT_YET_DUE.value)
    assert response.status_code == 422

    row = read_meeting(meeting["id"])
    assert row["status"] == "NOTICED"
    assert row["opened_at"] is None
    assert row["seated_member_count_snapshot"] == 0


def test_opening_a_meeting_with_too_thin_a_room_is_refused():
    """PRD 3.4: "The derived `quorum_required` is a bare majority of the board: before the
    meeting opens it is half the current count of `SEATED` trustees with the remainder
    discarded, plus one; once opened it is computed the same way from the frozen
    `seated_member_count_snapshot`."
    PRD 3.6: "The number of attendees must be at least `quorum_required`, and a thinner
    room is refused with `ERR_QUORUM_NOT_MET`."

    Design: Corner/validations/opening_a_meeting_below_quorum_returns_quorum_not_met
    """
    members = seat_board(3)
    meeting = schedule_meeting()
    post_notice(meeting["id"])
    set_clock("2026-09-10T18:00:00Z")

    from test_helpers import make_board_president_headers

    response = api_client.open_meeting(
        meeting["id"],
        {"attending_member_ids": [members[0]["id"]]},
        make_board_president_headers(members[0]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_QUORUM_NOT_MET.value)
    assert response.status_code == 422

    row = read_meeting(meeting["id"])
    assert row["status"] == "NOTICED"
    assert row["quorum_required"] == 2


def test_minutes_may_not_be_drafted_before_the_gavel_falls():
    """PRD 3.7: "The clerk supplies an `action`: `DRAFT` moves `NOT_DRAFTED → DRAFTED` and
    is permitted only once the meeting's `status` is `ADJOURNED`; `APPROVE` moves
    `DRAFTED → APPROVED` and additionally requires an `approving_meeting_id` in the
    payload, which must be supplied exactly when the action is `APPROVE`."
    PRD 3.7: "A `DRAFT` action on minutes that are not `NOT_DRAFTED`, an `APPROVE` action
    on minutes that are not `DRAFTED`, and a `DRAFT` action on a meeting that has not
    adjourned are all refused with `ERR_INVALID_MINUTES_STATE`."

    Design: Corner/validations/drafting_minutes_before_adjournment_returns_invalid_minutes_state
    """
    members = seat_board(3)
    meeting = schedule_meeting()
    post_notice(meeting["id"])
    set_clock("2026-09-10T18:00:00Z")
    open_meeting(meeting["id"], [m["id"] for m in members], members[0]["id"])

    response = api_client.advance_minutes(meeting["id"], {"action": "DRAFT"}, CLERK)
    validate_error(response, ApiErrorId.ERR_INVALID_MINUTES_STATE.value)
    assert response.status_code == 409

    row = read_meeting(meeting["id"])
    assert row["minutes_status"] == "NOT_DRAFTED"
    assert row["status"] == "OPEN"


def test_minutes_cannot_be_approved_at_an_earlier_meeting():
    """PRD 3.7: "Minutes may only be approved at a genuinely later meeting. The meeting
    named by `approving_meeting_id` must currently be `OPEN`, must not be the meeting whose
    minutes are being approved, and must have a `scheduled_start_utc` strictly after that
    of the meeting whose minutes are on the table. Naming the same meeting, or one that is
    not scheduled strictly later, is refused with `ERR_INVALID_APPROVING_MEETING`."

    Design: Corner/validations/approving_minutes_at_an_earlier_meeting_returns_invalid_approving_meeting
    """
    members = seat_board(3)
    ids = [m["id"] for m in members]
    early = schedule_meeting(
        title="September Regular Meeting", scheduled_start_utc="2026-09-10T18:00:00Z"
    )
    late = schedule_meeting(
        title="Late September Regular Meeting", scheduled_start_utc="2026-09-24T18:00:00Z"
    )
    post_notice(early["id"])
    post_notice(late["id"])
    set_clock("2026-09-10T18:00:00Z")
    open_meeting(early["id"], ids, ids[0])
    set_clock("2026-09-24T18:00:00Z")
    open_meeting(late["id"], ids, ids[0])
    adjourn_meeting(late["id"])
    draft_minutes(late["id"])

    response = api_client.advance_minutes(
        late["id"], {"action": "APPROVE", "approving_meeting_id": early["id"]}, CLERK
    )
    validate_error(response, ApiErrorId.ERR_INVALID_APPROVING_MEETING.value)
    assert response.status_code == 422

    row = read_meeting(late["id"])
    assert row["minutes_status"] == "DRAFTED"
    assert row["minutes_approved_at_meeting_id"] is None
    assert read_meeting(early["id"])["status"] == "OPEN"


def test_minutes_axis_reaches_approved_while_the_conduct_axis_sits_at_adjourned():
    """PRD 3.7: "**The minutes axis.** A meeting's `minutes_status` is a second,
    independent state axis that advances on its own trigger. It only starts moving after
    the conduct axis has reached its terminal state."
    PRD 3.7: "On approval the meeting records `minutes_approved_at_meeting_id` — a
    self-reference from one meeting to another — and, in doing so, unblocks any second
    reading whose version records that meeting in `first_reading_meeting_id`."

    Design: Difficulty/non_linear_state_machine/meeting_status_and_minutes_axes_advance_independently
    """
    members = seat_board(3)
    ids = [m["id"] for m in members]
    first = schedule_meeting(
        title="September Regular Meeting", scheduled_start_utc="2026-09-10T18:00:00Z"
    )
    second = schedule_meeting(
        title="Late September Regular Meeting", scheduled_start_utc="2026-09-24T18:00:00Z"
    )
    post_notice(first["id"])
    post_notice(second["id"])
    set_clock("2026-09-10T18:00:00Z")
    open_meeting(first["id"], ids, ids[0])
    adjourn_meeting(first["id"])

    drafted = draft_minutes(first["id"])
    assert drafted["minutes_status"] == "DRAFTED"

    set_clock("2026-09-24T18:00:00Z")
    open_meeting(second["id"], ids, ids[0])
    approve_minutes(first["id"], second["id"])

    row = read_meeting(first["id"])
    assert row["status"] == "ADJOURNED"
    assert row["minutes_status"] == "APPROVED"
    assert row["minutes_approved_at_meeting_id"] == second["id"]
    assert_instant_equals(row["adjourned_at"], "2026-09-10T18:00:00Z", "Meeting.adjourned_at")


def test_the_approving_meeting_keeps_its_own_axes_untouched():
    """PRD 3.4: "A newly scheduled meeting opens with `status` `DRAFT` and `minutes_status`
    `NOT_DRAFTED` — two independent axes on the same record — and with `notice_posted_at`,
    `agenda_locked_at`, `opened_at`, `adjourned_at`, `minutes_approved_at_meeting_id` and
    `public_comment_allocation_variant` all null, `seated_member_count_snapshot` 0, and
    `attending_member_ids` an empty array."
    PRD 3.7: "Minutes may only be approved at a genuinely later meeting. The meeting named
    by `approving_meeting_id` must currently be `OPEN`, must not be the meeting whose
    minutes are being approved, and must have a `scheduled_start_utc` strictly after that
    of the meeting whose minutes are on the table."

    Design: Difficulty/non_linear_state_machine/meeting_status_and_minutes_axes_advance_independently
    """
    members = seat_board(3)
    ids = [m["id"] for m in members]
    first = schedule_meeting(
        title="September Regular Meeting", scheduled_start_utc="2026-09-10T18:00:00Z"
    )
    second = schedule_meeting(
        title="Late September Regular Meeting", scheduled_start_utc="2026-09-24T18:00:00Z"
    )
    post_notice(first["id"])
    post_notice(second["id"])
    set_clock("2026-09-10T18:00:00Z")
    open_meeting(first["id"], ids, ids[0])
    adjourn_meeting(first["id"])
    draft_minutes(first["id"])
    set_clock("2026-09-24T18:00:00Z")
    open_meeting(second["id"], ids, ids[0])
    approve_minutes(first["id"], second["id"])

    row = read_meeting(second["id"])
    assert row["status"] == "OPEN"
    assert row["minutes_status"] == "NOT_DRAFTED"
    assert row["minutes_approved_at_meeting_id"] is None
