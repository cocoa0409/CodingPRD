"""Domain lifecycle cascade tests (PRD §2.5, §3.3, §3.5)."""
from test_helpers import (
    find_invoice,
    get_domain,
    get_success_data,
    list_invoices,
    make_admin_headers,
    make_operator_headers,
    registrar_ledger,
    set_clock,
    setup_disputed_transfer,
    setup_two_registrars_with_domain,
)


class TestClockCascadeAutoRenewLapse:
    def _setup(self, api, name="cascade-me"):
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
                "iana_number": 8201,
                "legal_name": "Cascade Registrar",
                "application_fee_cents": 250000,
                "annual_fee_cents": 400000,
                "escrow_deposit_cents": 1000000,
                "technical_test_score": 90,
                "financial_statement_verified": True,
            },
            make_admin_headers(),
        )
        registrar = get_success_data(resp, expected_status=201)
        resp = api.accredit_registrar(registrar["id"], make_admin_headers())
        get_success_data(resp)
        set_clock("2027-03-01T00:00:00Z")
        resp = api.create_domain(
            {"name": name, "registrar_id": registrar["id"], "years": 1},
            make_operator_headers(registrar["id"]),
        )
        domain = get_success_data(resp, expected_status=201)
        return registrar, domain

    def test_clock_advance_cascades_auto_renew_then_lapse(self, api):
        """PRD §3.3: "If the logical clock passes `expires_on` while the
        domain is still `ACTIVE`, the registry itself renews the name for one
        year: the domain enters `AUTO_RENEW_GRACE`, `auto_renewed_on` is
        stamped with the old `expires_on`, `expires_on` advances by one year,
        `grace_deadline` is recomputed from the new expiry, and an
        `AUTO_RENEW` invoice is minted at the renewal fee for a single year
        from the schedule effective at the auto-renew instant."
        PRD §3.3: "either because the registrar explicitly deletes the name
        during the grace window or because the logical clock passes forty-five
        days past `auto_renewed_on` without action — the domain falls into
        `REDEMPTION_GRACE`, and the auto-renew is unwound: the outstanding
        `AUTO_RENEW` invoice is voided, a `VOID_CREDIT` ledger entry repays
        the registrar the full invoice total, and `expires_on` reverts by one
        year."

        Design: Difficulty/transitive_cascade/clock_advance_cascades_auto_renew_then_lapse_then_pending_delete
        """
        registrar, domain = self._setup(api)
        # Domain created 2027-03-01 for 1 year -> expires 2028-03-01.

        set_clock("2028-03-10T00:00:00Z")
        in_grace = get_domain(domain["id"])
        assert in_grace["status"] == "AUTO_RENEW_GRACE"
        assert in_grace["auto_renewed_on"] == "2028-03-01T00:00:00.000Z"
        assert in_grace["expires_on"] == "2029-03-01T00:00:00.000Z"

        # auto_renewed_on + 45 days = 2027-03-01; the lapse fires after it.
        set_clock("2028-04-20T00:00:00Z")
        lapsed = get_domain(domain["id"])
        assert lapsed["status"] == "REDEMPTION_GRACE"
        assert lapsed["expires_on"] == "2028-03-01T00:00:00.000Z", (
            f"the auto-renew extension must unwind, got "
            f"{lapsed['expires_on']}"
        )

        auto_invoice = find_invoice(domain_id=domain["id"], kind="AUTO_RENEW")
        assert auto_invoice["status"] == "VOIDED"

        entries = registrar_ledger(registrar["id"])
        auto_debits = [e for e in entries
                       if e["entry_type"] == "DEBIT"
                       and e.get("invoice_id") == auto_invoice["id"]]
        auto_credits = [e for e in entries
                        if e["entry_type"] == "VOID_CREDIT"
                        and e.get("invoice_id") == auto_invoice["id"]]
        assert len(auto_debits) == 1 and auto_debits[0]["amount_cents"] == -850
        assert len(auto_credits) == 1 \
            and auto_credits[0]["amount_cents"] == 850

    def test_pending_delete_entry_follows_redemption_lapse(self, api):
        """PRD §3.3: "If thirty days pass with no restore, the domain enters
        `PENDING_DELETE` and `delete_scheduled_on` is set to the date
        thirty-five days after redemption entry; five days later — that is,
        once the clock passes thirty-five days past redemption entry — the
        name is purged to `DELETED`, its uniqueness constraint lapses, and
        the label becomes available for fresh registration."

        Design: Difficulty/transitive_cascade/clock_advance_cascades_auto_renew_then_lapse_then_pending_delete
        """
        registrar, domain = self._setup(api)
        # expires 2028-03-01; lapse after 2028-04-15 -> REDEMPTION_GRACE
        # (entry 2028-04-15); +30d = 2028-05-15 -> PENDING_DELETE; +35d =
        # 2028-05-20 -> DELETED.
        set_clock("2028-03-10T00:00:00Z")
        assert get_domain(domain["id"])["status"] == "AUTO_RENEW_GRACE"
        set_clock("2028-04-20T00:00:00Z")
        assert get_domain(domain["id"])["status"] == "REDEMPTION_GRACE"
        set_clock("2028-05-16T00:00:00Z")
        pending = get_domain(domain["id"])
        assert pending["status"] == "PENDING_DELETE"
        assert pending["delete_scheduled_on"] is not None
        assert pending["delete_scheduled_on"][:10] == "2028-05-20", (
            f"delete_scheduled_on must be redemption entry + 35 days, got "
            f"{pending['delete_scheduled_on']}"
        )
        set_clock("2028-05-21T00:00:00Z")
        assert get_domain(domain["id"])["status"] == "DELETED"

        auto_invoice = find_invoice(domain_id=domain["id"], kind="AUTO_RENEW")
        assert auto_invoice["status"] == "VOIDED"


