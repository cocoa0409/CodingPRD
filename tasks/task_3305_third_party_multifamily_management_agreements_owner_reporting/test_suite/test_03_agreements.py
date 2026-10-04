"""Agreement lifecycle: invalid transitions, terminal lockdown, expiry (PRD §3.2, §3.7)."""
from test_helpers import (
    ApiErrorId,
    get_success_data,
    make_owner_rep_headers,
    set_clock,
    setup_active_agreement,
    setup_draft_agreement,
    setup_managed_property,
    setup_owner,
    setup_property,
    validate_error,
    validate_success,
)


class TestTerminateFromDraft:
    def test_terminate_from_draft_is_invalid_transition(self, api, pm_headers):
        """PRD §3.7: "An `OwnerRep` initiates termination of an `ACTIVE`
        agreement by supplying a `terminated_reason`"; PRD §3.7: "Initiation
        requires the property's `management_posture` to be `MANAGED`
        (otherwise `ERR_INVALID_STATE_TRANSITION`)".

        Design: Corner/state_machines/terminate_from_draft_is_invalid_transition
        """
        owner = setup_owner(legal_name="Term Owner LP")
        prop = setup_property(owner, name="Term Property", unit_count=25)
        ag = setup_draft_agreement(owner, prop)

        resp = api.terminate_agreement(
            ag["id"],
            {"terminated_reason": "CONVENIENCE"},
            make_owner_rep_headers(owner["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

        after = validate_success(api.get_agreement(ag["id"], pm_headers))
        assert after["status"] == "DRAFT"
        assert after["termination_fee_tail_cents"] == 0


class TestTerminalLockdown:
    def test_terminated_agreement_is_terminal_no_further_transitions(self, api, pm_headers):
        """PRD §3.2: "The agreement begins in `DRAFT`, and its full state
        vocabulary is `DRAFT`, `ACTIVE`, `SUSPENDED`, `TERMINATION_PENDING`,
        `TERMINATED`, and `EXPIRED`, with `TERMINATED` and `EXPIRED`
        terminal."

        Design: Corner/state_machines/terminated_agreement_is_terminal_no_further_transitions
        """
        fx = setup_managed_property(legal_name="Lock Owner LP",
                                    property_name="Lock Property", unit_count=25)
        owner, ag = fx["owner"], fx["agreement"]
        hdrs = make_owner_rep_headers(owner["id"])
        get_success_data(
            api.terminate_agreement(ag["id"], {"terminated_reason": "CAUSE"}, hdrs)
        )
        done = get_success_data(api.complete_termination(ag["id"], pm_headers))
        assert done["status"] == "TERMINATED"

        r1 = api.suspend_agreement(ag["id"], pm_headers)
        validate_error(r1, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        r2 = api.resume_agreement(ag["id"], pm_headers)
        validate_error(r2, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        r3 = api.terminate_agreement(
            ag["id"], {"terminated_reason": "CAUSE"}, hdrs
        )
        validate_error(r3, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

        after = validate_success(api.get_agreement(ag["id"], pm_headers))
        assert after["status"] == "TERMINATED"


class TestAgreementExpiry:
    def test_expired_agreement_auto_transition_at_advance_month(self, api, pm_headers):
        """PRD §3.7: "Expiry is the clock-driven ending: when the logical clock
        reaches an `ACTIVE` agreement's `term_end_date` during month advance,
        the agreement moves to `EXPIRED`, the property's posture returns to
        `UNMANAGED`, and no fee tail accrues."

        Design: Corner/state_machines/expired_agreement_auto_transition_at_advance_month
        """
        fx = setup_managed_property(
            legal_name="Expiry Owner LP",
            property_name="Expiry Property",
            unit_count=15,
            takeover_date="2026-01-01T00:00:00Z",
            effective_date="2026-01-01T00:00:00Z",
            term_end_date="2026-09-30T00:00:00Z",
            lease_end_date="2026-12-31T00:00:00Z",
        )
        prop, ag = fx["prop"], fx["agreement"]
        set_clock("2026-10-01T00:00:00Z")
        get_success_data(api.advance_month(pm_headers))

        after = validate_success(api.get_agreement(ag["id"], pm_headers))
        assert after["status"] == "EXPIRED"
        assert after["termination_fee_tail_cents"] == 0, (
            "EXPIRY accrues no fee tail"
        )
        prop_after = validate_success(api.get_property(prop["id"], pm_headers))
        assert prop_after["management_posture"] == "UNMANAGED"


class TestSuspendBlockedByPendingBudget:
    def test_error_pending_owner_decision_blocks_suspend(self, api, pm_headers, acct_headers):
        """PRD §3.2: "A `PortfolioManager` may suspend an `ACTIVE` agreement —
        but only when no `Budget` for the property is sitting in `SUBMITTED`
        awaiting the owner's decision; if one is, the suspension is rejected
        with `ERR_PENDING_OWNER_DECISION`."

        Design: Corner/errors/error_pending_owner_decision_blocks_suspend
        """
        fx = setup_managed_property(legal_name="Pend Owner LP",
                                    property_name="Pend Property", unit_count=20)
        owner, prop, ag = fx["owner"], fx["prop"], fx["agreement"]
        hdrs = make_owner_rep_headers(owner["id"])

        b = get_success_data(
            api.create_budget(
                {
                    "property_id": prop["id"],
                    "fiscal_year": 2027,
                    "kind": "ANNUAL",
                    "operating_revenue_cents": 3000000,
                    "operating_expense_cents": 2000000,
                    "capex_total_cents": 100000,
                },
                acct_headers,
            )
        )
        get_success_data(api.submit_budget(b["id"], acct_headers))

        resp = api.suspend_agreement(ag["id"], pm_headers)
        validate_error(resp, ApiErrorId.ERR_PENDING_OWNER_DECISION)

        get_success_data(api.reject_budget(b["id"], hdrs))
        suspended = validate_success(api.suspend_agreement(ag["id"], pm_headers))
        assert suspended["status"] == "SUSPENDED"


class TestOccAgreementActivate:
    def test_occ_stale_version_on_agreement_activate(self, api, pm_headers):
        """PRD §2.8: "Activating a draft agreement requires
        `expected_agreement_version`, carrying the `version` of the
        `ManagementAgreement` the client last read. If another writer has
        advanced the agreement's version since that read — terms amended,
        state changed — the activation is rejected with `ERR_STALE_VERSION`
        (HTTP 412), so activation never proceeds on outdated terms."

        Design: Corner/cross_cutting/occ_stale_version_on_agreement_activate
        """
        owner = setup_owner(legal_name="OCC Owner LP")
        prop = setup_property(owner, name="OCC Property", unit_count=10)
        ag = setup_draft_agreement(owner, prop)
        current_v = ag["version"]

        stale = api.activate_agreement(
            ag["id"], {"expected_agreement_version": current_v - 1}, pm_headers
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

        fresh = validate_success(
            api.activate_agreement(
                ag["id"], {"expected_agreement_version": current_v}, pm_headers
            )
        )
        assert fresh["status"] == "ACTIVE"
        assert fresh["version"] == current_v + 1


class TestFeeTail:
    def test_fee_tail_averages_recent_closed_statements_only(self, api, pm_headers, acct_headers):
        """PRD §3.7: "the system looks back over the six most recent `CLOSED`
        monthly statements for the property ordered by `period_month`
        descending (averaging over however many exist when fewer than six are
        available, and producing a tail of zero when none exist), takes the
        mean of their `base_fee_cents` rounded half-up to whole cents, and
        multiplies that average by the agreement's `tail_rate_pct` and its
        `tail_months`, rounding half-up to whole cents. On `CAUSE` or `EXPIRY`
        the tail is zero regardless of the formula."

        Design: Corner/calculations/fee_tail_averages_recent_closed_statements_only
        """
        tails = {}
        for name, reason in (("Tail A", "CONVENIENCE"), ("Tail B", "CAUSE")):
            fx = setup_managed_property(
                legal_name="Tail Owner LP",
                property_name=name,
                unit_count=20,
                takeover_date="2026-07-01T00:00:00Z",
                effective_date="2026-07-01T00:00:00Z",
                term_end_date="2027-06-30T00:00:00Z",
                lease_end_date="2027-06-30T00:00:00Z",
                tail_months=3,
                tail_rate_pct=0.50,
            )
            owner, prop, ag = fx["owner"], fx["prop"], fx["agreement"]
            # Two CLOSED min-fee statements (no revenue rows -> floor 250000).
            s1 = get_success_data(
                api.create_statement(
                    prop["id"], {"period_month": "2026-08", "basis": "CASH"}, acct_headers
                )
            )
            set_clock("2026-09-01T00:00:00Z")
            get_success_data(api.close_statement(s1["id"], acct_headers))
            s2 = get_success_data(
                api.create_statement(
                    prop["id"], {"period_month": "2026-09", "basis": "CASH"}, acct_headers
                )
            )
            set_clock("2026-10-01T00:00:00Z")
            get_success_data(api.close_statement(s2["id"], acct_headers))

            term = get_success_data(
                api.terminate_agreement(
                    ag["id"],
                    {"terminated_reason": reason},
                    make_owner_rep_headers(owner["id"]),
                )
            )
            tails[reason] = term["termination_fee_tail_cents"]

        assert tails["CONVENIENCE"] == 375000, (
            f"avg(250000, 250000) * 0.50 * 3 must be 375000, got {tails['CONVENIENCE']}"
        )
        assert tails["CAUSE"] == 0, "CAUSE termination accrues no tail"
