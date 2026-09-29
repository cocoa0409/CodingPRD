"""Entity-shape breadth: creation defaults, server-owned fields, listing windows and foreign keys."""

from test_helpers import (
    COORDINATOR_HEADERS,
    ERR_EVENT_NOT_FOUND,
    ERR_GUEST_ISSUE_NOT_FOUND,
    ERR_INVALID_TIME_WINDOW,
    ERR_POSITION_TYPE_NOT_FOUND,
    ERR_STAFF_MEMBER_NOT_FOUND,
    ERR_VALIDATION_FAILED,
    SUPERVISOR_HEADERS,
    SUPERVISOR_USER_ID,
    assert_absent,
    assert_average,
    assert_cents,
    assert_common_fields,
    assert_fields,
    assert_instant,
    assert_ratio,
    create_event,
    create_member,
    create_plan,
    create_resource,
    create_satisfaction_response,
    create_slot,
    create_ticket_taker,
    create_usher,
    created,
    err,
    ok,
    page,
    read_event,
    read_plan,
    read_resource,
    set_clock,
)
from test_helpers.factories import (
    accessibility_request_payload,
    accessibility_resource_payload,
    certification_payload,
    guest_issue_payload,
    omit,
    position_slot_payload,
    satisfaction_response_payload,
    staffing_plan_payload,
    usher_payload,
    with_fields,
)

MISSING_UUID = "00000000-0000-0000-0000-0000000000ff"


def _unset(entity, *fields):
    """A field the PRD calls absent reads as missing or null, never as a value."""
    for field in fields:
        assert entity.get(field) is None, (
            f"{field} should be absent on a freshly created record, got {entity.get(field)!r}"
        )


def test_registering_an_event_returns_its_tier_and_an_opening_ledger(client):
    """The forecast picks the tier and the three money fields open in agreement.

    "A newly registered event opens in `FORECAST` with `version` 1,
    `refund_approved_total_cents` at 0, `refund_budget_remaining_cents` equal to
    `refund_budget_total_cents`, and `gratuity_allocated_cents` at 0."

    Design: Corner/entities/event_creation_returns_tier_and_ledger_defaults
    """
    set_clock(client, "2026-09-01T09:00:00Z")

    event = create_event(
        client,
        name="Tier Two Matinee",
        expected_attendance=12000,
        refund_budget_total_cents=60000,
        gratuity_pool_cents=40000,
    )

    assert_common_fields(event)
    assert_fields(event, status="FORECAST", version=1, attendance_tier="TIER_2")
    assert_cents(event["refund_budget_total_cents"], 60000, "refund_budget_total_cents")
    assert_cents(event["refund_approved_total_cents"], 0, "refund_approved_total_cents")
    assert_cents(
        event["refund_budget_remaining_cents"], 60000, "refund_budget_remaining_cents"
    )
    assert_cents(event["gratuity_pool_cents"], 40000, "gratuity_pool_cents")
    assert_cents(event["gratuity_allocated_cents"], 0, "gratuity_allocated_cents")
    _unset(event, "historical_actual_attendance")
    assert_instant(event["created_at"], "2026-09-01T09:00:00.000Z", "created_at")


def test_reading_an_event_back_returns_every_stored_value_unmoved(client):
    """A read is not a mutation, so neither the version nor the update stamp stirs.

    "All resources except satisfaction responses additionally carry `updated_at` — an
    ISO 8601 UTC instant refreshed on every mutation of the resource — and `version`,
    an integer that starts at 1 on creation and increments by exactly 1 on every
    mutation."

    Design: Corner/entities/event_retrieval_returns_stored_values_unchanged
    """
    set_clock(client, "2026-09-01T10:00:00Z")

    event = create_event(
        client, name="Tier Three Evening", expected_attendance=25000
    )
    assert_fields(event, attendance_tier="TIER_3", version=1)
    assert_cents(event["refund_budget_total_cents"], 100000, "defaulted budget ceiling")
    assert_cents(event["gratuity_pool_cents"], 0, "defaulted gratuity pool")

    first_read = read_event(client, event["id"])
    second_read = read_event(client, event["id"])

    assert_fields(
        first_read,
        id=event["id"],
        name="Tier Three Evening",
        expected_attendance=25000,
        attendance_tier="TIER_3",
        status="FORECAST",
        version=1,
        created_at=event["created_at"],
        updated_at=event["updated_at"],
    )
    assert_cents(
        first_read["refund_budget_remaining_cents"], 100000, "refund_budget_remaining_cents"
    )
    assert_fields(second_read, version=1, updated_at=first_read["updated_at"])


