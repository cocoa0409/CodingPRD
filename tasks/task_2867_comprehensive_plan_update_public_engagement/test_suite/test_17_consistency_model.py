"""Immediate visibility of every derived field the write touched.

The expensive writes here are scenario creation, which computes capacity and demand
onto the scenario's own row, and scenario adoption, which recomputes the four
income-tier housing allocations and the plan's own capacity fields. Every test
below reads those results at the earliest moment the API allows and then re-reads
them, so an implementation that fills a derived field on access rather than inside
the writing request fails.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions as a
from test_helpers import constants as C
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import DIRECTOR, STAFF

# The reference acreage row of PRD section 3.2 — 400 vacant, 250 underutilized,
# 60 infrastructure-constrained, 18 allowed units per acre — read under the POLICY
# method, which selects the NET_CAPACITY variant and a pool of 7115 units.
REF_VACANT = 400
REF_UNDERUTILIZED = 250
REF_CONSTRAINED = 60
REF_DENSITY = 18
POLICY_POOL = 7115

# The four state-assigned tiers. 900 / 700 / 800 are absorbed in full; the top tier
# is deliberately far larger than the pool can reach, so the whole plan-wide
# shortfall lands on ABOVE_MODERATE alone.
ASSIGNED = {
    C.TIER_VERY_LOW: 900,
    C.TIER_LOW: 700,
    C.TIER_MODERATE: 800,
    C.TIER_ABOVE_MODERATE: 9000,
}

SCENARIO_DRIVERS = {
    "label": "Policy 2045",
    "base_households": 20000,
    "annual_household_growth_rate": 0.012,
    "job_growth_total": 15000,
    "demolition_replacement_units": 500,
}


def _expected_demand() -> int:
    return a.expected_projected_demand(
        C.METHOD_POLICY,
        SCENARIO_DRIVERS["base_households"],
        SCENARIO_DRIVERS["annual_household_growth_rate"],
        f.REF_HORIZON_YEAR,
        f.REF_BASE_YEAR,
        SCENARIO_DRIVERS["job_growth_total"],
        SCENARIO_DRIVERS["demolition_replacement_units"],
    )


def _plan_with_allocations_before_any_scenario(api) -> dict:
    """Plan, four certified inventories and all four allocation rows — no scenario.

    The allocations are recorded while the plan still has no adopted projection, so
    their waterfall figures can only be filled in by the adoption that follows.
    """
    plan = fx.create_plan(api, title="Horizon 2045 General Plan")
    inventories = fx.certified_inventory_set(api, plan["id"])
    allocations = fx.create_all_allocations(api, plan["id"], ASSIGNED)
    return {
        "plan_id": plan["id"],
        "land_use_inventory_id": inventories[C.INVENTORY_LAND_USE]["id"],
        "allocations": allocations,
    }


def test_scenario_creation_response_already_carries_its_capacity_and_demand(api):
    """Capacity, variant, demand and gap are all present in the POST response itself,
    and an immediate re-read of the same scenario repeats them unchanged.

    PRD section 1: "by the time a mutating request returns, every derived counter,
    every cascaded child state and every recomputed gate on the plan already reflects
    the write."

    Design: Corner/consistency_model/every_derived_field_is_readable_in_the_same_response
    """
    plan = fx.create_plan(api, title="Horizon 2045 General Plan")
    inventories = fx.certified_inventory_set(api, plan["id"])
    land_use = get_success_data(
        api.get_inventory_dataset(inventories[C.INVENTORY_LAND_USE]["id"], STAFF)
    )

    created = validate_success(
        api.create_growth_scenario(
            f.growth_scenario_payload(
                plan["id"],
                land_use["id"],
                land_use["version"],
                method=C.METHOD_POLICY,
                **SCENARIO_DRIVERS,
            ),
            STAFF,
        ),
        201,
    )

    expected_demand = _expected_demand()
    assert created["capacity_variant"] == C.CAPACITY_VARIANT_NET
    assert created["land_capacity_units"] == POLICY_POOL
    assert created["land_capacity_units"] == a.expected_net_capacity(
        REF_VACANT, REF_UNDERUTILIZED, REF_CONSTRAINED, REF_DENSITY
    )
    assert created["projected_demand_units"] == expected_demand
    assert created["capacity_gap_units"] == a.expected_capacity_gap(
        expected_demand, POLICY_POOL
    )
    assert created["status"] == C.SCENARIO_STATUS_DRAFT

    # The very next read of the same row must not "settle" on different figures.
    reread = get_success_data(api.get_growth_scenario(created["id"], STAFF))
    a.assert_fields_equal(
        reread,
        {
            "capacity_variant": created["capacity_variant"],
            "land_capacity_units": created["land_capacity_units"],
            "projected_demand_units": created["projected_demand_units"],
            "capacity_gap_units": created["capacity_gap_units"],
            "version": created["version"],
        },
    )


def test_adoption_publishes_the_recomputed_tier_row_and_summary_in_one_step(api):
    """Adopting the projection recomputes the allocation rows and the plan's own
    capacity dashboard before it returns: the first read of the shorted tier and the
    first read of the compliance summary both already show the post-adoption figures.

    PRD section 3.2: "all four of the plan's income-tier housing allocations are
    recomputed by the capacity waterfall of section 3.3; the plan's
    `housing_shortfall_total` is refreshed to the sum of the tiers' shortfalls".

    Design: Corner/consistency_model/every_derived_field_is_readable_in_the_same_response
    """
    ctx = _plan_with_allocations_before_any_scenario(api)
    plan_id = ctx["plan_id"]

    # "when the plan has no adopted scenario yet, the pool is zero, and consequently
    # every tier is fully short" — 900 + 700 + 800 + 9000 units of shortfall.
    before = fx.read_summary(api, plan_id)
    assert before["housing_shortfall_total"] == a.expected_shortfall_total(0, ASSIGNED)
    assert before["housing_shortfall_total"] == 11400
    assert before["compliance_posture"] == C.POSTURE_CAPACITY_HOLD

    scenario = fx.create_scenario(
        api,
        plan_id,
        ctx["land_use_inventory_id"],
        method=C.METHOD_POLICY,
        **SCENARIO_DRIVERS,
    )
    adopted = validate_success(api.adopt_growth_scenario(scenario["id"], {}, DIRECTOR))
    assert adopted["status"] == C.SCENARIO_STATUS_ADOPTED

    expected_rows = a.expected_waterfall(POLICY_POOL, ASSIGNED)
    top = expected_rows[C.TIER_ABOVE_MODERATE]
    rows, meta = validate_paginated(
        api.list_plan_housing_allocations(
            plan_id, DIRECTOR, params={"income_tier": C.TIER_ABOVE_MODERATE}
        )
    )
    assert meta["total_count"] == 1
    a.assert_fields_equal(
        rows[0],
        {
            "income_tier": C.TIER_ABOVE_MODERATE,
            "assigned_units": ASSIGNED[C.TIER_ABOVE_MODERATE],
            "tier_capacity_units": 2135,
            "carryover_in_units": 2581,
            "accommodated_units": 4716,
            "shortfall_units": 4284,
        },
    )
    a.assert_fields_equal(rows[0], top)

    after = fx.read_summary(api, plan_id)
    assert after["housing_shortfall_total"] == top["shortfall_units"]
    assert after["housing_shortfall_total"] == 4284
    assert after["land_capacity_units"] == POLICY_POOL
    assert after["projected_demand_units"] == _expected_demand()
    assert after["capacity_gap_units"] == a.expected_capacity_gap(
        _expected_demand(), POLICY_POOL
    )
    assert after["compliance_posture"] == C.POSTURE_CAPACITY_HOLD


SUMMARY_FIELDS = (
    "plan_update_id",
    "compliance_posture",
    "state_review_status",
    "required_elements_complete_count",
    "missing_element_types",
    "open_consistency_link_count",
    "housing_shortfall_total",
    "equity_share_pct",
    "land_capacity_units",
    "projected_demand_units",
    "capacity_gap_units",
    "monitoring_on_track_count",
)


def test_repeated_reads_and_the_plan_row_agree_with_the_tier_rows(api):
    """Reading the dashboard twice returns the same figures, the unfiltered allocation
    list reports the same four tier results, and the plan row's own denormalised
    shortfall total and projection pointer already agree with them.

    PRD section 3.3: "The plan's `housing_shortfall_total` is then the sum of
    `shortfall_units` across the four tiers, counting zero for any tier that has no
    row."

    Design: Corner/consistency_model/every_derived_field_is_readable_in_the_same_response
    """
    ctx = _plan_with_allocations_before_any_scenario(api)
    plan_id = ctx["plan_id"]
    scenario = fx.create_scenario(
        api,
        plan_id,
        ctx["land_use_inventory_id"],
        method=C.METHOD_POLICY,
        **SCENARIO_DRIVERS,
    )
    fx.adopt_scenario(api, scenario["id"])

    first = fx.read_summary(api, plan_id)
    second = fx.read_summary(api, plan_id)
    for field in SUMMARY_FIELDS:
        assert field in first, f"the computed read must report {field!r}"
        assert second[field] == first[field], (
            f"{field} changed between two identical reads: "
            f"{first[field]!r} then {second[field]!r}"
        )

    rows, meta = validate_paginated(api.list_plan_housing_allocations(plan_id, STAFF))
    assert meta["total_count"] == len(C.TIER_ORDER)
    assert [row["income_tier"] for row in rows] == C.TIER_ORDER
    assert [row["shortfall_units"] for row in rows] == [0, 0, 0, 4284]
    expected_rows = a.expected_waterfall(POLICY_POOL, ASSIGNED)
    for row in rows:
        a.assert_fields_equal(row, expected_rows[row["income_tier"]])
    assert sum(row["shortfall_units"] for row in rows) == first["housing_shortfall_total"]

    plan = fx.read_plan(api, plan_id)
    assert plan["housing_shortfall_total"] == 4284
    assert plan["adopted_scenario_id"] == scenario["id"]
    assert plan["housing_shortfall_total"] == first["housing_shortfall_total"]
    assert plan["compliance_posture"] == first["compliance_posture"]
    a.assert_posture_consistent(plan)
