"""Corner / state_machines — initial state, terminal lockdown, invalid
transitions, and idempotent re-trigger rejection.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_success,
)

from test_helpers import api_errors as E
from test_helpers import factories as f
from test_helpers.fixtures import (
    accept_user,
    activate_subscription,
    add_bank_connection,
    add_employee,
    add_payroll,
    create_company,
    create_firm,
    create_plus_plan,
    create_primary_admin,
    reset_clock,
    setup_company_with_active_subscription,
)
from test_helpers.test_users import (
    PLATFORM_ADMIN,
    make_company_user_headers,
)


class TestCompanyUserInitialState:
    def test_company_user_initial_state_is_invited(self, client):
        """PRD 3.2: "Invitees are born `INVITED`, and the first user created
        becomes the company's `primary_admin_user_id`."

        Design: Corner/state_machines/company_user_initial_state_is_invited
        """
        reset_clock(client)
        plan = create_plus_plan(client)
        company = create_company(client, plan["id"], legal_name="Sys Co")
        response = client.create_company_user(
            company["id"],
            f.create_company_user_payload(company["id"], email="new@s.example"),
            headers=PLATFORM_ADMIN,
        )
        user = validate_success(response, expected_status=201)
        assert user["user_status"] == "INVITED"


class TestFirmTerminalStateLockdown:
    def test_firm_close_from_terminal_state_rejected(self, client):
        """PRD 3.10: "Closing a firm is terminal and is refused while the
        firm still owns billing on any non-terminal subscription (one in
        `TRIAL`, `ACTIVE`, `PAST_DUE`, or `SUSPENDED` with `billing_owner`
        `FIRM`) or while any of its grants remain in `PENDING_ACCEPT` or
        `ACTIVE`."

        Once CLOSED, the firm is in a terminal state; further close calls
        must be rejected.

        Design: Corner/state_machines/firm_close_from_terminal_state_rejected
        """
        reset_clock(client)
        firm = create_firm(client)
        first = client.close_firm(firm["id"], headers=PLATFORM_ADMIN)
        assert first.status_code in (200, 201), (
            "first close must succeed: {0}".format(first.text)
        )
        # Second close on a CLOSED firm is an invalid transition.
        second = client.close_firm(firm["id"], headers=PLATFORM_ADMIN)
        validate_error(second, E.ERR_INVALID_STATE_TRANSITION)


class TestReconCompleteFromDraftRejected:
    def test_recon_complete_from_draft_rejected_invalid_transition(self, client):
        """PRD 3.7: "Completing a reconciliation requires `difference_cents`
        to be exactly zero" — and the completion transition is defined from
        `IN_PROGRESS` only.

        Design: Corner/state_machines/recon_complete_from_draft_rejected_invalid_transition
        """
        reset_clock(client)
        plan = create_plus_plan(client)
        company = create_company(client, plan["id"], legal_name="Draft Co")
        admin = create_primary_admin(client, company["id"], email="adm@draft.example")
        accept_user(client, company["id"], admin["id"])
        admin_headers = make_company_user_headers(admin["id"])
        activate_subscription(client, company["id"], admin["id"])
        connection = add_bank_connection(
            client, company["id"], admin["id"],
            institution_name="B", external_account_mask="1",
            consent_expires_at="2027-01-01T00:00:00Z",
        )
        create_response = client.create_reconciliation(
            company["id"],
            f.create_reconciliation_payload(
                company["id"], connection["id"],
                statement_period_start="2026-08-01T00:00:00Z",
                statement_period_end="2026-08-31T00:00:00Z",
                statement_ending_balance_cents=0,
            ),
            headers=admin_headers,
        )
        recon = validate_success(create_response, expected_status=201)
        assert recon["recon_status"] == "DRAFT"
        # complete() directly from DRAFT is not a defined transition.
        complete_response = client.complete_reconciliation(
            company["id"], recon["id"], headers=admin_headers
        )
        validate_error(complete_response, E.ERR_INVALID_STATE_TRANSITION)


class TestPayrollTerminateIdempotency:
    def test_payroll_terminate_idempotent_second_call_rejected(self, client):
        """PRD 3.4: "Terminating someone already `TERMINATED` is rejected
        with `ERR_EMPLOYEE_ALREADY_TERMINATED` (HTTP 400)."

        Design: Corner/state_machines/payroll_terminate_idempotent_second_call_rejected
        """
        reset_clock(client)
        plan = create_plus_plan(client)
        scenario = setup_company_with_active_subscription(
            client, plan_id=plan["id"], legal_name="Idem Co"
        )
        company = scenario["company"]
        admin = scenario["admin"]
        admin_headers = scenario["admin_headers"]

        payroll = add_payroll(client, company["id"], admin["id"], "SELF_SERVICE")
        employee = add_employee(
            client, company["id"], admin["id"], payroll["id"],
            legal_name="E", hire_date="2026-09-01T00:00:00Z",
        )
        first = client.terminate_payroll_employee(
            company["id"], employee["id"],
            {"expected_payroll_addon_version": payroll["version"]},
            headers=admin_headers,
        )
        first_body = get_success_data(first)
        assert first_body["employment_status"] == "TERMINATED"

        # Re-read payroll to learn the post-terminate version.
        payroll_after = get_success_data(
            client.get_payroll(company["id"], headers=PLATFORM_ADMIN)
        )
        second = client.terminate_payroll_employee(
            company["id"], employee["id"],
            {"expected_payroll_addon_version": payroll_after["version"]},
            headers=admin_headers,
        )
        validate_error(second, E.ERR_EMPLOYEE_ALREADY_TERMINATED)
