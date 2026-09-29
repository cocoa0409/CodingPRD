"""Computed reads: the input sets they evaluate and the ladders they walk.

None of these reads persist anything, so each one is exercised by moving the
underlying rows and re-reading, proving the figure is derived at read time from a
precisely specified input set rather than patched incrementally.
"""

import pytest

from test_helpers import (
    MANAGER,
    SAFETY_OFFICER,
    api_client,
    assert_bulletin,
    assert_bulletin_action,
    assert_bulletin_risk_shape,
    assert_capacity_impact_shape,
    assert_downtime_event,
    assert_instant_equals,
    assert_operator_certification,
    assert_work_order,
    assert_work_order_cost_chain,
    factories,
    fixtures,
    validate_success,
)

CLOCK_START = "2026-08-01T00:00:00.000Z"


def _two_filter_units_under_one_advisory():
    """Two identical FAMILY units under one acknowledged ADVISORY bulletin."""
    units = [
        fixtures.create_attraction(
            name=name,
            park_area="KIDS_COVE",
            manufacturer="Chance",
            model_code="RS-4",
            ride_class="FAMILY",
            theoretical_hourly_capacity=500,
            min_operators_required=1,
            parts_budget_cents=1000000,
        )
        for name in ("Filter Unit One", "Filter Unit Two")
    ]
    return fixtures.acknowledged_bulletin_with_actions(
        bulletin_ref="BR-FILT-1",
        manufacturer="Chance",
        model_code="RS-4",
        severity="ADVISORY",
        attractions=units,
        issued_date="2026-07-01",
        compliance_deadline_date="2026-12-01",
    )


def test_fleet_risk_evaluates_only_the_outstanding_actions():
    """A verified action leaves the evaluated set, taking its score with it.

    PRD §3.6: "That set is every fleet action of the bulletin whose `status` is
    `PENDING`, `IN_WORK` or `DEFERRED`; actions in `VERIFIED` and `CANCELLED` are
    excluded from both figures."
    PRD §3.6: "The severity base comes from the parent bulletin's `severity`: 10 for
    `ADVISORY`, 40 for `MANDATORY`, 70 for `RECALL`. The ride-class factor comes from
    the action's attraction's `ride_class`: 0.6 for `KIDDIE`, 0.8 for `FAMILY`, 1.0
    for `WATER`, 1.2 for `THRILL`. The status factor comes from the action's own
    `status`: 1.0 for `PENDING`, 0.6 for `IN_WORK`, 1.4 for `DEFERRED`".

    Design: Corner/calculations/bulletin_risk_excludes_verified_and_cancelled_actions_from_both_variants
    """
    bundle = _two_filter_units_under_one_advisory()
    first, second = bundle["actions"]
    assert_bulletin_action(first)
    assert first["required_part_received"] is True

    fixtures.start_action(first["id"])
    verified = fixtures.verify_action(first["id"])
    assert verified["status"] == "VERIFIED"
    assert verified["required_part_received"] is True
    assert_instant_equals(verified["verified_at"], CLOCK_START, "verified_at")

    bulletin = validate_success(
        api_client.get_bulletin(bundle["bulletin"]["id"], MANAGER)
    )
    assert_bulletin(bulletin)
    assert bulletin["status"] == "ACKNOWLEDGED"
    assert bulletin["action_total_count"] == 2
    assert bulletin["action_verified_count"] == 1

    still_pending = validate_success(
        api_client.get_bulletin_action(second["id"], MANAGER)
    )
    assert still_pending["status"] == "PENDING"

    risk = validate_success(
        api_client.get_bulletin_risk(bundle["bulletin"]["id"], MANAGER)
    )
    assert_bulletin_risk_shape(risk)
    assert risk["evaluated_action_count"] == 1
    assert risk["deferred_action_count"] == 0
    assert risk["escalation_factor"] == pytest.approx(1.00, abs=0.01)
    assert risk["fleet_aggregate_score"] == pytest.approx(8.00, abs=0.01)
    assert risk["per_unit_max_score"] == pytest.approx(8.00, abs=0.01)
    assert risk["divergence"] == pytest.approx(0.00, abs=0.01)


