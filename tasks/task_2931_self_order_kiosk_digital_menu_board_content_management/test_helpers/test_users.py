"""Role header builders.

Five roles carry an opaque operator identity, so they use fixed identifiers.
Two roles carry an entity-backed identity and MUST be built from the acting
entity's own id: a StoreOperator's X-User-ID is the acting Store.id and a
DeviceAgent's X-User-ID is the acting Device.id.
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_COMPLIANCE_OFFICER,
    ROLE_CONTENT_MANAGER,
    ROLE_DEVICE_AGENT,
    ROLE_PLATFORM_ADMIN,
    ROLE_PRICING_ANALYST,
    ROLE_PRICING_APPROVER,
    ROLE_STORE_OPERATOR,
)
from .types import Headers

# Opaque operator identifiers.
USER_ADMIN = "u_admin_1"
USER_CONTENT_MANAGER = "u_content_1"
USER_ANALYST_1 = "u_analyst_1"
USER_ANALYST_2 = "u_analyst_2"
USER_APPROVER_1 = "u_approver_1"
USER_APPROVER_2 = "u_approver_2"
USER_COMPLIANCE = "u_compliance_1"

ADMIN: Headers = build_user_headers(USER_ADMIN, ROLE_PLATFORM_ADMIN)
CONTENT_MANAGER: Headers = build_user_headers(USER_CONTENT_MANAGER, ROLE_CONTENT_MANAGER)
ANALYST: Headers = build_user_headers(USER_ANALYST_1, ROLE_PRICING_ANALYST)
ANALYST_2: Headers = build_user_headers(USER_ANALYST_2, ROLE_PRICING_ANALYST)
APPROVER: Headers = build_user_headers(USER_APPROVER_1, ROLE_PRICING_APPROVER)
APPROVER_2: Headers = build_user_headers(USER_APPROVER_2, ROLE_PRICING_APPROVER)
COMPLIANCE: Headers = build_user_headers(USER_COMPLIANCE, ROLE_COMPLIANCE_OFFICER)


def make_admin_headers(user_id: str = USER_ADMIN) -> Headers:
    return build_user_headers(user_id, ROLE_PLATFORM_ADMIN)


def make_content_manager_headers(user_id: str = USER_CONTENT_MANAGER) -> Headers:
    return build_user_headers(user_id, ROLE_CONTENT_MANAGER)


def make_analyst_headers(user_id: str = USER_ANALYST_1) -> Headers:
    return build_user_headers(user_id, ROLE_PRICING_ANALYST)


def make_approver_headers(user_id: str = USER_APPROVER_1) -> Headers:
    """A PricingApprover identity; the id is what segregation of duties compares."""
    return build_user_headers(user_id, ROLE_PRICING_APPROVER)


def make_compliance_headers(user_id: str = USER_COMPLIANCE) -> Headers:
    return build_user_headers(user_id, ROLE_COMPLIANCE_OFFICER)


def make_store_operator_headers(store_id: str) -> Headers:
    """StoreOperator identity: X-User-ID is the id of the acting Store."""
    return build_user_headers(store_id, ROLE_STORE_OPERATOR)


def make_device_agent_headers(device_id: str) -> Headers:
    """DeviceAgent identity: X-User-ID is the id of the acting Device."""
    return build_user_headers(device_id, ROLE_DEVICE_AGENT)


def make_role_headers(role: str, user_id: str) -> Headers:
    return build_user_headers(user_id, role)


def headers_without_role(user_id: str = USER_ADMIN) -> Headers:
    """Headers whose X-User-Role is the empty string (blank, never spaces)."""
    return {"X-User-ID": user_id, "X-User-Role": "", "Content-Type": "application/json"}


def headers_without_user_id(role: str = ROLE_PLATFORM_ADMIN) -> Headers:
    """Headers whose X-User-ID is the empty string (blank, never spaces)."""
    return {"X-User-ID": "", "X-User-Role": role, "Content-Type": "application/json"}


def headers_with_unknown_role(user_id: str = USER_ADMIN) -> Headers:
    """A well-formed header pair naming a role outside the seven declared ones."""
    return {"X-User-ID": user_id, "X-User-Role": "NotARole", "Content-Type": "application/json"}
