"""Warehouse grading, the quarantine protocol and the bed-bug contagion chain."""

import pytest

from test_helpers import (
    ADMIN,
    DISPATCH,
    WAREHOUSE,
    WAREHOUSE_INSPECTOR_ID,
    WAREHOUSE_RELEASER_ID,
    ApiErrorId,
    allocate,
    book_stop,
    create_run,
    create_truck,
    create_volunteer,
    donation_item_payload,
    get_crew_assignment,
    get_stop,
    invite_crew,
    list_donation_items,
    list_inventory,
    make_warehouse_lead_headers,
    prepare_offer_for_intake,
    respond_crew,
    run_intake,
    set_clock,
    setup_issued_voucher,
    setup_quarantined_offer,
    supply_clean_stock,
    validate_error,
    validate_paginated,
    validate_success,
    voucher_line_payload,
)
from test_helpers.assertions import assert_donation_offer, assert_inventory_item


def _live_pest_cascade_scenario(run_service_date, run_window_start, run_window_end):
    """A clean BED allocated onto a crewed run, then a second offer on the same
    truck inspected with a live pest.  Returns every entity the cascade touches."""
    set_clock("2026-08-04T07:00:00Z")
    scenario = setup_issued_voucher(
        lines=[voucher_line_payload("BED", 1, "B")],
        agency_name="Cedar Hollow Services",
    )
    truck = create_truck(label="BOX-CASCADE", capacity_cubic_feet=600,
                         home_county="CENTRAL", crew_minimum=1)
    supply_clean_stock(
        truck["id"], [donation_item_payload("BED", "B", False, 30.0)],
        donor_name="Grace Lin", donor_phone="555-0166",
        window_start="2026-08-04T08:00:00Z", window_end="2026-08-04T09:00:00Z",
    )
    allocate(scenario["voucher"]["id"], scenario["voucher"]["version"])
    reserved_bed = list_inventory(status="RESERVED", category="BED")[0]

    volunteer = create_volunteer(name="Sam Ortega", county="CENTRAL",
                                 lift_certified=True)
    run = create_run(truck["id"], service_date=run_service_date,
                     window_start=run_window_start, window_end=run_window_end,
                     county="CENTRAL")
    stop = book_stop(run["id"], scenario["voucher"]["id"], 1, run["version"])
    crew = invite_crew(run["id"], volunteer["id"], "DRIVER")
    respond_crew(crew["id"], volunteer["id"], "CONFIRM")

    pest_offer = prepare_offer_for_intake(
        truck["id"], [donation_item_payload("DRESSER", "B", False, 20.0)],
        donor_name="Ruth Alvarez", donor_phone="555-0177",
        window_start="2026-08-04T13:00:00Z", window_end="2026-08-04T15:00:00Z",
    )

    set_clock("2026-08-04T16:00:00Z")
    quarantined = run_intake(
        pest_offer["offer"]["id"], pest_offer["items"],
        grades=["B"], pest_flags=[True], inspector="wl-inspector-2",
    )

    scenario.update({
        "truck": truck, "volunteer": volunteer, "run": run, "stop": stop,
        "crew": crew, "reserved_bed": reserved_bed, "pest_offer": quarantined,
    })
    return scenario


# ─── Corner: minting stock from the inspection ─────────────────────────

