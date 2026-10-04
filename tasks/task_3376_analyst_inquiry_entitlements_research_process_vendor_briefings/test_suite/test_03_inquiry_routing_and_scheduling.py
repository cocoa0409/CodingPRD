"""Inquiry submission, topic routing, scheduling, decline and terminal states."""
from test_helpers import (
    ApiErrorId,
    api_client,
    create_account,
    create_active_seat,
    create_analyst,
    create_routed_inquiry,
    create_scheduled_inquiry,
    create_seat,
    get_success_data,
    make_analyst_headers,
    make_client_admin_headers,
    make_seat_holder_headers,
    revoke_seat,
    schedule_inquiry,
    set_clock,
    setup_account_with_active_seat,
    validate_error,
    validate_paginated,
    validate_success,
)


def _two_analyst_roster(lead):
    """Extend the roster to exactly two CLOUD_COST analysts.

    `lead` is the analyst already created by `setup_account_with_active_seat`
    (DISTINGUISHED on CLOUD_COST).  Reusing it as the senior candidate keeps the
    routing pool at two: creating a third analyst here would leave the fixture
    with three eligible candidates, and topic routing's `created_at` tie-break
    would then hand the inquiry to the extra DISTINGUISHED analyst instead of
    `first`.
    """
    first = lead
    second = create_analyst(
        full_name="Ravi Menon", seniority="SENIOR", topic_routes=["CLOUD_COST"],
    )
    return first, second


def test_declined_inquiry_reroutes_to_the_next_ranked_analyst():
    """PRD §3.2: "The declining analyst is appended to `declined_analyst_ids` and
    thereby removed from eligibility for the rest of this inquiry's life; topic
    routing runs again over the remaining eligible analysts, and the winner becomes
    the new `analyst_id` while `routing_attempt_count` is incremented. The inquiry
    returns to `ROUTED`, `scheduled_start_utc` is cleared, the `version` is
    incremented, the account's `reserved_inquiry_units` is decremented and its
    `remaining_reserved_units` recomputed, and the load counters move: the previous
    analyst's `open_inquiry_count` is decremented and the new analyst's is
    incremented."

    Design: Difficulty/non_linear_state_machine/inquiry_decline_reroute_cycle
    """
    set_clock("2026-09-01T00:00:00Z")
    account, seat, lead = setup_account_with_active_seat(
        seat_count_contracted=10, inquiry_allowance_total=10
    )
    first, second = _two_analyst_roster(lead)

    inquiry = create_scheduled_inquiry(
        account, seat, first, "2026-09-10T15:00:00Z",
        question_summary="Which observability vendor fits our estate?",
    )
    assert inquiry["analyst_id"] == first["id"]

    rerouted = get_success_data(
        api_client.decline_inquiry(
            inquiry["id"], {"decline_reason": "Outside my practice this quarter"},
            make_analyst_headers(first["id"]),
        )
    )
    assert rerouted["status"] == "ROUTED"
    assert rerouted["analyst_id"] == second["id"]
    assert rerouted["analyst_id"] != first["id"]
    assert rerouted["routing_attempt_count"] == 2
    assert rerouted["scheduled_start_utc"] is None
    assert rerouted["declined_analyst_ids"] == [first["id"]]

    data = get_success_data(
        api_client.get_client(account["id"], make_client_admin_headers(account["id"]))
    )
    assert data["reserved_inquiry_units"] == 0
    assert data["remaining_reserved_units"] == 10