def test_the_worker_list_windows_by_limit_and_offset_over_a_counted_set(client):
    """total_count sizes the whole set while limit and offset only move the window.

    "Every list response carries `limit`, `offset`, `total_count` and `has_more` inside
    the `meta` object of the envelope, where `total_count` is the size of the full
    filtered result set before the window is applied and `has_more` states whether
    records remain beyond the current window."

    Design: Corner/entities/staff_member_listing_paginates_with_total_count_and_has_more
    """
    set_clock(client, "2026-09-01T11:00:00Z")
    newest = create_member(
        client,
        full_name="Cleo Nunes",
        employment_type="CONTRACTED",
        seniority_date="2022-04-01T00:00:00Z",
        hourly_rate_cents=2600,
    )
    oldest = create_member(
        client,
        full_name="Abe Larsen",
        employment_type="PART_TIME_EMPLOYEE",
        seniority_date="2020-04-01T00:00:00Z",
        hourly_rate_cents=2100,
    )
    middle = create_member(
        client,
        full_name="Bea Ortiz",
        employment_type="PART_TIME_EMPLOYEE",
        seniority_date="2021-04-01T00:00:00Z",
        hourly_rate_cents=2200,
    )

    first_window, first_meta = page(
        client.list_staff_members(COORDINATOR_HEADERS, {"limit": 2, "offset": 0})
    )
    assert [row["id"] for row in first_window] == [oldest["id"], middle["id"]]
    assert_fields(first_meta, limit=2, offset=0, total_count=3, has_more=True)

    second_window, second_meta = page(
        client.list_staff_members(COORDINATOR_HEADERS, {"limit": 2, "offset": 2})
    )
    assert [row["id"] for row in second_window] == [newest["id"]]
    assert_fields(second_meta, limit=2, offset=2, total_count=3, has_more=False)

    everyone, default_meta = page(client.list_staff_members(COORDINATOR_HEADERS))
    assert [row["id"] for row in everyone] == [oldest["id"], middle["id"], newest["id"]]
    assert_fields(default_meta, limit=10, offset=0, total_count=3, has_more=False)


def test_fetching_an_unknown_issue_identifier_names_the_missing_entity(client):
    """The 404 names the guest issue itself, and the refused read stores nothing.

    "When a path carries an identifier that resolves to nothing, the request is refused
    with the 404 error naming that entity — `ERR_EVENT_NOT_FOUND`,
    `ERR_POSITION_TYPE_NOT_FOUND`, `ERR_STAFFING_PLAN_NOT_FOUND`,
    `ERR_POSITION_SLOT_NOT_FOUND`, `ERR_STAFF_MEMBER_NOT_FOUND`,
    `ERR_CERTIFICATION_NOT_FOUND`, `ERR_SHIFT_BID_NOT_FOUND`,
    `ERR_STAFF_ASSIGNMENT_NOT_FOUND`, `ERR_BACKFILL_REQUEST_NOT_FOUND`,
    `ERR_GUEST_ISSUE_NOT_FOUND`, `ERR_ACCESSIBILITY_RESOURCE_NOT_FOUND` or
    `ERR_ACCESSIBILITY_REQUEST_NOT_FOUND` — and the first unresolved identifier in the
    path wins."

    Design: Corner/entities/guest_issue_get_unknown_id_returns_not_found
    """
    body = err(client.get_guest_issue(MISSING_UUID, SUPERVISOR_HEADERS), ERR_GUEST_ISSUE_NOT_FOUND)
    assert body.get("message"), "a 404 envelope must carry a human-readable message"

    rows, meta = page(client.list_guest_issues(SUPERVISOR_HEADERS))
    assert rows == [], "a failed read must not conjure an issue"
    assert_fields(meta, total_count=0)


