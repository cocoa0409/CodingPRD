"""Refund settlement: the two reason variants, the four-link cascade they set off,
and the conservation of brand currency across a REDEEM/RELEASE pair.

Every order here is placed on an OUTERWEAR grade B unit listed at
floor(50000 * 3900 / 10000) = 19500, so gross 19500, channel fee 1755 and order
total 21255 throughout, and the tier's `restock_fee_pct_bp` of 1200 makes the
remorse restocking fee ceil(19500 * 1200 / 10000) = 2340 and the retained
non-refundable amount 2340 + 1755 = 4095. Refurbishment needs a bay in the
trade-in's custody store (§3.5), so the unit on sale always comes from an
`IN_STORE` trade-in while a buyer's brand currency comes from a mail-in trade-in
of their own.
"""

from test_helpers import (
    CREDIT_POLICY_OPEN,
    GRADE_POLICY_FOOTWEAR_A,
    GRADE_POLICY_OUTERWEAR_B,
    MERCH,
    TEST_DEFAULTS,
    api_client,
    assert_credit_ledger_entry,
    assert_grant_conservation,
    assert_instant,
    assert_ledger_balances_run,
    assert_null,
    assert_pagination_meta,
    assert_resale_order,
    assert_unit_dimensions,
    create_customer,
    fetch_customer,
    fetch_grant,
    fetch_order,
    fetch_unit,
    fulfill_order,
    grant_ledger_entries,
    list_unit,
    make_customer_headers,
    order_ledger_entries,
    place_order,
    request_return,
    return_request_payload,
    set_clock,
    settle_return,
    setup_credit_source_grant,
    setup_estate,
    setup_fulfilled_order,
    setup_listed_unit,
    validate_error,
    validate_paginated,
)

GROSS = 19500
FEE = 1755
TOTAL = 21255
REMORSE_RESTOCK_FEE = 2340
NON_REFUNDABLE_ON_REMORSE = 4095


def _open_policy_estate():
    """A policy that permits redeeming the whole order total but for the cash floor."""
    return setup_estate(
        grade_policies=(GRADE_POLICY_OUTERWEAR_B, GRADE_POLICY_FOOTWEAR_A),
        credit_policy=CREDIT_POLICY_OPEN,
    )


def _seller_listing(estate, **overrides):
    """Ava's OWNED_INVENTORY unit, refurbished for nothing and listed at 19500."""
    scenario = setup_listed_unit(estate, loyalty_tier="PLUS", **overrides)
    assert scenario["unit"]["list_price_minor"] == GROSS
    assert_unit_dimensions(scenario["unit"], "LISTED", "CAPITALIZED")
    return scenario


def _rich_buyer(estate, expected_grant=48300):
    """Ben, funded by a mail-in FOOTWEAR grade A trade-in of his own."""
    scenario = setup_credit_source_grant(
        estate,
        loyalty_tier="PLUS",
        product_category="FOOTWEAR",
        declared_grade="A",
        assessed_grade="A",
        msrp_minor=TEST_DEFAULTS["FOOTWEAR_MSRP_MINOR"],
        item_mass_grams=TEST_DEFAULTS["FOOTWEAR_MASS_GRAMS"],
    )
    # 42000 base + 4200 mail-in bonus + 2100 PLUS loyalty.
    assert scenario["grant"]["issued_amount_minor"] == expected_grant
    return scenario


def _buy_fulfil_and_claim(buyer, channel, unit, requested_credit_minor, reason_type):
    """Place, hand over and open an after-sale claim, returning the live order."""
    order = place_order(buyer, channel, unit, requested_credit_minor)
    assert order["status"] == "PLACED"
    assert order["gross_price_minor"] == GROSS
    assert order["channel_fee_minor"] == FEE
    assert order["order_total_minor"] == TOTAL
    fulfilled = fulfill_order(order["id"])
    assert fulfilled["status"] == "FULFILLED"
    claimed = request_return(order["id"], buyer, reason_type)
    assert claimed["status"] == "RETURN_REQUESTED"
    assert claimed["reason_type"] == reason_type
    return claimed


