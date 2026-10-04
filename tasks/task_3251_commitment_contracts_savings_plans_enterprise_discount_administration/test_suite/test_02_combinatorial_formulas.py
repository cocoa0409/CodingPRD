"""Tests for combinatorial formulas: tiered marginal discount and per-line rounding."""
from test_helpers import (
    validate_success,
    api_client,
    make_admin_headers,
    make_finance_headers,
    make_platform_headers,
    create_org,
    create_active_agreement,
    create_linked_account,
    create_plan,
    ingest_usage,
    generate_invoice,
    period_close,
    get_agreement,
    get_invoice_lines,
    ApiErrorId,
)

ADMIN = make_admin_headers()
FINANCE = make_finance_headers()
PLATFORM = make_platform_headers()


class TestTieredDiscountMarginalBrackets:
    """Tier discount straddling brackets mid-invoice."""

    def _setup(self, second_usage):
        org = create_org(name="Tier Org", max_hourly_commitment_cents=100000,
                         capacity_quota_units=100)
        agr = create_active_agreement(
            org["id"],
            tiers=[{"service_family": "COMPUTE", "threshold_cents": 0, "rate": 0.10},
                   {"service_family": "COMPUTE", "threshold_cents": 400000, "rate": 0.25}],
            committed_spend_cents=1000000,
        )
        acct = create_linked_account(org["id"], name="acct-1", external_ref="ext-1")
        ingest_usage(acct["id"], usage_hour_start="2026-09-01T00:00:00Z",
                     list_price_cents=350000)
        generate_invoice(org["id"], period_index=0)
        period_close(org["id"])
        ingest_usage(acct["id"], usage_hour_start="2026-09-01T01:00:00Z",
                     list_price_cents=second_usage)
        return org, agr, acct

    def test_straddling_amount_splits_across_brackets(self, api):
        """PRD section 3.6: "The discount is the sum over brackets of the bracket's
        `rate` times the overlap between the line's consumption span and the
        bracket's half-open span from its `threshold_cents` up to the next tier's
        threshold, where the highest tier's bracket extends without bound."

        Design: Difficulty/combinatorial_formula/tiered_discount_straddles_marginal_brackets_mid_invoice
        """
        org, agr, _ = self._setup(100000)
        inv = generate_invoice(org["id"], period_index=1)
        lines = get_invoice_lines(inv["id"])
        assert len(lines) == 1
        line = lines[0]
        assert line["tier_discount_cents"] == 17500, (
            f"50000 @ 10% + 50000 @ 25% = 5000 + 12500 = 17500, "
            f"got {line['tier_discount_cents']}"
        )
        assert line["net_due_cents"] == 82500
        agr_after = get_agreement(agr["id"])
        assert agr_after["consumed_commitment_cents"] == 450000, (
            f"consumed must advance 350000 + 100000 = 450000, "
            f"got {agr_after['consumed_commitment_cents']}"
        )

    def test_bracket_rates_are_marginal_not_flat(self, api):
        """PRD section 3.3: "Each tier row names an `agreement_id`, a
        `service_family` (for example COMPUTE, STORAGE, or DATABASE), a
        `threshold_cents` at which the bracket begins — inclusive, so consumption
        exactly equal to the threshold already qualifies for the higher bracket —
        and a `rate`, a marginal discount rate of at least 0 and strictly less
        than 1 applied inside that bracket."

        Design: Difficulty/combinatorial_formula/tiered_discount_straddles_marginal_brackets_mid_invoice
        """
        org, agr, _ = self._setup(100000)
        inv = generate_invoice(org["id"], period_index=1)
        line = get_invoice_lines(inv["id"])[0]
        # A flat-rate interpretation would give 100000 * 0.25 = 25000; the
        # correct marginal computation gives 17500.
        assert line["tier_discount_cents"] != 25000, (
            "tier rates are marginal per bracket, not flat over the whole amount"
        )
        assert line["tier_discount_cents"] == 17500


class TestPerLineRoundingOrder:
    """Per-line round-half-up beats sum-then-round by one cent."""

    def _setup(self):
        org = create_org(name="Rnd Org", max_hourly_commitment_cents=100000,
                         capacity_quota_units=100)
        agr = create_active_agreement(
            org["id"],
            tiers=[{"service_family": "COMPUTE", "threshold_cents": 0, "rate": 0.10}],
            committed_spend_cents=1000000,
        )
        a1 = create_linked_account(org["id"], name="acct-1", external_ref="ext-1")
        a2 = create_linked_account(org["id"], name="acct-2", external_ref="ext-2")
        create_plan(
            org["id"], agr["id"],
            type="SAVINGS_PLAN", instance_family="COMPUTE", units=0,
            hourly_commitment_cents=100000, plan_discount_rate=0.30,
            term_start="2026-09-01T00:00:00Z", term_end="2026-10-01T00:00:00Z",
        )
        ingest_usage(a1["id"], usage_hour_start="2026-09-01T00:00:00Z",
                     list_price_cents=101)
        ingest_usage(a2["id"], usage_hour_start="2026-09-01T00:00:00Z",
                     list_price_cents=101)
        return org, agr, a1, a2

    def test_each_line_rounds_half_up_independently(self, api):
        """PRD section 2.5: "Per-stage discount fields on a line are each stored as
        integer cents rounded half-up, with the final stage absorbing any residual
        one-cent difference so that every line satisfies the identity `list_cents`
        minus `amendment_discount_cents` minus `plan_discount_cents` minus
        `tier_discount_cents` minus `credit_applied_cents` equals `net_due_cents`."

        Design: Difficulty/combinatorial_formula/waterfall_per_line_rounding_beats_sum_then_round_by_one_cent
        """
        org, _, _, _ = self._setup()
        inv = generate_invoice(org["id"], period_index=0)
        lines = get_invoice_lines(inv["id"])
        assert len(lines) == 2
        for line in lines:
            assert line["plan_discount_cents"] == 30, (
                f"round_half_up(101 * 0.30 = 30.3) = 30, got {line['plan_discount_cents']}"
            )
            assert line["tier_discount_cents"] == 7, (
                f"round_half_up((101 - 30.3) * 0.10 = 7.07) = 7, got {line['tier_discount_cents']}"
            )
            assert line["net_due_cents"] == 64, (
                f"63.63 rounds half-up to 64, got {line['net_due_cents']}"
            )
            assert (line["list_cents"] - line["amendment_discount_cents"]
                    - line["plan_discount_cents"] - line["tier_discount_cents"]
                    - line["credit_applied_cents"]) == line["net_due_cents"]

    def test_invoice_total_sums_rounded_lines_never_sum_then_round(self, api):
        """PRD section 2.5: "All money amounts are integer cents."
        PRD section 2.5: "Unless a rule says otherwise, intermediate computation
        keeps full precision and rounding happens exactly once per invoice line:
        the line's `net_due_cents` is rounded half-up to integer cents at line
        finalization, and invoice totals are sums of those already-rounded line
        values" — with the sum-of-unrounded-then-round pattern never used.

        Design: Difficulty/combinatorial_formula/waterfall_per_line_rounding_beats_sum_then_round_by_one_cent
        """
        org, _, _, _ = self._setup()
        inv = generate_invoice(org["id"], period_index=0)
        assert inv["total_due_cents"] == 128, (
            f"sum of rounded lines 64 + 64 = 128; sum-then-round of 127.26 "
            f"would give 127 which is the forbidden order; got {inv['total_due_cents']}"
        )
