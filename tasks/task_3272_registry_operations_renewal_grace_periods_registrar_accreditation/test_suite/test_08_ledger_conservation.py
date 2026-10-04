"""Ledger conservation invariants (PRD §2.6, §3.3, §3.5)."""
from test_helpers import (
    find_invoice,
    get_domain,
    get_success_data,
    ledger_sum,
    make_admin_headers,
    make_finance_headers,
    make_operator_headers,
    registrar_ledger,
    set_clock,
    setup_completed_transfer,
    setup_disputed_transfer,
)


class TestAutoRenewLapseConservation:
    def test_auto_renew_and_lapse_leave_ledger_net_zero(self, api):
        """PRD §3.3: "the domain falls into `REDEMPTION_GRACE`, and the
        auto-renew is unwound: the outstanding `AUTO_RENEW` invoice is
        voided, a `VOID_CREDIT` ledger entry repays the registrar the full
        invoice total, and `expires_on` reverts by one year."
        PRD §2.6: "A minted invoice posts a `DEBIT` entry of negative
        `total_cents`; a voided invoice posts a compensating `VOID_CREDIT`
        entry of positive `total_cents` and flips the invoice to `VOIDED`."

        Accreditation at the epoch 2026-09-01: 122 days of 365 remain (Sep 1
        through Dec 31 inclusive), so the prorated annual is
        round_half_up(400000 * 122 / 365) = 133699 and the all-in
        accreditation debit is 250000 + 133699 + 1000000 = 1383699. With a
        50000 top-up and a 700 create debit, plus the auto-renew debit (-850)
        and its compensating void credit (+850), the ledger nets to
        -1383699 + 50000 - 700 = -1334399.

        Design: Difficulty/compensating_invariant/auto_renew_and_lapse_leave_ledger_net_zero
        """
        resp = api.create_price_schedule(
            {
                "create_fee_cents": 700,
                "renew_fee_cents": 850,
                "restore_fee_cents": 12000,
                "transfer_fee_cents": 700,
                "effective_on": "2027-03-01T00:00:00Z",
            },
            make_admin_headers(),
        )
        get_success_data(resp, expected_status=201)
        resp = api.create_registrar(
            {
                "iana_number": 8701,
                "legal_name": "Invariant Registrar",
                "application_fee_cents": 250000,
                "annual_fee_cents": 400000,
                "escrow_deposit_cents": 1000000,
                "technical_test_score": 90,
                "financial_statement_verified": True,
            },
            make_admin_headers(),
        )
        registrar = get_success_data(resp, expected_status=201)
        get_success_data(
            api.accredit_registrar(registrar["id"], make_admin_headers()))
        set_clock("2027-03-01T00:00:00Z")
        resp = api.create_ledger_topup(registrar["id"], 50000,
                                       make_finance_headers())
        get_success_data(resp, expected_status=201)
        resp = api.create_domain(
            {"name": "invariant-domain", "registrar_id": registrar["id"],
             "years": 1},
            make_operator_headers(registrar["id"]),
        )
        domain = get_success_data(resp, expected_status=201)
        expires_before = domain["expires_on"]
        assert expires_before == "2028-03-01T00:00:00.000Z"

        set_clock("2028-03-10T00:00:00Z")
        assert get_domain(domain["id"])["status"] == "AUTO_RENEW_GRACE"
        set_clock("2028-04-20T00:00:00Z")

        final = get_domain(domain["id"])
        assert final["status"] == "REDEMPTION_GRACE"
        assert final["expires_on"] == expires_before, (
            "the auto-renew extension must be fully unwound"
        )

        auto_invoice = find_invoice(domain_id=domain["id"], kind="AUTO_RENEW")
        assert auto_invoice["status"] == "VOIDED"

        entries = registrar_ledger(registrar["id"])
        auto_net = sum(
            e["amount_cents"] for e in entries
            if e.get("invoice_id") == auto_invoice["id"]
        )
        assert auto_net == 0, (
            f"auto-renew debit and void credit must net to zero, got "
            f"{auto_net}"
        )
        assert ledger_sum(registrar["id"]) == -1334399, (
            f"expected ledger net -1334399, got {ledger_sum(registrar['id'])}"
        )

    def test_auto_renew_invoice_amounts_match_schedule_renew_fee(self, api):
        """PRD §3.3: "an `AUTO_RENEW` invoice is minted at the renewal fee
        for a single year from the schedule effective at the auto-renew
        instant."
        PRD §2.6: "A minted invoice posts a `DEBIT` entry of negative
        `total_cents`; a voided invoice posts a compensating `VOID_CREDIT`
        entry of positive `total_cents` and flips the invoice to `VOIDED`."

        Design: Difficulty/compensating_invariant/auto_renew_and_lapse_leave_ledger_net_zero
        """
        resp = api.create_price_schedule(
            {
                "create_fee_cents": 700,
                "renew_fee_cents": 850,
                "restore_fee_cents": 12000,
                "transfer_fee_cents": 700,
                "effective_on": "2027-03-01T00:00:00Z",
            },
            make_admin_headers(),
        )
        get_success_data(resp, expected_status=201)
        resp = api.create_registrar(
            {
                "iana_number": 8701,
                "legal_name": "Invariant Registrar",
                "application_fee_cents": 250000,
                "annual_fee_cents": 400000,
                "escrow_deposit_cents": 1000000,
                "technical_test_score": 90,
                "financial_statement_verified": True,
            },
            make_admin_headers(),
        )
        registrar = get_success_data(resp, expected_status=201)
        get_success_data(
            api.accredit_registrar(registrar["id"], make_admin_headers()))
        set_clock("2027-03-01T00:00:00Z")
        resp = api.create_domain(
            {"name": "invariant-domain", "registrar_id": registrar["id"],
             "years": 1},
            make_operator_headers(registrar["id"]),
        )
        domain = get_success_data(resp, expected_status=201)

        set_clock("2028-03-10T00:00:00Z")
        auto_invoice = find_invoice(domain_id=domain["id"], kind="AUTO_RENEW")
        assert auto_invoice["base_cents"] == 850
        assert auto_invoice["total_cents"] == 850

        set_clock("2028-04-20T00:00:00Z")
        auto_invoice = find_invoice(domain_id=domain["id"], kind="AUTO_RENEW")
        assert auto_invoice["status"] == "VOIDED"
        entries = registrar_ledger(registrar["id"])
        auto_entries = [e for e in entries
                        if e.get("invoice_id") == auto_invoice["id"]]
        amounts = sorted(e["amount_cents"] for e in auto_entries)
        assert amounts == [-850, 850]