def test_the_refund_diverges_on_the_reason_type_alone():
    """Two orders, identical to the minor unit, refund 17160 and 21255.

    PRD §3.8: "For a `BUYER_REMORSE` claim, `restock_fee_minor` is the order's
    `gross_price_minor` multiplied by that tier's `restock_fee_pct_bp`, divided by
    ten thousand and rounded **up**; the non-refundable amount is that restocking
    fee plus the order's `channel_fee_minor`, because the brand does not eat the
    channel fee on a change of mind."
    PRD §3.8: "For a `WARRANTY_DEFECT` claim, `restock_fee_minor` is 0 and the
    non-refundable amount is 0 as well — the channel fee **is** refunded, because
    the fault was the brand's."
    PRD §3.8: "`refund_cash_minor` is the order's `cash_due_minor` less the
    non-refundable amount, floored at zero so it can never go negative."
    PRD §3.8: "`refund_credit_minor` is the order's `credit_applied_minor` less that
    shortfall, floored at zero — so a remorse buyer who paid mostly in brand
    currency has the unrecovered fee taken out of their credit refund rather than
    being invoiced for it."
    PRD §3.8: "Identical orders can therefore settle to very different cash
    depending only on the reason."

    Design: Difficulty/dual_variant_calc/return_refund_remorse_versus_warranty_diverges_on_identical_order
    """
    estate = setup_estate()
    scenario = setup_fulfilled_order(estate, seller_kwargs={"loyalty_tier": "PLUS"})
    channel = scenario["channel"]
    buyer = scenario["buyer"]
    unit = scenario["unit"]
    first = scenario["order"]
    assert first["gross_price_minor"] == GROSS
    assert first["channel_fee_minor"] == FEE
    assert first["order_total_minor"] == TOTAL
    assert first["cash_due_minor"] == TOTAL
    assert first["credit_applied_minor"] == 0

    request_return(first["id"], buyer, "BUYER_REMORSE")
    remorse = settle_return(first["id"], "REFUND")
    assert remorse["status"] == "RETURNED"
    assert remorse["restock_fee_minor"] == REMORSE_RESTOCK_FEE
    # 21255 cash paid, less the 1755 channel fee and the 2340 restocking fee.
    assert remorse["refund_cash_minor"] == 17160
    assert remorse["refund_credit_minor"] == 0

    relisted = list_unit(unit["id"], channel["id"])
    # The very same price data on the second sale.
    assert relisted["list_price_minor"] == GROSS
    assert relisted["current_price_minor"] == GROSS

    second = _buy_fulfil_and_claim(
        buyer, channel, relisted, 0, "WARRANTY_DEFECT"
    )
    assert second["cash_due_minor"] == TOTAL
    assert second["credit_applied_minor"] == 0

    warranty = settle_return(second["id"], "REFUND")
    assert warranty["status"] == "RETURNED"
    assert warranty["restock_fee_minor"] == 0
    assert warranty["refund_cash_minor"] == TOTAL
    assert warranty["refund_credit_minor"] == 0

    # The whole divergence is the retained fee pair, 1755 + 2340.
    assert warranty["refund_cash_minor"] - remorse["refund_cash_minor"] == 4095


def test_a_credit_heavy_remorse_refund_takes_the_fee_out_of_the_credit_leg():
    """With only 500 of cash to claw back, the remorse fee lands on the credit refund.

    PRD §3.8: "`refund_cash_minor` is the order's `cash_due_minor` less the
    non-refundable amount, floored at zero so it can never go negative."
    PRD §3.8: "Any part of the non-refundable amount that the cash leg could not
    absorb is a shortfall: the non-refundable amount less `cash_due_minor`, again
    floored at zero."
    PRD §3.8: "`refund_credit_minor` is the order's `credit_applied_minor` less that
    shortfall, floored at zero — so a remorse buyer who paid mostly in brand
    currency has the unrecovered fee taken out of their credit refund rather than
    being invoiced for it."
    PRD §3.8: "For a warranty claim the two consequences of a zero non-refundable
    amount are that `refund_cash_minor` equals `cash_due_minor` exactly and
    `refund_credit_minor` equals `credit_applied_minor` exactly."
    PRD §3.8: "For a `WARRANTY_DEFECT` claim, `restock_fee_minor` is 0 and the
    non-refundable amount is 0 as well — the channel fee **is** refunded, because
    the fault was the brand's."

    Design: Difficulty/dual_variant_calc/return_refund_remorse_versus_warranty_diverges_on_identical_order
    """
    estate = _open_policy_estate()
    seller = _seller_listing(estate)
    channel = seller["channel"]
    unit = seller["unit"]
    buyer = _rich_buyer(estate)["customer"]

    # 21255 - 20755 leaves exactly the 500 minimum cash remainder.
    first = _buy_fulfil_and_claim(buyer, channel, unit, 20755, "BUYER_REMORSE")
    assert first["credit_applied_minor"] == 20755
    assert first["cash_due_minor"] == 500

    remorse = settle_return(first["id"], "REFUND")
    assert remorse["restock_fee_minor"] == REMORSE_RESTOCK_FEE
    # The 4095 non-refundable amount cannot fit inside 500 of cash.
    assert remorse["refund_cash_minor"] == 0
    # Shortfall 4095 - 500 = 3595, taken off the 20755 credit leg.
    assert remorse["refund_credit_minor"] == 17160

    relisted = list_unit(unit["id"], channel["id"])
    assert relisted["list_price_minor"] == GROSS

    second = _buy_fulfil_and_claim(
        buyer, channel, relisted, 20755, "WARRANTY_DEFECT"
    )
    assert second["credit_applied_minor"] == 20755
    assert second["cash_due_minor"] == 500

    warranty = settle_return(second["id"], "REFUND")
    assert warranty["restock_fee_minor"] == 0
    # Both legs come back untouched on the identical order.
    assert warranty["refund_cash_minor"] == 500
    assert warranty["refund_credit_minor"] == 20755