def test_minted_stock_copies_category_volume_and_the_graded_condition(api):
    """PRD §3.5: "Grading is what mints warehouse stock. Every inspection graded
    `A`, `B` or `C` produces one `InventoryItem`, which copies its `category`
    and its `cubic_feet` from the originating piece, copies the assigned
    `graded_condition` into its own `condition`, and records the piece it came
    from in `donation_item_id`."
    PRD §3.5: "On the **clean branch** — no inspection reported
    `live_pest_observed` true *and* no accepted piece on the offer has
    `soft_surface` true — the offer moves `PICKUP_SCHEDULED → INSPECTED` and
    every minted unit is created directly in `status` `AVAILABLE` with its
    `available_since` set to the current instant and its
    `reserved_for_voucher_line_id` null."
    PRD §3.5: "Every inspection also stamps the offer's `inspector_user_id` with
    the acting `X-User-ID`, which is what the segregation-of-duties rule will
    later compare against."

    Design: Corner/entities/corner_inventory_item_copies_category_condition_and_volume_from_donation_item
    """
    set_clock("2026-08-04T09:00:00Z")
    truck = create_truck(label="BOX-20", capacity_cubic_feet=600,
                         home_county="CENTRAL", crew_minimum=1)
    prepared = prepare_offer_for_intake(
        truck["id"], [donation_item_payload("DRESSER", "B", False, 18.0)],
        donor_name="Hana Ito", donor_phone="555-0401",
    )
    piece = prepared["items"][0]

    inspected = run_intake(prepared["offer"]["id"], prepared["items"], grades=["C"])

    assert_donation_offer(inspected)
    assert inspected["status"] == "INSPECTED"
    assert inspected["inspector_user_id"] == WAREHOUSE_INSPECTOR_ID

    units = list_inventory(donation_item_id=piece["id"])
    assert len(units) == 1, f"one A/B/C grade mints one unit, got {len(units)}"
    unit = units[0]
    assert_inventory_item(unit)
    assert unit["category"] == "DRESSER", "category is copied from the piece"
    assert unit["condition"] == "C", "condition is the grade the lead assigned"
    assert unit["cubic_feet"] == pytest.approx(18.0, abs=0.001)
    assert unit["status"] == "AVAILABLE"
    assert unit["available_since"] == "2026-08-04T09:00:00.000Z"
    assert unit["reserved_for_voucher_line_id"] is None

    piece_now = list_donation_items(prepared["offer"]["id"])[0]
    assert piece_now["graded_condition"] == "C"


# ─── Corner: quarantine dwell and release ──────────────────────────────

def test_quarantine_release_moves_every_unit_to_available(api):
    """PRD §3.5: "Release moves the offer `QUARANTINED → RELEASED` and moves
    every inventory unit sourced from that offer still sitting in `QUARANTINED`
    to `AVAILABLE`, restamping each unit's `available_since` to the release
    instant and bumping each unit's `version` along with the offer's."
    PRD §3.5: "The offer's `quarantine_started_at` is set to the current
    instant, and `quarantine_release_due_at` is set to that instant plus 21 days
    when a live pest fired anywhere on the offer, or plus 14 days when the risk
    came only from upholstery."

    Design: Corner/state_machines/corner_quarantine_release_moves_every_unit_to_available
    """
    set_clock("2026-08-04T09:00:00Z")
    truck = create_truck(label="BOX-26", capacity_cubic_feet=600,
                         home_county="CENTRAL", crew_minimum=1)
    supply = setup_quarantined_offer(
        truck["id"], donor_name="Ulla Nyberg", donor_phone="555-0541"
    )
    offer = supply["offer"]

    assert offer["status"] == "QUARANTINED"
    assert offer["quarantine_started_at"] == "2026-08-04T09:00:00.000Z"
    assert offer["quarantine_release_due_at"] == "2026-08-18T09:00:00.000Z", (
        "upholstery-only risk carries the 14-day dwell"
    )
    assert offer["bed_bug_risk_score"] == pytest.approx(50.0, abs=0.05), (
        "40 of the 80 accepted cubic feet are upholstered"
    )

    set_clock("2026-08-18T09:00:00Z")
    released = validate_success(
        api.release_quarantine(offer["id"],
                               make_warehouse_lead_headers(WAREHOUSE_RELEASER_ID))
    )
    assert released["status"] == "RELEASED"

    available, _ = validate_paginated(
        api.list_inventory_items(WAREHOUSE, {"status": "AVAILABLE", "limit": 100})
    )
    assert len(available) == 3, f"all three units reach the floor, got {len(available)}"
    still_quarantined, _ = validate_paginated(
        api.list_inventory_items(WAREHOUSE, {"status": "QUARANTINED", "limit": 100})
    )
    assert still_quarantined == []
    for unit in available:
        assert unit["available_since"] == "2026-08-18T09:00:00.000Z", (
            "available_since is restamped to the release instant"
        )


def test_quarantine_release_before_the_dwell_elapses_is_refused(api):
    """PRD §3.5: "the current instant must be at or after
    `quarantine_release_due_at`, otherwise `ERR_QUARANTINE_NOT_ELAPSED`; and the
    acting `X-User-ID` must differ from the offer's stored `inspector_user_id`,
    otherwise `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/validations/corner_quarantine_release_before_dwell_elapsed_rejected
    """
    set_clock("2026-08-04T09:00:00Z")
    truck = create_truck(label="BOX-44", capacity_cubic_feet=600,
                         home_county="CENTRAL", crew_minimum=1)
    supply = setup_quarantined_offer(
        truck["id"], donor_name="Jonas Weber", donor_phone="555-0721"
    )
    assert supply["offer"]["quarantine_release_due_at"] == "2026-08-18T09:00:00.000Z"

    set_clock("2026-08-17T09:00:00Z")
    response = api.release_quarantine(
        supply["offer"]["id"], make_warehouse_lead_headers(WAREHOUSE_RELEASER_ID)
    )
    validate_error(response, ApiErrorId.ERR_QUARANTINE_NOT_ELAPSED.value, 409)

    offer_now = validate_success(api.get_donation_offer(supply["offer"]["id"], WAREHOUSE))
    assert offer_now["status"] == "QUARANTINED"
    quarantined, _ = validate_paginated(
        api.list_inventory_items(WAREHOUSE, {"status": "QUARANTINED", "limit": 100})
    )
    assert len(quarantined) == 3, "the units stay off the floor"
    available, _ = validate_paginated(
        api.list_inventory_items(WAREHOUSE, {"status": "AVAILABLE", "limit": 100})
    )
    assert available == []


