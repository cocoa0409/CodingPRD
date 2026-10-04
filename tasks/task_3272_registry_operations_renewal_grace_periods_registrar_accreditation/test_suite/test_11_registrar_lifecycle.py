"""Registrar lifecycle corner tests (PRD §2.2, §2.3, §2.9, §3.1, §3.3)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_registrar,
    get_success_data,
    list_invoices,
    make_admin_headers,
    make_finance_headers,
    make_operator_headers,
    registrar_ledger,
    set_clock,
    setup_active_domain,
    validate_error,
    validate_paginated,
)


class TestRegistrarCreation:
    def test_create_returns_pending_tests_with_defaults(self, api):
        """PRD §3.1: "A new applicant starts in `PENDING_TESTS`, with
        `accredited_on` null and `accredited_version` unset until
        accreditation actually happens."
        PRD §3.1: "An optional `credit_hold` flag (defaulting to false) lets
        finance mark the account."
        PRD §2.4: "`version` (integer): a system-managed integer that
        increments by exactly one on every mutation, and underpins optimistic
        concurrency control."

        Design: Corner/entities/registrar_create_returns_all_fields_and_pending_tests
        """
        resp = api.create_registrar(
            {
                "iana_number": 9001,
                "legal_name": "Fresh Registrar Co",
                "application_fee_cents": 250000,
                "annual_fee_cents": 400000,
                "escrow_deposit_cents": 1000000,
                "technical_test_score": 85,
                "financial_statement_verified": True,
            },
            make_admin_headers(),
        )
        registrar = get_success_data(resp, expected_status=201)
        assert_registrar(registrar)
        assert registrar["status"] == "PENDING_TESTS"
        assert registrar["version"] == 1
        assert registrar["accredited_on"] is None
        assert registrar["credit_hold"] is False


class TestRegistrarNotFound:
    def test_get_unknown_registrar_returns_not_found(self, api):
        """PRD §2.9: "then path-id existence checked left-to-right —
        registrar before domain before transfer, and so on along the URL —
        with the first missing identifier yielding `ERR_NOT_FOUND`."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."

        Design: Corner/entities/registrar_get_unknown_id_returns_not_found
        """
        resp = api.get_registrar(NON_EXISTENT_UUID, make_admin_headers())
        error = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        assert "error_id" in error and "message" in error


class TestRegistrarPagination:
    def test_list_paginates_with_total_count_and_has_more(self, api):
        """PRD §2.3: "Paginated list responses include `limit`, `offset`,
        `total_count`, and `has_more` in the `meta` object of the response
        envelope."
        PRD §2.3: "The `limit` parameter caps the number of items returned;
        it defaults to 10, with a minimum of 1 and a maximum of 100. The
        `offset` parameter says how many items to skip and defaults to 0."

        Design: Corner/entities/registrars_list_paginates_total_count_and_has_more
        """
        for iana, name in ((9011, "Page One"), (9012, "Page Two"),
                           (9013, "Page Three")):
            resp = api.create_registrar(
                {
                    "iana_number": iana,
                    "legal_name": name,
                    "application_fee_cents": 250000,
                    "annual_fee_cents": 400000,
                    "escrow_deposit_cents": 1000000,
                    "technical_test_score": 80,
                    "financial_statement_verified": True,
                },
                make_admin_headers(),
            )
            get_success_data(resp, expected_status=201)

        resp = api.list_registrars(
            make_admin_headers(), params={"limit": 2, "offset": 0})
        page1, meta1 = validate_paginated(resp)
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        resp = api.list_registrars(
            make_admin_headers(), params={"limit": 2, "offset": 2})
        page2, meta2 = validate_paginated(resp)
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

        resp = api.list_registrars(make_admin_headers())
        page_all, meta_all = validate_paginated(resp)
        assert len(page_all) == 3
        assert meta_all["limit"] == 10
        assert meta_all["offset"] == 0


class TestRegistrarTermination:
    def test_terminate_blocked_until_domains_purged(self, api):
        """PRD §3.1: "Either an `ACTIVE` or a `SUSPENDED` registrar may be
        terminated, but only when it sponsors no live domain: if any domain
        under that registrar is `ACTIVE`, in `AUTO_RENEW_GRACE`, in
        `REDEMPTION_GRACE`, or `TRANSFERRING`, termination is rejected with
        `ERR_REGISTRAR_HAS_LIVE_DOMAINS`. Termination is final (`TERMINATED`)
        and credits the `escrow_deposit_cents` back as a `WRITE_OFF` ledger
        entry when the deposit is positive."

        Design: Corner/state_machines/registrar_terminate_blocked_by_live_domain
        """
        registrar, _schedule, domain = setup_active_domain(
            clock="2027-03-15T00:00:00Z", name="blocking-domain",
            escrow_deposit_cents=1000000)
        headers = make_operator_headers(registrar["id"])

        resp = api.terminate_registrar(registrar["id"], make_admin_headers())
        validate_error(resp, ApiErrorId.ERR_REGISTRAR_HAS_LIVE_DOMAINS)

        # ACTIVE -> REDEMPTION_GRACE on 2026-01-15; PENDING_DELETE after
        # 30 days (2026-02-14); DELETED after 35 days (2026-02-19).
        get_success_data(api.delete_domain(domain["id"], headers))
        set_clock("2027-04-20T00:00:00Z")

        resp = api.terminate_registrar(registrar["id"], make_admin_headers())
        terminated = get_success_data(resp)
        assert terminated["status"] == "TERMINATED"

        write_offs = [e for e in registrar_ledger(registrar["id"])
                      if e["entry_type"] == "WRITE_OFF"]
        assert len(write_offs) == 1
        assert write_offs[0]["amount_cents"] == 1000000, (
            "termination credits the escrow deposit back as a WRITE_OFF"
        )

    def test_terminated_registrar_is_terminal(self, api):
        """PRD §3.1: "Termination is final (`TERMINATED`) and credits the
        `escrow_deposit_cents` back as a `WRITE_OFF` ledger entry when the
        deposit is positive."
        PRD §2.9: "Only then does the system evaluate whether the target
        resource is in a state from which the requested transition exists
        (`ERR_INVALID_STATE`)".

        Design: Corner/state_machines/registrar_terminate_blocked_by_live_domain
        """
        registrar, _schedule, domain = setup_active_domain(
            clock="2027-03-15T00:00:00Z", name="blocking-domain",
            escrow_deposit_cents=1000000)
        headers = make_operator_headers(registrar["id"])

        resp = api.terminate_registrar(registrar["id"], make_admin_headers())
        validate_error(resp, ApiErrorId.ERR_REGISTRAR_HAS_LIVE_DOMAINS)

        get_success_data(api.delete_domain(domain["id"], headers))
        set_clock("2027-04-20T00:00:00Z")
        resp = api.terminate_registrar(registrar["id"], make_admin_headers())
        get_success_data(resp)

        # A second termination from the terminal state is an invalid state.
        resp = api.terminate_registrar(registrar["id"], make_admin_headers())
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        write_offs = [e for e in registrar_ledger(registrar["id"])
                      if e["entry_type"] == "WRITE_OFF"]
        assert len(write_offs) == 1