def test_a_family_filing_without_a_required_field_is_refused_outright(client):
    """Two omissions, two schema refusals, and no family on the books afterwards.

    "Request schema — required fields present, JSON types correct, enum values
    recognized, integers inside their declared ranges (a forecast attendance of at least
    0, a requested unit count of at least 1, a satisfaction score from 1 through 5, a
    headcount override either absent or at least 1), and pagination inside its declared
    range (`ERR_VALIDATION_FAILED`)."

    Design: Corner/entities/position_type_missing_required_fields_rejected
    """
    complete = usher_payload(required_certifications=["EVACUATION_PROCEDURES"])

    err(
        client.create_position_type(omit(complete, "min_headcount"), COORDINATOR_HEADERS),
        ERR_VALIDATION_FAILED,
    )
    err(
        client.create_position_type(
            omit(complete, "required_certifications"), COORDINATOR_HEADERS
        ),
        ERR_VALIDATION_FAILED,
    )

    rows, meta = page(client.list_position_types(COORDINATOR_HEADERS))
    assert rows == [], "a refused filing must not register a position family"
    assert_fields(meta, total_count=0)


def test_a_worker_enrolled_without_the_optional_flag_gets_the_declared_defaults(client):
    """The pool flag defaults to true, and every derived standing figure opens at its floor.

    "The optional `in_backfill_pool` flag records whether the worker has opted into the
    no-show backfill pool and is true unless the enrolment says otherwise. A new worker
    opens in `ACTIVE` with `reliability_score` and `season_reliability_score` both at
    100, `no_show_strikes` and `completed_assignment_count` both at 0, and
    `last_status_reason` absent."

    Design: Corner/entities/staff_member_omitted_optionals_get_declared_defaults
    """
    set_clock(client, "2026-09-01T12:00:00Z")

    defaulted = create_member(
        client,
        full_name="Nell Draper",
        employment_type="PART_TIME_EMPLOYEE",
        seniority_date="2023-08-01T00:00:00Z",
        hourly_rate_cents=2100,
    )
    opted_out = create_member(
        client,
        full_name="Owen Frick",
        employment_type="CONTRACTED",
        seniority_date="2023-09-01T00:00:00Z",
        hourly_rate_cents=2500,
        in_backfill_pool=False,
    )

    assert_common_fields(defaulted)
    assert_fields(
        defaulted,
        status="ACTIVE",
        in_backfill_pool=True,
        reliability_score=100,
        season_reliability_score=100,
        no_show_strikes=0,
        completed_assignment_count=0,
        version=1,
    )
    _unset(defaulted, "last_status_reason")

    assert_fields(opted_out, status="ACTIVE", in_backfill_pool=False, reliability_score=100)

    rows, meta = page(client.list_staff_members(COORDINATOR_HEADERS))
    assert [row["id"] for row in rows] == [defaulted["id"], opted_out["id"]]
    assert_fields(meta, total_count=2)


def test_a_block_computes_its_own_headcount_and_minutes_whatever_the_body_says(client):
    """Smuggled values for two derived fields are discarded and recomputed from the family.

    "`required_headcount` is then the `required_headcount_override` when that field
    carries a value and `ratio_derived_headcount` otherwise; note that the
    `min_headcount` floor is applied to the ratio result only and never to an override.
    Alongside the headcount the system records `shift_minutes`, the whole minutes between
    `shift_start` and `shift_end`."

    Design: Corner/entities/position_slot_computed_headcount_input_ignored
    """
    set_clock(client, "2026-09-01T13:00:00Z")
    event = create_event(client, name="Derived Field Fixture", expected_attendance=6000)
    family = create_ticket_taker(client)
    plan = create_plan(client, event["id"])
    assert_fields(plan, basis_attendance=6000, basis_attendance_tier="TIER_1")

    smuggled = created(
        client.create_position_slot(
            with_fields(
                position_slot_payload(
                    plan["id"],
                    family["id"],
                    zone_code="Z901",
                    shift_start="2026-09-12T18:00:00Z",
                    shift_end="2026-09-12T22:05:00Z",
                ),
                required_headcount=99,
                shift_minutes=10,
            ),
            COORDINATOR_HEADERS,
        )
    )
    assert_fields(
        smuggled,
        ratio_derived_headcount=5,
        required_headcount=5,
        shift_minutes=245,
        filled_headcount=0,
        status="OPEN",
    )
    assert_cents(smuggled["slot_labor_cost_cents"], 40833, "slot_labor_cost_cents")

    overridden = create_slot(
        client,
        plan["id"],
        family["id"],
        zone_code="Z902",
        shift_start="2026-09-12T18:00:00Z",
        shift_end="2026-09-12T22:05:00Z",
        required_headcount_override=2,
    )
    assert_fields(
        overridden, ratio_derived_headcount=5, required_headcount=2, shift_minutes=245
    )
    assert_cents(overridden["slot_labor_cost_cents"], 16333, "overridden slot cost")

    costed = read_plan(client, plan["id"])
    assert_fields(costed, total_required_headcount=7)
    assert_cents(costed["base_labor_cost_cents"], 57166, "base_labor_cost_cents")
    assert_cents(costed["accessibility_surcharge_cents"], 0, "accessibility_surcharge_cents")
    assert_cents(costed["projected_labor_cost_cents"], 57166, "projected_labor_cost_cents")
    assert_ratio(family["attendance_ratio_per_1000"], 0.8, "attendance_ratio_per_1000")


