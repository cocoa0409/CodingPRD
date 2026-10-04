"""Billing runs, invoice line totals, trust-balance conservation, and the
invoice lifecycle escalations (due date, collections, write-off floor)."""
from test_helpers import (
    BOR, MB, TA,
    InvoiceLineKind, InvoiceOrigin, InvoiceStatus, OfficeStatus,
    assert_invoice, assert_office,
    generate_september_invoices,
    get_success_data,
    list_agent_invoice_rows,
    set_clock,
    setup_office_with_active_agent, setup_office_with_schedule,
    setup_office_with_two_active_agents, setup_pending_close_transaction,
    validate_error, validate_paginated, validate_success,
    make_agent_headers,
    create_offer, create_transaction_under_contract, create_cda,
    approve_cda_fully,
    api_client,
)


def _lines(api, invoice_id):
    rows, _ = validate_paginated(api.list_invoice_lines_for_invoice(invoice_id, TA))
    return rows


def test_monthly_invoice_totals_use_per_line_rounding_then_sum(api):
    """PRD §3.4: "The invoice's `amount_due_cents` is the sum of its
    `InvoiceLine` amounts, and its `due_date` is the first day of the billing
    month plus seven days. The invoice carries three monthly lines, each
    rounded half-up to whole cents before the sum (line-rounding order is
    pinned): a `DESK_FEE` line at the schedule's `desk_fee_cents`, a
    `TECH_SUBSCRIPTION` line at `tech_subscription_monthly_cents`, and a
    `MARKETING` line at `marketing_monthly_cents`."

    Design: Difficulty/combinatorial_formula/invoice_line_totals_per_line_rounding_then_sum
    """
    office, schedule, alice = setup_office_with_active_agent("2026-09-01T00:00:00Z")
    invoices = generate_september_invoices(office["id"])
    assert len(invoices) == 1, "exactly one invoice for the single ACTIVE agent"
    inv = invoices[0]
    assert inv["origin"] == InvoiceOrigin.AUTO_RUN.value
    assert inv["status"] == InvoiceStatus.ISSUED.value
    assert inv["amount_due_cents"] == 365000
    assert inv["due_date"].startswith("2026-09-08"), (
        f"due_date must be the first of the billing month plus seven days, got {inv['due_date']}")

    lines = _lines(api, inv["id"])
    assert len(lines) == 3
    amounts = {r["line_kind"]: r["amount_cents"] for r in lines}
    assert amounts[InvoiceLineKind.DESK_FEE.value] == 300000
    assert amounts[InvoiceLineKind.TECH_SUBSCRIPTION.value] == 25000
    assert amounts[InvoiceLineKind.MARKETING.value] == 40000
    # Overhead share is deliberately not a monthly line.
    assert InvoiceLineKind.OVERHEAD_SHARE.value not in amounts
    # Sum of rounded lines == invoice total.
    assert sum(amounts.values()) == inv["amount_due_cents"]


def test_generate_invoices_idempotent_per_agent_and_month(api):
    """PRD §3.4: "The run is idempotent per (agent, billing month): re-running
    it for the same month returns the already-existing invoices without
    duplicating them."

    Design: Difficulty/combinatorial_formula/invoice_line_totals_per_line_rounding_then_sum
    """
    office, schedule, alice = setup_office_with_active_agent("2026-09-01T00:00:00Z")
    first = generate_september_invoices(office["id"])
    second = generate_september_invoices(office["id"])
    assert {i["id"] for i in first} == {i["id"] for i in second}, (
        "re-running the billing run must return the same invoices")
    rows = list_agent_invoice_rows(alice["id"])
    assert len(rows) == 1, "no duplicate invoice may be persisted"


