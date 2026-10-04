"""Difficulty queue: validation priority pairs — the PRD's fixed check order
decides which error surfaces when two checks fail on the same request."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    charge_melt,
    create_permit,
    create_product,
    create_retail_allocation_payload,
    get_inventory_record_for_product,
    get_melt,
    get_permit,
    record_chemistry,
    record_reading,
    certify_melt,
    setup_charging_melt,
    tap_melt,
    validate_error,
)

_EO = TEST_USERS["environmental_officer_headers"]
_RP = TEST_USERS["retail_planner_headers"]


def _tapped_batch_with_air_breach():
    """TAPPED melt (immune to the hold cascade) plus a breached AIR permit."""
    ctx = setup_charging_melt()
    permit = create_permit("AIR_EMISSIONS", limit_value=100.0)
    batch_id = ctx["melt"]["id"]
    charge_melt(batch_id)
    record_chemistry(batch_id)
    certify_melt(batch_id)
    tap_melt(batch_id, tapped_lbs=2010)
    record_reading(permit["id"], 120.0)
    record_reading(permit["id"], 130.0)
    return ctx, permit["id"], batch_id


def test_tap_state_failure_beats_emissions_safety(api):
    """PRD §2.9: "sixth, state-transition legality, including terminal-state
    lockdown and repeated triggers (`ERR_INVALID_STATE_TRANSITION`); seventh, the
    optimistic-concurrency comparison where the endpoint declares one
    (`ERR_STALE_ORDER_VERSION` or `ERR_STALE_INVENTORY_VERSION`); eighth,
    production-order posture gates (`ERR_ORDER_FROZEN`, then
    `ERR_ORDER_RESTRICTED`); ninth through twelfth, the business-safety checks in
    the order chemistry specification (`ERR_CHEMISTRY_OUT_OF_SPEC`), environmental
    permit breach gates (`ERR_EMISSIONS_PERMIT_BREACH`)"
    The batch is TAPPED (tap requires CERTIFIED) AND the AIR permit is in BREACH;
    the state error wins.

    Design: Difficulty/priority_pair_validation_conflict/tap_state_failure_beats_emissions_safety
    """
    _, _, batch_id = _tapped_batch_with_air_breach()
    resp = api.tap_melt_batch(batch_id, {"tapped_temp_f": 2690, "tapped_lbs": 100},
                              TEST_USERS["melt_operator_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)


def test_rejected_tap_leaves_batch_and_permit_unchanged(api):
    """PRD §3.3: "Tapping moves a `CERTIFIED` batch to `TAPPED` and initializes the
    iron mass ledger."
    After the rejected second tap the ledger is untouched (tapped_lbs still 2010)
    and the permit remains in BREACH — the losing checks had no side effects.

    Design: Difficulty/priority_pair_validation_conflict/tap_state_failure_beats_emissions_safety
    """
    _, permit_id, batch_id = _tapped_batch_with_air_breach()
    resp = api.tap_melt_batch(batch_id, {"tapped_temp_f": 2690, "tapped_lbs": 100},
                              TEST_USERS["melt_operator_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
    melt = get_melt(batch_id)
    assert melt["state"] == "TAPPED"
    assert melt["tapped_lbs"] == 2010
    assert get_permit(permit_id)["status"] == "BREACH"


def test_allocation_temporal_failure_beats_fiscal(api):
    """PRD §2.9: "then the temporal checks — ship week in the future
    (`ERR_SHIP_WEEK_INVALID`) and the peak-window cancellation freeze
    (`ERR_ALLOCATION_FROZEN`); then product-activeness (`ERR_PRODUCT_DISCONTINUED`);
    and finally the fiscal checks — brand price floor
    (`ERR_PRICE_BELOW_BRAND_FLOOR`), outlet price floor
    (`ERR_OUTLET_PRICE_BELOW_FLOOR`), inventory sufficiency
    (`ERR_INSUFFICIENT_INVENTORY`)"
    The request fails BOTH ship-week-in-the-future (2026-08-17 is before the
    2026-09-01 logical clock) and available-inventory (5 > 0); the temporal error
    wins.

    Design: Difficulty/priority_pair_validation_conflict/allocation_temporal_beats_fiscal
    """
    product = create_product()
    record = get_inventory_record_for_product(product["id"])
    payload = create_retail_allocation_payload(
        record["id"], record["version"], allocated_qty=5, ship_week="2026-08-17")
    resp = api.create_retail_allocation(payload, _RP)
    validate_error(resp, ApiErrorId.ERR_SHIP_WEEK_INVALID)


def test_rejected_allocation_has_no_reservation_side_effect(api):
    """PRD §3.8: "A created allocation starts in `PROPOSED` and immediately adds its
    `allocated_qty` to the record's `reserved_units`, incrementing the inventory
    record's `version` by 1."
    Because the create is rejected, no reservation happens: reserved_units stays 0
    and the record version is unmoved.

    Design: Difficulty/priority_pair_validation_conflict/allocation_temporal_beats_fiscal
    """
    product = create_product()
    record = get_inventory_record_for_product(product["id"])
    payload = create_retail_allocation_payload(
        record["id"], record["version"], allocated_qty=5, ship_week="2026-08-17")
    resp = api.create_retail_allocation(payload, _RP)
    validate_error(resp, ApiErrorId.ERR_SHIP_WEEK_INVALID)
    after = get_inventory_record_for_product(product["id"])
    assert after["reserved_units"] == 0
    assert after["version"] == record["version"]
