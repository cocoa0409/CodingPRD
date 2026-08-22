"""Interval arithmetic on the two conventions the platform keeps apart:
half-open sponsor-distribution effective windows and closed wash windows.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_harvest,
    create_block_payload,
    create_distribution,
    create_distribution_payload,
    create_harvest_proposal,
    evaluate_drift,
    execute_harvest,
    get_account,
    get_model_version,
    get_success_data,
    get_trade_order,
    list_tax_lots,
    list_trade_orders,
    make_sponsor_operator_headers,
    rebalance,
    set_clock,
    setup_harvest_ready_account,
    setup_platform,
    validate_error,
    validate_success,
)

MANAGER_HEADERS = TEST_USERS["portfolio_manager_headers"]

WASH_SECURITIES = [
    ("ALFA", "Alfa Industrials", 10_000),
    ("BETA", "Beta Materials", 5_000),
]
WASH_SLEEVES = [("ALFA", 5000), ("BETA", 5000)]


# ---------------------------------------------------------------------------
# Local multi-step setups
# ---------------------------------------------------------------------------
def _env_with_january_to_june_window():
    """A PUBLISHED version distributed to one sponsor for the window running
    from 2026-01-01 inclusive to 2026-06-01 exclusive."""
    env = setup_platform(
        securities=[("ALFA", "Alfa Industrials", 10_000)],
        sleeves=[("ALFA", 10000)],
    )
    env["distribution"] = create_distribution(
        env["sponsor"]["id"],
        env["model_version"]["id"],
        effective_from="2026-01-01T00:00:00Z",
        effective_until="2026-06-01T00:00:00Z",
    )
    return env


def _distributions_on_key(api, env):
    response = api.list_distributions(
        MANAGER_HEADERS,
        params={"sponsor_id": env["sponsor"]["id"], "model_id": env["model"]["id"]},
    )
    return get_success_data(response)


def _env_with_stamped_wash_window():
    """ALFA and BETA booked in kind on 2026-06-01, the whole ALFA position
    harvested at a loss on 2026-08-01, then a rebalance that wants to buy ALFA
    straight back. Returns the env plus `buy_back_order`."""
    set_clock("2026-06-01T00:00:00Z")
    env = setup_harvest_ready_account(
        securities=WASH_SECURITIES,
        sleeves=WASH_SLEEVES,
        model_overrides={"drift_threshold_bps": 300},
        cash_cents=2_000_000,
        positions=[("ALFA", 100, 1_200_000), ("BETA", 200, 1_000_000)],
    )
    account_id = env["account"]["id"]
    sponsor_id = env["sponsor"]["id"]
    alfa_id = env["securities"]["ALFA"]["id"]

    set_clock("2026-08-01T00:00:00Z")
    proposal = create_harvest_proposal(account_id, alfa_id, 100)
    approve_harvest(proposal["id"])
    env["harvest"] = execute_harvest(proposal["id"])

    evaluate_drift(account_id, sponsor_id, "SETTLED")
    rebalance(account_id, sponsor_id)
    env["account"] = get_account(account_id)
    env["buy_back_order"] = list_trade_orders(
        account_id=account_id, security_id=alfa_id, status="PROPOSED"
    )[0]
    return env


# ---------------------------------------------------------------------------
# Half-open sponsor-distribution effective windows
# ---------------------------------------------------------------------------
def test_distribution_window_starting_inside_a_live_window_collides(api):
    """PRD §2.10: "Two windows collide when the first window's start is strictly
    earlier than the second's end and the second window's start is strictly
    earlier than the first's end, treating a null end as unbounded."

    Design: Difficulty/resource_temporal_overlap/distribution_half_open_window_collides_but_touching_endpoints_do_not
    """
    env = _env_with_january_to_june_window()
    current_version = get_model_version(env["model_version"]["id"])["version"]

    response = api.create_distribution(
        create_distribution_payload(
            env["sponsor"]["id"],
            env["model_version"]["id"],
            current_version,
            "2026-05-01T00:00:00Z",
        ),
        MANAGER_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_DISTRIBUTION_WINDOW_OVERLAP.value)

    rows = _distributions_on_key(api, env)
    assert len(rows) == 1, "the rejected window must not have been persisted"
    assert rows[0]["id"] == env["distribution"]["id"]


def test_distribution_window_starting_on_the_excluded_endpoint_is_accepted(api):
    """PRD §2.10: "Because both comparisons are strict, **adjacency is legal**: a
    new window whose start instant equals an existing window's end instant does
    not collide."

    Design: Difficulty/resource_temporal_overlap/distribution_half_open_window_collides_but_touching_endpoints_do_not
    """
    env = _env_with_january_to_june_window()
    current_version = get_model_version(env["model_version"]["id"])["version"]

    response = api.create_distribution(
        create_distribution_payload(
            env["sponsor"]["id"],
            env["model_version"]["id"],
            current_version,
            "2026-06-01T00:00:00Z",
        ),
        MANAGER_HEADERS,
    )
    adjacent = validate_success(response, 201)

    assert adjacent["effective_from"].startswith("2026-06-01T00:00:00")
    assert adjacent["effective_until"] is None
    assert adjacent["status"] == "PENDING"
    assert adjacent["sponsor_id"] == env["sponsor"]["id"]
    assert adjacent["model_id"] == env["model"]["id"]

    rows = _distributions_on_key(api, env)
    assert len(rows) == 2, "both the touching windows must coexist on the key"
    assert {row["id"] for row in rows} == {env["distribution"]["id"], adjacent["id"]}


# ---------------------------------------------------------------------------
# Closed wash windows on the account-and-security pair
# ---------------------------------------------------------------------------
def test_buy_block_inside_the_stamped_wash_window_is_refused(api):
    """PRD §2.10: "The **occupation clause** applies when a block is assembled
    for a `BUY`: the block is rejected when a tax lot exists for that account and
    security whose `status` is `CLOSED` and whose `realized_gain_cents` is
    negative, and whose stamped window from `wash_window_start` to
    `wash_window_end` contains the current clock date, again inclusive at both
    ends."

    Design: Difficulty/resource_temporal_overlap/wash_window_closed_interval_blocks_buy_block_until_it_expires
    """
    env = _env_with_stamped_wash_window()

    assert env["harvest"]["realized_loss_cents"] == 200000
    assert env["account"]["realized_loss_ytd_cents"] == 200000
    assert env["account"]["cash_cents"] == 3000000

    closed_lots = list_tax_lots(
        account_id=env["account"]["id"],
        security_id=env["securities"]["ALFA"]["id"],
        status="CLOSED",
    )
    assert len(closed_lots) == 1
    closed_lot = closed_lots[0]
    assert closed_lot["realized_gain_cents"] == -200000
    assert closed_lot["wash_window_start"].startswith("2026-07-02")
    assert closed_lot["wash_window_end"].startswith("2026-08-31")

    response = api.create_block(
        create_block_payload([env["buy_back_order"]["id"]]),
        make_sponsor_operator_headers(env["sponsor"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_WASH_SALE_WINDOW_CONFLICT.value)
    assert get_trade_order(env["buy_back_order"]["id"])["status"] == "PROPOSED"


def test_buy_block_is_accepted_only_once_the_clock_passes_the_closing_endpoint(api):
    """PRD §2.10: "Both endpoints are inside the window, and the time-of-day
    component of every instant involved is discarded before comparison."

    Design: Difficulty/resource_temporal_overlap/wash_window_closed_interval_blocks_buy_block_until_it_expires
    """
    env = _env_with_stamped_wash_window()
    sponsor_headers = make_sponsor_operator_headers(env["sponsor"]["id"])
    order_id = env["buy_back_order"]["id"]

    set_clock("2026-08-31T00:00:00Z")
    on_endpoint = api.create_block(create_block_payload([order_id]), sponsor_headers)
    validate_error(on_endpoint, ApiErrorId.ERR_WASH_SALE_WINDOW_CONFLICT.value)

    set_clock("2026-09-01T00:00:00Z")
    block = validate_success(
        api.create_block(create_block_payload([order_id]), sponsor_headers), 201
    )

    assert block["side"] == "BUY"
    assert block["requested_shares"] == 198
    assert block["order_count"] == 1
    assert block["status"] == "OPEN"
    assert block["filled_shares"] == 0
    assert block["allocated_shares"] == 0
    assert block["unallocated_shares"] == 0

    order = get_trade_order(order_id)
    assert order["status"] == "BLOCKED"
    assert order["block_id"] == block["id"]
    assert order["shares"] == 198
