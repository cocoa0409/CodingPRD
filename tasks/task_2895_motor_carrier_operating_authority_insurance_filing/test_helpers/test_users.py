"""Role headers for the five roles of PRD S2.1.

Two of the five roles are entity-backed: a ``CarrierRep``'s ``X-User-ID`` is
the id of the acting Carrier and an ``InsuranceFiler``'s is the id of the
acting Insurer, so every ownership-gated call must use the per-instance
builders below rather than a shared constant.  The remaining three roles carry
opaque operator identifiers drawn from one shared staff directory, which is
why the segregation-of-duties comparison of S3.6 is made on the identifier.
"""

from typing import Dict, Optional

from prd_bench_local_runner.testing import build_user_headers

from .types import (
    ROLE_CARRIER_REP,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_INSURANCE_FILER,
    ROLE_REGISTRY_ADMIN,
    ROLE_VETTING_ANALYST,
)

# ---------------------------------------------------------------------------
# Opaque operator identifiers (S2.1)
# ---------------------------------------------------------------------------
VETTING_ANALYST_ID = "staff-va-001"
VETTING_ANALYST_ALT_ID = "staff-va-003"
COMPLIANCE_OFFICER_ID = "staff-co-002"
COMPLIANCE_OFFICER_ALT_ID = "staff-co-003"
COMPLIANCE_OFFICER_THIRD_ID = "staff-co-005"
REGISTRY_ADMIN_ID = "staff-ra-004"

# Pre-built headers for the three opaque roles.
VETTING_ANALYST = build_user_headers(VETTING_ANALYST_ID, ROLE_VETTING_ANALYST)
VETTING_ANALYST_ALT = build_user_headers(VETTING_ANALYST_ALT_ID, ROLE_VETTING_ANALYST)
COMPLIANCE_OFFICER = build_user_headers(COMPLIANCE_OFFICER_ID, ROLE_COMPLIANCE_OFFICER)
COMPLIANCE_OFFICER_ALT = build_user_headers(
    COMPLIANCE_OFFICER_ALT_ID, ROLE_COMPLIANCE_OFFICER
)
COMPLIANCE_OFFICER_THIRD = build_user_headers(
    COMPLIANCE_OFFICER_THIRD_ID, ROLE_COMPLIANCE_OFFICER
)
REGISTRY_ADMIN = build_user_headers(REGISTRY_ADMIN_ID, ROLE_REGISTRY_ADMIN)

# The publisher of an application and the officer who activates it must differ
# (S3.6); these two names make that intent explicit at the call site.
PUBLISHING_ANALYST = VETTING_ANALYST
ACTIVATING_OFFICER = COMPLIANCE_OFFICER


def make_carrier_headers(carrier_id: str) -> Dict[str, str]:
    """Headers for the ``CarrierRep`` acting for the carrier with this id."""
    return build_user_headers(carrier_id, ROLE_CARRIER_REP)


def make_insurer_headers(insurer_id: str) -> Dict[str, str]:
    """Headers for the ``InsuranceFiler`` acting for the insurer with this id."""
    return build_user_headers(insurer_id, ROLE_INSURANCE_FILER)


def make_analyst_headers(user_id: str) -> Dict[str, str]:
    """Headers for a ``VettingAnalyst`` with an explicit operator identifier."""
    return build_user_headers(user_id, ROLE_VETTING_ANALYST)


def make_officer_headers(user_id: str) -> Dict[str, str]:
    """Headers for a ``ComplianceOfficer`` with an explicit operator identifier."""
    return build_user_headers(user_id, ROLE_COMPLIANCE_OFFICER)


def make_admin_headers(user_id: str) -> Dict[str, str]:
    """Headers for a ``RegistryAdmin`` with an explicit operator identifier."""
    return build_user_headers(user_id, ROLE_REGISTRY_ADMIN)


def headers_for_role(role: str, user_id: Optional[str] = None) -> Dict[str, str]:
    """Headers for any role, defaulting to that role's canonical test user."""
    defaults = {
        ROLE_CARRIER_REP: "00000000-0000-4000-8000-000000000001",
        ROLE_INSURANCE_FILER: "00000000-0000-4000-8000-000000000002",
        ROLE_VETTING_ANALYST: VETTING_ANALYST_ID,
        ROLE_COMPLIANCE_OFFICER: COMPLIANCE_OFFICER_ID,
        ROLE_REGISTRY_ADMIN: REGISTRY_ADMIN_ID,
    }
    return build_user_headers(user_id or defaults[role], role)


# ---------------------------------------------------------------------------
# Malformed authentication headers (S2.1)
# ---------------------------------------------------------------------------
# A header sent with an EMPTY-STRING value counts as absent.  The value must be
# the zero-length string and never whitespace.
def headers_without_role(user_id: str = REGISTRY_ADMIN_ID) -> Dict[str, str]:
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_without_user_id(role: str = ROLE_REGISTRY_ADMIN) -> Dict[str, str]:
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_with_empty_user_id(role: str = ROLE_REGISTRY_ADMIN) -> Dict[str, str]:
    return {
        "X-User-ID": "",
        "X-User-Role": role,
        "Content-Type": "application/json",
    }


def headers_with_empty_role(user_id: str = REGISTRY_ADMIN_ID) -> Dict[str, str]:
    return {
        "X-User-ID": user_id,
        "X-User-Role": "",
        "Content-Type": "application/json",
    }


NO_HEADERS: Dict[str, str] = {"Content-Type": "application/json"}
