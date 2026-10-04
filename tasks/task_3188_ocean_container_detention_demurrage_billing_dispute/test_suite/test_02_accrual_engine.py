"""Accrual engine tests: working-day sequences, free windows, tiered pricing,
hold overlays, and provisional-vs-final divergence."""
from test_helpers import (
    ApiErrorId,
    api_client,
    create_account,
    create_active_contract,
    create_terminal_with_labor_day,
    create_return_location,
    create_available_container,
    gate_out,
    return_empty,
    set_clock,
    validate_success,
)

CM = {"X-User-ID": "cm-1", "X-User-Role": "ContractManager"}
TO = {"X-User-ID": "to-1", "X-User-Role": "TerminalOperator"}
EC = {"X-User-ID": "ec-1", "X-User-Role": "EquipmentController"}


class TestDemurrageTierStraddle:
    def test_extended_tiered_schedule_straddle(self):
        """PRD §3.5: "Under `EXTENDED_TIERED`, days one through five cost 12000
        cents per day, days six through ten cost 24000, days eleven through
        fifteen cost 36000, and days sixteen and beyond cost 50000."
        PRD §3.5: "Marginal allocation means the k-th billable day is priced at
        the tier whose range contains k, so a run of days straddling a boundary
        splits across tiers; the total is the sum over billable days of each
        day's marginal rate."

        Design: Difficulty/combinatorial_formula/demurrage_tier_straddle_marginal_allocation
        """
        account = create_account(account_code="ACCT-C-EXT", legal_name="Gamma Logistics")
        contract = create_active_contract(
            account["id"],
            contract_ref="CTR-EXT",
            demurrage_free_days=3,
            detention_free_days=2,
            saturday_counts_as_free_day=True,
            demurrage_rate_schedule="EXTENDED_TIERED",
            detention_rate_schedule="EXTENDED_TIERED",
        )
        terminal = create_terminal_with_labor_day(terminal_code="OAK")
        create_return_location(terminal["id"], location_code="LOC-1")
        container = create_available_container(
            account,
            contract,
            terminal,
            container_number="MATU0000045",
            discharge_ts="2026-09-03T12:00:00Z",
            available_ts="2026-09-04T12:00:00Z",
        )
        gated = gate_out(container["id"], clock_ts="2026-09-16T12:00:00Z")
        # Saturdays count under CTR-EXT: billable 09-10,09-11,09-12,09-14,09-15,09-16
        assert gated["demurrage_billable_days"] == 6
        # 5@12000 + 1@24000 marginal straddle of the day-5/day-6 boundary
        assert gated["demurrage_amount_cents"] == 84000

    def test_standard_schedule_straddle(self):
        """PRD §3.5: "Under `STANDARD`, billable days one through three cost
        15000 cents per day, days four through seven cost 30000 cents per day,
        and days eight and beyond cost 45000 cents per day."
        PRD §3.5: "Marginal allocation means the k-th billable day is priced at
        the tier whose range contains k, so a run of days straddling a boundary
        splits across tiers; the total is the sum over billable days of each
        day's marginal rate."

        Design: Difficulty/combinatorial_formula/demurrage_tier_straddle_marginal_allocation
        """
        account = create_account(account_code="ACCT-C-STD", legal_name="Gamma Logistics Std")
        contract = create_active_contract(
            account["id"],
            contract_ref="CTR-STD",
            demurrage_free_days=4,
            detention_free_days=5,
            saturday_counts_as_free_day=False,
            demurrage_rate_schedule="STANDARD",
            detention_rate_schedule="STANDARD",
        )
        terminal = create_terminal_with_labor_day(terminal_code="OAK")
        create_return_location(terminal["id"], location_code="LOC-1")
        container = create_available_container(
            account,
            contract,
            terminal,
            container_number="MATU0000037",
            discharge_ts="2026-08-31T12:00:00Z",
            available_ts="2026-09-01T12:00:00Z",
        )
        gated = gate_out(container["id"], clock_ts="2026-09-15T12:00:00Z")
        # Free = 09-02,03,04,08 (09-07 holiday); billable 09-09,10,11,14,15
        assert gated["demurrage_billable_days"] == 5
        # 3@15000 + 2@30000 marginal straddle of the day-3/day-4 boundary
        assert gated["demurrage_amount_cents"] == 105000


