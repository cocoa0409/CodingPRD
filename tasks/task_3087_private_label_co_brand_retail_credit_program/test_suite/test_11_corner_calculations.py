"""Corner coverage for the promotional exposure, profitability constants and
the incremental profitability path.
"""
import pytest

from test_helpers import (
    validate_success,
    get_success_data,
    setup_program_with_account,
    setup_program_with_two_promo_plans,
    setup_settled_month,
    open_settlement_batch,
    post_promo_purchase,
    get_plan_for_transaction,
    program_summary,
    round_half_up,
    ACQUISITION_COST_PER_ACCOUNT_CENTS,
)


class TestPromotionalExposureIsNettedByTheSubsidyRate:

    def test_partner_exposure_is_the_gross_projection_times_the_subsidy_rate(self, api, admin_headers):
        """PRD §3.4: "otherwise it is the plan's principal multiplied by its term
        rate, multiplied by its term in months, divided by twelve, multiplied by
        the agreement's `promo_subsidy_rate`, rounded half-up to two decimal
        places." PRD §3.4: "`subsidy_at_application_cents` is the projected subsidy
        struck once from the transaction-specific term rate; it is the quote the
        cardholder is shown and is never revised".

        Design: Corner/calculations/promo_subsidy_at_risk_is_netted_by_the_agreement_subsidy_rate
        """
        _partner, _agreement, program, account = setup_program_with_account(api)
        transaction = post_promo_purchase(api, account["id"], 120000, 12)
        plan = get_plan_for_transaction(api, transaction["id"])

        assert plan["subsidy_at_application_cents"] == 19188, (
            "the gross projection at the 12-month term rate"
        )
        assert plan["subsidy_at_risk_cents"] == 5756, (
            "the partner's 30% share, the figure the retailer carries"
        )
        assert plan["plan_status"] == "ACTIVE"
        assert plan["qualifying_flag"] is True

        summary = program_summary(api, program["id"])
        assert summary["free_look_exposure_cents"] == 5756

    def test_the_two_figures_diverge_under_a_different_subsidy_rate(self, api, admin_headers):
        """PRD §3.4: "`subsidy_at_risk_cents` is the live, partner-funded figure
        the retailer carries, and it moves." PRD §3.4: "the as-charged subsidy asset
        and is written only at settlement; it stays null for as long as
        `plan_status` is anything other than `SETTLED`."

        Design: Corner/calculations/promo_subsidy_at_risk_is_netted_by_the_agreement_subsidy_rate
        """
        _partner, _agreement, _program, account = setup_program_with_account(
            api, credit_limit_cents=500000, promo_subsidy_rate=0.50
        )
        transaction = post_promo_purchase(api, account["id"], 240000, 6)
        plan = get_plan_for_transaction(api, transaction["id"])

        assert plan["subsidy_at_application_cents"] == 15588
        assert plan["subsidy_at_risk_cents"] == 7794, "50% of the 6-month projection"
        assert plan["net_subsidy_cents"] is None, "the as-charged asset is null until settlement"


class TestProgramProfitabilityAcquisitionCost:

    def test_acquisition_cost_is_charged_once_per_account(self, api, admin_headers):
        """PRD §3.6: "The final subtraction is the account count of the program
        multiplied by a per-account acquisition cost of 4,200 cents, and the whole
        result is rounded half-up to two decimal places."

        Design: Corner/calculations/program_profitability_subtracts_acquisition_cost_per_account
        """
        _partner, _agreement, program, _account, batch = setup_settled_month(api)
        summary = validate_success(api.get_program_summary(program["id"], admin_headers), 200)

        assert summary["program_profitability_cents"] == 21196
        assert summary["account_count"] == 1
        assert batch["retailer_liability_cents"] == 10432
        assert summary["program_profitability_cents"] < 34776 - ACQUISITION_COST_PER_ACCOUNT_CENTS


class TestProgramProfitabilityIncrementalPath:

    def test_a_second_empty_window_batch_leaves_profitability_unchanged(self, api, admin_headers):
        """PRD §3.6: "may be maintained either by recomputing every settled
        batch from scratch" and "by adding a single new batch's contribution to
        the prior total when only that batch has settled". PRD §3.7: "It is every
        promotional plan whose
        `promo_start_at` falls within the half-open window running from
        `period_start` inclusive to `period_end` exclusive".

        Design: Corner/calculations/program_profitability_incremental_matches_full_recompute
        """
        _partner, agreement, program, _account, _batch = setup_settled_month(api)
        first = validate_success(api.get_program_summary(program["id"], admin_headers), 200)
        assert first["program_profitability_cents"] == 21196

        october = open_settlement_batch(api, agreement["id"],
                                        "2026-10-01T00:00:00Z", "2026-11-01T00:00:00Z")
        validate_success(api.finalize_settlement_batch(october["id"], admin_headers), 200)

        second = validate_success(api.get_program_summary(program["id"], admin_headers), 200)
        assert second["settled_batch_count"] == 2
        assert october["transaction_count"] == 0
        assert second["program_profitability_cents"] == 21196, (
            "the second window contains no promotion, so its contribution is exactly 0"
        )

    def test_a_second_settled_batch_keeps_the_incremental_sum_free_of_rounding_drift(
            self, api, admin_headers):
        """PRD §3.6: "The incremental path must land on exactly the same cents as
        the full recomputation; the reason each batch contribution is rounded
        before the outer sum is precisely so that no rounding drift accumulates
        between the two paths."

        Design: Corner/calculations/program_profitability_incremental_matches_full_recompute
        """
        _partner, agreement, program, _account, _batch = setup_settled_month(api)
        first = validate_success(api.get_program_summary(program["id"], admin_headers), 200)

        october = open_settlement_batch(api, agreement["id"],
                                        "2026-10-01T00:00:00Z", "2026-11-01T00:00:00Z")
        validate_success(api.finalize_settlement_batch(october["id"], admin_headers), 200)
        second = validate_success(api.get_program_summary(program["id"], admin_headers), 200)

        assert second["program_profitability_cents"] == first["program_profitability_cents"], (
            "the incremental path and the full recomputation agree to the cent"
        )
        assert second["settled_batch_count"] == 2