def _two_closed_events_on_consecutive_service_dates():
    """One peak-hour event on 2026-08-09 and one off-peak event on 2026-08-10."""
    fixtures.set_clock("2026-08-10T20:00:00.000Z")
    attraction = fixtures.create_attraction(
        name="Window Filter Ride",
        park_area="SKYLINE",
        manufacturer="Intamin",
        model_code="WF-1",
        ride_class="THRILL",
        theoretical_hourly_capacity=1000,
        min_operators_required=2,
        parts_budget_cents=4000000,
    )
    events = fixtures.closed_downtime_window(
        attraction["id"],
        [
            ("2026-08-09T12:00:00.000Z", "2026-08-09T13:00:00.000Z"),
            ("2026-08-10T18:00:00.000Z", "2026-08-10T19:00:00.000Z"),
        ],
    )
    return {"attraction": attraction, "events": events}


def test_the_capacity_window_defaults_to_the_clock_date_and_buckets_by_service_date():
    """An omitted window reports today only, and today is the logical clock's date.

    PRD §3.4: "The caller may supply `window_start_date` and `window_end_date`;
    either that is omitted defaults to the logical clock's current UTC date, so the
    unparameterised call reports today."
    PRD §3.4: "that set is every downtime event of the attraction whose
    `service_date` falls inside the window with both bounds inclusive and whose
    `status` is `RESOLVED`, `CLOSED`, `OPEN`, `DIAGNOSED` or `AWAITING_PARTS`."

    Design: Corner/calculations/capacity_window_defaults_to_the_clock_date_and_excludes_other_service_dates
    """
    bundle = _two_closed_events_on_consecutive_service_dates()
    peak_event, off_peak_event = bundle["events"]
    assert_downtime_event(peak_event)
    assert peak_event["service_date"] == "2026-08-09"
    assert peak_event["peak_minutes"] == 60
    assert peak_event["off_peak_minutes"] == 0
    assert peak_event["settled_guest_slots_lost"] == pytest.approx(1000.00, abs=0.01)
    assert off_peak_event["service_date"] == "2026-08-10"
    assert off_peak_event["peak_minutes"] == 0
    assert off_peak_event["off_peak_minutes"] == 60
    assert off_peak_event["settled_guest_slots_lost"] == pytest.approx(550.00, abs=0.01)

    today = validate_success(
        api_client.get_capacity_impact(bundle["attraction"]["id"], MANAGER)
    )
    assert_capacity_impact_shape(today)
    assert today["window_start_date"] == "2026-08-10"
    assert today["window_end_date"] == "2026-08-10"
    assert today["event_count"] == 1
    assert today["settled_guest_slots_lost"] == pytest.approx(550.00, abs=0.01)
    assert today["provisional_guest_slots_lost"] == pytest.approx(467.50, abs=0.01)
    assert today["divergence_guest_slots"] == pytest.approx(82.50, abs=0.01)

    assert fixtures.read_attraction(bundle["attraction"]["id"])[
        "ytd_downtime_minutes"
    ] == 120


