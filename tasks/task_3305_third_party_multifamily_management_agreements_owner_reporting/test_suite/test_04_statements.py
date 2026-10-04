"""Statements and fee computation: dual basis, floors, filtering, preview (PRD §3.6)."""
from test_helpers import (
    ApiErrorId,
    get_success_data,
    open_statement,
    post_ledger_entry,
    set_clock,
    setup_managed_property,
    setup_owner,
    setup_property,
    start_onboarding,
    setup_resident,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import drive_onboarding_to_ready


def _managed_with_rent(rent_cents, period="2026-09", close_clock="2026-10-01T00:00:00Z",
                       legal_name="Fee Owner LP", property_name="Fee Property",
                       unit_count=20):
    """Managed property with one RENT row collected in `period` and an OPEN
    CASH statement, clock moved past month end. Returns (fx, statement)."""
    fx = setup_managed_property(
        legal_name=legal_name, property_name=property_name, unit_count=unit_count
    )
    post_ledger_entry(fx["prop"], "RENT", rent_cents, period,
                      collected_month=period, resident_id=fx["resident"]["id"])
    st = open_statement(fx["prop"], period_month=period, basis="CASH")
    set_clock(close_clock)
    return fx, st


class TestMinimumFeeFloor:
    def test_minimum_fee_floor_binds_below_threshold(self, api, acct_headers):
        """PRD §3.6: "The base fee is then `base_fee_cents`, the greater of the
        agreement's `minimum_monthly_fee_cents` and the agreement's
        `base_fee_pct` multiplied by that revenue, the multiplication rounded
        half-up to whole cents exactly once (the percentage itself is never
        rounded)."

        Design: Corner/calculations/minimum_fee_floor_binds_below_threshold
        """
        fx, st = _managed_with_rent(3000000, legal_name="Floor Owner LP",
                                    property_name="Floor Property")
        closed = validate_success(api.close_statement(st["id"], acct_headers))
        # round(0.04 * 3000000) == 120000 < floor 250000 -> floor binds.
        assert closed["base_fee_cents"] == 250000, (
            f"floor must bind at 250000, got {closed['base_fee_cents']}"
        )
        assert closed["incentive_fee_cents"] == 0
        assert closed["collected_revenue_cents"] == 3000000


class TestRevenueInputSet:
    def test_statement_revenue_excludes_expense_payroll_and_void_rows(self, api, acct_headers):
        """PRD §2.9: "Six kinds of entry exist — `RENT`, `FEE`, `RECOVERY`,
        `CONCESSION`, `EXPENSE`, and `PAYROLL` — and only `RENT`, `FEE`, and
        `RECOVERY` count toward revenue, with `CONCESSION` entries reducing
        `RENT` revenue; `EXPENSE` and `PAYROLL` never enter revenue."

        Design: Corner/calculations/statement_revenue_excludes_expense_payroll_and_void_rows
        """
        fx = setup_managed_property(legal_name="Filter Owner LP",
                                    property_name="Filter Property", unit_count=20)
        prop, resident = fx["prop"], fx["resident"]
        post_ledger_entry(prop, "RENT", 5000000, "2026-09",
                          collected_month="2026-09", resident_id=resident["id"])
        post_ledger_entry(prop, "FEE", 200000, "2026-09",
                          collected_month="2026-09", resident_id=resident["id"])
        post_ledger_entry(prop, "RECOVERY", 100000, "2026-09",
                          collected_month="2026-09", resident_id=resident["id"])
        post_ledger_entry(prop, "CONCESSION", -300000, "2026-09",
                          collected_month="2026-09", resident_id=resident["id"])
        post_ledger_entry(prop, "EXPENSE", 900000, "2026-09", collected_month="2026-09")
        post_ledger_entry(prop, "PAYROLL", 400000, "2026-09", collected_month="2026-09")
        st = open_statement(prop, period_month="2026-09", basis="CASH")
        set_clock("2026-10-01T00:00:00Z")

        closed = validate_success(api.close_statement(st["id"], acct_headers))
        # 5000000 + 200000 + 100000 - 300000 == 5000000; EXPENSE/PAYROLL excluded.
        assert closed["collected_revenue_cents"] == 5000000, (
            f"revenue must be 5000000, got {closed['collected_revenue_cents']}"
        )
        assert closed["base_fee_cents"] == 250000
        assert closed["incentive_fee_cents"] == 0


class TestDualBasisDivergence:
    def _build_divergence_property(self, api, acct_headers, pm_headers,
                                   legal_name, property_name):
        fx = setup_managed_property(legal_name=legal_name,
                                    property_name=property_name, unit_count=200)
        prop, resident = fx["prop"], fx["resident"]
        post_ledger_entry(prop, "RENT", 9000000, "2026-09",
                          collected_month="2026-09", resident_id=resident["id"])
        post_ledger_entry(prop, "RENT", 100000, "2026-09",
                          collected_month="2026-10", resident_id=resident["id"])
        post_ledger_entry(prop, "FEE", 400000, "2026-09",
                          collected_month="2026-09", resident_id=resident["id"])
        post_ledger_entry(prop, "RECOVERY", 200000, "2026-09",
                          collected_month="2026-09", resident_id=resident["id"])
        return fx

    def test_statement_fee_cash_vs_accrual_diverge_on_late_collection(self, api, pm_headers, acct_headers):
        """PRD §3.6: "On the `CASH` basis, a row counts when its
        `collected_month` equals `period_month`: revenue is counted in the
        month cash is collected, so a charge accrued in month M but collected
        in month M+1 counts in M+1 only. On the `ACCRUAL` basis, a row counts
        when its `accrual_month` equals `period_month` regardless of
        collection. The identical ledger therefore produces a different fee
        whenever collection lags accrual."

        Design: Difficulty/dual_variant_calc/statement_fee_cash_vs_accrual_diverge_on_late_collection
        """
        fx = self._build_divergence_property(
            api, acct_headers, pm_headers, "DV Owner LP", "DV Property"
        )
        prop = fx["prop"]
        s_cash = open_statement(prop, period_month="2026-09", basis="CASH")
        s_accr = open_statement(prop, period_month="2026-09", basis="ACCRUAL")
        set_clock("2026-10-01T00:00:00Z")

        cash = validate_success(api.close_statement(s_cash["id"], acct_headers))
        accr = validate_success(api.close_statement(s_accr["id"], acct_headers))

        # CASH excludes the 100000 row collected in 2026-10:
        # 9000000 + 400000 + 200000 == 9600000; fee = 0.04 * 9600000 == 384000.
        assert cash["collected_revenue_cents"] == 9600000
        assert cash["base_fee_cents"] == 384000
        assert cash["incentive_fee_cents"] == 0
        # ACCRUAL includes it: 9700000; fee = 388000.
        assert accr["collected_revenue_cents"] == 9700000
        assert accr["base_fee_cents"] == 388000
        assert accr["incentive_fee_cents"] == 0

    def test_statement_fee_accrual_includes_uncollected_rows_while_cash_excludes(self, api, pm_headers, acct_headers):
        """PRD §3.6: "On the `ACCRUAL` basis, a row counts when its
        `accrual_month` equals `period_month` regardless of collection."

        Design: Difficulty/dual_variant_calc/statement_fee_cash_vs_accrual_diverge_on_late_collection
        """
        # Second probe on the same rule with the uncollected row being the ONLY
        # revenue: CASH sees zero revenue (floor binds), ACCRUAL sees the row.
        fx = setup_managed_property(legal_name="DV2 Owner LP",
                                    property_name="DV2 Property", unit_count=50)
        prop, resident = fx["prop"], fx["resident"]
        post_ledger_entry(prop, "RENT", 10000000, "2026-09",
                          collected_month="2026-10", resident_id=resident["id"])
        s_cash = open_statement(prop, period_month="2026-09", basis="CASH")
        s_accr = open_statement(prop, period_month="2026-09", basis="ACCRUAL")
        set_clock("2026-10-01T00:00:00Z")

        cash = validate_success(api.close_statement(s_cash["id"], acct_headers))
        accr = validate_success(api.close_statement(s_accr["id"], acct_headers))

        assert cash["collected_revenue_cents"] == 0
        assert cash["base_fee_cents"] == 250000  # floor binds at zero revenue
        assert accr["collected_revenue_cents"] == 10000000
        assert accr["base_fee_cents"] == 400000  # round(0.04 * 10000000)


class TestStatementPreviewAndFreeze:
    def test_statement_get_preview_while_open_shows_live_computation(self, api, acct_headers):
        """PRD §3.6: "While a statement is open, reading it previews the
        computations that close will freeze."; PRD §3.6: "On close, the
        computed fields freeze".

        Design: Corner/endpoints/statement_get_preview_while_open_shows_live_computation
        """
        fx, st = _managed_with_rent(5000000, legal_name="Prev Owner LP",
                                    property_name="Prev Property")
        prop, resident = fx["prop"], fx["resident"]

        preview = validate_success(api.get_statement(st["id"], acct_headers))
        # round(0.04 * 5000000) == 200000 < floor 250000.
        assert preview["base_fee_cents"] == 250000

        closed = validate_success(api.close_statement(st["id"], acct_headers))
        assert closed["base_fee_cents"] == 250000

        # Posting more revenue after close does not move the frozen values.
        post_ledger_entry(prop, "RENT", 1000000, "2026-09",
                          collected_month="2026-09", resident_id=resident["id"])
        after = validate_success(api.get_statement(st["id"], acct_headers))
        assert after["status"] == "CLOSED"
        assert after["base_fee_cents"] == 250000, (
            f"closed statement values must stay frozen; got {after['base_fee_cents']}"
        )


class TestImmediateConsistency:
    def test_immediate_consistency_close_response_contains_frozen_values(self, api, acct_headers):
        """PRD §3.6: "On close, the computed fields freeze, and two cascades
        fire: the property's cash available is reduced by the management fee
        total plus the payroll charge (the manager is paid), and any `DRAFT`
        `OwnerReportPackage` for the same property and period becomes
        `GENERATED`".

        Design: Corner/consistency/immediate_consistency_close_response_contains_frozen_values
        """
        fx, st = _managed_with_rent(9600000, legal_name="IC Owner LP",
                                    property_name="IC Property")
        closed = validate_success(api.close_statement(st["id"], acct_headers))
        assert closed["status"] == "CLOSED"
        assert closed["base_fee_cents"] == 384000
        assert closed["incentive_fee_cents"] == 0
        assert closed["management_fee_total_cents"] == 384000
        assert "payroll_charge_cents" in closed


class TestStatementCloseGates:
    def test_close_before_month_end_rejected(self, api, acct_headers):
        """PRD §3.6: "a statement may never close before its month has ended,
        and an early close is rejected with `ERR_STATEMENT_PERIOD_OPEN`."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_temporal_on_statement_close
        """
        fx = setup_managed_property(legal_name="Early Owner LP",
                                    property_name="Early Property", unit_count=20)
        st = open_statement(fx["prop"], period_month="2026-09", basis="CASH")
        # Logical clock is still 2026-09-01 (inside the statement month).
        resp = api.close_statement(st["id"], acct_headers)
        validate_error(resp, ApiErrorId.ERR_STATEMENT_PERIOD_OPEN)

    def test_state_vs_business_temporal_on_statement_close(self, api, pm_headers, acct_headers):
        """PRD §2.10: "When several validation rules apply to a single request,
        the server evaluates them in a fixed priority order and surfaces the
        first failure. ... then state-machine legality
        (`ERR_INVALID_STATE_TRANSITION`), then the business rules in their
        domain order".

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_temporal_on_statement_close
        """
        fx = setup_managed_property(legal_name="Prio One LP",
                                    property_name="Prio Property", unit_count=90)
        st = open_statement(fx["prop"], period_month="2026-09", basis="CASH")
        set_clock("2026-10-01T00:00:00Z")
        closed = validate_success(api.close_statement(st["id"], acct_headers))
        assert closed["status"] == "CLOSED"
        # Move the clock back inside the statement month so the temporal check
        # would also fail if reached; state legality must win.
        set_clock("2026-09-15T00:00:00Z")
        resp = api.close_statement(st["id"], acct_headers)
        body = resp.json()
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        assert body["data"]["error_id"] != ApiErrorId.ERR_STATEMENT_PERIOD_OPEN.value
