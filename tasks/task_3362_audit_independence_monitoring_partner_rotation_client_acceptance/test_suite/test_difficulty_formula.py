"""Difficulty claims about the three multi-input formulas.

Each formula has a conditional term, a filtered input set or a pinned
evaluation order; the tests fix the inputs so the output is a single number.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    fixtures,
    get_acceptance_data,
    get_client_data,
    get_engagement_data,
    get_professional_data,
    get_service_data,
    validate_error,
)


class TestClientRiskScoreFormula:
    """Base + conditional surcharge + decayed penalty, then clamped."""

    def test_pie_surcharge_is_worth_fifteen_and_the_clamp_binds(self, api):
        """PRD §3.2: "When the client is a public interest entity, a further
        surcharge of 15 is added to the base."
        PRD §3.2: "The stored `combined_risk_score` is the clamped form — the
        raw score raised to a floor of 0 and lowered to a ceiling of 100."

        Design: Difficulty/combinatorial_formula/risk_score_conditional_pie_surcharge_and_clamp
        """
        world = fixtures.scenario_pie_surcharge_clamp(api)
        acceptance = get_acceptance_data(api, world["pie_acceptance"]["id"])

        # ENERGY 30 + CN 25 + PIE 15 + a 40-point row one month old.
        assert acceptance["risk_score"] == pytest.approx(110.0)
        assert acceptance["combined_risk_score"] == pytest.approx(100.0)

    def test_non_pie_client_lands_below_the_clamp(self, api):
        """PRD §3.2: "The penalty layer mirrors the integrity calculation's
        decay: each contributing assessment adds its `score_impact` multiplied
        by the same three-tier decay factor, and the unclamped `risk_score` is
        the base plus that penalty."

        Design: Difficulty/combinatorial_formula/risk_score_conditional_pie_surcharge_and_clamp
        """
        world = fixtures.scenario_pie_surcharge_clamp(api)
        acceptance = get_acceptance_data(api, world["np_acceptance"]["id"])

        # ENERGY 30 + CN 25 + no surcharge + the same 40-point row.
        assert acceptance["risk_score"] == pytest.approx(95.0)
        assert acceptance["combined_risk_score"] == pytest.approx(95.0)
        assert acceptance["combined_risk_score"] == pytest.approx(
            min(100.0, max(0.0, acceptance["risk_score"]))
        )


class TestNonAuditFeePool:
    """Round each service to whole dollars, then sum."""

    def test_each_service_fee_is_rounded_to_whole_dollars_before_approval(self, api):
        """PRD §3.6: "Each service's rounded fee is its `fee_cents` divided by
        100, rounded half-up to a whole number of dollars, then multiplied back
        by 100 to return to cents".

        Design: Difficulty/combinatorial_formula/naf_pool_rounds_each_service_then_sums
        """
        world = fixtures.scenario_naf_rounding(api)
        for service in (world["first"], world["second"]):
            fixtures.service_transition_ok(
                api, service["id"], "APPROVE", committee_resolution_ref="AC-2026-0417"
            )
            approved = get_service_data(api, service["id"])
            assert approved["status"] == "APPROVED"
            assert approved["approved_fee_cents"] == 100000

    def test_fee_pool_is_the_sum_of_rounded_fees(self, api):
        """PRD §3.6: "the pool is the total of those already-rounded figures
        across all of the client's `APPROVED` services, and only `APPROVED` rows
        count".
        PRD §3.6: "The rounding order is pinned deliberately: rounding each
        service first and then summing produces different cent totals than
        summing raw fees and rounding once".

        Design: Difficulty/combinatorial_formula/naf_pool_rounds_each_service_then_sums
        """
        world = fixtures.scenario_naf_rounding(api)
        fixtures.service_transition_ok(
            api, world["first"]["id"], "APPROVE", committee_resolution_ref="AC-2026-0417"
        )
        fixtures.service_transition_ok(
            api, world["second"]["id"], "APPROVE", committee_resolution_ref="AC-2026-0418"
        )

        client = get_client_data(api, world["client"]["id"])
        assert client["naf_approved_fee_cents"] == 200000
        # Summing the raw cents first would have rounded 200080 up to 200100.
        assert client["naf_approved_fee_cents"] != 200100


class TestWorkloadEvaluationOrder:
    """Base sum first, overload tier from that sum, surcharge added last."""

    def test_base_sum_at_sixty_selects_no_overload_tier(self, api):
        """PRD §3.3: "In the second step, the professional's base sum is the
        total of those step-1 values across all of that professional's `ACTIVE`
        assignments".
        PRD §3.3: "a base sum above 60 adds 5 points and a base sum above 80
        adds 10 points, and a base sum at or below 60 adds nothing".

        Design: Difficulty/combinatorial_formula/workload_base_sum_then_surcharge_tier_selection
        """
        world = fixtures.scenario_workload_ladder(api)
        professional = get_professional_data(api, world["professional"]["id"])

        assert professional["active_workload_points"] == 60
        first = fixtures.get_assignment_data(api, world["first"]["id"])
        second = fixtures.get_assignment_data(api, world["second"]["id"])
        assert first["workload_points"] == 40
        assert second["workload_points"] == 20
        assert first["workload_points"] + second["workload_points"] == 60

    def test_surcharge_tier_is_selected_from_the_base_sum(self, api):
        """PRD §3.3: "In the fourth step, the professional's
        `active_workload_points` is the base sum plus the surcharge".
        PRD §3.3: "Engagement.assigned_workload_points = sum of base(a) over
        ACTIVE assignments a of that engagement" is the step-1 value only.

        Design: Difficulty/combinatorial_formula/workload_base_sum_then_surcharge_tier_selection
        """
        world = fixtures.scenario_workload_ladder(api)
        engagements = world["engagements"]
        professional_id = world["professional"]["id"]
        ep_headers = world["ep_headers"]

        fixtures.staff_ok(
            api, engagements[2]["id"], professional_id, "ENGAGEMENT_MANAGER",
            "2026-02-01T00:00:00Z", "2027-02-01T00:00:00Z", ep_headers=ep_headers,
        )
        after_third = get_professional_data(api, professional_id)
        assert after_third["active_workload_points"] == 80

        fourth = fixtures.staff_ok(
            api, engagements[3]["id"], professional_id, "ENGAGEMENT_MANAGER",
            "2026-02-01T00:00:00Z", "2027-02-01T00:00:00Z", ep_headers=ep_headers,
        )
        after_fourth = get_professional_data(api, professional_id)
        assert after_fourth["active_workload_points"] == 100
        assert after_fourth["active_workload_points"] == after_fourth["max_workload_points"]
        # The surcharge is never written back onto the assignment itself.
        assert fourth["workload_points"] == 15
        engagement = get_engagement_data(api, engagements[3]["id"])
        assert engagement["assigned_workload_points"] == 15

    def test_assignment_over_the_ceiling_is_rejected(self, api):
        """PRD §3.3: "A staffing request that would push the professional's
        active workload points above their personal ceiling is rejected with
        `ERR_WORKLOAD_LIMIT_EXCEEDED` before the assignment is created."

        Design: Difficulty/combinatorial_formula/workload_base_sum_then_surcharge_tier_selection
        """
        world = fixtures.scenario_workload_ladder(api)
        engagements = world["engagements"]
        professional_id = world["professional"]["id"]
        ep_headers = world["ep_headers"]

        for index, role in ((2, "ENGAGEMENT_MANAGER"), (3, "ENGAGEMENT_MANAGER")):
            fixtures.staff_ok(
                api, engagements[index]["id"], professional_id, role,
                "2026-02-01T00:00:00Z", "2027-02-01T00:00:00Z", ep_headers=ep_headers,
            )

        response = fixtures.staff(
            api, engagements[4]["id"], professional_id, "EQ_REVIEWER",
            "2026-02-01T00:00:00Z", "2027-02-01T00:00:00Z", ep_headers=ep_headers,
        )
        validate_error(response, ApiErrorId.ERR_WORKLOAD_LIMIT_EXCEEDED)

        # Nothing was created for the fifth engagement and no ceiling drifted.
        remaining = fixtures.list_assignments_for(api, engagements[4]["id"])
        assert remaining == []
        professional = get_professional_data(api, professional_id)
        assert professional["active_workload_points"] == 100
