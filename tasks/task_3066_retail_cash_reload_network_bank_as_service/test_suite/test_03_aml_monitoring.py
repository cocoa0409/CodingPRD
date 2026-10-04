"""AML monitoring: velocity windows, the structuring predicate and the
daily-counter reset semantics (PRD §3.6, §2.9).
"""
import pytest

from test_helpers import (
    get_success_data, get_account, get_location, set_clock,
    setup_network, create_load, create_load_raw, create_and_fund_load,
    setup_velocity_boundary, setup_structuring_account,
    VELOCITY_TXN_LIMIT, VELOCITY_AMOUNT_LIMIT_CENTS,
    api_client, ApiErrorId, validate_error,
)


# ---------------------------------------------------------------------------
# Velocity boundary
# ---------------------------------------------------------------------------

def test_velocity_count_reaches_exactly_five_and_trips_inclusively():
    """PRD §3.6: "The breach predicate is that the count reaches the transaction
    limit or the amount reaches the amount limit under whichever variant is being
    evaluated, and both boundaries are inclusive."

    Design: Difficulty/boundary_precision_check/velocity_count_limit_inclusive_at_five
    """
    net, funded, nxt = setup_velocity_boundary(funded_count=VELOCITY_TXN_LIMIT)
    account = get_account(net["account"]["id"])
    assert account["window_load_count"] == VELOCITY_TXN_LIMIT
    # PRD §3.4 recomputes the store's `is_velocity_breached` on each funding.
    assert get_location(net["location"]["id"])["is_velocity_breached"] is True
    assert nxt["load_status"] == "INITIATED"


def test_velocity_sixth_funding_is_refused_and_leaves_the_count_at_five():
    """PRD §3.4: "the window trip that the load would produce must not exceed the
    velocity transaction limit or the velocity amount limit under the active
    variant, else `ERR_VELOCITY_LIMIT_EXCEEDED` (HTTP 422). A load that lands
    exactly at a limit is permitted".
    PRD §3.6: "The breach predicate is that the count reaches the transaction
    limit or the amount reaches the amount limit under whichever variant is being
    evaluated, and both boundaries are inclusive."

    Design: Difficulty/boundary_precision_check/velocity_count_limit_inclusive_at_five
    """
    net, funded, nxt = setup_velocity_boundary(funded_count=VELOCITY_TXN_LIMIT)
    result = api_client.fund_load(nxt["id"], net["clerk_headers"])
    validate_error(result, ApiErrorId.ERR_VELOCITY_LIMIT_EXCEEDED, 422)
    assert get_account(net["account"]["id"])["window_load_count"] == VELOCITY_TXN_LIMIT
    load = get_success_data(api_client.get_load(nxt["id"], net["clerk_headers"]))
    assert load["load_status"] == "INITIATED"


def test_velocity_four_funded_loads_do_not_trip_the_breach_flag():
    """PRD §3.6: "The breach predicate is that the count reaches the transaction
    limit or the amount reaches the amount limit under whichever variant is being
    evaluated, and both boundaries are inclusive."

    Design: Difficulty/boundary_precision_check/velocity_count_limit_inclusive_at_five
    """
    net, funded, nxt = setup_velocity_boundary(funded_count=4)
    account = get_account(net["account"]["id"])
    assert account["window_load_count"] == 4
    assert get_location(net["location"]["id"])["is_velocity_breached"] is False


def test_velocity_amount_limit_is_inclusive_at_exactly_the_constant():
    """PRD §3.6: "The velocity trip measures an account's recent load activity
    against two ceilings: five transactions and 1,000,000 cents of principal."
    PRD §3.6: "both boundaries are inclusive."

    Design: Corner/calculations/velocity_score_matches_constant_limit
    """
    net = setup_network(agreement_overrides={
        "per_transaction_limit_cents": 1_500_000,
        "daily_location_limit_cents": 9_000_000,
    })
    create_and_fund_load(net["location"], net["account"], net["agreement"],
                         principal_cents=VELOCITY_AMOUNT_LIMIT_CENTS)
    account = get_account(net["account"]["id"])
    assert account["window_load_cents"] == VELOCITY_AMOUNT_LIMIT_CENTS
    assert account["window_load_count"] == 1
    # PRD §3.4 recomputes the store's `is_velocity_breached` on each funding.
    assert get_location(net["location"]["id"])["is_velocity_breached"] is True