def test_decline_moves_the_load_counters_and_releases_the_reservation():
    """PRD §3.2: "the previous analyst's `open_inquiry_count` is decremented and the
    new analyst's is incremented."
    PRD §3.2: "`open_inquiry_count` — the number of inquiries assigned to that
    analyst that are in `ROUTED`, `SCHEDULED` or `IN_PREP`"
    PRD §3.2: "the account's `reserved_inquiry_units` is decremented and its
    `remaining_reserved_units` recomputed"

    Design: Difficulty/non_linear_state_machine/inquiry_decline_reroute_cycle
    """
    set_clock("2026-09-01T00:00:00Z")
    account, seat, lead = setup_account_with_active_seat(
        seat_count_contracted=10, inquiry_allowance_total=10
    )
    first, second = _two_analyst_roster(lead)
    inquiry = create_scheduled_inquiry(
        account, seat, first, "2026-09-10T15:00:00Z", question_summary="Reroute and rebook"
    )
    assert get_success_data(
        api_client.get_analyst(first["id"])
    )["open_inquiry_count"] == 1

    rerouted = get_success_data(
        api_client.decline_inquiry(
            inquiry["id"], {}, make_analyst_headers(first["id"])
        )
    )
    assert rerouted["analyst_id"] == second["id"]
    assert rerouted["routing_attempt_count"] == 2

    assert get_success_data(api_client.get_analyst(first["id"]))["open_inquiry_count"] == 0
    assert get_success_data(api_client.get_analyst(second["id"]))["open_inquiry_count"] == 1

    released = get_success_data(
        api_client.get_client(account["id"], make_client_admin_headers(account["id"]))
    )
    assert released["reserved_inquiry_units"] == 0
    assert released["remaining_reserved_units"] == 10

    rebooked = schedule_inquiry(second, inquiry, "2026-09-10T15:00:00Z")
    assert rebooked["status"] == "SCHEDULED"
    assert rebooked["analyst_id"] == second["id"]

    after = get_success_data(
        api_client.get_client(account["id"], make_client_admin_headers(account["id"]))
    )
    assert after["reserved_inquiry_units"] == 1
    assert after["remaining_reserved_units"] == 9


def test_past_slot_error_precedes_the_exhausted_allowance_error():
    """PRD §2.11: "Beyond existence, checks run in a fixed precedence. When more than
    one check would fail, the earliest one in this ordering determines the response,
    and later checks are not evaluated".
    PRD §2.11: "Time windows: a requested inquiry start instant must not be strictly
    before the clock (`ERR_INQUIRY_START_IN_PAST`, HTTP 400)".
    PRD §2.11: "Allowance: the account's reservation remainder must be at least 1
    before an inquiry may be scheduled (`ERR_INQUIRY_ALLOWANCE_EXHAUSTED`, HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/temporal_precedes_fiscal_on_inquiry_schedule
    """
    set_clock("2026-09-01T00:00:00Z")
    account = create_account(seat_count_contracted=5, inquiry_allowance_total=1)
    seat = create_active_seat(account)
    analyst = create_analyst()

    first = create_routed_inquiry(
        account, seat, requested_start_utc="2026-09-05T10:00:00Z", question_summary="First inquiry"
    )
    schedule_inquiry(analyst, first, "2026-09-05T10:00:00Z")
    second = create_routed_inquiry(
        account, seat, requested_start_utc="2026-09-06T10:00:00Z", question_summary="Second inquiry"
    )

    past = api_client.schedule_inquiry(
        second["id"], {"scheduled_start_utc": "2026-08-31T10:00:00Z"},
        make_analyst_headers(analyst["id"]),
    )
    error = validate_error(past, ApiErrorId.ERR_INQUIRY_START_IN_PAST)
    assert error["error_id"] != ApiErrorId.ERR_INQUIRY_ALLOWANCE_EXHAUSTED

    future = api_client.schedule_inquiry(
        second["id"], {"scheduled_start_utc": "2026-09-06T10:00:00Z"},
        make_analyst_headers(analyst["id"]),
    )
    validate_error(future, ApiErrorId.ERR_INQUIRY_ALLOWANCE_EXHAUSTED)

    data = get_success_data(
        api_client.get_client(account["id"], make_client_admin_headers(account["id"]))
    )
    assert data["remaining_reserved_units"] == 0
    assert get_success_data(
        api_client.get_inquiry(second["id"], make_analyst_headers(analyst["id"]))
    )["status"] == "ROUTED"


def test_past_slot_is_rejected_alone_when_the_allowance_is_still_free():
    """PRD §2.11: "Time windows: a requested inquiry start instant must not be
    strictly before the clock (`ERR_INQUIRY_START_IN_PAST`, HTTP 400)".
    PRD §2.4: "A requested inquiry start instant must not be strictly before the
    current clock reading."

    Design: Difficulty/priority_pair_validation_conflict/temporal_precedes_fiscal_on_inquiry_schedule
    """
    set_clock("2026-09-01T00:00:00Z")
    account, seat, analyst = setup_account_with_active_seat(
        seat_count_contracted=5, inquiry_allowance_total=5
    )
    create_scheduled_inquiry(
        account, seat, analyst, "2026-09-05T10:00:00Z", question_summary="Occupies one unit"
    )
    inquiry = create_routed_inquiry(
        account, seat, requested_start_utc="2026-09-06T10:00:00Z", question_summary="Still has units"
    )

    past = api_client.schedule_inquiry(
        inquiry["id"], {"scheduled_start_utc": "2026-08-31T10:00:00Z"},
        make_analyst_headers(analyst["id"]),
    )
    validate_error(past, ApiErrorId.ERR_INQUIRY_START_IN_PAST)

    accepted = schedule_inquiry(analyst, inquiry, "2026-09-06T10:00:00Z")
    assert accepted["status"] == "SCHEDULED"


