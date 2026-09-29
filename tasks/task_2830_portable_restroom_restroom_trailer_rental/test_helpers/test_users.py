"""Pre-built request identity headers for every role the PRD declares.

For the six operator roles the `X-User-ID` is an opaque operator identifier not
tied to any persisted entity, so a shared constant is the canonical form. For a
`CustomerContact` the `X-User-ID` is the id of the acting rental account, so
ownership-gated calls must be made with `make_customer_contact_headers()`
carrying that account's real id.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

PLATFORM_ADMIN_USER_ID = "admin-1"
SALES_REP_USER_ID = "sales-1"
PERMIT_COORDINATOR_USER_ID = "coordinator-1"
DISPATCH_PLANNER_USER_ID = "planner-1"
DRIVER_OPERATOR_USER_ID = "driver-1"
COMPLIANCE_OFFICER_USER_ID = "officer-1"
SECOND_COMPLIANCE_OFFICER_USER_ID = "officer-2"

TEST_USERS: Dict[str, Dict[str, str]] = {
    "platform_admin_headers": build_user_headers(
        PLATFORM_ADMIN_USER_ID, "PlatformAdmin"
    ),
    "sales_rep_headers": build_user_headers(SALES_REP_USER_ID, "SalesRep"),
    "permit_coordinator_headers": build_user_headers(
        PERMIT_COORDINATOR_USER_ID, "PermitCoordinator"
    ),
    "dispatch_planner_headers": build_user_headers(
        DISPATCH_PLANNER_USER_ID, "DispatchPlanner"
    ),
    "driver_operator_headers": build_user_headers(
        DRIVER_OPERATOR_USER_ID, "DriverOperator"
    ),
    "compliance_officer_headers": build_user_headers(
        COMPLIANCE_OFFICER_USER_ID, "ComplianceOfficer"
    ),
    "second_compliance_officer_headers": build_user_headers(
        SECOND_COMPLIANCE_OFFICER_USER_ID, "ComplianceOfficer"
    ),
    # Fallback only for calls that never touch account ownership.
    "customer_contact_headers": build_user_headers(
        "00000000-0000-0000-0000-000000000000", "CustomerContact"
    ),
}


def make_customer_contact_headers(account_id: str) -> Dict[str, str]:
    """Headers for a CustomerContact acting as the rental account `account_id`.

    Mandatory for every ownership-gated call: raising a contract on the account
    and disputing a charge billed to it both compare the resource's account
    reference to `X-User-ID`.
    """
    return build_user_headers(account_id, "CustomerContact")


def make_platform_admin_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, "PlatformAdmin")


def make_sales_rep_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, "SalesRep")


def make_permit_coordinator_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, "PermitCoordinator")


def make_dispatch_planner_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, "DispatchPlanner")


def make_driver_operator_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, "DriverOperator")


def make_compliance_officer_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_headers_for_role(user_id: str, role: str) -> Dict[str, str]:
    """Headers for an arbitrary role name, including unrecognised ones."""
    return build_user_headers(user_id, role)


def headers_without_role(user_id: str = "anonymous-1") -> Dict[str, str]:
    """Headers carrying X-User-ID but no X-User-Role."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_without_user_id(role: str = "PlatformAdmin") -> Dict[str, str]:
    """Headers carrying X-User-Role but no X-User-ID."""
    return {"X-User-Role": role, "Content-Type": "application/json"}
