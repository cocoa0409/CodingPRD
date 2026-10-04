"""Reinsurance treaties: lifecycle, attachment, retroactive reserve cession."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    attach_treaty,
    create_active_treaty,
    create_cause_and_cohort,
    create_escalated_claim,
    file_claim,
    get_cohort,
    pay_premium,
    set_clock,
    setup_bound_policy,
    validate_error,
    validate_success,
)

FINANCE = TEST_USERS["finance_ops_headers"]
ADJ_1 = TEST_USERS["adjuster_1_headers"]


class TestTreatyLifecycle:
    def test_retire_attached_treaty_rejected(self, api):
        """PRD §3.3: "A treaty attached to any cohort cannot be retired — retirement is rejected with ERR_TREATY_IN_USE".

        Design: Corner/validations/treaty_retire_while_attached_rejected
        """
        set_clock()
        cause, cohort = create_cause_and_cohort(2026)
        t1 = create_active_treaty(name="T1", quota_share_pct=0.75)
        create_active_treaty(name="T2", quota_share_pct=0.50)
        attach_treaty(cohort["id"], t1["id"])
        resp = api.retire_treaty(t1["id"], FINANCE)
        validate_error(resp, ApiErrorId.ERR_TREATY_IN_USE)


class TestRetroactiveAttach:
    def test_attach_recomputes_escalated_claim_reserve_cession(self, api):
        """PRD §3.3: "Attachment is retroactive over open reserves: every ESCALATED claim in the cohort immediately has its reinsurance_share_cents recomputed as the reserve amount multiplied by the quota-share percentage, rounded half-up to integer cents".

        Design: Difficulty/transitive_cascade/treaty_attach_retroactive_recompute_cascade_over_reserves
        """
        ctx = setup_bound_policy(
            state_code="RI", premium_cents=200000, coverage_amount_cents=900000,
            filing_mode="ABSOLUTE_CENTS", max_flat_fee_pct=0.30,
            max_flat_fee_cap_cents=25000, flat_fee_pct=0.30, flat_fee_cents=25000,
        )
        pay_premium(ctx["policy"]["id"], 200000)  # pot 175000, no treaty yet
        claim = create_escalated_claim(ctx["policyholder"]["id"], ctx["policy"]["id"], 60000)
        assert claim["reinsurance_share_cents"] == 0
        treaty = create_active_treaty(quota_share_pct=0.75)
        attach_treaty(ctx["cohort"]["id"], treaty["id"])
        claim_after = validate_success(api.get_claim(claim["id"], ADJ_1))
        assert claim_after["reinsurance_share_cents"] == 45000

    def test_attach_recomputes_cohort_projections_and_leaves_pot_untouched(self, api):
        """PRD §3.3: "The cohort's reinsurance_ceded_cents, both retained-claims aggregates, and both giveback figures are recomputed in the same request".
        PRD §3.10: "giveback_projected_cents is the claims pot minus that larger figure, floored at zero" and "giveback_actual_cents is the claims pot minus that figure, floored at zero" — the premium ledger rows themselves are not re-ceded by attachment.

        Design: Difficulty/transitive_cascade/treaty_attach_retroactive_recompute_cascade_over_reserves
        """
        ctx = setup_bound_policy(
            state_code="RI", premium_cents=200000, coverage_amount_cents=900000,
            filing_mode="ABSOLUTE_CENTS", max_flat_fee_pct=0.30,
            max_flat_fee_cap_cents=25000, flat_fee_pct=0.30, flat_fee_cents=25000,
        )
        pay_premium(ctx["policy"]["id"], 200000)  # pot 175000
        create_escalated_claim(ctx["policyholder"]["id"], ctx["policy"]["id"], 60000)
        treaty = create_active_treaty(quota_share_pct=0.75)
        attach_treaty(ctx["cohort"]["id"], treaty["id"])
        cohort = get_cohort(ctx["cohort"]["id"])
        assert cohort["retained_claims_reserved_cents"] == 15000
        assert cohort["giveback_projected_cents"] == 160000
        assert cohort["giveback_actual_cents"] == 175000
        assert cohort["claims_pot_cents"] == 175000
