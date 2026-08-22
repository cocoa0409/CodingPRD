"""Dose figures, the conformance verdict, the emission ledger, the aeration
derating bands and the residual verdict."""

import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    abort_cycle,
    add_load_position,
    api_client,
    assert_instant_equals,
    build_cycle_scenario,
    close_dosimetry,
    complete_cycle,
    create_cycle,
    create_cycle_payload,
    create_lot,
    create_product,
    create_qualified_qualification,
    get_cycle,
    get_lot,
    get_permit,
    get_qualification,
    open_aeration_record,
    operator,
    place_indicator,
    record_reading,
    record_residual_test,
    release_lot,
    set_clock,
    setup_reference_data,
    sign_ready,
    start_cycle,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["regulatory_admin_headers"]

TWO_ROUTINE_RECIPE = {
    "required_min_zone_dosimeters": 1,
    "required_routine_dosimeters": 2,
    "required_biological_indicators": 0,
}


def test_load_density_is_zero_for_an_empty_load_map():
    """PRD 3.5: "When the total volume is zero — a cycle with no positions left
    — the density is 0.0000."
    PRD 3.4: "The cycle opens in `status` `PLANNED` with `loaded_pallet_count`
    0, `load_density_g_per_cm3` 0, `abated_eto_kg` 0, `emission_fee_usd` 0,
    `deviation_code` `NONE`, and `delivered_dose_kgy`, `max_observed_dose_kgy`,
    `operator_user_id` and `dosimetry_closed_by_user_id` all null."

    Design: Corner/calculations/corner_load_density_is_zero_for_an_empty_load_map
    """
    env = setup_reference_data(qualify=False)

    data = validate_success(
        api_client.create_cycle(
            create_cycle_payload(env["chamber"]["id"], env["recipe"]["id"]), operator()
        ),
        201,
    )

    assert data["load_density_g_per_cm3"] == pytest.approx(0.0, abs=1e-9)
    assert data["loaded_pallet_count"] == 0
    _, meta = validate_paginated(
        api_client.list_load_positions(operator(), params={"cycle_id": data["id"]})
    )
    assert meta["total_count"] == 0


def test_routine_mean_rounds_half_up_at_two_decimals():
    """PRD 2.5: "All rounding, wherever it appears below, is **round half up**,
    and it is applied exactly at the step named and at no other step."
    PRD 3.7: "the server takes the subset of those read dosimeters whose
    `placement_zone` is `ROUTINE`; if that subset is empty the close is refused
    with `ERR_DOSIMETRY_INCOMPLETE`; otherwise `delivered_dose_kgy` is the sum
    of their `measured_dose_kgy` values divided by the count of those readings,
    with the single quotient rounded half up to two decimal places."

    Design: Corner/calculations/corner_delivered_dose_routine_mean_rounds_half_up_to_two_decimals
    """
    env = build_cycle_scenario(stage="completed", recipe_overrides=TWO_ROUTINE_RECIPE)
    record_reading(env["indicators"]["min_zone"][0]["id"], measured_dose_kgy=27.90)
    record_reading(env["indicators"]["routine"][0]["id"], measured_dose_kgy=28.40)
    record_reading(env["indicators"]["routine"][1]["id"], measured_dose_kgy=31.25)

    closed = close_dosimetry(env["cycle"]["id"])

    assert closed["delivered_dose_kgy"] == pytest.approx(29.83, abs=0.001), (
        "the exact quotient 29.825 rounds half up to 29.83"
    )
    assert closed["delivered_dose_kgy"] != pytest.approx(29.82, abs=0.001)
    assert closed["max_observed_dose_kgy"] == pytest.approx(31.25, abs=0.001)
    assert closed["status"] == "DOSE_CONFORMING"
    assert get_lot(env["lot"]["id"])["cumulative_dose_kgy"] == pytest.approx(
        29.83, abs=0.001
    )


