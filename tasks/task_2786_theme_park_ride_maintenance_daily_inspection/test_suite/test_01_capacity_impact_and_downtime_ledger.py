"""Capacity-impact arithmetic and the conserved downtime minutes ledger.

The two computed capacity figures are deliberately built from the same event set
by two different rounding regimes, and the minutes ledger only ever moves at
close and at void.
"""

import pytest

from test_helpers import (
    MANAGER,
    api_client,
    assert_capacity_impact_shape,
    fixtures,
    get_success_data,
    validate_success,
)

CAPACITY_CLOCK = "2026-08-10T20:00:00.000Z"
LEDGER_CLOCK = "2026-08-01T20:00:00.000Z"


def _comet_racer_window():
    """One CLOSED and one RESOLVED event on 2026-08-10 for a 1150-slot attraction.

    The first event runs 10:21 to 12:17 UTC and the second 15:46 to 17:31 UTC, so
    each one straddles one edge of the 11:00-to-17:00 peak band.
    """
    fixtures.set_clock(CAPACITY_CLOCK)
    attraction = fixtures.create_attraction(
        name="Comet Racer",
        park_area="SKYLINE",
        manufacturer="Intamin",
        model_code="CR-9",
        ride_class="THRILL",
        theoretical_hourly_capacity=1150,
        min_operators_required=3,
        parts_budget_cents=5000000,
    )
    first = fixtures.open_downtime(
        attraction["id"], "2026-08-10T10:21:00.000Z", "MECHANICAL"
    )
    fixtures.diagnose_downtime(first["id"], "BRK-114")
    fixtures.resolve_downtime(first["id"], "2026-08-10T12:17:00.000Z")
    first = fixtures.close_downtime(first["id"])

    second = fixtures.open_downtime(
        attraction["id"], "2026-08-10T15:46:00.000Z", "ELECTRICAL"
    )
    fixtures.diagnose_downtime(second["id"], "ELC-207")
    second = fixtures.resolve_downtime(second["id"], "2026-08-10T17:31:00.000Z")
    return {"attraction": attraction, "first": first, "second": second}


def test_each_event_freezes_its_own_rounded_settled_loss_at_resolution():
    """Each event's minute geometry and per-event settled loss are frozen at resolve.

    PRD §3.4: "The event's `peak_minutes` is the whole number of minutes in the
    intersection of its occupancy interval with its peak window; its
    `duration_minutes` is the whole number of minutes in its occupancy interval;
    and its `off_peak_minutes` is `duration_minutes` less `peak_minutes`."
    PRD §3.4: "For one event, the settled loss is the attraction's
    `theoretical_hourly_capacity` multiplied by that event's weighted lost hours,
    rounded half up to 2 decimal places; that per-event value is exactly what is
    stamped onto the event's own `settled_guest_slots_lost` field at resolution."

    Design: Difficulty/dual_variant_calc/capacity_loss_settled_per_event_rounding_vs_provisional_single_rounding
    """
    bundle = _comet_racer_window()

    first = bundle["first"]
    assert first["duration_minutes"] == 116
    assert first["peak_minutes"] == 77
    assert first["off_peak_minutes"] == 39
    assert first["settled_guest_slots_lost"] == pytest.approx(1886.96, abs=0.01)
    assert first["status"] == "CLOSED"

    second = bundle["second"]
    assert second["duration_minutes"] == 105
    assert second["peak_minutes"] == 74
    assert second["off_peak_minutes"] == 31
    assert second["settled_guest_slots_lost"] == pytest.approx(1745.13, abs=0.01)
    assert second["status"] == "RESOLVED"


def test_the_settled_window_sums_values_that_were_already_rounded_per_event():
    """The window total sums per-event rounded figures rather than raw products.

    PRD §3.4: "The **settled** figure is the books-closed number park operations
    reports after each event has been resolved, and it rounds per event before it
    sums."
    PRD §3.4: "The window's `settled_guest_slots_lost` is then the sum of those
    already-rounded per-event values, rounded half up to 2 decimal places once
    more."

    Design: Difficulty/dual_variant_calc/capacity_loss_settled_per_event_rounding_vs_provisional_single_rounding
    """
    bundle = _comet_racer_window()

    response = api_client.get_capacity_impact(bundle["attraction"]["id"], MANAGER)
    data = validate_success(response)
    assert_capacity_impact_shape(data)

    assert data["window_start_date"] == "2026-08-10"
    assert data["window_end_date"] == "2026-08-10"
    assert data["event_count"] == 2
    assert data["settled_guest_slots_lost"] == pytest.approx(3632.09, abs=0.01)
    assert data["settled_guest_slots_lost"] != pytest.approx(3632.08, abs=0.001), (
        "summing the unrounded per-event products would give 3632.08"
    )


def test_the_provisional_window_rounds_once_and_applies_the_recovery_credit():
    """The provisional figure aggregates raw minutes, rounds once, then credits 15%.

    PRD §3.4: "First, it aggregates the raw geometry before rounding: it sums
    `peak_minutes` across every event in the set and separately sums
    `off_peak_minutes` across every event in the set, then computes the
    attraction's `theoretical_hourly_capacity` multiplied by the quantity given by
    the summed peak minutes divided by 60 times the peak weight of 1.00 plus the
    summed off-peak minutes divided by 60 times the off-peak weight of 0.55, and
    rounds that whole product half up to 2 decimal places exactly once."
    PRD §3.4: "`divergence_guest_slots` is the window's
    `settled_guest_slots_lost` less its `provisional_guest_slots_lost`, rounded
    half up to 2 decimal places".

    Design: Difficulty/dual_variant_calc/capacity_loss_settled_per_event_rounding_vs_provisional_single_rounding
    """
    bundle = _comet_racer_window()

    data = validate_success(
        api_client.get_capacity_impact(bundle["attraction"]["id"], MANAGER)
    )

    assert data["provisional_guest_slots_lost"] == pytest.approx(3087.27, abs=0.01)
    assert data["divergence_guest_slots"] == pytest.approx(544.82, abs=0.01)