class TestProvisionalVsFinalDivergence:
    def test_provisional_read_diverges_from_final_at_gate_out(self):
        """PRD §3.5: "Provisional and final figures diverge whenever the
        logical clock moves between reads, which is precisely what lets a
        billing agent quote a customer an as-of-today number before the
        physical move completes."
        PRD §3.5: "The **provisional** variant runs whenever a container is read
        while still accruing — at the terminal in `AVAILABLE` for demurrage, or
        off-terminal in `GATE_OUT` for detention — with the accrual end set to
        the current logical date".

        Design: Difficulty/dual_variant_calc/demurrage_provisional_vs_final_accrual_divergence
        """
        account = create_account(account_code="ACCT-A", legal_name="Alpha Importers")
        contract = create_active_contract(
            account["id"],
            contract_ref="CTR-A",
            demurrage_free_days=2,
            detention_free_days=5,
            saturday_counts_as_free_day=False,
            demurrage_rate_schedule="STANDARD",
            detention_rate_schedule="STANDARD",
        )
        terminal = create_terminal_with_labor_day(terminal_code="LGB")
        location = create_return_location(terminal["id"], location_code="LOC-L1")
        container = create_available_container(
            account,
            contract,
            terminal,
            container_number="MATU0000011",
            discharge_ts="2026-09-07T12:00:00Z",
            available_ts="2026-09-08T12:00:00Z",
        )
        set_clock("2026-09-14T12:00:00Z", TO)
        provisional = validate_success(api_client.get_container(container["id"], TO))
        # Free days = 09-09,09-10; provisional billable 09-11,09-14 @15000
        assert provisional["demurrage_amount_cents"] == 30000
        assert provisional["demurrage_billable_days"] == 2

        gated = gate_out(container["id"], clock_ts="2026-09-18T12:00:00Z")
        # Final adds 09-15,09-16,17,18: 3@15000 + 3@30000
        assert gated["demurrage_amount_cents"] == 135000
        assert gated["demurrage_billable_days"] == 6
        assert provisional["demurrage_amount_cents"] != gated["demurrage_amount_cents"]
        assert gated["status"] == "GATE_OUT"
        assert gated["assigned_return_location_id"] == location["id"]

    def test_provisional_read_is_never_persisted_as_accrual_row(self):
        """PRD §3.5: "its result refreshes the container's computed
        `demurrage_billable_days`, `demurrage_amount_cents`,
        `detention_billable_days`, and `detention_amount_cents` fields for
        display but is never persisted as a `ChargeAccrual`."

        Design: Difficulty/dual_variant_calc/demurrage_provisional_vs_final_accrual_divergence
        """
        account = create_account(account_code="ACCT-A2", legal_name="Alpha Importers II")
        contract = create_active_contract(
            account["id"],
            contract_ref="CTR-A2",
            demurrage_free_days=2,
            detention_free_days=5,
            saturday_counts_as_free_day=False,
        )
        terminal = create_terminal_with_labor_day(terminal_code="LGB")
        create_return_location(terminal["id"], location_code="LOC-L1")
        container = create_available_container(
            account,
            contract,
            terminal,
            container_number="MATU0000202",
            discharge_ts="2026-09-07T12:00:00Z",
            available_ts="2026-09-08T12:00:00Z",
        )
        set_clock("2026-09-14T12:00:00Z", TO)
        validate_success(api_client.get_container(container["id"], TO))
        resp = api_client.list_container_accruals(container["id"], TO)
        rows = validate_success(resp)
        assert isinstance(rows, list)
        assert len(rows) == 0, "provisional reads must not persist ChargeAccrual rows"


