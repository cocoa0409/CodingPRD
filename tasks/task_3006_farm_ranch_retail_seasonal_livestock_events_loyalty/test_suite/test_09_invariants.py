"""Compensating invariants: bird conservation and loyalty points."""

from test_helpers import (
    TEST_USERS,
    accrue_points,
    create_account,
    create_open_store,
    make_customer_headers,
    place_chick_order,
    set_clock,
    setup_reserved_order,
    validate_success,
)

MGR = TEST_USERS["store_manager_headers"]
ASSOC = TEST_USERS["store_associate_headers"]

FALL_NOW = "2026-09-20T10:00:00Z"


def test_reserve_decrements_on_hand_by_exact_quantity(api):
    """PRD §3.4: "The reservation decrements the lot's `quantity_on_hand` by the ordered quantity and increments the lot's `version` by 1."

    Design: Difficulty/compensating_invariant/reserve_cancel_leaves_lot_bird_conservation_exact
    """
    ctx = setup_reserved_order()
    lot = validate_success(api.get_livestock_lot(ctx["lot"]["id"], MGR))
    assert lot["quantity_on_hand"] == 94
    assert lot["quantity_sold"] == 0
    assert lot["mortality_count"] == 0
    assert lot["quantity_quarantined"] == 0


def test_cancel_restores_bird_conservation_exactly(api):
    """PRD §3.4: "Cancellation from a healthy lot restores the quantity to `quantity_on_hand`"
    PRD §3.3: "Thereafter `quantity_on_hand` is a derived figure: the birds received minus those sold, minus mortality losses, minus those quarantined, minus those reserved but not yet fulfilled."

    Design: Difficulty/compensating_invariant/reserve_cancel_leaves_lot_bird_conservation_exact
    """
    ctx = setup_reserved_order()

    validate_success(
        api.cancel_chick_order(
            ctx["order"]["id"], {"reason": "changed mind"},
            make_customer_headers(ctx["account"]["id"]),
        )
    )

    lot = validate_success(api.get_livestock_lot(ctx["lot"]["id"], MGR))
    assert lot["quantity_on_hand"] == 100
    assert lot["quantity_sold"] == 0
    assert lot["mortality_count"] == 0
    assert lot["quantity_quarantined"] == 0
    assert (
        lot["quantity_received"]
        == lot["quantity_on_hand"]
        + lot["quantity_sold"]
        + lot["mortality_count"]
        + lot["quantity_quarantined"]
    )


def test_accrual_crosses_tier_threshold(api):
    """PRD §3.7: "The resulting `tier` is `HOMESTEAD` when qualifying points reach at least 7500, `RANCH_HAND` when they reach at least 2500, and `NEIGHBOR` otherwise"
    PRD §3.7: "The `points_balance`, by contrast, is the plain sum of `points_delta` over all ledger entries regardless of age or tier-counting"

    Design: Difficulty/compensating_invariant/accrual_reversal_leaves_points_balance_and_tier_exact
    """
    set_clock(FALL_NOW)
    store = create_open_store(season="WINTER_HEATING")
    account = create_account(full_name="Ada Merritt")
    accrue_points(account, store, 249900, earn_context="OTHER")

    accrue_points(account, store, 10000, earn_context="OTHER")

    acct = validate_success(api.get_loyalty_account(account["id"], ASSOC))
    assert acct["points_balance"] == 2599
    assert acct["tier_qualifying_points"] == 2599
    assert acct["tier"] == "RANCH_HAND"


def test_reversal_restores_balance_and_tier_exactly(api):
    """PRD §3.7: "Every entry records `counts_toward_tier` — true for `ACCRUAL` and `REVERSAL`, false for `REDEMPTION` and `ADJUSTMENT`"
    PRD §3.7: "A `REVERSAL` requires a `related_entry_id` referencing an existing entry of the same account — a dangling or cross-account reference fails with `ERR_ENTRY_NOT_FOUND` — and its supplied `points_delta` must carry the opposite sign of the referenced entry and must not exceed that entry's remaining unreversed magnitude"
    PRD §3.7: "The `points_balance`, by contrast, is the plain sum of `points_delta` over all ledger entries regardless of age or tier-counting"

    Design: Difficulty/compensating_invariant/accrual_reversal_leaves_points_balance_and_tier_exact
    """
    set_clock(FALL_NOW)
    store = create_open_store(season="WINTER_HEATING")
    account = create_account(full_name="Ada Merritt")
    accrue_points(account, store, 249900, earn_context="OTHER")

    accrual = accrue_points(account, store, 10000, earn_context="OTHER")
    assert accrual["points_delta"] == 100
    mid = validate_success(api.get_loyalty_account(account["id"], ASSOC))
    assert mid["points_balance"] == 2599
    assert mid["tier"] == "RANCH_HAND"

    validate_success(
        api.create_ledger_entry(
            account["id"],
            {
                "entry_type": "REVERSAL",
                "related_entry_id": accrual["id"],
                "points_delta": -100,
            },
            ASSOC,
        ),
        expected_status=201,
    )

    end = validate_success(api.get_loyalty_account(account["id"], ASSOC))
    assert end["points_balance"] == 2499
    assert end["tier_qualifying_points"] == 2499
    assert end["tier"] == "NEIGHBOR"
