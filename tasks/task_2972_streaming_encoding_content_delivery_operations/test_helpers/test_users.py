"""Header builders for the seven roles of PRD §2.1.

Six of the seven roles carry an opaque identity: their `X-User-ID` "is an
operator identifier that is not tied to any persisted entity", so any stable
literal serves.  `VendorOperator` is the single exception and is entity-backed:
"When `X-User-Role` is `VendorOperator`, `X-User-ID` is the `id` of the acting
`CdnVendor` row".  Tests acting as a vendor operator must therefore thread the
real vendor id through ``make_vendor_operator_headers``; the shared
``VENDOR_OPERATOR`` constant below deliberately carries an id that resolves to
nothing so it can only be used where `ERR_VENDOR_IDENTITY_UNKNOWN` is expected.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_CONTENT_OPS,
    ROLE_DELIVERY_ENGINEER,
    ROLE_DRM_OPERATOR,
    ROLE_ENCODING_ENGINEER,
    ROLE_PLATFORM_ADMIN,
    ROLE_QC_ANALYST,
    ROLE_VENDOR_OPERATOR,
    UUID_ABSENT,
)

# --- Opaque-identity operators (§2.1) --------------------------------------
CONTENT_OPS_USER_ID = "op-content-ops-001"
QC_ANALYST_USER_ID = "op-qc-analyst-001"
ENCODING_ENGINEER_USER_ID = "op-encoding-engineer-001"
DRM_OPERATOR_USER_ID = "op-drm-operator-001"
DELIVERY_ENGINEER_USER_ID = "op-delivery-engineer-001"
PLATFORM_ADMIN_USER_ID = "op-platform-admin-001"

CONTENT_OPS: Dict[str, str] = build_user_headers(CONTENT_OPS_USER_ID, ROLE_CONTENT_OPS)
QC_ANALYST: Dict[str, str] = build_user_headers(QC_ANALYST_USER_ID, ROLE_QC_ANALYST)
ENCODING_ENGINEER: Dict[str, str] = build_user_headers(
    ENCODING_ENGINEER_USER_ID, ROLE_ENCODING_ENGINEER
)
DRM_OPERATOR: Dict[str, str] = build_user_headers(DRM_OPERATOR_USER_ID, ROLE_DRM_OPERATOR)
DELIVERY_ENGINEER: Dict[str, str] = build_user_headers(
    DELIVERY_ENGINEER_USER_ID, ROLE_DELIVERY_ENGINEER
)
PLATFORM_ADMIN: Dict[str, str] = build_user_headers(
    PLATFORM_ADMIN_USER_ID, ROLE_PLATFORM_ADMIN
)

# A VendorOperator whose X-User-ID resolves to no stored CdnVendor: usable only
# where ERR_VENDOR_IDENTITY_UNKNOWN is the expected outcome (§2.1, rung 4).
VENDOR_OPERATOR_UNKNOWN: Dict[str, str] = build_user_headers(
    UUID_ABSENT, ROLE_VENDOR_OPERATOR
)

TEST_USERS: Dict[str, Dict[str, str]] = {
    ROLE_CONTENT_OPS: CONTENT_OPS,
    ROLE_QC_ANALYST: QC_ANALYST,
    ROLE_ENCODING_ENGINEER: ENCODING_ENGINEER,
    ROLE_DRM_OPERATOR: DRM_OPERATOR,
    ROLE_DELIVERY_ENGINEER: DELIVERY_ENGINEER,
    ROLE_PLATFORM_ADMIN: PLATFORM_ADMIN,
}

# Per-role opaque identifiers, for tests that need distinct operator ids.
OPAQUE_USER_IDS: Dict[str, str] = {
    ROLE_CONTENT_OPS: CONTENT_OPS_USER_ID,
    ROLE_QC_ANALYST: QC_ANALYST_USER_ID,
    ROLE_ENCODING_ENGINEER: ENCODING_ENGINEER_USER_ID,
    ROLE_DRM_OPERATOR: DRM_OPERATOR_USER_ID,
    ROLE_DELIVERY_ENGINEER: DELIVERY_ENGINEER_USER_ID,
    ROLE_PLATFORM_ADMIN: PLATFORM_ADMIN_USER_ID,
}


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Build headers for an arbitrary user id and role string."""
    return build_user_headers(user_id, role)


def make_content_ops_headers(user_id: str = CONTENT_OPS_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_CONTENT_OPS)


def make_qc_analyst_headers(user_id: str = QC_ANALYST_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_QC_ANALYST)


def make_encoding_engineer_headers(
    user_id: str = ENCODING_ENGINEER_USER_ID,
) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_ENCODING_ENGINEER)


def make_drm_operator_headers(user_id: str = DRM_OPERATOR_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_DRM_OPERATOR)


def make_delivery_engineer_headers(
    user_id: str = DELIVERY_ENGINEER_USER_ID,
) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_DELIVERY_ENGINEER)


def make_platform_admin_headers(user_id: str = PLATFORM_ADMIN_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_PLATFORM_ADMIN)


def make_vendor_operator_headers(vendor_id: str) -> Dict[str, str]:
    """Headers for the operator of one specific `CdnVendor` row (§2.1).

    `vendor_id` must be the `id` returned by the vendor's own registration:
    "if no stored `CdnVendor` has that `id`, the request fails with
    `ERR_VENDOR_IDENTITY_UNKNOWN`".
    """
    assert vendor_id, "make_vendor_operator_headers requires a real CdnVendor id"
    return build_user_headers(vendor_id, ROLE_VENDOR_OPERATOR)


# --- Malformed credentials for rung 1 and rung 2 of §2.6 ------------------
def headers_missing_user_id(role: str = ROLE_CONTENT_OPS) -> Dict[str, str]:
    return {"X-User-Role": role}


def headers_missing_role(user_id: str = CONTENT_OPS_USER_ID) -> Dict[str, str]:
    return {"X-User-ID": user_id}


def headers_empty_user_id(role: str = ROLE_CONTENT_OPS) -> Dict[str, str]:
    """An empty-string X-User-ID -- not a whitespace string (§2.1)."""
    return {"X-User-ID": "", "X-User-Role": role}


def headers_empty_role(user_id: str = CONTENT_OPS_USER_ID) -> Dict[str, str]:
    """An empty-string X-User-Role -- not a whitespace string (§2.1)."""
    return {"X-User-ID": user_id, "X-User-Role": ""}


def headers_whitespace_role(user_id: str = CONTENT_OPS_USER_ID) -> Dict[str, str]:
    """A role header "containing nothing but whitespace" (§2.1)."""
    return {"X-User-ID": user_id, "X-User-Role": "   "}


def headers_whitespace_user_id(role: str = ROLE_CONTENT_OPS) -> Dict[str, str]:
    return {"X-User-ID": "   ", "X-User-Role": role}


def headers_unknown_role(user_id: str = CONTENT_OPS_USER_ID) -> Dict[str, str]:
    return {"X-User-ID": user_id, "X-User-Role": "CatalogWizard"}


def headers_miscased_role(user_id: str = CONTENT_OPS_USER_ID) -> Dict[str, str]:
    """"matching is case-sensitive and exact" (§2.1)."""
    return {"X-User-ID": user_id, "X-User-Role": "contentops"}
