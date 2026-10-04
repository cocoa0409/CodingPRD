"""Combinatorial calculations: clean-room query costing and activation fees.

Query cost combines row units, join breadth, and tier multiplier with a single
ceiling at the end; activation fees pin a round-per-line-then-sum order.
"""

import pytest

from test_helpers import (
    account_with_contract,
    create_approved_grant,
    create_approved_segment,
    get_success_data,
    ingest_category_households,
    make_data_steward_headers,
    make_supplier_analyst_headers,
    read_grant,
)
from test_helpers import factories
from test_helpers.test_users import TEST_USERS

STEWARD = TEST_USERS["data_steward_headers"]


def _query_cost_scenario(api):
    """TIER_BRAND contract + APPROVED grant with query_budget_total 200."""
    world = account_with_contract(api, name="Beta Brands", tier="TIER_BRAND")
    grant = create_approved_grant(api, world["account"]["id"], steward_user_id="steward-q1",
                                  query_budget_total=200)
    return world, grant


def test_query_cost_combines_rows_joins_and_tier(api):
    """5200 rows, three joined datasets, TIER_BRAND: 6 * 1.5 * 1.25 = 11.25 -> ceil 12.

    PRD: "The raw cost is the product of row units, join factor, and tier multiplier; the final `query_cost` is that product rounded up to a whole credit — the ceiling is applied once, after the full multiplication — then clamped to a minimum of one credit and a maximum of one hundred credits."
    Design: Difficulty/combinatorial_formula/query_cost_nonlinear_three_input
    """
    world, grant = _query_cost_scenario(api)
    resp = api.submit_query(
        grant["id"],
        factories.query_payload(dataset_joins=["SALES", "PROMOS", "DEMOGRAPHICS"], estimated_rows=5200),
        world["analyst_headers"],
    )
    query = get_success_data(resp)
    assert query["query_cost"] == 12
    assert query["status"] == "EXECUTED"
    assert query["result_rows"] == 5200


def test_query_budget_debits_by_computed_cost(api):
    """The executed query's cost moves the grant budget from 200 to consumed 12 / remaining 188.

    PRD: "The `query_cost` must not exceed `query_budget_remaining` (else `ERR_INSUFFICIENT_QUERY_BUDGET`)."
    PRD: "if `result_rows` is at least twenty, the query lands in `EXECUTED`, the grant's `query_budget_consumed` increases by `query_cost`, and a `QUERY_EXECUTED` audit event is written."
    Design: Difficulty/combinatorial_formula/query_cost_nonlinear_three_input
    """
    world, grant = _query_cost_scenario(api)
    get_success_data(api.submit_query(
        grant["id"],
        factories.query_payload(dataset_joins=["SALES", "PROMOS", "DEMOGRAPHICS"], estimated_rows=5200),
        world["analyst_headers"],
    ))
    observed = read_grant(api, grant["id"])
    assert observed["query_budget_consumed"] == 12
    assert observed["query_budget_remaining"] == 188


def _activation_scenario(api, household_count=37):
    """APPROVED segment of exactly ``household_count`` SNACKS households."""
    world = account_with_contract(
        api, name="Gamma Goods", tier="TIER_PORTFOLIO", scope_category="SNACKS", scope_brands=["ACME"]
    )
    ingest_category_households(api, household_count, "h")
    segment = create_approved_segment(api, world["contract"]["id"], world["analyst_headers"])
    assert segment["size"] == household_count, f"Setup failed: size {segment['size']} != {household_count}"
    return world, segment


def test_activation_fees_round_per_line_then_sum(api):
    """Size 37 on [COUPON, RETAIL_MEDIA]: 73 + 59 = 132, not the forbidden sum-then-round 131.

    PRD: "The rounding order is pinned: each line fee is rounded first, and `total_fee_cents` is the integer sum of the rounded line fees."
    PRD: "concretely, a size-37 segment activated on both channels yields line fees of 73 cents and 59 cents for a total of 132 cents, even though the raw sum is exactly 131.0 cents."
    Design: Difficulty/combinatorial_formula/activation_fee_per_line_then_sum_rounding
    """
    world, segment = _activation_scenario(api)
    resp = api.create_activation(
        segment["id"],
        factories.activation_payload(segment["version"], channels=["COUPON", "RETAIL_MEDIA"]),
        world["analyst_headers"],
    )
    activation = get_success_data(resp)
    lines = activation["channel_lines"]
    assert lines[0]["channel"] == "COUPON"
    assert lines[0]["households_reached"] == 29
    assert lines[0]["line_fee_cents"] == 73
    assert lines[1]["channel"] == "RETAIL_MEDIA"
    assert lines[1]["households_reached"] == 18
    assert lines[1]["line_fee_cents"] == 59
    assert activation["total_fee_cents"] == 132


def test_activation_fee_debits_contract_activation_budget(api):
    """Creating the activation adds the 132-cent total to the contract's spent counter.

    PRD: "Creating the activation debits the sponsoring contract: `activation_budget_spent_cents` increases by `total_fee_cents`"
    PRD: "`activation_budget_spent_cents` accumulates the `total_fee_cents` of every activation under the contract that is not `CANCELLED`"
    Design: Difficulty/combinatorial_formula/activation_fee_per_line_then_sum_rounding
    """
    from test_helpers import read_contract

    world, segment = _activation_scenario(api)
    get_success_data(api.create_activation(
        segment["id"],
        factories.activation_payload(segment["version"], channels=["COUPON", "RETAIL_MEDIA"]),
        world["analyst_headers"],
    ))
    contract = read_contract(api, world["contract"]["id"])
    assert contract["activation_budget_spent_cents"] == 132
