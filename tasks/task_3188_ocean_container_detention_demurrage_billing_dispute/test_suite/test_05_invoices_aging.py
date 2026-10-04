"""Invoice aging buckets, aging-posture sweep, payments, and write-off."""
from test_helpers import (
    ApiErrorId,
    api_client,
    create_account,
    create_active_contract,
    create_terminal,
    create_terminal_with_labor_day,
    create_return_location,
    create_available_container,
    gate_out,
    return_empty,
    set_clock,
    setup_issued_invoice,
    validate_error,
    validate_success,
)

CM = {"X-User-ID": "cm-1", "X-User-Role": "ContractManager"}
TO = {"X-User-ID": "to-1", "X-User-Role": "TerminalOperator"}
EC = {"X-User-ID": "ec-1", "X-User-Role": "EquipmentController"}
BA = {"X-User-ID": "ba-1", "X-User-Role": "BillingAgent"}
DIR = {"X-User-ID": "dir-1", "X-User-Role": "CreditDirector"}


def _issued_invoice_with_holds_scenario():
    """Reproduce the demurrage-only 15000-cent invoice via the customs-hold
    overlay scenario (billable 09-04 only; holds cover 09-02 and 09-08)."""
    account = create_account(account_code="ACCT-B", legal_name="Beta Traders")
    contract = create_active_contract(
        account["id"],
        contract_ref="CTR-B",
        demurrage_free_days=2,
        detention_free_days=5,
        saturday_counts_as_free_day=False,
        effective_from="2026-09-01T00:00:00Z",
        effective_to="2027-06-30T00:00:00Z",
    )
    terminal = create_terminal_with_labor_day(terminal_code="HON")
    create_return_location(
        terminal["id"], location_code="LOC-H1",
        accepts_equipment_types=["DRY20"],
    )
    container = create_available_container(
        account, contract, terminal,
        container_number="MATU0000029",
        equipment_type="DRY20",
        discharge_ts="2026-08-31T12:00:00Z",
        available_ts="2026-09-01T12:00:00Z",
    )
    # Customs hold over 09-04..09-05 (covers the 09-04 working day)
    set_clock("2026-09-04T00:00:00Z", TO)
    api_client.set_container_hold(
        container["id"], {"hold_code": "CUSTOMS_HOLD", "action": "PLACE"}, TO
    )
    set_clock("2026-09-05T00:00:00Z", TO)
    api_client.set_container_hold(
        container["id"], {"hold_code": "CUSTOMS_HOLD", "action": "RELEASE"}, TO
    )
    # Customs hold over 09-08..09-09 (covers the 09-08 working day)
    set_clock("2026-09-08T00:00:00Z", TO)
    api_client.set_container_hold(
        container["id"], {"hold_code": "CUSTOMS_HOLD", "action": "PLACE"}, TO
    )
    set_clock("2026-09-09T00:00:00Z", TO)
    api_client.set_container_hold(
        container["id"], {"hold_code": "CUSTOMS_HOLD", "action": "RELEASE"}, TO
    )
    gate_out(container["id"])
    return_empty(container["id"])
    set_clock("2026-09-30T12:00:00Z", BA)
    invoice = validate_success(api_client.issue_invoice(container["id"], BA), 201)
    return account, invoice


