"""Run planning, stop booking, crew invitations and the dispatch gates."""

import pytest

from test_helpers import (
    ADMIN,
    DISPATCH,
    WAREHOUSE,
    ApiErrorId,
    allocate,
    book_stop,
    create_agency,
    create_approved_referral,
    create_client,
    create_run,
    create_truck,
    create_volunteer,
    crew_assignment_payload,
    delivery_stop_payload,
    dispatch_run,
    donation_item_payload,
    get_crew_assignment,
    get_run,
    get_stop,
    invite_crew,
    issue_voucher,
    make_volunteer_headers,
    respond_crew,
    set_clock,
    setup_allocated_voucher,
    setup_banned_household,
    setup_crewed_run,
    supply_clean_stock,
    validate_error,
    validate_paginated,
    validate_success,
    voucher_line_payload,
)
from test_helpers.assertions import assert_crew_assignment, assert_delivery_run


def _run_with_one_confirmed_driver(truck_label="BOX-22", crew_minimum=1):
    set_clock("2026-08-04T09:00:00Z")
    truck = create_truck(label=truck_label, capacity_cubic_feet=600,
                         home_county="CENTRAL", crew_minimum=crew_minimum)
    volunteer = create_volunteer(name="Mira Solberg", county="CENTRAL",
                                 lift_certified=True)
    run = create_run(truck["id"], service_date="2026-08-05",
                     window_start="2026-08-05T09:00:00Z",
                     window_end="2026-08-05T17:00:00Z", county="CENTRAL")
    assignment = invite_crew(run["id"], volunteer["id"], "DRIVER")
    confirmed = respond_crew(assignment["id"], volunteer["id"], "CONFIRM")
    return {"truck": truck, "volunteer": volunteer, "run": run,
            "assignment": assignment, "confirmed": confirmed}


def _volunteer_with_three_candidate_runs():
    set_clock("2026-08-04T09:00:00Z")
    truck = create_truck(label="BOX-11", capacity_cubic_feet=600,
                         home_county="CENTRAL", crew_minimum=1)
    volunteer = create_volunteer(name="Kai Mensah", county="CENTRAL",
                                 lift_certified=False)
    run_one = create_run(truck["id"], service_date="2026-08-05",
                         window_start="2026-08-05T09:00:00Z",
                         window_end="2026-08-05T12:00:00Z", county="CENTRAL")
    run_two = create_run(truck["id"], service_date="2026-08-05",
                         window_start="2026-08-05T13:00:00Z",
                         window_end="2026-08-05T16:00:00Z", county="CENTRAL")
    run_three = create_run(truck["id"], service_date="2026-08-05",
                           window_start="2026-08-05T13:01:00Z",
                           window_end="2026-08-05T16:00:00Z", county="CENTRAL")
    first_assignment = invite_crew(run_one["id"], volunteer["id"], "LIFTER")
    return {"truck": truck, "volunteer": volunteer, "run_one": run_one,
            "run_two": run_two, "run_three": run_three,
            "assignment": first_assignment}


# ─── Corner: crew lifecycle ────────────────────────────────────────────

def test_crew_withdrawal_demotes_a_crewed_run_back_to_planned(api):
    """PRD §3.7: "Withdrawing requires the assignment to be `CONFIRMED`,
    requires the acting user to own it, and requires the run to be in `PLANNED`
    or `CREWED`; it moves the assignment `CONFIRMED → RELEASED`, returns 4.0
    hours from that volunteer's `assigned_hours_month` with the result floored
    at 0.0, lowers the run's `confirmed_crew_count` by 1, recomputes
    `has_confirmed_driver`, and bumps the assignment's `version`."
    PRD §3.7: "After a withdrawal, a run in `CREWED` falls back `CREWED →
    PLANNED` when its `confirmed_crew_count` has dropped below the truck's
    `crew_minimum` or its `has_confirmed_driver` has become false."

    Design: Corner/state_machines/corner_crew_withdraw_demotes_run_from_crewed_back_to_planned
    """
    scenario = _run_with_one_confirmed_driver()
    assert scenario["confirmed"]["status"] == "CONFIRMED"
    assert get_run(scenario["run"]["id"])["status"] == "CREWED"

    respond_crew(scenario["assignment"]["id"], scenario["volunteer"]["id"], "WITHDRAW")

    assignment_now = get_crew_assignment(scenario["run"]["id"],
                                         scenario["assignment"]["id"])
    assert assignment_now["status"] == "RELEASED"

    run_now = validate_success(api.get_delivery_run(scenario["run"]["id"], DISPATCH))
    assert_delivery_run(run_now)
    assert run_now["status"] == "PLANNED", "the run falls back below its crew minimum"
    assert run_now["confirmed_crew_count"] == 0
    assert run_now["has_confirmed_driver"] is False

    volunteer_now = validate_success(
        api.get_volunteer(scenario["volunteer"]["id"], DISPATCH)
    )
    assert volunteer_now["assigned_hours_month"] == pytest.approx(0.0, abs=0.001)
    assert volunteer_now["reliability_score"] == pytest.approx(100.0, abs=0.001)


