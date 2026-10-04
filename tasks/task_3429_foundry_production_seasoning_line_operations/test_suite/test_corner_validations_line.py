"""Corner queue (validations, production line): mold-order matching, seasoning
unit composition, iron sufficiency, completion yield, inspection tolerances,
food safety, and the disposition rules."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    certify_melt,
    charge_melt,
    create_melt,
    create_mold_for_order,
    create_order,
    create_product,
    create_seasoning_batch,
    create_seasoning_batch_payload,
    disposition_report,
    get_melt,
    get_mold,
    get_order,
    get_success_data,
    get_unit,
    inspect_unit_defect,
    inspect_unit_pass,
    pour_units,
    qa_release,
    record_chemistry,
    release_order,
    scrap_unit_via_defect,
    setup_baking_batch,
    setup_released_order,
    setup_shaken_units,
    setup_tapped_melt,
    shakeout,
    start_bake,
    tap_melt,
    validate_error,
    validate_paginated,
)

_FM = TEST_USERS["foundry_manager_headers"]
_OP = TEST_USERS["melt_operator_headers"]
_QI = TEST_USERS["quality_inspector_headers"]
_SL = TEST_USERS["seasoning_lead_headers"]


def test_mold_order_mismatch_rejected(api):
    """PRD §3.4: "The mold must belong to the same production order as the melt
    batch — if the mold's `production_order_id` differs from the batch's, the pour
    is rejected with `ERR_MOLD_ORDER_MISMATCH` (HTTP 422)"
    Both orders make the same product and every other check passes; the cross-order
    mold alone dooms the pour, with no partial side effects.

    Design: Corner/validations/mold_order_mismatch_rejected
    """
    product = create_product()
    o1 = release_order(create_order(product["id"])["id"])
    o2 = release_order(create_order(product["id"], scheduled_week=41)["id"])
    melt = create_melt(o1["id"])
    charge_melt(melt["id"])
    record_chemistry(melt["id"])
    certify_melt(melt["id"])
    tap_melt(melt["id"])
    mold = create_mold_for_order(o2["id"])
    resp = api.pour_melt_batch(
        melt["id"], {"mold_id": mold["id"], "unit_count": 1,
                     "pour_weight_per_unit_oz": 128.0}, _OP)
    validate_error(resp, ApiErrorId.ERR_MOLD_ORDER_MISMATCH)
    assert get_mold(o2["id"], mold["id"])["state"] == "PREPARED"
    assert get_melt(melt["id"])["poured_lbs"] == 0


def test_seasoning_units_from_two_orders_rejected(api):
    """PRD §3.6: "The unit list must be non-empty, contain at most 12 units, and
    every listed unit must currently be `FINISHED` and belong to the named order;
    an empty list, an oversized batch, or a foreign unit is rejected with
    `ERR_UNITS_NOT_SAME_ORDER` (HTTP 422)."
    O1 is seasoning-eligible (POURING) but the listed unit belongs to O2.

    Design: Corner/validations/seasoning_units_from_two_orders_rejected
    """
    product = create_product()
    # O1: released and poured once (POURING) so the state gate passes.
    o1 = release_order(create_order(product["id"])["id"])
    melt1 = create_melt(o1["id"])
    charge_melt(melt1["id"])
    record_chemistry(melt1["id"])
    certify_melt(melt1["id"])
    tap_melt(melt1["id"])
    mold1 = create_mold_for_order(o1["id"])
    pour_units(melt1["id"], mold1["id"], unit_count=1)
    # O2: one unit walked to FINISHED.
    o2 = release_order(create_order(product["id"], planned_quantity=5,
                                    scheduled_week=41)["id"])
    melt2 = create_melt(o2["id"], furnace_id="FURNACE_B")
    charge_melt(melt2["id"])
    record_chemistry(melt2["id"])
    certify_melt(melt2["id"])
    tap_melt(melt2["id"])
    mold2 = create_mold_for_order(o2["id"])
    foreign_unit = pour_units(melt2["id"], mold2["id"], unit_count=1)[0]["id"]
    shakeout(mold2["id"])
    inspect_unit_pass(foreign_unit)

    payload = create_seasoning_batch_payload(o1["id"], [foreign_unit])
    resp = api.create_seasoning_batch(payload, _SL)
    validate_error(resp, ApiErrorId.ERR_UNITS_NOT_SAME_ORDER)
    assert get_unit(foreign_unit)["state"] == "FINISHED"
    _, meta = validate_paginated(api.list_seasoning_batches(
        _SL, params={"production_order_id": o1["id"]}))
    assert meta["total_count"] == 0


def test_pour_exceeding_remaining_iron_rejected(api):
    """PRD §3.4: "the pour's total weight, computed as `unit_count` times
    `pour_weight_per_unit_oz` divided by 16.0 pounds, must not exceed the batch's
    `remaining_iron_lbs`; equality is allowed and leaves the batch empty, while a
    shortfall is rejected with `ERR_INSUFFICIENT_IRON` (HTTP 422)."
    A 60-lb tap leaves 60 - 1.8 == 58.2 lbs; 8 x 8 == 64 lbs exceeds it.

    Design: Corner/validations/pour_exceeding_remaining_iron_rejected
    """
    ctx = setup_tapped_melt(tap_overrides={"tapped_lbs": 60})
    mold = create_mold_for_order(ctx["order"]["id"])
    resp = api.pour_melt_batch(
        ctx["melt"]["id"], {"mold_id": mold["id"], "unit_count": 8,
                            "pour_weight_per_unit_oz": 128.0}, _OP)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_IRON)
    melt = get_melt(ctx["melt"]["id"])
    assert melt["state"] == "TAPPED"
    assert melt["poured_lbs"] == 0
    assert melt["remaining_iron_lbs"] == pytest.approx(58.2, abs=1e-9)
    assert get_mold(ctx["order"]["id"], mold["id"])["state"] == "PREPARED"


def test_complete_below_yield_rejected(api):
    """PRD §3.2: "the yield gate requires `good_units` to be at least the ceiling
    of 0.85 times `planned_quantity`, otherwise the completion is rejected with
    `ERR_YIELD_BELOW_MINIMUM` (HTTP 422)."
    Planned 10 needs 9 good; with one unit scrapped and 8 seasoned (plus 15
    recovery pours diluting the index back to OPEN), completion is rejected and
    unit_cost_final_cents stays null.

    Design: Corner/validations/complete_below_yield_rejected
    """
    ctx = setup_shaken_units(num_units=10)  # planned_quantity 10
    unit_ids = ctx["unit_ids"]
    scrap_unit = unit_ids[0]
    scrap_unit_via_defect(scrap_unit, defect_type="POROSITY", severity="MINOR")
    # Recovery pours: 15 more units dilute 1.0/10 == 0.1000 to 1.0/25 == 0.0400.
    mold2 = create_mold_for_order(ctx["order"]["id"])
    pour_units(ctx["melt"]["id"], mold2["id"], unit_count=15)
    order = get_order(ctx["order"]["id"])
    assert order["posture"] == "OPEN"
    good_ids = unit_ids[1:9]  # 8 units pass and season
    for uid in good_ids:
        inspect_unit_pass(uid)
    batch = create_seasoning_batch(ctx["order"]["id"], good_ids)
    start_bake(batch["id"])
    qa_release(batch["id"])
    assert get_order(ctx["order"]["id"])["good_units"] == 8
    resp = api.complete_production_order(
        ctx["order"]["id"], {"labor_hours_actual": 40, "energy_kwh_actual": 900},
        _FM)
    validate_error(resp, ApiErrorId.ERR_YIELD_BELOW_MINIMUM)
    order = get_order(ctx["order"]["id"])
    assert order["state"] == "SEASONING"
    assert order["unit_cost_final_cents"] is None


def test_tolerance_boundary_weight_pass_and_fail(api):
    """PRD §3.5: "An `outcome` of `PASS` enforces the product's physical
    specification, with every bound inclusive: the absolute difference between
    `measured_weight_oz` and the product's `target_weight_oz` must not exceed
    `weight_tolerance_oz`"
    134.0 oz is exactly 128.0 + 6.0 and passes; 134.1 oz fails and the unit stays
    SHAKEOUT_DONE.

    Design: Corner/validations/tolerance_boundary_weight_pass_and_fail
    """
    ctx = setup_shaken_units(num_units=2)
    u1, u2 = ctx["unit_ids"]
    resp1 = api.inspect_casting_unit(
        u1, {"outcome": "PASS", "measured_weight_oz": 134.0,
             "measured_diameter_in": 10.25, "measured_wall_thickness_in": 0.19},
        _QI)
    assert resp1.status_code == 200, resp1.text
    assert get_unit(u1)["state"] == "FINISHED"
    resp2 = api.inspect_casting_unit(
        u2, {"outcome": "PASS", "measured_weight_oz": 134.1,
             "measured_diameter_in": 10.25, "measured_wall_thickness_in": 0.19},
        _QI)
    validate_error(resp2, ApiErrorId.ERR_TOLERANCE_EXCEEDED)
    assert get_unit(u2)["state"] == "SHAKEOUT_DONE"


def test_food_safety_unverified_release_rejected(api):
    """PRD §3.6: "A `decision` of `RELEASE` requires `food_safety_verified` to be
    true — the inspector attests that the oil lot and COA documentation match the
    batch — otherwise the release is rejected with `ERR_FOOD_SAFETY_INCOMPLETE`
    (HTTP 422)"
    The food-safety gate fires even though the 475F/60min bake would score 87.

    Design: Corner/validations/food_safety_unverified_release_rejected
    """
    ctx = setup_baking_batch(num_units=1, order_overrides={"planned_quantity": 5})
    batch_id = ctx["seasoning_batch"]["id"]
    resp = api.qa_release_seasoning_batch(
        batch_id, {"bake_duration_min": 60, "food_safety_verified": False,
                   "decision": "RELEASE"}, _QI)
    validate_error(resp, ApiErrorId.ERR_FOOD_SAFETY_INCOMPLETE)
    assert get_success_data(api.get_seasoning_batch(batch_id, _SL))["state"] == "BAKING"
    assert get_unit(ctx["unit_ids"][0])["state"] == "SEASONING_QUEUED"


def test_critical_defect_rework_disposition_rejected(api):
    """PRD §3.5: "A `disposition` of `REWORK` requires the report's `severity` to
    be anything other than `CRITICAL` — a critical defect must be scrapped, and
    requesting rework on one is rejected with
    `ERR_CRITICAL_DEFECT_MUST_SCRAP` (HTTP 422)"
    SCRAP remains available and closes the report.

    Design: Corner/validations/critical_defect_rework_disposition_rejected
    """
    ctx = setup_shaken_units(num_units=1)
    unit_id = ctx["unit_ids"][0]
    _, report_id = inspect_unit_defect(unit_id, defect_type="CRACK",
                                       severity="CRITICAL")
    resp = api.disposition_defect_report(report_id, {"disposition": "REWORK"}, _QI)
    validate_error(resp, ApiErrorId.ERR_CRITICAL_DEFECT_MUST_SCRAP)
    report = disposition_report(report_id, "SCRAP")
    assert report["status"] == "DISPOSITIONED"
    unit = get_unit(unit_id)
    assert unit["state"] == "SCRAPPED"
    assert unit["scrap_reason"] == "DEFECT"


def test_use_as_is_major_defect_rejected(api):
    """PRD §3.5: "A `disposition` of `USE_AS_IS` requires `severity` `MINOR` and is
    otherwise rejected with `ERR_USE_AS_IS_MINOR_ONLY` (HTTP 422)"
    The MAJOR report cannot be used as-is, but REWORK is legal on it
    (rework_count 0 < 2, severity not CRITICAL).

    Design: Corner/validations/use_as_is_major_defect_rejected
    """
    ctx = setup_shaken_units(num_units=1)
    unit_id = ctx["unit_ids"][0]
    _, report_id = inspect_unit_defect(unit_id, defect_type="SAND_INCLUSION",
                                       severity="MAJOR")
    resp = api.disposition_defect_report(report_id, {"disposition": "USE_AS_IS"},
                                         _QI)
    validate_error(resp, ApiErrorId.ERR_USE_AS_IS_MINOR_ONLY)
    disposition_report(report_id, "REWORK")
    unit = get_unit(unit_id)
    assert unit["state"] == "REWORK"
    assert unit["rework_count"] == 1


def test_sand_mix_reclaimed_over_85_rejected(api):
    """PRD §3.4: "the sand recipe: `new_sand_pct` and `reclaimed_sand_pct` must sum
    to exactly 100.0 within a tolerance of 0.01, `reclaimed_sand_pct` may not
    exceed 85.0, `moisture_pct` must lie within the inclusive range 3.0 to 4.5,
    `clay_pct` must lie within the inclusive range 8.0 to 12.0, and
    `sand_weight_lbs` must be greater than zero; any violation is rejected with
    `ERR_SAND_MIX_VIOLATION` (HTTP 422)."
    85.0% reclaimed is the inclusive cap (accepted); 86.0% is rejected.

    Design: Corner/validations/sand_mix_reclaimed_over_85_rejected
    """
    ctx = setup_released_order()
    ok = create_mold_for_order(ctx["order"]["id"], new_sand_pct=15.0,
                               reclaimed_sand_pct=85.0)
    assert ok["state"] == "PREPARED"
    resp = api.create_mold(
        {"production_order_id": ctx["order"]["id"], "new_sand_pct": 14.0,
         "reclaimed_sand_pct": 86.0, "moisture_pct": 3.8, "clay_pct": 10.0,
         "sand_weight_lbs": 500}, _FM)
    validate_error(resp, ApiErrorId.ERR_SAND_MIX_VIOLATION)
