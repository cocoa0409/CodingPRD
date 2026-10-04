"""Remaining corner claims: expiry, period shape, escalation and window edges."""
from test_helpers import (
    api_client,
    setup_published_failing_audit,
    TEST_USERS,
    ApiErrorId,
    conduct_audit,
    create_audit,
    create_lead,
    create_referral,
    franchisee_version,
    get_agreement,
    get_audit,
    get_franchisee,
    get_lead,
    get_referral,
    get_territory,
    make_franchisee_operator_headers,
    set_clock,
    setup_active_agreement,
    setup_two_brand_pair,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["franchise_admin_headers"]


class TestAgreementExpireBoundary:
    def test_expiring_before_the_term_end_is_refused_and_at_it_succeeds(self, api):
        """PRD §3.7: "A `FranchiseAdmin` may also cross the term end explicitly,
        but only once the logical clock is at or past `expires_on`; attempting it
        earlier is refused with `ERR_AGREEMENT_NOT_EXPIRABLE`."

        Design: Corner/state_machines/agreement_expire_before_term_end_returns_not_expirable
        """
        brand, franchisee, territory, agreement = setup_active_agreement(
            agreement={"signed_on": "2025-09-01T00:00:00Z", "initial_term_months": 12},
        )
        assert agreement["expires_on"] == "2026-09-01T00:00:00Z", (
            f"a 12-month term signed 2025-09-01T00:00:00Z expires "
            f"2026-09-01T00:00:00Z, got {agreement['expires_on']}"
        )

        set_clock("2026-08-31T23:59:59Z")
        resp = api.expire_agreement(agreement["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_EXPIRABLE)
        assert get_agreement(agreement["id"])["lifecycle_status"] == "ACTIVE", (
            "a refused expiry must leave the agreement ACTIVE"
        )

        set_clock("2026-09-01T00:00:00Z")
        resp = api.expire_agreement(agreement["id"], ADMIN)
        expired = validate_success(resp, 200)
        assert expired["lifecycle_status"] == "EXPIRED"

        stood_down = get_territory(territory["id"])
        assert stood_down["status"] == "PENDING_REALLOCATION", (
            f"expiry stands the territory down, got {stood_down['status']}"
        )
        assert stood_down["franchisee_id"] is None
        assert get_franchisee(franchisee["id"])["status"] == "TERMINATED", (
            "the franchisee's last agreement expired, so its standing terminates"
        )


class TestStatementPeriodShape:
    def test_an_inverted_period_is_refused_before_the_overlap_check(self, api):
        """PRD §3.10: "The period must be non-empty in the forward direction: a
        `period_end` at or before the `period_start` is refused with
        `ERR_INVALID_PERIOD`."

        Design: Corner/errors/statement_with_an_inverted_period_returns_invalid_period
        """
        brand, franchisee, territory, agreement = setup_active_agreement()
        resp = api.create_statement(
            {
                "agreement_id": agreement["id"],
                "period_start": "2026-10-01T00:00:00Z",
                "period_end": "2026-09-01T00:00:00Z",
                "gross_revenue_cents": 100000,
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_PERIOD)
        assert resp.json()["data"]["error_id"] != ApiErrorId.ERR_STATEMENT_PERIOD_OVERLAP.value

        rows, meta = validate_paginated(
            api.list_statements(ADMIN, {"agreement_id": agreement["id"]})
        )
        assert meta["total_count"] == 0, "no statement may have been persisted"

    def test_a_zero_width_period_is_refused_as_well(self, api):
        """PRD §3.10: "a `period_end` at or before the `period_start` is refused
        with `ERR_INVALID_PERIOD`" — a period whose ends coincide is not
        non-empty in the forward direction.

        Design: Corner/errors/statement_with_an_inverted_period_returns_invalid_period
        """
        _, _, _, agreement = setup_active_agreement()
        resp = api.create_statement(
            {
                "agreement_id": agreement["id"],
                "period_start": "2026-09-01T00:00:00Z",
                "period_end": "2026-09-01T00:00:00Z",
                "gross_revenue_cents": 100000,
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_PERIOD)


class TestRemediationEscalationWindow:
    def _submitted_remediation(self):
        _, _, _, agreement, audit = setup_published_failing_audit()
        assert audit["remediation_status"] == "OPEN"
        assert audit["remediation_due_iso"] == "2026-09-08T00:00:00Z"

        # A second audit for the same agreement serves as the verification
        # audit; it must be conducted at or before the remediation due instant.
        verification = create_audit(
            agreement["id"], audit_kind="ANNOUNCED", raw_score=95.0,
            findings_count=0, critical_findings_count=0,
            conducted_iso="2026-09-02T00:00:00Z",
        )
        conduct_audit(verification["id"])

        resp = api_client.remediation_transition(
            audit["id"],
            {"action": "SUBMIT", "verification_audit_id": verification["id"]},
            ADMIN,
        )
        submitted = validate_success(resp, 200)
        assert submitted["remediation_status"] == "SUBMITTED"
        return agreement, audit

    def test_escalating_strictly_before_the_due_instant_is_refused(self, api):
        """PRD §3.8: "A `FranchiseAdmin` may also escalate explicitly, but only
        from `SUBMITTED` and only once the logical clock has reached the
        `remediation_due_iso` — escalation attempted strictly before the due
        instant is refused with `ERR_REMEDIATION_NOT_OVERDUE`, and escalation
        exactly at the due instant is allowed."

        Design: Corner/errors/escalating_a_remediation_before_its_due_instant_returns_not_overdue
        """
        _, audit = self._submitted_remediation()

        set_clock("2026-09-07T23:59:59Z")
        resp = api.remediation_transition(audit["id"], {"action": "ESCALATE"}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_REMEDIATION_NOT_OVERDUE)
        assert get_audit(audit["id"])["remediation_status"] == "SUBMITTED", (
            "a refused escalation must leave the remediation submitted"
        )

    def test_escalating_exactly_at_the_due_instant_is_allowed(self, api):
        """PRD §3.8: "escalation attempted strictly before the due instant is
        refused with `ERR_REMEDIATION_NOT_OVERDUE`, and escalation exactly at the
        due instant is allowed."

        Design: Corner/errors/escalating_a_remediation_before_its_due_instant_returns_not_overdue
        """
        _, audit = self._submitted_remediation()

        set_clock("2026-09-08T00:00:00Z")
        resp = api.remediation_transition(audit["id"], {"action": "ESCALATE"}, ADMIN)
        escalated = validate_success(resp, 200)
        assert escalated["remediation_status"] == "ESCALATED", (
            f"the due instant itself is inside the window, got "
            f"{escalated['remediation_status']}"
        )


class TestRenewalWindowBoundary:
    def _active_agreement_expiring_2026_10_01(self):
        return setup_active_agreement(
            agreement={"signed_on": "2025-10-01T00:00:00Z", "initial_term_months": 12},
        )

    def test_an_agreement_exactly_ninety_days_out_is_not_yet_renewable(self, api):
        """PRD §3.7: "The request is refused with `ERR_RENEWAL_WINDOW_CLOSED`
        unless the agreement's `expires_on` is strictly before the logical clock
        advanced by 90 days — an agreement whose term runs longer than ninety
        days past the current clock is not yet renewable, and one that expires
        exactly ninety days out is not either."

        Design: Corner/errors/renewing_outside_the_ninety_day_window_returns_renewal_window_closed
        """
        _, franchisee, _, agreement = self._active_agreement_expiring_2026_10_01()
        assert agreement["expires_on"] == "2026-10-01T00:00:00Z"

        # Clock + 90 days is exactly the expiry instant, which is not strictly
        # before it, so the window is still closed.
        set_clock("2026-07-03T00:00:00Z")
        resp = api.renew_agreement(
            agreement["id"], make_franchisee_operator_headers(franchisee["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_RENEWAL_WINDOW_CLOSED)
        assert get_agreement(agreement["id"])["lifecycle_status"] == "ACTIVE"

    def test_inside_the_window_the_renewal_opens(self, api):
        """PRD §3.7: "Renewal is requested by the agreement's own franchisee and
        is available only inside a closing window."
        PRD §3.7: "A successful request moves the agreement from `ACTIVE` to
        `RENEWAL_PENDING` and records the instant in `renewal_clock_iso`."

        Design: Corner/errors/renewing_outside_the_ninety_day_window_returns_renewal_window_closed
        """
        _, franchisee, _, agreement = self._active_agreement_expiring_2026_10_01()

        # One day later the expiry is 89 days out, strictly inside the window.
        set_clock("2026-07-04T00:00:00Z")
        resp = api.renew_agreement(
            agreement["id"], make_franchisee_operator_headers(franchisee["id"]),
        )
        renewed = validate_success(resp, 200)
        assert renewed["lifecycle_status"] == "RENEWAL_PENDING", (
            f"89 days out is inside the window, got {renewed['lifecycle_status']}"
        )
        assert renewed["renewal_clock_iso"] == "2026-07-04T00:00:00Z"


class TestLeadHoldWindowBoundary:
    def _allocated_lead(self):
        _, franchisee, _, agreement = setup_active_agreement()
        lead = create_lead(
            agreement["brand_id"], source="CALL_CENTER",
            household_income_band="BAND_2", estimated_value_cents=120000,
        )
        allocated = validate_success(api_client.allocate_lead(
            lead["id"], franchisee_version(franchisee["id"]), ADMIN,
            allocated_agreement_id=agreement["id"],
        ), 200)
        assert allocated["allocation_hold_until_iso"] == "2026-09-02T02:00:00Z", (
            "the hold runs 26 logical hours from the allocation clock, got "
            f"{allocated['allocation_hold_until_iso']}"
        )
        return franchisee, agreement, allocated

    def test_a_release_before_the_hold_ends_is_refused(self, api):
        """PRD §3.6: "The hold window is the receiving franchisee's protected
        period: the allocation may be released only once the logical clock is
        strictly after `allocation_hold_until_iso`, so a release attempted at or
        before that instant is refused with `ERR_HOLD_WINDOW_ACTIVE`."

        Design: Corner/errors/releasing_a_lead_allocation_during_its_hold_window_returns_hold_window_active
        """
        franchisee, _, lead = self._allocated_lead()

        set_clock("2026-09-02T01:59:59Z")
        resp = api.release_lead(
            lead["id"], make_franchisee_operator_headers(franchisee["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_HOLD_WINDOW_ACTIVE)

        refused = get_lead(lead["id"])
        assert refused["status"] == "ALLOCATED"
        assert get_franchisee(franchisee["id"])["lead_cost_balance_cents"] == lead["lead_cost_cents"]
        assert lead["lead_cost_cents"] not in (0,), (
            "the lead keeps its resolved cost while the hold runs"
        )

    def test_the_boundary_instant_itself_is_still_inside_the_hold(self, api):
        """PRD §3.6: "a release attempted at or before that instant is refused
        with `ERR_HOLD_WINDOW_ACTIVE`" — the window is strictly-after, so the
        boundary instant does not release the allocation.

        Design: Corner/errors/releasing_a_lead_allocation_during_its_hold_window_returns_hold_window_active
        """
        franchisee, _, lead = self._allocated_lead()

        set_clock("2026-09-02T02:00:00Z")
        resp = api.release_lead(
            lead["id"], make_franchisee_operator_headers(franchisee["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_HOLD_WINDOW_ACTIVE)

        set_clock("2026-09-02T02:00:01Z")
        resp = api.release_lead(
            lead["id"], make_franchisee_operator_headers(franchisee["id"]),
        )
        released = validate_success(resp, 200)
        assert released["status"] == "RELEASED"
        assert get_franchisee(franchisee["id"])["lead_cost_balance_cents"] == 0


class TestReferralExpiryBoundary:
    def test_accepting_at_the_expiry_instant_is_too_late(self, api):
        """PRD §3.5: "an acceptance attempted at or after the referral's
        `expires_clock_iso` is refused with `ERR_REFERRAL_EXPIRED` — the expiry
        instant itself is already too late."

        Design: Corner/errors/accepting_a_referral_past_its_expiry_returns_referral_expired
        """
        ctx = setup_two_brand_pair()
        referral = create_referral(
            ctx["agt_a1"]["id"], ctx["agt_a2"]["id"], ctx["fr_ms"]["id"],
            estimated_job_value_cents=90000,
        )
        assert referral["expires_clock_iso"] == "2026-09-08T00:00:00Z"

        set_clock("2026-09-08T00:00:00Z")
        resp = api.accept_referral(
            referral["id"], make_franchisee_operator_headers(ctx["fr_il"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_REFERRAL_EXPIRED)

        refused = get_referral(referral["id"])
        assert refused["status"] == "PENDING", (
            f"the refusal leaves the referral pending, got {refused['status']}"
        )
        assert refused["accepted_clock_iso"] is None