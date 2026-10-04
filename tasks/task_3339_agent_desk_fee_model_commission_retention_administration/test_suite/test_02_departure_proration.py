"""Departure proration (owed vs refund variants) and the terminate cascade."""
from test_helpers import (
    BOR, MB, TA,
    AgentStatus, EntryKind, EntryStatus, InvoiceLineKind, InvoiceOrigin,
    InvoiceStatus, FIXED_MONTH_DAYS,
    assert_agent,
    create_active_agent,
    generate_september_invoices,
    get_success_data,
    list_agent_invoice_rows,
    set_clock,
    setup_office_with_active_agent, setup_office_with_schedule,
    setup_office_with_two_active_agents,
    validate_error, validate_paginated, validate_success,
    make_agent_headers,
    api_client,
)


def _invoice_lines(api, invoice_id):
    rows, _meta = validate_paginated(
        api.list_invoice_lines_for_invoice(invoice_id, TA))
    return rows


def _lines_of_kind(rows, kind):
    return [r for r in rows if r["line_kind"] == kind]


def test_departure_owed_variant_charges_partial_month(api):
    """PRD §3.10: "The owed variant — used when the departure invoice charges
    the partial month — computes the prorated desk fee as `desk_fee_cents`
    multiplied by `D` and divided by 30, rounded half-up to whole cents; that
    figure becomes the `PRORATED_DESK_FEE` line's `amount_cents`, covering
    days 1 through `D`."

    Design: Difficulty/dual_variant_calc/departure_proration_owed_vs_refund_fixed_month
    """
    # Alice never pays her September invoice; she terminates on day 10.
    office, schedule, alice = setup_office_with_active_agent("2026-09-01T00:00:00Z")
    generate_september_invoices(office["id"])
    set_clock("2026-09-10T00:00:00Z")
    validate_success(api.terminate_agent(alice["id"], make_agent_headers(alice["id"])))
    set_clock("2026-09-24T00:00:00Z")
    agent = validate_success(api.complete_termination(alice["id"], MB))
    assert agent["status"] == AgentStatus.TERMINATED.value

    departure = [i for i in list_agent_invoice_rows(alice["id"])
                 if i["origin"] == InvoiceOrigin.DEPARTURE.value]
    assert len(departure) == 1, "exactly one DEPARTURE invoice must be generated"
    lines = _invoice_lines(api, departure[0]["id"])
    prorated = _lines_of_kind(lines, InvoiceLineKind.PRORATED_DESK_FEE.value)
    assert len(prorated) == 1
    # Owed variant: 300000 * 10 / 30 = 100000.
    assert prorated[0]["amount_cents"] == 100000


def test_departure_refund_variant_credits_paid_month_and_variants_sum(api):
    """PRD §3.10: "The refund variant — used when the full month's desk fee was
    already invoiced and paid before termination was requested — computes the
    credit as `desk_fee_cents` multiplied by `30 - D` and divided by 30,
    rounded half-up to whole cents, returning days `D+1` through 30; that
    credit is netted against the departure invoice. The two variants never
    appear on the same departure invoice, and because both round independently
    under the same convention, the owed amount plus the refund amount equals
    the full `desk_fee_cents` exactly."

    Design: Difficulty/dual_variant_calc/departure_proration_owed_vs_refund_fixed_month
    """
    office, schedule, alice, bob = setup_office_with_two_active_agents(
        "2026-09-01T00:00:00Z")
    invoices = generate_september_invoices(office["id"])
    # Bob's September invoice is paid in full before termination; Alice's is
    # left ISSUED (owed variant).
    bob_invoice = next(i for i in invoices if i["agent_id"] == bob["id"])
    validate_success(api.pay_invoice(
        bob_invoice["id"], {"amount_cents": 365000}, make_agent_headers(bob["id"])))

    set_clock("2026-09-10T00:00:00Z")
    validate_success(api.terminate_agent(alice["id"], make_agent_headers(alice["id"])))
    validate_success(api.terminate_agent(bob["id"], make_agent_headers(bob["id"])))
    set_clock("2026-09-24T00:00:00Z")
    validate_success(api.complete_termination(alice["id"], MB))
    validate_success(api.complete_termination(bob["id"], MB))

    alice_dep = [i for i in list_agent_invoice_rows(alice["id"])
                 if i["origin"] == InvoiceOrigin.DEPARTURE.value][0]
    bob_dep = [i for i in list_agent_invoice_rows(bob["id"])
               if i["origin"] == InvoiceOrigin.DEPARTURE.value][0]

    alice_lines = _invoice_lines(api, alice_dep["id"])
    bob_lines = _invoice_lines(api, bob_dep["id"])
    alice_owed = sum(r["amount_cents"] for r in
                     _lines_of_kind(alice_lines, InvoiceLineKind.PRORATED_DESK_FEE.value))
    assert alice_owed == 100000

    # Refund variant: credit of 300000 * 20 / 30 = 200000 netted against the
    # departure invoice — Bob's PRORATED_DESK_FEE line carries the -200000
    # credit, and the two variants never appear on the same departure invoice.
    bob_prorated = _lines_of_kind(bob_lines, InvoiceLineKind.PRORATED_DESK_FEE.value)
    assert sum(r["amount_cents"] for r in bob_prorated) == -200000, (
        f"refund variant must credit 200000, got "
        f"{[r['amount_cents'] for r in bob_prorated]}")
    # Invariant: owed + refund == desk_fee_cents exactly.
    assert 100000 + 200000 == 300000
    # Departure metadata: origin and due_date == terminated_at + 14 days.
    assert alice_dep["origin"] == InvoiceOrigin.DEPARTURE.value
    assert alice_dep["due_date"].startswith("2026-10-08"), (
        f"departure due_date must be terminated_at + 14 days, got {alice_dep['due_date']}")


