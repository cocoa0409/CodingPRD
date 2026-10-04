"""Tests for compensating invariants: credit conservation and commitment conservation."""
from test_helpers import (
    validate_success,
    api_client,
    make_admin_headers,
    make_platform_headers,
    create_org,
    create_active_agreement,
    create_linked_account,
    create_grant,
    ingest_usage,
    generate_invoice,
    period_close,
    set_clock,
    get_agreement,
    get_credit_grant,
    setup_finalized_invoice,
    assert_credit_conservation,
)

ADMIN = make_admin_headers()
PLATFORM = make_platform_headers()


class TestCreditConservationAcrossConsumeAndRevoke:
    """consume + revoke leaves amount == consumed + remaining + forfeited."""

    def _setup(self):
        org = create_org(name="Ci Org", max_hourly_commitment_cents=100000,
                         capacity_quota_units=100)
        acct = create_linked_account(org["id"], name="acct-1", external_ref="ext-1")
        grant = create_grant(org["id"], amount_cents=1000,
                             expires_at="2026-12-01T00:00:00Z")
        inv = setup_finalized_invoice(org["id"], acct["id"], 300)
        return org, acct, grant, inv

    def test_partial_consumption_then_revoke_preserves_conservation(self, api):
        """PRD section 2.9: "Credit grants obey a strict conservation invariant
        at all times: for every grant, `amount_cents` equals `consumed_cents` plus
        `remaining_cents` plus `forfeited_cents`, so `remaining_cents` is always
        the original amount less what has been consumed less what has been
        forfeited."

        Design: Difficulty/compensating_invariant/credit_grant_conservation_across_consume_and_revoke
        """
        _, _, grant, _ = self._setup()
        data = validate_success(api.revoke_credit_grant(grant["id"], PLATFORM))
        assert data["status"] == "REVOKED"
        assert data["consumed_cents"] == 300
        assert data["forfeited_cents"] == 700
        assert data["remaining_cents"] == 0
        assert_credit_conservation(data)

    def test_finalize_moves_grant_to_depleting_before_revoke(self, api):
        """PRD section 3.7: "The debit happens at finalize, not at generation:
        when a `DRAFT` invoice is finalized, the cascade debits each grant in that
        order; a grant debited down to exactly zero remaining moves to `EXHAUSTED`
        (whether from `ISSUED` or `DEPLETING`), a partially debited `ISSUED` grant
        moves to `DEPLETING`, and every such transition recomputes
        `unapplied_credit_cents`."
        PRD section 3.7: "A `PlatformBillingOperator` may revoke an `ISSUED` or
        `DEPLETING` grant, with the same forfeiture bookkeeping and a `version`
        bump."

        Design: Difficulty/compensating_invariant/credit_grant_conservation_across_consume_and_revoke
        """
        _, _, grant, _ = self._setup()
        g = get_credit_grant(grant["id"])
        assert g["status"] == "DEPLETING"
        assert g["consumed_cents"] == 300
        assert g["remaining_cents"] == 700
        validate_success(api.revoke_credit_grant(grant["id"], PLATFORM))
        g = get_credit_grant(grant["id"])
        assert_credit_conservation(g)


class TestCommitmentConservation:
    """consumed + accrued true-up equals the committed spend."""

    def _setup(self):
        org = create_org(name="Cc Org", max_hourly_commitment_cents=100000,
                         capacity_quota_units=100)
        agr = create_active_agreement(
            org["id"],
            tiers=[{"service_family": "COMPUTE", "threshold_cents": 0, "rate": 0.10}],
            committed_spend_cents=1000000,
            term_start="2026-09-01T00:00:00Z", term_end="2026-10-01T00:00:00Z",
        )
        acct = create_linked_account(org["id"], name="acct-1", external_ref="ext-1")
        ingest_usage(acct["id"], usage_hour_start="2026-09-01T00:00:00Z",
                     list_price_cents=600000)
        generate_invoice(org["id"], period_index=0)
        set_clock("2026-10-01T00:00:00Z")
        period_close(org["id"])
        return org, agr, acct

    def test_shortfall_trueup_amount_is_committed_minus_consumed(self, api):
        """PRD section 3.8: "The shortfall is the amount by which
        `committed_spend_cents` exceeds the pass-2 consumed value, floored at
        zero. When the shortfall is zero — including the boundary where pass-2
        consumption exactly equals the commitment — no charge is created at all
        and the assess call answers 200 with null data; a positive shortfall
        yields a `SHORTFALL` charge in `ASSESSED` status with null `plan_id`,
        returned with 201, and the agreement's `accrued_trueup_cents` is
        recomputed."

        Design: Difficulty/compensating_invariant/commitment_conservation_consumed_plus_trueup_equals_committed
        """
        _, agr, _ = self._setup()
        agr_after = get_agreement(agr["id"])
        assert agr_after["lifecycle_status"] == "EXPIRED"
        resp = api.assess_trueup({"agreement_id": agr["id"]}, ADMIN)
        data = validate_success(resp, expected_status=201)
        assert data["type"] == "SHORTFALL"
        assert data["amount_cents"] == 400000, (
            f"1000000 - 600000 = 400000, got {data['amount_cents']}"
        )
        assert data["plan_id"] is None

    def test_consumed_plus_accrued_equals_committed(self, api):
        """PRD section 2.9: "On the agreement, `accrued_trueup_cents` is the sum
        of `amount_cents` over all true-up charges of the agreement whose status
        is anything other than `WAIVED`; it is recomputed whenever a charge is
        created, billed, or waived."
        PRD section 3.8: "The shortfall is the amount by which
        `committed_spend_cents` exceeds the pass-2 consumed value, floored at
        zero."

        Design: Difficulty/compensating_invariant/commitment_conservation_consumed_plus_trueup_equals_committed
        """
        _, agr, _ = self._setup()
        validate_success(api.assess_trueup({"agreement_id": agr["id"]}, ADMIN),
                         expected_status=201)
        agr_after = get_agreement(agr["id"])
        assert agr_after["consumed_commitment_cents"] == 600000
        assert agr_after["accrued_trueup_cents"] == 400000
        assert (agr_after["consumed_commitment_cents"]
                + agr_after["accrued_trueup_cents"]
                == agr_after["committed_spend_cents"] == 1000000)