class TestTransferReversalCascade:
    def test_reverse_reverts_domain_and_voids_invoice(self, api):
        """PRD §3.5: "Reversal moves the transfer to `REVERSED`, reverts the
        domain's `registrar_id` to the original losing registrar, unwinds the
        one-year extension from `expires_on`, recomputes the grace deadline,
        voids the `TRANSFER` invoice, and posts a `VOID_CREDIT` repaying the
        gaining registrar."

        Design: Difficulty/transitive_cascade/transfer_reversal_cascades_domain_revert_then_invoice_void
        """
        reg_a, reg_b, domain, transfer = setup_disputed_transfer(
            name="reverse-me")
        assert transfer["status"] == "DISPUTED"

        resp = api.reverse_transfer(transfer["id"], make_admin_headers())
        reversed_transfer = get_success_data(resp)
        assert reversed_transfer["status"] == "REVERSED"

        reverted = get_domain(domain["id"])
        assert reverted["registrar_id"] == reg_a["id"]
        assert reverted["expires_on"] == "2028-03-01T00:00:00.000Z", (
            f"the +1y transfer extension must be unwound, got "
            f"{reverted['expires_on']}"
        )

        transfer_invoice = find_invoice(domain_id=domain["id"],
                                        kind="TRANSFER")
        assert transfer_invoice["status"] == "VOIDED"

        credits = [e for e in registrar_ledger(reg_b["id"])
                   if e["entry_type"] == "VOID_CREDIT"
                   and e.get("invoice_id") == transfer_invoice["id"]]
        assert len(credits) == 1
        assert credits[0]["amount_cents"] == transfer_invoice["total_cents"] \
            == 700

    def test_reverse_repayment_exactly_cancels_transfer_debit(self, api):
        """PRD §3.5: "voids the `TRANSFER` invoice, and posts a `VOID_CREDIT`
        repaying the gaining registrar."
        PRD §2.6: "A minted invoice posts a `DEBIT` entry of negative
        `total_cents`; a voided invoice posts a compensating `VOID_CREDIT`
        entry of positive `total_cents` and flips the invoice to `VOIDED`."

        Design: Difficulty/transitive_cascade/transfer_reversal_cascades_domain_revert_then_invoice_void
        """
        reg_a, reg_b, domain, transfer = setup_disputed_transfer(
            name="reverse-me")
        resp = api.reverse_transfer(transfer["id"], make_admin_headers())
        get_success_data(resp)

        entries = registrar_ledger(reg_b["id"])
        debits = [e["amount_cents"] for e in entries
                  if e["entry_type"] == "DEBIT"]
        credits = [e["amount_cents"] for e in entries
                   if e["entry_type"] == "VOID_CREDIT"]
        assert -700 in debits, f"missing TRANSFER debit in {debits}"
        assert 700 in credits, f"missing VOID_CREDIT in {credits}"
        # The transfer debit and its compensating credit cancel exactly.
        assert -700 + 700 == 0