def test_a_filed_issue_takes_its_reporter_and_its_clock_from_the_server(client):
    """The client may not choose its own status, its reporter or its response allowance.

    "A new issue opens in `OPEN` with `reported_by_user_id` recorded from `X-User-ID`,
    `refund_status` at `NONE`, `refund_requested_cents` at 0, `reopen_count` at 0, and
    `assigned_staff_member_id`, `resolved_by_user_id`, `resolution_type`, `resolved_at`,
    `relocation_zone_code`, `escalated_from_issue_id`, `refund_requested_by_user_id` and
    `refund_decided_by_user_id` all absent."

    Design: Corner/entities/guest_issue_system_fields_stamped_by_server_input_ignored
    """
    set_clock(client, "2026-09-12T18:00:00Z")
    event = create_event(client, name="Server Stamped Fields Fixture")

    issue = created(
        client.create_guest_issue(
            with_fields(
                guest_issue_payload(
                    event["id"],
                    channel="IN_PERSON",
                    category="OTHER",
                    severity="MEDIUM",
                    description="Concourse queue never moved for twenty minutes",
                ),
                status="RESOLVED",
                reported_by_user_id="spoofed-user",
            ),
            SUPERVISOR_HEADERS,
        )
    )

    assert_common_fields(issue)
    assert_fields(
        issue,
        status="OPEN",
        reported_by_user_id=SUPERVISOR_USER_ID,
        severity="MEDIUM",
        sla_minutes=45,
        sla_breached=False,
        refund_status="NONE",
        refund_requested_cents=0,
        reopen_count=0,
        version=1,
    )
    assert issue["reported_by_user_id"] != "spoofed-user", (
        "the reporter is read from X-User-ID, never from the request body"
    )
    assert_instant(
        issue["sla_clock_started_at"], "2026-09-12T18:00:00.000Z", "sla_clock_started_at"
    )
    assert_instant(issue["sla_deadline"], "2026-09-12T18:45:00.000Z", "sla_deadline")
    _unset(
        issue,
        "assigned_staff_member_id",
        "resolved_by_user_id",
        "resolution_type",
        "resolved_at",
        "relocation_zone_code",
        "escalated_from_issue_id",
        "refund_requested_by_user_id",
        "refund_decided_by_user_id",
    )