def test_inquiry_submission_is_blocked_until_the_seat_is_activated():
    """PRD §3.1: "The seat's status is the gate for the account's inquiry capability:
    an inquiry may only be submitted from a seat that is `ACTIVE`, on an account
    whose contract is `ACTIVE`."
    PRD §2.11: "Referenced entity state: the seat must be `ACTIVE` and its account
    `ACTIVE` before an inquiry may be submitted (`ERR_SEAT_NOT_ACTIVE`, HTTP 409)".

    Design: Difficulty/cross_entity_state_dependency/inquiry_submission_requires_an_active_seat
    """
    set_clock("2026-09-01T00:00:00Z")
    account = create_account(seat_count_contracted=10, inquiry_allowance_total=10)
    analyst = create_analyst()
    seat = create_seat(account, seat_email="nina@acme.example")

    blocked = api_client.create_inquiry(
        {
            "seat_id": seat["id"],
            "topic_route": "CLOUD_COST",
            "question_summary": "Blocked while provisioned",
            "requested_start_utc": "2026-09-20T10:00:00Z",
            "duration_minutes": 45,
            "preparation_notes": "Brief attached.",
        },
        make_seat_holder_headers(seat["id"]),
    )
    validate_error(blocked, ApiErrorId.ERR_SEAT_NOT_ACTIVE)

    activated = get_success_data(
        api_client.activate_seat(seat["id"], make_client_admin_headers(account["id"]))
    )
    assert activated["status"] == "ACTIVE"

    inquiry = create_routed_inquiry(
        account, seat, requested_start_utc="2026-09-20T10:00:00Z",
        question_summary="Accepted after activation",
    )
    assert inquiry["status"] == "ROUTED"
    assert inquiry["analyst_id"] == analyst["id"]


