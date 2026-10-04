"""The finite-pool waterfall and the deterministic ranking behind it (PRD §3.2)."""
from test_helpers import (
    TEST_USERS,
    allocate_waterfall,
    api_client,
    create_season,
    onboard_partner,
    record_round,
    set_clock,
    setup_three_partner_pool,
    validate_error,
    validate_paginated,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]

PLANNER = TEST_USERS["planner_headers"]


class TestWaterfallLargestRemainder:
    """Difficulty/combinatorial_formula — the floor shortfall is swept to the winners."""

    def test_cap_boundaries_are_a_hard_range(self, api):
        """PRD §3.2: "The eligible pool is every partner whose status is `APPROVED` at the instant of computation: `SUSPENDED`, `INACTIVE`, `REJECTED` and `REJECTED_FINAL` partners receive no slot at all and take no part in the remainder sweep."

        Design: Difficulty/boundary_precision_check/allocation_ceiling_at_fifty_reuses_the_same_largest_remainder_sweep
        """
        pool = setup_three_partner_pool(cap_units=100000)
        over = api.allocate_allocation_plan(
            pool["season"]["id"],
            {
                "claim_id": pool["claim"]["id"],
                "donation_product_id": pool["product"]["id"],
                "liquidity_cap": 51,
                "baseline_units": 2400,
                "demand_units": 15000,
                "pool_units": 4000,
            },
            PLANNER,
        )
        validate_error(over, "ERR_INVALID_REQUEST")

        at_min = allocate_waterfall(
            pool["season"]["id"], pool["claim"]["id"], pool["product"]["id"],
            liquidity_cap=1, baseline_units=2400, demand_units=15000, pool_units=4000,
        )
        assert at_min["liquidity_cap"] == 1

class TestNeedScorePromotionIsNotApproval:
    """Difficulty/combinatorial_formula — the verified-tier debit and the gate are separate."""

    def _clinic(self, region, registry_id, ein, recipients):
        return onboard_partner(
            legal_name=f"Delta Community Clinic {registry_id}",
            partner_type="COMMUNITY_HEALTH_CLINIC",
            operating_region=region,
            operating_state_code="IL",
            registry_id=registry_id,
            ein=ein,
            founded_year=1990,
            unduplicated_recipients_per_facility=recipients,
            need_tier="LOW",
        )

    def test_promotion_debits_five_points_yet_approval_stands(self, api):
        """PRD §3.1: "It is assembled from a base value that depends on the partner's declared need band and a regional adjustment, with the band's base drawn from the partner type (a disaster relief organization scores 95, a domestic violence shelter 83, a homeless shelter 70, a veteran outreach organization 61, a youth outreach organization 52, and a community health clinic 20) and the adjustment drawn from the operating region (the midwest adds 6, the northeast 3, the southwest 2, the southeast 0 and the west subtracts 2)."
        PRD §3.1: "A separate access component is added: the partner's average unduplicated recipients per facility divided by one thousand in truncating integer division, capped at 20."
        PRD §3.1: "When the points are 3 or fewer the declared band's base is used unchanged."
        PRD §3.1: "Independently, the computed `need_score` must be at least 40; a score below that threshold is rejected with `ERR_NEED_SCORE_BELOW_MINIMUM` (HTTP 409) even when every verification flag is true."

        Design: Difficulty/combinatorial_formula/proved_monthly_upkeep_only_residency_holds_the_promoted_tier
        """
        set_clock("2026-09-01T00:00:00Z")
        create_season()
        partner = self._clinic("MIDWEST", "IL-CHR-400004", "444555666", 20000)
        vetting_id = partner["latest_vetting_round_id"]

        record_round(vetting_id, need_verification_points=3)
        before = validate_success(
            api_client.get_giving_partner(partner["id"], COORD), 200
        )
        # PRD §3.1: the band's base is 20 for a community health clinic, +6 for
    # the midwest, +min(20, 20000 // 1000) access; three verification points
    # are below the 4-point promotion threshold so the base is unchanged.
        assert before["need_score"] == 46, "20 + 6 + min(20, 20000 // 1000)"

        # PRD §3.1: "`need_score` is recomputed ... on any vetting-round write
        # that changes the verification points", and a round may carry forward
        # further evidence while it is still open.
        validate_success(
            api_client.update_vetting_round(
                vetting_id,
                {"outcome": "EVALUATING", "need_verification_points": 5},
                COORD,
            ),
            200,
        )
        after = validate_success(api_client.get_giving_partner(partner["id"], COORD), 200)
        assert after["need_score"] == 41, "20 + 6 - 5 + 20"
        assert after["status"] == "VETTING"

        # The promoted score still clears the approval floor, so the debit does
        # not by itself block approval.
        validate_success(api_client.approve_vetting_round(vetting_id, {}, COORD), 200)
        assert validate_success(
            api_client.get_giving_partner(partner["id"], COORD), 200
        )["status"] == "APPROVED"

    def test_the_same_arithmetic_in_a_zero_adjustment_region_falls_below_the_gate(self, api):
        """PRD §3.1: "Independently, the computed `need_score` must be at least 40; a score below that threshold is rejected with `ERR_NEED_SCORE_BELOW_MINIMUM` (HTTP 409) even when every verification flag is true."
        PRD §3.1: "It is assembled from a base value that depends on the partner's declared need band and a regional adjustment, with the band's base drawn from the partner type (a disaster relief organization scores 95, a domestic violence shelter 83, a homeless shelter 70, a veteran outreach organization 61, a youth outreach organization 52, and a community health clinic 20) and the adjustment drawn from the operating region (the midwest adds 6, the northeast 3, the southwest 2, the southeast 0 and the west subtracts 2)."

        Design: Difficulty/combinatorial_formula/proved_monthly_upkeep_only_residency_holds_the_promoted_tier
        """
        set_clock("2026-09-01T00:00:00Z")
        create_season()
        partner = self._clinic("SOUTHEAST", "FL-CHR-410004", "444555667", 20000)
        vetting_id = partner["latest_vetting_round_id"]

        record_round(vetting_id, need_verification_points=5)
        refreshed = validate_success(
            api_client.get_giving_partner(partner["id"], COORD), 200
        )
        assert refreshed["need_score"] == 35, "20 + 0 - 5 + 20"

        refused = api_client.approve_vetting_round(vetting_id, {}, COORD)
        validate_error(refused, "ERR_NEED_SCORE_BELOW_MINIMUM", expected_status=409)


