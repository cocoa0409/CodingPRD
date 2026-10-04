"""Corner queue (calculations): carbon equivalent precision, charge-cost
rounding order, scrap tier boundaries and recovery, cure scores, and the sand
reclamation rate bands."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_iron_mass_conserved,
    certify_melt,
    charge_melt,
    create_mold_for_order,
    create_permit,
    create_seasoning_batch,
    expected_charge_lines_cents,
    get_melt,
    get_mold,
    get_order,
    get_permit,
    get_seasoning_batch,
    get_unit,
    inspect_unit_pass,
    pour_units,
    qa_release,
    record_chemistry,
    reclaim_mold,
    scrap_unit_via_defect,
    setup_baking_batch,
    setup_charging_melt,
    setup_shaken_units,
    validate_error,
)

_FM = TEST_USERS["foundry_manager_headers"]
_QI = TEST_USERS["quality_inspector_headers"]
_SL = TEST_USERS["seasoning_lead_headers"]


def test_carbon_equivalent_upper_bound_inclusive_passes(api):
    """PRD §3.3: "A decision of `CERTIFY` accepts the chemistry only when
    `carbon_equivalent` lies within the inclusive band from 3.90 to 4.30 — a value
    of exactly 4.30 passes while 4.31 fails"
    3.30 + (2.99 + 0.010)/3 == 4.30 exactly, so CERTIFY succeeds.

    Design: Corner/calculations/carbon_equivalent_upper_bound_inclusive_passes
    """
    ctx = setup_charging_melt()
    batch_id = ctx["melt"]["id"]
    charge_melt(batch_id)
    record_chemistry(batch_id)
    melt = get_melt(batch_id)
    assert melt["carbon_equivalent"] == pytest.approx(4.30, abs=1e-9)
    melt = certify_melt(batch_id, decision="CERTIFY")
    assert melt["state"] == "CERTIFIED"


def test_carbon_equivalent_rounds_4305_up_and_rejects(api):
    """PRD §2.7: "The melt chemistry value `carbon_equivalent` and the iron-ledger
    values `slag_loss_lbs` and `returns_credit_lbs` are carried to 2 decimal places
    with round-half-up."
    PRD §3.3: "a value of exactly 4.30 passes while 4.31 fails"
    3.30 + (3.00 + 0.015)/3 == 4.305, which round-half-up at 2dp makes 4.31 — over
    the cap — so CERTIFY is rejected and the batch stays in CHEMISTRY_CHECK.

    Design: Corner/calculations/carbon_equivalent_rounds_4305_up_and_rejects
    """
    ctx = setup_charging_melt()
    batch_id = ctx["melt"]["id"]
    charge_melt(batch_id)
    record_chemistry(batch_id, carbon_pct=3.30, silicon_pct=3.00,
                     phosphorus_pct=0.015)
    melt = get_melt(batch_id)
    assert melt["carbon_equivalent"] == pytest.approx(4.31, abs=1e-9), (
        f"carbon_equivalent {melt['carbon_equivalent']} != 4.31 "
        "(round-half-up of 4.305)")
    resp = api.certify_chemistry(batch_id, {"decision": "CERTIFY"}, _QI)
    validate_error(resp, ApiErrorId.ERR_CHEMISTRY_OUT_OF_SPEC)
    assert get_melt(batch_id)["state"] == "CHEMISTRY_CHECK"


def test_charge_cost_per_line_rounding_beats_sum_rounding(api):
    """PRD §3.3: "Summing the raw products and rounding once at the end is a
    different, forbidden order."
    pig 100 / scrap 10.5 / returns 10.716 / alloy 0.25 lbs: per-line rounding gives
    3800 + 126 + 64 + 36 == 4026; the forbidden sum-then-round order would give
    round(4026.546) == 4027.

    Design: Corner/calculations/charge_cost_per_line_rounding_beats_sum_rounding
    """
    ctx = setup_charging_melt()
    charged = charge_melt(ctx["melt"]["id"], pig_iron_lbs=100,
                          scrap_steel_lbs=10.5, returns_lbs=10.716,
                          alloy_lbs=0.25)
    assert charged["actual_charge_cost_cents"] == 4026
    assert charged["actual_charge_cost_cents"] == expected_charge_lines_cents(
        100, 10.5, 10.716, 0.25)
    assert charged["actual_charge_cost_cents"] != 4027


def test_scrap_tier_watch_at_exactly_four_percent(api):
    """PRD §2.8: "Both band lower bounds are inclusive — a `scrap_index` of exactly
    0.0400 is `WATCH`, not `GREEN`, and exactly 0.0800 is `RED`."
    One plain scrap over 25 poured -> 0.0400 -> WATCH with posture still OPEN, so
    the seasoning line still accepts the order's FINISHED unit.

    Design: Corner/calculations/scrap_tier_watch_at_exactly_four_percent
    """
    ctx = setup_shaken_units(num_units=25, order_overrides={"planned_quantity": 30})
    u1, u2 = ctx["unit_ids"][0], ctx["unit_ids"][1]
    scrap_unit_via_defect(u1, defect_type="POROSITY", severity="MINOR")
    inspect_unit_pass(u2)
    order = get_order(ctx["order"]["id"])
    assert order["scrap_index"] == pytest.approx(0.04, abs=1e-9)
    assert order["scrap_tier"] == "WATCH"
    assert order["posture"] == "OPEN"
    batch = create_seasoning_batch(ctx["order"]["id"], [u2])
    assert batch["unit_count"] == 1
    assert get_unit(u2)["state"] == "SEASONING_QUEUED"


def test_scrap_index_recovery_reopens_posture(api):
    """PRD §2.8: "Posture is recomputed on the same triggers that recompute scrap
    tiering — every defect-disposition scrap and every pour"
    At 2.0 / 25 == 0.0800 the order is RESTRICTED; a further 25-unit pour (pours
    require only a non-FROZEN posture) dilutes the ratio to 2.0 / 50 == 0.0400 ->
    WATCH -> OPEN.

    Design: Corner/calculations/scrap_index_recovery_reopens_posture
    """
    ctx = setup_shaken_units(num_units=25, order_overrides={"planned_quantity": 60})
    scrap_unit_via_defect(ctx["unit_ids"][0], defect_type="POROSITY",
                          severity="MINOR")
    scrap_unit_via_defect(ctx["unit_ids"][1], defect_type="MISRUN",
                          severity="MINOR")
    order = get_order(ctx["order"]["id"])
    assert order["posture"] == "RESTRICTED"
    mold2 = create_mold_for_order(ctx["order"]["id"])
    pour_units(ctx["melt"]["id"], mold2["id"], unit_count=25)
    order = get_order(ctx["order"]["id"])
    assert order["poured_units"] == 50
    assert order["scrap_weighted_units"] == pytest.approx(2.0, abs=1e-9)
    assert order["scrap_index"] == pytest.approx(0.04, abs=1e-9)
    assert order["scrap_tier"] == "WATCH"
    assert order["posture"] == "OPEN"
    melt = get_melt(ctx["melt"]["id"])
    assert melt["remaining_iron_lbs"] == pytest.approx(1549.7, abs=1e-9)
    assert_iron_mass_conserved(melt)


def test_cure_score_87_release_allowed(api):
    """PRD §3.6: "The `cure_score` is 60 times the temperature factor plus 40 times
    the duration factor, rounded half-up to an integer between 0 and 100."
    PRD §3.6: "and it requires a `cure_score` of at least 70, otherwise the release
    is rejected with `ERR_CURE_PROFILE_VIOLATION` (HTTP 422)."
    SOYBEAN at the band midpoint 475F for exactly 60 minutes: temp_factor 1.0 and
    duration_factor (60/60)/1.5 give round_half_up(60 + 26.6667) == 87 >= 70.

    Design: Corner/calculations/cure_score_87_release_allowed
    """
    ctx = setup_baking_batch(num_units=1, order_overrides={"planned_quantity": 5})
    batch = qa_release(ctx["seasoning_batch"]["id"], bake_duration_min=60,
                       food_safety_verified=True, decision="RELEASE")
    assert batch["cure_score"] == 87
    assert batch["state"] == "RELEASED"
    assert get_unit(ctx["unit_ids"][0])["state"] == "SEASONED"
    assert get_order(ctx["order"]["id"])["good_units"] == 1


def test_cure_score_51_release_rejected_then_fail(api):
    """PRD §3.6: "The temperature factor is 1 minus the absolute distance of
    `actual_bake_temp_f` from the band midpoint, divided by the band's half-width"
    PRD §3.6: "and it requires a `cure_score` of at least 70, otherwise the release
    is rejected with `ERR_CURE_PROFILE_VIOLATION` (HTTP 422)."
    SOYBEAN at 460F (|460-475|/25 -> temp_factor 0.4) for 60 minutes scores
    round_half_up(24 + 26.6667) == 51 < 70; the batch stays BAKING, and the
    fallback FAIL decision then closes it.

    Design: Corner/calculations/cure_score_51_release_rejected_then_fail
    """
    ctx = setup_baking_batch(num_units=1, order_overrides={"planned_quantity": 5},
                             bake_overrides={"actual_bake_temp_f": 460})
    batch_id = ctx["seasoning_batch"]["id"]
    resp = api.qa_release_seasoning_batch(
        batch_id, {"bake_duration_min": 60, "food_safety_verified": True,
                   "decision": "RELEASE"}, _QI)
    validate_error(resp, ApiErrorId.ERR_CURE_PROFILE_VIOLATION)
    assert get_seasoning_batch(batch_id)["state"] == "BAKING"
    batch = qa_release(batch_id, bake_duration_min=60, food_safety_verified=True,
                       decision="FAIL")
    assert batch["state"] == "FAILED"
    assert batch["cure_score"] == 51
    unit = get_unit(ctx["unit_ids"][0])
    assert unit["state"] == "FINISHED"
    assert unit["seasoning_batch_id"] is None


def _mold_shaken_with_sand_permit():
    """SAND_RECLAMATION permit at 0.90 plus one poured+shaken 500-lb mold."""
    permit = create_permit("SAND_RECLAMATION", limit_value=0.90)
    ctx = setup_shaken_units(num_units=1, order_overrides={"planned_quantity": 5})
    return permit, ctx


def test_sand_reclamation_rate_warning_band(api):
    """PRD §3.4: "a rate below `limit_value` but still within 0.05 of it moves an
    `ACTIVE` permit to `WARNING`; a rate more than 0.05 below `limit_value` drives
    the permit to `BREACH` from any non-terminal status and records the reclaiming
    officer's `X-User-ID` in `last_breach_reading_recorded_by`"
    PRD §3.4: "must not exceed 12 percent of `sand_weight_lbs`, with a loss of
    exactly 12 percent allowed"

    Re-derivation note: the design YAML claims 380/500 -> rate 0.7600 lands in the
    WARNING band, but 0.7600 is more than 0.05 below the 0.90 limit
    (0.90 - 0.05 = 0.85), so PRD §3.4 uniquely derives BREACH on these inputs;
    that PRD-derived outcome is asserted here. The 12%-loss-inclusivity half of
    the recipe stands: the reclaim itself is accepted.

    Design: Corner/calculations/sand_reclamation_rate_warning_band
    """
    permit, ctx = _mold_shaken_with_sand_permit()
    mold = reclaim_mold(ctx["mold"]["id"], reclaimed_sand_lbs=380,
                        dust_collected_lbs=60)
    assert mold["state"] == "SAND_RECLAIMED"
    assert mold["reclaim_loss_lbs"] == pytest.approx(60.0, abs=1e-9)
    permit = get_permit(permit["id"])
    assert permit["current_sand_rate"] == pytest.approx(0.76, abs=1e-9)
    assert permit["status"] == "BREACH"
    assert permit["last_breach_reading_recorded_by"] == "eo-1"


def test_sand_reclamation_rate_breach_blocks_mold_create(api):
    """PRD §3.4: "if the `SAND_RECLAMATION` permit exists and is in `BREACH`, mold
    creation is rejected with `ERR_EMISSIONS_PERMIT_BREACH`."
    A reclaim at 400/500 -> rate 0.8000 < 0.85 breaches the permit directly from
    ACTIVE; the breach then blocks new mold preparation while the TAPPED melt is
    untouched (the hold cascade is AIR-only).

    Design: Corner/calculations/sand_reclamation_rate_breach_blocks_mold_create
    """
    permit, ctx = _mold_shaken_with_sand_permit()
    reclaim_mold(ctx["mold"]["id"], reclaimed_sand_lbs=400, dust_collected_lbs=60)
    permit = get_permit(permit["id"])
    assert permit["status"] == "BREACH"
    assert permit["current_sand_rate"] == pytest.approx(0.80, abs=1e-9)
    assert permit["last_breach_reading_recorded_by"] == "eo-1"
    resp = api.create_mold(
        {"production_order_id": ctx["order"]["id"], "new_sand_pct": 20.0,
         "reclaimed_sand_pct": 80.0, "moisture_pct": 3.8, "clay_pct": 10.0,
         "sand_weight_lbs": 500}, _FM)
    validate_error(resp, ApiErrorId.ERR_EMISSIONS_PERMIT_BREACH)
    assert get_melt(ctx["melt"]["id"])["state"] == "TAPPED"


def test_sand_loss_over_twelve_percent_rejected(api):
    """PRD §3.4: "the implied `reclaim_loss_lbs` — the `sand_weight_lbs` minus the
    reclaimed sand minus the collected dust — must not exceed 12 percent of
    `sand_weight_lbs`, with a loss of exactly 12 percent allowed; a violation is
    rejected with `ERR_SAND_LOSS_EXCEEDED` (HTTP 422)."
    Reclaiming 300 with 60 dust from a 500-lb mold implies a 140-lb loss (28%).

    Design: Corner/calculations/sand_loss_over_twelve_percent_rejected
    """
    ctx = setup_shaken_units(num_units=1, order_overrides={"planned_quantity": 5})
    resp = api.reclaim_mold(ctx["mold"]["id"],
                            {"reclaimed_sand_lbs": 300, "dust_collected_lbs": 60},
                            TEST_USERS["environmental_officer_headers"])
    validate_error(resp, ApiErrorId.ERR_SAND_LOSS_EXCEEDED)
    mold = get_mold(ctx["order"]["id"], ctx["mold"]["id"])
    assert mold["state"] == "SHAKEOUT_DONE"
    assert mold["reclaimed_sand_lbs"] is None