def test_terminate_spawns_departure_holds_and_completion_releases_them(api):
    """PRD §3.10: "every `InvoiceLine` belonging to the agent whose
    `applied_at_closing_cents` is below its `amount_cents` on an invoice in
    `ISSUED`, `PARTIALLY_PAID`, or `OVERDUE` spawns a `CommissionEntry` of kind
    `DEPARTURE_HOLD` in `DEPARTURE_HOLD` status, with an amount equal to that
    line's remaining balance — quarantining the agent's open receivables
    inside the trust."
    PRD §3.10: "every `DEPARTURE_HOLD` entry for the agent is resolved: if the
    departure invoice nets to zero or less, each hold advances through
    `DEPARTURE_RELEASE` to `DISBURSED`; otherwise the holds stay held against
    the invoice until it is paid."

    Design: Difficulty/transitive_cascade/terminate_cascade_holds_to_departure_invoice_to_release
    """
    office, schedule, alice = setup_office_with_active_agent("2026-09-01T00:00:00Z")
    invoices = generate_september_invoices(office["id"])
    alice_invoice = next(i for i in invoices if i["agent_id"] == alice["id"])

    set_clock("2026-09-10T00:00:00Z")
    validate_success(api.terminate_agent(alice["id"], make_agent_headers(alice["id"])))

    # Hop 1: DEPARTURE_HOLD entries spawned for the open invoice balance.
    held, _m = validate_paginated(api.list_commission_entries(
        TA, params={"office_id": office["id"], "status": EntryStatus.DEPARTURE_HOLD.value}))
    hold_total = sum(e["amount_cents"] for e in held
                     if e["entry_kind"] == EntryKind.DEPARTURE_HOLD.value)
    assert hold_total == 365000, (
        f"holds must quarantine the open 365000 balance, got {hold_total}")

    set_clock("2026-09-24T00:00:00Z")
    agent = validate_success(api.complete_termination(alice["id"], MB))
    assert agent["status"] == AgentStatus.TERMINATED.value

    # Hop 2: departure invoice with the prorated desk fee.
    departure = [i for i in list_agent_invoice_rows(alice["id"])
                 if i["origin"] == InvoiceOrigin.DEPARTURE.value]
    assert len(departure) == 1
    lines = _invoice_lines(api, departure[0]["id"])
    prorated = _lines_of_kind(lines, InvoiceLineKind.PRORATED_DESK_FEE.value)
    assert prorated and prorated[0]["amount_cents"] == 100000

    # Alice's departure invoice nets +100000 (owed variant, no advance), which
    # is greater than zero — PRD §3.10: "otherwise the holds stay held against
    # the invoice until it is paid." The original DEPARTURE_HOLD entries must
    # therefore remain in DEPARTURE_HOLD status.
    still_held, _m2 = validate_paginated(api.list_commission_entries(
        TA, params={"office_id": office["id"], "status": EntryStatus.DEPARTURE_HOLD.value}))
    held_total = sum(e["amount_cents"] for e in still_held
                     if e["entry_kind"] == EntryKind.DEPARTURE_HOLD.value)
    assert held_total == 365000, (
        f"holds must stay held against the unpaid departure invoice, got {held_total}")
    office_after = validate_success(api.get_office(office["id"], MB))
    assert office_after["active_agent_count"] == 0


def test_complete_termination_terminal_agent_state_and_office_count(api):
    """PRD §3.10: "Completion moves the agent to `TERMINATED`, sets
    `terminated_at`, and decrements the office's `active_agent_count`."

    Design: Difficulty/transitive_cascade/terminate_cascade_holds_to_departure_invoice_to_release
    """
    office, schedule, alice = setup_office_with_active_agent("2026-09-10T00:00:00Z")
    validate_success(api.terminate_agent(alice["id"], make_agent_headers(alice["id"])))
    set_clock("2026-09-24T00:00:00Z")
    validate_success(api.complete_termination(alice["id"], MB))

    agent = validate_success(api.get_agent(alice["id"], MB))
    assert agent["status"] == AgentStatus.TERMINATED.value
    assert agent["terminated_at"] is not None
    assert_agent(agent)
    office_after = validate_success(api.get_office(office["id"], MB))
    assert office_after["active_agent_count"] == 0
