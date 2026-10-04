"""Disputes, vendor quality accountability, and case posture gating."""
from test_helpers import (
    TEST_USERS,
    api_client,
    add_approved_project,
    cancel_case,
    complete_engagement,
    create_dispute,
    create_eligible_case,
    create_engagement,
    get_case,
    get_engagement,
    get_vendor,
    make_agent,
    make_vendor,
    make_vendor_headers,
    make_vendor_with_window,
    reset_clock,
    setup_engagement_in_work,
    start_engagement,
    validate_error,
    validate_success,
)
from test_helpers import ApiErrorId as ERR

HOMEOWNER = TEST_USERS["homeowner_headers"]
UNDERWRITER = TEST_USERS["program_underwriter_headers"]


class TestVendorQualityScoreDualVariant:
    """Recovery (+50bp, capped) and penalty (-500bp) variants from the same
    10000bp baseline."""

    def test_on_time_completion_at_cap_keeps_quality_at_10000(self, api):
        """PRD §3.4: "If the current clock reading is at or before the
        `completion_deadline`, the engagement moves from `IN_WORK` to
        `COMPLETE_ON_TIME`: the vendor's `on_time_streak` grows by 1, and when the
        engagement completes on time with no dispute attached to it, the vendor's
        `quality_score_bp` rises by 50 basis points, capped at 10000."

        Design: Difficulty/dual_variant_calc/vendor_quality_score_dual_variant_recovery_vs_penalty
        """
        ctx = setup_engagement_in_work()
        complete_engagement(ctx["engagement"]["id"], ctx["vendor"])
        vendor = get_vendor(ctx["vendor"]["id"])
        # min(10000, 10000 + 50) == 10000 — the recovery is capped.
        assert vendor["quality_score_bp"] == 10_000
        assert vendor["on_time_streak"] == 1

    def test_on_time_then_vendor_fault_resolution_yields_9500(self, api):
        """PRD §3.4: "when the engagement completes on time with no dispute
        attached to it, the vendor's `quality_score_bp` rises by 50 basis points,
        capped at 10000."
        PRD §3.6: "A vendor-fault resolution additionally cuts the responsible
        vendor's `quality_score_bp` by 500 basis points, never below 0."

        Design: Difficulty/dual_variant_calc/vendor_quality_score_dual_variant_recovery_vs_penalty
        """
        reset_clock()
        agent = make_agent()
        vendor, _window = make_vendor_with_window(trade="PAINT")
        vendor_id = vendor["id"]

        # Case 1: on-time completion with no dispute (capped at 10000).
        case1 = create_eligible_case(agent)
        project1 = add_approved_project(
            case1["id"], agent, expected_sale_price_lift_cents=1_000_000,
            estimated_cost_cents=1_000_000,
        )
        eng1 = create_engagement(
            project1["id"], vendor_id, agent, agreed_price_cents=1_000_000,
            start_date="2026-09-05T00:00:00Z", end_date="2026-09-10T00:00:00Z",
        )
        start_engagement(eng1["id"], vendor)
        complete_engagement(eng1["id"], vendor)
        assert get_vendor(vendor_id)["quality_score_bp"] == 10_000

        # Case 2: in-work engagement hit by a vendor-fault dispute resolution.
        case2 = create_eligible_case(
            agent, address_line="456 Oak Ave",
            estimated_property_value_cents=90_000_000,
            expected_sale_proceeds_cents=110_000_000,
        )
        project2 = add_approved_project(
            case2["id"], agent, expected_sale_price_lift_cents=1_000_000,
            estimated_cost_cents=1_000_000,
        )
        eng2 = create_engagement(
            project2["id"], vendor_id, agent, agreed_price_cents=1_000_000,
            start_date="2026-09-05T00:00:00Z", end_date="2026-09-10T00:00:00Z",
        )
        start_engagement(eng2["id"], vendor)
        dispute = create_dispute(case2["id"], project2["id"], eng2["id"])
        api_client.review_dispute(dispute["id"], UNDERWRITER)
        resp = api_client.resolve_dispute(
            dispute["id"], {"resolution": "RESOLVED_VENDOR_FAULT"}, UNDERWRITER
        )
        validate_success(resp)
        # max(0, min(10000, 10000 + 50) - 500) == 9500
        assert get_vendor(vendor_id)["quality_score_bp"] == 9_500


