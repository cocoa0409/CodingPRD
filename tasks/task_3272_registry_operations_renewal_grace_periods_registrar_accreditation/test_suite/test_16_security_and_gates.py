"""Security, uniqueness, and accreditation gate corner tests (PRD §2.1,
§2.7, §3.1, §3.6)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    get_registrar,
    get_success_data,
    make_abuse_headers,
    make_admin_headers,
    make_finance_headers,
    make_operator_headers,
    set_clock,
    setup_active_domain,
    setup_active_registrar,
    validate_error,
)


class TestAuthentication:
    def test_missing_auth_headers_returns_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, or presenting a role
        outside this enumeration, is rejected with `ERR_UNAUTHENTICATED`
        (HTTP 401)."
        PRD §2.9: "Authentication comes first (missing or invalid headers,
        `ERR_UNAUTHENTICATED`), followed by role authorization
        (`ERR_FORBIDDEN`), then path-id existence checked left-to-right —
        registrar before domain before transfer, and so on along the URL —
        with the first missing identifier yielding `ERR_NOT_FOUND`."

        Design: Corner/validations/auth_header_missing_returns_unauthenticated_before_any_other_check
        """
        resp = api.get_registrar(NON_EXISTENT_UUID, headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestAuthorizationBeforeExistence:
    def test_forbidden_role_beats_not_found(self, api):
        """PRD §2.9: "Authentication comes first (missing or invalid headers,
        `ERR_UNAUTHENTICATED`), followed by role authorization
        (`ERR_FORBIDDEN`), then path-id existence checked left-to-right —
        registrar before domain before transfer, and so on along the URL —
        with the first missing identifier yielding `ERR_NOT_FOUND`."
        PRD §2.1: "A request whose authenticated role is not permitted for
        the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/validations/forbidden_role_beats_not_found_for_hidden_resource
        """
        resp = api.suspend_registrar(NON_EXISTENT_UUID, make_abuse_headers())
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestAccreditationGates:
    def test_failing_technical_score_rejected(self, api):
        """PRD §3.1: "Accreditation is a deliberate `RegistryAdmin` act, and
        it enforces two gates: the `technical_test_score` must be at least 80
        (otherwise `ERR_TECHNICAL_TEST_FAILED`), and
        `financial_statement_verified` must be true (otherwise
        `ERR_FINANCIAL_STANDING_UNVERIFIED`)."

        Design: Corner/validations/accreditation_gates_technical_then_financial
        """
        resp = api.create_registrar(
            {
                "iana_number": 9101,
                "legal_name": "Failing Registrar",
                "application_fee_cents": 250000,
                "annual_fee_cents": 400000,
                "escrow_deposit_cents": 1000000,
                "technical_test_score": 79,
                "financial_statement_verified": False,
            },
            make_admin_headers(),
        )
        registrar = get_success_data(resp, expected_status=201)

        resp = api.accredit_registrar(registrar["id"], make_admin_headers())
        validate_error(resp, ApiErrorId.ERR_TECHNICAL_TEST_FAILED)
        assert get_registrar(registrar["id"])["status"] == "PENDING_TESTS"

    def test_score_80_passes_technical_gate(self, api):
        """PRD §3.1: "the `technical_test_score` must be at least 80
        (otherwise `ERR_TECHNICAL_TEST_FAILED`), and
        `financial_statement_verified` must be true (otherwise
        `ERR_FINANCIAL_STANDING_UNVERIFIED`)."
        PRD §3.1: "On success the registrar moves from `PENDING_TESTS` to
        `ACTIVE`."

        Design: Corner/validations/accreditation_gates_technical_then_financial
        """
        resp = api.create_registrar(
            {
                "iana_number": 9101,
                "legal_name": "Boundary Registrar",
                "application_fee_cents": 250000,
                "annual_fee_cents": 400000,
                "escrow_deposit_cents": 1000000,
                "technical_test_score": 80,
                "financial_statement_verified": True,
            },
            make_admin_headers(),
        )
        registrar = get_success_data(resp, expected_status=201)

        resp = api.accredit_registrar(registrar["id"], make_admin_headers())
        accredited = get_success_data(resp)
        assert accredited["status"] == "ACTIVE"


class TestUniquenessConstraints:
    def test_duplicate_iana_number_rejected(self, api):
        """PRD §3.1: "A `RegistryAdmin` onboards a prospective registrar by
        creating an applicant record carrying the IANA-assigned `iana_number`
        (unique across all registrars, an integer from 1 to 99999; a
        duplicate is rejected with `ERR_DUPLICATE_IANA_NUMBER`)".

        Design: Corner/validations/duplicate_iana_number_and_case_reference_rejected
        """
        payload = {
            "iana_number": 9110,
            "legal_name": "Dup One",
            "application_fee_cents": 250000,
            "annual_fee_cents": 400000,
            "escrow_deposit_cents": 1000000,
            "technical_test_score": 90,
            "financial_statement_verified": True,
        }
        resp = api.create_registrar(payload, make_admin_headers())
        get_success_data(resp, expected_status=201)

        resp = api.create_registrar(
            {**payload, "legal_name": "Dup Two"}, make_admin_headers())
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_IANA_NUMBER)

    def test_duplicate_case_reference_rejected(self, api):
        """PRD §3.6: "A `RegistryAdmin` lodges an order with a unique
        `case_reference` (a duplicate is rejected with
        `ERR_DUPLICATE_CASE_REFERENCE`)".

        Design: Corner/validations/duplicate_iana_number_and_case_reference_rejected
        """
        registrar, _schedule, domain = setup_active_domain(
            clock="2027-04-29T00:00:00Z", name="dup-domain")

        payload = {
            "case_reference": "CASE-DUP-1",
            "domain_id": domain["id"],
            "action": "SUSPEND",
            "effective_immediately": True,
        }
        resp = api.create_court_order(payload, make_admin_headers())
        get_success_data(resp, expected_status=201)

        resp = api.create_court_order(
            {**payload, "action": "UNSUSPEND"}, make_admin_headers())
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_CASE_REFERENCE)