def test_trust_balance_conservation_through_pay_and_write_off(api):
    """PRD §2.8: "An office's `trust_balance_cents` is the sum of two
    components: the `amount_cents` of every `CommissionEntry` belonging to the
    office whose status is `ESCROW_HELD`, `OFFICE_FEE_ACCRUED`, or
    `DEPARTURE_HOLD`, plus the unpaid remainder — `amount_due_cents` minus
    `amount_paid_cents` — of every `Invoice` belonging to the office whose
    status is `ISSUED`, `PARTIALLY_PAID`, or `COLLECTIONS`."
    PRD §3.4: "Write-off moves the invoice to `WRITTEN_OFF`, reduces the
    office's `trust_balance_cents` by the unpaid balance (bad-debt
    recognition), and — if this was the office's last `COLLECTIONS` invoice —
    lifts the suspension back to `ACTIVE`."

    Design: Difficulty/compensating_invariant/pay_then_writeoff_floor_and_trust_conservation
    """
    office, schedule, alice, bob = setup_office_with_two_active_agents(
        "2026-09-01T00:00:00Z")
    invoices = generate_september_invoices(office["id"])
    inv_alice = next(i for i in invoices if i["agent_id"] == alice["id"])
    inv_bob = next(i for i in invoices if i["agent_id"] == bob["id"])

    # Alice pays in full; her invoice drops out of the receivable sum.
    validate_success(api.pay_invoice(
        inv_alice["id"], {"amount_cents": 365000}, make_agent_headers(alice["id"])))
    office_now = validate_success(api.get_office(office["id"], MB))
    assert office_now["trust_balance_cents"] == 365000, (
        f"only Bob's unpaid invoice contributes to trust, got "
        f"{office_now['trust_balance_cents']}")

    # Advance past due + 30 days; Bob's invoice escalates to COLLECTIONS and
    # the office suspends.
    set_clock("2026-10-09T00:00:00Z")
    bob_read = validate_success(api.get_invoice(inv_bob["id"], TA))
    assert bob_read["status"] == InvoiceStatus.COLLECTIONS.value
    office_now = validate_success(api.get_office(office["id"], MB))
    assert office_now["status"] == OfficeStatus.SUSPENDED.value

    # Write-off recognizes the bad debt: trust reduced by the unpaid balance,
    # suspension lifted because this was the last COLLECTIONS invoice.
    set_clock("2026-12-08T00:00:00Z")  # >= 90 days past 2026-09-08 due date
    inv = validate_success(api.write_off_invoice(inv_bob["id"], BOR))
    assert inv["status"] == InvoiceStatus.WRITTEN_OFF.value
    office_after = validate_success(api.get_office(office["id"], MB))
    assert office_after["trust_balance_cents"] == 0
    assert office_after["status"] == OfficeStatus.ACTIVE.value


def test_paid_invoice_drops_out_of_trust_receivable_sum(api):
    """PRD §2.8: "Invoices that are `OVERDUE` remain in the trust base because
    the obligation is still owed; invoices that reach `PAID` or `WRITTEN_OFF`
    drop out."

    Design: Difficulty/compensating_invariant/pay_then_writeoff_floor_and_trust_conservation
    """
    office, schedule, alice = setup_office_with_active_agent("2026-09-01T00:00:00Z")
    invoices = generate_september_invoices(office["id"])
    inv = invoices[0]

    before = validate_success(api.get_office(office["id"], MB))
    assert before["trust_balance_cents"] == 365000

    validate_success(api.pay_invoice(
        inv["id"], {"amount_cents": 365000}, make_agent_headers(alice["id"])))
    after = validate_success(api.get_office(office["id"], MB))
    assert after["trust_balance_cents"] == 0, (
        "a fully PAID invoice drops out of the receivable component")


def test_invoice_escalates_overdue_then_collections_on_clock_advance(api):
    """PRD §3.4: "When the logical clock passes `due_date` with any balance
    remaining, an `ISSUED` or `PARTIALLY_PAID` invoice advances to `OVERDUE`.
    When the clock passes `due_date` plus thirty days, an `OVERDUE` invoice
    advances to `COLLECTIONS`, and at that moment the office's `status` flips
    to `SUSPENDED` (the cascade up)."

    Design: Corner/calculations/invoice_escalation_issued_overdue_collections_on_clock_advance
    """
    office, schedule, alice = setup_office_with_active_agent("2026-09-01T00:00:00Z")
    inv = generate_september_invoices(office["id"])[0]

    # At the due_date instant the invoice is still ISSUED.
    set_clock("2026-09-08T00:00:00Z")
    read = validate_success(api.get_invoice(inv["id"], TA))
    assert read["status"] == InvoiceStatus.ISSUED.value

    # One second past due_date it reads OVERDUE.
    set_clock("2026-09-08T00:00:01Z")
    read = validate_success(api.get_invoice(inv["id"], TA))
    assert read["status"] == InvoiceStatus.OVERDUE.value

    # Past due_date + 30 days it reads COLLECTIONS and the office suspends.
    set_clock("2026-10-08T00:00:01Z")
    read = validate_success(api.get_invoice(inv["id"], TA))
    assert read["status"] == InvoiceStatus.COLLECTIONS.value
    office_now = validate_success(api.get_office(office["id"], MB))
    assert office_now["status"] == OfficeStatus.SUSPENDED.value