def test_a_widened_window_admits_the_earlier_service_date_and_an_empty_one_reports_zero():
    """Both bounds are inclusive, and an empty input set drives all three figures to zero.

    PRD §3.4: "`divergence_guest_slots` is the window's `settled_guest_slots_lost`
    less its `provisional_guest_slots_lost`, rounded half up to 2 decimal places; it
    may legitimately be negative when open events dominate the window. When the event
    set is empty, all three figures are 0.00."
    PRD §3.4: "Second, it applies a recovery credit: the rounded raw figure is
    multiplied by 0.85 — that is, one less the 15 percent recovery credit the park
    assumes it will claw back through re-rides and extended hours".

    Design: Corner/calculations/capacity_window_defaults_to_the_clock_date_and_excludes_other_service_dates
    """
    bundle = _two_closed_events_on_consecutive_service_dates()

    both = validate_success(
        api_client.get_capacity_impact(
            bundle["attraction"]["id"],
            MANAGER,
            params={
                "window_start_date": "2026-08-09",
                "window_end_date": "2026-08-10",
            },
        )
    )
    assert both["window_start_date"] == "2026-08-09"
    assert both["window_end_date"] == "2026-08-10"
    assert both["event_count"] == 2
    assert both["settled_guest_slots_lost"] == pytest.approx(1550.00, abs=0.01)
    assert both["provisional_guest_slots_lost"] == pytest.approx(1317.50, abs=0.01)
    assert both["divergence_guest_slots"] == pytest.approx(232.50, abs=0.01)

    empty = validate_success(
        api_client.get_capacity_impact(
            bundle["attraction"]["id"],
            MANAGER,
            params={
                "window_start_date": "2026-08-08",
                "window_end_date": "2026-08-08",
            },
        )
    )
    assert empty["event_count"] == 0
    assert empty["settled_guest_slots_lost"] == pytest.approx(0.00, abs=0.01)
    assert empty["provisional_guest_slots_lost"] == pytest.approx(0.00, abs=0.01)
    assert empty["divergence_guest_slots"] == pytest.approx(0.00, abs=0.01)


def _unresolved_event_two_hours_old():
    """A DIAGNOSED event with a null ended_at, read against a 90-minute mean repair."""
    fixtures.set_clock("2026-08-10T18:00:00.000Z")
    attraction = fixtures.create_attraction(
        name="Projection Ride",
        park_area="FRONTIER",
        manufacturer="Vekoma",
        model_code="PJ-1",
        ride_class="THRILL",
        theoretical_hourly_capacity=1200,
        min_operators_required=2,
        parts_budget_cents=4000000,
        mean_repair_minutes=90,
    )
    event = fixtures.open_downtime(
        attraction["id"], started_at="2026-08-10T16:00:00.000Z"
    )
    fixtures.diagnose_downtime(event["id"], root_cause_code="BRAKE-VALVE")
    return {"attraction": attraction, "event": event}


def test_the_provisional_figure_projects_an_open_event_from_the_mean_repair_minutes():
    """The settled figure ignores an unresolved event; the provisional one projects it.

    PRD §3.4: "Third, it projects still-open downtime rather than ignoring it: for any
    event whose `status` is `OPEN`, `DIAGNOSED` or `AWAITING_PARTS` and whose
    `ended_at` is null, the provisional figure substitutes a projected end instant
    equal to that event's `started_at` plus the attraction's `mean_repair_minutes` in
    minutes, clamped so that the projected end never crosses midnight UTC at the end
    of the event's `service_date`."
    PRD §3.4: "The settled figure never projects: an event whose `ended_at` is still
    null — anything in `OPEN`, `DIAGNOSED` or `AWAITING_PARTS` — contributes zero to
    it."

    Design: Corner/calculations/provisional_variant_projects_still_open_downtime_from_mean_repair_minutes
    """
    bundle = _unresolved_event_two_hours_old()

    projected = validate_success(
        api_client.get_capacity_impact(bundle["attraction"]["id"], MANAGER)
    )
    assert_capacity_impact_shape(projected)
    assert projected["window_start_date"] == "2026-08-10"
    assert projected["event_count"] == 1
    assert projected["settled_guest_slots_lost"] == pytest.approx(0.00, abs=0.01)
    assert projected["provisional_guest_slots_lost"] == pytest.approx(1300.50, abs=0.01)
    assert projected["divergence_guest_slots"] == pytest.approx(-1300.50, abs=0.01)


