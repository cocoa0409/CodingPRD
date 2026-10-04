"""Rapid replenishment: pinned five-step quantity evaluation, supersession,
OCC on the variant, and retired-variant lockdown (PRD §2.5, §2.8, §3.3, §3.7).
"""
import pytest

from test_helpers import (
    RETAIL,
    SOURCING,
    ApiErrorId,
    api_client,
    advance_variant_to_refresh_candidate,
    advance_variant_to_retired,
    assert_capacity_conservation,
    create_replenishment,
    create_replenishment_payload,
    get_partner,
    get_variant,
    setup_retail_live_fulfilled,
    setup_retail_live_open_commitment,
    tool_variant_payload,
    validate_created,
    validate_error,
    validate_ok,
)


def test_replenishment_quantity_five_input_clamp_then_round(api):
    """PRD §3.7: "Second, the raw need: three weeks of cover at the reported
    velocity, minus `on_hand_units`, minus `in_transit_units`. ... Third,
    case-pack rounding: the raw need is rounded up to the next whole multiple
    of `case_pack_units`; this rounding happens only after the zero-need
    branch, never before. ... Fifth, the rounded need becomes the order's
    `quantity_units`, and the order starts `OPEN` with `superseded_by_id`
    null."

    raw_need = 3*120 - 100 - 60 = 200; ceil(200/24) = 9 packs; 9 * 24 = 216.

    Design: Difficulty/combinatorial_formula/replenishment_quantity_five_input_clamp_then_round
    """
    bundle = setup_retail_live_fulfilled()
    assert bundle["variant"]["lifecycle"] == "RETAIL_LIVE"
    order = create_replenishment(
        bundle["variant"]["id"], bundle["variant"]["version"],
        weekly_velocity=120, on_hand_units=100, in_transit_units=60,
        case_pack_units=24,
    )
    assert order["quantity_units"] == 216
    assert order["status"] == "OPEN"
    assert order["superseded_by_id"] is None
    assert get_partner(bundle["partner"]["id"])["allocated_units"] == 216


def test_replenishment_create_advances_variant_version_and_conserves(api):
    """PRD §2.5: "posting a replenishment order advances the parent
    ModelVariant's `version` by one" and PRD §2.9: "the partner's
    `allocated_units` equals the sum of `committed_units` over all
    LaunchCommitments in `OPEN` status on variants tooled at that partner,
    plus the sum of `quantity_units` over all ReplenishmentOrders in `OPEN`
    status on variants tooled at that partner."

    Design: Difficulty/combinatorial_formula/replenishment_quantity_five_input_clamp_then_round
    """
    bundle = setup_retail_live_fulfilled()
    v_live = bundle["variant"]["version"]
    order = create_replenishment(
        bundle["variant"]["id"], v_live,
        weekly_velocity=120, on_hand_units=100, in_transit_units=60,
        case_pack_units=24,
    )
    assert order["quantity_units"] == 216
    assert get_variant(bundle["variant"]["id"])["version"] == v_live + 1
    assert_capacity_conservation(
        get_partner(bundle["partner"]["id"]), [], [order]
    )


def test_replenishment_zero_raw_need_rejected(api):
    """PRD §3.7: "If the raw need is zero or negative the request is rejected
    with `ERR_REPLENISHMENT_NOT_NEEDED` — exactly zero is rejected, because
    there is nothing to order."

    raw_need = 3*60 - 100 - 80 = 0 exactly (velocity 60 passes the >= 50 gate).

    Design: Difficulty/boundary_precision_check/replenishment_zero_raw_need_rejected
    """
    bundle = setup_retail_live_fulfilled()
    payload = create_replenishment_payload(
        bundle["variant"]["id"], bundle["variant"]["version"],
        weekly_velocity=60, on_hand_units=100, in_transit_units=80,
        case_pack_units=24,
    )
    resp = api_client.create_replenishment_order(payload, RETAIL)
    validate_error(resp, ApiErrorId.ERR_REPLENISHMENT_NOT_NEEDED)
    rows = validate_ok(
        api_client.list_variant_replenishments(bundle["variant"]["id"], RETAIL)
    )
    assert rows == []


def test_replenishment_one_unit_raw_need_rounds_up_to_case_pack(api):
    """PRD §3.7: "Third, case-pack rounding: the raw need is rounded up to the
    next whole multiple of `case_pack_units`; this rounding happens only after
    the zero-need branch, never before."

    raw_need = 3*60 - 99 - 80 = 1 (strictly positive, not the rejected zero);
    ceil(1/24) = 1 pack -> quantity_units 24.

    Design: Difficulty/boundary_precision_check/replenishment_zero_raw_need_rejected
    """
    bundle = setup_retail_live_fulfilled()
    order = create_replenishment(
        bundle["variant"]["id"], bundle["variant"]["version"],
        weekly_velocity=60, on_hand_units=99, in_transit_units=80,
        case_pack_units=24,
    )
    assert order["quantity_units"] == 24
    assert order["status"] == "OPEN"


def test_velocity_gate_fires_before_need_computation(api):
    """PRD §3.7: "The order quantity is derived by a pinned five-step
    evaluation, and the order of the gates matters. First, the velocity gate:
    `weekly_velocity` must be at least 50 units per week — inclusive — because
    replenishment is reserved for successful items, else
    `ERR_VELOCITY_BELOW_THRESHOLD`."

    Design: Corner/calculations/velocity_gate_fires_before_need_computation
    """
    bundle = setup_retail_live_fulfilled()
    payload = create_replenishment_payload(
        bundle["variant"]["id"], bundle["variant"]["version"],
        weekly_velocity=49, on_hand_units=0, in_transit_units=0,
        case_pack_units=24,
    )
    resp = api_client.create_replenishment_order(payload, RETAIL)
    validate_error(resp, ApiErrorId.ERR_VELOCITY_BELOW_THRESHOLD)