def test_overdose_branch_uses_the_smallest_product_ceiling_in_the_load():
    """PRD 3.7: "Before the tests run, the server derives a product-side dose
    ceiling: the smallest `max_allowed_dose_kgy` among the distinct products of
    the lots present in this cycle's load map."
    PRD 3.7: "The third test asks whether `max_observed_dose_kgy` is strictly
    greater than the recipe's `max_dose_kgy`, or strictly greater than the
    product-side ceiling, so that a reading landing exactly on either limit
    conforms; if either is exceeded, the verdict is a deviation with
    `deviation_code` `OVERDOSE`."

    Design: Corner/calculations/corner_overdose_branch_uses_the_minimum_product_ceiling_in_the_load
    """
    env = setup_reference_data()
    limited = create_product(
        env["customer"]["id"], product_code="PL", max_allowed_dose_kgy=29.0
    )
    create_qualified_qualification(limited["id"], env["recipe"]["id"])
    lot_a = create_lot(env["customer"]["id"], env["product"]["id"], lot_code="L-P1")
    lot_b = create_lot(env["customer"]["id"], limited["id"], lot_code="L-PL")
    cycle = create_cycle(env["chamber"]["id"], env["recipe"]["id"])
    position_a = add_load_position(
        cycle["id"], lot_a["id"], position_index=1, zone="MIN_DOSE", pallet_count=2
    )
    position_b = add_load_position(
        cycle["id"], lot_b["id"], expected_cycle_version=position_a["cycle_version_after"],
        position_index=2, zone="INTERIOR", pallet_count=2,
    )
    min_dose = place_indicator(
        position_a["id"], indicator_type="DOSIMETER", placement_zone="MIN_DOSE",
        serial_code="D-MIN",
    )
    routine = place_indicator(
        position_b["id"], indicator_type="DOSIMETER", placement_zone="ROUTINE",
        serial_code="D-RT",
    )
    sign_ready(cycle["id"])
    start_cycle(cycle["id"])
    complete_cycle(cycle["id"])
    record_reading(min_dose["id"], measured_dose_kgy=28.50)
    record_reading(routine["id"], measured_dose_kgy=30.00)

    closed = close_dosimetry(cycle["id"])

    assert closed["delivered_dose_kgy"] == pytest.approx(30.00, abs=0.001)
    assert closed["max_observed_dose_kgy"] == pytest.approx(30.00, abs=0.001)
    assert closed["deviation_code"] == "OVERDOSE", (
        "30.00 exceeds the co-loaded product's 29.0 ceiling"
    )
    assert closed["status"] == "DOSE_DEVIATION"
    assert get_lot(lot_a["id"])["quarantine_reason"] == "DOSE_DEVIATION"
    assert get_lot(lot_b["id"])["quarantine_reason"] == "DOSE_DEVIATION"


def test_delivered_dose_exactly_on_the_floor_conforms():
    """PRD 3.7: "The second test asks whether `delivered_dose_kgy` is strictly
    less than the recipe's `min_dose_kgy`, so that a cycle landing exactly on
    the floor conforms; if it is below, the verdict is a deviation with
    `deviation_code` `UNDERDOSE`."
    PRD 3.7: "If none of the three fires, the verdict is conforming and
    `deviation_code` is `NONE`."

    Design: Corner/calculations/corner_delivered_dose_exactly_at_min_dose_conforms
    """
    env = build_cycle_scenario(stage="completed")
    record_reading(env["indicators"]["min_zone"][0]["id"], measured_dose_kgy=27.50)
    record_reading(env["indicators"]["routine"][0]["id"], measured_dose_kgy=27.00)

    closed = close_dosimetry(env["cycle"]["id"])

    assert closed["delivered_dose_kgy"] == pytest.approx(27.00, abs=0.001)
    assert closed["status"] == "DOSE_CONFORMING"
    assert closed["deviation_code"] == "NONE"
    assert closed["max_observed_dose_kgy"] == pytest.approx(27.50, abs=0.001)
    lot = get_lot(env["lot"]["id"])
    assert lot["status"] == "QUARANTINE"
    assert lot["quarantine_reason"] == "ROUTINE"
    assert lot["cumulative_dose_kgy"] == pytest.approx(27.00, abs=0.001)


def test_gamma_start_leaves_the_emission_ledger_untouched():
    """PRD 3.6: "For gamma and electron-beam chambers, `raw_eto_charge_kg` is
    ignored entirely: `abated_eto_kg` is 0.000, `emission_fee_usd` is 0.00, and
    steps three through six are skipped."
    PRD 3.6: "The caller's `X-User-ID` is stamped onto the cycle as
    `operator_user_id` — the first half of the segregation-of-duties pair."

    Design: Corner/calculations/corner_emission_ledger_untouched_for_a_gamma_cycle
    """
    env = build_cycle_scenario(stage="ready")

    started = start_cycle(env["cycle"]["id"])

    assert started["abated_eto_kg"] == pytest.approx(0.0, abs=1e-9)
    assert started["emission_fee_usd"] == pytest.approx(0.0, abs=1e-9)
    assert started["status"] == "RUNNING"
    assert started["operator_user_id"] == "op-1"
    permit = get_permit(env["permit"]["id"])
    assert permit["consumed_kg_ytd"] == pytest.approx(0.0, abs=1e-9)
    assert permit["total_emission_fee_usd"] == pytest.approx(0.0, abs=1e-9)
    assert permit["status"] == "ACTIVE"


