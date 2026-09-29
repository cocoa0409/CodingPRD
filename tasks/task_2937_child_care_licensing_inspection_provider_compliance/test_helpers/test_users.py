"""Role header builders (PRD §2.1).

Three roles are **entity-backed**: an ``Applicant``'s ``X-User-ID`` is the id of
the acting ``Provider``, and both ``LicensingInspector`` and
``ComplaintInvestigator`` carry the id of the acting ``Inspector``.  Those three
therefore have per-instance builders that take the backing row's id.

The remaining five roles carry opaque identity.  They get default operator
identifiers plus builders that accept an explicit identifier, because the
segregation-of-duties rules of §2.8 compare those identifiers to each other and
so need distinct values (e.g. the supervisor who approves a plan versus the one
who issues enforcement, or the administrator who issues an action versus the one
who decides its appeal).
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import (
    ROLE_AGENCY_ADMIN,
    ROLE_APPLICANT,
    ROLE_BACKGROUND_CHECK_UNIT,
    ROLE_COMPLAINT_INTAKE_SPECIALIST,
    ROLE_COMPLAINT_INVESTIGATOR,
    ROLE_LICENSING_INSPECTOR,
    ROLE_LICENSING_SUPERVISOR,
    ROLE_PUBLIC_PORTAL_READER,
)

# ─── Opaque operator identifiers ───────────────────────────────────────
ADMIN_1 = "admin-1"
ADMIN_2 = "admin-2"
SUPERVISOR_1 = "sup-1"
SUPERVISOR_2 = "sup-2"
SUPERVISOR_3 = "sup-3"
INTAKE_1 = "intake-1"
BGU_1 = "bgu-1"
PUBLIC_1 = "public-1"


# ─── Opaque-identity roles ─────────────────────────────────────────────
def admin_headers(user_id: str = ADMIN_1) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_AGENCY_ADMIN)


def supervisor_headers(user_id: str = SUPERVISOR_1) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_LICENSING_SUPERVISOR)


def intake_headers(user_id: str = INTAKE_1) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_COMPLAINT_INTAKE_SPECIALIST)


def bgu_headers(user_id: str = BGU_1) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_BACKGROUND_CHECK_UNIT)


def public_headers(user_id: str = PUBLIC_1) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_PUBLIC_PORTAL_READER)


# ─── Entity-backed roles ───────────────────────────────────────────────
def make_applicant_headers(provider_id: str) -> Dict[str, str]:
    """``X-User-ID`` is the id of the acting Provider."""
    return build_user_headers(provider_id, ROLE_APPLICANT)


def make_inspector_headers(inspector_id: str) -> Dict[str, str]:
    """``X-User-ID`` is the id of the acting Inspector."""
    return build_user_headers(inspector_id, ROLE_LICENSING_INSPECTOR)


def make_investigator_headers(inspector_id: str) -> Dict[str, str]:
    """``X-User-ID`` is likewise the id of the acting Inspector."""
    return build_user_headers(inspector_id, ROLE_COMPLAINT_INVESTIGATOR)


# ─── Malformed identity envelopes (PRD §2.1) ───────────────────────────
def headers_without_user_id(role: str) -> Dict[str, str]:
    """Role only — the ``X-User-ID`` header is absent entirely."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_with_blank_user_id(role: str) -> Dict[str, str]:
    """``X-User-ID`` sent as an empty string.  It must be exactly ``""`` — a
    whitespace-only value is rejected by the HTTP client and never reaches the
    server, so it would not exercise the server-side rule at all."""
    return {"X-User-ID": "", "X-User-Role": role, "Content-Type": "application/json"}


def headers_without_role(user_id: str) -> Dict[str, str]:
    """``X-User-Role`` absent entirely."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_with_unknown_role(user_id: str, role: str = "Auditor") -> Dict[str, str]:
    """A role name outside the eight the agency recognises."""
    return build_user_headers(user_id, role)


def no_identity_headers() -> Dict[str, str]:
    """Neither identity header — used by provider creation, the one endpoint
    that sends no ``X-User-ID``."""
    return {"Content-Type": "application/json"}


def applicant_creation_headers() -> Dict[str, str]:
    """Provider creation declares the ``Applicant`` role but carries no
    ``X-User-ID``, because the identifier the applicant will use from then on is
    the id this call returns."""
    return headers_without_user_id(ROLE_APPLICANT)


# ─── Convenience map consumed by test_suite/conftest.py ────────────────
TEST_USERS: Dict[str, Dict[str, str]] = {
    "admin_headers": admin_headers(),
    "admin2_headers": admin_headers(ADMIN_2),
    "supervisor_headers": supervisor_headers(),
    "supervisor2_headers": supervisor_headers(SUPERVISOR_2),
    "intake_headers": intake_headers(),
    "bgu_headers": bgu_headers(),
    "public_headers": public_headers(),
}