def test_declined_crew_assignment_cannot_be_confirmed_later(api):
    """PRD §3.7: "A response that has no outgoing edge from the assignment's
    current state — confirming or declining something that is not `INVITED`, or
    withdrawing something that is not `CONFIRMED` — is rejected with
    `ERR_CREW_ASSIGNMENT_INVALID_STATE`."
    PRD §3.7: "Declining requires the assignment to be `INVITED` and the acting
    user to own it; it moves the assignment `INVITED → DECLINED` and bumps its
    `version`, with no effect on hours or crew counts."

    Design: Corner/state_machines/corner_declined_crew_assignment_cannot_be_confirmed_later
    """
    set_clock("2026-08-04T09:00:00Z")
    truck = create_truck(label="BOX-23", capacity_cubic_feet=600,
                         home_county="CENTRAL", crew_minimum=1)
    volunteer = create_volunteer(name="Otto Brandt", county="CENTRAL",
                                 lift_certified=True)
    run = create_run(truck["id"], service_date="2026-08-05",
                     window_start="2026-08-05T09:00:00Z",
                     window_end="2026-08-05T17:00:00Z", county="CENTRAL")
    assignment = invite_crew(run["id"], volunteer["id"], "DRIVER")
    respond_crew(assignment["id"], volunteer["id"], "DECLINE")

    response = api.respond_crew_assignment(
        assignment["id"], {"response": "CONFIRM"},
        make_volunteer_headers(volunteer["id"]),
    )
    validate_error(response, ApiErrorId.ERR_CREW_ASSIGNMENT_INVALID_STATE.value, 409)

    assignment_now = get_crew_assignment(run["id"], assignment["id"])
    assert assignment_now["status"] == "DECLINED"

    run_now = validate_success(api.get_delivery_run(run["id"], DISPATCH))
    assert run_now["status"] == "PLANNED"
    assert run_now["confirmed_crew_count"] == 0

    volunteer_now = validate_success(api.get_volunteer(volunteer["id"], DISPATCH))
    assert volunteer_now["assigned_hours_month"] == pytest.approx(0.0, abs=0.001)


def test_duplicate_invitation_of_the_same_volunteer_on_one_run_is_refused(api):
    """PRD §3.7: "The volunteer must not already hold an `INVITED` or
    `CONFIRMED` assignment on this same run, otherwise
    `ERR_DUPLICATE_CREW_ASSIGNMENT`."

    Design: Corner/validations/corner_duplicate_crew_invitation_on_same_run_rejected
    """
    set_clock("2026-08-04T09:00:00Z")
    truck = create_truck(label="BOX-41", capacity_cubic_feet=600,
                         home_county="CENTRAL", crew_minimum=1)
    volunteer = create_volunteer(name="Aiko Tanaka", county="CENTRAL",
                                 lift_certified=False)
    run = create_run(truck["id"], service_date="2026-08-05",
                     window_start="2026-08-05T09:00:00Z",
                     window_end="2026-08-05T17:00:00Z", county="CENTRAL")
    assignment = invite_crew(run["id"], volunteer["id"], "LIFTER")

    response = api.create_crew_assignment(
        run["id"], crew_assignment_payload(volunteer["id"], "LIFTER"), DISPATCH
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_CREW_ASSIGNMENT.value, 409)

    crew_rows, _ = validate_paginated(api.list_run_crew(run["id"], DISPATCH))
    assert len(crew_rows) == 1, "the refused invitation creates no second row"
    assert crew_rows[0]["id"] == assignment["id"]
    assert crew_rows[0]["status"] == "INVITED"


