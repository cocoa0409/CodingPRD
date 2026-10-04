"""Corner coverage for the error catalogue triggers and the role matrix."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    validate_success,
    validate_error,
    get_success_data,
    onboard_partner,
    setup_program,
    setup_program_with_account,
    setup_wound_down_program_with_transfer,
    issue_account,
    open_negotiation,
    draft_agreement,
    post_purchase,
    make_cardholder_headers,
    make_retail_partner_analyst_headers,
    roll_into_winding_down,
    propose_transfer,
    accept_transfer,
    program_summary,
)

UNAUTH_HEADERS = {}
ADMIN = TEST_USERS["program_admin_headers"]
UNDERWRITER = TEST_USERS["underwriter_headers"]
APPLICANT = TEST_USERS["applicant_headers"]
COBRAND = TEST_USERS["co_brand_issuer_headers"]


class TestErrorTriggers:

    def test_missing_required_field_on_create_is_invalid_request(self, api, admin_headers):
        """PRD §2.11: "Existence resolution is third, reporting
        `ERR_RESOURCE_NOT_FOUND` (HTTP 404)." PRD §2.11: "Every request passes
        through a fixed validation sequence".

        Design: Corner/errors/invalid_request_triggerable_on_missing_required_field
        """
        get_success_data(api.set_clock("2026-09-01T00:00:00Z", admin_headers))
        resp = api.create_partner({"loyalty_program_code": "NO_NAME"}, admin_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_stale_program_version_on_a_renewal_round_is_rejected(self, api, admin_headers):
        """PRD §2.8: "The second is the opening of a renewal round against a
        credit program, which must carry `expected_program_version`; if that value
        does not match the program's current `version`, the request is rejected
        with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/errors/stale_version_triggerable_on_renewal_round
        """
        _partner, _agreement, program = setup_program(api)
        resp = api.open_renewal(program["id"], program["version"] - 1,
                                "RENEWAL_NEGOTIATION", admin_headers)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)

        refreshed = validate_success(api.get_credit_program(program["id"], admin_headers), 200)
        assert refreshed["program_status"] == "ACTIVE"
        assert refreshed["version"] == program["version"]

    def test_an_unsupported_promo_term_is_rejected(self, api, admin_headers):
        """PRD §3.4: "the requested term must be a member of the supported term
        set — the only permissible values are 6, 12, 18, and 24 months — and a
        term outside that set is rejected with `ERR_INVALID_PROMO_TERM` (HTTP 422)."

        Design: Corner/errors/invalid_promo_term_triggerable
        """
        _partner, _agreement, _program, account = setup_program_with_account(api, credit_limit_cents=500000)
        resp = api.create_transaction(
            {"account_id": account["id"], "merchant_name": "Coldgate Rope",
             "amount_cents": 50000, "transaction_channel": "IN_STORE",
             "promo_requested": True, "promo_term_months": 9},
            make_cardholder_headers(account["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_PROMO_TERM, 422)

    def test_an_unallocated_path_id_is_resource_not_found(self, api, admin_headers):
        """PRD §2.9: "Every path-segment identifier and every body-referenced
        foreign key must resolve to an existing resource before an operation
        proceeds, and a failure to resolve is reported with
        `ERR_RESOURCE_NOT_FOUND` (HTTP 404)."

        Design: Corner/errors/resource_not_found_triggerable_on_filtered_list_absent_id
        """
        get_success_data(api.set_clock("2026-09-01T00:00:00Z", admin_headers))
        resp = api.get_program_summary(NON_EXISTENT_UUID, admin_headers)
        validate_error(resp, ApiErrorId.ERR_RESOURCE_NOT_FOUND, 404)

    def test_an_unauthorized_role_is_rejected_before_the_operation_runs(self, api, admin_headers):
        """PRD §2.11: "Authorization is evaluated second, so a request from a
        permitted-but-insufficient role reports `ERR_UNAUTHORIZED` (HTTP 403)
        before any resource is loaded." PRD §2.1: "A request that carries a valid
        role which is not permitted for the requested operation is rejected with
        `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/errors/unauthenticated_and_unauthorized_error_triggerable
        """
        _partner, _agreement, _program, _account, transfer = setup_wound_down_program_with_transfer(
            api, account_balance_cents=100, accepted=False
        )
        resp = api.accept_transfer(transfer["id"], "ISSUER", UNDERWRITER)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)

        refreshed = validate_success(api.get_transfer(transfer["id"], admin_headers), 200)
        assert refreshed["transfer_status"] == "PROPOSED", "the denial changed nothing"


class TestRoleMatrix:

    def test_underwriter_cannot_suspend_a_partner(self, api, admin_headers):
        """PRD §2.1: "A request that carries a valid role which is not permitted
        for the requested operation is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        Partner suspension is a `ProgramAdmin` operation.

        Design: Corner/rbac/rbac_underwriter_cannot_suspend_partner
        """
        partner = onboard_partner(api)
        resp = api.suspend_partner(partner["id"], UNDERWRITER)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)

        refreshed = validate_success(api.get_partner(partner["id"], admin_headers), 200)
        assert refreshed["partner_status"] == "ACTIVE"

    def test_analyst_reads_their_own_partner_and_program_read_only(self, api, admin_headers):
        """PRD §2.4: "a `RetailPartnerAnalyst` may only read the resources tied to
        their `RetailPartner`". PRD §2.1: "Ownership checks on any resource that
        references a `RetailPartner` therefore compare the resource's partner
        foreign-key field to `X-User-ID`".

        Design: Corner/rbac/rbac_retail_partner_analyst_reads_own_partner_and_program
        """
        partner, _agreement, program = setup_program(api)
        analyst = make_retail_partner_analyst_headers(partner["id"])

        summary = validate_success(api.get_program_summary(program["id"], analyst), 200)
        assert summary["program_status"] == "ACTIVE"
        own = validate_success(api.get_partner(partner["id"], analyst), 200)
        assert own["id"] == partner["id"]
        assert summary["outstanding_receivable_cents"] == 0
        assert summary["free_look_exposure_cents"] == 0

    def test_a_cardholder_cannot_decide_an_application(self, api, admin_headers):
        """PRD §2.1: "A request that carries a valid role which is not permitted
        for the requested operation is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        Decisioning belongs to the `Underwriter`.

        Design: Corner/rbac/rbac_cardholder_cannot_decide_own_application
        """
        _partner, _agreement, program = setup_program(api)
        application = get_success_data(
            api.create_application({"program_id": program["id"], "source_channel": "DIGITAL",
                                    "requested_credit_limit_cents": 150000}, APPLICANT), 201
        )
        resp = api.decide_application(application["id"], make_cardholder_headers(NON_EXISTENT_UUID))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)

        refreshed = validate_success(api.get_application(application["id"], admin_headers), 200)
        assert refreshed["application_status"] == "PENDING"

    def test_the_underwriter_approves_and_stamps_the_limit(self, api, admin_headers):
        """PRD §3.3: "On approval the application becomes `APPROVED`, its
        `approved_credit_limit_cents` is set equal to the requested limit".

        Design: Corner/rbac/rbac_underwriter_can_decide_application
        """
        _partner, _agreement, program = setup_program(api)
        application = get_success_data(
            api.create_application({"program_id": program["id"], "source_channel": "DIGITAL",
                                    "requested_credit_limit_cents": 150000}, APPLICANT), 201
        )
        decided = validate_success(api.decide_application(application["id"], UNDERWRITER), 200)
        assert decided["application_status"] == "APPROVED"
        assert decided["approved_credit_limit_cents"] == 150000

    def test_the_co_brand_issuer_can_accept_a_transfer_as_issuer(self, api, admin_headers):
        """PRD §3.9: "The delegated purchase right held by a `CoBrandIssuer` is
        exercised through the acceptance step rather than through proposal, and a
        `CoBrandIssuer` may accept only as the `ISSUER` buyer."

        Design: Corner/rbac/rbac_cobrand_issuer_can_accept_transfer_as_issuer
        """
        _partner, _agreement, _program, _account, transfer = setup_wound_down_program_with_transfer(
            api, buyer_role="ISSUER", account_balance_cents=100, accepted=False
        )
        accepted = validate_success(api.accept_transfer(transfer["id"], "ISSUER", COBRAND), 200)
        assert accepted["transfer_status"] == "AGREEMENT_REACHED"
        assert accepted["accepted_by_role"] == "ISSUER"