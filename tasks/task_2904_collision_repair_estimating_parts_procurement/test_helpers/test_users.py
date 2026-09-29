"""Acting identities.

Five of the seven roles are shop operators whose `X-User-ID` is opaque to the
contract. Two are entity-backed: an `InsurerAdjuster` is recognised only when
its `X-User-ID` equals the order's `insurer_id`, and a `Customer` only when its
`X-User-ID` equals the order's `customer_id`. Those two therefore have no fixed
identifier at all -- their headers are built from the row they own, which is why
every fixture that needs one takes the entity identifier.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_CUSTOMER,
    ROLE_ESTIMATOR,
    ROLE_INSURER_ADJUSTER,
    ROLE_PARTS_MANAGER,
    ROLE_QC_INSPECTOR,
    ROLE_SHOP_ADMIN,
    ROLE_TECHNICIAN,
    UNDECLARED_ROLE,
)

# ---------------------------------------------------------------------------
# Opaque shop-operator identifiers
# ---------------------------------------------------------------------------
SHOP_ADMIN_USER_ID = "admin-001"
ESTIMATOR_USER_ID = "est-001"
SECOND_ESTIMATOR_USER_ID = "est-002"
PARTS_MANAGER_USER_ID = "parts-001"
TECHNICIAN_USER_ID = "tech-001"
QC_INSPECTOR_USER_ID = "qc-001"
SECOND_QC_INSPECTOR_USER_ID = "qc-002"

TEST_USERS: Dict[str, Dict[str, str]] = {
    "shop_admin": {"user_id": SHOP_ADMIN_USER_ID, "role": ROLE_SHOP_ADMIN},
    "estimator": {"user_id": ESTIMATOR_USER_ID, "role": ROLE_ESTIMATOR},
    "second_estimator": {"user_id": SECOND_ESTIMATOR_USER_ID, "role": ROLE_ESTIMATOR},
    "parts_manager": {"user_id": PARTS_MANAGER_USER_ID, "role": ROLE_PARTS_MANAGER},
    "technician": {"user_id": TECHNICIAN_USER_ID, "role": ROLE_TECHNICIAN},
    "qc_inspector": {"user_id": QC_INSPECTOR_USER_ID, "role": ROLE_QC_INSPECTOR},
    "second_qc_inspector": {
        "user_id": SECOND_QC_INSPECTOR_USER_ID,
        "role": ROLE_QC_INSPECTOR,
    },
}

SHOP_ADMIN_HEADERS = build_user_headers(SHOP_ADMIN_USER_ID, ROLE_SHOP_ADMIN)
ESTIMATOR_HEADERS = build_user_headers(ESTIMATOR_USER_ID, ROLE_ESTIMATOR)
SECOND_ESTIMATOR_HEADERS = build_user_headers(SECOND_ESTIMATOR_USER_ID, ROLE_ESTIMATOR)
PARTS_MANAGER_HEADERS = build_user_headers(PARTS_MANAGER_USER_ID, ROLE_PARTS_MANAGER)
TECHNICIAN_HEADERS = build_user_headers(TECHNICIAN_USER_ID, ROLE_TECHNICIAN)
QC_INSPECTOR_HEADERS = build_user_headers(QC_INSPECTOR_USER_ID, ROLE_QC_INSPECTOR)
SECOND_QC_INSPECTOR_HEADERS = build_user_headers(
    SECOND_QC_INSPECTOR_USER_ID, ROLE_QC_INSPECTOR
)


# ---------------------------------------------------------------------------
# Builders for the five opaque roles, when a test needs a specific identifier
# ---------------------------------------------------------------------------
def make_shop_admin_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_SHOP_ADMIN)


def make_estimator_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_ESTIMATOR)


def make_parts_manager_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_PARTS_MANAGER)


def make_technician_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_TECHNICIAN)


def make_qc_inspector_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_QC_INSPECTOR)


# ---------------------------------------------------------------------------
# Builders for the two entity-backed roles
# ---------------------------------------------------------------------------
def make_insurer_adjuster_headers(insurer_id: str) -> Dict[str, str]:
    """An adjuster is the order's insurer program, addressed by its identifier."""
    return build_user_headers(insurer_id, ROLE_INSURER_ADJUSTER)


def make_customer_headers(customer_id: str) -> Dict[str, str]:
    """An owner is the order's customer row, addressed by its identifier."""
    return build_user_headers(customer_id, ROLE_CUSTOMER)


# ---------------------------------------------------------------------------
# Malformed and unauthorised identities
# ---------------------------------------------------------------------------
def headers_for_role(user_id: str, role: str) -> Dict[str, str]:
    return build_user_headers(user_id, role)


def headers_without_user_id(role: str) -> Dict[str, str]:
    """Headers carrying a role but no `X-User-ID` at all."""
    headers = build_user_headers("placeholder", role)
    headers.pop("X-User-ID", None)
    return headers


def headers_without_role(user_id: str) -> Dict[str, str]:
    """Headers carrying an identifier but no `X-User-Role` at all."""
    headers = build_user_headers(user_id, "placeholder")
    headers.pop("X-User-Role", None)
    return headers


def headers_with_empty_user_id(role: str) -> Dict[str, str]:
    """An empty `X-User-ID`. The value is the empty string, never whitespace."""
    return build_user_headers("", role)


def headers_with_empty_role(user_id: str) -> Dict[str, str]:
    """An empty `X-User-Role`. The value is the empty string, never whitespace."""
    return build_user_headers(user_id, "")


BLANK_HEADERS = build_user_headers("", "")

UNDECLARED_ROLE_HEADERS = build_user_headers("painter-001", UNDECLARED_ROLE)


def headers_with_undeclared_role(user_id: str = "painter-001") -> Dict[str, str]:
    """A role outside the seven the contract declares."""
    return build_user_headers(user_id, UNDECLARED_ROLE)


ALL_ROLE_HEADER_BUILDERS = {
    ROLE_SHOP_ADMIN: make_shop_admin_headers,
    ROLE_ESTIMATOR: make_estimator_headers,
    ROLE_PARTS_MANAGER: make_parts_manager_headers,
    ROLE_TECHNICIAN: make_technician_headers,
    ROLE_QC_INSPECTOR: make_qc_inspector_headers,
    ROLE_INSURER_ADJUSTER: make_insurer_adjuster_headers,
    ROLE_CUSTOMER: make_customer_headers,
}
