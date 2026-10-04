"""Tests for boundary precision: tier thresholds and zero-shortfall boundary."""
from test_helpers import (
    validate_success,
    api_client,
    make_admin_headers,
    create_org,
    create_active_agreement,
    create_linked_account,
    ingest_usage,
    generate_invoice,
    period_close,
    set_clock,
    get_invoice_lines,
    ApiErrorId,
)

ADMIN = make_admin_headers()


class TestTierThresholdBoundary:
    """Cumulative consumption landing exactly at a tier threshold."""

    def _setup(self, second_usage):
        org = create_org(name="Bd Org", max_hourly_commitment_cents=100000,
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

    def test_consumption_ending_exactly_at_threshold_stays_in_lower_bracket(self, api):
        """PRD section 3.3: "Each tier row names an `agreement_id`, a
        `service_family` (for example COMPUTE, STORAGE, or DATABASE), a
        `threshold_cents` at which the bracket begins — inclusive, so consumption
        exactly equal to the threshold already qualifies for the higher bracket —
        and a `rate`, a marginal discount rate of at least 0 and strictly less
        than 1 applied inside that bracket."

        Design: Difficulty/boundary_precision_check/tier_threshold_boundary_consumed_exactly_at_threshold_enters_higher_bracket
        """
        org, _, _ = self._setup(50000)
        inv = generate_invoice(org["id"], period_index=1)
        line = get_invoice_lines(inv["id"])[0]
        assert line["tier_discount_cents"] == 5000, (
            f"c1 lands exactly on 400000 so no portion enters the 25% bracket: "
            f"50000 @ 10% = 5000, got {line['tier_discount_cents']}"
        )
        assert line["net_due_cents"] == 45000

    def test_one_cent_past_threshold_enters_higher_bracket(self, api):
        """PRD section 3.6: "The discount is the sum over brackets of the bracket's
        `rate` times the overlap between the line's consumption span and the
        bracket's half-open span from its `threshold_cents` up to the next tier's
        threshold, where the highest tier's bracket extends without bound."
        PRD section 3.3: "Each tier row names an `agreement_id`, a
        `service_family` (for example COMPUTE, STORAGE, or DATABASE), a
        `threshold_cents` at which the bracket begins — inclusive, so consumption
        exactly equal to the threshold already qualifies for the higher bracket —
        and a `rate`, a marginal discount rate of at least 0 and strictly less
        than 1 applied inside that bracket."

        Design: Difficulty/boundary_precision_check/tier_threshold_boundary_consumed_exactly_at_threshold_enters_higher_bracket
        """
        org, _, _ = self._setup(50001)
        inv = generate_invoice(org["id"], period_index=1)
        line = get_invoice_lines(inv["id"])[0]
        # 50000 @ 10% = 5000, plus 1 cent @ 25% = 0.25 -> round half-up 5000
        # The >= boundary is decisive: at exactly 50000 no 25% contribution exists.
        assert line["tier_discount_cents"] == 5000, (
            f"50000 @ 10% = 5000 + round_half_up(1 * 0.25 = 0.25) = 0 -> 5000, "
            f"got {line['tier_discount_cents']}"
        )
        assert line["net_due_cents"] == 45001


class TestShortfallZeroBoundary:
    """Consumed exactly equal to committed creates no charge at all."""

    def _setup(self):
        org = create_org(name="Zo Org", max_hourly_commitment_cents=100000,
                         capacity_quota_units=100)
        agr = create_active_agreement(
            org["id"],
            tiers=[{"service_family": "COMPUTE", "threshold_cents": 0, "rate": 0.10}],
            committed_spend_cents=100000,
            term_start="2026-09-01T00:00:00Z", term_end="2026-10-01T00:00:00Z",
        )
        acct = create_linked_account(org["id"], name="acct-1", external_ref="ext-1")
        ingest_usage(acct["id"], usage_hour_start="2026-09-01T00:00:00Z",
                     list_price_cents=100000)
        set_clock("2026-10-01T00:00:00Z")
        period_close(org["id"])
        return org, agr, acct

    def test_assess_returns_200_null_data_at_exact_boundary(self, api):
        """PRD section 2.10: "One endpoint behaves dual-mode: assessing a
        term-end shortfall returns 201 with the created charge when the shortfall
        is positive, but 200 with `data` null when the shortfall is exactly zero
        (including the boundary where consumed spend equals the commitment) — no
        zero-amount charge is ever created."

        Design: Difficulty/boundary_precision_check/shortfall_boundary_consumed_exactly_committed_creates_no_charge
        """
        _, agr, _ = self._setup()
        resp = api.assess_trueup({"agreement_id": agr["id"]}, ADMIN)
        assert resp.status_code == 200, (
            f"consumed == committed must answer 200, got {resp.status_code}"
        )
        body = resp.json()
        assert body["data"] is None, "zero shortfall returns null data"

    def test_no_trueup_row_exists_after_zero_shortfall_assess(self, api):
        """PRD section 3.8: "When the shortfall is zero — including the boundary
        where pass-2 consumption exactly equals the commitment — no charge is
        created at all and the assess call answers 200 with null data; a positive
        shortfall yields a `SHORTFALL` charge in `ASSESSED` status with null
        `plan_id`, returned with 201, and the agreement's `accrued_trueup_cents`
        is recomputed."

        Design: Difficulty/boundary_precision_check/shortfall_boundary_consumed_exactly_committed_creates_no_charge
        """
        _, agr, _ = self._setup()
        resp = api.assess_trueup({"agreement_id": agr["id"]}, ADMIN)
        assert resp.status_code == 200
        charges = api.list_trueup_charges(
            ADMIN, params={"agreement_id": agr["id"]}
        ).json()["data"]
        assert charges == [], "no zero-amount charge row may exist"