def test_the_refund_cascade_runs_from_the_order_to_the_recomputed_balance():
    """Four links: RETURNED order → RELEASE entry → grant back to ISSUED → balance.

    PRD §3.8: "The **first link** writes `restock_fee_minor`, `refund_cash_minor`
    and `refund_credit_minor` onto the order, moves the order to `RETURNED`,
    increments its version, and moves the unit from `SOLD` to `RETURNED` with
    `listed_channel_id` cleared to null and its own version incremented."
    PRD §3.8: "One `RELEASE` entry per grant is appended with a positive
    `amount_minor`, its `balance_after_minor` reflecting that grant's restored
    `remaining_minor`, and `resale_order_id` naming this order; the last grant
    reached may be only partially restored."
    PRD §3.8: "Each touched grant then has its `remaining_minor` increased by the
    released amount and its `status` recomputed: an `EXHAUSTED` grant that is partly
    refilled becomes `PARTIALLY_REDEEMED`, a `PARTIALLY_REDEEMED` grant whose
    `remaining_minor` is restored all the way back to its `issued_amount_minor`
    returns to `ISSUED`, and even an `EXPIRED` grant that funded part of this order
    accepts its release and becomes `PARTIALLY_REDEEMED`."
    PRD §3.8: "The **fourth link**, caused by the second and the third together,
    recomputes the buyer's `credit_balance_minor` and increments the customer's
    version — and when a release has been immediately re-expired, that recomputed
    balance is identical to what it was before the settlement began."
    PRD §3.8: "The unit's `current_price_minor` and `list_price_minor` are retained
    until it is re-listed, and its `accounting_state` is left exactly as it was — a
    `CAPITALIZED` unit stays `CAPITALIZED`, and a `WRITTEN_DOWN` unit stays
    `WRITTEN_DOWN`."

    Design: Difficulty/transitive_cascade/refund_cascades_order_to_release_entry_to_grant_status_to_balance
    """
    estate = setup_estate()
    seller = _seller_listing(estate)
    channel = seller["channel"]
    unit = seller["unit"]
    funded = setup_credit_source_grant(estate, loyalty_tier="PLUS")
    buyer = funded["customer"]
    grant_id = funded["grant"]["id"]
    assert funded["grant"]["issued_amount_minor"] == 11500

    # 10627 is exactly the 5000 bp cap on a total of 21255.
    order = _buy_fulfil_and_claim(buyer, channel, unit, 10627, "BUYER_REMORSE")
    assert order["credit_applied_minor"] == 10627
    assert order["cash_due_minor"] == 10628
    mid_grant = fetch_grant(grant_id)
    assert mid_grant["remaining_minor"] == 873
    assert mid_grant["status"] == "PARTIALLY_REDEEMED"
    assert fetch_customer(buyer["id"])["credit_balance_minor"] == 873

    settled = settle_return(order["id"], "REFUND")
    # Link 1.
    assert settled["status"] == "RETURNED"
    assert settled["restock_fee_minor"] == REMORSE_RESTOCK_FEE
    # 10628 cash less the 1755 channel fee and the 2340 restocking fee.
    assert settled["refund_cash_minor"] == 6533
    # The cash leg absorbed the whole 4095, so the credit leg comes back whole.
    assert settled["refund_credit_minor"] == 10627
    assert settled["version"] > order["version"]

    # Link 2, caused by link 1.
    entries = order_ledger_entries(order["id"])
    assert len(entries) == 2
    redeem, release = entries
    assert redeem["entry_type"] == "REDEEM"
    assert redeem["amount_minor"] == -10627
    assert_credit_ledger_entry(release)
    assert release["entry_type"] == "RELEASE"
    assert release["amount_minor"] == 10627
    assert release["balance_after_minor"] == 11500
    assert release["credit_grant_id"] == grant_id
    assert release["resale_order_id"] == order["id"]
    assert_instant(release["occurred_at"], "2026-08-01T00:00:00Z", "occurred_at")

    # Link 3, caused by link 2.
    restored = fetch_grant(grant_id)
    assert restored["remaining_minor"] == 11500
    assert restored["status"] == "ISSUED"
    assert restored["version"] > mid_grant["version"]

    # Link 4, re-derived from the grant set rather than incremented.
    assert fetch_customer(buyer["id"])["credit_balance_minor"] == 11500

    returned_unit = fetch_unit(unit["id"])
    assert_unit_dimensions(returned_unit, "RETURNED", "CAPITALIZED")
    assert_null(returned_unit["listed_channel_id"], "listed_channel_id")
    assert returned_unit["current_price_minor"] == GROSS
    assert returned_unit["list_price_minor"] == GROSS