def test_resolving_the_event_stamps_the_settled_loss_and_flips_the_divergence():
    """Once ended_at exists both variants read the same geometry, 15 percent apart.

    PRD §3.4: "For one event, the settled loss is the attraction's
    `theoretical_hourly_capacity` multiplied by that event's weighted lost hours,
    rounded half up to 2 decimal places; that per-event value is exactly what is
    stamped onto the event's own `settled_guest_slots_lost` field at resolution."
    PRD §3.4: "Each event's **peak window** runs from 11:00 UTC on its `service_date`
    up to but not including 17:00 UTC on that same date — a six-hour band across the
    middle of the operating day."

    Design: Corner/calculations/provisional_variant_projects_still_open_downtime_from_mean_repair_minutes
    """
    bundle = _unresolved_event_two_hours_old()

    resolved = fixtures.resolve_downtime(
        bundle["event"]["id"], "2026-08-10T17:30:00.000Z"
    )
    assert_downtime_event(resolved)
    assert resolved["status"] == "RESOLVED"
    assert resolved["duration_minutes"] == 90
    assert resolved["peak_minutes"] == 60
    assert resolved["off_peak_minutes"] == 30
    assert resolved["settled_guest_slots_lost"] == pytest.approx(1530.00, abs=0.01)

    settled = validate_success(
        api_client.get_capacity_impact(bundle["attraction"]["id"], MANAGER)
    )
    assert settled["event_count"] == 1
    assert settled["settled_guest_slots_lost"] == pytest.approx(1530.00, abs=0.01)
    assert settled["provisional_guest_slots_lost"] == pytest.approx(1300.50, abs=0.01)
    assert settled["divergence_guest_slots"] == pytest.approx(229.50, abs=0.01)

    assert fixtures.read_attraction(bundle["attraction"]["id"])[
        "ytd_downtime_minutes"
    ] == 0


def _gearbox_ready_for_the_shop():
    """One WATER unit, one essential gearbox and a single-slot bay."""
    attraction = fixtures.create_attraction(
        name="Off Season Ride",
        park_area="LAGOON",
        manufacturer="Mack",
        model_code="OS-1",
        ride_class="WATER",
        theoretical_hourly_capacity=900,
        min_operators_required=2,
        parts_budget_cents=6000000,
    )
    component = fixtures.create_component(
        attraction["id"],
        name="Drive Gearbox",
        component_type="GEARBOX",
        criticality="ESSENTIAL",
        ndt_interval_cycles=900000,
        ndt_interval_days=3650,
    )
    return {
        "attraction": attraction,
        "component": component,
        "shop_bay": fixtures.create_shop_bay("Bay Season", 1),
    }


def test_a_window_straddling_march_forfeits_the_off_season_discount():
    """Every date in the window must sit inside the span, not merely most of them.

    PRD §3.9: "`off_season` is true when **every** calendar date in the inclusive
    window from `window_start_date` through `window_end_date` falls inside the park's
    off-season span, which runs from the 1st of November in one year through the 28th
    of February in the next".
    PRD §3.9: "When it is true, `expedite_pct` is 0.12 if `discounted_base_cents` is
    below 5,000,000 cents (50,000 dollars), 0.08 if it is below 20,000,000 cents
    (200,000 dollars) but not below the first ceiling, and 0.05 otherwise."

    Design: Corner/calculations/overhaul_off_season_predicate_requires_every_window_date_inside_the_span
    """
    bundle = _gearbox_ready_for_the_shop()

    booked = fixtures.book_work_order(
        bundle["attraction"]["id"],
        bundle["component"]["id"],
        shop_bay=bundle["shop_bay"],
        window_start_date="2027-02-25",
        window_end_date="2027-03-02",
        parts_subtotal_cents=3000000,
        labor_hours=100,
        expedite_requested=True,
    )
    order = booked["work_order"]
    assert_work_order(order)
    assert_work_order_cost_chain(order)
    assert order["off_season"] is False
    assert order["base_total_cents"] == 3950000
    assert order["off_season_discount_cents"] == 0
    assert order["discounted_base_cents"] == 3950000
    assert order["expedite_fee_cents"] == 474000
    assert order["estimated_total_cents"] == 4424000

    assert booked["shop_bay"]["booked_order_count"] == 1
    assert booked["shop_bay"]["version"] == 2