def test_accessibility_enums_and_counted_ranges_are_policed_at_the_schema(client):
    """An unknown pool type, a zero unit ask, a score of six and a collapsed window all fail.

    "Request schema — required fields present, JSON types correct, enum values
    recognized, integers inside their declared ranges (a forecast attendance of at least
    0, a requested unit count of at least 1, a satisfaction score from 1 through 5, a
    headcount override either absent or at least 1), and pagination inside its declared
    range (`ERR_VALIDATION_FAILED`)."

    "The window must be strictly ordered, `window_start` before `window_end`, or the
    booking is refused with `ERR_INVALID_TIME_WINDOW`."

    Design: Corner/entities/accessibility_enum_and_range_constraints_rejected
    """
    set_clock(client, "2026-09-01T14:00:00Z")
    event = create_event(client, name="Accessibility Schema Fixture")
    pool = create_resource(
        client, event["id"], resource_type="WHEELCHAIR_ESCORT", zone_code="Z903", unit_count=3
    )
    assert_fields(pool, status="AVAILABLE", unit_count=3, peak_committed_units=0)

    err(
        client.create_accessibility_resource(
            accessibility_resource_payload(
                event["id"], resource_type="SERVICE_ANIMAL_RELIEF", zone_code="Z904"
            ),
            SUPERVISOR_HEADERS,
        ),
        ERR_VALIDATION_FAILED,
    )
    err(
        client.create_accessibility_request(
            accessibility_request_payload(pool["id"], units_requested=0),
            SUPERVISOR_HEADERS,
        ),
        ERR_VALIDATION_FAILED,
    )
    err(
        client.create_satisfaction_response(
            satisfaction_response_payload(event["id"], "Z903", 6), SUPERVISOR_HEADERS
        ),
        ERR_VALIDATION_FAILED,
    )
    err(
        client.create_accessibility_request(
            accessibility_request_payload(
                pool["id"],
                window_start="2026-09-12T19:00:00Z",
                window_end="2026-09-12T19:00:00Z",
            ),
            SUPERVISOR_HEADERS,
        ),
        ERR_INVALID_TIME_WINDOW,
    )

    assert_fields(read_resource(client, pool["id"]), peak_committed_units=0, unit_count=3)
    bookings, booking_meta = page(
        client.list_accessibility_requests(SUPERVISOR_HEADERS, {"resource_id": pool["id"]})
    )
    assert bookings == [], "no refused booking may be stored"
    assert_fields(booking_meta, total_count=0)
    _pools, pool_meta = page(
        client.list_accessibility_resources(SUPERVISOR_HEADERS, {"event_id": event["id"]})
    )
    assert_fields(pool_meta, total_count=1)


def test_a_satisfaction_response_carries_neither_a_version_nor_an_update_stamp(client):
    """The append-only resource is the one exception to the common mutation fields.

    "A response is the one resource in this system that carries no `updated_at` and no
    `version` at all — only its `id` and its `created_at` — because it can never be
    edited, withdrawn or corrected once filed."

    Design: Corner/entities/satisfaction_response_has_no_version_and_no_update_endpoint
    """
    set_clock(client, "2026-09-01T15:00:00Z")
    event = create_event(client, name="Append Only Sentiment Fixture")

    first = create_satisfaction_response(
        client, event["id"], "Z301", 5, comment="Escort staff were outstanding"
    )
    second = create_satisfaction_response(client, event["id"], "Z301", 4)

    for response in (first, second):
        assert_common_fields(response, versioned=False)
        assert_absent(response, "updated_at", "version")
        assert_fields(response, event_id=event["id"], zone_code="Z301")
        assert response["submitted_by_user_id"] == SUPERVISOR_USER_ID, (
            "submitted_by_user_id is recorded from X-User-ID"
        )
    assert_fields(first, score=5, comment="Escort staff were outstanding")
    assert_fields(second, score=4)
    _unset(second, "comment")

    rows, meta = page(client.list_event_satisfaction_responses(event["id"], SUPERVISOR_HEADERS))
    assert [row["id"] for row in rows] == [first["id"], second["id"]]
    assert_fields(meta, total_count=2)

    summary = ok(client.get_satisfaction_summary(event["id"], SUPERVISOR_HEADERS))
    assert_fields(summary, response_count=2, promoter_share_bp=10000)
    assert_average(summary["average_score"], 4.50, "average_score")
    assert len(summary["zone_breakdown"]) == 1, "one entry per distinct zone_code"
    assert_fields(summary["zone_breakdown"][0], zone_code="Z301", response_count=2)
    assert_average(summary["zone_breakdown"][0]["average_score"], 4.50, "zone average_score")