class TestPriceNoticePeriod:
    def test_notice_under_180_days_rejected_exactly_180_accepted(self, api):
        """PRD §2.7: "For the notice, the gap between `effective_on` and
        `announced_at` must be at least 180 days; a shorter gap is rejected
        with `ERR_PRICE_NOTICE_TOO_SHORT`."

        Submitted at 2027-05-15, effective_on 2027-11-10 is a 179-day gap
        (rejected); 2027-11-11 is exactly 180 days (accepted).

        Design: Corner/calculations/price_notice_under_180_days_rejected
        """
        resp = api.create_price_schedule(
            {
                "create_fee_cents": 700,
                "renew_fee_cents": 850,
                "restore_fee_cents": 12000,
                "transfer_fee_cents": 700,
                "effective_on": "2027-05-15T00:00:00Z",
            },
            make_admin_headers(),
        )
        baseline = get_success_data(resp, expected_status=201)

        # Announce at the baseline's own effective_on so the follow-up
        # submissions measure the 179/180-day notice gap from 2027-05-15.
        set_clock("2027-05-15T00:00:00Z")

        resp = api.create_price_schedule(
            {
                "create_fee_cents": 710,
                "renew_fee_cents": 850,
                "restore_fee_cents": 12000,
                "transfer_fee_cents": 700,
                "effective_on": "2027-11-10T00:00:00Z",
                "supersedes_schedule_id": baseline["id"],
            },
            make_admin_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_PRICE_NOTICE_TOO_SHORT)

        resp = api.create_price_schedule(
            {
                "create_fee_cents": 710,
                "renew_fee_cents": 850,
                "restore_fee_cents": 12000,
                "transfer_fee_cents": 700,
                "effective_on": "2027-11-11T00:00:00Z",
                "supersedes_schedule_id": baseline["id"],
            },
            make_admin_headers(),
        )
        accepted = get_success_data(resp, expected_status=201)
        assert accepted["status"] == "PROPOSED"


class TestRoleSeparation:
    def test_registrar_operator_cannot_accredit_or_set_clock(self, api):
        """PRD §4: the accreditation endpoint is listed as "Accredit a
        `PENDING_TESTS` registrar | RegistryAdmin" and the clock endpoint as
        "Advance the logical clock | RegistryAdmin" in the endpoint table.
        PRD §2.1: "A request whose authenticated role is not permitted for
        the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/registrar_operator_cannot_accredit_or_set_clock
        """
        resp = api.create_registrar(
            {
                "iana_number": 9140,
                "legal_name": "RBAC Registrar",
                "application_fee_cents": 250000,
                "annual_fee_cents": 400000,
                "escrow_deposit_cents": 1000000,
                "technical_test_score": 90,
                "financial_statement_verified": True,
            },
            make_admin_headers(),
        )
        registrar = get_success_data(resp, expected_status=201)
        operator = make_operator_headers(registrar["id"])

        resp = api.accredit_registrar(registrar["id"], operator)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

        resp = api.set_clock("2028-08-27T00:00:00Z", operator)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_registry_finance_peer_role_separation(self, api):
        """PRD §4: the ledger top-up endpoint is listed as "Credit a
        registrar's ledger account | RegistryFinance" and domain
        registration as "Register a second-level domain | RegistrarOperator"
        in the endpoint table.
        PRD §2.1: "A request whose authenticated role is not permitted for
        the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §3.1: "`RegistryFinance` tops the account up by crediting a
        positive `amount_cents` as a `TOP_UP` entry".

        Design: Corner/rbac/registry_finance_cannot_file_domains_but_can_top_up
        """
        registrar, _schedule = setup_active_registrar(
            clock="2027-04-01T00:00:00Z")

        resp = api.create_ledger_topup(
            registrar["id"], 10000, make_finance_headers())
        topup = get_success_data(resp, expected_status=201)
        assert topup["entry_type"] == "TOP_UP"
        assert topup["amount_cents"] == 10000

        resp = api.create_domain(
            {"name": "finance-domain", "registrar_id": registrar["id"],
             "years": 1},
            make_finance_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

        resp = api.create_ledger_topup(
            registrar["id"], 5000,
            make_operator_headers(registrar["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