def test_a_window_wholly_inside_november_takes_the_six_percent_discount():
    """The discount is struck off the base before any expedite rate is selected.

    PRD §3.9: "When `off_season` is true, `off_season_discount_cents` is
    `base_total_cents` multiplied by the off-season discount of 6 percent, rounded
    half up to a whole cent; when `off_season` is false, `off_season_discount_cents`
    is 0."
    PRD §3.9: "`expedite_fee_cents` is `discounted_base_cents` multiplied by
    `expedite_pct`, rounded half up to a whole cent; it is 0 whenever
    `expedite_requested` is false."

    Design: Corner/calculations/overhaul_off_season_predicate_requires_every_window_date_inside_the_span
    """
    bundle = _gearbox_ready_for_the_shop()
    first = fixtures.book_work_order(
        bundle["attraction"]["id"],
        bundle["component"]["id"],
        shop_bay=bundle["shop_bay"],
        window_start_date="2027-02-25",
        window_end_date="2027-03-02",
        parts_subtotal_cents=3000000,
        labor_hours=100,
        expedite_requested=True,
    )

    second = fixtures.book_work_order(
        bundle["attraction"]["id"],
        bundle["component"]["id"],
        shop_bay=first["shop_bay"],
        window_start_date="2026-11-05",
        window_end_date="2026-11-10",
        parts_subtotal_cents=3000000,
        labor_hours=100,
    )
    order = second["work_order"]
    assert_work_order_cost_chain(order)
    assert order["off_season"] is True
    assert order["expedite_requested"] is False
    assert order["base_total_cents"] == 3950000
    assert order["off_season_discount_cents"] == 237000
    assert order["discounted_base_cents"] == 3713000
    assert order["expedite_fee_cents"] == 0
    assert order["estimated_total_cents"] == 3713000

    assert second["shop_bay"]["booked_order_count"] == 2
    assert second["shop_bay"]["version"] == 3

    assert fixtures.read_attraction(bundle["attraction"]["id"])[
        "parts_budget_committed_cents"
    ] == 0


def _one_certified_operator_and_one_future_trainee():
    """C1 in force with passing scores, C2 identical but starting nine days later."""
    attraction = fixtures.create_attraction(
        name="Cert Precedence Ride",
        park_area="KIDS_COVE",
        manufacturer="Zamperla",
        model_code="CP-1",
        ride_class="FAMILY",
        theoretical_hourly_capacity=600,
        min_operators_required=1,
        parts_budget_cents=1000000,
    )
    in_force = fixtures.create_certification(
        attraction["id"],
        operator_user_id="op-1",
        effective_from="2026-08-01T00:00:00.000Z",
        expires_at="2026-08-15T00:00:00.000Z",
        restraint_verification_score=90,
        dispatch_procedure_score=85,
    )
    future = fixtures.create_certification(
        attraction["id"],
        operator_user_id="op-2",
        effective_from="2026-08-10T00:00:00.000Z",
        expires_at="2026-09-01T00:00:00.000Z",
        restraint_verification_score=88,
        dispatch_procedure_score=82,
    )
    return {"attraction": attraction, "in_force": in_force, "future": future}


