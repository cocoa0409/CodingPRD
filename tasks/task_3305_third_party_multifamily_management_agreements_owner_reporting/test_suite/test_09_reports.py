"""Reports, distributions, books-locked, disposition cascade, ledger filtering (PRD §3.6–§3.8)."""
from test_helpers import (
    ApiErrorId,
    get_success_data,
    make_owner_rep_headers,
    open_statement,
    post_ledger_entry,
    set_clock,
    setup_managed_property,
    setup_owner,
    setup_property,
    start_onboarding,
    setup_resident,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import TEST_USERS

PM = TEST_USERS["pm_headers"]
ACCT = TEST_USERS["acct_headers"]
RISK = TEST_USERS["risk_headers"]


def _setup_closed_statement_with_report(api, rent_cents, day=10,
                                        legal_name="Rep Owner LP",
                                        property_name="Rep Property"):
    """Managed property, one RENT row for 2026-09, statement + DRAFT
    MONTHLY_OWNER report, clock at 2026-10-01. Returns (fx, statement, report)."""
    fx = setup_managed_property(legal_name=legal_name, property_name=property_name,
                                unit_count=20, distribution_day_of_month=day)
    prop, resident = fx["prop"], fx["resident"]
    post_ledger_entry(prop, "RENT", rent_cents, "2026-09",
                      collected_month="2026-09", resident_id=resident["id"])
    st = open_statement(prop, period_month="2026-09", basis="CASH")
    rp = get_success_data(
        api.create_report(
            prop["id"], {"period_month": "2026-09", "package_type": "MONTHLY_OWNER"},
            ACCT,
        )
    )
    set_clock("2026-10-01T00:00:00Z")
    return fx, st, rp


class TestStatementCloseCascade:
    def test_statement_close_cascades_to_report_generation_depth2(self, api, acct_headers):
        """PRD §3.6: "On close, the computed fields freeze, and two cascades
        fire: the property's cash available is reduced by the management fee
        total plus the payroll charge (the manager is paid), and any `DRAFT`
        `OwnerReportPackage` for the same property and period becomes
        `GENERATED` with its distribution computed as described in §3.8."

        Design: Difficulty/transitive_cascade/statement_close_cascades_to_report_generation_depth2
        """
        fx, st, rp = _setup_closed_statement_with_report(
            api, 9600000, legal_name="Cascade Owner LP",
            property_name="Cascade Property",
        )
        closed = validate_success(api.close_statement(st["id"], acct_headers))
        assert closed["status"] == "CLOSED"
        assert closed["management_fee_total_cents"] == 384000

        rp_after = validate_success(api.get_report(rp["id"], acct_headers))
        assert rp_after["status"] == "GENERATED", (
            "DRAFT package must flip to GENERATED via the close cascade"
        )
        # Waterfall: cash 9216000 after fees; floor 20000000 clamps to zero.
        assert rp_after["distribution_amount_cents"] == 0, (
            f"floor must clamp the distribution to zero, got {rp_after['distribution_amount_cents']}"
        )

    def test_statement_close_cascade_distribution_above_floor(self, api, acct_headers):
        """PRD §3.8: "The distribution is then cash available minus the floor,
        minus the holdback, minus the claim holds — never less than zero, so
        the floor can never be breached by a distribution."

        Design: Difficulty/transitive_cascade/statement_close_cascades_to_report_generation_depth2
        """
        # Cash 60000000; fees 0.04*60000000 == 2400000; incentive
        # round(0.10*(60000000-12000000)) == 4800000; total fees 7200000;
        # cash after fees 52800000; distribution 52800000 - 20000000 == 32800000.
        fx, st, rp = _setup_closed_statement_with_report(
            api, 60000000, legal_name="Cascade2 Owner LP",
            property_name="Cascade2 Property",
        )
        closed = validate_success(api.close_statement(st["id"], acct_headers))
        assert closed["base_fee_cents"] == 2400000
        assert closed["incentive_fee_cents"] == 4800000
        assert closed["management_fee_total_cents"] == 7200000

        rp_after = validate_success(api.get_report(rp["id"], acct_headers))
        assert rp_after["status"] == "GENERATED"
        assert rp_after["distribution_amount_cents"] == 32800000


class TestDistributionGraceWindow:
    def test_error_distribution_window_missed_after_grace(self, api, acct_headers):
        """PRD §3.8: "for `MONTHLY_OWNER` packages, the logical clock's day of
        month must be no later than the owner's `distribution_day_of_month`
        plus a five-day grace — delivery inside the grace window is permitted,
        delivery past it is rejected with
        `ERR_DISTRIBUTION_WINDOW_MISSED`."

        Design: Corner/errors/error_distribution_window_missed_after_grace
        """
        fx, st, rp = _setup_closed_statement_with_report(
            api, 5000000, day=10, legal_name="Grace Owner LP",
            property_name="Grace Property",
        )
        get_success_data(api.close_statement(st["id"], acct_headers))

        # Grace ends on day 15 (10 + 5); delivery on day 16 is too late.
        set_clock("2026-10-16T00:00:00Z")
        resp = api.deliver_report(rp["id"], acct_headers)
        validate_error(resp, ApiErrorId.ERR_DISTRIBUTION_WINDOW_MISSED)
        after = validate_success(api.get_report(rp["id"], acct_headers))
        assert after["status"] == "GENERATED"


class TestBooksLocked:
    def test_restate_blocked_once_report_delivered(self, api, acct_headers):
        """PRD §3.6: "From `CLOSED`, a `PropertyAccountant` may restate a
        statement only while the period's books are not owner-locked: once any
        `OwnerReportPackage` for the same property and period has been
        `DELIVERED`, restatement is rejected with `ERR_BOOKS_LOCKED`. A
        permitted restatement leaves the statement in `CLOSED` but recomputes
        every computed field from the current ledger state — prior computed
        values are superseded — and increments the statement's `version` by
        one."

        Design: Corner/validations/restate_blocked_once_report_delivered
        """
        fx, st, rp = _setup_closed_statement_with_report(
            api, 5000000, day=28, legal_name="Lock2 Owner LP",
            property_name="Lock2 Property",
        )
        closed = validate_success(api.close_statement(st["id"], acct_headers))
        v_closed = closed["version"]

        restated = validate_success(api.restate_statement(st["id"], acct_headers))
        assert restated["version"] == v_closed + 1, (
            "restatement must increment the statement version by one"
        )
        assert restated["status"] == "CLOSED"

        set_clock("2026-10-10T00:00:00Z")  # within grace (28 + 5)
        get_success_data(api.deliver_report(rp["id"], acct_headers))

        resp = api.restate_statement(st["id"], acct_headers)
        validate_error(resp, ApiErrorId.ERR_BOOKS_LOCKED)


class TestDispositionCascade:
    def test_disposition_listing_to_termination_cascade_depth3(self, api, pm_headers, acct_headers):
        """PRD §3.7: "Completion closes the property (`status` `CLOSED`,
        posture `DISPOSED`) and immediately moves the agreement from
        `TERMINATION_PENDING` to `TERMINATED` — a shortcut past the normal
        completion gates, though the tail is still invoiced when the computed
        fee tail is greater than zero."; PRD §3.7: "every `VendorContract` in
        `ASSIGNED_TO_MANAGER` for the property cascades to `TERMINATED`".

        Design: Difficulty/transitive_cascade/disposition_listing_to_termination_cascade_depth3
        """
        fx = setup_managed_property(
            legal_name="Dispo Owner LP", property_name="Dispo Property",
            unit_count=150, tail_months=3, tail_rate_pct=0.50,
        )
        owner, prop, ag = fx["owner"], fx["prop"], fx["agreement"]
        hdrs = make_owner_rep_headers(owner["id"])

        # One vendor contract resolved ASSIGNED_TO_MANAGER (a second contract
        # may be registered and resolved while the property is managed).
        v = get_success_data(
            api.create_vendor_contract(
                prop["id"],
                {"vendor_name": "LiftCo", "service_type": "ELEVATOR",
                 "monthly_cost_cents": 50000,
                 "start_date": "2026-08-01T00:00:00Z",
                 "end_date": "2027-07-31T00:00:00Z"},
                acct_headers,
            )
        )
        get_success_data(
            api.resolve_vendor_contract(v["id"], {"resolution": "ASSIGNED_TO_MANAGER"}, acct_headers)
        )

        get_success_data(api.list_for_disposition(prop["id"], hdrs))
        term = get_success_data(
            api.terminate_agreement(ag["id"], {"terminated_reason": "DISPOSITION"}, hdrs)
        )
        tail = term["termination_fee_tail_cents"]
        # No CLOSED statements exist -> tail is 0 per the fee-tail rule.
        assert tail == 0

        done = validate_success(api.complete_disposition(prop["id"], hdrs))
        assert done["status"] == "CLOSED"
        assert done["management_posture"] == "DISPOSED"

        ag_after = validate_success(api.get_agreement(ag["id"], pm_headers))
        assert ag_after["status"] == "TERMINATED", (
            "disposition completion drives the agreement TERMINATION_PENDING -> TERMINATED"
        )
        v_after = validate_success(api.get_vendor_contract(v["id"], acct_headers))
        assert v_after["assignment_status"] == "TERMINATED", (
            "ASSIGNED_TO_MANAGER contracts cascade to TERMINATED on agreement termination"
        )

    def test_disposition_requires_pending_disposition_termination(self, api, pm_headers):
        """PRD §3.7: "Completing the disposition requires
        `disposition_listed_at` to be set and the property's agreement to be
        sitting in `TERMINATION_PENDING` with `terminated_reason`
        `DISPOSITION` — both failures surface as
        `ERR_INVALID_STATE_TRANSITION`."

        Design: Difficulty/transitive_cascade/disposition_listing_to_termination_cascade_depth3
        """
        fx = setup_managed_property(legal_name="Dispo2 Owner LP",
                                    property_name="Dispo2 Property", unit_count=150)
        owner, prop = fx["owner"], fx["prop"]
        hdrs = make_owner_rep_headers(owner["id"])

        # Property listed but agreement not terminated -> completion rejected.
        get_success_data(api.list_for_disposition(prop["id"], hdrs))
        resp = api.complete_disposition(prop["id"], hdrs)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)