class TestAgingBucketBoundariesAndSuspension:
    def test_bucket_flips_at_30_31_60_61_and_account_suspends_after_7_sweeps(self):
        """PRD §3.6: "Otherwise: days-past-due at or below zero is `CURRENT`;
        one through thirty is `DAYS_1_30`; thirty-one through sixty is
        `DAYS_31_60`; and sixty-one or more is `DAYS_61_PLUS`."
        PRD §2.7: "When the counter reaches seven consecutive logical days
        while the account is `ACTIVE`, the account transitions to `SUSPENDED`,
        its `credit_hold` flag is set to `true`, and new container intake for
        the account is thereafter rejected with `ERR_ACCOUNT_CREDIT_HOLD`."

        Design: Difficulty/dual_variant_calc/aging_bucket_threshold_variant_vs_accrual_variant_domains
        """
        account, invoice = _issued_invoice_with_holds_scenario()
        assert invoice["balance_due_cents"] == 15000

        set_clock("2026-10-30T12:00:00Z", BA)
        at_due = validate_success(api_client.get_invoice(invoice["id"], BA))
        assert at_due["aging_bucket"] == "CURRENT"

        set_clock("2026-11-29T12:00:00Z", BA)
        b30 = validate_success(api_client.get_invoice(invoice["id"], BA))
        assert b30["aging_bucket"] == "DAYS_1_30"

        set_clock("2026-11-30T12:00:00Z", BA)
        b31 = validate_success(api_client.get_invoice(invoice["id"], BA))
        assert b31["aging_bucket"] == "DAYS_31_60"

        set_clock("2026-12-29T12:00:00Z", BA)
        b60 = validate_success(api_client.get_invoice(invoice["id"], BA))
        assert b60["aging_bucket"] == "DAYS_31_60"

        set_clock("2026-12-30T12:00:00Z", BA)
        b61 = validate_success(api_client.get_invoice(invoice["id"], BA))
        assert b61["aging_bucket"] == "DAYS_61_PLUS"

        for day in ("2026-12-31", "2027-01-01", "2027-01-02", "2027-01-03", "2027-01-04"):
            set_clock(f"{day}T12:00:00Z", BA)
            acct = validate_success(api_client.get_customer_account(account["id"], BA))
            assert acct["status"] == "ACTIVE", (
                f"account must not suspend before 7 consecutive sweeps (clock {day})"
            )

        set_clock("2027-01-05T12:00:00Z", BA)
        acct = validate_success(api_client.get_customer_account(account["id"], BA))
        assert acct["status"] == "SUSPENDED"
        assert acct["credit_hold"] is True

    def test_zero_balance_invoice_is_always_current(self):
        """PRD §3.6: "An invoice whose `balance_due_cents` is zero is always
        `CURRENT`."

        Design: Difficulty/dual_variant_calc/aging_bucket_threshold_variant_vs_accrual_variant_domains
        """
        ctx = setup_issued_invoice(
            contract_overrides={"demurrage_free_days": 0, "detention_free_days": 5},
            gate_out_clock="2026-09-04T12:00:00Z",
        )
        invoice = ctx["invoice"]
        validate_success(
            api_client.create_payment(
                invoice["id"], {"amount_cents": invoice["balance_due_cents"]}, BA
            ), 201
        )
        set_clock("2027-03-01T12:00:00Z", BA)
        paid = validate_success(api_client.get_invoice(invoice["id"], BA))
        assert paid["status"] == "PAID"
        assert paid["balance_due_cents"] == 0
        assert paid["aging_bucket"] == "CURRENT"


