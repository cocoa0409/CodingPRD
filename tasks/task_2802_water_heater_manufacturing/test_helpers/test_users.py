"""Header builders for every role the PRD declares.

Seven roles carry an opaque ``X-User-ID`` that the service never resolves to a
row; the segregation-of-duties rules compare those identifiers to each other, so
each helper takes an explicit user id where the tests need to control it.
``SupplierRep`` is the one entity-backed role: its ``X-User-ID`` must be the
``id`` of the Supplier it is acting for, which is why it has its own builder.
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_CERTIFICATION_APPROVER,
    ROLE_COMPLIANCE_ENGINEER,
    ROLE_PLANT_ADMIN,
    ROLE_PLANT_OPERATOR,
    ROLE_QUALITY_INSPECTOR,
    ROLE_SUPPLIER_QUALITY_MANAGER,
    ROLE_SUPPLIER_REP,
    ROLE_WARRANTY_ANALYST,
)

# Canonical opaque user identifiers. Distinct values per actor keep the
# segregation-of-duties comparisons meaningful.
USER_PLANT_ADMIN = "admin-1"
USER_PLANT_OPERATOR = "op-1"
USER_WELD_OPERATOR = "op-weld-1"
USER_INSPECTOR = "insp-1"
USER_INSPECTOR_ALT = "insp-2"
USER_ENGINEER = "eng-1"
USER_ENGINEER_ALT = "eng-2"
USER_APPROVER = "appr-1"
USER_APPROVER_ALT = "appr-2"
USER_SUPPLIER_QUALITY = "sqm-1"
USER_WARRANTY_ANALYST = "wa-1"


def plant_admin_headers(user_id: str = USER_PLANT_ADMIN):
    return build_user_headers(user_id, ROLE_PLANT_ADMIN)


def plant_operator_headers(user_id: str = USER_PLANT_OPERATOR):
    return build_user_headers(user_id, ROLE_PLANT_OPERATOR)


def weld_operator_headers(user_id: str = USER_WELD_OPERATOR):
    """The operator whose id gets pinned onto the lot by the weld transition."""
    return build_user_headers(user_id, ROLE_PLANT_OPERATOR)


def quality_inspector_headers(user_id: str = USER_INSPECTOR):
    return build_user_headers(user_id, ROLE_QUALITY_INSPECTOR)


def compliance_engineer_headers(user_id: str = USER_ENGINEER):
    return build_user_headers(user_id, ROLE_COMPLIANCE_ENGINEER)


def certification_approver_headers(user_id: str = USER_APPROVER):
    return build_user_headers(user_id, ROLE_CERTIFICATION_APPROVER)


def supplier_quality_headers(user_id: str = USER_SUPPLIER_QUALITY):
    return build_user_headers(user_id, ROLE_SUPPLIER_QUALITY_MANAGER)


def warranty_analyst_headers(user_id: str = USER_WARRANTY_ANALYST):
    return build_user_headers(user_id, ROLE_WARRANTY_ANALYST)


def make_supplier_rep_headers(supplier_id: str):
    """Headers for the entity-backed role: X-User-ID is the acting Supplier id."""
    return build_user_headers(supplier_id, ROLE_SUPPLIER_REP)


#: Header builder for each opaque role, keyed by the role name itself.
HEADERS_BY_ROLE = {
    ROLE_PLANT_ADMIN: plant_admin_headers,
    ROLE_PLANT_OPERATOR: plant_operator_headers,
    ROLE_QUALITY_INSPECTOR: quality_inspector_headers,
    ROLE_COMPLIANCE_ENGINEER: compliance_engineer_headers,
    ROLE_CERTIFICATION_APPROVER: certification_approver_headers,
    ROLE_SUPPLIER_QUALITY_MANAGER: supplier_quality_headers,
    ROLE_WARRANTY_ANALYST: warranty_analyst_headers,
}


def headers_for_role(role: str):
    """Return default headers for any opaque role named by the PRD."""
    return HEADERS_BY_ROLE[role]()


def headers_missing_user_id(role: str = ROLE_PLANT_ADMIN):
    """Headers carrying a role but no ``X-User-ID`` at all."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_missing_role(user_id: str = USER_PLANT_ADMIN):
    """Headers carrying a user id but no ``X-User-Role`` at all."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_blank_user_id(role: str = ROLE_PLANT_ADMIN):
    """Headers whose ``X-User-ID`` is present but empty."""
    return {
        "X-User-ID": "",
        "X-User-Role": role,
        "Content-Type": "application/json",
    }


def headers_unknown_role(user_id: str = USER_PLANT_ADMIN):
    """Headers naming a role outside the eight the PRD declares."""
    return build_user_headers(user_id, "FactoryJanitor")


#: Headers with neither authentication header set.
NO_AUTH_HEADERS = {"Content-Type": "application/json"}