def test_inquiry_submission_is_blocked_when_the_contract_left_active():
    """PRD §3.1: "an inquiry may only be submitted from a seat that is `ACTIVE`, on
    an account whose contract is `ACTIVE`."
    PRD §2.11: "Referenced entity state: the seat must be `ACTIVE` and its account
    `ACTIVE` before an inquiry may be submitted (`ERR_SEAT_NOT_ACTIVE`, HTTP 409)".

    Design: Difficulty/cross_entity_state_dependency/inquiry_submission_requires_an_active_seat
    """
    set_clock("2026-09-01T00:00:00Z")
    account = create_account(seat_count_contracted=4, inquiry_allowance_total=4)
    analyst = create_analyst()
    assert get_success_data(api_client.get_analyst(analyst["id"]))["status"] == "ACTIVE", (
        "An eligible analyst exists, so the account state is the only blocker"
    )
    doomed = create_active_seat(account, seat_email="doomed@acme.example")
    survivor = create_active_seat(account, seat_email="survivor@acme.example")

    revoke_seat(account, doomed)
    account_data = get_success_data(
        api_client.get_client(account["id"], make_client_admin_headers(account["id"]))
    )
    assert account_data["contract_status"] == "RENEWAL_REVIEW"
    assert account_data["active_seat_count"] == 1

    resp = api_client.create_inquiry(
        {
            "seat_id": survivor["id"],
            "topic_route": "CLOUD_COST",
            "question_summary": "Account no longer active",
            "requested_start_utc": "2026-09-20T10:00:00Z",
            "duration_minutes": 45,
            "preparation_notes": "Brief attached.",
        },
        make_seat_holder_headers(survivor["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_SEAT_NOT_ACTIVE)


def test_adjacent_inquiry_window_is_accepted_and_an_inside_start_is_refused():
    """PRD §3.2: "the half-open window from the supplied start for the inquiry's
    `duration_minutes` must not overlap any other inquiry of the same analyst that is
    `SCHEDULED` or `IN_PREP`, or the request fails with `ERR_INQUIRY_SLOT_OVERLAP`
    (HTTP 409)".

    Design: Difficulty/resource_temporal_overlap/analyst_inquiry_calendar_pairwise_half_open_overlap
    """
    set_clock("2026-09-01T00:00:00Z")
    account, seat, analyst = setup_account_with_active_seat(
        seat_count_contracted=10, inquiry_allowance_total=10
    )
    create_scheduled_inquiry(
        account, seat, analyst, "2026-09-08T10:00:00Z", question_summary="Window one",
        duration_minutes=45,
    )
    adjacent = create_routed_inquiry(
        account, seat, requested_start_utc="2026-09-08T10:45:00Z",
        question_summary="Window two", duration_minutes=45,
    )
    inside = create_routed_inquiry(
        account, seat, requested_start_utc="2026-09-08T10:30:00Z",
        question_summary="Window three", duration_minutes=45,
    )

    booked = schedule_inquiry(analyst, adjacent, "2026-09-08T10:45:00Z")
    assert booked["status"] == "SCHEDULED"

    resp = api_client.schedule_inquiry(
        inside["id"], {"scheduled_start_utc": "2026-09-08T10:30:00Z"},
        make_analyst_headers(analyst["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INQUIRY_SLOT_OVERLAP)

    rejected = get_success_data(
        api_client.get_inquiry(inside["id"], make_analyst_headers(analyst["id"]))
    )
    assert rejected["status"] == "ROUTED"
    assert rejected["scheduled_start_utc"] is None

    data = get_success_data(
        api_client.get_client(account["id"], make_client_admin_headers(account["id"]))
    )
    assert data["reserved_inquiry_units"] == 2


def test_window_ending_exactly_at_an_existing_start_is_accepted():
    """PRD §3.2: "the half-open window from the supplied start for the inquiry's
    `duration_minutes` must not overlap any other inquiry of the same analyst that is
    `SCHEDULED` or `IN_PREP`, or the request fails with `ERR_INQUIRY_SLOT_OVERLAP`
    (HTTP 409)".

    Design: Difficulty/resource_temporal_overlap/analyst_inquiry_calendar_pairwise_half_open_overlap
    """
    set_clock("2026-09-01T00:00:00Z")
    account, seat, analyst = setup_account_with_active_seat(
        seat_count_contracted=10, inquiry_allowance_total=10
    )
    create_scheduled_inquiry(
        account, seat, analyst, "2026-09-08T10:00:00Z", question_summary="Anchor window",
        duration_minutes=45,
    )
    before = create_routed_inquiry(
        account, seat, requested_start_utc="2026-09-08T09:15:00Z",
        question_summary="Ends exactly at the anchor start", duration_minutes=45,
    )
    overlapping = create_routed_inquiry(
        account, seat, requested_start_utc="2026-09-08T09:30:00Z",
        question_summary="Crosses into the anchor window", duration_minutes=45,
    )

    accepted = schedule_inquiry(analyst, before, "2026-09-08T09:15:00Z")
    assert accepted["status"] == "SCHEDULED", (
        "A window ending exactly at the next window's start does not overlap it"
    )

    resp = api_client.schedule_inquiry(
        overlapping["id"], {"scheduled_start_utc": "2026-09-08T09:30:00Z"},
        make_analyst_headers(analyst["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INQUIRY_SLOT_OVERLAP)


def test_inquiry_created_without_duration_minutes_is_rejected():
    """PRD §2.11: "Request shape: every required input field is present, enum members
    are in range, and integers satisfy their declared bounds — including the
    requirement that evaluation weights sum to exactly 1.00. Failure is
    `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD §3.2: "A `SeatHolder` submits an inquiry by supplying the `seat_id` that will
    spend the allowance unit, the `topic_route` the question belongs to, a
    `question_summary`, the `requested_start_utc`, and a `duration_minutes` of 30, 45
    or 60 minutes."

    Design: Corner/entities/inquiry_create_missing_duration_returns_invalid_request
    """
    set_clock("2026-09-01T00:00:00Z")
    account, seat, _ = setup_account_with_active_seat()

    resp = api_client.create_inquiry(
        {
            "seat_id": seat["id"],
            "topic_route": "CLOUD_COST",
            "question_summary": "Missing duration",
            "requested_start_utc": "2026-09-20T10:00:00Z",
            "preparation_notes": "Brief attached.",
        },
        make_seat_holder_headers(seat["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    rows, meta = validate_paginated(
        api_client.list_inquiries(
            make_seat_holder_headers(seat["id"]), params={"seat_id": seat["id"]}
        )
    )
    assert rows == []
    assert meta["total_count"] == 0


def test_client_supplied_status_and_units_are_ignored_on_inquiry_creation():
    """PRD §3.2: "The new inquiry begins in `SUBMITTED`, with `analyst_id` unset,
    `scheduled_start_utc` null, `settled_at` null, `units_consumed` 0,
    `note_delivered` false, `note_reference` an empty string, `declined_analyst_ids`
    empty, and `routing_attempt_count` 0."
    PRD §3.2: "Otherwise the winner's `id` becomes the inquiry's `analyst_id`,
    `routing_attempt_count` is set to 1, the inquiry moves to `ROUTED` with its
    `version` incremented".

    Design: Corner/entities/inquiry_create_extra_field_status_and_units_is_ignored_input
    """
    set_clock("2026-09-01T00:00:00Z")
    account, seat, analyst = setup_account_with_active_seat()

    resp = api_client.create_inquiry(
        {
            "seat_id": seat["id"],
            "topic_route": "CLOUD_COST",
            "question_summary": "Ignore my status",
            "requested_start_utc": "2026-09-20T10:00:00Z",
            "duration_minutes": 45,
            "preparation_notes": "Brief.",
            "status": "COMPLETED",
            "units_consumed": 1,
        },
        make_seat_holder_headers(seat["id"]),
    )
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "ROUTED"
    assert data["units_consumed"] == 0
    assert data["analyst_id"] == analyst["id"]
    assert data["routing_attempt_count"] == 1

    account_data = get_success_data(
        api_client.get_client(account["id"], make_client_admin_headers(account["id"]))
    )
    assert account_data["consumed_inquiry_units"] == 0
    assert account_data["reserved_inquiry_units"] == 0


def test_inquiry_list_composes_the_seat_and_status_filters():
    """PRD §2.3: "`total_count` is the number of resources matching the request's
    filters across all pages, and `has_more` is true when further items remain beyond
    the returned page."
    PRD §2.3: "The `limit` parameter sets the maximum number of items returned in one
    page; it defaults to 10, must be at least 1, and must be at most 100. The
    `offset` parameter sets the number of items skipped before the first returned
    item and defaults to 0."

    Design: Corner/entities/inquiry_list_filters_by_seat_and_status
    """
    set_clock("2026-09-01T00:00:00Z")
    account, seat, analyst = setup_account_with_active_seat()
    create_routed_inquiry(
        account, seat, requested_start_utc="2026-09-20T10:00:00Z", question_summary="Listing one"
    )
    second = create_routed_inquiry(
        account, seat, requested_start_utc="2026-09-21T10:00:00Z", question_summary="Listing two"
    )
    schedule_inquiry(analyst, second, "2026-09-21T10:00:00Z")

    headers = make_seat_holder_headers(seat["id"])
    filtered, filtered_meta = validate_paginated(
        api_client.list_inquiries(headers, params={"seat_id": seat["id"], "status": "SCHEDULED"})
    )
    assert len(filtered) == 1
    assert filtered[0]["id"] == second["id"]
    assert filtered_meta["total_count"] == 1
    assert filtered_meta["has_more"] is False
    assert filtered_meta["limit"] == 10
    assert filtered_meta["offset"] == 0

    everything, all_meta = validate_paginated(
        api_client.list_inquiries(headers, params={"seat_id": seat["id"]})
    )
    assert len(everything) == 2
    assert all_meta["total_count"] == 2
    assert all_meta["has_more"] is False


def test_completed_inquiry_is_terminal_for_schedule_and_cancel():
    """PRD §3.3: "`COMPLETED`, `NO_SHOW` and `CANCELLED` are terminal: any further
    transition attempted on such an inquiry is rejected with `ERR_INVALID_STATE`
    (HTTP 409)."

    Design: Corner/state_machines/inquiry_terminal_state_rejects_further_transitions
    """
    set_clock("2026-09-01T00:00:00Z")
    account, seat, analyst = setup_account_with_active_seat()
    inquiry = create_scheduled_inquiry(
        account, seat, analyst, "2026-09-02T10:00:00Z", question_summary="Terminal lockdown"
    )
    set_clock("2026-09-02T12:00:00Z")
    settled = get_success_data(
        api_client.complete_inquiry(
            inquiry["id"],
            {"outcome": "COMPLETED", "note_delivered": True, "note_reference": "NOTE-1"},
            make_analyst_headers(analyst["id"]),
        )
    )
    assert settled["status"] == "COMPLETED"
    assert settled["units_consumed"] == 1

    reschedule = api_client.schedule_inquiry(
        inquiry["id"], {"scheduled_start_utc": "2026-09-09T10:00:00Z"},
        make_analyst_headers(analyst["id"]),
    )
    validate_error(reschedule, ApiErrorId.ERR_INVALID_STATE)

    cancel = api_client.cancel_inquiry(
        inquiry["id"], {"cancel_reason": "Too late"}, make_seat_holder_headers(seat["id"])
    )
    validate_error(cancel, ApiErrorId.ERR_INVALID_STATE)

    account_data = get_success_data(
        api_client.get_client(account["id"], make_client_admin_headers(account["id"]))
    )
    assert account_data["consumed_inquiry_units"] == 1
    assert account_data["reserved_inquiry_units"] == 0


def test_inquiry_submission_without_auth_headers_is_unauthenticated():
    """PRD §2.1: "A request that omits either header is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD §2.11: "Authentication: both `X-User-ID` and `X-User-Role` are present,
    except on the clock operation. Failure is `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/inquiry_create_missing_auth_headers_returns_unauthenticated
    """
    set_clock("2026-09-01T00:00:00Z")
    resp = api_client.create_inquiry({}, {})
    error = validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
    assert error["error_id"] == "ERR_UNAUTHENTICATED"


def test_fourth_inquiry_on_the_same_utc_day_is_refused():
    """PRD §3.2: "the analyst must hold fewer than 3 inquiries whose
    `scheduled_start_utc` falls on the same UTC calendar day as the requested slot,
    or the request fails with `ERR_ANALYST_DAILY_INQUIRY_CAP` (HTTP 409)".

    Design: Corner/validations/analyst_daily_inquiry_cap_blocks_the_fourth_booking
    """
    set_clock("2026-09-01T00:00:00Z")
    account, seat, analyst = setup_account_with_active_seat(
        seat_count_contracted=10, inquiry_allowance_total=10
    )
    starts = ["2026-09-08T10:00:00Z", "2026-09-08T11:00:00Z",
              "2026-09-08T12:00:00Z", "2026-09-08T13:00:00Z"]
    inquiries = []
    for index, start in enumerate(starts):
        inquiries.append(create_routed_inquiry(
            account, seat, requested_start_utc=start,
            question_summary=f"Slot {index + 1}", duration_minutes=30,
        ))
    for inquiry, start in zip(inquiries[:3], starts[:3]):
        schedule_inquiry(analyst, inquiry, start)

    resp = api_client.schedule_inquiry(
        inquiries[3]["id"], {"scheduled_start_utc": starts[3]},
        make_analyst_headers(analyst["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ANALYST_DAILY_INQUIRY_CAP)

    rejected = get_success_data(
        api_client.get_inquiry(inquiries[3]["id"], make_analyst_headers(analyst["id"]))
    )
    assert rejected["status"] == "ROUTED"
    assert rejected["scheduled_start_utc"] is None

    data = get_success_data(
        api_client.get_client(account["id"], make_client_admin_headers(account["id"]))
    )
    assert data["reserved_inquiry_units"] == 3


def test_inquiry_on_a_topic_no_analyst_covers_is_not_eligible():
    """PRD §3.2: "If the eligible pool is empty, the submission is rejected with
    `ERR_ANALYST_NOT_ELIGIBLE` (HTTP 409) and no inquiry row is created."

    Design: Corner/errors/inquiry_on_an_uncovered_topic_returns_analyst_not_eligible
    """
    set_clock("2026-09-01T00:00:00Z")
    account, seat, _ = setup_account_with_active_seat()
    headers = make_seat_holder_headers(seat["id"])

    resp = api_client.create_inquiry(
        {
            "seat_id": seat["id"],
            "topic_route": "SECURITY_OPS",
            "question_summary": "Nobody covers this",
            "requested_start_utc": "2026-09-20T10:00:00Z",
            "duration_minutes": 45,
            "preparation_notes": "Brief.",
        },
        headers,
    )
    validate_error(resp, ApiErrorId.ERR_ANALYST_NOT_ELIGIBLE)

    rows, _ = validate_paginated(
        api_client.list_inquiries(headers, params={"seat_id": seat["id"]})
    )
    assert rows == []

    data = get_success_data(
        api_client.get_client(account["id"], make_client_admin_headers(account["id"]))
    )
    assert data["reserved_inquiry_units"] == 0
    assert data["consumed_inquiry_units"] == 0
