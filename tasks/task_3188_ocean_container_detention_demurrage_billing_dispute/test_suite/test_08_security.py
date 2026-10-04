"""Security surface: auth context, role authorization, ownership, not-found."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    api_client,
    create_account,
    create_active_contract,
    create_terminal,
    create_return_location,
    create_available_container,
    gate_out,
    make_customer_rep_headers,
    set_clock,
    setup_empty_returned_container,
    setup_issued_invoice,
    validate_error,
    validate_success,
)

CM = {"X-User-ID": "cm-1", "X-User-Role": "ContractManager"}
TO = {"X-User-ID": "to-1", "X-User-Role": "TerminalOperator"}
EC = {"X-User-ID": "ec-1", "X-User-Role": "EquipmentController"}
BA = {"X-User-ID": "ba-1", "X-User-Role": "BillingAgent"}
DIR = {"X-User-ID": "dir-1", "X-User-Role": "CreditDirector"}


class TestAuthContext:
    def test_missing_role_header_rejected(self):
        """PRD §2.1: "A request missing either header, or presenting a role not
        in this list, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

        Design: Corner/validations/missing_auth_header_rejected
        """
        resp = api_client.list_terminals({"X-User-ID": "some-user"})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

    def test_invalid_role_beats_not_found(self):
        """PRD §2.10: "Authentication context comes first: missing or malformed
        identity headers produce
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` before anything else is
        examined."

        Design: Corner/validations/auth_precedes_not_found
        """
        resp = api_client.get_container(
            NON_EXISTENT_UUID, {"X-User-ID": "x", "X-User-Role": "NotARealRole"}
        )
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


class TestNotFound:
    def test_get_container_unknown_id_returns_not_found_envelope(self):
        """PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."
        PRD §2.2: "The `message` provides a human-readable explanation of what
        went wrong."

        Design: Corner/entities/container_get_not_found
        """
        resp = api_client.get_container(NON_EXISTENT_UUID, BA)
        data = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        assert isinstance(data.get("message"), str) and data["message"]


class TestRoleAuthorization:
    def test_customer_rep_cannot_issue_invoice(self):
        """PRD §2.1: "When the headers are valid but the role is not permitted
        to perform the requested operation, the request is rejected with
        `ERR_FORBIDDEN`."
        PRD §4: issue-invoice is authorized for BillingAgent only.

        Design: Corner/rbac/customer_rep_cannot_issue_invoice
        """
        ctx = setup_empty_returned_container(
            account_overrides={"account_code": "ACCT-RB", "legal_name": "RbacCo"},
            contract_overrides={"contract_ref": "CTR-RB", "demurrage_free_days": 0},
            container_overrides={"container_number": "MATU0001217"},
            gate_out_clock="2026-09-04T12:00:00Z",
            with_holiday=False,
        )
        resp = api_client.issue_invoice(
            ctx["container"]["id"], make_customer_rep_headers(ctx["account"]["id"])
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_customer_rep_cannot_dispute_other_accounts_invoice(self):
        """PRD §2.1: "When `X-User-Role` is `CustomerRep`, `X-User-ID` is the
        `id` of the acting `CustomerAccount`; ownership checks on any resource
        that references a `CustomerAccount` compare the resource's foreign-key
        field to `X-User-ID` — a customer representative filing a dispute, for
        example, may only act on invoices billed to the account whose `id` they
        present, and any attempt to act on another account's resource is
        rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/customer_rep_cannot_dispute_other_accounts_invoice
        """
        ctx = setup_issued_invoice(
            account_overrides={"account_code": "ACCT-XX", "legal_name": "Owner Co"},
            contract_overrides={"contract_ref": "CTR-XX", "demurrage_free_days": 0},
            container_overrides={"container_number": "MATU0001225"},
            gate_out_clock="2026-09-04T12:00:00Z",
            with_holiday=False,
        )
        intruder = create_account(account_code="ACCT-YY", legal_name="Intruder Co")
        resp = api_client.create_dispute(
            ctx["invoice"]["id"],
            {
                "dispute_reason": "OTHER",
                "contested_amount_cents": 5000,
                "evidence_window_start": "2026-09-02T00:00:00Z",
                "evidence_window_end": "2026-09-04T00:00:00Z",
                "evidence_summary": "intrusion",
            },
            make_customer_rep_headers(intruder["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_billing_agent_cannot_write_off(self):
        """PRD §2.1: "A `CreditDirector` holds unbounded credit authority,
        performs write-offs, and reverses applied waivers."
        PRD §2.1: "When the headers are valid but the role is not permitted to
        perform the requested operation, the request is rejected with
        `ERR_FORBIDDEN`."

        Design: Corner/rbac/billing_agent_cannot_write_off
        """
        ctx = setup_issued_invoice(
            account_overrides={"account_code": "ACCT-BA", "legal_name": "BaDeny Co"},
            contract_overrides={
                "contract_ref": "CTR-BA", "demurrage_free_days": 0,
                "effective_to": "2027-06-30T00:00:00Z",
            },
            container_overrides={"container_number": "MATU0001233"},
            gate_out_clock="2026-09-04T12:00:00Z",
            with_holiday=False,
        )
        set_clock("2026-12-05T12:00:00Z", BA)
        resp = api_client.write_off_invoice(
            ctx["invoice"]["id"], {"justification": "agent attempt"}, BA
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
