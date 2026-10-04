"""State machines: agent dual dimensions, document-gated activation, period and
distribution lifecycles, transfer terminal states, and the governance cycle."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_agent_payload,
    create_center,
    create_commission_event_payload,
    create_departure_payload,
    create_document_payload,
    enroll_agent,
    file_dispute,
    get_agent,
    get_success_data,
    open_period,
    add_ledger_entry,
    post_commission,
    prelim_close,
    draft_resolution,
    propose_resolution,
    ratify_resolution,
    request_transfer,
    setup_center_with_mca,
    setup_filed_dispute,
    setup_final_closed_single_sponsor_period,
    setup_two_centers_with_agent,
    validate_error,
    validate_success,
    find_distribution,
)
from test_helpers import (
    TEST_USERS,
    make_agent_headers,
    make_alc_chair_headers,
    make_market_center_admin_headers,
)

PA = TEST_USERS["platform_admin_headers"]
RD = TEST_USERS["regional_director_headers"]


class TestAgentDualStateDimensions:
    def _setup_capped(self, api):
        ctx = setup_center_with_mca()
        a1 = ctx["mca"]
        headers = make_market_center_admin_headers(a1["id"])
        v = get_agent(a1["id"])["version"]
        validate_success(api.create_commission_event(
            create_commission_event_payload(a1["id"], v, gross_commission=40000.00,
                                            occurred_on="2026-09-05T00:00:00Z",
                                            external_ref="ref-a1-1"), headers), 201)
        v = get_agent(a1["id"])["version"]
        ev2 = validate_success(api.create_commission_event(
            create_commission_event_payload(a1["id"], v, gross_commission=40000.00,
                                            occurred_on="2026-09-20T00:00:00Z",
                                            external_ref="ref-a1-2"), headers), 201)
        return ctx, a1, headers, ev2

    def test_capping_leaves_membership_untouched(self, api):
        """PRD §3.2: "A newly enrolled agent begins with membership_status
        ENROLLED_PENDING_DOCS and cap_status UNCAPPED — two independent state
        dimensions that evolve on the same row and never imply one another."
        PRD §3.5: "The agent's accrued_company_dollar advances by the event's
        company dollar, and when the resulting accrual reaches at least 20,000.00 —
        the boundary is inclusive — cap_status flips from UNCAPPED to CAPPED."

        Design: Difficulty/non_linear_state_machine/agent_parallel_membership_and_cap_dimensions
        """
        ctx, a1, headers, ev2 = self._setup_capped(api)
        agent = get_agent(a1["id"])
        assert agent["cap_status"] == "CAPPED"
        assert agent["membership_status"] == "ACTIVE", (
            "the cap dimension flips without touching membership_status"
        )

    def test_void_reverts_only_the_cap_dimension(self, api):
        """PRD §3.2: "A newly enrolled agent begins with membership_status
        ENROLLED_PENDING_DOCS and cap_status UNCAPPED — two independent state
        dimensions that evolve on the same row and never imply one another."
        PRD §3.5: "A void subtracts the event's company_dollar from the agent's
        accrued_company_dollar; if the result falls strictly below 20,000.00 while
        the agent is CAPPED, cap_status reverts to UNCAPPED."

        Design: Difficulty/non_linear_state_machine/agent_parallel_membership_and_cap_dimensions
        """
        ctx, a1, headers, ev2 = self._setup_capped(api)
        validate_success(api.void_commission_event(ev2["id"], headers), 200)
        agent = get_agent(a1["id"])
        assert agent["cap_status"] == "UNCAPPED", (
            f"CAPPED -> UNCAPPED cycle via compensation, got {agent['cap_status']}"
        )
        assert agent["accrued_company_dollar"] == pytest.approx(12000.00, abs=0.01)
        assert agent["membership_status"] == "ACTIVE", (
            "the void touched only the cap dimension"
        )


class TestDocumentGatedActivation:
    def test_sponsored_agent_waits_for_attestation(self, api):
        """PRD §3.2: "Activation is automatic. The moment the agent's document set
        contains both ICA_SIGNED and W9 — plus a SPONSOR_ATTESTATION when the agent
        has a non-null sponsor_agent_id — membership_status moves from
        ENROLLED_PENDING_DOCS to ACTIVE and the agent's version is incremented."

        Design: Corner/state_machines/sponsored_agent_activation_requires_attestation
        """
        ctx = setup_center_with_mca()
        center, mca = ctx["center"], ctx["mca"]
        s1 = enroll_agent(center["id"], sponsor_id=mca["id"], docs=False)
        # ICA + W9 only: the sponsored agent's set is still incomplete.
        get_success_data(api.create_onboarding_document(
            s1["id"], create_document_payload("ICA_SIGNED"), PA))
        get_success_data(api.create_onboarding_document(
            s1["id"], create_document_payload("W9"), PA))
        assert get_agent(s1["id"])["membership_status"] == "ENROLLED_PENDING_DOCS", (
            "a sponsored agent stays pending without the attestation"
        )
        get_success_data(api.create_onboarding_document(
            s1["id"], create_document_payload("SPONSOR_ATTESTATION",
                                              attested_sponsor_agent_id=mca["id"]), PA))
        assert get_agent(s1["id"])["membership_status"] == "ACTIVE", (
            "the SPONSOR_ATTESTATION completes the set and activates the agent"
        )


class TestDisputeStateMachine:
    def test_resolve_from_filed_rejected(self, api):
        """PRD §3.4: "Adjudication belongs to the RegionalDirector. Opening review
        moves a dispute from FILED to UNDER_REVIEW. Resolution takes an outcome of
        UPHELD, OVERTURNED, or DISMISSED, recorded in the dispute's resolution
        field, and moves the dispute to RESOLVED_UPHELD, RESOLVED_OVERTURNED, or
        DISMISSED respectively."

        Design: Corner/state_machines/dispute_resolve_from_filed_rejected
        """
        ctx = setup_filed_dispute()
        resp = api.resolve_dispute(ctx["dispute"]["id"], {"outcome": "UPHELD"}, RD)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        dispute = get_success_data(api.get_dispute(ctx["dispute"]["id"], PA))
        assert dispute["status"] == "FILED", "FILED is not a valid source state for resolve"
        assert dispute["resolution"] is None


class TestFinalClosedPeriodLockdown:
    def test_final_closed_rejects_ledger_and_prelim_close(self, api):
        """PRD §3.9: "The period lands in FINAL_CLOSED, terminal."
        PRD §3.6: "While OPEN, the period accepts ledger entries recording the
        center's costs and corrections."

        Design: Corner/state_machines/final_closed_period_terminal_lockdown
        """
        ctx = setup_final_closed_single_sponsor_period()
        period = ctx["period"]
        assert period["status"] == "FINAL_CLOSED"
        assert period["final_profit"] == pytest.approx(1500.00, abs=0.01)
        mca_headers = make_market_center_admin_headers(ctx["mca"]["id"])
        resp1 = api.create_ledger_entry(
            period["id"], {"entry_type": "EXPENSE", "amount": 10.00}, mca_headers)
        validate_error(resp1, ApiErrorId.ERR_INVALID_STATE)
        resp2 = api.preliminary_close_period(period["id"], mca_headers)
        validate_error(resp2, ApiErrorId.ERR_INVALID_STATE)
        after = get_success_data(api.get_period(period["id"], PA))
        assert after["status"] == "FINAL_CLOSED"
        assert after["final_profit"] == pytest.approx(1500.00, abs=0.01)


class TestDistributionStateMachine:
    def _setup_projection_distribution(self, api):
        center = create_center()
        mca = enroll_agent(center["id"])
        d1 = enroll_agent(center["id"], sponsor_id=mca["id"])
        post_commission(d1["id"], 5000.00, "2026-09-10T00:00:00Z", mca["id"],
                        settle=True, external_ref="ref-d1")
        period = open_period(center["id"], "2026-09", mca["id"])
        prelim_close(period["id"], mca["id"])
        return {"center": center, "mca": mca, "d1": d1, "period": period}

    def test_projection_amount_unscaled_when_pool_covers(self, api):
        """PRD §3.8: "If the gross total fits within the pool, no scaling occurs
        and the unallocated remainder stays with the center."
        PRD §3.8: "The level rates by depth are: fifty percent at level 1, ten
        percent at level 2, five percent at level 3, five percent at level 4,
        seven and a half percent at level 5, ten percent at level 6, and twelve
        and a half percent at level 7."

        Design: Corner/state_machines/distribution_markpaid_from_projection_rejected
        """
        ctx = self._setup_projection_distribution(api)
        dist = find_distribution(ctx["period"]["id"], ctx["mca"]["id"])
        assert dist["status"] == "PROJECTION"
        # Level 1: 0.50 * 1500.00 = 750.00, unscaled (pool 780.00 covers it).
        assert dist["amount"] == pytest.approx(750.00, abs=0.01)

    def test_markpaid_from_projection_rejected(self, api):
        """PRD §3.9: "Payment is a separate, deliberate act: a MarketCenterAdmin
        marks a PAYABLE distribution paid, moving it to PAID, adding the amount to
        the recipient's lifetime_profit_share (the sum of that agent's PAID
        distributions), subtracting it from pending_payable_profit_share, and
        incrementing the agent's version."

        Design: Corner/state_machines/distribution_markpaid_from_projection_rejected
        """
        ctx = self._setup_projection_distribution(api)
        dist = find_distribution(ctx["period"]["id"], ctx["mca"]["id"])
        resp = api.mark_distribution_paid(
            dist["id"], make_market_center_admin_headers(ctx["mca"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestTransferTerminalStates:
    def test_reject_is_terminal_for_approve(self, api):
        """PRD §3.11: "A MarketCenterAdmin approves or rejects a REQUESTED
        transfer; approval additionally requires the destination center to be
        ACTIVE, else ERR_CENTER_NOT_ACTIVE."

        Design: Corner/state_machines/transfer_reject_terminal_then_approve_rejected
        """
        ctx = setup_two_centers_with_agent()
        a1 = ctx["a1"]
        tr = request_transfer(a1["id"], ctx["mc2"]["id"])
        headers = make_market_center_admin_headers(a1["id"])
        rejected = validate_success(api.reject_transfer(tr["id"], headers), 200)
        assert rejected["status"] == "REJECTED"
        resp = api.approve_transfer(tr["id"], headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestCommissionEventTerminalStates:
    def test_settle_twice_rejected(self, api):
        """PRD §3.5: "A MarketCenterAdmin may settle a POSTED event (moving it to
        SETTLED, which makes it eligible for the final replay) or void it (moving
        it to VOID) — both terminal."

        Design: Corner/state_machines/commission_settle_twice_rejected
        """
        ctx = setup_center_with_mca()
        a1 = ctx["mca"]
        headers = make_market_center_admin_headers(a1["id"])
        v = get_agent(a1["id"])["version"]
        ev = validate_success(api.create_commission_event(
            create_commission_event_payload(a1["id"], v, gross_commission=1000.00,
                                            occurred_on="2026-09-05T00:00:00Z",
                                            external_ref="ref-1"), headers), 201)
        settled = validate_success(api.settle_commission_event(ev["id"], headers), 200)
        assert settled["status"] == "SETTLED"
        resp = api.settle_commission_event(ev["id"], headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestCenterSuspensionGate:
    def test_enrollment_blocked_while_suspended(self, api):
        """PRD §3.1: "Suspension is a gate, not a teardown: while a center is
        SUSPENDED, new agent enrollment into that center, creation of new
        profit-share periods for it, and approval or completion of transfers
        involving it are all blocked with ERR_CENTER_NOT_ACTIVE (HTTP 422)."

        Design: Corner/state_machines/enrollment_rejected_when_center_suspended
        """
        center = create_center()
        validate_success(api.suspend_market_center(center["id"], PA), 200)
        resp = api.create_agent(center["id"], create_agent_payload(), PA)
        validate_error(resp, ApiErrorId.ERR_CENTER_NOT_ACTIVE)
        validate_success(api.reactivate_market_center(center["id"], PA), 200)
        agent = validate_success(api.create_agent(center["id"], create_agent_payload(), PA), 201)
        assert agent["membership_status"] == "ENROLLED_PENDING_DOCS"


class TestGovernanceRejectAmendCycle:
    def _setup_draft_resolution(self, api):
        ctx = setup_center_with_mca()
        mca = ctx["mca"]
        alc = enroll_agent(ctx["center"]["id"])
        post_commission(mca["id"], 20000.00, "2026-09-10T00:00:00Z", mca["id"],
                        settle=True, external_ref="ref-1")
        period = open_period(ctx["center"]["id"], "2026-09", mca["id"])
        prelim_close(period["id"], mca["id"])
        res = draft_resolution(period["id"], mca["id"])
        return {"center": ctx["center"], "mca": mca, "alc": alc,
                "period": period, "res": res}

    def test_reject_returns_period_to_preliminary_closed(self, api):
        """PRD §3.7: "Rejection, also from PROPOSED, moves the resolution to
        REJECTED and returns the period from FINAL_CLOSE_PENDING to
        PRELIMINARY_CLOSED, reopening it for a fresh proposal; a rejected
        resolution can be amended — optionally carrying new notes — back to DRAFT
        by a MarketCenterAdmin, ready to be proposed again."

        Design: Corner/state_machines/governance_reject_amend_repropose_cycle
        """
        ctx = self._setup_draft_resolution(api)
        mca, alc = ctx["mca"], ctx["alc"]
        propose_resolution(ctx["res"]["id"], mca["id"])
        rejected = validate_success(api.reject_resolution(
            ctx["res"]["id"], make_alc_chair_headers(alc["id"])), 200)
        assert rejected["status"] == "REJECTED"
        period = get_success_data(api.get_period(ctx["period"]["id"], PA))
        assert period["status"] == "PRELIMINARY_CLOSED", (
            "rejection returns the period for a fresh proposal"
        )

    def test_amend_reopens_the_resolution_loop(self, api):
        """PRD §3.7: "Rejection, also from PROPOSED, moves the resolution to
        REJECTED and returns the period from FINAL_CLOSE_PENDING to
        PRELIMINARY_CLOSED, reopening it for a fresh proposal; a rejected
        resolution can be amended — optionally carrying new notes — back to DRAFT
        by a MarketCenterAdmin, ready to be proposed again."
        PRD §3.7: "Proposing the resolution — permitted only while the owning
        period is PRELIMINARY_CLOSED, else ERR_INVALID_STATE — moves the
        resolution from DRAFT to PROPOSED, stamps proposed_by with the acting
        user, and moves the period to FINAL_CLOSE_PENDING."

        Design: Corner/state_machines/governance_reject_amend_repropose_cycle
        """
        ctx = self._setup_draft_resolution(api)
        mca, alc = ctx["mca"], ctx["alc"]
        propose_resolution(ctx["res"]["id"], mca["id"])
        validate_success(api.reject_resolution(
            ctx["res"]["id"], make_alc_chair_headers(alc["id"])), 200)
        amended = validate_success(api.amend_resolution(
            ctx["res"]["id"], {"notes": "rework numbers"},
            make_market_center_admin_headers(mca["id"])), 200)
        assert amended["status"] == "DRAFT"
        proposed = propose_resolution(ctx["res"]["id"], mca["id"])
        assert proposed["status"] == "PROPOSED"
        period = get_success_data(api.get_period(ctx["period"]["id"], PA))
        assert period["status"] == "FINAL_CLOSE_PENDING", (
            "the amended resolution drives the period back to FINAL_CLOSE_PENDING"
        )
