"""Delivery-window overlap between sibling contracts: half-open interval
semantics, grower+variety scoping, and the terminal-state exemption."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_crop_contract_payload,
    deliver_lot,
    make_active_contract,
    make_contract,
    make_facility,
    make_grower,
    set_clock,
    setup_procurement,
    validate_error,
    validate_paginated,
    validate_success,
)

GRM = TEST_USERS["grower_relations_manager_headers"]


def test_delivery_window_adjacency_allowed_overlap_rejected(api):
    """PRD §3.1: "Windows are compared as half-open intervals, start inclusive
    and end exclusive: an overlap exists when the existing window's start
    falls before the candidate window's end and the candidate window's start
    falls before the existing window's end. Adjacency is not overlap — a
    candidate starting exactly when a sibling ends, or ending exactly when a
    sibling starts, is allowed, so back-to-back seasons merge cleanly. A
    conflicting creation, or an amendment acceptance that would create a
    conflict, is rejected with `ERR_DELIVERY_WINDOW_OVERLAP`."
    PRD §3.1: "Two contracts of the same grower and the same variety may not
    hold overlapping delivery windows while either is still live."

    Design: Difficulty/resource_temporal_overlap/contract_delivery_window_overlap_half_open_adjacency_allowed
    """
    set_clock(api=api)
    grower = make_grower(api=api)
    make_contract(grower["id"], api=api)  # C1 RUSSET_BURBANK [2026-09-01, 2026-10-15]

    adjacent = api.create_crop_contract(
        create_crop_contract_payload(
            grower["id"], contracted_acres=50, expected_yield_cwt_per_acre=380,
            base_price_per_cwt_cents=2400,
            delivery_window_start="2026-10-15T00:00:00Z",
            delivery_window_end="2026-12-01T00:00:00Z",
        ),
        GRM,
    )
    c2 = validate_success(adjacent, 201)
    # PRD pins the three-fractional-digit format only for created_at/updated_at;
    # the echo representation of a client-supplied window is unpinned, so assert
    # only that the supplied value is carried (PRD §3.1: the contract names its
    # delivery_window_start), tolerant of either canonical representation.
    assert c2["delivery_window_start"].startswith("2026-10-15T00:00:00"), (
        "back-to-back seasons merge cleanly: C2 starting exactly at C1's end is allowed"
    )

    overlapping = api.create_crop_contract(
        create_crop_contract_payload(
            grower["id"], contracted_acres=40, expected_yield_cwt_per_acre=380,
            base_price_per_cwt_cents=2400,
            delivery_window_start="2026-10-14T00:00:00Z",
            delivery_window_end="2026-12-01T00:00:00Z",
        ),
        GRM,
    )
    validate_error(overlapping, ApiErrorId.ERR_DELIVERY_WINDOW_OVERLAP)
    assert overlapping.status_code == 409, "one day into C1's window is a true overlap"

    other_variety = api.create_crop_contract(
        create_crop_contract_payload(
            grower["id"], variety="RANGER_RUSSET",
            contracted_acres=30, expected_yield_cwt_per_acre=350,
            base_price_per_cwt_cents=2300,
            delivery_window_start="2026-09-15T00:00:00Z",
            delivery_window_end="2026-11-01T00:00:00Z",
        ),
        GRM,
    )
    validate_success(other_variety, 201)

    rows, meta = validate_paginated(api.list_crop_contracts(GRM, params={"grower_id": grower["id"]}))
    assert len(rows) == 3, f"C1, C2 and C4 persist; the rejected C3 must not (got {len(rows)})"


def test_delivery_window_terminal_contract_no_longer_blocks(api):
    """PRD §3.1: "The check considers every sibling contract of that grower
    and variety whose status is `DRAFT`, `ACTIVE`, or `AMENDMENT_PENDING` —
    contracts in the terminal states `FULFILLED` and `SHORTFALL_DECLARED` no
    longer block."
    PRD §3.1: "immediately after a newly received contracted lot is counted,
    if the contract's `delivered_volume_cwt` has reached at least 98 percent
    of its `contracted_volume_cwt` — the threshold computed as 0.98 times the
    contracted volume, rounded half-up to one decimal place — the contract
    transitions automatically to `FULFILLED`."

    Design: Difficulty/resource_temporal_overlap/contract_delivery_window_overlap_half_open_adjacency_allowed
    """
    world = setup_procurement(api=api)  # ACTIVE 100x400 = 40000.0 cwt, window 09-01..10-15
    # Deliver exactly 98% (39200.0 cwt) so the contract auto-fulfills.
    deliver_lot(
        world["contract"]["id"], world["facility"]["id"], world["grower"]["id"],
        api=api, gross_weight_cwt=39300.0, tare_weight_cwt=100.0,
    )
    fulfilled = validate_success(api.get_crop_contract(world["contract"]["id"], GRM))
    assert fulfilled["status"] == "FULFILLED"

    overlapping = api.create_crop_contract(
        create_crop_contract_payload(
            world["grower"]["id"], contracted_acres=20, expected_yield_cwt_per_acre=350,
            base_price_per_cwt_cents=2400,
            delivery_window_start="2026-09-10T00:00:00Z",
            delivery_window_end="2026-11-01T00:00:00Z",
        ),
        GRM,
    )
    c2 = validate_success(overlapping, 201)
    assert c2["status"] == "DRAFT", (
        "a FULFILLED sibling no longer blocks, so the overlapping window is accepted"
    )
