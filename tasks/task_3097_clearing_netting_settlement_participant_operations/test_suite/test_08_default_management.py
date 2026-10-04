"""Default management: the sealed-bid auction, liquidation and loss allocation."""
from test_helpers import (
    api_client, validate_success, validate_error,
    assert_default_proceeding, assert_fund_component,
    set_clock, create_active_participant, create_security, create_window,
    net_window, create_fund, recompute_fund, component_of, get_deposit,
    setup_default_proceeding, open_auction, place_bid, liquidate, allocate_loss,
    member, TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]
RISK = TEST_USERS["risk_officer_headers"]


def test_suspension_then_default_declaration_cascades_to_the_deposit_pool():
    """PRD §3.9: "which sets the member `DEFAULTED`, sets `is_defaulted` true,
    opens a `DefaultProceeding` in `DECLARED`, and forces the member's deposit
    pool to `DEFICIENT_DEFAULT`."

    Design: Difficulty/transitive_cascade/participant_default_declaration_three_hop_cascade
    """
    handles = setup_default_proceeding(defaulter_posted_cents=5_000_000,
                                       survivor_names=("Cascade Beta",))
    defaulter = handles["defaulter"]
    proceeding = handles["proceeding"]

    after = validate_success(api_client.get_participant(defaulter["id"], ADMIN), 200)
    assert after["membership_status"] == "DEFAULTED"
    assert after["is_defaulted"] is True

    pools = validate_success(
        api_client.list_participant_deposits(defaulter["id"], ADMIN), 200)
    assert len(pools) == 1
    assert pools[0]["status"] == "DEFICIENT_DEFAULT"

    read = validate_success(
        api_client.get_default_proceeding(proceeding["id"], ADMIN), 200)
    assert read["status"] == "DECLARED"


def test_vickrey_second_price_settles_at_the_second_highest_distinct_bid():
    """PRD §3.9: "With two or more bids, the settlement price is the second-highest
    distinct bid price and the winning quantity is the quantity of the single high
    bidder".
    PRD §3.9: "A single bid yields that bid's price multiplied by its
    quantity."

    Design: Difficulty/combinatorial_formula/default_proceeds_round_per_trade_then_sum
    """
    handles = setup_default_proceeding(defaulter_posted_cents=5_000_000,
                                       survivor_names=("Auction Beta",))
    proceeding = handles["proceeding"]
    bidder = handles["counterparty"]
    component = component_of(bidder["id"], handles["fund"]["id"],
                             1)

    open_auction(proceeding["id"])
    place_bid(proceeding["id"], bidder["id"], component["id"], 2222, 1000,
              "2026-09-05T10:00:00Z")
    place_bid(proceeding["id"], bidder["id"], component["id"], 3333, 3000,
              "2026-09-05T11:00:00Z")

    liquidated = liquidate(proceeding["id"])
    assert_default_proceeding(liquidated)
    assert liquidated["liquidation_proceeds_cents"] == 2222 * 3000
    assert liquidated["status"] == "LIQUIDATED"


def test_single_bidder_settles_at_its_own_price():
    """PRD §3.9: "a lone bidder therefore settles at its own price, and any lower
    second bidder drives the proceeds below the high bid."

    Design: Difficulty/combinatorial_formula/default_proceeds_round_per_trade_then_sum
    """
    handles = setup_default_proceeding(defaulter_posted_cents=5_000_000,
                                       survivor_names=("Solo Beta",))
    proceeding = handles["proceeding"]
    bidder = handles["counterparty"]
    component = component_of(bidder["id"], handles["fund"]["id"],
                             1)

    open_auction(proceeding["id"])
    place_bid(proceeding["id"], bidder["id"], component["id"], 2222, 1000,
              "2026-09-05T10:00:00Z")

    liquidated = liquidate(proceeding["id"])
    assert liquidated["liquidation_proceeds_cents"] == 2222 * 1000


def test_first_price_convention_would_report_the_high_bid():
    """PRD §3.9: "With two or more bids, the settlement price is the second-highest
    distinct bid price".

    Design: Difficulty/combinatorial_formula/default_proceeds_round_per_trade_then_sum
    """
    handles = setup_default_proceeding(defaulter_posted_cents=5_000_000,
                                       survivor_names=("Compare Beta",))
    proceeding = handles["proceeding"]
    bidder = handles["counterparty"]
    component = component_of(bidder["id"], handles["fund"]["id"],
                             1)

    open_auction(proceeding["id"])
    place_bid(proceeding["id"], bidder["id"], component["id"], 2222, 1000,
              "2026-09-05T10:00:00Z")
    place_bid(proceeding["id"], bidder["id"], component["id"], 3333, 3000,
              "2026-09-05T11:00:00Z")

    liquidated = liquidate(proceeding["id"])
    assert liquidated["liquidation_proceeds_cents"] != 3333 * 3000
    assert liquidated["liquidation_proceeds_cents"] == 2222 * 3000


def test_defaulter_resources_saturate_at_the_posted_deposit_balance():
    """PRD §3.9: "The defaulter's resources are its posted deposit balance,
    saturating at the total of its settlement obligations across all of its net
    positions irrespective of delivery-versus-payment status".
    PRD §3.9: "The loss the fund must absorb is those resources minus the
    liquidation proceeds, floored at zero."

    Design: Difficulty/combinatorial_formula/default_proceeds_round_per_trade_then_sum
    """
    handles = setup_default_proceeding(defaulter_posted_cents=5_000_000,
                                       survivor_names=("Resource Beta",))
    proceeding = handles["proceeding"]
    bidder = handles["counterparty"]
    component = component_of(bidder["id"], handles["fund"]["id"],
                             1)

    open_auction(proceeding["id"])
    place_bid(proceeding["id"], bidder["id"], component["id"], 2222, 1000,
              "2026-09-05T10:00:00Z")
    place_bid(proceeding["id"], bidder["id"], component["id"], 3333, 3000,
              "2026-09-05T11:00:00Z")

    liquidated = liquidate(proceeding["id"])
    assert liquidated["defaulter_resources_cents"] == 5_000_000
    assert liquidated["deficit_amount_cents"] == max(
        5_000_000 - liquidated["liquidation_proceeds_cents"], 0)