def test_aeration_density_factor_is_one_below_the_first_breakpoint():
    """PRD 3.8: "A governing density below 0.1000 grams per cubic centimetre
    gives a `density_factor` of 1.00; a density at or above 0.1000 and below
    0.2000 gives 1.25; a density at or above 0.2000 gives 1.60."
    PRD 3.8: "Under the **`STANDARD`** variant — which is what a freshly opened
    record with a `retest_count` of 0 always uses — `required_hours` is the
    product of `base_hours` and `density_factor`, rounded up to the next whole
    hour by a single ceiling applied to the complete product, and
    `target_end_at` is `aeration_start_at` advanced by that many hours."

    Design: Corner/calculations/corner_aeration_density_factor_low_branch_below_first_breakpoint
    """
    env = build_cycle_scenario(
        stage="closed",
        modality="ETO",
        product_overrides={
            "product_code": "PLOW",
            "pallet_mass_kg": 100.0,
            "pallet_volume_m3": 1.25,
            "requires_aeration": True,
        },
        recipe_overrides={
            "recipe_code": "REL",
            "density_min_g_per_cm3": 0.0700,
            "density_max_g_per_cm3": 0.0900,
            "aeration_base_hours": 12,
        },
    )
    assert get_cycle(env["cycle"]["id"])["load_density_g_per_cm3"] == pytest.approx(
        0.0800, abs=1e-9
    )
    set_clock("2026-08-12T08:00:00Z")

    record = open_aeration_record(env["lot"]["id"])

    assert record["density_factor"] == pytest.approx(1.00, abs=0.001)
    assert record["required_hours"] == 12
    assert record["base_hours"] == 12
    assert record["variant_applied"] == "STANDARD"
    assert record["retest_count"] == 0
    assert_instant_equals(record["target_end_at"], "2026-08-12T20:00:00Z", "target_end_at")
    assert get_lot(env["lot"]["id"])["residual_status"] == "AERATING"


def test_aeration_density_factor_is_one_point_six_on_the_upper_breakpoint():
    """PRD 3.8: "A governing density below 0.1000 grams per cubic centimetre
    gives a `density_factor` of 1.00; a density at or above 0.1000 and below
    0.2000 gives 1.25; a density at or above 0.2000 gives 1.60. A load sitting
    exactly on 0.1000 therefore takes 1.25, not 1.00."

    Design: Corner/calculations/corner_aeration_density_factor_high_branch_at_upper_breakpoint
    """
    env = build_cycle_scenario(
        stage="closed",
        modality="ETO",
        product_overrides={
            "product_code": "PHI",
            "pallet_mass_kg": 240.0,
            "pallet_volume_m3": 1.2,
            "requires_aeration": True,
        },
        recipe_overrides={
            "recipe_code": "REH",
            "density_min_g_per_cm3": 0.2000,
            "density_max_g_per_cm3": 0.2100,
            "aeration_base_hours": 12,
        },
    )
    assert get_cycle(env["cycle"]["id"])["load_density_g_per_cm3"] == pytest.approx(
        0.2000, abs=1e-9
    )
    set_clock("2026-08-12T08:00:00Z")

    record = open_aeration_record(env["lot"]["id"])

    assert record["density_factor"] == pytest.approx(1.60, abs=0.001)
    assert record["required_hours"] == 20, "ceil(12 * 1.60) == 20"
    assert record["required_hours"] != 15
    assert_instant_equals(record["target_end_at"], "2026-08-13T04:00:00Z", "target_end_at")