def test_the_cascade_leaves_the_grant_partly_drawn_when_a_fee_is_retained():
    """The release restores only what the refund covers, and the balance follows it.

    PRD §3.8: "Release entries totalling `refund_credit_minor` are appended against
    the very grants that funded this order, walked in **reverse redemption order**
    — this order's own `REDEEM` entries taken by descending `occurred_at` and, where
    two share an instant, by descending `created_at`, never by identifier."
    PRD §3.8: "Each touched grant then has its `remaining_minor` increased by the
    released amount and its `status` recomputed: an `EXHAUSTED` grant that is partly
    refilled becomes `PARTIALLY_REDEEMED`, a `PARTIALLY_REDEEMED` grant whose
    `remaining_minor` is restored all the way back to its `issued_amount_minor`
    returns to `ISSUED`, and even an `EXPIRED` grant that funded part of this order
    accepts its release and becomes `PARTIALLY_REDEEMED`."
    PRD §3.8: "Any part of the non-refundable amount that the cash leg could not
    absorb is a shortfall: the non-refundable amount less `cash_due_minor`, again
    floored at zero."
    PRD §3.1: "Whenever brand currency moves, the balance is **recomputed from
    scratch** as the sum of `remaining_minor` over that customer's grants whose
    `status` is `ISSUED` or `PARTIALLY_REDEEMED`."
    PRD §3.8: "The **first link** writes `restock_fee_minor`, `refund_cash_minor`
    and `refund_credit_minor` onto the order, moves the order to `RETURNED`,
    increments its version, and moves the unit from `SOLD` to `RETURNED` with
    `listed_channel_id` cleared to null and its own version incremented."

    Design: Difficulty/transitive_cascade/refund_cascades_order_to_release_entry_to_grant_status_to_balance
    """
    estate = _open_policy_estate()
    seller = _seller_listing(estate)
    unit = seller["unit"]
    funded = _rich_buyer(estate)
    buyer = funded["customer"]
    grant_id = funded["grant"]["id"]

    order = _buy_fulfil_and_claim(
        buyer, seller["channel"], unit, 20755, "BUYER_REMORSE"
    )
    assert order["cash_due_minor"] == 500
    assert fetch_grant(grant_id)["remaining_minor"] == 27545

    settled = settle_return(order["id"], "REFUND")
    assert settled["status"] == "RETURNED"
    assert settled["refund_cash_minor"] == 0
    # 20755 less the 3595 the cash leg could not absorb.
    assert settled["refund_credit_minor"] == 17160

    entries = order_ledger_entries(order["id"])
    assert len(entries) == 2
    release = entries[1]
    assert release["entry_type"] == "RELEASE"
    assert release["amount_minor"] == 17160
    # 27545 + 17160, which is 3595 short of the original 48300.
    assert release["balance_after_minor"] == 44705

    partly_back = fetch_grant(grant_id)
    assert partly_back["remaining_minor"] == 44705
    # Restored, but not all the way to its issued amount.
    assert partly_back["status"] == "PARTIALLY_REDEEMED"
    assert fetch_customer(buyer["id"])["credit_balance_minor"] == 44705

    returned_unit = fetch_unit(unit["id"])
    assert returned_unit["lifecycle_state"] == "RETURNED"
    assert_null(returned_unit["listed_channel_id"], "listed_channel_id")


