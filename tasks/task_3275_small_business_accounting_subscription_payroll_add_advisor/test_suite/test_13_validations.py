"""Corner / validations — auth header check, role check, segregation of
duties, and the subscription writability gate.
"""

from prd_bench_local_runner.testing import (
    validate_error,
)

from test_helpers import api_errors as E
from test_helpers import factories as f
from test_helpers.fixtures import (
    accept_user,
    activate_subscription,
    cancel_subscription,
    create_company,
    create_company_user,
    create_essentials_plan,
    create_plus_plan,
    create_primary_admin,
    reset_clock,
    setup_company_with_active_subscription,
)
from test_helpers.test_users import (
    MISSING_ID_HEADERS,
    MISSING_ROLE_HEADERS,
    NO_HEADERS,
    PLATFORM_ADMIN,
    make_company_user_headers,
)


class TestMissingContextHeader:
    def test_missing_context_header_returns_400(self, client):
        """PRD 2.1: "Every request carries two headers: `X-User-ID` and
        `X-User-Role`. If either header is missing or malformed, the request
        is rejected with `ERR_MISSING_OR_INVALID_CONTEXT_HEADER` (HTTP 400)
        before any other check runs."

        Design: Corner/validations/missing_context_header_returns_400
        """
        reset_clock(client)
        # No headers at all.
        r1 = client.list_plans(headers=NO_HEADERS)
        validate_error(r1, E.ERR_MISSING_OR_INVALID_CONTEXT_HEADER)
        # Missing role.
        r2 = client.list_plans(headers=MISSING_ROLE_HEADERS)
        validate_error(r2, E.ERR_MISSING_OR_INVALID_CONTEXT_HEADER)
        # Missing id.
        r3 = client.list_plans(headers=MISSING_ID_HEADERS)
        validate_error(r3, E.ERR_MISSING_OR_INVALID_CONTEXT_HEADER)


class TestForbiddenRole:
    def test_forbidden_role_returns_403(self, client):
        """PRD 2.1: "A role that the endpoint's authorization does not admit
        is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
        PRD 4: POST /api/plans is PlatformAdmin-only.

        Design: Corner/validations/forbidden_role_returns_403
        """
        reset_clock(client)
        plan = create_plus_plan(client)
        scenario = setup_company_with_active_subscription(
            client, plan_id=plan["id"], legal_name="Forbidden Co"
        )
        admin_headers = scenario["admin_headers"]
        response = client.create_plan(
            {"plan_code": "HACK", "list_price_cents": 1, "max_seats": 99,
             "feature_inventory": True, "feature_project_profitability": True,
             "feature_multi_currency": True, "feature_bank_rules": True,
             "plan_rank": 99},
            headers=admin_headers,
        )
        validate_error(response, E.ERR_FORBIDDEN_FOR_ROLE)


class TestRequiresPrimaryAdmin:
    def test_requires_primary_admin_for_cancel(self, client):
        """PRD 2.1: "Certain operations are reserved to `PRIMARY_ADMIN` as a
        segregation-of-duties rule — cancelling the subscription, accepting
        a billing transfer on the client side, changing the plan, and
        downloading an export whose `scope` is `FULL_LEDGER`. A
        `COMPANY_ADMIN` cannot substitute; such attempts are rejected with
        `ERR_REQUIRES_PRIMARY_ADMIN` (HTTP 403)."

        Design: Corner/validations/requires_primary_admin_for_cancel
        """
        reset_clock(client)
        plan = create_essentials_plan(client)  # max_seats=3
        company = create_company(client, plan["id"], legal_name="SoD Co")
        admin = create_primary_admin(client, company["id"], email="pa@s.example")
        accept_user(client, company["id"], admin["id"])
        admin_headers = make_company_user_headers(admin["id"])
        # Add a COMPANY_ADMIN and accept them.
        company_admin = create_company_user(
            client, company["id"], actor_headers=admin_headers,
            email="ca@s.example", display_name="CA",
            permission_level="COMPANY_ADMIN",
        )
        accept_user(client, company["id"], company_admin["id"])
        ca_headers = make_company_user_headers(company_admin["id"])
        activate_subscription(client, company["id"], admin["id"])

        response = client.cancel_subscription(
            company["id"],
            {"reason": "by company admin"},
            headers=ca_headers,
        )
        validate_error(response, E.ERR_REQUIRES_PRIMARY_ADMIN)


class TestSubscriptionNotWritable:
    def test_subscription_not_writable_blocks_mutations_in_read_only(self, client):
        """PRD 3.3: "While in `CANCELLED_READ_ONLY`, reads and export
        requests remain possible but other mutations are rejected with
        `ERR_SUBSCRIPTION_NOT_WRITABLE` (HTTP 400)."

        Design: Corner/validations/subscription_not_writable_blocks_mutations_in_read_only
        """
        reset_clock(client)
        plan = create_plus_plan(client)
        scenario = setup_company_with_active_subscription(
            client, plan_id=plan["id"], legal_name="RO Co"
        )
        company = scenario["company"]
        admin = scenario["admin"]
        admin_headers = scenario["admin_headers"]

        cancel_subscription(client, company["id"], admin["id"], reason="test")

        response = client.create_company_user(
            company["id"],
            f.create_company_user_payload(company["id"], email="new2@s.example"),
            headers=admin_headers,
        )
        validate_error(response, E.ERR_SUBSCRIPTION_NOT_WRITABLE)