def test_driver_seat_requires_a_lift_certified_volunteer(api):
    """PRD §3.7: "And a `DRIVER` seat may only be offered to a volunteer whose
    `lift_certified` is true, otherwise `ERR_DRIVER_NOT_CERTIFIED`."
    PRD §3.7: "A planner invites a volunteer onto a run by naming the
    `volunteer_id` and the `role_on_crew`, which is either `DRIVER` or `LIFTER`.
    The assignment is created in `status` `INVITED`."

    Design: Corner/validations/corner_driver_seat_requires_lift_certified_volunteer
    """
    set_clock("2026-08-04T09:00:00Z")
    truck = create_truck(label="BOX-42", capacity_cubic_feet=600,
                         home_county="CENTRAL", crew_minimum=1)
    volunteer = create_volunteer(name="Bruno Salgado", county="CENTRAL",
                                 lift_certified=False)
    run = create_run(truck["id"], service_date="2026-08-05",
                     window_start="2026-08-05T09:00:00Z",
                     window_end="2026-08-05T17:00:00Z", county="CENTRAL")

    refused = api.create_crew_assignment(
        run["id"], crew_assignment_payload(volunteer["id"], "DRIVER"), DISPATCH
    )
    validate_error(refused, ApiErrorId.ERR_DRIVER_NOT_CERTIFIED.value, 422)

    accepted = validate_success(
        api.create_crew_assignment(
            run["id"], crew_assignment_payload(volunteer["id"], "LIFTER"), DISPATCH
        ),
        201,
    )
    assert_crew_assignment(accepted)
    assert accepted["role_on_crew"] == "LIFTER"
    assert accepted["status"] == "INVITED"

    crew_rows, _ = validate_paginated(api.list_run_crew(run["id"], DISPATCH))
    assert len(crew_rows) == 1, "only the LIFTER seat was created"


def test_dispatch_marks_the_still_invited_crew_member_as_a_no_show(api):
    """PRD §3.7: "And every crew assignment on the run still sitting in
    `INVITED` at that moment moves `INVITED → NO_SHOW`, deducting 15.0 points
    from that volunteer's `reliability_score` with the result floored at 0.0 and
    bumping each assignment's `version`."
    PRD §3.7: "Every inventory unit sitting in `RESERVED` for a voucher with a
    `SCHEDULED` stop on this run moves `RESERVED → STAGED`, bumping each unit's
    `version`."

    Design: Corner/state_machines/corner_dispatch_marks_still_invited_crew_as_no_show
    """
    set_clock("2026-08-04T09:00:00Z")
    scenario = setup_allocated_voucher(
        lines=[voucher_line_payload("BED", 1, "B")],
        offer_items=[donation_item_payload("BED", "B", False, 30.0)],
        truck_label="BOX-24", agency_name="Marlow Bridge Aid",
    )
    driver = create_volunteer(name="Devon Marsh", county="CENTRAL",
                              lift_certified=True)
    lifter = create_volunteer(name="Lena Fischer", county="CENTRAL",
                              lift_certified=False)
    run = create_run(scenario["truck"]["id"], service_date="2026-08-05",
                     window_start="2026-08-05T09:00:00Z",
                     window_end="2026-08-05T17:00:00Z", county="CENTRAL")
    book_stop(run["id"], scenario["voucher"]["id"], 1, run["version"])
    driver_seat = invite_crew(run["id"], driver["id"], "DRIVER")
    lifter_seat = invite_crew(run["id"], lifter["id"], "LIFTER")
    respond_crew(driver_seat["id"], driver["id"], "CONFIRM")

    dispatched = dispatch_run(run["id"])
    assert dispatched["status"] == "DISPATCHED"

    lifter_now = get_crew_assignment(run["id"], lifter_seat["id"])
    driver_now = get_crew_assignment(run["id"], driver_seat["id"])
    assert lifter_now["status"] == "NO_SHOW", "the unanswered invitation is marked absent"
    assert driver_now["status"] == "CONFIRMED"

    lifter_row = validate_success(api.get_volunteer(lifter["id"], DISPATCH))
    driver_row = validate_success(api.get_volunteer(driver["id"], DISPATCH))
    assert lifter_row["reliability_score"] == pytest.approx(85.0, abs=0.001)
    assert lifter_row["assigned_hours_month"] == pytest.approx(0.0, abs=0.001)
    assert driver_row["reliability_score"] == pytest.approx(100.0, abs=0.001)
    assert driver_row["assigned_hours_month"] == pytest.approx(4.0, abs=0.001)

    staged, _ = validate_paginated(
        api.list_inventory_items(WAREHOUSE, {"status": "STAGED", "limit": 100})
    )
    assert len(staged) == 1, "the reserved BED is staged onto the truck"