def test_a_child_naming_a_parent_that_does_not_exist_is_refused_with_that_parents_404(client):
    """Body foreign keys are resolved before anything is stored, entity by entity.

    "Foreign keys carried in a request body are resolved after every path identifier, and
    among themselves in the order the fields are declared on the target entity."

    Design: Corner/entities/child_creation_with_unknown_parent_fk_rejected
    """
    set_clock(client, "2026-09-01T16:00:00Z")
    event = create_event(client, name="Foreign Key Fixture")
    plan = create_plan(client, event["id"])

    err(
        client.create_staffing_plan(staffing_plan_payload(MISSING_UUID), COORDINATOR_HEADERS),
        ERR_EVENT_NOT_FOUND,
    )
    err(
        client.create_certification(
            certification_payload(MISSING_UUID, "CODE_OF_CONDUCT"), COORDINATOR_HEADERS
        ),
        ERR_STAFF_MEMBER_NOT_FOUND,
    )
    err(
        client.create_position_slot(
            position_slot_payload(plan["id"], MISSING_UUID, zone_code="Z906"),
            COORDINATOR_HEADERS,
        ),
        ERR_POSITION_TYPE_NOT_FOUND,
    )

    plans, plan_meta = page(
        client.list_staffing_plans(COORDINATOR_HEADERS, {"event_id": event["id"]})
    )
    assert [row["id"] for row in plans] == [plan["id"]]
    assert_fields(plan_meta, total_count=1)
    slots, slot_meta = page(
        client.list_position_slots(COORDINATOR_HEADERS, {"plan_id": plan["id"]})
    )
    assert slots == [], "a refused block filing must leave the plan empty"
    assert_fields(slot_meta, total_count=0)

    unchanged = read_plan(client, plan["id"])
    assert_fields(unchanged, total_required_headcount=0)
    assert_cents(unchanged["base_labor_cost_cents"], 0, "base_labor_cost_cents")
    assert_cents(unchanged["projected_labor_cost_cents"], 0, "projected_labor_cost_cents")


def test_blocks_are_cross_referenced_by_plan_and_by_family_independently(client):
    """A flat block table partitions cleanly along either reference and along both at once.

    "Blocks may be listed filtered by `plan_id`, `position_type_id`, `status` and
    `zone_code`."

    "A plan opens in `DRAFT` with `activated_at` absent, with `total_required_headcount`,
    `base_labor_cost_cents`, `accessibility_surcharge_cents` and
    `projected_labor_cost_cents` all at 0 because it owns no shift blocks yet, and with a
    `revision_number` equal to 1 plus the number of plans the event already had at the
    moment of creation — so a plan that supersedes another is identifiable without
    reading any identifier."

    Design: Corner/entities/flat_topology_slot_cross_reference_integrity
    """
    set_clock(client, "2026-09-01T17:00:00Z")
    event = create_event(client, name="Cross Reference Fixture")
    ushers = create_usher(client)
    takers = create_ticket_taker(client)
    first_plan = create_plan(client, event["id"])
    second_plan = create_plan(client, event["id"])
    assert_fields(first_plan, revision_number=1)
    assert_fields(second_plan, revision_number=2)

    blocks = {}
    zone = 911
    for plan in (first_plan, second_plan):
        for family in (ushers, takers):
            blocks[(plan["id"], family["id"])] = create_slot(
                client,
                plan["id"],
                family["id"],
                zone_code=f"Z{zone}",
                shift_start="2026-09-12T18:00:00Z",
                shift_end="2026-09-12T22:00:00Z",
                required_headcount_override=1,
            )
            zone += 1

    for plan in (first_plan, second_plan):
        rows, meta = page(
            client.list_position_slots(COORDINATOR_HEADERS, {"plan_id": plan["id"]})
        )
        assert_fields(meta, total_count=2)
        assert {row["position_type_id"] for row in rows} == {ushers["id"], takers["id"]}

    for family in (ushers, takers):
        rows, meta = page(
            client.list_position_slots(
                COORDINATOR_HEADERS, {"position_type_id": family["id"]}
            )
        )
        assert_fields(meta, total_count=2)
        assert {row["plan_id"] for row in rows} == {first_plan["id"], second_plan["id"]}

    pinpoint, pinpoint_meta = page(
        client.list_position_slots(
            COORDINATOR_HEADERS,
            {"plan_id": second_plan["id"], "position_type_id": ushers["id"]},
        )
    )
    assert_fields(pinpoint_meta, total_count=1)
    assert_fields(pinpoint[0], id=blocks[(second_plan["id"], ushers["id"])]["id"])

    plans, plans_meta = page(
        client.list_staffing_plans(COORDINATOR_HEADERS, {"event_id": event["id"]})
    )
    assert_fields(plans_meta, total_count=2)
    assert [row["revision_number"] for row in plans] == [1, 2]
    for row in plans:
        assert_fields(row, total_required_headcount=2)