def test_write_off_rejected_before_ninety_days_past_due(api):
    """PRD §3.4: "A `BrokerOfRecord` may write off a `COLLECTIONS` invoice,
    but only once the invoice is at least ninety days past its `due_date`;
    attempting it earlier is rejected with `ERR_WRITE_OFF_TOO_EARLY` (HTTP
    409)."

    Design: Corner/validations/write_off_before_ninety_days_rejected
    """
    office, schedule, alice = setup_office_with_active_agent("2026-09-01T00:00:00Z")
    inv = generate_september_invoices(office["id"])[0]
    # Escalate to COLLECTIONS.
    set_clock("2026-10-09T00:00:00Z")
    read = validate_success(api.get_invoice(inv["id"], TA))
    assert read["status"] == InvoiceStatus.COLLECTIONS.value

    # 89 days past due (2026-09-08 + 89d = 2026-12-06): still too early.
    set_clock("2026-12-06T00:00:01Z")
    err = api.write_off_invoice(inv["id"], BOR)
    validate_error(err, "ERR_WRITE_OFF_TOO_EARLY")

    # Exactly 90 days past due (2026-12-07): the write-off succeeds.
    set_clock("2026-12-07T00:00:01Z")
    ok = validate_success(api.write_off_invoice(inv["id"], BOR))
    assert ok["status"] == InvoiceStatus.WRITTEN_OFF.value


def test_trust_balance_recomputed_after_close_and_reconcile(api):
    """PRD §2.8: "An office's `trust_balance_cents` is the sum of two
    components: the `amount_cents` of every `CommissionEntry` belonging to the
    office whose status is `ESCROW_HELD`, `OFFICE_FEE_ACCRUED`, or
    `DEPARTURE_HOLD`, plus the unpaid remainder — `amount_due_cents` minus
    `amount_paid_cents` — of every `Invoice` belonging to the office whose
    status is `ISSUED`, `PARTIALLY_PAID`, or `COLLECTIONS`."
    PRD §3.8: "every `AGENT_PAYABLE` entry advances to `DISBURSED` with the
    office's `trust_balance_cents` reduced by the entry's amount as cash
    leaves escrow; every `REFERRAL_PAYABLE` entry advances to `DISBURSED` and
    the referring office receives the payout; every `OFFICE_FEE_ACCRUED` entry
    advances to `RECONCILED`, recognized as office revenue with the trust
    balance reduced accordingly."

    Design: Corner/calculations/trust_balance_recomputed_after_close_and_reconcile
    """
    ctx = setup_pending_close_transaction()
    office, txn = ctx["office"], ctx["txn"]
    validate_success(api.close_transaction(txn["id"], MB))

    after_close = validate_success(api.get_office(office["id"], TA))
    # ESCROW_HELD receipt 1000000 + OFFICE_FEE_ACCRUED 37500; the AGENT_PAYABLE
    # and REFERRAL_PAYABLE splits are excluded from the trust sum.
    assert after_close["trust_balance_cents"] == 1037500, (
        f"post-close trust must equal receipt + accrued fee, got "
        f"{after_close['trust_balance_cents']}")

    validate_success(api.reconcile_office(office["id"], TA))
    entries, _ = validate_paginated(api.list_commission_entries(
        TA, params={"office_id": office["id"]}))
    by_kind = {}
    for e in entries:
        by_kind.setdefault(e["entry_kind"], []).append(e["status"])
    assert "DISBURSED" in by_kind.get("AGENT_DISBURSEMENT", [])
    assert "RECONCILED" in by_kind.get("OFFICE_FEE_ACCRUAL", [])

    after_rec = validate_success(api.get_office(office["id"], TA))
    # PRD §3.8: "Entries in `ESCROW_HELD` and `DEPARTURE_HOLD` are not touched
    # by reconciliation" — so the 1000000 GCI_RECEIPT remains in the trust
    # base while the accrued fee leaves: 1037500 - 37500 = 1000000.
    assert after_rec["trust_balance_cents"] == 1000000, (
        f"post-reconcile trust must retain the untouched ESCROW_HELD receipt, "
        f"got {after_rec['trust_balance_cents']}")