class TestPayments:
    def test_overpay_rejected_then_exact_balance_settles(self):
        """PRD §3.6: "A payment carries `amount_cents` — at least one cent and
        never more than the invoice's current `balance_due_cents`, with an
        overage rejected as `ERR_PAYMENT_EXCEEDS_BALANCE` — and is stamped
        `tendered_at` from the logical clock with the terminal status
        `SETTLED`".
        PRD §3.6: "one exactly equal to the remaining balance moves the invoice
        to `PAID`, whether from `ISSUED` or `PARTIALLY_PAID`."

        Design: Corner/calculations/payment_overpay_rejected_boundary
        """
        ctx = setup_issued_invoice(
            account_overrides={"account_code": "ACCT-OP", "legal_name": "Overpay Co"},
            contract_overrides={
                "contract_ref": "CTR-OP", "demurrage_free_days": 0, "detention_free_days": 5,
            },
            container_overrides={"container_number": "MATU0001100"},
            gate_out_clock="2026-09-04T12:00:00Z",
            with_holiday=False,
        )
        invoice = ctx["invoice"]
        assert invoice["balance_due_cents"] == 45000

        over = api_client.create_payment(invoice["id"], {"amount_cents": 45001}, BA)
        validate_error(over, ApiErrorId.ERR_PAYMENT_EXCEEDS_BALANCE)

        paid = validate_success(
            api_client.create_payment(invoice["id"], {"amount_cents": 45000}, BA), 201
        )
        assert paid["status"] == "SETTLED"
        inv = validate_success(api_client.get_invoice(invoice["id"], BA))
        assert inv["status"] == "PAID"

    def test_paid_invoice_rejects_further_payments(self):
        """PRD §3.6: "Payments against a `PAID` or `WRITTEN_OFF` invoice are
        refused with `ERR_INVOICE_ALREADY_SETTLED`."

        Design: Corner/state_machines/terminal_state_lockdown_paid_invoice_rejects_payment
        """
        ctx = setup_issued_invoice(
            account_overrides={"account_code": "ACCT-TL", "legal_name": "TermLock Co"},
            contract_overrides={
                "contract_ref": "CTR-TL", "demurrage_free_days": 0, "detention_free_days": 5,
            },
            container_overrides={"container_number": "MATU0001035"},
            gate_out_clock="2026-09-04T12:00:00Z",
            with_holiday=False,
        )
        invoice = ctx["invoice"]
        validate_success(
            api_client.create_payment(invoice["id"], {"amount_cents": 45000}, BA), 201
        )
        resp = api_client.create_payment(invoice["id"], {"amount_cents": 100}, BA)
        validate_error(resp, ApiErrorId.ERR_INVOICE_ALREADY_SETTLED)


class TestInvoiceComputedFields:
    def test_gross_and_balance_derived_from_frozen_totals(self):
        """PRD §3.6: "Issuance freezes the financial snapshot:
        `demurrage_total_cents` and `detention_total_cents` are taken from the
        non-voided `ChargeAccrual` rows at that instant; `gross_amount_cents`
        is their sum; `credit_total_cents` starts as the sum of any `APPLIED`
        credits (zero at issuance) and `paid_total_cents` likewise starts at
        zero; and `balance_due_cents` is the gross minus credits minus
        payments, with the invariant that it never goes below zero."

        Design: Corner/entities/invoice_computed_gross_and_balance_fields
        """
        ctx = setup_issued_invoice(
            account_overrides={"account_code": "ACCT-CF", "legal_name": "CompField Co"},
            contract_overrides={
                "contract_ref": "CTR-CF",
                "demurrage_free_days": 0,
                "detention_free_days": 0,
                "saturday_counts_as_free_day": False,
            },
            container_overrides={"container_number": "MATU0001001"},
            gate_out_clock="2026-09-04T12:00:00Z",
            return_clock="2026-09-08T12:00:00Z",
        )
        invoice = ctx["invoice"]
        assert invoice["demurrage_total_cents"] == 45000
        assert invoice["detention_total_cents"] == 9000
        assert invoice["gross_amount_cents"] == 54000
        assert invoice["balance_due_cents"] == 54000