# ─── Difficulty: the five-link live-pest cascade ───────────────────────

def test_live_pest_intake_quarantines_the_offer_and_locks_the_truck(api):
    """PRD §3.5: "On the **risk branch** — at least one inspection reported
    `live_pest_observed` true, *or* at least one accepted piece has
    `soft_surface` true — the offer moves `PICKUP_SCHEDULED → QUARANTINED`."
    PRD §3.5: "The offer's `quarantine_started_at` is set to the current
    instant, and `quarantine_release_due_at` is set to that instant plus 21 days
    when a live pest fired anywhere on the offer, or plus 14 days when the risk
    came only from upholstery."
    PRD §3.5: "**Step 1.** The collecting truck's `bed_bug_lockout_until` is
    stamped with the current instant plus 72 hours, and the truck's `version` is
    bumped by 1."

    Design: Difficulty/transitive_cascade/live_pest_intake_cascades_truck_run_stop_voucher_crew
    """
    scenario = _live_pest_cascade_scenario(
        "2026-08-04", "2026-08-04T18:00:00Z", "2026-08-04T22:00:00Z"
    )

    offer = scenario["pest_offer"]
    assert offer["status"] == "QUARANTINED"
    assert offer["quarantine_started_at"] == "2026-08-04T16:00:00.000Z"
    assert offer["quarantine_release_due_at"] == "2026-08-25T16:00:00.000Z", (
        "a live pest carries the 21-day dwell"
    )

    truck_now = validate_success(api.get_truck(scenario["truck"]["id"], DISPATCH))
    assert truck_now["bed_bug_lockout_until"] == "2026-08-07T16:00:00.000Z", (
        "the lockout is the intake instant plus 72 hours"
    )


def test_live_pest_cascade_cancels_the_run_stop_and_releases_the_crew(api):
    """PRD §3.5: "**Step 2.** Every delivery run on that truck whose `status` is
    `PLANNED` or `CREWED` and whose `service_date` equals the UTC calendar date
    of the current instant is cancelled — the `PLANNED → CANCELLED` and `CREWED
    → CANCELLED` edges — each bumping that run's `version`."
    PRD §3.5: "**Step 3.** Every delivery stop on those cancelled runs whose
    `status` is `SCHEDULED` moves `SCHEDULED → CANCELLED`, with its
    `chargeback_cents` staying at 0 and its `version` bumped."
    PRD §3.5: "**Step 4.** Each of those cancelled stops releases its voucher
    back off the road: the voucher leaves `SCHEDULED` for `ALLOCATED` when every
    one of its lines is fully filled, or for `PARTIALLY_ALLOCATED` when at least
    one line is still short. The reserved stock is retained exactly as it was,
    because the run never dispatched and nothing was ever staged."
    PRD §3.5: "**Step 5.** Every crew assignment on those cancelled runs whose
    `status` is `INVITED` moves `INVITED → RELEASED`, and every one whose
    `status` is `CONFIRMED` moves `CONFIRMED → RELEASED`, the latter also
    returning 4.0 hours to that volunteer's `assigned_hours_month`, floored at
    0.0."

    Design: Difficulty/transitive_cascade/live_pest_intake_cascades_truck_run_stop_voucher_crew
    """
    scenario = _live_pest_cascade_scenario(
        "2026-08-04", "2026-08-04T18:00:00Z", "2026-08-04T22:00:00Z"
    )

    run_now = validate_success(api.get_delivery_run(scenario["run"]["id"], DISPATCH))
    assert run_now["status"] == "CANCELLED", "the same-day run on that truck is cancelled"

    stop_now = get_stop(scenario["run"]["id"], scenario["stop"]["id"])
    assert stop_now["status"] == "CANCELLED"
    assert stop_now["chargeback_cents"] == 0, "a cascade cancellation bills nothing"

    voucher_now = validate_success(api.get_voucher(scenario["voucher"]["id"], ADMIN))
    assert voucher_now["status"] == "ALLOCATED", (
        "every line is filled, so the voucher falls back to ALLOCATED"
    )

    crew_now = get_crew_assignment(scenario["run"]["id"], scenario["crew"]["id"])
    assert crew_now["status"] == "RELEASED"

    volunteer_now = validate_success(
        api.get_volunteer(scenario["volunteer"]["id"], DISPATCH)
    )
    assert volunteer_now["assigned_hours_month"] == pytest.approx(0.0, abs=0.001), (
        "the released confirmation returns its 4.0 hours"
    )
    assert volunteer_now["reliability_score"] == pytest.approx(100.0, abs=0.001), (
        "a cascade release is not a no-show"
    )

    bed_now = validate_success(
        api.get_inventory_item(scenario["reserved_bed"]["id"], WAREHOUSE)
    )
    assert bed_now["status"] == "RESERVED", "the reserved stock is retained as it was"