# ─── Corner: the dispatch gates ────────────────────────────────────────

def test_dispatch_reports_crew_below_minimum_and_run_invalid_state_separately(api):
    """PRD §3.7: "The state gate accepts a run in `PLANNED` or `CREWED` and
    refuses a run in `DISPATCHED`, `COMPLETED` or `CANCELLED` with
    `ERR_RUN_INVALID_STATE`; a run carrying zero `SCHEDULED` stops is likewise
    refused with `ERR_RUN_INVALID_STATE`. A run that passes the state gate while
    still in `PLANNED` then always fails the crew gate with
    `ERR_CREW_BELOW_MINIMUM`, which is precisely how that rejection becomes
    observable."

    Design: Corner/validations/corner_dispatch_reports_crew_below_minimum_then_run_invalid_state_without_stops
    """
    set_clock("2026-08-04T09:00:00Z")
    scenario = setup_allocated_voucher(
        lines=[voucher_line_payload("BED", 1, "B")],
        offer_items=[donation_item_payload("BED", "B", False, 30.0)],
        truck_label="BOX-43", agency_name="Glenmore Aid Society",
    )
    loaded_run = create_run(scenario["truck"]["id"], service_date="2026-08-05",
                            window_start="2026-08-05T09:00:00Z",
                            window_end="2026-08-05T17:00:00Z", county="CENTRAL")
    stop = book_stop(loaded_run["id"], scenario["voucher"]["id"], 1,
                     loaded_run["version"])
    empty_run = create_run(scenario["truck"]["id"], service_date="2026-08-06",
                           window_start="2026-08-06T09:00:00Z",
                           window_end="2026-08-06T17:00:00Z", county="CENTRAL")

    crew_refusal = api.dispatch_delivery_run(loaded_run["id"], DISPATCH)
    validate_error(crew_refusal, ApiErrorId.ERR_CREW_BELOW_MINIMUM.value, 409)

    state_refusal = api.dispatch_delivery_run(empty_run["id"], DISPATCH)
    validate_error(state_refusal, ApiErrorId.ERR_RUN_INVALID_STATE.value, 409)

    assert get_run(loaded_run["id"])["status"] == "PLANNED"
    assert get_run(empty_run["id"])["status"] == "PLANNED"
    assert get_stop(loaded_run["id"], stop["id"])["status"] == "SCHEDULED"

    staged, _ = validate_paginated(
        api.list_inventory_items(WAREHOUSE, {"status": "STAGED", "limit": 100})
    )
    assert staged == [], "neither refused dispatch stages anything"


