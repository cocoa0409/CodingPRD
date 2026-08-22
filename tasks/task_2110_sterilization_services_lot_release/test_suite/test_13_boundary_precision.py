"""Boundary precision on two different metrics: the fourth decimal place of
the load-density band and the unit count of VDmax audit positives."""

import pytest

from test_helpers import (
    ApiErrorId,
    add_load_position,
    api_client,
    assert_instant_equals,
    build_cycle_scenario,
    create_cycle,
    create_lot,
    create_product,
    create_qualified_qualification,
    get_cycle,
    get_qualification,
    operator,
    place_indicator,
    record_dose_audit,
    setup_reference_data,
    sign_ready,
    validate_error,
)

EDGE_BAND_RECIPE = {
    "density_min_g_per_cm3": 0.0900,
    "density_max_g_per_cm3": 0.1050,
    "required_min_zone_dosimeters": 1,
    "required_routine_dosimeters": 1,
    "required_biological_indicators": 0,
}


def test_density_exactly_on_the_upper_edge_is_out_of_band():
    """PRD 3.3: "`density_max_g_per_cm3`, which must be strictly greater than
    the minimum and is the **exclusive** upper edge — a load sitting exactly on
    the maximum is out of band."
    PRD 3.6: "Third, the cycle's `load_density_g_per_cm3` must sit inside the
    recipe's validated band — at or above `density_min_g_per_cm3` and strictly
    below `density_max_g_per_cm3` — with a density below the floor or at or
    above the ceiling refused as `ERR_LOAD_DENSITY_OUT_OF_BAND`."

    Design: Difficulty/boundary_precision_check/density_band_upper_edge_is_exclusive_on_ready_endpoint
    """
    env = setup_reference_data(recipe_overrides=EDGE_BAND_RECIPE)
    product_b = create_product(
        env["customer"]["id"], product_code="P2", pallet_mass_kg=90.0, pallet_volume_m3=0.8
    )
    create_qualified_qualification(product_b["id"], env["recipe"]["id"])
    lot_a = create_lot(
        env["customer"]["id"], env["product"]["id"], lot_code="L-P1", total_pallet_count=1
    )
    lot_b = create_lot(
        env["customer"]["id"], product_b["id"], lot_code="L-P2", total_pallet_count=1
    )
    cycle = create_cycle(env["chamber"]["id"], env["recipe"]["id"], cycle_code="C-EDGE")
    first = add_load_position(
        cycle["id"], lot_a["id"], position_index=1, zone="MIN_DOSE", pallet_count=1
    )
    second = add_load_position(
        cycle["id"], lot_b["id"], expected_cycle_version=first["cycle_version_after"],
        position_index=2, zone="INTERIOR", pallet_count=1,
    )
    place_indicator(
        first["id"], indicator_type="DOSIMETER", placement_zone="MIN_DOSE",
        serial_code="D-MIN",
    )
    place_indicator(
        second["id"], indicator_type="DOSIMETER", placement_zone="ROUTINE",
        serial_code="D-RT",
    )
    assert get_cycle(cycle["id"])["load_density_g_per_cm3"] == pytest.approx(
        0.1050, abs=1e-9
    )

    response = api_client.ready_cycle(cycle["id"], operator())

    validate_error(response, ApiErrorId.ERR_LOAD_DENSITY_OUT_OF_BAND)
    after = get_cycle(cycle["id"])
    assert after["status"] == "LOADING", "the sign-off did not take effect"
    assert after["loaded_pallet_count"] == 2


def test_density_exactly_on_the_lower_edge_is_in_band():
    """PRD 3.3: "The recipe declares the load-density band it was validated for
    through `density_min_g_per_cm3`, which must be greater than zero and is the
    **inclusive** lower edge"
    PRD 3.6: "Third, the cycle's `load_density_g_per_cm3` must sit inside the
    recipe's validated band — at or above `density_min_g_per_cm3` and strictly
    below `density_max_g_per_cm3` — with a density below the floor or at or
    above the ceiling refused as `ERR_LOAD_DENSITY_OUT_OF_BAND`."

    Design: Difficulty/boundary_precision_check/density_band_upper_edge_is_exclusive_on_ready_endpoint
    """
    env = build_cycle_scenario(
        stage="loading",
        recipe_overrides=EDGE_BAND_RECIPE,
        product_overrides={"pallet_mass_kg": 90.0, "pallet_volume_m3": 1.0},
    )
    assert get_cycle(env["cycle"]["id"])["load_density_g_per_cm3"] == pytest.approx(
        0.0900, abs=1e-9
    )

    signed = sign_ready(env["cycle"]["id"])

    assert signed["status"] == "READY", "a load sitting exactly on the floor is in band"