# ---------------------------------------------------------------------------
# Structuring
# ---------------------------------------------------------------------------

def test_structuring_predicate_true_at_three_band_loads():
    """PRD §3.6: "The count tier is met when that count reaches 3, and the total
    tier is met when the summed principal reaches 27,000 cents. The account is
    structuring exactly when *both* tiers are met."
    PRD §3.6: "Three loads of 9000 cents satisfy both tiers and yield true".

    Design: Corner/calculations/structuring_predicate_true_at_three_band_loads
    """
    net, loads = setup_structuring_account(principals=(9000, 9500, 9999))
    account = get_account(net["account"]["id"])
    assert account["structuring_txn_count"] == 3
    assert account["is_structuring"] is True
    assert account["compliance_hold_status"] == "CLEAR"


def test_structuring_two_loads_of_9999_stay_false():
    """PRD §3.6: "two loads of 9999 cents sum to 19,998 cents and count only two,
    so both tiers fail and the answer is false".

    Design: Corner/calculations/structuring_predicate_true_at_three_band_loads
    """
    net, loads = setup_structuring_account(principals=(9999, 9999))
    account = get_account(net["account"]["id"])
    assert account["structuring_txn_count"] == 2
    assert account["is_structuring"] is False


def test_structuring_three_loads_of_10000_are_outside_the_band():
    """PRD §3.6: "three loads of 10,000 cents each sit outside the band because
    10,000 exceeds the band's upper bound, so they yield false as well."

    Design: Corner/calculations/structuring_predicate_true_at_three_band_loads
    """
    net, loads = setup_structuring_account(principals=(10000, 10000, 10000))
    account = get_account(net["account"]["id"])
    assert account["structuring_txn_count"] == 0
    assert account["is_structuring"] is False


# ---------------------------------------------------------------------------
# Dual variant: trailing 24h vs epoch day
# ---------------------------------------------------------------------------

def test_velocity_amount_reads_the_same_under_both_variants_for_a_same_day_burst():
    """PRD §3.6: "The trailing variant looks back 24 hours from the current clock
    instant, counting loads whose `funded_at` is strictly later than the instant
    24 hours ago and no later than the current instant; the window moves with every
    read and nothing is ever reset".

    Design: Difficulty/dual_variant_calc/velocity_trailing_window_vs_epoch_day_reset
    """
    net = setup_network()
    for _ in range(3):
        create_and_fund_load(net["location"], net["account"], net["agreement"],
                             principal_cents=3000)
    account = get_account(net["account"]["id"])
    # Three loads funded inside one logical day: both readings agree at 3 / 9000.
    assert account["window_load_count"] == 3
    assert account["window_load_cents"] == 9000


def test_daily_location_counter_resets_at_the_logical_day_rollover():
    """PRD §3.6: "The epoch-day variant counts loads belonging to the current
    logical day instead, so it drops to zero at each day rollover".
    PRD §2.9: "An *epoch day* is a logical-day bucket derived from the clock".

    Design: Corner/cross_cutting_complexity_layers/daily_counter_reset_moves_with_the_logical_day
    """
    net = setup_network(clock="2026-09-01T20:00:00Z")
    create_and_fund_load(net["location"], net["account"], net["agreement"],
                         principal_cents=3000)
    before = get_location(net["location"]["id"])
    assert before["daily_accepted_cents"] > 0
    set_clock("2026-09-02T00:00:00Z")
    after = get_location(net["location"]["id"])
    assert after["daily_accepted_cents"] == 0
    assert after["daily_txn_count"] == 0
    assert after["last_epoch_index"] == before["last_epoch_index"] + 1


def test_trailing_window_keeps_counting_loads_across_a_day_rollover():
    """PRD §3.6: "the window moves with every read and nothing is ever reset, which
    is why a burst that straddles midnight still counts in full."

    Design: Difficulty/dual_variant_calc/velocity_trailing_window_vs_epoch_day_reset
    """
    net = setup_network(clock="2026-09-01T20:00:00Z")
    create_and_fund_load(net["location"], net["account"], net["agreement"],
                         principal_cents=3000)
    set_clock("2026-09-02T00:00:00Z")
    account = get_account(net["account"]["id"])
    # The epoch-day daily counter reset, but the trailing window still holds the load.
    assert get_location(net["location"]["id"])["daily_txn_count"] == 0
    assert account["window_load_count"] == 1