"""Reservation charge: the pinned escalation, rounding order and grace band."""
import pytest

from test_helpers import (
    PLATFORM,
    OPERATOR,
    api_client,
    get_success_data,
    make_member_headers,
    setup_confirmed_reservation,
    start_trip,
    validate_success,
)
from test_helpers.fixtures import FLEET

SAMPLE_INSTANT = "2026-09-10T12:00:00Z"


def _trip_in_use(clock, pod_name, fuel_floor_pct=35):
    """Confirmed reservation advanced to IN_USE with the clock parked at `clock`."""
    setup = setup_confirmed_reservation(
        pod_name=pod_name, site_type="AIRPORT", pod_capacity=4, fuel_floor_pct=fuel_floor_pct
    )
    start_trip(setup["member"]["id"], setup["reservation"]["id"])
    get_success_data(api_client.set_clock(clock, PLATFORM), 200)
    return setup


def _overdue_trip(clock, pod_name):
    """Confirmed reservation whose window elapsed with no physical return.

    PRD §3.10 declares the sweep's declared entry edges as the elapsed-window
    sweep itself, and PRD §3.9 pins this fixture's outcome verbatim: "An
    unresolved overdue reservation that is swept and then resolved carries no
    fuel deficit and no time adjustment beyond the lateness itself; resolved at
    the sample instant 2026-09-10T12:00:00Z it produces a pre-discount amount of
    12429 cents and charges 9944 cents."
    """
    setup = setup_confirmed_reservation(
        pod_name=pod_name, site_type="AIRPORT", pod_capacity=4, fuel_floor_pct=35
    )
    get_success_data(api_client.set_clock(clock, PLATFORM), 200)
    setup["reopened"] = get_success_data(
        api_client.reopen_overdue(setup["reservation"]["id"], OPERATOR), 200
    )
    return setup


def _return(setup, odometer_miles, fuel_level_pct, contamination_level=0):
    return validate_success(
        api_client.return_reservation(
            setup["reservation"]["id"],
            {
                "returned_pod_id": setup["pod"]["id"],
                "returned_odometer_miles": odometer_miles,
                "returned_fuel_level_pct": fuel_level_pct,
                "contamination_level": contamination_level,
            },
            make_member_headers(setup["member"]["id"]),
        ),
        200,
    )


# ─── Escalating late fee versus the flat competing variant ───

def test_overdue_resolution_charges_the_sample_instant_amount_not_an_hour_scaled_one():
    """PRD §3.9: "An unresolved overdue reservation that is swept and then resolved carries
    no fuel deficit and no time adjustment beyond the lateness itself; resolved at the
    sample instant 2026-09-10T12:00:00Z it produces a pre-discount amount of 12429 cents
    and charges 9944 cents."

    Design: Difficulty/dual_variant_calc/reservation_charge_late_variant_divergence
    """
    setup = _overdue_trip(SAMPLE_INSTANT, "Sample Instant Pod")

    resolved = validate_success(
        api_client.resolve_overdue(setup["reservation"]["id"], OPERATOR), 200
    )

    assert resolved["status"] == "CLOSED", (
        f"Resolution lands on CLOSED regardless of the preserved status, got {resolved['status']}"
    )
    assert resolved["status_before_overdue"] == "CONFIRMED", (
        f"The sweep must preserve the status it observed: got {resolved['status_before_overdue']}"
    )
    assert resolved["charge_total_cents"] == 9944, (
        f"Expected the worked sample figure 9944, got {resolved['charge_total_cents']}"
    )


def test_overdue_resolution_posts_the_flat_eight_thousand_tier_with_no_ledger_delta():
    """PRD §3.10: "when `S` is at least 2 the penalty is the flat 8000-cent tier"
    PRD §3.10: "When the vehicle has no posted fuel-card transaction at all, every
    last-transaction total is zero, so the ledger delta is zero and a large overage
    resolves to the flat 8000-cent tier with no ledger contribution."
    PRD §2.6: "When a reservation is resolved while overdue, the late-return penalty is
    posted to the member ledger and the hold that covered it is consumed first."

    Design: Difficulty/dual_variant_calc/reservation_charge_late_variant_divergence
    """
    setup = _overdue_trip(SAMPLE_INSTANT, "Flat Tier Pod")

    validate_success(api_client.resolve_overdue(setup["reservation"]["id"], OPERATOR), 200)

    member = validate_success(api_client.get_member(setup["member"]["id"], OPERATOR), 200)
    assert member["wallet_hold_cents"] == 0, (
        f"The hold covering the penalty must be consumed: got {member['wallet_hold_cents']}"
    )
    assert member["wallet_credit_cents"] == 8000, (
        f"The flat 8000-cent tier must be posted as a service credit, not scaled by the "
        f"elapsed blocks: got {member['wallet_credit_cents']}"
    )


# ─── Nested per-block rounding order ─────────────────