def _pinewood_plunge_ledger():
    """Two CLOSED events on 2026-08-01 for a 1000-slot water ride."""
    fixtures.set_clock(LEDGER_CLOCK)
    attraction = fixtures.create_attraction(
        name="Pinewood Plunge",
        park_area="LAGOON",
        manufacturer="Hafema",
        model_code="PP-5",
        ride_class="WATER",
        theoretical_hourly_capacity=1000,
        min_operators_required=2,
        parts_budget_cents=1400000,
    )
    first = fixtures.open_downtime(
        attraction["id"], "2026-08-01T10:00:00.000Z", "WEATHER"
    )
    fixtures.diagnose_downtime(first["id"], "WX-002")
    fixtures.resolve_downtime(first["id"], "2026-08-01T11:45:00.000Z")
    first = fixtures.close_downtime(first["id"])

    second = fixtures.open_downtime(
        attraction["id"], "2026-08-01T13:00:00.000Z", "GUEST_ILLNESS"
    )
    fixtures.diagnose_downtime(second["id"], "GI-011")
    fixtures.resolve_downtime(second["id"], "2026-08-01T13:30:00.000Z")
    second = fixtures.close_downtime(second["id"])
    return {"attraction": attraction, "first": first, "second": second}


def test_closing_each_resolved_event_accumulates_the_minutes_ledger():
    """The ledger only moves at close, and it sums the closed events' minutes.

    PRD §2.9: "`ytd_downtime_minutes` is the sum, in whole minutes, of
    `duration_minutes` across every downtime event of that attraction whose
    `status` is exactly `CLOSED`."
    PRD §3.4: "Resolution computes `duration_minutes`, `peak_minutes`,
    `off_peak_minutes` and `settled_guest_slots_lost`, and it deliberately does not
    touch the attraction's `ytd_downtime_minutes` — the minutes ledger moves only
    at close."

    Design: Difficulty/compensating_invariant/void_restores_ytd_downtime_minutes_exactly_and_drops_the_event_from_both_variants
    """
    bundle = _pinewood_plunge_ledger()

    assert bundle["first"]["duration_minutes"] == 105
    assert bundle["first"]["peak_minutes"] == 45
    assert bundle["first"]["settled_guest_slots_lost"] == pytest.approx(
        1300.00, abs=0.01
    )
    assert bundle["second"]["duration_minutes"] == 30
    assert bundle["second"]["peak_minutes"] == 30
    assert bundle["second"]["settled_guest_slots_lost"] == pytest.approx(
        500.00, abs=0.01
    )

    attraction = fixtures.read_attraction(bundle["attraction"]["id"])
    assert attraction["ytd_downtime_minutes"] == 135


def test_voiding_a_closed_event_returns_the_ledger_to_its_pre_close_value():
    """Voiding subtracts exactly what closing added and freezes nothing else.

    PRD §2.9: "Closing a resolved event adds its `duration_minutes` to the counter;
    voiding a closed event subtracts exactly the same number back out, returning
    the counter to its pre-close value."
    PRD §3.4: "`VOIDED` is terminal."

    Design: Difficulty/compensating_invariant/void_restores_ytd_downtime_minutes_exactly_and_drops_the_event_from_both_variants
    """
    bundle = _pinewood_plunge_ledger()

    voided = get_success_data(
        api_client.void_downtime_event(
            bundle["first"]["id"],
            {"void_reason": "Logged against the wrong attraction by the duty manager"},
            MANAGER,
        )
    )
    assert voided["status"] == "VOIDED"
    assert voided["duration_minutes"] == 105, (
        "voiding does not erase the frozen minute geometry"
    )
    assert voided["settled_guest_slots_lost"] == pytest.approx(1300.00, abs=0.01)

    attraction = fixtures.read_attraction(bundle["attraction"]["id"])
    assert attraction["ytd_downtime_minutes"] == 30


def test_a_voided_event_leaves_the_input_set_of_both_capacity_variants():
    """A voided event is excluded from the settled and the provisional figure alike.

    PRD §3.4: "Events whose `status` is `VOIDED` are excluded from both figures."
    PRD §3.4: "Second, it applies a recovery credit: the rounded raw figure is
    multiplied by 0.85 — that is, one less the 15 percent recovery credit the park
    assumes it will claw back through re-rides and extended hours — and the product
    is rounded half up to 2 decimal places again to give
    `provisional_guest_slots_lost`."

    Design: Difficulty/compensating_invariant/void_restores_ytd_downtime_minutes_exactly_and_drops_the_event_from_both_variants
    """
    bundle = _pinewood_plunge_ledger()
    fixtures.void_downtime(
        bundle["first"]["id"],
        "Logged against the wrong attraction by the duty manager",
    )

    data = validate_success(
        api_client.get_capacity_impact(bundle["attraction"]["id"], MANAGER)
    )
    assert_capacity_impact_shape(data)

    assert data["event_count"] == 1
    assert data["settled_guest_slots_lost"] == pytest.approx(500.00, abs=0.01)
    assert data["provisional_guest_slots_lost"] == pytest.approx(425.00, abs=0.01)
    assert data["divergence_guest_slots"] == pytest.approx(75.00, abs=0.01)