def test_vdmax_zero_positives_passes_for_ninety_days():
    """PRD 3.3: "Zero positives is a `PASS` and buys an interval of 90 days."
    PRD 3.3: "Where the outcome is not `FAIL`, the audit's `next_audit_due_at`
    is `performed_at` advanced by the interval in whole days; where the outcome
    is `FAIL`, `next_audit_due_at` is null."
    PRD 3.3: "A `PASS` sets `consecutive_conditional_count` back to 0 and the
    qualification's `status` to `QUALIFIED`."

    Design: Difficulty/boundary_precision_check/vdmax_positive_count_boundary_zero_one_two
    """
    env = setup_reference_data(qualify=False, clock="2026-08-20T00:00:00Z")

    audit = record_dose_audit(
        env["qualification"]["id"], performed_at="2026-08-20T00:00:00Z", positives=0
    )

    assert audit["outcome"] == "PASS"
    assert audit["qualification_status_after"] == "QUALIFIED"
    assert_instant_equals(
        audit["next_audit_due_at"], "2026-11-18T00:00:00Z", "next_audit_due_at"
    )
    qualification = get_qualification(env["qualification"]["id"])
    assert qualification["status"] == "QUALIFIED"
    assert qualification["audit_interval_days"] == 90
    assert qualification["consecutive_conditional_count"] == 0


@pytest.mark.parametrize(
    "positives,outcome,status_after,interval_days,next_due,count_after",
    [
        (1, "CONDITIONAL_PASS", "CONDITIONAL", 30, "2026-09-19T00:00:00Z", 1),
        (2, "FAIL", "SUSPENDED", 0, None, 0),
    ],
)
def test_vdmax_positive_count_boundary(
    positives, outcome, status_after, interval_days, next_due, count_after
):
    """PRD 3.3: "Zero positives is a `PASS` and buys an interval of 90 days.
    Exactly one positive is a `CONDITIONAL_PASS` and buys only 30 days. Two or
    more positives is a `FAIL` and buys nothing — the interval is 0. Where the
    outcome is not `FAIL`, the audit's `next_audit_due_at` is `performed_at`
    advanced by the interval in whole days; where the outcome is `FAIL`,
    `next_audit_due_at` is null. The parent qualification is then updated in
    lockstep: its `audit_interval_days` becomes the selected interval, its
    `last_audit_at` becomes `performed_at`, and its `next_audit_due_at` becomes
    the audit's. A `PASS` sets `consecutive_conditional_count` back to 0 and
    the qualification's `status` to `QUALIFIED`. A `CONDITIONAL_PASS` increases
    `consecutive_conditional_count` by one and then looks at the new count:
    below 2 the qualification becomes `CONDITIONAL`; at 2 or above it becomes
    `REVOKED`, with `next_audit_due_at` forced to null. A `FAIL` resets
    `consecutive_conditional_count` to 0 and sets the qualification to
    `SUSPENDED` with `next_audit_due_at` null."

    Design: Difficulty/boundary_precision_check/vdmax_positive_count_boundary_zero_one_two
    """
    env = setup_reference_data(qualify=False, clock="2026-08-20T00:00:00Z")

    audit = record_dose_audit(
        env["qualification"]["id"],
        performed_at="2026-08-20T00:00:00Z",
        positives=positives,
    )

    assert audit["outcome"] == outcome
    assert audit["qualification_status_after"] == status_after
    if next_due is None:
        assert audit["next_audit_due_at"] is None
    else:
        assert_instant_equals(audit["next_audit_due_at"], next_due, "next_audit_due_at")

    qualification = get_qualification(env["qualification"]["id"])
    assert qualification["status"] == status_after
    assert qualification["audit_interval_days"] == interval_days
    assert qualification["consecutive_conditional_count"] == count_after
    assert_instant_equals(
        qualification["last_audit_at"], "2026-08-20T00:00:00Z", "last_audit_at"
    )
    if next_due is None:
        assert qualification["next_audit_due_at"] is None
    else:
        assert_instant_equals(
            qualification["next_audit_due_at"], next_due, "next_audit_due_at"
        )
