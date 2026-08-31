"""Distribution events: seat throughput, publication gates and the two fill projections."""

from test_helpers import (
    ApiErrorId,
    assert_distribution_event,
    assert_pct_equals,
    create_active_school,
    create_backpack,
    create_cash_gift,
    create_collecting_cycle,
    create_event,
    create_purchase_order,
    create_registration,
    create_spec,
    add_spec_line,
    make_school_liaison_headers,
    move_cycle,
    move_event,
    move_school,
    setup_three_line_program,
    submit_order,
    validate_error,
    validate_paginated,
    validate_success,
    verify_registration,
    waitlist_registration,
)
from test_helpers import TEST_USERS

PD = TEST_USERS["program_director_headers"]
WL = TEST_USERS["warehouse_lead_headers"]


def _fill_projection_scenario():
    """Six pencils, twenty notebooks and five backpacks on hand, a SUBMITTED order
    adding twenty-four pencils of expectation, and a PUBLISHED twenty-seat event with
    two VERIFIED, one PENDING and one WAITLISTED registration."""
    program = setup_three_line_program(
        pencil_on_hand=6, notebook_on_hand=20, backpack_on_hand=5,
        seat_capacity=20, publish_event=False,
    )
    create_cash_gift(
        program.cycle_id, donor_name="Acme Corp", amount_cents=20_000,
        restriction_type="UNRESTRICTED",
    )
    order = create_purchase_order(program.cycle_id, program.pencil_id, requested_unit_gap=24)
    submit_order(order["id"], program.cycle_id)

    event = validate_success(move_event(program.event_id, program.school_id, "PUBLISHED"))
    registrations = []
    for reference, guardian, flags in (
        ("S-001", "G One", {"free_lunch_eligible": True}),
        ("S-002", "G Two", {"free_lunch_eligible": True}),
        ("S-003", "G Three", {"free_lunch_eligible": True}),
        ("S-004", "G Four", {"income_verified": True}),
    ):
        registrations.append(
            create_registration(
                event["id"], program.school_id,
                student_reference=reference, guardian_name=guardian, **flags,
            )
        )
    verify_registration(registrations[0]["id"], event["id"], program.school_id)
    verify_registration(registrations[1]["id"], event["id"], program.school_id)
    verify_registration(registrations[3]["id"], event["id"], program.school_id)
    waitlist_registration(registrations[3]["id"], event["id"], program.school_id)
    return program, registrations


def test_provisional_fill_counts_in_transit_units_and_every_live_registration(api):
    """PRD §3.6: "Its available units for a line are the position's `on_hand_qty` plus
    its `in_transit_qty` — that is, it counts stock already in the building together
    with the purchase orders in `SUBMITTED` or `APPROVED` and the donation batches in
    `RECEIVED`, `INSPECTED` or `REMEDIATED` that are still expected to arrive."
    PRD §3.6: "Its headcount is the number of the event's registrations whose
    `eligibility_status` is `PENDING`, `VERIFIED`, `CONFIRMED` or `WAITLISTED`."
    PRD §3.6: "Because a kit is not a kit unless every line is present, the number of
    coverable students is the **smallest** of those per-line figures across all lines
    of the list."

    Design: Difficulty/dual_variant_calc/fill_projection_provisional_vs_final_diverge_on_distribution_event
    """
    program, _ = _fill_projection_scenario()

    event = validate_success(api.get_distribution_event(program.event_id, PD))
    assert_distribution_event(event)
    assert_pct_equals(event["provisional_fill_pct"], 100.00, "provisional_fill_pct")


def test_final_fill_discards_in_transit_units_and_narrows_the_headcount(api):
    """PRD §3.6: "Its available units for a line are the position's `on_hand_qty` alone;
    in-transit expectation is discarded entirely."
    PRD §3.6: "Its headcount counts only the event's registrations whose
    `eligibility_status` is `VERIFIED` or `CONFIRMED`, so `PENDING` and `WAITLISTED`
    registrations drop out of the denominator."
    PRD §3.6: "It is computed exactly once, at the moment the event moves from
    `PUBLISHED` to `LOCKED`, written to `final_fill_pct`, and never recomputed
    afterwards."

    Design: Difficulty/dual_variant_calc/fill_projection_provisional_vs_final_diverge_on_distribution_event
    """
    program, _ = _fill_projection_scenario()
    validate_success(move_cycle(program.cycle_id, "SORTING"))
    validate_success(move_cycle(program.cycle_id, "DISTRIBUTION"))

    locked = validate_success(move_event(program.event_id, program.school_id, "LOCKED"))
    assert locked["status"] == "LOCKED"
    assert_pct_equals(locked["final_fill_pct"], 50.00, "final_fill_pct")
    assert_pct_equals(locked["provisional_fill_pct"], 100.00, "provisional_fill_pct")
    assert float(locked["provisional_fill_pct"]) != float(locked["final_fill_pct"]), (
        "the two variants read different evidence and must not be conflated"
    )


