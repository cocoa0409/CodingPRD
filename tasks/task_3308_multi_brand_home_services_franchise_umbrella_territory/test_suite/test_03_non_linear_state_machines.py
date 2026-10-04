"""Non-linear state machines: parallel dimensions and a cyclic dispute loop."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    conduct_audit,
    create_audit,
    get_agreement,
    get_audit,
    get_referral,
    make_franchisee_operator_headers,
    publish_audit,
    setup_active_agreement,
    setup_completed_referral,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["franchise_admin_headers"]


class TestAgreementParallelDimensions:
    def _published_failing_audit(self):
        _, franchisee, _, agreement = setup_active_agreement()
        audit = create_audit(agreement["id"])
        audit = conduct_audit(audit["id"])
        audit = publish_audit(audit["id"], agreement["id"])
        return franchisee, agreement, audit

    def test_publishing_a_failing_audit_moves_only_the_standards_axis(self, api):
        """PRD §2.7: "The two dimensions evolve independently: a published audit
        can be reopened while its remediation is escalated, and an escalated
        remediation can still be reopened away by the audit pipeline. Neither
        dimension gates the other."

        Design: Difficulty/non_linear_state_machine/agreement_parallel_dimensions_lifecycle_and_standards
        """
        _, agreement, audit = self._published_failing_audit()

        published = get_audit(audit["id"])
        assert published["audit_status"] == "PUBLISHED"
        assert published["weighted_score"] == 56.5, (
            f"a MYSTERY_SHOP raw 80.0 weighted by 0.80 with one critical finding "
            f"is 64.0 - 7.5 = 56.5, got {published['weighted_score']}"
        )
        assert published["outcome"] == "FAIL"
        assert published["remediation_status"] == "OPEN"

        refreshed = get_agreement(agreement["id"])
        assert refreshed["standards_status"] == "REMEDIATION_REQUIRED", (
            f"a published FAIL outcome must raise the standards posture, got "
            f"{refreshed['standards_status']}"
        )
        assert refreshed["lifecycle_status"] == "ACTIVE", (
            "the standards axis moved; the commercial lifecycle axis must be "
            f"exactly where it was, got {refreshed['lifecycle_status']}"
        )

    def test_open_remediation_count_and_the_filtered_listing_agree(self, api):
        """PRD §2.7: "The open remediation count is the number of that
        agreement's audits whose `remediation_status` is `OPEN`, `SUBMITTED`,
        `RE_VERIFICATION` or `ESCALATED`."

        Design: Difficulty/non_linear_state_machine/agreement_parallel_dimensions_lifecycle_and_standards
        """
        franchisee, agreement, _ = self._published_failing_audit()

        refreshed = get_agreement(agreement["id"])
        assert refreshed["open_remediation_count"] == 1

        resp = api.list_agreements(
            ADMIN,
            {"franchisee_id": franchisee["id"], "standards_status": "REMEDIATION_REQUIRED"},
        )
        rows, meta = validate_paginated(resp)
        assert meta["total_count"] == 1, (
            f"the franchisee must carry exactly one agreement in "
            f"REMEDIATION_REQUIRED, got {meta['total_count']}"
        )
        assert rows[0]["id"] == agreement["id"]

    def test_the_commercial_axis_still_moves_while_the_standards_axis_is_open(self, api):
        """PRD §2.7: "An agreement's `standards_status` is the worst posture among
        its audits" — it is derived from the audits and is recomputed on the
        audit's own transitions, so a commercial move by the agreement itself
        leaves it untouched.

        Design: Difficulty/non_linear_state_machine/agreement_parallel_dimensions_lifecycle_and_standards
        """
        _, agreement, _ = self._published_failing_audit()

        resp = api.suspend_agreement(agreement["id"], ADMIN, reason="Standing down")
        suspended = validate_success(resp, 200)
        assert suspended["lifecycle_status"] == "SUSPENDED"
        assert suspended["standards_status"] == "REMEDIATION_REQUIRED", (
            "suspending the agreement is a commercial move and must not clear "
            f"the open standards posture, got {suspended['standards_status']}"
        )
        assert suspended["open_remediation_count"] == 1


class TestReferralCyclicDisputeLoop:
    def test_settlement_is_refused_while_a_dispute_is_open(self, api):
        """PRD §3.5: "A referral that still carries an open dispute cannot be
        settled, and such an attempt is refused with `ERR_REFERRAL_DISPUTED`."

        Design: Difficulty/non_linear_state_machine/referral_cyclic_dispute_and_resolution_loop
        """
        ctx, referral = setup_completed_referral()
        resp = api.dispute_referral(
            referral["id"], "Job value recorded as 120000 but the work performed was partial",
            make_franchisee_operator_headers(ctx["fr_ms"]["id"]),
        )
        disputed = validate_success(resp, 200)
        assert disputed["status"] == "DISPUTED"

        resp = api.settle_referral(
            referral["id"], ctx["agt_a1"]["version"], ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_REFERRAL_DISPUTED)
        assert get_referral(referral["id"])["status"] == "DISPUTED"

    def test_clearing_the_dispute_returns_the_referral_to_completed(self, api):
        """PRD §3.5: "A `FranchiseAdmin` clears the dispute, which returns the
        referral to `COMPLETED` with its recorded reason removed, or settles it
        directly if no dispute is open."

        Design: Difficulty/non_linear_state_machine/referral_cyclic_dispute_and_resolution_loop
        """
        ctx, referral = setup_completed_referral()
        api.dispute_referral(
            referral["id"], "Partial work performed",
            make_franchisee_operator_headers(ctx["fr_ms"]["id"]),
        )

        resp = api.resolve_referral_dispute(referral["id"], ADMIN)
        resolved = validate_success(resp, 200)
        assert resolved["status"] == "COMPLETED"
        assert resolved["dispute_reason"] is None, (
            f"clearing the dispute removes the recorded reason, got "
            f"{resolved['dispute_reason']!r}"
        )

    def test_the_whole_d_to_c_to_d_cycle_posts_the_fee_exactly_once(self, api):
        """PRD §3.5: "On success the referral's `settled_clock_iso` is stamped,
        its status becomes `SETTLED`, and the fee is posted to both sides at
        once: the originating agreement's `cumulative_referral_net_cents` is
        increased by the fee".

        Design: Difficulty/non_linear_state_machine/referral_cyclic_dispute_and_resolution_loop
        """
        ctx, referral = setup_completed_referral()
        operator = make_franchisee_operator_headers(ctx["fr_ms"]["id"])
        api.dispute_referral(referral["id"], "Value disputed", operator)
        api.resolve_referral_dispute(referral["id"], ADMIN)

        resp = api.settle_referral(
            referral["id"], ctx["agt_a1"]["version"], ADMIN,
        )
        settled = validate_success(resp, 200)
        assert settled["status"] == "SETTLED"
        assert settled["fee_variant"] == "TIERED_BRAND_PAIR"
        assert settled["referral_fee_cents"] == 18000

        originator = get_agreement(ctx["agt_a1"]["id"])
        assert originator["cumulative_referral_net_cents"] == 18000, (
            "the dispute round-trip must not double-post the fee: expected "
            f"18000, got {originator['cumulative_referral_net_cents']}"
        )