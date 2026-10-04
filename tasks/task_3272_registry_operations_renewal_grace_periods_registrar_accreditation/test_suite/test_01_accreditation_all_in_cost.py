"""Accreditation fee calculation tests (PRD §2.6, §3.1)."""
from test_helpers import (
    ApiErrorId,
    assert_invoice_invariants,
    find_invoice,
    get_success_data,
    make_admin_headers,
    make_operator_headers,
    registrar_ledger,
    set_clock,
)


class TestAccreditationAllInCost:
    def test_provisional_prorates_partial_year_march_16(self, api):
        """PRD §3.1: "The `all_in_cost_cents` is then the sum of
        `application_fee_cents`, that prorated annual amount, and
        `escrow_deposit_cents`."
        PRD §3.1: "where "remaining days" counts from `accredited_on` through
        December 31 of the accreditation year, inclusive on both ends, and the
        result is rounded half-up to whole cents exactly once at the end,
        after the multiplication, with no intermediate rounding."

        Accreditation at 2027-11-16 leaves 45 days of 365, so the prorated
        annual fee is round_half_up(400000 * 45 / 365) = 49315, and the
        all-in cost is 250000 + 49315 + 1000000 = 1300411.

        Design: Difficulty/dual_variant_calc/accreditation_all_in_provisional_prorates_partial_year
        """
        set_clock("2027-11-16T00:00:00Z")
        resp = api.create_registrar(
            {
                "iana_number": 8001,
                "legal_name": "Alpha Registrar LLC",
                "application_fee_cents": 250000,
                "annual_fee_cents": 400000,
                "escrow_deposit_cents": 1000000,
                "technical_test_score": 92,
                "financial_statement_verified": True,
            },
            make_admin_headers(),
        )
        registrar = get_success_data(resp, expected_status=201)

        resp = api.accredit_registrar(registrar["id"], make_admin_headers())
        accredited = get_success_data(resp)
        assert accredited["annual_fee_mode"] == "PROVISIONAL"
        assert accredited["all_in_cost_cents"] == 1300411, (
            f"expected all_in_cost_cents 1300411, got "
            f"{accredited['all_in_cost_cents']}"
        )

        invoice = find_invoice(registrar_id=registrar["id"],
                               kind="ACCREDITATION")
        assert invoice["base_cents"] == 1300411
        assert invoice["premium_surcharge_cents"] == 0
        assert_invoice_invariants(invoice)

        debits = [e for e in registrar_ledger(registrar["id"])
                  if e["entry_type"] == "DEBIT"]
        assert len(debits) == 1
        assert debits[0]["amount_cents"] == -1300411

    def test_provisional_reinstate_flips_to_audit_basis(self, api):
        """PRD §3.1: "Reinstating a `SUSPENDED` registrar returns it to
        `ACTIVE` and recomputes the all-in cost under the `AUDIT` basis:
        `annual_fee_mode` becomes `AUDIT`, and `all_in_cost_cents` now
        reflects the full `annual_fee_cents` at face value with no proration
        — for the same fee fields this yields a strictly larger figure than
        the provisional basis whenever the accreditation year was partial."

        Design: Difficulty/dual_variant_calc/accreditation_all_in_provisional_prorates_partial_year
        """
        set_clock("2027-11-16T00:00:00Z")
        resp = api.create_registrar(
            {
                "iana_number": 8001,
                "legal_name": "Alpha Registrar LLC",
                "application_fee_cents": 250000,
                "annual_fee_cents": 400000,
                "escrow_deposit_cents": 1000000,
                "technical_test_score": 92,
                "financial_statement_verified": True,
            },
            make_admin_headers(),
        )
        registrar = get_success_data(resp, expected_status=201)
        resp = api.accredit_registrar(registrar["id"], make_admin_headers())
        accredited = get_success_data(resp)
        assert accredited["all_in_cost_cents"] == 1300411
        assert accredited["annual_fee_mode"] == "PROVISIONAL"

        resp = api.suspend_registrar(registrar["id"], make_admin_headers())
        get_success_data(resp)
        resp = api.reinstate_registrar(registrar["id"], make_admin_headers())
        reinstated = get_success_data(resp)
        assert reinstated["annual_fee_mode"] == "AUDIT"
        assert reinstated["all_in_cost_cents"] == 1650000, (
            f"AUDIT basis: 250000 + 400000 + 1000000 = 1650000, got "
            f"{reinstated['all_in_cost_cents']}"
        )
        assert reinstated["all_in_cost_cents"] > accredited["all_in_cost_cents"]

    def test_provisional_prorates_partial_year_march_17(self, api):
        """PRD §3.1: "the prorated annual fee is the `annual_fee_cents`
        multiplied by the number of remaining days in the calendar year and
        divided by the number of days in that year — 366 in a leap year, 365
        otherwise — where "remaining days" counts from `accredited_on`
        through December 31 of the accreditation year, inclusive on both
        ends".

        Boundary-adjacent check: accreditation one day later (2026-03-17)
        leaves 45 days, so the prorated annual is
        round_half_up(400000 * 45 / 365) = 49315 and the all-in cost is
        1299315 — one day less remaining means a smaller prorated annual.

        Design: Difficulty/dual_variant_calc/accreditation_all_in_provisional_prorates_partial_year
        """
        set_clock("2027-11-17T00:00:00Z")
        resp = api.create_registrar(
            {
                "iana_number": 8001,
                "legal_name": "Alpha Registrar LLC",
                "application_fee_cents": 250000,
                "annual_fee_cents": 400000,
                "escrow_deposit_cents": 1000000,
                "technical_test_score": 92,
                "financial_statement_verified": True,
            },
            make_admin_headers(),
        )
        registrar = get_success_data(resp, expected_status=201)
        resp = api.accredit_registrar(registrar["id"], make_admin_headers())
        accredited = get_success_data(resp)
        assert accredited["annual_fee_mode"] == "PROVISIONAL"
        assert accredited["all_in_cost_cents"] == 1299315, (
            f"expected all_in_cost_cents 1299315, got "
            f"{accredited['all_in_cost_cents']}"
        )