def test_nested_rounding_order_charges_10203_not_10204():
    """PRD §3.9: "returned 75 minutes late with a 6-point fuel deficit it has a late fee of
    6104, a surcharge of 324 and a pre-discount amount of 12753 cents, charging 10203 cents.
    That last figure is the one to check rounding order against: summing the unrounded block
    rates before rounding would give 12754 and charge 10204 cents."

    Design: Difficulty/combinatorial_formula/late_fee_nested_rounding_order_mode_b
    """
    setup = _trip_in_use("2026-09-05T14:15:00Z", "Rounding Pod", fuel_floor_pct=41)

    returned = _return(setup, odometer_miles=41400, fuel_level_pct=35)

    assert returned["charge_total_cents"] == 10203, (
        f"Per-block rounding then summation gives 10203; a single rounding pass would give "
        f"10204. Got {returned['charge_total_cents']}"
    )
    assert returned["charge_total_cents"] != 10204, (
        "The unrounded-then-summed order is explicitly not what this system does"
    )


def test_nested_rounding_amount_is_copied_onto_the_vehicle_charge():
    """PRD §3.8: "The reservation's `charge_total_cents` is recomputed by the return charge
    calculation of §3.9, and that same amount is copied onto the vehicle's own
    `charge_total_cents`, so the vehicle reflects whatever its latest close produced while
    the reservation keeps its own figure."
    PRD §3.9: "That last figure is the one to check rounding order against: summing the
    unrounded block rates before rounding would give 12754 and charge 10204 cents."

    Design: Difficulty/combinatorial_formula/late_fee_nested_rounding_order_mode_b
    """
    setup = _trip_in_use("2026-09-05T14:15:00Z", "Copy Charge Pod", fuel_floor_pct=41)

    returned = _return(setup, odometer_miles=41400, fuel_level_pct=35)
    vehicle = validate_success(api_client.get_vehicle(setup["vehicle"]["id"], FLEET), 200)

    assert vehicle["charge_total_cents"] == returned["charge_total_cents"] == 10203, (
        f"Vehicle charge {vehicle['charge_total_cents']} must mirror the reservation's "
        f"{returned['charge_total_cents']}"
    )


# ─── Grace-band boundary on the lateness metric ───────

@pytest.mark.parametrize(
    "late_minutes,expected_charge",
    [
        (9, 3680),
        (10, 3680),
        (31, 7595),
    ],
)
def test_late_penalty_grace_block_boundary(late_minutes, expected_charge):
    """PRD §3.9: "The number of lateness blocks is zero when `late_minutes` is at most the
    10-minute grace period, and otherwise the whole number of 30-minute blocks that covers
    `late_minutes`, rounded up."
    PRD §3.9: "A reservation with a 4-hour window, no prior vehicle charge, an on-time
    reading at the pod floor and a fresh reservation therefore charges 4600 cents in the
    pre-discount amount and 3680 cents after the 20-percent discount, for both a zero-minute
    return and a 10-minute return."

    Design: Difficulty/boundary_precision_check/late_penalty_grace_block_boundary
    """
    # end_at is 2026-09-05T13:00:00Z and the sweep must fire strictly past it, so
    # the lateness is elapsed through the window rather than through a return.
    clock = f"2026-09-05T{13 + late_minutes // 60:02d}:{late_minutes % 60:02d}:00Z"
    setup = _overdue_trip(clock, f"Boundary Pod {late_minutes}")

    assert setup["reopened"]["late_minutes"] == late_minutes, (
        f"Expected {late_minutes} whole minutes past end_at, got "
        f"{setup['reopened']['late_minutes']}"
    )
    assert setup["reopened"]["status"] == "OVERDUE", (
        f"The sweep carries the reservation into the lateness dimension, got "
        f"{setup['reopened']['status']}"
    )
    assert setup["reopened"]["charge_total_cents"] == expected_charge, (
        f"Expected {expected_charge} at {late_minutes} late minutes, got "
        f"{setup['reopened']['charge_total_cents']}"
    )


def test_sweep_inside_the_grace_band_stays_on_the_on_time_charge():
    """PRD §3.9: "A reservation with a 4-hour window, no prior vehicle charge, an on-time
    reading at the pod floor and a fresh reservation therefore charges 4600 cents in the
    pre-discount amount and 3680 cents after the 20-percent discount, for both a zero-minute
    return and a 10-minute return."

    Design: Difficulty/boundary_precision_check/late_penalty_grace_block_boundary
    """
    setup = _overdue_trip("2026-09-05T13:10:00Z", "Grace Exact Pod")

    assert setup["reopened"]["late_minutes"] == 10, (
        f"A ten-minute lateness sits inside the grace band: got {setup['reopened']['late_minutes']}"
    )
    assert setup["reopened"]["charge_total_cents"] == 3680, (
        f"A 10-minute lateness must never bill a whole 30-minute block: got "
        f"{setup['reopened']['charge_total_cents']}"
    )