def test_a_warranty_refund_restores_the_conserved_quantity_exactly():
    """Three append-only rows sum back to the pre-order balance, to the minor unit.

    PRD §3.8: "For a `WARRANTY_DEFECT` claim, `restock_fee_minor` is 0 and the
    non-refundable amount is 0 as well — the channel fee **is** refunded, because
    the fault was the brand's."
    PRD §3.8: "For a warranty claim the two consequences of a zero non-refundable
    amount are that `refund_cash_minor` equals `cash_due_minor` exactly and
    `refund_credit_minor` equals `credit_applied_minor` exactly."
    PRD §2.9: "A movement is signed: `amount_minor` is positive for `ISSUE` and
    `RELEASE` entries and negative for `REDEEM` and `EXPIRE` entries, and
    `balance_after_minor` records the parent grant's `remaining_minor` immediately
    after that entry was applied."
    PRD §2.12: "And for every grant: its `remaining_minor` equals the sum of
    `amount_minor` across all of that grant's ledger entries, and the
    `balance_after_minor` of its most recent entry — the latest by `occurred_at`,
    tie-broken by the later `created_at` — equals its `remaining_minor`."
    PRD §2.12: "The compensating pair is redemption at order placement and release at
    refund settlement; a warranty settlement that releases into a grant which has
    already expired must append both the release and the offsetting expiry, so that
    every sum above is byte-identical to its value before the order was ever placed."
    PRD §3.8: "Each touched grant then has its `remaining_minor` increased by the
    released amount and its `status` recomputed: an `EXHAUSTED` grant that is partly
    refilled becomes `PARTIALLY_REDEEMED`, a `PARTIALLY_REDEEMED` grant whose
    `remaining_minor` is restored all the way back to its `issued_amount_minor`
    returns to `ISSUED`, and even an `EXPIRED` grant that funded part of this order
    accepts its release and becomes `PARTIALLY_REDEEMED`."

    Design: Difficulty/compensating_invariant/warranty_refund_restores_credit_ledger_conservation_exactly
    """
    estate = setup_estate()
    seller = _seller_listing(estate)
    funded = setup_credit_source_grant(estate, loyalty_tier="PLUS")
    buyer = funded["customer"]
    grant_id = funded["grant"]["id"]
    assert funded["grant"]["issued_amount_minor"] == 11500
    balance_before = fetch_customer(buyer["id"])["credit_balance_minor"]
    assert balance_before == 11500

    order = _buy_fulfil_and_claim(
        buyer, seller["channel"], seller["unit"], 10627, "WARRANTY_DEFECT"
    )
    assert_resale_order(order)
    assert order["credit_applied_minor"] == 10627
    assert order["cash_due_minor"] == 10628
    # 30 warranty days from the OUTERWEAR grade B tier, so the claim is well inside.
    assert_instant(
        order["warranty_expires_at"], "2026-08-31T00:00:00Z", "warranty_expires_at"
    )
    mid = fetch_grant(grant_id)
    assert mid["remaining_minor"] == 873
    assert mid["status"] == "PARTIALLY_REDEEMED"

    settled = settle_return(order["id"], "REFUND")
    assert settled["status"] == "RETURNED"
    assert settled["restock_fee_minor"] == 0
    assert settled["refund_cash_minor"] == 10628
    assert settled["refund_credit_minor"] == 10627

    restored = fetch_grant(grant_id)
    assert restored["remaining_minor"] == 11500
    assert restored["status"] == "ISSUED"

    entries = grant_ledger_entries(grant_id)
    # Nothing was deleted or rewritten: issuance, redemption, release.
    assert len(entries) == 3
    assert [e["entry_type"] for e in entries] == ["ISSUE", "REDEEM", "RELEASE"]
    assert [e["amount_minor"] for e in entries] == [11500, -10627, 10627]
    assert [e["balance_after_minor"] for e in entries] == [11500, 873, 11500]
    assert_ledger_balances_run(entries)
    assert_grant_conservation(restored, entries)
    assert sum(e["amount_minor"] for e in entries) == restored["remaining_minor"]

    # Byte-identical to the pre-order figure.
    assert fetch_customer(buyer["id"])["credit_balance_minor"] == balance_before