class TestRestoreInvoiceVariant:
    def _setup_redemption_domain(self, api, name="premium-example"):
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
        schedule = get_success_data(resp, expected_status=201)
        resp = api.create_registrar(
            {
                "iana_number": 8002,
                "legal_name": "Beta Registrar Inc",
                "application_fee_cents": 250000,
                "annual_fee_cents": 400000,
                "escrow_deposit_cents": 1000000,
                "technical_test_score": 95,
                "financial_statement_verified": True,
            },
            make_admin_headers(),
        )
        registrar = get_success_data(resp, expected_status=201)
        resp = api.accredit_registrar(registrar["id"], make_admin_headers())
        get_success_data(resp)
        set_clock("2027-03-01T00:00:00Z")
        headers = make_operator_headers(registrar["id"])
        resp = api.create_domain(
            {"name": name, "registrar_id": registrar["id"], "years": 1,
             "premium": True},
            headers,
        )
        domain = get_success_data(resp, expected_status=201)
        resp = api.delete_domain(domain["id"], headers)
        deleted = get_success_data(resp)
        assert deleted["status"] == "REDEMPTION_GRACE"
        return schedule, registrar, domain, headers

    def test_restore_base_composes_renew_plus_restore_fee(self, api):
        """PRD §3.3: "A restore moves the domain back to `ACTIVE`, extends
        `expires_on` by one year, recomputes the grace deadline, clears
        `auto_renewed_on`, and mints a `RESTORE` invoice whose base is the
        effective schedule's `renew_fee_cents` plus its `restore_fee_cents`."
        PRD §2.6: "Premium names — domains created with the `premium` flag
        set — carry a ten-percent registry service surcharge on every
        lifecycle invoice: `premium_surcharge_cents` is ten percent of the
        base, rounded half-up to whole cents."

        Design: Difficulty/dual_variant_calc/lifecycle_invoice_restore_variant_adds_restore_fee_on_domain
        """
        schedule, registrar, domain, headers = self._setup_redemption_domain(api)

        resp = api.restore_domain(domain["id"], headers)
        restored = get_success_data(resp)
        assert restored["status"] == "ACTIVE"

        invoice = find_invoice(domain_id=domain["id"], kind="RESTORE")
        assert invoice["base_cents"] == 12850, (
            f"restore base must be renew 850 + restore 12000 = 12850, got "
            f"{invoice['base_cents']}"
        )
        assert invoice["premium_surcharge_cents"] == 1285
        assert invoice["total_cents"] == 14135
        assert_invoice_invariants(invoice)
        assert invoice["price_schedule_id"] == schedule["id"]

        debits = [e for e in registrar_ledger(registrar["id"])
                  if e["entry_type"] == "DEBIT"
                  and e.get("invoice_id") == invoice["id"]]
        assert len(debits) == 1
        assert debits[0]["amount_cents"] == -14135

    def test_restore_non_premium_carries_no_surcharge(self, api):
        """PRD §2.6: "Non-premium domains and all accreditation invoices
        carry a surcharge of zero."
        PRD §3.3: "mints a `RESTORE` invoice whose base is the effective
        schedule's `renew_fee_cents` plus its `restore_fee_cents`."

        Design: Difficulty/dual_variant_calc/lifecycle_invoice_restore_variant_adds_restore_fee_on_domain
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
                "iana_number": 8002,
                "legal_name": "Beta Registrar Inc",
                "application_fee_cents": 250000,
                "annual_fee_cents": 400000,
                "escrow_deposit_cents": 1000000,
                "technical_test_score": 95,
                "financial_statement_verified": True,
            },
            make_admin_headers(),
        )
        registrar = get_success_data(resp, expected_status=201)
        resp = api.accredit_registrar(registrar["id"], make_admin_headers())
        get_success_data(resp)
        set_clock("2027-03-01T00:00:00Z")
        headers = make_operator_headers(registrar["id"])
        resp = api.create_domain(
            {"name": "plain-restore", "registrar_id": registrar["id"],
             "years": 1},
            headers,
        )
        domain = get_success_data(resp, expected_status=201)
        resp = api.delete_domain(domain["id"], headers)
        get_success_data(resp)

        resp = api.restore_domain(domain["id"], headers)
        get_success_data(resp)
        invoice = find_invoice(domain_id=domain["id"], kind="RESTORE")
        assert invoice["base_cents"] == 12850
        assert invoice["premium_surcharge_cents"] == 0
        assert invoice["total_cents"] == 12850