def test_distribution_event_cannot_be_created_for_a_suspended_school(api):
    """PRD §3.6: "The governing school must be `ACTIVE` at creation time, or
    `ERR_SCHOOL_PARTNERSHIP_INACTIVE` applies, and the window must sit inside the cycle
    window exactly as volunteer sessions must, reported as `ERR_WINDOW_OUTSIDE_CYCLE`."

    Design: Difficulty/cross_entity_state_dependency/distribution_event_create_requires_active_school_partnership
    """
    school = create_active_school()
    cycle = create_collecting_cycle()
    validate_success(move_school(school["id"], "SUSPENDED"))

    response = api.create_distribution_event(
        {
            "school_id": school["id"],
            "drive_cycle_id": cycle["id"],
            "grade_band": "K_2",
            "window_start": "2026-08-20T15:00:00Z",
            "window_end": "2026-08-20T19:00:00Z",
            "seat_capacity": 5,
        },
        make_school_liaison_headers(school["id"]),
    )
    validate_error(
        response, ApiErrorId.ERR_SCHOOL_PARTNERSHIP_INACTIVE.value, expected_status=409
    )

    rows, _ = validate_paginated(
        api.list_distribution_events(PD, params={"school_id": school["id"]})
    )
    assert rows == [], "no event may be persisted for an inactive partnership"


def test_the_identical_event_request_succeeds_only_while_the_school_is_active(api):
    """PRD §3.1: "Only an `ACTIVE` school may publish a needs list or stand up a
    distribution event, which makes the `ACTIVE` state the gate the rest of §3 keeps
    referring back to."
    PRD §3.6: "The governing school must be `ACTIVE` at creation time, or
    `ERR_SCHOOL_PARTNERSHIP_INACTIVE` applies, and the window must sit inside the cycle
    window exactly as volunteer sessions must, reported as `ERR_WINDOW_OUTSIDE_CYCLE`."

    Design: Difficulty/cross_entity_state_dependency/distribution_event_create_requires_active_school_partnership
    """
    school = create_active_school()
    cycle = create_collecting_cycle()
    liaison = make_school_liaison_headers(school["id"])
    payload = {
        "school_id": school["id"],
        "drive_cycle_id": cycle["id"],
        "grade_band": "K_2",
        "window_start": "2026-08-20T15:00:00Z",
        "window_end": "2026-08-20T19:00:00Z",
        "seat_capacity": 5,
    }

    created = validate_success(api.create_distribution_event(payload, liaison), expected_status=201)
    assert created["status"] == "DRAFT"

    validate_success(move_school(school["id"], "SUSPENDED"))
    refused = api.create_distribution_event(payload, liaison)
    validate_error(refused, ApiErrorId.ERR_SCHOOL_PARTNERSHIP_INACTIVE.value, expected_status=409)


def test_events_touching_at_an_endpoint_overlap_and_breach_the_seat_ceiling(api):
    """PRD §3.6: "A distribution event's interval is **closed**: it includes both its
    `window_start` and its `window_end`, so two events that merely touch at an endpoint
    do overlap."
    PRD §3.6: "The request is refused only when, at some instant inside the proposed
    interval, the sum of `seat_capacity` over the proposed event together with every
    overlapping event of the same school whose `status` is `DRAFT`, `PUBLISHED` or
    `LOCKED` exceeds that school's `max_concurrent_seats`."
    PRD §3.6: "Breaching that ceiling is reported as `ERR_SCHOOL_THROUGHPUT_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/distribution_events_overlap_on_closed_intervals_with_aggregate_seat_ceiling
    """
    school = create_active_school(max_concurrent_seats=120)
    cycle = create_collecting_cycle()
    create_event(
        school["id"], cycle["id"], grade_band="K_2",
        window_start="2026-08-20T15:00:00Z", window_end="2026-08-20T19:00:00Z",
        seat_capacity=100,
    )

    response = api.create_distribution_event(
        {
            "school_id": school["id"],
            "drive_cycle_id": cycle["id"],
            "grade_band": "G3_5",
            "window_start": "2026-08-20T19:00:00Z",
            "window_end": "2026-08-20T21:00:00Z",
            "seat_capacity": 30,
        },
        make_school_liaison_headers(school["id"]),
    )
    validate_error(
        response, ApiErrorId.ERR_SCHOOL_THROUGHPUT_EXCEEDED.value, expected_status=409
    )


