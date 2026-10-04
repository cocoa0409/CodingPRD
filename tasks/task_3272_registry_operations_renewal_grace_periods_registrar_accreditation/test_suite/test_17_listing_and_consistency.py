"""Filtered listing and immediate-consistency tests (PRD §2.6, §3.1, §3.2)."""
from test_helpers import (
    find_invoice,
    get_success_data,
    make_admin_headers,
    make_finance_headers,
    make_operator_headers,
    registrar_ledger,
    set_clock,
    validate_paginated,
)


def _setup_two_registrars_with_domains(api):
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
    registrars = {}
    for iana, legal in ((9120, "Filter A"), (9121, "Filter B")):
        resp = api.create_registrar(
            {
                "iana_number": iana,
                "legal_name": legal,
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
        registrars[legal] = registrar

    domains = {}
    for name, legal in (("filter-a1", "Filter A"), ("filter-a2", "Filter A"),
                        ("filter-b1", "Filter B")):
        registrar = registrars[legal]
        resp = api.create_domain(
            {"name": name, "registrar_id": registrar["id"], "years": 1},
            make_operator_headers(registrar["id"]),
        )
        domains[name] = get_success_data(resp, expected_status=201)
    return registrars, domains


class TestFilteredDomainListing:
    def test_domains_filtered_list_reverse_reaches_registrar(self, api):
        """PRD §3.2: "Domains are listed with optional filters on
        `registrar_id`, `status`, and `name`; the same records are reachable
        in reverse by listing the domains a given registrar sponsors."

        Design: Corner/endpoints/domains_filtered_list_reverse_reaches_registrar
        """
        registrars, domains = _setup_two_registrars_with_domains(api)
        reg_a = registrars["Filter A"]

        resp = api.list_registrar_domains(reg_a["id"], make_admin_headers())
        rows, _meta = validate_paginated(resp)
        assert sorted(d["name"] for d in rows) == ["filter-a1", "filter-a2"]

        resp = api.list_domains(
            make_admin_headers(), params={"registrar_id": reg_a["id"]})
        filtered, _meta = validate_paginated(resp)
        assert sorted(d["name"] for d in filtered) == [
            "filter-a1", "filter-a2"]
        assert all(d["registrar_id"] == reg_a["id"] for d in filtered)
        assert "filter-b1" not in {d["name"] for d in filtered}

    def test_filtered_list_by_status_returns_matching_only(self, api):
        """PRD §3.2: "Domains are listed with optional filters on
        `registrar_id`, `status`, and `name`; the same records are reachable
        in reverse by listing the domains a given registrar sponsors."

        Design: Corner/endpoints/domains_filtered_list_reverse_reaches_registrar
        """
        registrars, domains = _setup_two_registrars_with_domains(api)
        reg_a = registrars["Filter A"]

        resp = api.delete_domain(
            domains["filter-a1"]["id"], make_operator_headers(reg_a["id"]))
        get_success_data(resp)

        resp = api.list_domains(
            make_admin_headers(), params={"status": "REDEMPTION_GRACE"})
        rows, _meta = validate_paginated(resp)
        assert [d["name"] for d in rows] == ["filter-a1"]

        resp = api.list_domains(
            make_admin_headers(), params={"status": "ACTIVE"})
        rows, _meta = validate_paginated(resp)
        assert sorted(d["name"] for d in rows) == ["filter-a2", "filter-b1"]


class TestImmediateConsistency:
    def test_invoice_and_ledger_visible_immediately_after_create(self, api):
        """PRD §3.2: "It also mints a `CREATE` invoice whose base is the
        effective schedule's `create_fee_cents` multiplied by the number of
        years — plus the ten-percent premium surcharge when the name is
        premium — and debits the sponsoring registrar's ledger."
        PRD §2.6: "A minted invoice posts a `DEBIT` entry of negative
        `total_cents`".

        Design: Corner/consistency_model/immediate_consistency_invoice_visible_in_same_read_after_create
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
                "iana_number": 9160,
                "legal_name": "Consistency Registrar",
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
            {"name": "immediate-domain", "registrar_id": registrar["id"],
             "years": 2},
            make_operator_headers(registrar["id"]),
        )
        domain = get_success_data(resp, expected_status=201)

        invoice = find_invoice(domain_id=domain["id"], kind="CREATE")
        assert invoice["total_cents"] == 1400, (
            f"CREATE for 2 years at 700/year is 1400, got "
            f"{invoice['total_cents']}"
        )

        debits = [e for e in registrar_ledger(registrar["id"])
                  if e["entry_type"] == "DEBIT"
                  and e.get("invoice_id") == invoice["id"]]
        assert len(debits) == 1
        assert debits[0]["amount_cents"] == -1400

    def test_domain_readable_immediately_after_create(self, api):
        """PRD §3.2: "A successful registration creates the domain in
        `ACTIVE` status with `expires_on` set to the current logical time
        plus the requested years, `grace_deadline` set to forty-five days
        past that expiry, `lock_status` and `suspension_status` both `NONE`".
        PRD §3.2: "It also mints a `CREATE` invoice whose base is the
        effective schedule's `create_fee_cents` multiplied by the number of
        years — plus the ten-percent premium surcharge when the name is
        premium — and debits the sponsoring registrar's ledger."

        Design: Corner/consistency_model/immediate_consistency_invoice_visible_in_same_read_after_create
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
                "iana_number": 9160,
                "legal_name": "Consistency Registrar",
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
            {"name": "immediate-domain", "registrar_id": registrar["id"],
             "years": 2},
            make_operator_headers(registrar["id"]),
        )
        domain = get_success_data(resp, expected_status=201)
        assert domain["status"] == "ACTIVE"
        assert domain["expires_on"] == "2029-03-01T00:00:00.000Z"
        assert domain["grace_deadline"] == "2029-04-15T00:00:00.000Z"

        invoice = find_invoice(domain_id=domain["id"], kind="CREATE")
        assert invoice["total_cents"] == 1400