def test_the_release_walks_two_grants_in_reverse_redemption_order():
    """Both grants conserve exactly, and the shortfall lands on the first-drained one.

    PRD §3.8: "Release entries totalling `refund_credit_minor` are appended against
    the very grants that funded this order, walked in **reverse redemption order**
    — this order's own `REDEEM` entries taken by descending `occurred_at` and, where
    two share an instant, by descending `created_at`, never by identifier."
    PRD §3.8: "One `RELEASE` entry per grant is appended with a positive
    `amount_minor`, its `balance_after_minor` reflecting that grant's restored
    `remaining_minor`, and `resale_order_id` naming this order; the last grant
    reached may be only partially restored."
    PRD §3.8: "Each touched grant then has its `remaining_minor` increased by the
    released amount and its `status` recomputed: an `EXHAUSTED` grant that is partly
    refilled becomes `PARTIALLY_REDEEMED`, a `PARTIALLY_REDEEMED` grant whose
    `remaining_minor` is restored all the way back to its `issued_amount_minor`
    returns to `ISSUED`, and even an `EXPIRED` grant that funded part of this order
    accepts its release and becomes `PARTIALLY_REDEEMED`."
    PRD §3.7: "Redemption then walks that set as a **waterfall**, ordered by
    ascending `expires_at` and, where two grants expire together, by ascending
    `created_at` — never by identifier."
    PRD §2.12: "After every request that appends a ledger entry — a trade-in
    acceptance, a resale order placement, a return settlement and an expiry sweep —
    the following must hold for every customer: their `credit_balance_minor` equals
    the sum of `remaining_minor` over their grants whose `status` is `ISSUED` or
    `PARTIALLY_REDEEMED`, and equals the sum of `amount_minor` over all ledger
    entries belonging to those same grants."

    Design: Difficulty/compensating_invariant/warranty_refund_restores_credit_ledger_conservation_exactly
    """
    estate = _open_policy_estate()
    seller = _seller_listing(estate)
    first_source = setup_credit_source_grant(estate, loyalty_tier="PLUS")
    buyer = first_source["customer"]
    # A second mail-in trade-in by the same buyer, so both grants expire together
    # and the tie is broken by ascending created_at.
    second_source = setup_credit_source_grant(estate, customer=buyer)
    grant_one = first_source["grant"]
    grant_two = second_source["grant"]
    assert grant_one["issued_amount_minor"] == 11500
    assert grant_two["issued_amount_minor"] == 11500
    assert grant_one["expires_at"] == grant_two["expires_at"]
    assert fetch_customer(buyer["id"])["credit_balance_minor"] == 23000

    order = _buy_fulfil_and_claim(
        buyer, seller["channel"], seller["unit"], 20755, "BUYER_REMORSE"
    )
    assert order["credit_applied_minor"] == 20755
    assert order["cash_due_minor"] == 500
    # The waterfall emptied the earlier grant before touching the later one.
    drained = fetch_grant(grant_one["id"])
    assert drained["remaining_minor"] == 0
    assert drained["status"] == "EXHAUSTED"
    partial = fetch_grant(grant_two["id"])
    assert partial["remaining_minor"] == 2245
    assert partial["status"] == "PARTIALLY_REDEEMED"

    settled = settle_return(order["id"], "REFUND")
    assert settled["restock_fee_minor"] == REMORSE_RESTOCK_FEE
    assert settled["refund_cash_minor"] == 0
    # 20755 less the 3595 of the 4095 non-refundable amount that 500 of cash left.
    assert settled["refund_credit_minor"] == 17160
    assert NON_REFUNDABLE_ON_REMORSE - 500 == 3595

    # The later-drawn grant is refilled first and lands back on its issued amount.
    refilled = fetch_grant(grant_two["id"])
    assert refilled["remaining_minor"] == 11500
    assert refilled["status"] == "ISSUED"
    # The first-drained grant takes the shortfall and is only partly refilled.
    part_way = fetch_grant(grant_one["id"])
    assert part_way["remaining_minor"] == 7905
    assert part_way["status"] == "PARTIALLY_REDEEMED"

    one_entries = grant_ledger_entries(grant_one["id"])
    assert [e["entry_type"] for e in one_entries] == ["ISSUE", "REDEEM", "RELEASE"]
    assert [e["amount_minor"] for e in one_entries] == [11500, -11500, 7905]
    assert_ledger_balances_run(one_entries)
    assert_grant_conservation(part_way, one_entries)

    two_entries = grant_ledger_entries(grant_two["id"])
    assert [e["entry_type"] for e in two_entries] == ["ISSUE", "REDEEM", "RELEASE"]
    assert [e["amount_minor"] for e in two_entries] == [11500, -9255, 9255]
    assert_ledger_balances_run(two_entries)
    assert_grant_conservation(refilled, two_entries)

    order_entries = order_ledger_entries(order["id"])
    assert len(order_entries) == 4
    assert [e["entry_type"] for e in order_entries] == [
        "REDEEM",
        "REDEEM",
        "RELEASE",
        "RELEASE",
    ]
    # Redeemed earliest-first, released latest-first.
    assert [e["credit_grant_id"] for e in order_entries] == [
        grant_one["id"],
        grant_two["id"],
        grant_two["id"],
        grant_one["id"],
    ]

    # 23000 issued, 3595 of it retained as the unrecovered fee.
    assert fetch_customer(buyer["id"])["credit_balance_minor"] == 19405