class TestWriteOff:
    def test_write_off_requires_61_plus_bucket(self):
        """PRD §3.8: "An invoice in `ISSUED` or `PARTIALLY_PAID` whose
        `aging_bucket` has reached `DAYS_61_PLUS` may be written off with a
        documented `justification` — an invoice aged less is rejected with
        `ERR_INVOICE_NOT_AGED_ENOUGH`, and a missing justification with
        `ERR_JUSTIFICATION_REQUIRED`."

        Design: Corner/errors/write_off_requires_61_plus_bucket
        """
        ctx = setup_issued_invoice(
            account_overrides={"account_code": "ACCT-WO", "legal_name": "WriteOff Co"},
            contract_overrides={
                "contract_ref": "CTR-WO", "demurrage_free_days": 0, "detention_free_days": 5,
                "effective_to": "2027-06-30T00:00:00Z",
            },
            container_overrides={"container_number": "MATU0001191"},
            gate_out_clock="2026-09-04T12:00:00Z",
            with_holiday=False,
        )
        invoice = ctx["invoice"]

        set_clock("2026-11-10T12:00:00Z", BA)
        early = api_client.write_off_invoice(
            invoice["id"], {"justification": "uncollectible"}, DIR
        )
        validate_error(early, ApiErrorId.ERR_INVOICE_NOT_AGED_ENOUGH)

        set_clock("2026-12-05T12:00:00Z", DIR)
        done = validate_success(
            api_client.write_off_invoice(
                invoice["id"], {"justification": "uncollectible, aged past 60"}, DIR
            ), 200
        )
        assert done["status"] == "WRITTEN_OFF"
        assert done["balance_due_cents"] == 0


class TestInvoiceListFilters:
    def test_invoice_list_filter_by_aging_bucket(self):
        """PRD §3.6: "Invoices may be listed with filters on
        `customer_account_id`, `status`, `aging_bucket`, and `container_id`,
        which together form the aging-receivable management surface."
        PRD §3.6: "An invoice whose `balance_due_cents` is zero is always
        `CURRENT`."

        Design: Corner/endpoints/invoice_list_filter_by_aging_bucket
        """
        terminal = create_terminal(terminal_code="OAK")
        create_return_location(terminal["id"], location_code="LOC-1", daily_empty_capacity=100)
        a1 = create_account(account_code="ACCT-F1", legal_name="Filter One")
        a2 = create_account(account_code="ACCT-F2", legal_name="Filter Two")
        c1 = create_active_contract(
            a1["id"], contract_ref="CTR-F1", demurrage_free_days=0, detention_free_days=5,
            effective_to="2027-06-30T00:00:00Z",
        )
        c2 = create_active_contract(
            a2["id"], contract_ref="CTR-F2", demurrage_free_days=0, detention_free_days=5,
            effective_to="2027-06-30T00:00:00Z",
        )

        def flow(account, contract, number):
            container = create_available_container(
                account, contract, terminal,
                container_number=number,
                discharge_ts="2026-08-31T12:00:00Z",
                available_ts="2026-09-01T12:00:00Z",
            )
            gate_out(container["id"], clock_ts="2026-09-04T12:00:00Z")
            return_empty(container["id"])
            return container

        k1 = flow(a1, c1, "MATU0001167")
        k1b = flow(a1, c1, "MATU0001185")

        # Issue both ACCT-F1 invoices at clock 2026-09-01 (due 2026-10-01)
        set_clock("2026-09-01T00:00:00Z", TO)
        inv1 = validate_success(api_client.issue_invoice(k1["id"], BA), 201)
        inv1b = validate_success(api_client.issue_invoice(k1b["id"], BA), 201)
        # Pay the second invoice in full so the account never suspends
        validate_success(
            api_client.create_payment(inv1b["id"], {"amount_cents": inv1b["balance_due_cents"]}, BA),
            201,
        )

        # ACCT-F2 invoice issued later so it stays CURRENT
        k2 = create_available_container(
            a2, c2, terminal,
            container_number="MATU0001175",
            discharge_ts="2026-09-08T12:00:00Z",
            available_ts="2026-09-09T12:00:00Z",
        )
        gate_out(k2["id"], clock_ts="2026-09-14T12:00:00Z")
        return_empty(k2["id"])
        set_clock("2026-10-15T12:00:00Z", BA)
        inv2 = validate_success(api_client.issue_invoice(k2["id"], BA), 201)

        set_clock("2026-10-20T12:00:00Z", BA)
        resp = api_client.list_invoices(BA, params={"aging_bucket": "DAYS_1_30"})
        rows = validate_success(resp)
        ids = [r["id"] for r in rows]
        assert inv1["id"] in ids
        assert inv2["id"] not in ids
        assert inv1b["id"] not in ids
