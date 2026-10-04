"""The supply waterfall (tier-major, created_at-minor order with partial and
zero fills plus shortfall credits), the supply summary read, and the
mid-season reorder pool boundary.
"""
from test_helpers import (
    ApiErrorId,
    CommitmentStatus,
    ProgramAdvanceTarget,
    TEST_USERS,
    advance_program_to,
    api_client,
    compute_shortfall_credit,
    get_commitment,
    get_retailer_account,
    make_retailer_headers,
    setup_allocated_program,
    setup_ready_for_allocation,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def _run_waterfall(commitment_specs, produced_units):
    """Drive a world to IN_PRODUCTION with the given CONFIRMED commitments and
    a COMPLETE run, then fire the allocation-day advance to SHIPPING."""
    world = setup_ready_for_allocation(
        commitment_specs=commitment_specs, produced_units=produced_units,
    )
    advance_program_to(world["program"]["id"], ProgramAdvanceTarget.SHIPPING.value)
    return world


def test_allocation_waterfall_tier_order_produces_partial_and_zero_fills(api):
    """PRD §3.5: "Eligible commitments are sorted by retailer tier first,
    using the fixed rank order `GOLD` (rank 0), then `SILVER` (rank 1), then
    `BRONZE` (rank 2), and ties within a tier break by the commitment's
    `created_at`, earliest first. Walking that pinned order, each commitment
    is granted the smaller of its `committed_units` and the pool remaining at
    its turn"."

    Design: Difficulty/combinatorial_formula/allocation_waterfall_tier_then_created_at_partial_fill
    """
    world = _run_waterfall(
        commitment_specs=[
            {"tier": "GOLD", "units": 60},
            {"tier": "SILVER", "units": 60},
            {"tier": "BRONZE", "units": 10},
        ],
        produced_units=100,
    )
    gold = get_commitment(world["commitments"][0]["id"])
    silver = get_commitment(world["commitments"][1]["id"])
    bronze = get_commitment(world["commitments"][2]["id"])

    assert gold["status"] == CommitmentStatus.ALLOCATED.value
    assert gold["allocated_units"] == 60, "GOLD ranks first and fills fully"
    # Pool 100 - 60 = 40 remaining at SILVER's turn.
    assert silver["status"] == CommitmentStatus.SHORTED.value
    assert silver["allocated_units"] == 40
    # Pool empty at BRONZE's turn: a zero grant is a legal SHORTED.
    assert bronze["status"] == CommitmentStatus.SHORTED.value
    assert bronze["allocated_units"] == 0


def test_allocation_waterfall_posts_shortfall_credits_and_updates_summary(api):
    """PRD §3.5: "A commitment granted strictly less — including a grant of
    zero, which is a legal outcome — becomes `SHORTED`, and the house owes it
    a shortfall credit: the unmet units times the program's
    `retail_price_cents`, times the shortfall-credit rate of 0.10 (ten
    percent), rounded half-up to whole cents, posted onto the retailer
    account's `credit_balance_cents`."

    Design: Difficulty/combinatorial_formula/allocation_waterfall_tier_then_created_at_partial_fill
    """
    world = _run_waterfall(
        commitment_specs=[
            {"tier": "GOLD", "units": 60},
            {"tier": "SILVER", "units": 60},
            {"tier": "BRONZE", "units": 10},
        ],
        produced_units=100,
    )
    retailers = world["commitment_retailers"]
    assert get_retailer_account(retailers[0]["id"])["credit_balance_cents"] == 0
    silver_credit = get_retailer_account(retailers[1]["id"])["credit_balance_cents"]
    bronze_credit = get_retailer_account(retailers[2]["id"])["credit_balance_cents"]
    # 20 short x 499 x 0.10 = 998.0 ; 10 short x 499 x 0.10 = 499.0
    assert silver_credit == 998
    assert silver_credit == compute_shortfall_credit(20, 499)
    assert bronze_credit == 499
    assert bronze_credit == compute_shortfall_credit(10, 499)

    summary = validate_success(
        api_client.get_supply_summary(world["program"]["id"], ADMIN), 200,
    )
    assert summary["produced_units_total"] == 100
    assert summary["committed_units_total"] == 130
    assert summary["allocated_units_total"] == 100
    assert summary["remaining_supply_pool_units"] == 0


def test_allocation_same_tier_tie_break_by_created_at(api):
    """PRD §3.5: "ties within a tier break by the commitment's `created_at`,
    earliest first." and "Per-product pools are independent, and within a
    product the tier-major, `created_at`-minor order is the only evaluation
    order."

    Design: Corner/calculations/allocation_same_tier_tie_break_by_created_at
    """
    world = _run_waterfall(
        commitment_specs=[
            {"tier": "GOLD", "units": 50, "use_default_retailer": True},
            {"tier": "GOLD", "units": 50},
        ],
        produced_units=70,
    )
    first = get_commitment(world["commitments"][0]["id"])
    second = get_commitment(world["commitments"][1]["id"])
    assert first["status"] == CommitmentStatus.ALLOCATED.value
    assert first["allocated_units"] == 50
    assert second["status"] == CommitmentStatus.SHORTED.value
    assert second["allocated_units"] == 20  # pool 70 - 50

    first_retailer = get_retailer_account(world["commitment_retailers"][0]["id"])
    second_retailer = get_retailer_account(world["commitment_retailers"][1]["id"])
    assert first_retailer["credit_balance_cents"] == 0
    # 30 short x 499 x 0.10 = 1497.0
    assert second_retailer["credit_balance_cents"] == 1497
    assert second_retailer["credit_balance_cents"] == compute_shortfall_credit(30, 499)

    summary = validate_success(
        api_client.get_supply_summary(world["program"]["id"], ADMIN), 200,
    )
    assert summary["remaining_supply_pool_units"] == 0


def test_supply_summary_tracks_production_allocation_and_shipping(api):
    """PRD §3.9: "A program's aggregate position is readable at any moment
    through its supply summary, a computed read returning `program_id`,
    `produced_units_total`, `committed_units_total`, `allocated_units_total`
    ..., `shipped_units_total`, `disposed_units_total`, and
    `remaining_supply_pool_units`"."

    Design: Corner/entities/supply_summary_tracks_production_allocation_and_shipping
    """
    world = setup_allocated_program(
        commitment_specs=[{"tier": "GOLD", "units": 30, "use_default_retailer": True}],
        produced_units=50,
        shipment_specs=[{"units": 10}],
    )
    summary = validate_success(
        api_client.get_supply_summary(world["program"]["id"], ADMIN), 200,
    )
    assert summary["program_id"] == world["program"]["id"]
    assert summary["produced_units_total"] == 50
    assert summary["committed_units_total"] == 30
    assert summary["allocated_units_total"] == 30
    assert summary["shipped_units_total"] == 10
    assert summary["disposed_units_total"] == 0
    # remaining pool = 50 produced - 30 allocated
    assert summary["remaining_supply_pool_units"] == 20


def _setup_reorder_boundary():
    """SHIPPING world: pool 120 produced; GOLD 100 ALLOCATED, SILVER 5
    ALLOCATED — remaining pool exactly 15."""
    return setup_allocated_program(
        commitment_specs=[
            {"tier": "GOLD", "units": 100, "use_default_retailer": True},
            {"tier": "SILVER", "units": 5},
        ],
        produced_units=120,
    )


def test_reorder_of_exact_remaining_pool_succeeds_and_drains_it(api):
    """PRD §3.6: "The reorder is granted only when the requested `units` is at
    least 1 and no more than the product's remaining supply pool, the
    commitment's `reorder_used` is still false, and the program is in
    `SHIPPING` or `ON_SHELF` status." and "A granted reorder adds `units` to
    the commitment's `allocated_units`, records the grant in `reorder_units`,
    flips `reorder_used` to true, and increments the commitment's `version`".

    Design: Difficulty/boundary_precision_check/reorder_drains_pool_to_exactly_zero_then_exhausted
    """
    world = _setup_reorder_boundary()
    gold = world["commitments"][0]
    gold_retailer = world["commitment_retailers"][0]

    resp = api_client.reorder_commitment(
        gold["id"], {"units": 15}, make_retailer_headers(gold_retailer["id"]),
    )
    data = validate_success(resp, 200)
    # 15 == pool exactly: draining to zero is success, not exhaustion.
    assert data["allocated_units"] == 115
    assert data["reorder_units"] == 15
    assert data["reorder_used"] is True
    assert data["version"] == gold["version"] + 1

    summary = validate_success(
        api_client.get_supply_summary(world["program"]["id"], ADMIN), 200,
    )
    assert summary["remaining_supply_pool_units"] == 0


def test_reorder_after_pool_drained_and_reorder_reuse_rejected(api):
    """PRD §3.6: "a request whose units exceed the remaining pool — including
    any request when the pool is zero, which is a rejection, not a zero-grant
    — is rejected with `ERR_SUPPLY_POOL_EXHAUSTED` (HTTP 422)." and "A request
    against a commitment that already consumed its reorder, or while the
    program is in the wrong state, is rejected with `ERR_REORDER_NOT_ALLOWED`
    (HTTP 422)." PRD §2.8 ranks structural constraints (10) ahead of pool
    gates (11, "evaluated last").

    Design: Difficulty/boundary_precision_check/reorder_drains_pool_to_exactly_zero_then_exhausted
    """
    world = _setup_reorder_boundary()
    gold = world["commitments"][0]
    silver = world["commitments"][1]
    gold_retailer = world["commitment_retailers"][0]
    silver_retailer = world["commitment_retailers"][1]
    validate_success(api_client.reorder_commitment(
        gold["id"], {"units": 15}, make_retailer_headers(gold_retailer["id"]),
    ), 200)

    pool_empty = api_client.reorder_commitment(
        silver["id"], {"units": 1}, make_retailer_headers(silver_retailer["id"]),
    )
    validate_error(pool_empty, ApiErrorId.ERR_SUPPLY_POOL_EXHAUSTED)

    reused = api_client.reorder_commitment(
        gold["id"], {"units": 1}, make_retailer_headers(gold_retailer["id"]),
    )
    validate_error(reused, ApiErrorId.ERR_REORDER_NOT_ALLOWED)

    assert get_commitment(silver["id"])["allocated_units"] == 5
    assert get_commitment(gold["id"])["allocated_units"] == 115