def test_residual_readings_exactly_on_the_limits_pass():
    """PRD 3.8: "The verdict is a pass when `eto_residual_ppm` is at or below
    the product's `eto_residual_limit_ppm` **and** `ech_residual_ppm` is at or
    below the product's `ech_residual_limit_ppm`; both comparisons are
    inclusive, so a reading landing exactly on a limit passes. A pass carries
    the record `IN_PROGRESS → PASSED` or `RETEST_REQUIRED → PASSED`, and the
    lot `AERATING → RESIDUAL_PASS`, which is what makes the lot releasable on
    the residual axis."

    Design: Corner/calculations/corner_residual_verdict_passes_at_exact_ppm_limits
    """
    env = build_cycle_scenario(
        stage="closed", modality="ETO", product_overrides={"requires_aeration": True}
    )
    set_clock("2026-08-12T08:00:00Z")
    record = open_aeration_record(env["lot"]["id"])
    set_clock("2026-08-12T23:00:00Z")

    tested = record_residual_test(
        record["id"], eto_residual_ppm=4.0, ech_residual_ppm=9.0
    )

    assert tested["status"] == "PASSED"
    assert tested["retest_count"] == 0
    assert tested["variant_applied"] == "STANDARD"
    assert tested["last_eto_ppm"] == pytest.approx(4.0, abs=0.001)
    assert tested["last_ech_ppm"] == pytest.approx(9.0, abs=0.001)
    lot = get_lot(env["lot"]["id"])
    assert lot["residual_status"] == "RESIDUAL_PASS"
    assert lot["status"] == "QUARANTINE"


def test_dose_audit_sample_size_must_be_exactly_one_hundred():
    """PRD 3.3: "`samples_tested`, which the VDmax method fixes at exactly 100
    so that any other value is refused as a schema violation"
    PRD 2.7: "**Payload schema.** On every write, required fields are present,
    types are correct, enum members are recognised and numeric ranges hold —
    `pallet_count` at least 1, `positives` between 0 and `samples_tested`
    inclusive, `samples_tested` exactly 100"

    Design: Corner/calculations/corner_vdmax_sample_size_must_be_exactly_one_hundred
    """
    env = setup_reference_data(qualify=False)

    response = api_client.create_dose_audit(
        env["qualification"]["id"],
        {
            "performed_at": "2026-08-05T00:00:00Z",
            "samples_tested": 99,
            "positives": 0,
            "verification_dose_kgy_applied": 12.5,
        },
        ADMIN,
    )

    validate_error(response, ApiErrorId.ERR_VALIDATION)
    assert get_qualification(env["qualification"]["id"])["status"] == "PENDING"
    _, meta = validate_paginated(
        api_client.list_dose_audits(env["qualification"]["id"], ADMIN)
    )
    assert meta["total_count"] == 0