def test_certification_status_is_re_derived_at_every_read_in_a_pinned_order():
    """Expiry outranks a live suspension, and a future window ripens on its own.

    PRD §3.7: "If the current logical clock instant is at or after `expires_at`, the
    status is `EXPIRED` — and `EXPIRED` takes precedence over everything else,
    including suspension, so a suspended certification that reaches its expiry reads
    `EXPIRED` rather than `SUSPENDED`."
    PRD §3.7: "Otherwise, if `suspended_at` is not null, the status is `SUSPENDED`.
    Otherwise, if the clock is still before `effective_from`, the status is `TRAINEE`,
    because a future-dated certification is not yet in force."
    PRD §3.7: "If the attraction's `operational_posture` is anything other than
    `OPEN`, the `dispatch_readiness_index` is 0.00 — a closed, down, held or
    overhauled attraction has no dispatch readiness by definition."

    Design: Corner/calculations/certification_status_precedence_expiry_beats_suspension_and_trainee_flips_at_effective_from
    """
    bundle = _one_certified_operator_and_one_future_trainee()
    attraction_id = bundle["attraction"]["id"]
    assert_operator_certification(bundle["in_force"])
    assert bundle["in_force"]["status"] == "CERTIFIED"
    assert bundle["future"]["status"] == "TRAINEE"
    assert fixtures.read_attraction(attraction_id)["certified_operator_count"] == 1

    suspended = validate_success(
        api_client.suspend_operator_certification(
            bundle["in_force"]["id"],
            factories.suspend_certification_payload("PROCEDURAL_REVIEW"),
            SAFETY_OFFICER,
        )
    )
    assert suspended["status"] == "SUSPENDED"
    assert suspended["suspension_reason"] == "PROCEDURAL_REVIEW"
    assert_instant_equals(suspended["suspended_at"], CLOCK_START, "suspended_at")
    assert fixtures.read_attraction(attraction_id)["certified_operator_count"] == 0

    fixtures.set_clock("2026-08-15T00:00:00.000Z")
    expired = validate_success(
        api_client.get_operator_certification(bundle["in_force"]["id"], MANAGER)
    )
    assert expired["status"] == "EXPIRED"
    assert expired["suspended_at"] is not None
    ripened = validate_success(
        api_client.get_operator_certification(bundle["future"]["id"], MANAGER)
    )
    assert ripened["status"] == "CERTIFIED"
    assert fixtures.read_attraction(attraction_id)["certified_operator_count"] == 1

    fixtures.set_clock("2026-09-01T00:00:00.000Z")
    lapsed = validate_success(
        api_client.get_operator_certification(bundle["future"]["id"], MANAGER)
    )
    assert lapsed["status"] == "EXPIRED"
    assert fixtures.read_attraction(attraction_id)["certified_operator_count"] == 0

    readiness = validate_success(
        api_client.get_dispatch_readiness(attraction_id, MANAGER)
    )
    assert readiness["operational_posture"] == "CLOSED_PENDING_INSPECTION"
    assert readiness["certified_operator_count"] == 0
    assert readiness["dispatch_readiness_index"] == pytest.approx(0.00, abs=0.01)


def _one_unit_carrying_every_posture_condition():
    """An attraction with no template, plus a gearbox and a single-slot bay."""
    fixtures.set_clock("2026-08-01T20:00:00.000Z")
    attraction = fixtures.create_attraction(
        name="Precedence Ladder Ride",
        park_area="SKYLINE",
        manufacturer="B&M",
        model_code="PL-1",
        ride_class="THRILL",
        theoretical_hourly_capacity=800,
        min_operators_required=2,
        parts_budget_cents=5000000,
    )
    component = fixtures.create_component(
        attraction["id"],
        name="Main Gearbox",
        component_type="GEARBOX",
        criticality="ESSENTIAL",
        ndt_interval_cycles=500000,
        ndt_interval_days=3650,
    )
    return {
        "attraction": attraction,
        "component": component,
        "shop_bay": fixtures.create_shop_bay("Bay Ladder", 1),
    }