# ─── On-time hourly component and the fuel surcharge variant ───

def test_on_time_return_uses_the_flat_hourly_time_component():
    """PRD §3.9: "For an hourly reservation the time component is the number of on-time
    blocks multiplied by the 1150-cent hourly rate, plus the number of billed late blocks
    multiplied by the hourly rate multiplied by the 1.5 late multiplier."
    PRD §3.9: "An on-time reading at the pod floor therefore carries a deficit of zero and a
    bucket of 1, and contributes neither a surcharge nor a fine."

    Design: Corner/calculations/charge_on_time_reservation_uses_flat_hourly_component
    """
    setup = _trip_in_use("2026-09-05T12:00:00Z", "Ontime Lot", fuel_floor_pct=35)

    returned = _return(setup, odometer_miles=37000, fuel_level_pct=35)

    assert returned["status"] == "RETURNED", (
        f"An early or on-time return lands on RETURNED, got {returned['status']}"
    )
    assert returned["late_minutes"] == 0, (
        f"An early return reports zero late minutes rather than a negative count: got "
        f"{returned['late_minutes']}"
    )
    assert returned["charge_total_cents"] == 3680, (
        f"Four on-time blocks at 1150 cents is 4600 pre-discount, charging 3680 after the "
        f"20-percent discount: got {returned['charge_total_cents']}"
    )


def test_ten_minutes_late_return_bills_no_late_block():
    """PRD §3.9: "A reservation with a 4-hour window, no prior vehicle charge, an on-time
    reading at the pod floor and a fresh reservation therefore charges 4600 cents in the
    pre-discount amount and 3680 cents after the 20-percent discount, for both a zero-minute
    return and a 10-minute return."

    Design: Corner/calculations/charge_ten_minutes_late_inside_the_grace_band
    """
    setup = _trip_in_use("2026-09-05T13:10:00Z", "Grace Lot", fuel_floor_pct=35)

    returned = _return(setup, odometer_miles=38000, fuel_level_pct=35)

    assert returned["late_minutes"] == 10, (
        f"Ten whole minutes past end_at, got {returned['late_minutes']}"
    )
    assert returned["status"] == "RETURNED", (
        f"A ten-minute lateness bills no block and so stays RETURNED, got {returned['status']}"
    )
    assert returned["charge_total_cents"] == 3680, (
        f"A 10-minute return must equal the untouched on-time charge, got "
        f"{returned['charge_total_cents']}"
    )


def test_fuel_surcharge_uses_the_measured_deficit_not_the_reduced_variant():
    """PRD §3.9: "The competing reading applies the flat 750-cent amount to any deficit at
    all, which would produce 750 cents for a 15-point deficit where the measured formula
    produces 810 cents; this system applies the measured formula, so a 20-percent pod floor
    against a 35-percent reading yields a deficit of 15 points and a surcharge of the ceiling
    of 15 multiplied by 12 divided by 100, multiplied by 450, which is 810 cents."

    Design: Corner/calculations/fuel_surcharge_uses_the_measured_deficit_not_the_flat_variant
    """
    setup = _trip_in_use("2026-09-05T12:00:00Z", "Airport Fuel", fuel_floor_pct=35)

    returned = _return(setup, odometer_miles=40000, fuel_level_pct=20)

    # 4600 time + 810 measured surcharge + 2500 bucket-2 fine == 7910 pre-discount,
    # charging 7910 - floor(1582) == 6328.
    assert returned["charge_total_cents"] == 6328, (
        f"The measured 810-cent surcharge gives 6328, got {returned['charge_total_cents']}"
    )
    assert returned["charge_total_cents"] != 6280, (
        "The flat reduced surcharge of 750 cents is explicitly not what this system does"
    )

def test_eleven_minute_overdue_sweep_also_crosses_into_the_first_block():
    """PRD §3.9: "The pre-discount amount is the time component plus the late fee plus the fuel
    surcharge plus the fuel-level fine."
    PRD §3.9: "Each qualifying block's raw rate is individually rounded half-up to a whole
    number of cents before anything else happens, and the late fee is the sum of those
    individually rounded block rates."

    Design: Corner/calculations/charge_eleven_minutes_late_crosses_into_the_first_block
    """
    setup = _overdue_trip("2026-09-05T13:11:00Z", "Eleven Sweep Pod")

    assert setup["reopened"]["late_minutes"] == 11, (
        f"Eleven whole minutes past end_at, got {setup['reopened']['late_minutes']}"
    )
    assert setup["reopened"]["charge_total_cents"] == 5520, (
        f"One escalated block at 1725 cents on top of three on-time blocks charges 5520: got "
        f"{setup['reopened']['charge_total_cents']}"
    )
    assert setup["reopened"]["status"] == "OVERDUE", (
        f"The lateness sweep records the dimension independently of the physical return, got "
        f"{setup['reopened']['status']}"
    )