def test_dispatch_is_refused_when_the_load_exceeds_the_truck_capacity(api):
    """PRD §3.7: "Beyond those, the truck must not be locked out —
    `bed_bug_lockout_until` null or no later than the run's `window_start`,
    otherwise `ERR_TRUCK_BED_BUG_LOCKOUT` — and the load must fit, otherwise
    `ERR_TRUCK_CAPACITY_EXCEEDED`."
    PRD §3.7: "`load_cubic_feet` is the sum of `cubic_feet` over every inventory
    unit whose `status` is `RESERVED` or `STAGED` and whose
    `reserved_for_voucher_line_id` points at a line of a voucher served by a
    `SCHEDULED` stop on this run — so a stop cancelled by the cascade drops out
    of the sum immediately."

    Design: Corner/errors/corner_truck_capacity_exceeded_at_dispatch
    """
    set_clock("2026-08-04T09:00:00Z")
    scenario = setup_allocated_voucher(
        lines=[voucher_line_payload("BED", 1, "B"),
               voucher_line_payload("DRESSER", 1, "B")],
        categories=["BED", "DRESSER"],
        offer_items=[donation_item_payload("BED", "B", False, 30.0),
                     donation_item_payload("DRESSER", "B", False, 25.0)],
        truck_label="BOX-54", truck_capacity=40.0,
        agency_name="Underhill Relief Board",
    )
    booked = setup_crewed_run(scenario["truck"]["id"], scenario["voucher"]["id"],
                              volunteer_name="Gil Baptiste")
    assert booked["run"]["load_cubic_feet"] == pytest.approx(55.0, abs=0.001)

    response = api.dispatch_delivery_run(booked["run"]["id"], DISPATCH)
    validate_error(response, ApiErrorId.ERR_TRUCK_CAPACITY_EXCEEDED.value, 422)

    run_now = validate_success(api.get_delivery_run(booked["run"]["id"], DISPATCH))
    assert run_now["status"] == "CREWED"
    assert run_now["load_cubic_feet"] == pytest.approx(55.0, abs=0.001)

    staged, _ = validate_paginated(
        api.list_inventory_items(WAREHOUSE, {"status": "STAGED", "limit": 100})
    )
    assert staged == []
    reserved, _ = validate_paginated(
        api.list_inventory_items(WAREHOUSE, {"status": "RESERVED", "limit": 100})
    )
    assert len(reserved) == 2, "both units stay merely reserved"


# ─── Corner: stop booking guards ───────────────────────────────────────

def test_duplicate_routing_sequence_on_one_run_is_refused(api):
    """PRD §3.7: "A planner books a voucher onto a run by supplying the
    `voucher_id`, a routing `sequence` of at least 1 and at most 40 that must be
    unique among that run's `SCHEDULED` stops, and `expected_run_version`."
    PRD §3.7: "A duplicate `sequence` is rejected with
    `ERR_STOP_SEQUENCE_CONFLICT`."

    Design: Corner/validations/corner_stop_sequence_collision_on_same_run_rejected
    """
    set_clock("2026-08-04T09:00:00Z")
    agency = create_agency(name="Northgate Household Aid", county="CENTRAL",
                           quarterly_voucher_quota=5)
    household_one = create_client(agency["id"], household_size=4, county="CENTRAL")
    household_two = create_client(agency["id"], household_size=4, county="CENTRAL")
    referral_one = create_approved_referral(agency["id"], household_one["id"],
                                            requested_categories=["BED"])
    voucher_one = issue_voucher(agency["id"], referral_one["id"],
                                [voucher_line_payload("BED", 1, "B")])
    referral_two = create_approved_referral(agency["id"], household_two["id"],
                                            requested_categories=["BED"])
    voucher_two = issue_voucher(agency["id"], referral_two["id"],
                                [voucher_line_payload("BED", 1, "B")])

    truck = create_truck(label="BOX-45", capacity_cubic_feet=600,
                         home_county="CENTRAL", crew_minimum=1)
    supply_clean_stock(
        truck["id"], [donation_item_payload("BED", "B", False, 30.0)] * 2,
        donor_name="Orla Byrne", donor_phone="555-0731",
    )
    allocate(voucher_one["id"], voucher_one["version"])
    allocate(voucher_two["id"], voucher_two["version"])

    run = create_run(truck["id"], service_date="2026-08-05",
                     window_start="2026-08-05T09:00:00Z",
                     window_end="2026-08-05T17:00:00Z", county="CENTRAL")
    first_stop = book_stop(run["id"], voucher_one["id"], 1, run["version"])
    current_run = get_run(run["id"])

    response = api.create_delivery_stop(
        run["id"],
        delivery_stop_payload(voucher_two["id"], 1, current_run["version"]),
        DISPATCH,
    )
    validate_error(response, ApiErrorId.ERR_STOP_SEQUENCE_CONFLICT.value, 409)

    run_now = validate_success(api.get_delivery_run(run["id"], DISPATCH))
    assert run_now["stop_count"] == 1
    stops, _ = validate_paginated(api.list_run_stops(run["id"], DISPATCH))
    assert len(stops) == 1 and stops[0]["id"] == first_stop["id"]
    assert stops[0]["sequence"] == 1

    voucher_two_now = validate_success(api.get_voucher(voucher_two["id"], ADMIN))
    assert voucher_two_now["status"] == "ALLOCATED", "the refused booking changes nothing"


