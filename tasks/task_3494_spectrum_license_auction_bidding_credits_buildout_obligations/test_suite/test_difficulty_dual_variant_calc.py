"""Depth tests for the two dual-variant calculations: settlement pricing
(provisional vs final net) and relocation cost shares (proportional vs equal).
Same inputs, two pinned variants — the variants must diverge exactly as the
PRD formulas say."""
from test_helpers import (
    SECOND_GRANT_DAY_ISO,
    TRANSITION_WINDOW_END_ISO,
    TRANSITION_WINDOW_START_ISO,
    UPFRONT_10M_UNITS,
    UPFRONT_20M_UNITS,
    assert_incumbent,
    assert_license,
    assert_license_price_invariants,
    assert_shares_cover_cost,
    get_incumbent,
    get_license,
    incumbent_begin_relocation,
    incumbent_confirm_cleared,
    incumbent_submit_plan,
    list_licenses,
    register_incumbent,
    set_clock,
    setup_closed_auction_with_licenses,
    settle_license_in_full,
)


def test_settlement_provisional_vs_final_net_price(api):
    """PRD §3.6: "The provisional variant, `provisional_net_price_cents`, is
    `gross_clock_price_cents` scaled by (100 minus `credit_pct`) percent and
    rounded half up to a whole cent; because it excludes the assignment bid it
    is invariant to the assignment phase, and identical clock data yields a
    different provisional and final figure whenever any assignment bid exceeds
    0."
    PRD §3.6: "The final variant, `net_price_cents`, applies the same scaling
    to `gross_final_price_cents` and is the settlement amount actually due."
    PRD §3.6: "The `credit_amount_cents` — the dollar value of the bidding
    credit, and the basis for unjust-enrichment repayment at transfer time —
    is `gross_final_price_cents` minus `net_price_cents`."

    Design: Difficulty/dual_variant_calc/settlement_provisional_vs_final_net_price
    """
    ctx = setup_closed_auction_with_licenses(
        bids=[(0, "PEA002", "CATEGORY_A", 1)],
        assignment_amounts={(0, "PEA002", "CATEGORY_A"): 7_000_000},
        area_codes=("PEA002",),
        block_categories=("CATEGORY_A",),
        bidder_specs=[
            {
                "legal_name": "Rural Wireless Co",
                "claims_rural_credit": True,
                "service_population": 200_000,
            }
        ],
    )
    lic = ctx["licenses"][0]
    assert_license(lic)
    assert_license_price_invariants(lic)
    # Clock-price basis: 10 MHz * 500,000 pop * 50 cents = 250,000,000.
    assert lic["gross_clock_price_cents"] == 250_000_000
    assert lic["assignment_bid_cents"] == 7_000_000
    assert lic["gross_final_price_cents"] == 257_000_000
    # Provisional (assignment-invariant): 250,000,000 * 85/100.
    assert lic["provisional_net_price_cents"] == 212_500_000
    # Final (assignment-inclusive): 257,000,000 * 85/100.
    assert lic["net_price_cents"] == 218_450_000
    assert lic["provisional_net_price_cents"] != lic["net_price_cents"]
    assert lic["credit_amount_cents"] == 38_550_000
    assert lic["credit_pct"] == 15
    assert lic["status"] == "PENDING_PAYMENT"
    assert lic["frequency_block_index"] == 0


def test_relocation_share_proportional_vs_equal_split(api):
    """PRD §3.7: "The binding schedule, `shares_proportional`, gives each
    license a base amount of the cost multiplied by the license's units and
    divided by the total units across those licenses, rounded down; the
    leftover cents are then distributed one cent at a time to licenses ordered
    by units descending, ties broken by the license's `created_at` ascending —
    never by id — until the remainder is exhausted."
    PRD §3.7: "The dispute-reference schedule, `shares_equal`, gives each
    license an equal base of the cost divided by the number of licenses,
    rounded down, with the same remainder rule."
    PRD §3.7: "The proportional amounts are posted onto each license's
    `relocation_share_owed_cents`, syncing the license ledger; if no `ACTIVE`
    licenses exist in the area, both arrays are empty and nothing is posted."

    Design: Difficulty/dual_variant_calc/relocation_share_proportional_vs_equal_split
    """
    ctx = setup_closed_auction_with_licenses(
        bids=[
            (0, "PEA001", "CATEGORY_A", 1),
            (1, "PEA001", "CATEGORY_B", 1),
        ],
        area_codes=("PEA001",),
        block_categories=("CATEGORY_A", "CATEGORY_B"),
        bidder_specs=[
            {"legal_name": "Winner One LLC", "upfront_cents": UPFRONT_10M_UNITS},
            {"legal_name": "Winner Two LLC", "upfront_cents": UPFRONT_20M_UNITS},
        ],
    )
    w1, w2 = ctx["applicants"]
    lic_a = list_licenses(holder_applicant_id=w1["id"])[0]  # 10 MHz * 1,000,000 = 10M units
    lic_b = list_licenses(holder_applicant_id=w2["id"])[0]  # 20 MHz * 1,000,000 = 20M units

    # Incumbent must be RELOCATING before settlement or the grants are blocked.
    incumbent = register_incumbent(
        ctx["plan"]["id"],
        ctx["areas"]["PEA001"]["id"],
        callsign="KOLD940",
        relocation_cost_cents=100_000_001,
    )
    incumbent_submit_plan(incumbent["id"])
    incumbent_begin_relocation(
        incumbent["id"], TRANSITION_WINDOW_START_ISO, TRANSITION_WINDOW_END_ISO
    )

    set_clock(SECOND_GRANT_DAY_ISO)  # 2026-10-02
    lic_a = settle_license_in_full(lic_a)
    lic_b = settle_license_in_full(lic_b)
    assert lic_a["status"] == "ACTIVE"
    assert lic_b["status"] == "ACTIVE"

    set_clock(TRANSITION_WINDOW_END_ISO)  # 2026-11-05: window end reached
    incumbent_confirm_cleared(incumbent["id"])

    incumbent_after = get_incumbent(incumbent["id"])
    assert_incumbent(incumbent_after)
    assert incumbent_after["status"] == "CLEARED"

    # Binding variant: floor shares 33,333,333 / 66,666,667 leave 1 cent,
    # which lands on the larger-units license (B).
    proportional = {
        s["license_id"]: s["amount_cents"]
        for s in incumbent_after["shares_proportional"]
    }
    assert proportional == {lic_a["id"]: 33_333_333, lic_b["id"]: 66_666_668}
    # Dispute-reference variant: equal base 50,000,000 each, the same 1-cent
    # remainder again lands on the larger-units license (B).
    equal = {
        s["license_id"]: s["amount_cents"] for s in incumbent_after["shares_equal"]
    }
    assert equal == {lic_a["id"]: 50_000_000, lic_b["id"]: 50_000_001}

    # The binding (proportional) amounts are posted onto the license ledger.
    assert get_license(lic_a["id"])["relocation_share_owed_cents"] == 33_333_333
    assert get_license(lic_b["id"])["relocation_share_owed_cents"] == 66_666_668
    # Largest-remainder allocation conserves every cent of the cost.
    assert_shares_cover_cost(incumbent_after["shares_proportional"], 100_000_001)
    assert_shares_cover_cost(incumbent_after["shares_equal"], 100_000_001)
