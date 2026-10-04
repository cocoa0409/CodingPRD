"""Promotional subsidy settlement: the projected and as-charged variants.

The two variants are struck from identical inputs and yield genuinely
different cents; the projected figure is quoted at batch open and the
as-charged figure only at finalize.
"""
import pytest

from test_helpers import (
    validate_success,
    setup_program_with_two_promo_plans,
    open_settlement_batch,
    get_success_data,
    round_half_up,
    TERM_RATE,
)


class TestPromotionalSubsidyDualVariant:

    def test_gross_and_net_subsidy_diverge_for_identical_inputs(self, api, admin_headers):
        """PRD §3.7: "Later, a `ProgramAdmin` finalizes the batch, which strikes
        the as-charged figures and posts the partner-funded chargeback invoice"
        and "This projection assumes the balance runs the full term and therefore
        over-states the exposure whenever a balance is paid in full inside the
        promotional window." The same two plans that project to the full term are
        replayed as 30 days accrued to `period_end`.

        Design: Difficulty/dual_variant_calc/subsidy_asset_projected_vs_as_charged
        """
        _partner, agreement, _program, _account, _plan12, _plan6 = (
            setup_program_with_two_promo_plans(api)
        )
        batch = open_settlement_batch(api, agreement["id"],
                                      "2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z",
                                      settlement_method="AS_CHARGED",
                                      reconciliation_method="PROJECTED")
        result = validate_success(api.finalize_settlement_batch(batch["id"], admin_headers), 200)

        assert result["gross_subsidy_cents"] == 34776, (
            f"projected full-term subsidy should be 34776, got {result['gross_subsidy_cents']}"
        )
        assert result["net_subsidy_cents"] == 4139, (
            f"as-charged 30-day subsidy should be 4139, got {result['net_subsidy_cents']}"
        )
        assert result["variance_cents"] == 30637, (
            f"variance should be 30637, got {result['variance_cents']}"
        )
        assert result["gross_subsidy_cents"] != result["net_subsidy_cents"]

    def test_variance_identity_holds_on_per_plan_rounded_figures(self, api, admin_headers):
        """PRD §3.7: "`variance_cents` is `gross_subsidy_cents` minus
        `net_subsidy_cents`, signed" and "both round each plan's figure to two
        decimal places half-up before summing, never after."

        Design: Difficulty/dual_variant_calc/subsidy_asset_projected_vs_as_charged
        """
        _partner, agreement, _program, _account, _plan12, _plan6 = (
            setup_program_with_two_promo_plans(api)
        )
        batch = open_settlement_batch(api, agreement["id"],
                                      "2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z",
                                      settlement_method="AS_CHARGED",
                                      reconciliation_method="PROJECTED")
        result = validate_success(api.finalize_settlement_batch(batch["id"], admin_headers), 200)

        expected_gross = (round_half_up(120000 * TERM_RATE[12] * 12 / 12)
                          + round_half_up(240000 * TERM_RATE[6] * 6 / 12))
        expected_net = (round_half_up(120000 * TERM_RATE[12] * 30 / 365)
                        + round_half_up(240000 * TERM_RATE[6] * 30 / 365))

        assert result["gross_subsidy_cents"] == expected_gross == 34776
        assert result["net_subsidy_cents"] == expected_net == 4139
        assert result["variance_cents"] == expected_gross - expected_net == 30637
        assert result["transaction_count"] == 2