def test_underfilled_voucher_below_the_scheduling_floor_is_refused(api):
    """PRD §3.7: "A voucher in `PARTIALLY_ALLOCATED` may also be booked, moving
    `PARTIALLY_ALLOCATED → SCHEDULED`, but only when its `fill_ratio` is at
    least 0.5 — a half-empty truckload is worth a trip, a nearly empty one is
    not, and anything below that inclusive floor is rejected with
    `ERR_VOUCHER_UNDERFILLED`."
    PRD §3.6: "A voucher's `fill_ratio` is the sum of `quantity_allocated`
    across its lines divided by the sum of `quantity_requested` across its
    lines, carried to three decimals."

    Design: Corner/validations/corner_partially_allocated_voucher_below_half_fill_rejected_for_scheduling
    """
    set_clock("2026-08-04T09:00:00Z")
    scenario = setup_allocated_voucher(
        lines=[voucher_line_payload("BED", 3, "B")],
        offer_items=[donation_item_payload("BED", "B", False, 30.0)],
        truck_label="BOX-40", agency_name="Fernhill Support",
    )
    assert scenario["allocated"]["fill_ratio"] == pytest.approx(0.333, abs=0.0005)
    assert scenario["allocated"]["status"] == "PARTIALLY_ALLOCATED"

    run = create_run(scenario["truck"]["id"], service_date="2026-08-05",
                     window_start="2026-08-05T09:00:00Z",
                     window_end="2026-08-05T17:00:00Z", county="CENTRAL")

    response = api.create_delivery_stop(
        run["id"],
        delivery_stop_payload(scenario["voucher"]["id"], 1, run["version"]),
        DISPATCH,
    )
    validate_error(response, ApiErrorId.ERR_VOUCHER_UNDERFILLED.value, 422)

    voucher_now = validate_success(api.get_voucher(scenario["voucher"]["id"], ADMIN))
    assert voucher_now["status"] == "PARTIALLY_ALLOCATED"

    run_now = validate_success(api.get_delivery_run(run["id"], DISPATCH))
    assert run_now["stop_count"] == 0
    assert run_now["version"] == run["version"], "the refused booking bumps no version"


def test_banned_household_cannot_be_booked_onto_a_new_run(api):
    """PRD §3.7: "The household must be eligible: its `status` must be `ACTIVE`,
    its `bed_bug_status` must not be `CONFIRMED`, and its `delivery_ban_until`
    must be null or no later than the current instant, otherwise
    `ERR_CLIENT_DELIVERY_BANNED`."
    PRD §3.8: "Step two fires only when that raised count reaches 2: the
    household's `status` becomes `ON_HOLD` and its `delivery_ban_until` is set
    to the current instant plus 90 days."

    Design: Corner/validations/corner_banned_household_cannot_be_booked_onto_a_new_run
    """
    set_clock("2026-08-04T09:00:00Z")
    scenario = setup_banned_household(truck_label_prefix="BOX-48")

    household = validate_success(api.get_client(scenario["client"]["id"], ADMIN))
    assert household["no_show_strikes"] == 2
    assert household["status"] == "ON_HOLD"
    assert household["bed_bug_status"] == "CLEAR", (
        "the household is banned, not bed-bug blocked"
    )
    assert household["delivery_ban_until"] == "2026-11-02T09:00:00.000Z"

    third_run = create_run(scenario["truck"]["id"], service_date="2026-08-07",
                           window_start="2026-08-07T09:00:00Z",
                           window_end="2026-08-07T17:00:00Z", county="CENTRAL")
    response = api.create_delivery_stop(
        third_run["id"],
        delivery_stop_payload(scenario["voucher"]["id"], 1, third_run["version"]),
        DISPATCH,
    )
    validate_error(response, ApiErrorId.ERR_CLIENT_DELIVERY_BANNED.value, 422)

    voucher_now = validate_success(api.get_voucher(scenario["voucher"]["id"], ADMIN))
    assert voucher_now["status"] == "ALLOCATED"
    assert get_run(third_run["id"])["stop_count"] == 0

    agency_now = validate_success(api.get_agency(scenario["agency"]["id"], ADMIN))
    assert agency_now["no_show_credits_owed_cents"] == 2250, (
        "two no-shows at 1125 cents each accumulate on the agency ledger"
    )