class TestSaturdayFlagAndHoldOverlay:
    def test_saturday_flag_changes_billable_set(self):
        """PRD §3.2: "A calendar date counts as a working day for a given
        terminal and contract when all of the following hold: the date is not a
        Sunday; the date is not declared as a `TerminalHoliday` at that
        terminal; and the date is not a Saturday unless the governing
        contract's `saturday_counts_as_free_day` is true."

        Design: Corner/calculations/saturday_flag_changes_free_window_and_billable_set
        """
        account = create_account(account_code="ACCT-SAT", legal_name="Saturday Co")
        ctr_no = create_active_contract(
            account["id"],
            contract_ref="CTR-SAT-N",
            demurrage_free_days=2,
            detention_free_days=5,
            saturday_counts_as_free_day=False,
        )
        ctr_yes = create_active_contract(
            account["id"],
            contract_ref="CTR-SAT-Y",
            demurrage_free_days=2,
            detention_free_days=5,
            saturday_counts_as_free_day=True,
        )
        terminal = create_terminal_with_labor_day(terminal_code="OAK")
        create_return_location(terminal["id"], location_code="LOC-1")
        k1 = create_available_container(
            account, ctr_no, terminal,
            container_number="MATU0001076",
            discharge_ts="2026-09-03T12:00:00Z",
            available_ts="2026-09-04T12:00:00Z",
        )
        k2 = create_available_container(
            account, ctr_yes, terminal,
            container_number="MATU0001084",
            discharge_ts="2026-09-03T12:00:00Z",
            available_ts="2026-09-04T12:00:00Z",
        )
        set_clock("2026-09-10T12:00:00Z", TO)
        g1 = gate_out(k1["id"])
        g2 = gate_out(k2["id"])
        # sat=false: free 09-08,09-09; billable 09-10 only
        assert g1["demurrage_billable_days"] == 1
        assert g1["demurrage_amount_cents"] == 15000
        # sat=true: Saturday 09-05 consumes a free day; billable 09-09,09-10
        assert g2["demurrage_billable_days"] == 2
        assert g2["demurrage_amount_cents"] == 30000

    def test_chassis_shortage_hold_stops_detention_clock(self):
        """PRD §3.5: "Layered over both windows is the **hold overlay**: any
        calendar day on which the container carried an active `CUSTOMS_HOLD` or
        `USDA_HOLD` during its demurrage phase, or an active `CHASSIS_SHORTAGE`
        during its detention phase, is excluded from both the free-day count
        and the billable-day count."

        Design: Corner/calculations/hold_overlay_stops_detention_clock
        """
        account = create_account(account_code="ACCT-HO", legal_name="HoldOver Co")
        contract = create_active_contract(
            account["id"],
            contract_ref="CTR-HO",
            demurrage_free_days=2,
            detention_free_days=5,
            saturday_counts_as_free_day=False,
        )
        terminal = create_terminal_with_labor_day(terminal_code="OAK")
        create_return_location(terminal["id"], location_code="LOC-1")
        container = create_available_container(
            account, contract, terminal,
            container_number="MATU0001092",
            discharge_ts="2026-09-08T12:00:00Z",
            available_ts="2026-09-09T12:00:00Z",
        )
        gate_out(container["id"], clock_ts="2026-09-09T12:00:00Z")
        # Chassis shortage hold over 09-18 (placed) .. 09-19 (released)
        set_clock("2026-09-18T12:00:00Z", EC)
        api_client.set_container_hold(
            container["id"], {"hold_code": "CHASSIS_SHORTAGE", "action": "PLACE"}, EC
        )
        set_clock("2026-09-19T12:00:00Z", EC)
        api_client.set_container_hold(
            container["id"], {"hold_code": "CHASSIS_SHORTAGE", "action": "RELEASE"}, EC
        )
        # Second hold over 09-21 .. 09-22
        set_clock("2026-09-21T12:00:00Z", EC)
        api_client.set_container_hold(
            container["id"], {"hold_code": "CHASSIS_SHORTAGE", "action": "PLACE"}, EC
        )
        set_clock("2026-09-22T12:00:00Z", EC)
        api_client.set_container_hold(
            container["id"], {"hold_code": "CHASSIS_SHORTAGE", "action": "RELEASE"}, EC
        )
        set_clock("2026-09-25T12:00:00Z", EC)
        resp = api_client.return_empty_container(container["id"], EC)
        data = validate_success(resp, 200)
        # Billable 09-17, 09-22, 09-23, 09-24, 09-25; hold days 09-18, 09-21 excluded
        assert data["detention_billable_days"] == 5
        assert data["detention_amount_cents"] == 54000


class TestZeroBoundaryAccrual:
    def test_zero_free_days_billable_starts_day_after_availability(self):
        """PRD §3.5: "The **demurrage free window** is the first
        `demurrage_free_days` working days strictly after `available_ts` — zero
        free days means an empty window".

        Design: Difficulty/boundary_precision_check/free_day_zero_and_return_on_last_free_day_zero_charge
        """
        account = create_account(account_code="ACCT-K0", legal_name="Kelp Traders")
        contract = create_active_contract(
            account["id"],
            contract_ref="CTR-K0",
            demurrage_free_days=0,
            detention_free_days=5,
            saturday_counts_as_free_day=False,
        )
        terminal = create_terminal_with_labor_day(terminal_code="OAK")
        create_return_location(terminal["id"], location_code="LOC-1")
        container = create_available_container(
            account, contract, terminal,
            container_number="MATU0000128",
            discharge_ts="2026-08-31T12:00:00Z",
            available_ts="2026-09-01T12:00:00Z",
        )
        gated = gate_out(container["id"], clock_ts="2026-09-04T12:00:00Z")
        # free=0: billable 09-02, 09-03, 09-04 @15000
        assert gated["demurrage_billable_days"] == 3
        assert gated["demurrage_amount_cents"] == 45000

    def test_return_on_last_free_day_accrues_zero_and_persists_row(self):
        """PRD §3.5: "the **detention free window** is the first
        `detention_free_days` working days strictly after `gate_out_ts`."
        PRD §3.5: "The **final** variant runs at the lifecycle transition —
        gate-out for demurrage, empty return for detention — with the accrual
        end set to the transition date; its result is frozen onto the container
        and persisted as a `ChargeAccrual` row".

        Design: Difficulty/boundary_precision_check/free_day_zero_and_return_on_last_free_day_zero_charge
        """
        account = create_account(account_code="ACCT-K5", legal_name="Kelp Traders V")
        contract = create_active_contract(
            account["id"],
            contract_ref="CTR-K5",
            demurrage_free_days=2,
            detention_free_days=5,
            saturday_counts_as_free_day=False,
        )
        terminal = create_terminal_with_labor_day(terminal_code="OAK")
        create_return_location(terminal["id"], location_code="LOC-1")
        container = create_available_container(
            account, contract, terminal,
            container_number="MATU0000136",
            discharge_ts="2026-09-07T12:00:00Z",
            available_ts="2026-09-08T12:00:00Z",
        )
        gate_out(container["id"], clock_ts="2026-09-09T12:00:00Z")
        # Detention free window: 09-10, 09-11, 09-14, 09-15, 09-16 — return ON 09-16
        returned = return_empty(container["id"], clock_ts="2026-09-16T12:00:00Z")
        assert returned["detention_billable_days"] == 0
        assert returned["detention_amount_cents"] == 0
        rows = validate_success(api_client.list_container_accruals(container["id"], TO))
        detention_rows = [r for r in rows if r["charge_kind"] == "DETENTION"]
        assert len(detention_rows) == 1
        assert detention_rows[0]["billable_days"] == 0
        assert detention_rows[0]["amount_cents"] == 0