def test_a_denial_returns_the_order_to_fulfilled_and_admits_a_fresh_claim():
    """The only non-terminal settlement: nothing moves and the window stays open.

    PRD §3.8: "**Denying** the claim is the cheapest resolution and the only one
    that is not terminal."
    PRD §3.8: "The order returns to `FULFILLED`, `reason_type` is reset to `NONE`,
    `return_requested_at` is cleared back to null, and the version is incremented."
    PRD §3.8: "No refund is computed, no ledger entry is appended and no unit
    moves."
    PRD §3.8: "Because the order is `FULFILLED` again, the buyer may raise a fresh
    claim — but only while the applicable window is still open, since the deadline is
    measured from `fulfilled_at` or against `warranty_expires_at` and a denial does
    not restart either."
    PRD §3.8: "A `BUYER_REMORSE` claim must be raised no later than fourteen days
    after `fulfilled_at` — the programme's two-week remorse window — and a claim
    raised after that is refused with `ERR_RETURN_WINDOW_CLOSED`."
    PRD §3.8: "A successful claim writes `reason_type` from the request, stamps
    `return_requested_at` from the logical clock and increments the order's version."

    Design: Corner/state_machines/deny_resolution_returns_the_order_to_fulfilled_and_clears_the_request
    """
    estate = setup_estate()
    seller = _seller_listing(estate)
    buyer = seller["customer"]
    unit = seller["unit"]

    order = place_order(buyer, seller["channel"], unit, 0)
    assert order["gross_price_minor"] == GROSS
    assert order["channel_fee_minor"] == FEE
    assert order["order_total_minor"] == TOTAL
    assert order["cash_due_minor"] == TOTAL

    set_clock("2026-08-02T00:00:00Z")
    fulfilled = fulfill_order(order["id"])
    assert_instant(fulfilled["fulfilled_at"], "2026-08-02T00:00:00Z", "fulfilled_at")
    # fulfilled_at plus the tier's 30 warranty days.
    assert_instant(
        fulfilled["warranty_expires_at"],
        "2026-09-01T00:00:00Z",
        "warranty_expires_at",
    )

    set_clock("2026-08-10T00:00:00Z")
    claimed = request_return(order["id"], buyer, "BUYER_REMORSE")
    assert claimed["status"] == "RETURN_REQUESTED"
    assert_instant(
        claimed["return_requested_at"], "2026-08-10T00:00:00Z", "return_requested_at"
    )

    denied = settle_return(order["id"], "DENY")
    assert denied["status"] == "FULFILLED"
    assert denied["reason_type"] == "NONE"
    assert_null(denied["return_requested_at"], "return_requested_at")
    assert denied["refund_cash_minor"] == 0
    assert denied["refund_credit_minor"] == 0
    assert denied["restock_fee_minor"] == 0
    assert denied["version"] > claimed["version"]
    # The denial did not disturb the handover instants either.
    assert_instant(denied["fulfilled_at"], "2026-08-02T00:00:00Z", "fulfilled_at")

    assert fetch_unit(unit["id"])["lifecycle_state"] == "SOLD"
    rows, meta = validate_paginated(
        api_client.list_resale_order_ledger_entries(order["id"], MERCH)
    )
    assert rows == []
    assert_pagination_meta(meta, 0)

    # 2026-08-10 is still inside fulfilled_at + 14 days, so a second claim stands.
    again = request_return(order["id"], buyer, "BUYER_REMORSE")
    assert again["status"] == "RETURN_REQUESTED"
    assert again["reason_type"] == "BUYER_REMORSE"
    assert_instant(
        again["return_requested_at"], "2026-08-10T00:00:00Z", "return_requested_at"
    )


