"""Difficulty queue: resource temporal overlap — furnace half-open exclusive
booking vs the seasoning oven's aggregate capacity pooling."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_melt,
    create_melt_batch_payload,
    create_seasoning_batch,
    get_order_version,
    get_seasoning_batch,
    get_unit,
    setup_finished_units,
    setup_released_order,
    validate_error,
    validate_paginated,
    validate_success,
)

_FM = TEST_USERS["foundry_manager_headers"]
_OP = TEST_USERS["melt_operator_headers"]
_SL = TEST_USERS["seasoning_lead_headers"]

_WINDOW_1 = ("2026-09-02T10:00:00Z", "2026-09-02T12:00:00Z")
_WINDOW_ADJACENT = ("2026-09-02T12:00:00Z", "2026-09-02T14:00:00Z")
_WINDOW_OVERLAP = ("2026-09-02T11:00:00Z", "2026-09-02T13:00:00Z")


def _order_with_melt(window):
    ctx = setup_released_order(order_overrides={"planned_quantity": 30})
    melt = create_melt(ctx["order"]["id"], planned_tap_start=window[0],
                       planned_tap_end=window[1])
    return ctx, melt


def test_furnace_adjacent_windows_allowed(api):
    """PRD §3.3: "the new batch's half-open window must not overlap any other melt
    batch on the same `furnace_id` whose state is neither `EXHAUSTED` nor
    `CANCELLED`, and a violation is rejected with `ERR_FURNACE_WINDOW_OVERLAP`
    (HTTP 409); adjacency, where one window starts exactly as another ends, is
    allowed."
    [12:00, 14:00) touches the existing [10:00, 12:00) on FURNACE_A and is booked.

    Design: Difficulty/resource_temporal_overlap/furnace_half_open_window_exclusion
    """
    ctx, b1 = _order_with_melt(_WINDOW_1)
    b2 = create_melt(ctx["order"]["id"],
                     planned_tap_start=_WINDOW_ADJACENT[0],
                     planned_tap_end=_WINDOW_ADJACENT[1])
    assert b1["furnace_id"] == "FURNACE_A"
    assert b2["furnace_id"] == "FURNACE_A"
    assert b2["state"] == "CHARGING"
    _, meta = validate_paginated(api.list_melt_batches(
        _FM, params={"production_order_id": ctx["order"]["id"]}))
    assert meta["total_count"] == 2


def test_furnace_strict_overlap_rejected_other_furnace_free(api):
    """PRD §3.3: "the new batch's half-open window must not overlap any other melt
    batch on the same `furnace_id` whose state is neither `EXHAUSTED` nor
    `CANCELLED`, and a violation is rejected with `ERR_FURNACE_WINDOW_OVERLAP`
    (HTTP 409)"
    [11:00, 13:00) strictly overlaps [10:00, 12:00) on FURNACE_A -> 409; the very
    same window is free on FURNACE_B -> 201.

    Design: Difficulty/resource_temporal_overlap/furnace_half_open_window_exclusion
    """
    ctx, _ = _order_with_melt(_WINDOW_1)
    create_melt(ctx["order"]["id"], planned_tap_start=_WINDOW_ADJACENT[0],
                planned_tap_end=_WINDOW_ADJACENT[1])
    order_id = ctx["order"]["id"]
    payload = create_melt_batch_payload(
        order_id, get_order_version(order_id),
        planned_tap_start=_WINDOW_OVERLAP[0], planned_tap_end=_WINDOW_OVERLAP[1])
    resp = api.create_melt_batch(payload, _OP)
    validate_error(resp, ApiErrorId.ERR_FURNACE_WINDOW_OVERLAP)
    payload_b = create_melt_batch_payload(
        order_id, get_order_version(order_id), furnace_id="FURNACE_B",
        planned_tap_start=_WINDOW_OVERLAP[0], planned_tap_end=_WINDOW_OVERLAP[1])
    created = validate_success(api.create_melt_batch(payload_b, _OP),
                               expected_status=201)
    assert created["furnace_id"] == "FURNACE_B"
    _, meta = validate_paginated(api.list_melt_batches(
        _FM, params={"production_order_id": order_id}))
    assert meta["total_count"] == 3


def _thirteen_finished_units():
    return setup_finished_units(num_units=13,
                                order_overrides={"planned_quantity": 30})


def test_oven_aggregate_capacity_at_boundary_allowed(api):
    """PRD §3.6: "a new batch's `unit_count` plus the summed `unit_count` of every
    other seasoning batch in `COATING` or `BAKING` whose half-open window from
    `planned_bake_start` to `planned_bake_end` overlaps the new window must not
    exceed 12, otherwise the create is rejected with
    `ERR_OVEN_CAPACITY_EXCEEDED` (HTTP 409)."
    Overlapping batches pool: 5 units on [08:00, 10:00) plus 7 units on
    [09:00, 11:00) sum to exactly 12 == capacity and both are booked.

    Design: Difficulty/resource_temporal_overlap/oven_aggregate_capacity_across_overlap
    """
    ctx = _thirteen_finished_units()
    ids = ctx["unit_ids"]
    sb1 = create_seasoning_batch(ctx["order"]["id"], ids[:5])
    sb2 = create_seasoning_batch(
        ctx["order"]["id"], ids[5:12], oil_type="CANOLA",
        planned_bake_start="2026-09-03T09:00:00Z",
        planned_bake_end="2026-09-03T11:00:00Z")
    assert sb1["unit_count"] == 5
    assert sb2["unit_count"] == 7
    assert get_seasoning_batch(sb1["id"])["state"] == "COATING"
    assert get_seasoning_batch(sb2["id"])["state"] == "COATING"


def test_oven_aggregate_capacity_overflow_rejected(api):
    """PRD §3.6: "The plant has a single seasoning oven, and every batch's
    `oven_id` is the constant `OVEN_1`, holding at most 12 units at once; batches
    whose bake windows overlap share that aggregate capacity"
    A third batch of 1 unit on [09:30, 10:30) overlaps both existing batches and
    would put 5 + 7 + 1 == 13 units in OVEN_1 -> 409; the unit stays FINISHED.

    Design: Difficulty/resource_temporal_overlap/oven_aggregate_capacity_across_overlap
    """
    ctx = _thirteen_finished_units()
    ids = ctx["unit_ids"]
    create_seasoning_batch(ctx["order"]["id"], ids[:5])
    create_seasoning_batch(
        ctx["order"]["id"], ids[5:12], oil_type="CANOLA",
        planned_bake_start="2026-09-03T09:00:00Z",
        planned_bake_end="2026-09-03T11:00:00Z")
    resp = api.create_seasoning_batch(
        {"production_order_id": ctx["order"]["id"], "oil_type": "FLAXSEED",
         "coating_count": 1, "planned_bake_start": "2026-09-03T09:30:00Z",
         "planned_bake_end": "2026-09-03T10:30:00Z", "unit_ids": [ids[12]]},
        _SL)
    validate_error(resp, ApiErrorId.ERR_OVEN_CAPACITY_EXCEEDED)
    assert get_unit(ids[12])["state"] == "FINISHED"