def test_governing_cycle_is_the_latest_surviving_load_position():
    """PRD 3.8: "Among all load positions referencing that lot, the server
    ranks them by `created_at` descending — compared at millisecond resolution
    — and breaks ties by `position_index` ascending; the cycle behind the first
    row of that ranking is the lot's **governing cycle**. Identifier values are
    never used as an ordering key."
    PRD 3.9: "`release_mode` records the pathway used, `released_at` records
    the current logical-clock instant, `released_by_user_id` records the
    officer's `X-User-ID`, and `release_dose_kgy` snapshots the governing
    cycle's `delivered_dose_kgy` so that the released record is immune to any
    later re-read of the cycle."

    Design: Corner/calculations/corner_governing_cycle_is_the_latest_surviving_load_position
    """
    env = setup_reference_data()
    lot = create_lot(env["customer"]["id"], env["product"]["id"])
    cycle_a = create_cycle(env["chamber"]["id"], env["recipe"]["id"], cycle_code="C-A")
    add_load_position(cycle_a["id"], lot["id"], position_index=1, pallet_count=2)
    abort_cycle(cycle_a["id"], reason="chamber conveyor fault before dwell")

    cycle_b = create_cycle(
        env["chamber"]["id"],
        env["recipe"]["id"],
        cycle_code="C-B",
        scheduled_start_at="2026-08-12T00:00:00Z",
        scheduled_end_at="2026-08-12T06:00:00Z",
    )
    position_b = add_load_position(
        cycle_b["id"], lot["id"], position_index=1, pallet_count=2
    )
    min_dose = place_indicator(
        position_b["id"], indicator_type="DOSIMETER", placement_zone="MIN_DOSE",
        serial_code="D-MIN",
    )
    routine = place_indicator(
        position_b["id"], indicator_type="DOSIMETER", placement_zone="ROUTINE",
        serial_code="D-RT",
    )
    sign_ready(cycle_b["id"])
    start_cycle(cycle_b["id"])
    complete_cycle(cycle_b["id"])
    record_reading(min_dose["id"], measured_dose_kgy=29.00)
    record_reading(routine["id"], measured_dose_kgy=31.00)
    close_dosimetry(cycle_b["id"])

    released = release_lot(lot["id"], "PARAMETRIC")

    assert get_cycle(cycle_a["id"])["status"] == "CANCELLED"
    assert get_cycle(cycle_b["id"])["delivered_dose_kgy"] == pytest.approx(31.00, abs=0.001)
    assert released["release_dose_kgy"] == pytest.approx(31.00, abs=0.001)
    assert released["release_mode"] == "PARAMETRIC"
    assert released["released_by_user_id"] == "qro-1"
    assert released["cumulative_dose_kgy"] == pytest.approx(31.00, abs=0.001)

    rows, meta = validate_paginated(
        api_client.list_load_positions(operator(), params={"lot_id": lot["id"]})
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == position_b["id"]


def test_emission_fee_uses_the_third_tier_above_two_hundred_kilograms():
    """PRD 3.2: "Above 200.000 kilograms the rate is 27.00 dollars per abated
    kilogram."
    PRD 3.6: "**Step five** computes `emission_fee_usd` as the abated mass
    multiplied by that rate, rounded half up to two decimal places."

    Design: Corner/calculations/corner_emission_fee_third_tier_above_two_hundred_kg
    """
    env = build_cycle_scenario(
        stage="ready", modality="ETO", cycle_overrides={"raw_eto_charge_kg": 6000.0}
    )

    started = start_cycle(env["cycle"]["id"])

    assert started["abated_eto_kg"] == pytest.approx(240.000, abs=1e-6)
    assert started["emission_fee_usd"] == pytest.approx(6480.00, abs=0.001)
    permit = get_permit(env["permit"]["id"])
    assert permit["consumed_kg_ytd"] == pytest.approx(240.000, abs=1e-6)
    assert permit["total_emission_fee_usd"] == pytest.approx(6480.00, abs=0.001)
    assert permit["status"] == "ACTIVE"


def test_a_lot_in_two_slots_of_one_cycle_is_credited_once():
    """PRD 3.7: "Finally the lifetime dose ledger is posted: taking the
    distinct lots referenced by this cycle's load positions, processed in
    ascending `created_at` order of their load positions and, where two
    positions share an instant, in ascending `position_index` order, each lot's
    `cumulative_dose_kgy` becomes its previous value plus the cycle's
    `delivered_dose_kgy`, rounded half up to two decimal places at each
    accumulation step. A lot occupying several slots of the same cycle is
    credited exactly once, because the distinct set of lots is used rather than
    the set of position rows."

    Design: Corner/calculations/corner_lot_cumulative_dose_credits_a_lot_once_per_cycle
    """
    env = setup_reference_data()
    lot = create_lot(env["customer"]["id"], env["product"]["id"], total_pallet_count=4)
    cycle = create_cycle(env["chamber"]["id"], env["recipe"]["id"])
    first = add_load_position(
        cycle["id"], lot["id"], position_index=1, zone="MIN_DOSE", pallet_count=2
    )
    add_load_position(
        cycle["id"], lot["id"], expected_cycle_version=first["cycle_version_after"],
        position_index=2, zone="INTERIOR", pallet_count=2,
    )
    min_dose = place_indicator(
        first["id"], indicator_type="DOSIMETER", placement_zone="MIN_DOSE",
        serial_code="D-MIN",
    )
    routine = place_indicator(
        first["id"], indicator_type="DOSIMETER", placement_zone="ROUTINE",
        serial_code="D-RT",
    )
    sign_ready(cycle["id"])
    start_cycle(cycle["id"])
    complete_cycle(cycle["id"])
    record_reading(min_dose["id"], measured_dose_kgy=28.50)
    record_reading(routine["id"], measured_dose_kgy=30.00)

    closed = close_dosimetry(cycle["id"])

    assert closed["delivered_dose_kgy"] == pytest.approx(30.00, abs=0.001)
    assert closed["status"] == "DOSE_CONFORMING"
    assert closed["load_density_g_per_cm3"] == pytest.approx(0.1000, abs=1e-9)
    assert closed["loaded_pallet_count"] == 4
    lot_after = get_lot(lot["id"])
    assert lot_after["cumulative_dose_kgy"] == pytest.approx(30.00, abs=0.001)
    assert lot_after["cumulative_dose_kgy"] != pytest.approx(60.00, abs=0.001)
    assert lot_after["status"] == "QUARANTINE"
    assert lot_after["staged_pallet_count"] == 4