# ─── Difficulty: the inclusive capacity boundary ───────────────────────

def test_dispatch_succeeds_when_the_load_exactly_equals_the_capacity(api):
    """PRD §3.7: "A run is feasible to dispatch when `stop_count` is at least 1,
    `load_cubic_feet` is no greater than the truck's `capacity_cubic_feet`,
    `confirmed_crew_count` is at least the truck's `crew_minimum`, and
    `has_confirmed_driver` is true. Both numeric comparisons are inclusive: a
    load exactly equal to capacity passes, and a confirmed crew exactly equal to
    the minimum passes."

    Design: Difficulty/boundary_precision_check/dispatch_allowed_when_load_exactly_equals_truck_capacity
    """
    set_clock("2026-08-04T09:00:00Z")
    scenario = setup_allocated_voucher(
        lines=[voucher_line_payload("BED", 1, "B"),
               voucher_line_payload("DRESSER", 1, "B")],
        categories=["BED", "DRESSER"],
        offer_items=[donation_item_payload("BED", "B", False, 30.0),
                     donation_item_payload("DRESSER", "B", False, 25.0)],
        truck_label="BOX-8", truck_capacity=55.0,
        agency_name="Harbor Point Services",
    )
    booked = setup_crewed_run(scenario["truck"]["id"], scenario["voucher"]["id"],
                              volunteer_name="Cyrus Mbeki")
    assert booked["run"]["status"] == "CREWED"

    dispatched = validate_success(
        api.dispatch_delivery_run(booked["run"]["id"], DISPATCH), 200
    )

    assert dispatched["status"] == "DISPATCHED", (
        "a load exactly equal to capacity passes the inclusive comparison"
    )
    assert dispatched["load_cubic_feet"] == pytest.approx(55.0, abs=0.001)
    assert dispatched["confirmed_crew_count"] == 1
    assert dispatched["has_confirmed_driver"] is True


def test_boundary_dispatch_stages_the_stock_and_quotes_the_provisional_fee(api):
    """PRD §3.7: "Every inventory unit sitting in `RESERVED` for a voucher with
    a `SCHEDULED` stop on this run moves `RESERVED → STAGED`, bumping each
    unit's `version`."
    PRD §3.9: "Second, a bulk charge is added: the total `cubic_feet` of the
    basis is divided by 50, that quotient is rounded **up** to a whole number,
    and the result is multiplied by 1200 cents — so a basis of zero cubic feet
    adds nothing, a basis of 50 cubic feet adds one increment, and a basis of 51
    adds two."

    Design: Difficulty/boundary_precision_check/dispatch_allowed_when_load_exactly_equals_truck_capacity
    """
    set_clock("2026-08-04T09:00:00Z")
    scenario = setup_allocated_voucher(
        lines=[voucher_line_payload("BED", 1, "B"),
               voucher_line_payload("DRESSER", 1, "B")],
        categories=["BED", "DRESSER"],
        offer_items=[donation_item_payload("BED", "B", False, 30.0),
                     donation_item_payload("DRESSER", "B", False, 25.0)],
        truck_label="BOX-8", truck_capacity=55.0,
        agency_name="Harbor Point Services",
    )
    assert scenario["allocated"]["gross_fee_cents"] == 6900, (
        "CENTRAL 3000 plus two bulk increments of 1200 plus the 1500 lift surcharge"
    )
    assert scenario["allocated"]["client_due_cents"] == 2070

    booked = setup_crewed_run(scenario["truck"]["id"], scenario["voucher"]["id"],
                              volunteer_name="Cyrus Mbeki")
    dispatch_run(booked["run"]["id"])

    staged, _ = validate_paginated(
        api.list_inventory_items(WAREHOUSE, {"status": "STAGED", "limit": 100})
    )
    assert len(staged) == 2, f"both reserved units are staged, got {len(staged)}"
    reserved, _ = validate_paginated(
        api.list_inventory_items(WAREHOUSE, {"status": "RESERVED", "limit": 100})
    )
    assert reserved == []