class TestEngagementDisputedCycle:
    def test_dispute_moves_in_work_engagement_to_disputed_and_restricts_case(self, api):
        """PRD §3.6: "A dispute is born `OPEN`. Its creation recomputes the
        case's `posture`, and if the engagement it references is currently
        `IN_WORK`, that engagement is automatically moved to `DISPUTED`."
        PRD §2.9: "When any dispute on the case is in `OPEN` or `IN_REVIEW` but
        the market-risk indicator is not true, the posture is `RESTRICTED`."

        Design: Difficulty/non_linear_state_machine/vendor_engagement_in_work_disputed_in_work_cycle
        """
        ctx = setup_engagement_in_work()
        create_dispute(ctx["case"]["id"], ctx["project"]["id"], ctx["engagement"]["id"])
        assert get_engagement(ctx["engagement"]["id"])["status"] == "DISPUTED"
        assert get_case(ctx["case"]["id"])["posture"] == "RESTRICTED"

    def test_resolution_returns_engagement_to_in_work_and_cycle_repeats(self, api):
        """PRD §3.6: "Every resolution recomputes the case `posture`, and if the
        referenced engagement was `DISPUTED`, it returns to `IN_WORK`."
        PRD §3.6: "Its creation recomputes the case's `posture`, and if the
        engagement it references is currently `IN_WORK`, that engagement is
        automatically moved to `DISPUTED`."

        Design: Difficulty/non_linear_state_machine/vendor_engagement_in_work_disputed_in_work_cycle
        """
        ctx = setup_engagement_in_work()
        dispute1 = create_dispute(
            ctx["case"]["id"], ctx["project"]["id"], ctx["engagement"]["id"]
        )
        assert get_engagement(ctx["engagement"]["id"])["status"] == "DISPUTED"
        api_client.review_dispute(dispute1["id"], UNDERWRITER)
        api_client.resolve_dispute(
            dispute1["id"], {"resolution": "RESOLVED_HOMEOWNER_FAULT"}, UNDERWRITER
        )
        assert get_engagement(ctx["engagement"]["id"])["status"] == "IN_WORK"
        # The cycle is repeatable: a second dispute re-disputes the engagement.
        create_dispute(
            ctx["case"]["id"], ctx["project"]["id"], ctx["engagement"]["id"],
            dispute_kind="COST_OVERRUN", claimed_amount_cents=100_000,
        )
        assert get_engagement(ctx["engagement"]["id"])["status"] == "DISPUTED"


class TestDisputeCascade:
    def test_dispute_cascades_to_engagement_and_case_posture(self, api):
        """PRD §3.6: "A dispute is born `OPEN`. Its creation recomputes the
        case's `posture`, and if the engagement it references is currently
        `IN_WORK`, that engagement is automatically moved to `DISPUTED`."
        PRD §2.9: "When any dispute on the case is in `OPEN` or `IN_REVIEW` but
        the market-risk indicator is not true, the posture is `RESTRICTED`."

        Design: Difficulty/transitive_cascade/dispute_cascade_engagement_case_posture
        """
        ctx = setup_engagement_in_work()
        dispute = create_dispute(
            ctx["case"]["id"], ctx["project"]["id"], ctx["engagement"]["id"]
        )
        api_client.review_dispute(dispute["id"], UNDERWRITER)
        assert get_engagement(ctx["engagement"]["id"])["status"] == "DISPUTED"
        assert get_case(ctx["case"]["id"])["posture"] == "RESTRICTED"

    def test_case_cancel_still_allowed_while_restricted(self, api):
        """PRD §3.7: "Cancellation requires the case `posture` to be anything
        other than `FROZEN`, failing with `ERR_CASE_FROZEN`"
        PRD §2.9: "When any dispute on the case is in `OPEN` or `IN_REVIEW` but
        the market-risk indicator is not true, the posture is `RESTRICTED`."

        Design: Difficulty/transitive_cascade/dispute_cascade_engagement_case_posture
        """
        ctx = setup_engagement_in_work()
        dispute = create_dispute(
            ctx["case"]["id"], ctx["project"]["id"], ctx["engagement"]["id"]
        )
        api_client.review_dispute(dispute["id"], UNDERWRITER)
        assert get_case(ctx["case"]["id"])["posture"] == "RESTRICTED"
        resp = api_client.cancel_case(ctx["case"]["id"], HOMEOWNER)
        cancelled = validate_success(resp)
        assert cancelled["status"] == "CANCELLED"


class TestPostureRecompute:
    def test_posture_restricted_on_open_dispute_and_open_after_withdraw(self, api):
        """PRD §2.9: "When any dispute on the case is in `OPEN` or `IN_REVIEW`
        but the market-risk indicator is not true, the posture is `RESTRICTED`.
        Otherwise the posture is `OPEN`."
        PRD §3.6: "The homeowner may instead withdraw a dispute while it is still
        `OPEN`, moving it to `WITHDRAWN`"

        Design: Corner/calculations/posture_recomputed_to_restricted_on_open_dispute
        """
        ctx = setup_engagement_in_work()
        dispute = create_dispute(
            ctx["case"]["id"], ctx["project"]["id"], ctx["engagement"]["id"]
        )
        assert get_case(ctx["case"]["id"])["posture"] == "RESTRICTED"
        resp = api_client.withdraw_dispute(dispute["id"], HOMEOWNER)
        validate_success(resp)
        assert get_case(ctx["case"]["id"])["posture"] == "OPEN"


class TestDisputeRoles:
    def test_vendor_cannot_resolve_dispute(self, api):
        """PRD §2.1: "A request whose role is well-formed but not authorized for
        the target endpoint is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
        PRD §3.6: "Resolution moves a dispute from `IN_REVIEW` to one of two
        terminal outcomes chosen by the underwriter's `resolution` input"

        Design: Corner/roles/vendor_cannot_create_dispute_resolution
        """
        ctx = setup_engagement_in_work()
        dispute = create_dispute(
            ctx["case"]["id"], ctx["project"]["id"], ctx["engagement"]["id"]
        )
        api_client.review_dispute(dispute["id"], UNDERWRITER)
        resp = api_client.resolve_dispute(
            dispute["id"], {"resolution": "RESOLVED_VENDOR_FAULT"},
            make_vendor_headers(ctx["vendor"]["id"]),
        )
        validate_error(resp, ERR.ERR_FORBIDDEN_FOR_ROLE)
