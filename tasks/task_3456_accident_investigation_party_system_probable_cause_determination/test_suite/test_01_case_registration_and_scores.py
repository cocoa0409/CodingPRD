"""Accident notification registration and launch-score computation (PRD §3.1).

Covers the create envelope, required-field rejection, and the dual score
variants: the flat statutory sum (gating) and the per-component-rounded
weighted risk score (observability only).
"""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_accident_case,
    assert_case_scores,
    create_case,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

DUTY_OFFICER = TEST_USERS["duty_officer_headers"]


class TestCaseRegistration:
    def test_case_create_returns_every_declared_field_with_computed_scores(self, api):
        """PRD §3.1: "The new case opens in `SCREENING` status, and the server
        immediately computes its two launch scores and its `suggested_mode`."
        PRD §2.2: "The `api_request_id` is a server-generated unique identifier
        for the request that starts with `req_`."

        Design: Corner/entities/case_create_returns_every_declared_field_with_computed_scores
        """
        set_clock()
        resp = api.create_accident_case(
            {
                "report_number": "NTSB-2026-0001",
                "category": "HIGHWAY",
                "occurred_at": "2026-08-31T14:22:00Z",
                "location_state": "VA",
                "fatalities_count": 1,
                "injuries_count": 0,
                "damage_estimate_cents": 0,
                "is_public_transport": True,
            },
            DUTY_OFFICER,
        )
        assert resp.status_code == 201, f"create must return 201, got {resp.status_code}"
        body = resp.json()
        assert body["response_type"] == "object"
        assert body["meta"]["api_request_id"].startswith("req_")
        assert body["meta"]["api_request_timestamp"]

        case = validate_success(resp, expected_status=201)
        assert_accident_case(case)
        assert case["status"] == "SCREENING"
        assert case["version"] == 1
        # 40 (one fatality) + 0 + 0 + 20 (public conveyance) = 60 statutory;
        # 40.0 + 0.0 + 0.0 + round_half_up(20 * 0.5) = 50.0 risk-adjusted.
        assert case["statutory_score"] == 60
        assert case["risk_adjusted_score"] == pytest.approx(50.0, abs=1e-6)
        assert case["suggested_mode"] == "FULL_GO_TEAM"
        assert case["launch_decisions"] == []
        assert_case_scores(case)

    def test_case_create_missing_required_fatalities_returns_invalid_request(self, api):
        """PRD §3.1: registration supplies "the reported `fatalities_count`,
        `injuries_count`, and `damage_estimate_cents` (all three non-negative
        integers)". PRD §2.8: "a request that is malformed — a required field
        missing, an enum value outside its declared set, a conditional-field
        rule violated, or a numeric range violated — is rejected with
        `ERR_INVALID_REQUEST`."

        Design: Corner/entities/case_create_missing_required_fatalities_returns_invalid_request
        """
        set_clock()
        resp = api.create_accident_case(
            {
                "report_number": "NTSB-2026-0002",
                "category": "RAIL",
                "occurred_at": "2026-08-30T09:00:00Z",
                "location_state": "PA",
                "injuries_count": 2,
                "damage_estimate_cents": 500000,
                "is_public_transport": True,
            },
            DUTY_OFFICER,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        rows, meta = validate_paginated(api.list_accident_cases(DUTY_OFFICER))
        assert rows == [], "no case row may be persisted after a rejected create"


class TestLaunchScoreVariants:
    def test_dual_variant_launch_scores_diverge_on_hazmat_case(self, api):
        """PRD §3.1: "Each unrounded component is multiplied by a weight —
        fatalities by 1.0, injuries by 1.25, public interest by 0.5, and damage
        by a category multiplier that is 1.0 for aviation, rail, and highway,
        1.25 for marine, 1.5 for pipeline, and 2.0 for hazmat — then each
        weighted component is rounded half-up to one decimal place, the rounded
        components are summed, and the total is clamped between 0 and 100."
        PRD §3.1: "It is observability-only: it never gates any adoption
        decision."

        Design: Difficulty/dual_variant_calc/dual_variant_launch_scores_diverge_on_hazmat_case
        """
        set_clock()
        case = create_case(
            report_number="NTSB-2026-0101",
            category="HAZMAT",
            occurred_at="2026-08-30T04:12:00Z",
            location_state="LA",
            fatalities_count=2,
            injuries_count=3,
            damage_estimate_cents=5000000,
            is_public_transport=False,
        )
        assert_accident_case(case)
        # Statutory: 40 (fatalities) + 15 (damage tier mid) + 3 (injuries) + 0.
        assert case["statutory_score"] == 58
        # Risk: 40.0 + round1(15 * 2.0)=30.0 + round1(3 * 1.25)=3.8 + 0.0.
        assert case["risk_adjusted_score"] == pytest.approx(73.8, abs=1e-6)
        # Statutory 58 < 60 -> LIMITED even though risk-adjusted 73.8 >= 60;
        # the suggestion follows the statutory variant alone.
        assert case["suggested_mode"] == "LIMITED"
        assert_case_scores(case)

    def test_combinatorial_statutory_score_clamp_and_modal_bump(self, api):
        """PRD §3.1: "Public interest adds 20 points when a public-conveyance
        operation was involved, plus 10 more when the category is aviation or
        rail. The sum is clamped between 0 and 100 and stored as
        `statutory_score`."

        Design: Difficulty/combinatorial_formula/combinatorial_statutory_score_clamp_and_modal_bump
        """
        set_clock()
        case = create_case(
            report_number="NTSB-2026-0102",
            category="AVIATION",
            occurred_at="2026-08-29T19:40:00Z",
            location_state="AK",
            fatalities_count=5,
            injuries_count=15,
            damage_estimate_cents=10000000,
            is_public_transport=True,
        )
        assert_accident_case(case)
        # 55 (40 + 15 catastrophic bonus) + 25 (damage high tier) + min(15, 10)
        # + 30 (20 public + 10 modal bump) = 120, clamped at the 100 ceiling.
        assert case["statutory_score"] == 100
        # 55.0 + 25.0 + 12.5 + 15.0 = 107.5, clamped at 100.
        assert case["risk_adjusted_score"] == pytest.approx(100.0, abs=1e-6)
        assert case["suggested_mode"] == "FULL_GO_TEAM"
        assert_case_scores(case)

    def test_risk_adjusted_per_component_rounding_order_on_marine_case(self, api):
        """PRD §3.1: "then each weighted component is rounded half-up to one
        decimal place, the rounded components are summed, and the total is
        clamped between 0 and 100" — the rounding-before-summing order is
        pinned (PRD §2.9: "the rounding-before-summing order is pinned, so
        identical inputs generally yield two different numbers").

        Design: Difficulty/combinatorial_formula/combinatorial_risk_adjusted_per_component_rounding_order
        """
        set_clock()
        case = create_case(
            report_number="NTSB-2026-0103",
            category="MARINE",
            occurred_at="2026-08-28T02:05:00Z",
            location_state="WA",
            fatalities_count=1,
            injuries_count=3,
            damage_estimate_cents=5000000,
            is_public_transport=False,
        )
        assert_accident_case(case)
        assert case["statutory_score"] == 58
        # round1(40 * 1.0)=40.0 + round1(15 * 1.25)=18.8 + round1(3 * 1.25)=3.8
        # + round1(0 * 0.5)=0.0 = 62.6; sum-then-round would give 62.5.
        assert case["risk_adjusted_score"] == pytest.approx(62.6, abs=1e-6)
        assert abs(case["risk_adjusted_score"] - 62.5) > 0.05, (
            "the forbidden sum-then-round order yields 62.5 and must be excluded"
        )
        assert_case_scores(case)

    def test_risk_adjusted_damage_multiplier_varies_by_category(self, api):
        """PRD §3.1: "damage by a category multiplier that is 1.0 for aviation,
        rail, and highway, 1.25 for marine, 1.5 for pipeline, and 2.0 for
        hazmat".

        Design: Difficulty/combinatorial_formula/combinatorial_risk_adjusted_per_component_rounding_order
        """
        set_clock()
        highway = create_case(
            report_number="NTSB-2026-0107",
            category="HIGHWAY",
            occurred_at="2026-08-28T02:05:00Z",
            location_state="WA",
            fatalities_count=1,
            injuries_count=3,
            damage_estimate_cents=5000000,
            is_public_transport=False,
        )
        assert highway["statutory_score"] == 58
        # Identical severities to the marine case, but the 1.0 multiplier:
        # 40.0 + round1(15 * 1.0)=15.0 + 3.8 + 0.0 = 58.8.
        assert highway["risk_adjusted_score"] == pytest.approx(58.8, abs=1e-6)
        pipeline = create_case(
            report_number="NTSB-2026-0108",
            category="PIPELINE",
            occurred_at="2026-08-28T02:05:00Z",
            location_state="WA",
            fatalities_count=1,
            injuries_count=3,
            damage_estimate_cents=5000000,
            is_public_transport=False,
        )
        # 40.0 + round1(15 * 1.5)=22.5 + 3.8 + 0.0 = 66.3.
        assert pipeline["statutory_score"] == 58
        assert pipeline["risk_adjusted_score"] == pytest.approx(66.3, abs=1e-6)