# ─── Difficulty: the volunteer's closed-interval rest buffer ───────────

def test_gap_of_exactly_sixty_minutes_still_conflicts(api):
    """PRD §3.7: "The buffer is applied on a closed interval — a conflict exists
    when the new run's `window_start` is at or before the other run's
    `window_end` plus 60 minutes *and* the other run's `window_start` is at or
    before the new run's `window_end` plus 60 minutes — so a gap of exactly 60
    minutes still conflicts while a gap of 61 minutes does not, and the
    rejection is `ERR_VOLUNTEER_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/volunteer_rest_buffer_closed_interval_sixty_minutes_conflicts
    """
    scenario = _volunteer_with_three_candidate_runs()

    response = api.create_crew_assignment(
        scenario["run_two"]["id"],
        crew_assignment_payload(scenario["volunteer"]["id"], "LIFTER"),
        DISPATCH,
    )
    validate_error(response, ApiErrorId.ERR_VOLUNTEER_WINDOW_CONFLICT.value, 409)

    assignment_now = get_crew_assignment(scenario["run_one"]["id"],
                                         scenario["assignment"]["id"])
    assert assignment_now["status"] == "INVITED"

    run_two_now = validate_success(
        api.get_delivery_run(scenario["run_two"]["id"], DISPATCH)
    )
    assert run_two_now["confirmed_crew_count"] == 0


def test_gap_of_sixty_one_minutes_clears_the_rest_buffer(api):
    """PRD §3.7: "The volunteer must be rested: they must not already hold an
    assignment in `INVITED` or `CONFIRMED` on another run whose `status` is
    `PLANNED`, `CREWED` or `DISPATCHED` and whose window comes within one hour
    of the new run's window."
    PRD §3.7: "The buffer is applied on a closed interval — a conflict exists
    when the new run's `window_start` is at or before the other run's
    `window_end` plus 60 minutes *and* the other run's `window_start` is at or
    before the new run's `window_end` plus 60 minutes — so a gap of exactly 60
    minutes still conflicts while a gap of 61 minutes does not, and the
    rejection is `ERR_VOLUNTEER_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/volunteer_rest_buffer_closed_interval_sixty_minutes_conflicts
    """
    scenario = _volunteer_with_three_candidate_runs()

    api.create_crew_assignment(
        scenario["run_two"]["id"],
        crew_assignment_payload(scenario["volunteer"]["id"], "LIFTER"),
        DISPATCH,
    )

    accepted = validate_success(
        api.create_crew_assignment(
            scenario["run_three"]["id"],
            crew_assignment_payload(scenario["volunteer"]["id"], "LIFTER"),
            DISPATCH,
        ),
        201,
    )
    assert accepted["status"] == "INVITED", "a 61-minute gap clears the rest buffer"

    held, meta = validate_paginated(
        api.list_volunteer_crew_assignments(
            scenario["volunteer"]["id"],
            make_volunteer_headers(scenario["volunteer"]["id"]),
            {"limit": 100},
        )
    )
    assert len(held) == 2, (
        f"only the first run and the 61-minute run hold seats, got {len(held)}"
    )
    assert {row["run_id"] for row in held} == {
        scenario["run_one"]["id"], scenario["run_three"]["id"]
    }
