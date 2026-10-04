"""Resource lifecycles: creation defaults, listing, terminal states and the
guards that keep a resource in place."""
from test_helpers import (
    TEST_USERS,
    api_client,
    approve_application,
    approve_application_raw,
    create_application,
    create_event_application_payload,
    current_store_version,
    get_application,
    get_case,
    get_judge,
    get_set_release,
    make_store_organizer_headers,
    set_clock,
    setup_judge_with_case,
    setup_release_context,
    transition_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_a_newly_enrolled_store_comes_back_with_its_system_defaults(api):
    """PRD §3.1: "The store enters the program `ACTIVE` and `STANDARD`."
    PRD §2.8: "**`version`** is a system-managed integer that starts at the
    resource's creation value and increments by one on every modification"
    PRD §2.7: "Enrollment initializes the store's `status` to `ACTIVE` and its
    `reporting_tier` to `STANDARD`."

    Design: Corner/entities/store_creation_applies_system_defaults_and_mints_identity
    """
    set_clock("2026-09-01T00:00:00Z")

    created = validate_success(api_client.create_store(
        {
            "name": "Portland Play Lab",
            "region_code": "US-NORTH",
            "daily_event_capacity": 4,
            "event_space_capacity": 6,
        },
        TEST_USERS["ops_admin_headers"],
    ), 201)

    assert created["status"] == "ACTIVE"
    assert created["reporting_tier"] == "STANDARD"
    assert created["tp_balance"] == 0
    assert created["reporting_violation_points"] == 0
    assert created["version"] == 1
    assert created["name"] == "Portland Play Lab"
    assert created["region_code"] == "US-NORTH"

    body = api_client.create_store(
        {"name": "Dup Probe", "region_code": "US-NORTH",
         "daily_event_capacity": 1, "event_space_capacity": 1},
        TEST_USERS["ops_admin_headers"],
    )
    assert "api_request_id" in body.json()["meta"]
    assert "api_request_timestamp" in body.json()["meta"]


def test_a_set_release_round_trips_unchanged_through_the_collection_read(api):
    """PRD §3.7: "A set release is announced by an `OpsAdmin` supplying a globally
    unique `set_code`, the bounds of its prerelease weekend as
    `prerelease_start_date` and `prerelease_end_date`, and its `street_date`. The
    release enters `ANNOUNCED`."

    Design: Corner/entities/set_release_round_trips_through_the_collection_read
    """
    set_clock("2026-09-01T00:00:00Z")
    created = validate_success(api_client.create_set_release(
        {
            "set_code": "RT1",
            "prerelease_start_date": "2026-09-11T00:00:00Z",
            "prerelease_end_date": "2026-09-13T23:59:59Z",
            "street_date": "2026-09-18T00:00:00Z",
        },
        TEST_USERS["ops_admin_headers"],
    ), 201)

    data, meta = validate_paginated(api_client.list_set_releases(
        TEST_USERS["judge_headers"], params={"limit": 10, "offset": 0}
    ))
    rows = [row for row in data if row["id"] == created["id"]]
    assert len(rows) == 1

    row = rows[0]
    assert row["set_code"] == "RT1"
    assert row["prerelease_end_date"] == "2026-09-13T23:59:59Z"
    assert row["street_date"] == "2026-09-18T00:00:00Z"
    assert row["status"] == "ANNOUNCED"
    assert meta["total_count"] >= 1


def test_reading_an_absent_resource_returns_a_not_found_error_envelope(api):
    """PRD §2.2: "The `error_id` is a unique, machine-readable string that
    identifies the specific error."
    PRD §2.11: "Reads that reach a sub-resource through its parent follow the same
    discipline: the parent named in the path is resolved and checked before the
    sub-resource is considered, so a request that would be rejected on the parent
    is never evaluated at the child."

    Design: Corner/entities/store_get_on_unknown_id_returns_not_found
    """
    set_clock("2026-09-01T00:00:00Z")

    response = api_client.get_event_application(
        "11111111-2222-4333-8444-555555555555", TEST_USERS["judge_headers"]
    )
    error = validate_error(response, "ERR_NOT_FOUND", expected_status=404)
    assert response.json()["response_type"] == "error"
    assert error["message"].strip()


def test_submitting_an_application_without_its_format_code_is_a_shape_failure(api):
    """PRD §2.12: "Only then is the request's own shape examined — every required
    body field present, no undeclared body field supplied, every value conforming
    to its declared type and enumerated domain — with any violation rejected as
    `ERR_INVALID_REQUEST`."

    Design: Corner/entities/event_application_creation_missing_required_field_rejected
    """
    store, set_release, fmt = setup_release_context()

    payload = create_event_application_payload(
        store["id"], set_release["id"], fmt["id"],
        tier="LOCAL", scheduled_date="2026-09-26T18:00:00Z", expected_headcount=12,
    )
    payload.pop("format_code")

    refused = api_client.create_event_application(
        payload, make_store_organizer_headers(store["id"])
    )
    validate_error(refused, "ERR_INVALID_REQUEST", expected_status=400)

    data, meta = validate_paginated(api_client.list_event_applications(
        TEST_USERS["ops_admin_headers"], params={"store_id": store["id"], "limit": 10}
    ))
    assert meta["total_count"] == 0, "no row is created by the refused submission"


def test_the_filtered_application_listing_reports_pagination_metadata(api):
    """PRD §2.3: "`total_count` reports the size of the full filtered result set,
    not the size of the page, and `has_more` reports whether any rows remain
    beyond the current page."

    Design: Corner/entities/event_application_listing_reports_pagination_metadata
    """
    store, set_release, fmt = setup_release_context()
    for offset, day in enumerate(["26", "27", "28"]):
        create_application(
            store, set_release, fmt, tier="LOCAL",
            scheduled_date=f"2026-09-{day}T18:00:00Z", expected_headcount=12,
        )

    data, meta = validate_paginated(api_client.list_event_applications(
        TEST_USERS["judge_headers"],
        params={"store_id": store["id"], "limit": 2, "offset": 0},
    ))
    assert len(data) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert meta["limit"] == 2
    assert meta["offset"] == 0
    assert all(row["store_id"] == store["id"] for row in data)
    assert all(row["tier"] == "LOCAL" for row in data)


def test_a_fresh_application_starts_submitted_and_refuses_a_second_approval(api):
    """PRD §3.2: "The application enters life in `SUBMITTED` with no reporting
    obligation attached yet: `prizing_report_status` is `NOT_DUE` and
    `reporting_due_by` is null."
    PRD §3.4: "Approval is generative. It creates a prize allocation for the event
    and records that allocation's identifier on the application as
    `prize_allocation_id`"

    Design: Corner/state_machines/event_application_starts_submitted_and_rejects_double_approval
    """
    store, set_release, fmt = setup_release_context()
    application = create_application(store, set_release, fmt, tier="LOCAL")

    fresh = get_application(application["id"])
    assert fresh["status"] == "SUBMITTED"
    assert fresh["prizing_report_status"] == "NOT_DUE"
    assert fresh["reporting_due_by"] is None

    approved = approve_application(application["id"], store["id"])
    assert approved["prize_allocation_id"] is not None

    refused = approve_application_raw(
        application["id"], current_store_version(store["id"])
    )
    validate_error(refused, "ERR_INVALID_STATE", expected_status=409)
    assert get_application(application["id"])["prize_allocation_id"] == (
        approved["prize_allocation_id"]
    ), "no second pool is created"


def test_a_denied_application_cannot_be_walked_forward_to_approval(api):
    """PRD §3.3: "A `StoreOrganizer` may give up on a submitted application by
    denying it, which leaves the application in `DENIED` and creates no
    allocation at all."

    Design: Corner/state_machines/denied_application_is_terminal_against_later_approval
    """
    store, set_release, fmt = setup_release_context()
    application = create_application(
        store, set_release, fmt, tier="QUALIFIER", expected_headcount=30
    )
    refused_deny = api_client.transition_event_application(
        application["id"], transition_payload("DENY"),
        TEST_USERS["ops_admin_headers"],
    )
    validate_success(refused_deny, 200)
    assert get_application(application["id"])["status"] == "DENIED"

    refused = approve_application_raw(
        application["id"], current_store_version(store["id"])
    )
    validate_error(refused, "ERR_INVALID_STATE", expected_status=409)

    row = get_application(application["id"])
    assert row["status"] == "DENIED"
    assert row["prize_allocation_id"] is None

    data, meta = validate_paginated(api_client.list_prize_allocations(
        TEST_USERS["ops_admin_headers"],
        params={"event_application_id": application["id"], "limit": 10},
    ))
    assert meta["total_count"] == 0


def test_a_prerelease_set_cannot_be_retired_before_it_reaches_the_street(api):
    """PRD §3.7: "The final step is retirement, run by an `OpsAdmin` once the set
    has been on the street. A release may be retired only from `RELEASED`"

    Design: Corner/state_machines/set_release_cannot_move_from_prerelease_straight_to_retired
    """
    set_clock("2026-09-01T00:00:00Z")
    created = validate_success(api_client.create_set_release(
        {
            "set_code": "RT7",
            "prerelease_start_date": "2026-09-11T00:00:00Z",
            "prerelease_end_date": "2026-09-13T23:59:59Z",
            "street_date": "2026-09-18T00:00:00Z",
        },
        TEST_USERS["ops_admin_headers"],
    ), 201)

    set_clock("2026-09-12T12:00:00Z")
    assert get_set_release(created["id"])["status"] == "PRERELEASE"

    refused = api_client.transition_set_release(
        created["id"], transition_payload("RETIRE"), TEST_USERS["ops_admin_headers"]
    )
    validate_error(refused, "ERR_INVALID_STATE", expected_status=409)
    assert get_set_release(created["id"])["status"] == "PRERELEASE"

    set_clock("2026-09-18T00:00:00Z")
    accepted = api_client.transition_set_release(
        created["id"], transition_payload("RETIRE"), TEST_USERS["ops_admin_headers"]
    )
    validate_success(accepted, 200)
    assert get_set_release(created["id"])["status"] == "RETIRED"


def test_a_judge_can_only_be_decertified_once_a_case_against_them_is_escalated(api):
    """PRD §3.10: "A judge may be decertified, moving the certification from
    `ACTIVE` to `DECERTIFIED`, and decertification is not an operator's free
    choice: it is permitted only when the judge is the subject of an enforcement
    case that has been escalated."

    Design: Corner/state_machines/judge_decertification_requires_an_escalated_case
    """
    store, _set_release, _fmt, application, judge, case = setup_judge_with_case(
        judge_ref="JUDGE-ALPHA", offense_class="SEVERE",
        rules_enforcement_level="PROFESSIONAL",
    )

    early = api_client.transition_judge(
        judge["judge_ref"], transition_payload("DECERTIFY"),
        TEST_USERS["ops_admin_headers"],
    )
    validate_error(early, "ERR_INVALID_STATE", expected_status=409)

    assert get_judge(judge["judge_ref"])["status"] == "ACTIVE"

    api_client.transition_enforcement_case(
        case["id"], transition_payload("ESCALATE"), TEST_USERS["ops_admin_headers"]
    ).raise_for_status()
    assert get_case(case["id"])["status"] == "ESCALATED"

    accepted = api_client.transition_judge(
        judge["judge_ref"], transition_payload("DECERTIFY"),
        TEST_USERS["ops_admin_headers"],
    )
    validate_success(accepted, 200)
    assert get_judge(judge["judge_ref"])["status"] == "DECERTIFIED"