# ─── Difficulty: dispatch gated by the truck's lockout row ─────────────

def test_run_on_a_later_service_date_survives_the_cascade_with_the_lockout_stamped(api):
    """PRD §3.5: "Runs on later dates that still fall inside the lockout window
    are deliberately **not** cancelled; they survive but cannot be dispatched
    until the lockout lapses, and an attempt to dispatch them earlier is refused
    with `ERR_TRUCK_BED_BUG_LOCKOUT`."
    PRD §3.5: "**Step 1.** The collecting truck's `bed_bug_lockout_until` is
    stamped with the current instant plus 72 hours, and the truck's `version` is
    bumped by 1."

    Design: Difficulty/cross_entity_state_dependency/run_dispatch_gated_by_truck_bed_bug_lockout_state
    """
    scenario = _live_pest_cascade_scenario(
        "2026-08-06", "2026-08-06T09:00:00Z", "2026-08-06T17:00:00Z"
    )

    assert scenario["pest_offer"]["status"] == "QUARANTINED"
    truck_now = validate_success(api.get_truck(scenario["truck"]["id"], DISPATCH))
    assert truck_now["bed_bug_lockout_until"] == "2026-08-07T16:00:00.000Z"

    run_now = validate_success(api.get_delivery_run(scenario["run"]["id"], DISPATCH))
    assert run_now["status"] == "CREWED", (
        "the run's service date is not the intake date, so it is not cancelled"
    )
    assert run_now["stop_count"] == 1

    stop_now = get_stop(scenario["run"]["id"], scenario["stop"]["id"])
    assert stop_now["status"] == "SCHEDULED"


def test_dispatch_of_a_locked_out_truck_is_refused(api):
    """PRD §3.7: "Beyond those, the truck must not be locked out —
    `bed_bug_lockout_until` null or no later than the run's `window_start`,
    otherwise `ERR_TRUCK_BED_BUG_LOCKOUT` — and the load must fit, otherwise
    `ERR_TRUCK_CAPACITY_EXCEEDED`."
    PRD §3.7: "Dispatch has two cascading effects beyond the run's own state
    change. Every inventory unit sitting in `RESERVED` for a voucher with a
    `SCHEDULED` stop on this run moves `RESERVED → STAGED`, bumping each unit's
    `version`."

    Design: Difficulty/cross_entity_state_dependency/run_dispatch_gated_by_truck_bed_bug_lockout_state
    """
    scenario = _live_pest_cascade_scenario(
        "2026-08-06", "2026-08-06T09:00:00Z", "2026-08-06T17:00:00Z"
    )

    response = api.dispatch_delivery_run(scenario["run"]["id"], DISPATCH)
    validate_error(response, ApiErrorId.ERR_TRUCK_BED_BUG_LOCKOUT.value, 409)

    run_now = validate_success(api.get_delivery_run(scenario["run"]["id"], DISPATCH))
    assert run_now["status"] == "CREWED", "the refused dispatch leaves the run crewed"

    reserved, _ = validate_paginated(
        api.list_inventory_items(WAREHOUSE, {"status": "RESERVED", "limit": 100})
    )
    assert len(reserved) == 1, "the BED is still merely reserved"
    staged, _ = validate_paginated(
        api.list_inventory_items(WAREHOUSE, {"status": "STAGED", "limit": 100})
    )
    assert staged == [], "a refused dispatch stages nothing"