def test_the_two_after_sale_deadlines_close_independently():
    """The remorse window shuts on day 15 while the warranty still has a fortnight.

    PRD §3.8: "The two reasons then face different deadlines, both inclusive."
    PRD §3.8: "A `BUYER_REMORSE` claim must be raised no later than fourteen days
    after `fulfilled_at` — the programme's two-week remorse window — and a claim
    raised after that is refused with `ERR_RETURN_WINDOW_CLOSED`."
    PRD §3.8: "A `WARRANTY_DEFECT` claim must be raised no later than
    `warranty_expires_at`, which the tier's `warranty_days` fixed at fulfilment; a
    claim raised after that instant is refused with `ERR_WARRANTY_EXPIRED`."
    PRD §3.8: "The order returns to `FULFILLED`, `reason_type` is reset to `NONE`,
    `return_requested_at` is cleared back to null, and the version is incremented."
    PRD §3.8: "The unit is left completely untouched while the claim is pending — it
    stays `SOLD`."

    Design: Corner/errors/after_sale_window_errors_are_triggerable_on_both_reason_types
    """
    estate = setup_estate()
    seller = _seller_listing(estate)
    buyer = create_customer(email="ben@example.com", full_name="Ben Ortiz")

    order = place_order(buyer, seller["channel"], seller["unit"], 0)
    fulfilled = fulfill_order(order["id"])
    assert_instant(fulfilled["fulfilled_at"], "2026-08-01T00:00:00Z", "fulfilled_at")
    assert_instant(
        fulfilled["warranty_expires_at"],
        "2026-08-31T00:00:00Z",
        "warranty_expires_at",
    )

    # The inclusive remorse deadline was 2026-08-15T00:00:00Z.
    set_clock("2026-08-16T00:00:00Z")
    validate_error(
        api_client.request_resale_order_return(
            order["id"],
            return_request_payload("BUYER_REMORSE"),
            make_customer_headers(buyer["id"]),
        ),
        "ERR_RETURN_WINDOW_CLOSED",
        409,
    )

    # At that very instant the 30-day warranty is still open.
    warranty_claim = request_return(order["id"], buyer, "WARRANTY_DEFECT")
    assert warranty_claim["status"] == "RETURN_REQUESTED"
    assert warranty_claim["reason_type"] == "WARRANTY_DEFECT"
    assert_instant(
        warranty_claim["return_requested_at"],
        "2026-08-16T00:00:00Z",
        "return_requested_at",
    )
    assert fetch_unit(seller["unit"]["id"])["lifecycle_state"] == "SOLD"

    denied = settle_return(order["id"], "DENY")
    assert denied["status"] == "FULFILLED"
    assert denied["reason_type"] == "NONE"

    # 2026-09-01 is strictly past warranty_expires_at.
    set_clock("2026-09-01T00:00:00Z")
    validate_error(
        api_client.request_resale_order_return(
            order["id"],
            return_request_payload("WARRANTY_DEFECT"),
            make_customer_headers(buyer["id"]),
        ),
        "ERR_WARRANTY_EXPIRED",
        409,
    )

    # Both refusals left the order exactly where the denial put it.
    final = fetch_order(order["id"])
    assert final["status"] == "FULFILLED"
    assert final["reason_type"] == "NONE"
    assert_null(final["return_requested_at"], "return_requested_at")
    assert fetch_unit(seller["unit"]["id"])["lifecycle_state"] == "SOLD"