def test_an_event_starting_one_second_later_does_not_overlap(api):
    """PRD §3.6: "A distribution event's interval is **closed**: it includes both its
    `window_start` and its `window_end`, so two events that merely touch at an endpoint
    do overlap."
    PRD §3.6: "There is no turnover buffer, and overlapping events at one school are
    perfectly legal — a school may run two grade bands in adjacent gyms at the same
    hour."

    Design: Difficulty/resource_temporal_overlap/distribution_events_overlap_on_closed_intervals_with_aggregate_seat_ceiling
    """
    school = create_active_school(max_concurrent_seats=120)
    cycle = create_collecting_cycle()
    create_event(
        school["id"], cycle["id"], grade_band="K_2",
        window_start="2026-08-20T15:00:00Z", window_end="2026-08-20T19:00:00Z",
        seat_capacity=100,
    )

    created = validate_success(
        api.create_distribution_event(
            {
                "school_id": school["id"],
                "drive_cycle_id": cycle["id"],
                "grade_band": "G3_5",
                "window_start": "2026-08-20T19:00:01Z",
                "window_end": "2026-08-20T21:00:00Z",
                "seat_capacity": 30,
            },
            make_school_liaison_headers(school["id"]),
        ),
        expected_status=201,
    )
    assert created["seat_capacity"] == 30

    rows, meta = validate_paginated(
        api.list_distribution_events(PD, params={"school_id": school["id"]})
    )
    assert meta["total_count"] == 2
    assert len(rows) == 2


def test_event_window_must_sit_inside_the_cycle_window(api):
    """PRD §3.6: "The governing school must be `ACTIVE` at creation time, or
    `ERR_SCHOOL_PARTNERSHIP_INACTIVE` applies, and the window must sit inside the cycle
    window exactly as volunteer sessions must, reported as `ERR_WINDOW_OUTSIDE_CYCLE`."
    PRD §3.4: "The session's window must also sit entirely inside the governing drive
    cycle's window — the cycle's `window_start` must be no later than the session's
    `window_start`, and the session's `window_end` must be no later than the cycle's
    `window_end` — or the request is refused with `ERR_WINDOW_OUTSIDE_CYCLE`."

    Design: Corner/validations/distribution_window_outside_cycle_window_is_rejected
    """
    school = create_active_school()
    cycle = create_collecting_cycle()

    response = api.create_distribution_event(
        {
            "school_id": school["id"],
            "drive_cycle_id": cycle["id"],
            "grade_band": "K_2",
            "window_start": "2026-10-05T15:00:00Z",
            "window_end": "2026-10-05T19:00:00Z",
            "seat_capacity": 10,
        },
        make_school_liaison_headers(school["id"]),
    )
    validate_error(response, ApiErrorId.ERR_WINDOW_OUTSIDE_CYCLE.value, expected_status=422)

    rows, _ = validate_paginated(
        api.list_distribution_events(PD, params={"drive_cycle_id": cycle["id"]})
    )
    assert rows == []


def test_publishing_without_a_published_needs_list_is_rejected(api):
    """PRD §3.6: "Publishing requires the event to be in `DRAFT`, requires the governing
    school's `partnership_status` to be `ACTIVE`, requires a needs list with status
    `PUBLISHED` to exist for that exact combination of `school_id` and `grade_band` and
    to carry at least one line — otherwise `ERR_KIT_SPEC_NOT_PUBLISHED` — requires the
    governing cycle to be in `COLLECTING`, `SORTING` or `DISTRIBUTION`, and re-asserts
    the aggregate seat ceiling described above, again reporting
    `ERR_SCHOOL_THROUGHPUT_EXCEEDED`."

    Design: Corner/validations/event_publish_without_a_published_spec_is_rejected
    """
    school = create_active_school()
    backpack = create_backpack()
    spec = create_spec(school["id"], grade_band="K_2", student_target_count=100)
    add_spec_line(school["id"], spec["id"], backpack["id"], qty_per_student=1)
    cycle = create_collecting_cycle()
    event = create_event(school["id"], cycle["id"], grade_band="K_2", seat_capacity=10)

    response = move_event(event["id"], school["id"], "PUBLISHED")
    validate_error(response, ApiErrorId.ERR_KIT_SPEC_NOT_PUBLISHED.value, expected_status=409)

    reread = validate_success(api.get_distribution_event(event["id"], PD))
    assert reread["status"] == "DRAFT"
    assert_pct_equals(reread["provisional_fill_pct"], 0.00, "provisional_fill_pct")


def test_distribution_event_listing_is_paginated_with_envelope_counts(api):
    """PRD §2.3: "Every list endpoint accepts two optional query parameters. `limit`
    controls page size: it defaults to 10 when omitted, may be no smaller than 1 and no
    larger than 100."
    PRD §2.3: "Unless a subsection below says otherwise, list results are ordered by
    `created_at` ascending — oldest record first."

    Design: Corner/entities/distribution_event_listing_is_paginated_with_envelope_counts
    """
    school = create_active_school()
    cycle = create_collecting_cycle()
    first = create_event(
        school["id"], cycle["id"], grade_band="K_2",
        window_start="2026-08-20T15:00:00Z", window_end="2026-08-20T17:00:00Z",
        seat_capacity=10,
    )
    second = create_event(
        school["id"], cycle["id"], grade_band="G3_5",
        window_start="2026-08-21T15:00:00Z", window_end="2026-08-21T17:00:00Z",
        seat_capacity=10,
    )

    response = api.list_distribution_events(
        PD, params={"school_id": school["id"], "limit": 1, "offset": 0}
    )
    rows, meta = validate_paginated(response)
    assert response.json()["response_type"] == "array"
    assert len(rows) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert rows[0]["id"] in (first["id"], second["id"])