def test_the_posture_ladder_reports_only_its_highest_matching_clause():
    """Three simultaneous conditions climb the ladder and unwind down the same rungs.

    PRD §2.8: "The derivation walks five clauses in this exact order and the first
    clause that matches wins: 1. `OVERHAUL` — if any overhaul work order of the
    attraction has a `status` of `TEARDOWN`, `INSPECTION` or `REBUILD`. This is the
    highest-precedence posture and outranks even a regulatory hold. 2. `HOLD` — if the
    attraction's `regulatory_hold` is true."
    PRD §2.8: "4. `CLOSED_PENDING_INSPECTION` — if the attraction's
    `last_signed_off_service_date` is not the same as the logical clock's current UTC
    date. 5. `OPEN` — otherwise."

    Design: Corner/calculations/posture_precedence_walks_overhaul_over_hold_over_down_and_unwinds_in_reverse
    """
    bundle = _one_unit_carrying_every_posture_condition()
    attraction_id = bundle["attraction"]["id"]
    assert (
        bundle["attraction"]["operational_posture"] == "CLOSED_PENDING_INSPECTION"
    )
    assert bundle["attraction"]["last_signed_off_service_date"] is None

    event = fixtures.open_downtime(attraction_id, started_at="2026-08-01T08:00:00.000Z")
    assert fixtures.read_attraction(attraction_id)["operational_posture"] == "DOWN"

    incident = fixtures.create_incident(
        attraction_id,
        occurred_at="2026-08-01T09:00:00.000Z",
        injury_severity="SERIOUS",
        guest_count_affected=1,
        narrative="Guest reported arm injury during dispatch.",
    )
    assert incident["status"] == "RIDE_HELD"
    held = fixtures.read_attraction(attraction_id)
    assert held["regulatory_hold"] is True
    assert held["operational_posture"] == "HOLD"

    booked = fixtures.book_work_order(
        attraction_id,
        bundle["component"]["id"],
        shop_bay=bundle["shop_bay"],
        window_start_date="2026-11-01",
        window_end_date="2026-11-20",
        parts_subtotal_cents=500000,
        labor_hours=40,
    )
    work_order = booked["work_order"]
    for phase in ("TEARDOWN", "INSPECTION", "REBUILD"):
        fixtures.advance_work_order(work_order["id"], phase)
        assert (
            fixtures.read_attraction(attraction_id)["operational_posture"]
            == "OVERHAUL"
        )

    recommissioned = fixtures.advance_work_order(work_order["id"], "RECOMMISSIONED")
    assert recommissioned["status"] == "RECOMMISSIONED"
    assert fixtures.read_shop_bay(bundle["shop_bay"]["id"])["booked_order_count"] == 0
    component = fixtures.read_component(bundle["component"]["id"])
    assert component["ndt_status"] == "CURRENT"
    assert component["condition_flag"] == "OK"
    assert fixtures.read_attraction(attraction_id)["operational_posture"] == "HOLD"

    validate_success(api_client.investigate_incident(incident["id"], SAFETY_OFFICER))
    validate_success(
        api_client.notify_regulator(
            incident["id"],
            factories.notify_regulator_payload("REG-LADDER-1"),
            SAFETY_OFFICER,
        )
    )
    validate_success(
        api_client.clear_incident(
            incident["id"],
            SAFETY_OFFICER,
            factories.clear_incident_payload("CLR-LADDER-1"),
        )
    )
    cleared = fixtures.read_attraction(attraction_id)
    assert cleared["regulatory_hold"] is False
    assert cleared["operational_posture"] == "DOWN"

    fixtures.diagnose_downtime(event["id"], root_cause_code="GEAR-NOISE")
    fixtures.resolve_downtime(event["id"], "2026-08-01T09:00:00.000Z")
    fixtures.close_downtime(event["id"])
    settled = fixtures.read_attraction(attraction_id)
    assert settled["operational_posture"] == "CLOSED_PENDING_INSPECTION"
    assert settled["ytd_downtime_minutes"] == 60
    assert (
        fixtures.read_attraction(attraction_id)["operational_posture"]
        == "CLOSED_PENDING_INSPECTION"
    )