def test_replenishment_rejected_when_casepack_need_exceeds_free_capacity(api):
    """PRD §3.7: "Fourth, the capacity check: if the rounded need exceeds the
    variant's tooling partner's `capacity_units_total` minus its
    `allocated_units`, the request is rejected with `ERR_CAPACITY_EXCEEDED`
    and no partial fill is booked."

    Design: Corner/calculations/replenishment_rejected_when_casepack_need_exceeds_free_capacity
    """
    bundle = setup_retail_live_open_commitment()  # 300 of 500 still allocated
    assert bundle["variant"]["lifecycle"] == "RETAIL_LIVE"
    assert bundle["partner"]["allocated_units"] == 300
    payload = create_replenishment_payload(
        bundle["variant"]["id"], bundle["variant"]["version"],
        weekly_velocity=120, on_hand_units=100, in_transit_units=60,
        case_pack_units=24,
    )  # rounded need 216 > free 200
    resp = api_client.create_replenishment_order(payload, RETAIL)
    validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED)


def test_replenish_create_supersedes_prior_open_order(api):
    """PRD §3.7: "Placing a new order supersedes the old one. If the variant
    already has a ReplenishmentOrder in `OPEN` status, that order moves to
    `SUPERSEDED` with its `superseded_by_id` set to the new order's `id`; the
    old order's units are released and the new order's `quantity_units` are
    allocated, keeping the capacity invariant of §2.9 exact."

    Design: Corner/state_machines/replenish_create_supersedes_prior_open_order
    """
    bundle = setup_retail_live_fulfilled()
    first = create_replenishment(
        bundle["variant"]["id"], bundle["variant"]["version"],
        weekly_velocity=120, on_hand_units=100, in_transit_units=60,
        case_pack_units=24,
    )
    assert first["quantity_units"] == 216
    v_after_first = get_variant(bundle["variant"]["id"])["version"]
    second = create_replenishment(
        bundle["variant"]["id"], v_after_first,
        weekly_velocity=100, on_hand_units=50, in_transit_units=10,
        case_pack_units=24,
    )
    assert second["quantity_units"] == 240
    rows = validate_ok(
        api_client.list_variant_replenishments(bundle["variant"]["id"], RETAIL)
    )
    assert rows[0]["id"] == first["id"]
    assert rows[0]["status"] == "SUPERSEDED"
    assert rows[0]["superseded_by_id"] == second["id"]
    assert get_partner(bundle["partner"]["id"])["allocated_units"] == 240


def test_occ_stale_variant_version_rejected_on_replenish(api):
    """PRD §2.8: "Creating a replenishment order requires the request to carry
    `expected_variant_version`, holding the `version` of the target
    ModelVariant as the client last observed it. If the variant's current
    `version` has advanced since that observation — for example because
    another writer created a superseding order, or the variant changed
    lifecycle state — the request is rejected with
    `ERR_STALE_VARIANT_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_variant_version_rejected_on_replenish
    """
    bundle = setup_retail_live_fulfilled()
    v_live = bundle["variant"]["version"]
    first = create_replenishment(
        bundle["variant"]["id"], v_live,
        weekly_velocity=120, on_hand_units=100, in_transit_units=60,
        case_pack_units=24,
    )
    assert first["status"] == "OPEN"
    payload = create_replenishment_payload(
        bundle["variant"]["id"], v_live,  # stale: first create advanced it
        weekly_velocity=100, on_hand_units=50, in_transit_units=10,
        case_pack_units=24,
    )
    resp = api_client.create_replenishment_order(payload, RETAIL)
    validate_error(resp, ApiErrorId.ERR_STALE_VARIANT_VERSION)
    rows = validate_ok(
        api_client.list_variant_replenishments(bundle["variant"]["id"], RETAIL)
    )
    assert rows[0]["id"] == first["id"]
    assert rows[0]["status"] == "OPEN"


def test_retired_variant_rejects_tooling_and_replenishment(api):
    """PRD §3.3: "A `SourcingManager` tools a `DRAFT` variant — tooling a
    variant in any other state is rejected with `ERR_INVALID_STATE`" and PRD
    §3.7: "A `RetailExec` places a ReplenishmentOrder for a `RETAIL_LIVE`
    variant — a variant in any other lifecycle state is rejected with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/retired_variant_rejects_tooling_and_replenishment
    """
    bundle = setup_retail_live_open_commitment()
    bundle = advance_variant_to_refresh_candidate(bundle)
    bundle = advance_variant_to_retired(bundle)
    assert bundle["variant"]["lifecycle"] == "RETIRED"
    resp1 = api_client.tool_variant(
        bundle["variant"]["id"],
        tool_variant_payload(bundle["partner"]["id"]),
        SOURCING,
    )
    validate_error(resp1, ApiErrorId.ERR_INVALID_STATE)
    payload = create_replenishment_payload(
        bundle["variant"]["id"], bundle["variant"]["version"],
        weekly_velocity=120, on_hand_units=0, in_transit_units=0,
        case_pack_units=24,
    )
    resp2 = api_client.create_replenishment_order(payload, RETAIL)
    validate_error(resp2, ApiErrorId.ERR_INVALID_STATE)