class TestEmptyReturnCascade:
    def test_empty_return_finalizes_detention_invoice_and_account(self):
        """PRD §3.4: "On acceptance, `empty_return_ts` is stamped from the
        logical clock, the detention accrual finalizes —
        `detention_billable_days` and `detention_amount_cents` freeze and a
        `ChargeAccrual` row of `charge_kind` `DETENTION` is written — and the
        location's daily empty-return counter for that date increments."
        PRD §3.6: "Issuance freezes the financial snapshot:
        `demurrage_total_cents` and `detention_total_cents` are taken from the
        non-voided `ChargeAccrual` rows at that instant; `gross_amount_cents`
        is their sum".
        PRD §3.6: "Issuance also moves the container to `BILLED` — its terminal
        state — and adds the new `balance_due_cents` into the account's
        `outstanding_balance_cents`."

        Design: Difficulty/transitive_cascade/empty_return_cascade_container_invoice_account
        """
        account = create_account(account_code="ACCT-H", legal_name="Harbor Distributors")
        contract = create_active_contract(
            account["id"],
            contract_ref="CTR-H",
            demurrage_free_days=4,
            detention_free_days=2,
            saturday_counts_as_free_day=True,
            demurrage_rate_schedule="STANDARD",
            detention_rate_schedule="EXTENDED_TIERED",
        )
        terminal = create_terminal_with_labor_day(terminal_code="OAK")
        create_return_location(
            terminal["id"], location_code="LOC-1",
            accepts_equipment_types=["DRY40HC"],
        )
        container = create_available_container(
            account, contract, terminal,
            container_number="MATU0000094",
            equipment_type="DRY40HC",
            discharge_ts="2026-09-05T12:00:00Z",
            available_ts="2026-09-08T12:00:00Z",
        )
        gated = gate_out(container["id"], clock_ts="2026-09-10T12:00:00Z")
        # Gate-out on 09-10 is inside the 4-day demurrage free window (09-09..09-12)
        assert gated["demurrage_amount_cents"] == 0

        returned = return_empty(container["id"], clock_ts="2026-09-30T12:00:00Z")
        assert returned["status"] == "EMPTY_RETURNED"
        # 15 billable detention days: 6@7000 + 7@15000 + 2@22000
        assert returned["detention_amount_cents"] == 191000

        invoice = validate_success(api_client.issue_invoice(container["id"], {"X-User-ID": "ba-1", "X-User-Role": "BillingAgent"}), 201)
        assert invoice["gross_amount_cents"] == 191000

        acct = validate_success(
            api_client.get_customer_account(account["id"], CM)
        )
        assert acct["outstanding_balance_cents"] == 191000

    def test_invoice_issuance_moves_container_to_billed_terminal_state(self):
        """PRD §3.6: "Issuance also moves the container to `BILLED` — its
        terminal state — and adds the new `balance_due_cents` into the
        account's `outstanding_balance_cents`."

        Design: Difficulty/transitive_cascade/empty_return_cascade_container_invoice_account
        """
        from test_helpers import setup_issued_invoice, get_container

        ctx = setup_issued_invoice(
            contract_overrides={"demurrage_free_days": 0, "detention_free_days": 5},
            gate_out_clock="2026-09-04T12:00:00Z",
        )
        container = get_container(ctx["container"]["id"])
        assert container["status"] == "BILLED"
        assert ctx["invoice"]["balance_due_cents"] == 45000
