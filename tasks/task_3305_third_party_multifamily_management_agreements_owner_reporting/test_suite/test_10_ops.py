"""Auth, RBAC denials, cascades, OCC round-trips, and the annual NOI settlement (PRD §2.1, §2.10, §3.2, §3.6)."""
from test_helpers import (
    ApiErrorId,
    create_budget_payload,
    get_success_data,
    make_owner_rep_headers,
    open_statement,
    post_ledger_entry,
    set_clock,
    setup_managed_property,
    setup_owner,
    setup_property,
    validate_error,
    validate_success,
)
from test_helpers.test_users import TEST_USERS

PM = TEST_USERS["pm_headers"]
ACCT = TEST_USERS["acct_headers"]


class TestAuthHeaderPriority:
    def test_auth_header_missing_beats_role_check(self, api):
        """PRD §2.1: "A request in which either header is missing or malformed
        is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`
        (HTTP 400) before any other processing."

        Design: Corner/validations/auth_header_missing_beats_role_check
        """
        resp = api.create_owner(
            {"legal_name": "NoHdr LP"},
            {"Content-Type": "application/json"},  # neither auth header present
        )
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


class TestExistenceLeftToRight:
    def test_existence_check_left_to_right_owner_before_property(self, api, pm_headers):
        """PRD §2.6: "Requests that target nested resources validate path
        identifiers sequentially, left to right: the owner first, then the
        property or agreement, then the child resource. The request is
        rejected immediately with `ERR_NOT_FOUND` (HTTP 404) for the first
        identifier in the path that does not correspond to an existing
        resource, and no later identifier is examined."

        Design: Corner/validations/existence_check_left_to_right_owner_before_property
        """
        resp = api.create_property(
            "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2",
            {"name": "Ghost", "unit_count": 10},
            pm_headers,
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestSuspendStaffCascade:
    def test_agreement_suspend_resume_loop_toggles_staffing(self, api, pm_headers):
        """PRD §3.2: "Suspension moves the agreement to `SUSPENDED`, increments
        its `version`, and cascades down to staffing: every `StaffPosition`
        row for the property flips to `INACTIVE`. Resuming a `SUSPENDED`
        agreement returns it to `ACTIVE`, increments `version` again, and
        performs the compensation cascade — the positions that suspension
        pushed to `INACTIVE` return to `ACTIVE`."

        Design: Difficulty/non_linear_state_machine/agreement_suspend_resume_loop_toggles_staffing
        """
        fx = setup_managed_property(legal_name="Loop Owner LP",
                                    property_name="Loop Property", unit_count=60)
        prop, ag = fx["prop"], fx["agreement"]
        sp = get_success_data(
            api.create_staff(
                prop["id"],
                {"role_title": "LEASING_AGENT", "hourly_cost_cents": 2500,
                 "scheduled_hours_per_week": 40, "shared_region_code": "R2"},
                PM,
            )
        )

        suspended = validate_success(api.suspend_agreement(ag["id"], pm_headers))
        assert suspended["status"] == "SUSPENDED"
        sp_susp = validate_success(api.get_staff(sp["id"], pm_headers))
        assert sp_susp["status"] == "INACTIVE", (
            "suspend must cascade the property's staff positions to INACTIVE"
        )

        resumed = validate_success(api.resume_agreement(ag["id"], pm_headers))
        assert resumed["status"] == "ACTIVE"
        sp_res = validate_success(api.get_staff(sp["id"], pm_headers))
        assert sp_res["status"] == "ACTIVE", (
            "resume must restore suspension-inactivated positions to ACTIVE"
        )

    def test_agreement_suspend_resume_second_loop_toggles_staffing(self, api, pm_headers):
        """PRD §3.2: "Suspension moves the agreement to `SUSPENDED`, increments
        its `version`, and cascades down to staffing: every `StaffPosition`
        row for the property flips to `INACTIVE`. Resuming a `SUSPENDED`
        agreement returns it to `ACTIVE`, increments `version` again, and
        performs the compensation cascade — the positions that suspension
        pushed to `INACTIVE` return to `ACTIVE`."

        Design: Difficulty/non_linear_state_machine/agreement_suspend_resume_loop_toggles_staffing
        """
        fx = setup_managed_property(legal_name="Loop2 Owner LP",
                                    property_name="Loop2 Property", unit_count=60)
        prop, ag = fx["prop"], fx["agreement"]
        sp = get_success_data(
            api.create_staff(
                prop["id"],
                {"role_title": "MAINTENANCE_TECH", "hourly_cost_cents": 2800,
                 "scheduled_hours_per_week": 40, "shared_region_code": "R3"},
                PM,
            )
        )
        # Two passes through the loop must each track staffing exactly.
        for _ in range(2):
            get_success_data(api.suspend_agreement(ag["id"], pm_headers))
            sp_susp = validate_success(api.get_staff(sp["id"], pm_headers))
            assert sp_susp["status"] == "INACTIVE"
            get_success_data(api.resume_agreement(ag["id"], pm_headers))
            sp_res = validate_success(api.get_staff(sp["id"], pm_headers))
            assert sp_res["status"] == "ACTIVE"
        final = validate_success(api.get_agreement(ag["id"], pm_headers))
        assert final["status"] == "ACTIVE"


class TestCascadeImmediateConsistency:
    def test_cascade_side_effect_suspend_propagates_to_staff_within_one_request(self, api, pm_headers):
        """PRD §3.2: "Suspension moves the agreement to `SUSPENDED`, increments
        its `version`, and cascades down to staffing: every `StaffPosition`
        row for the property flips to `INACTIVE`."

        Design: Corner/cross_cutting/cascade_side_effect_suspend_propagates_to_staff_within_one_request
        """
        fx = setup_managed_property(legal_name="K Owner LP",
                                    property_name="K Property", unit_count=10)
        prop, ag = fx["prop"], fx["agreement"]
        sp = get_success_data(
            api.create_staff(
                prop["id"],
                {"role_title": "MAINTENANCE_TECH", "hourly_cost_cents": 2800,
                 "scheduled_hours_per_week": 40, "shared_region_code": "RK"},
                PM,
            )
        )
        suspended = validate_success(api.suspend_agreement(ag["id"], pm_headers))
        assert suspended["status"] == "SUSPENDED"
        # Immediate read-after-write: no wait, the cascade is already visible.
        sp_after = validate_success(api.get_staff(sp["id"], pm_headers))
        assert sp_after["status"] == "INACTIVE"


class TestAnnualNoiIncentive:
    def _run_fiscal_year(self, api, monthly_expense_last=533337):
        """Twelve CLOSED CASH statements for 2026 (1,000,000 RENT and 533,333
        EXPENSE each month, December expense 533,337) then the December epoch
        advance. Returns (fx, budgets, advance_response)."""
        fx = setup_managed_property(
            legal_name="NOI Owner LP", property_name="NOI Property", unit_count=300,
            takeover_date="2025-12-01T00:00:00Z",
            effective_date="2025-12-01T00:00:00Z",
            term_end_date="2027-11-30T00:00:00Z",
            lease_end_date="2027-11-30T00:00:00Z",
            noi_hurdle_pct=0.08, incentive_noi_share_pct=0.20,
        )
        owner, prop, resident = fx["owner"], fx["prop"], fx["resident"]
        hdrs = make_owner_rep_headers(owner["id"])

        # APPROVED ANNUAL budget for fiscal 2026: NOI 5,000,000.
        b = get_success_data(
            api.create_budget(
                {"property_id": prop["id"], "fiscal_year": 2026, "kind": "ANNUAL",
                 "operating_revenue_cents": 12000000,
                 "operating_expense_cents": 7000000, "capex_total_cents": 1000000},
                ACCT,
            )
        )
        get_success_data(api.submit_budget(b["id"], ACCT))
        get_success_data(api.approve_budget(b["id"], hdrs))

        months = [f"2026-{m:02d}" for m in range(1, 13)]
        for i, month in enumerate(months):
            # Move the clock into the FOLLOWING month so the statement can close.
            year, mon = 2026, i + 1
            nxt_year, nxt_mon = (year, mon + 1) if mon < 12 else (year + 1, 1)
            set_clock(f"{nxt_year}-{nxt_mon:02d}-01T00:00:00Z")
            post_ledger_entry(prop, "RENT", 1000000, month,
                              collected_month=month, resident_id=resident["id"])
            expense = monthly_expense_last if month == "2026-12" else 533333
            post_ledger_entry(prop, "EXPENSE", expense, month,
                              collected_month=month)
            st = open_statement(prop, period_month=month, basis="CASH")
            get_success_data(api.close_statement(st["id"], ACCT))
        return fx

    def test_annual_noi_incentive_zero_when_below_hurdle(self, api, pm_headers):
        """PRD §3.6: "if actual NOI exceeds that rounded hurdle, the annual
        incentive is the agreement's `incentive_noi_share_pct` applied to the
        excess of actual NOI over the rounded hurdle, rounded half-up to whole
        cents; otherwise it is zero."

        Design: Difficulty/combinatorial_formula/annual_noi_incentive_mode_c_pinned_evaluation_order
        """
        fx = setup_managed_property(
            legal_name="NOI2 Owner LP", property_name="NOI2 Property", unit_count=300,
            takeover_date="2025-12-01T00:00:00Z",
            effective_date="2025-12-01T00:00:00Z",
            term_end_date="2027-11-30T00:00:00Z",
            lease_end_date="2027-11-30T00:00:00Z",
            noi_hurdle_pct=0.08, incentive_noi_share_pct=0.20,
        )
        owner, prop, resident = fx["owner"], fx["prop"], fx["resident"]
        hdrs = make_owner_rep_headers(owner["id"])
        b = get_success_data(
            api.create_budget(
                {"property_id": prop["id"], "fiscal_year": 2026, "kind": "ANNUAL",
                 "operating_revenue_cents": 12000000,
                 "operating_expense_cents": 7000000, "capex_total_cents": 1000000},
                ACCT,
            )
        )
        get_success_data(api.submit_budget(b["id"], ACCT))
        get_success_data(api.approve_budget(b["id"], hdrs))

        # Actual NOI exactly 5,000,000 (== budget NOI, below the hurdle):
        # revenue 12,000,000; expenses 7,000,000 across the year.
        for i in range(1, 13):
            month = f"2026-{i:02d}"
            nxt_year, nxt_mon = (2026, i + 1) if i < 12 else (2027, 1)
            set_clock(f"{nxt_year}-{nxt_mon:02d}-01T00:00:00Z")
            post_ledger_entry(prop, "RENT", 1000000, month,
                              collected_month=month, resident_id=resident["id"])
            expense = 583337 if month == "2026-12" else 583333
            post_ledger_entry(prop, "EXPENSE", expense, month,
                              collected_month=month)
            st = open_statement(prop, period_month=month, basis="CASH")
            get_success_data(api.close_statement(st["id"], ACCT))

        resp = api.advance_month(pm_headers)
        assert resp.status_code < 300, (
            f"December epoch advance must succeed, got {resp.status_code}: {resp.text}"
        )
        body = resp.json().get("data", {})
        # actual_noi 12000000 - 7000000 == 5000000 <= hurdle 5400000 -> zero.
        assert body.get("annual_noi_incentive") in (0, None), (
            f"below-hurdle year must yield zero annual incentive; got {body!r}"
        )