class TestTransferTermConservation:
    def test_complete_and_reverse_conserve_domain_term(self, api):
        """PRD §3.5: "Completion moves the transfer to `COMPLETED`, switches
        the domain's `registrar_id` to the gaining registrar and returns the
        domain to `ACTIVE`, extends `expires_on` by one year, recomputes
        `grace_deadline`, and mints a `TRANSFER` invoice against the *gaining*
        registrar at the effective schedule's `transfer_fee_cents`".
        PRD §3.5: "Reversal moves the transfer to `REVERSED`, reverts the
        domain's `registrar_id` to the original losing registrar, unwinds the
        one-year extension from `expires_on`, recomputes the grace deadline,
        voids the `TRANSFER` invoice, and posts a `VOID_CREDIT` repaying the
        gaining registrar."

        Design: Difficulty/compensating_invariant/transfer_complete_and_reverse_conserve_domain_term
        """
        reg_a, reg_b, domain, transfer = setup_disputed_transfer(
            name="term-conserve")
        expires_before_transfer = domain["expires_on"]
        assert expires_before_transfer == "2028-03-01T00:00:00.000Z"

        resp = api.reverse_transfer(transfer["id"], make_admin_headers())
        reversed_transfer = get_success_data(resp)
        assert reversed_transfer["status"] == "REVERSED"

        final = get_domain(domain["id"])
        assert final["expires_on"] == expires_before_transfer, (
            "term conserved across complete+reverse"
        )
        assert final["registrar_id"] == reg_a["id"]

        transfer_invoice = find_invoice(domain_id=domain["id"],
                                        kind="TRANSFER")
        assert transfer_invoice["status"] == "VOIDED"

        b_entries = registrar_ledger(reg_b["id"])
        transfer_entries = [e for e in b_entries
                            if e.get("invoice_id") == transfer_invoice["id"]]
        amounts = sorted(e["amount_cents"] for e in transfer_entries)
        assert amounts == [-700, 700], (
            "the -700 TRANSFER DEBIT and +700 VOID_CREDIT cancel exactly"
        )

    def test_gaining_registrar_ledger_nets_to_pre_transfer_total(self, api):
        """PRD §3.5: "mints a `TRANSFER` invoice against the *gaining*
        registrar at the effective schedule's `transfer_fee_cents`".
        PRD §3.5: "voids the `TRANSFER` invoice, and posts a `VOID_CREDIT`
        repaying the gaining registrar."
        PRD §2.6: "a voided invoice posts a compensating `VOID_CREDIT` entry
        of positive `total_cents` and flips the invoice to `VOIDED`."

        Design: Difficulty/compensating_invariant/transfer_complete_and_reverse_conserve_domain_term
        """
        reg_a, reg_b, domain, transfer = setup_completed_transfer(
            name="term-conserve")
        b_ledger_after_complete = ledger_sum(reg_b["id"])

        resp = api.dispute_transfer(
            transfer["id"], "conservation test",
            make_operator_headers(reg_a["id"]))
        get_success_data(resp)
        resp = api.reverse_transfer(transfer["id"], make_admin_headers())
        get_success_data(resp)

        # The reverse posts +700; the ledger returns to the value it had
        # just before the completion minted the -700 debit.
        assert ledger_sum(reg_b["id"]) == b_ledger_after_complete + 700

        transfer_invoice = find_invoice(domain_id=domain["id"],
                                        kind="TRANSFER")
        assert transfer_invoice["status"] == "VOIDED"
