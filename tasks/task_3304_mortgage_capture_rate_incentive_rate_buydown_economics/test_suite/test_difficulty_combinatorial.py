"""The incentive waterfall: a pinned priority order with downstream spill."""

from prd_bench_local_runner.testing import get_success_data

from test_helpers import factories as f
from test_helpers import fixtures
from test_helpers import ADMIN_HEADERS, SALES_HEADERS


def standard_world(api):
    """Clock at the startup default and a community under the standard caps."""
    fixtures.set_clock(api, fixtures.BASE_CLOCK)
    community = fixtures.create_community(api)
    buyer = fixtures.create_buyer(api)
    site = fixtures.create_home_site(api, community["id"])
    contract = fixtures.create_contract(api, site["id"], buyer["id"])
    return {
        "cm1": community["id"],
        "b1": buyer["id"],
        "hs1": site["id"],
        "ct1": contract["id"],
        "ct1_v": contract["version"],
        "contract": contract,
    }


def test_allocation_spills_its_overflow_into_the_next_priority_bucket(api):
    """A request over the price-reduction cap spills the excess into closing costs.

    PRD §3.7: "The waterfall fills the buckets in a fixed priority order:
    `PRICE_REDUCTION` first, then `CLOSING_COSTS`, then `RATE_BUYDOWN`."
    PRD §3.7: "The requested amount is first drawn from the target bucket up to its
    remaining cap."
    PRD §3.7: "The first bucket that absorbs any overflow is recorded in the
    `spill_to_bucket` field, and the total granted across the target bucket and its
    downstream spill becomes `allocation_total_cents`."
    Design: Difficulty/combinatorial_formula/allocation_waterfall_circular_spill_mode_c
    """
    world = standard_world(api)

    allocation = get_success_data(
        api.create_incentive_allocation(
            world["ct1"],
            f.incentive_allocation_payload("PRICE_REDUCTION", 3_500_000, world["ct1_v"]),
            SALES_HEADERS,
        )
    )
    assert allocation["allocation_status"] == "RESERVED", allocation["allocation_status"]
    assert allocation["allocation_total_cents"] == 3_500_000, (
        f"3_000_000 from the target cap plus 500_000 spilled, got "
        f"{allocation['allocation_total_cents']}"
    )
    assert allocation["spill_to_bucket"] == "CLOSING_COSTS", (
        f"overflow moves only down the order, got {allocation['spill_to_bucket']}"
    )


def test_second_allocation_sees_the_cap_the_first_allocation_already_consumed(api):
    """The closing-cost cap is already reduced by the earlier spill, so 2_500_000 is granted.

    PRD §3.7: "It computes each bucket's remaining cap as the policy cap for that
    bucket minus the total already granted to that bucket by allocations sitting in
    `RESERVED` or `APPLIED` status; allocations in `PENDING` or `REVERSED` status
    consume nothing."
    PRD §3.7: "Any amount the target bucket cannot absorb becomes overflow, and
    overflow moves only *down* the priority order — it is offered to each later
    bucket in turn, each taking as much as its remaining cap allows, until the
    overflow is exhausted or the last bucket is reached."
    Design: Difficulty/combinatorial_formula/allocation_waterfall_circular_spill_mode_c
    """
    world = standard_world(api)

    first = get_success_data(
        api.create_incentive_allocation(
            world["ct1"],
            f.incentive_allocation_payload("PRICE_REDUCTION", 3_500_000, world["ct1_v"]),
            SALES_HEADERS,
        )
    )
    assert first["allocation_total_cents"] == 3_500_000, first["allocation_total_cents"]

    refreshed = fixtures.read_contract(api, world["ct1"])
    second = get_success_data(
        api.create_incentive_allocation(
            world["ct1"],
            f.incentive_allocation_payload(
                "CLOSING_COSTS", 2_500_000, refreshed["version"]
            ),
            SALES_HEADERS,
        )
    )

    assert second["allocation_total_cents"] == 2_500_000, (
        "1_500_000 remained in the closing-cost cap after the first spill and the "
        f"other 1_000_000 spilled onward, giving 2_500_000, not "
        f"{second['allocation_total_cents']}"
    )
    assert second["spill_to_bucket"] == "RATE_BUYDOWN", (
        f"the remaining overflow lands in the last bucket, got {second['spill_to_bucket']}"
    )

    read_back = fixtures.read_allocation(api, second["id"])
    assert read_back["allocation_total_cents"] == 2_500_000, (
        "the granted total is persisted on the row, not merely echoed"
    )


def test_contract_allocation_total_accumulates_the_granted_amounts_across_buckets(api):
    """Two requests under the standard caps leave the contract at 6_000_000 allocated.

    PRD §3.7: "Creating an allocation opens it in `RESERVED` status and immediately
    recomputes the contract's `incentive_allocated_cents` as the sum of
    `allocation_total_cents` over its `APPLIED` allocations."
    PRD §3.7: "overflow moves only *down* the priority order — it is offered to each
    later bucket in turn, each taking as much as its remaining cap allows, until the
    overflow is exhausted or the last bucket is reached."
    Design: Difficulty/combinatorial_formula/allocation_waterfall_circular_spill_mode_c
    """
    world = standard_world(api)

    first = get_success_data(
        api.create_incentive_allocation(
            world["ct1"],
            f.incentive_allocation_payload("PRICE_REDUCTION", 3_500_000, world["ct1_v"]),
            SALES_HEADERS,
        )
    )
    refreshed = fixtures.read_contract(api, world["ct1"])
    second = get_success_data(
        api.create_incentive_allocation(
            world["ct1"],
            f.incentive_allocation_payload(
                "CLOSING_COSTS", 2_500_000, refreshed["version"]
            ),
            SALES_HEADERS,
        )
    )

    granted = {first["id"]: first["allocation_total_cents"],
               second["id"]: second["allocation_total_cents"]}
    assert granted[second["id"]] == 2_500_000, granted[second["id"]]

    contract = fixtures.read_contract(api, world["ct1"])
    assert contract["version"] == refreshed["version"] + 1, (
        "each allocation write bumps the contract's version by one"
    )
    total = first["allocation_total_cents"] + second["allocation_total_cents"]
    assert total == 6_000_000, (
        f"the two granted amounts sum to the whole standard budget, got {total}"
    )