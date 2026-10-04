"""Difficulty queue: transitive cascades — the AIR_EMISSIONS breach freeze/thaw
chain and the defect-scrap posture cascade that blocks seasoning."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    acknowledge_breach,
    certify_melt,
    certify_remediation,
    charge_melt,
    create_melt,
    create_mold_for_order,
    create_permit,
    get_melt,
    get_order,
    get_permit,
    get_unit,
    inspect_unit_pass,
    record_chemistry,
    record_reading,
    scrap_unit_via_defect,
    setup_released_order,
    setup_shaken_units,
    tap_melt,
    validate_error,
)

_OP = TEST_USERS["melt_operator_headers"]


def _frozen_plant_ctx():
    """Breach the AIR_EMISSIONS permit with one CERTIFIED melt (held) and one
    TAPPED melt (not held) on the same order; returns the context pieces."""
    ctx = setup_released_order()
    order_id = ctx["order"]["id"]
    permit = create_permit("AIR_EMISSIONS", limit_value=100.0)
    b1 = create_melt(order_id)
    charge_melt(b1["id"])
    record_chemistry(b1["id"])
    certify_melt(b1["id"])
    b2 = create_melt(order_id, furnace_id="FURNACE_B")
    charge_melt(b2["id"])
    record_chemistry(b2["id"])
    certify_melt(b2["id"])
    tap_melt(b2["id"])
    mold = create_mold_for_order(order_id)
    record_reading(permit["id"], 120.0)
    record_reading(permit["id"], 130.0)
    return {"order_id": order_id, "permit_id": permit["id"],
            "b1_id": b1["id"], "b2_id": b2["id"], "mold_id": mold["id"]}


def test_air_breach_holds_melts_and_freezes_order(api):
    """PRD §3.7: "a second over-limit reading in the same calendar month — a count
    of 2 or more — moves the permit to `BREACH`."
    PRD §3.3: "When the `AIR_EMISSIONS` permit enters `BREACH`, every melt batch in
    `CHARGING`, `MELTING`, `CHEMISTRY_CHECK`, `ADJUSTMENT`, or `CERTIFIED` moves to
    `HELD` with `state_before_hold` recording exactly which of those five states it
    came from, and every production order linked to a held batch recomputes its
    `posture` to `FROZEN`."

    Design: Difficulty/transitive_cascade/emissions_breach_freeze_and_remediation_thaw
    """
    ctx = _frozen_plant_ctx()
    permit = get_permit(ctx["permit_id"])
    assert permit["status"] == "BREACH"
    assert permit["over_limit_reading_count_current_period"] == 2
    assert permit["last_breach_reading_recorded_by"] == "eo-1"
    b1 = get_melt(ctx["b1_id"])
    assert b1["state"] == "HELD"
    assert b1["state_before_hold"] == "CERTIFIED"
    b2 = get_melt(ctx["b2_id"])
    assert b2["state"] == "TAPPED", "tapped iron is not held"
    assert get_order(ctx["order_id"])["posture"] == "FROZEN"


def test_frozen_order_rejects_pour_then_remediation_thaws(api):
    """PRD §2.8: "melt-batch creation, mold creation, and pouring require a posture
    other than `FROZEN` and reject a `FROZEN` order with `ERR_ORDER_FROZEN`
    (HTTP 409)"
    PRD §3.7: "certification resets `over_limit_reading_count_current_period` to 0,
    resumes every `HELD` melt batch to its `state_before_hold` and clears that
    field, and recomputes the posture of every affected production order, lifting
    `FROZEN` once no held batch remains."

    Design: Difficulty/transitive_cascade/emissions_breach_freeze_and_remediation_thaw
    """
    ctx = _frozen_plant_ctx()
    resp = api.pour_melt_batch(
        ctx["b2_id"],
        {"mold_id": ctx["mold_id"], "unit_count": 1, "pour_weight_per_unit_oz": 128.0},
        _OP)
    validate_error(resp, ApiErrorId.ERR_ORDER_FROZEN)
    assert get_melt(ctx["b2_id"])["poured_lbs"] == 0

    acknowledge_breach(ctx["permit_id"])   # fm-1, segregated from eo-1
    certify_remediation(ctx["permit_id"])  # eo-2, segregated from eo-1
    permit = get_permit(ctx["permit_id"])
    assert permit["status"] == "ACTIVE"
    assert permit["over_limit_reading_count_current_period"] == 0
    b1 = get_melt(ctx["b1_id"])
    assert b1["state"] == "CERTIFIED"
    assert b1["state_before_hold"] is None
    assert get_order(ctx["order_id"])["posture"] == "OPEN"


def _restricted_ctx():
    """25 poured units; u1 passed FINISHED; u2/u3 plain-scrapped -> index 0.0800."""
    ctx = setup_shaken_units(num_units=25, order_overrides={"planned_quantity": 30})
    u1, u2, u3 = ctx["unit_ids"][0], ctx["unit_ids"][1], ctx["unit_ids"][2]
    inspect_unit_pass(u1)
    scrap_unit_via_defect(u2, defect_type="POROSITY", severity="MINOR")
    scrap_unit_via_defect(u3, defect_type="MISRUN", severity="MINOR")
    return ctx, u1


def test_two_plain_scraps_hit_restrict_threshold(api):
    """PRD §3.5: "The order's `scrap_index` is then recomputed as
    `scrap_weighted_units` divided by `poured_units`, rounded half-up to 4 decimal
    places — and defined as 0 while `poured_units` is 0 — with the `scrap_tier`
    re-derived per §2.8; if the recomputed `scrap_index` has reached 0.08 and the
    order's `posture` was `OPEN`, the posture becomes `RESTRICTED`."
    Two plain scraps over 25 poured -> 2.0 / 25 == 0.0800 exactly -> RED.

    Design: Difficulty/transitive_cascade/scrap_disposition_restricts_order_blocks_seasoning
    """
    ctx, _ = _restricted_ctx()
    order = get_order(ctx["order"]["id"])
    assert order["scrap_weighted_units"] == pytest.approx(2.0, abs=1e-9)
    assert order["scrap_index"] == pytest.approx(0.08, abs=1e-9)
    assert order["scrap_tier"] == "RED"
    assert order["posture"] == "RESTRICTED"


def test_restricted_order_blocks_seasoning_batch_create(api):
    """PRD §2.8: "seasoning-batch creation requires the posture to be exactly
    `OPEN`, rejecting `FROZEN` with `ERR_ORDER_FROZEN` and `RESTRICTED` with
    `ERR_ORDER_RESTRICTED` (HTTP 409)"
    The rejected create has no side effects: the FINISHED unit is not queued.

    Design: Difficulty/transitive_cascade/scrap_disposition_restricts_order_blocks_seasoning
    """
    ctx, u1 = _restricted_ctx()
    resp = api.create_seasoning_batch(
        {"production_order_id": ctx["order"]["id"], "oil_type": "SOYBEAN",
         "coating_count": 1, "planned_bake_start": "2026-09-03T08:00:00Z",
         "planned_bake_end": "2026-09-03T10:00:00Z", "unit_ids": [u1]},
        TEST_USERS["seasoning_lead_headers"])
    validate_error(resp, ApiErrorId.ERR_ORDER_RESTRICTED)
    assert get_order(ctx["order"]["id"])["posture"] == "RESTRICTED"
    assert get_unit(u1)["state"] == "FINISHED"