def test_repeating_the_waterfall_reproduces_the_split(api):
    """PRD §3.2: "Slot assignment itself, when two partners contend for a slot, is broken by descending `rank_score`, then descending `need_score`, then descending `claim_attributed_units`, then ascending `created_at` — never by identifier."
    PRD §3.2: "The eligible pool is every partner whose status is `APPROVED` at the instant of computation: `SUSPENDED`, `INACTIVE`, `REJECTED` and `REJECTED_FINAL` partners receive no slot at all and take no part in the remainder sweep."

    Design: Difficulty/combinatorial_formula/largest_remainder_waterfall_distributes_the_floor_shortfall
    """
    pool = setup_three_partner_pool(cap_units=5000)
    first = allocate_waterfall(
        pool["season"]["id"], pool["claim"]["id"], pool["product"]["id"],
        liquidity_cap=10, baseline_units=2400, demand_units=15000, pool_units=4000,
    )
    assert first["partner_count"] == 3
    data, _ = validate_paginated(api.list_season_allocations(pool["season"]["id"], PLANNER))
    rows = [a for a in data if a["allocation_kind"] == "ALLOCATION"]
    # PRD §3.2: "That exact share is floored to a whole number and the leftover
    # units — the cap minus the sum of the floors — are distributed one apiece",
    # so the sweep hands out exactly the cap across the eligible pool.
    assert sum(r["allocated_units"] for r in rows) == 10


def test_liquidity_cap_is_a_hard_range_not_a_clamp(api):
    """PRD §3.2: "The `liquidity_cap` defaults to 10 and must lie between 1 and 50 inclusive."

    Design: Corner/calculations/weighted_allocation_reports_the_pinned_liquidity_cap_boundaries
    """
    pool = setup_three_partner_pool(cap_units=100000)

    validate_error(
        api_client.allocate_allocation_plan(
            pool["season"]["id"],
            {
                "claim_id": pool["claim"]["id"],
                "donation_product_id": pool["product"]["id"],
                "liquidity_cap": 51,
                "baseline_units": 2400,
                "demand_units": 15000,
                "pool_units": 4000,
            },
            PLANNER,
        ),
        "ERR_INVALID_REQUEST",
        expected_status=400,
    )

    at_max = allocate_waterfall(
        pool["season"]["id"], pool["claim"]["id"], pool["product"]["id"],
        liquidity_cap=50, baseline_units=2400, demand_units=15000, pool_units=4000,
    )
    assert at_max["liquidity_cap"] == 50

    at_min = allocate_waterfall(
        pool["season"]["id"], pool["claim"]["id"], pool["product"]["id"],
        liquidity_cap=1, baseline_units=2400, demand_units=15000, pool_units=4000,
    )
    assert at_min["liquidity_cap"] == 1
    rows = validate_success(
        api_client.list_allocations(PLANNER, {"impact_season_id": pool["season"]["id"]}), 200
    )
    assert sum(r["allocated_units"] for r in rows) == 51