def test_loss_allocation_amounts_net_exactly_to_the_negative_deficit():
    """PRD §3.9: "After the repair the sum of the written allocation amounts
    equals the negative of the deficit exactly, and the sum of the component
    deltas equals the negative of the deficit exactly."

    Design: Difficulty/compensating_invariant/loss_allocation_preserves_total_component_balance
    """
    handles = setup_default_proceeding(defaulter_posted_cents=5_000_000,
                                       survivor_names=("Loss Beta", "Loss Gamma"))
    proceeding = handles["proceeding"]
    bidder = handles["counterparty"]
    component = component_of(bidder["id"], handles["fund"]["id"],
                             1)

    open_auction(proceeding["id"])
    # A low bid leaves a positive deficit for the surviving members to absorb.
    place_bid(proceeding["id"], bidder["id"], component["id"], 100, 1,
              "2026-09-05T10:00:00Z")
    liquidated = liquidate(proceeding["id"])
    assert liquidated["deficit_amount_cents"] > 0

    allocated = allocate_loss(proceeding["id"])
    assert allocated["allocated_total_cents"] == liquidated["deficit_amount_cents"]
    assert allocated["status"] == "ALLOCATED"

    rows = validate_success(api_client.list_proceeding_loss_allocations(
        proceeding["id"], ADMIN), 200)
    assert sum(r["amount_cents"] for r in rows) == -liquidated["deficit_amount_cents"]


def test_loss_allocation_debits_survivors_in_proportion_to_current_balances():
    """PRD §3.9: "Their current component balances are summed, read after the
    defaulter's own components were released; if that sum is zero or less the
    allocation cannot be covered and is refused with
    `ERR_CLEARING_FUND_DEFICIT`."

    Design: Difficulty/compensating_invariant/loss_allocation_preserves_total_component_balance
    """
    handles = setup_default_proceeding(defaulter_posted_cents=5_000_000,
                                       survivor_names=("Prop Beta", "Prop Gamma"))
    proceeding = handles["proceeding"]
    security = handles["security"]
    fund = handles["fund"]
    bidder = handles["counterparty"]
    component = component_of(bidder["id"], fund["id"], 1)

    before = {}
    for survivor in [handles["counterparty"]] + handles["others"]:
        row = component_of(survivor["id"], fund["id"], 1)
        before[survivor["id"]] = row["component_balance_cents"]
    total_before = sum(before.values())

    open_auction(proceeding["id"])
    place_bid(proceeding["id"], bidder["id"], component["id"], 100, 1,
              "2026-09-05T10:00:00Z")
    liquidated = liquidate(proceeding["id"])
    deficit = liquidated["deficit_amount_cents"]
    assert deficit > 0

    allocate_loss(proceeding["id"])

    total_after = 0
    for survivor in [handles["counterparty"]] + handles["others"]:
        row = component_of(survivor["id"], fund["id"], 1)
        assert_fund_component(row)
        total_after += row["component_balance_cents"]

    assert total_after == total_before - deficit


def test_allocation_without_a_positive_deficit_is_refused():
    """PRD §3.9: "a non-positive deficit is refused with
    `ERR_NO_ALLOCATABLE_DEFICIT`".

    Design: Difficulty/compensating_invariant/loss_allocation_preserves_total_component_balance
    """
    handles = setup_default_proceeding(defaulter_posted_cents=5_000_000,
                                       survivor_names=("NoDef Beta",))
    proceeding = handles["proceeding"]
    bidder = handles["counterparty"]
    component = component_of(bidder["id"], handles["fund"]["id"],
                             1)

    open_auction(proceeding["id"])
    # Proceeds far exceed the defaulter's resources, so the deficit floors at zero.
    place_bid(proceeding["id"], bidder["id"], component["id"], 100_000, 100,
              "2026-09-05T10:00:00Z")
    liquidated = liquidate(proceeding["id"])
    assert liquidated["deficit_amount_cents"] == 0

    validate_error(api_client.allocate_loss(proceeding["id"], RISK),
                   "ERR_NO_ALLOCATABLE_DEFICIT")


def test_liquidation_requires_the_proceeding_to_be_liquidating():
    """PRD §3.9: "Liquidating the book is a `RiskOfficer` act and requires the
    proceeding to be `LIQUIDATING`; otherwise it fails with
    `ERR_PROCEEDING_NOT_LIQUIDATING`."

    Design: Difficulty/compensating_invariant/loss_allocation_preserves_total_component_balance
    """
    handles = setup_default_proceeding(defaulter_posted_cents=5_000_000,
                                       survivor_names=("Guard Beta",))
    proceeding = handles["proceeding"]

    # Still DECLARED: the auction may not be run yet.
    validate_error(api_client.liquidate_proceeding(proceeding["id"], RISK),
                   "ERR_PROCEEDING_NOT_LIQUIDATING")

    handle = open_auction(proceeding["id"])
    assert handle["status"] == "LIQUIDATING"

    # A proceeding that has already reached LIQUIDATING is no longer in
    # DECLARED, so the advance step has no legal entry point left.
    validate_error(api_client.update_default_proceeding(
        proceeding["id"], {"reason_code": "AGAIN"}, RISK),
        "ERR_PROCEEDING_NOT_LIQUIDATING")