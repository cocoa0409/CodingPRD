"""Calculation corner claims: weighted composite, KPI legs, escalation margin."""
import pytest

from test_helpers import (
    api_client,
    get_success_data,
    validate_success,
    create_activated_account,
    create_scorecard,
    create_kpi,
    evaluate_kpi,
    TEST_USERS,
    ae_headers,
)

GM = TEST_USERS["governance_manager_headers"]


class TestWeightedScorecardComposite:

    def test_tier_shifts_the_quality_weight(self, api):
        """PRD §3.7: "when the account's platform_tier is COMPLETE or ENTERPRISE
        the quality weight is 6,000 and the response weight is 4,000, and
        otherwise both weights are 5,000."
        PRD §3.7: "That raw value is rounded half-up to 2 decimal places, clamped
        into the range 0 to 10,000 inclusive, and then floored to a whole number
        of basis points".

        Design: Corner/calculations/scorecard_composite_shifts_with_platform_tier_weight
        """
        account = create_activated_account(platform_tier="ENTERPRISE", portfolio_sqft=400_000)
        scorecard = create_scorecard(account, quality_bps=9800, response_bps=9300)
        version = get_success_data(api.get_account(account["id"], ae_headers(account)))[
            "version"
        ]
        published = validate_success(
            api.publish_scorecard(
                scorecard["id"], {"expected_account_version": version}, GM
            ),
            200,
        )
        # (9800*6000 + 9300*4000) / 10000 = 9600
        assert published["composite_bps"] == 9600


class TestKpiAdjustmentLegs:

    def test_savings_gainshare_leg_pays_over_target(self, api):
        """PRD §3.7: "if actual_value is at least the threshold the gainshare is
        the excess of actual_value over the threshold multiplied by 2,500 basis
        points and divided by 10,000".
        PRD §3.7: "penalty_cents is the shortfall component, gainshare_cents is
        the figure from the second step, and net_adjustment_cents is the gainshare
        minus the penalty."

        Design: Corner/calculations/kpi_savings_gainshare_leg_pays_over_target
        """
        account = create_activated_account()
        kpi = create_kpi(
            account, kpi_code="SAVINGS_ACHIEVED_CENTS", kpi_family="SAVINGS",
            measurement_unit="CENTS", measurement_window="ANNUAL",
            target_value=40_000_000,
        )
        evaluated = evaluate_kpi(kpi, 52_000_000)
        # (52,000,000 - 40,000,000) * 2500 / 10000 = 3,000,000
        assert evaluated["gainshare_cents"] == pytest.approx(3_000_000.00, abs=0.01)
        assert evaluated["penalty_cents"] == pytest.approx(0.00, abs=0.01)
        assert evaluated["net_adjustment_cents"] == pytest.approx(3_000_000.00, abs=0.01)

    def test_exactly_at_target_pays_nothing(self, api):
        """PRD §3.7: "The comparison is at-least on both legs, so an exact match
        produces zero shortfall and zero gainshare."

        Design: Corner/calculations/kpi_at_exact_target_pays_nothing
        """
        account = create_activated_account()
        kpi = create_kpi(account, target_value=9100)
        evaluated = evaluate_kpi(kpi, 9100)
        assert evaluated["gainshare_cents"] == pytest.approx(0.00, abs=0.01)
        assert evaluated["penalty_cents"] == pytest.approx(0.00, abs=0.01)
        assert evaluated["net_adjustment_cents"] == pytest.approx(0.00, abs=0.01)
        assert evaluated["escalation_status"] == "NONE"

    def test_bps_escalation_margin_is_strict(self, api):
        """PRD §2.11: "Both boundaries are strict — a shortfall of exactly 500
        basis points, or of exactly 500,000 cents, does not open an escalation
        and leaves escalation_status at NONE."
        PRD §2.4: "The same rollup writes the open escalation count into
        open_escalation_count on the account."

        Design: Corner/calculations/bps_escalation_margin_is_strict
        """
        account = create_activated_account()
        kpi = create_kpi(account, target_value=9100)
        at_margin = evaluate_kpi(kpi, 8600)
        assert at_margin["escalation_status"] == "NONE"
        over_margin = evaluate_kpi(kpi, 8599)
        assert over_margin["escalation_status"] == "OPEN"
        current = get_success_data(api.get_account(account["id"], ae_headers(account)))
        assert current["open_escalation_count"] == 1

    def test_cents_boundary_opens_escalation_one_cent_higher(self, api):
        """PRD §2.11: "when a CENTS row's actual_value falls more than 500,000
        cents below its target_value, the same happens."
        PRD §2.11: "a shortfall of exactly 500 basis points, or of exactly
        500,000 cents, does not open an escalation".

        Design: Corner/calculations/kpi_boundary_501_opens_escalation
        """
        account = create_activated_account()
        kpi = create_kpi(
            account, kpi_code="SAVINGS_ACHIEVED_CENTS", kpi_family="SAVINGS",
            measurement_unit="CENTS", measurement_window="ANNUAL",
            target_value=40_000_000,
        )
        # A shortfall of exactly 500,000 cents (39,500,000) does not open;
        # one cent lower (39,499,999) does.
        at_margin = evaluate_kpi(kpi, 39_500_000)
        assert at_margin["escalation_status"] == "NONE"
        over_margin = evaluate_kpi(kpi, 39_499_999)
        assert over_margin["escalation_status"] == "OPEN"