class TestLedgerFiltering:
    def test_filtered_list_supports_fk_filter(self, api, pm_headers, acct_headers):
        """PRD §3.6: "Entries are listed per property or top-level, filterable
        by `resident_id`, `kind`, `status`, `accrual_month`, and
        `collected_month`."

        Design: Corner/endpoints/filtered_list_supports_fk_filter
        """
        owner = setup_owner(legal_name="Q Owner LP")
        prop = setup_property(owner, name="Q Property", unit_count=10)
        start_onboarding(prop, takeover_date="2026-09-01T00:00:00Z")
        resident = setup_resident(prop, unit_label="Q1", full_name="Res Q",
                                  lease_end_date="2027-08-31T00:00:00Z")
        post_ledger_entry(prop, "RENT", 100000, "2026-09",
                          collected_month="2026-09", resident_id=resident["id"])
        post_ledger_entry(prop, "RENT", 100000, "2026-09",
                          collected_month="2026-09", resident_id=resident["id"])
        post_ledger_entry(prop, "EXPENSE", 50000, "2026-09",
                          collected_month="2026-09")

        expenses, meta_e = validate_paginated(
            api.list_property_ledger_entries(prop["id"], acct_headers,
                                             params={"kind": "EXPENSE"})
        )
        assert len(expenses) == 1
        assert expenses[0]["amount_cents"] == 50000
        assert expenses[0]["kind"] == "EXPENSE"

        rents, _ = validate_paginated(
            api.list_property_ledger_entries(prop["id"], acct_headers,
                                             params={"kind": "RENT"})
        )
        assert len(rents) == 2

        all_rows, meta_all = validate_paginated(
            api.list_property_ledger_entries(prop["id"], acct_headers)
        )
        assert len(all_rows) == 3


class TestRbacLedger:
    def test_riskofficer_cannot_post_ledger_entries(self, api, pm_headers, acct_headers):
        """PRD §2.1: "`PropertyAccountant` is the manager-side operator: it
        runs onboarding data, ledger, and vendor steps; ... posts ledger
        entries". PRD §2.1: "An attempt to perform an operation outside the
        caller's role is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."

        Design: Corner/rbac/riskofficer_cannot_post_ledger_entries
        """
        owner = setup_owner(legal_name="R2 Owner LP")
        prop = setup_property(owner, name="R2 Property", unit_count=10)
        start_onboarding(prop, takeover_date="2026-09-01T00:00:00Z")
        resident = setup_resident(prop, unit_label="R1", full_name="Res R",
                                  lease_end_date="2027-08-31T00:00:00Z")

        resp = api.create_ledger_entry(
            prop["id"],
            {"resident_id": resident["id"], "kind": "RENT", "amount_cents": 100000,
             "accrual_month": "2026-09", "collected_month": "2026-09"},
            RISK,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
