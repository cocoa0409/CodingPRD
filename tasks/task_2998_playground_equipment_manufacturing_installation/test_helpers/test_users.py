"""Pre-built role headers for every role in the PRD.

Five of the six roles carry an opaque operator identifier that the server never
compares to any entity's id, so a shared constant is the canonical form for
them.  `InstallerOperator` is different: its `X-User-ID` is the id of the acting
`CertifiedInstaller` and every job-ownership check compares `installer_id`
against it, so ownership-gated calls MUST use make_installer_operator_headers()
with the real installer id.

Two segregation-of-duties rules ride on the recorded opaque identifiers, so the
consultant, officer and auditor constants below are deliberately distinct
values, and a second auditor identity is provided for the post-installation
audit that may not be filed by the installation inspector.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

# Canonical operator identifiers.  They match the identities used throughout the
# fixtures so that segregation-of-duties comparisons behave predictably.
ADMIN_USER_ID = "admin-1"
CONSULTANT_USER_ID = "consultant-1"
CONSULTANT_2_USER_ID = "consultant-2"
OFFICER_USER_ID = "officer-1"
OFFICER_2_USER_ID = "officer-2"
CLIENT_USER_ID = "client-1"
AUDITOR_USER_ID = "auditor-1"
AUDITOR_2_USER_ID = "auditor-2"
INSTALLER_FALLBACK_USER_ID = "installer-not-an-entity"


TEST_USERS: Dict[str, Dict[str, str]] = {
    "manufacturer_admin_headers": build_user_headers(
        ADMIN_USER_ID, "ManufacturerAdmin"
    ),
    "design_consultant_headers": build_user_headers(
        CONSULTANT_USER_ID, "DesignConsultant"
    ),
    "design_consultant_2_headers": build_user_headers(
        CONSULTANT_2_USER_ID, "DesignConsultant"
    ),
    "compliance_officer_headers": build_user_headers(
        OFFICER_USER_ID, "ComplianceOfficer"
    ),
    "compliance_officer_2_headers": build_user_headers(
        OFFICER_2_USER_ID, "ComplianceOfficer"
    ),
    "client_representative_headers": build_user_headers(
        CLIENT_USER_ID, "ClientRepresentative"
    ),
    "safety_auditor_headers": build_user_headers(AUDITOR_USER_ID, "SafetyAuditor"),
    "safety_auditor_2_headers": build_user_headers(AUDITOR_2_USER_ID, "SafetyAuditor"),
    # InstallerOperator is entity_backed; this shared constant is a fallback for
    # tests that never reach an ownership check (role-denial, 404, bad payload).
    "installer_operator_headers": build_user_headers(
        INSTALLER_FALLBACK_USER_ID, "InstallerOperator"
    ),
}


def make_installer_operator_headers(installer_id: str) -> Dict[str, str]:
    """Headers for an `InstallerOperator` acting as the given CertifiedInstaller.

    Pass the real CertifiedInstaller id: every operator-driven job trigger
    compares the acting X-User-ID against the job's installer_id.
    """
    return build_user_headers(installer_id, "InstallerOperator")


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Arbitrary identity/role pair — used by header-validation tests."""
    return build_user_headers(user_id, role)


def headers_without_user_id(role: str) -> Dict[str, str]:
    """Headers with X-User-ID absent entirely."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_without_role(user_id: str) -> Dict[str, str]:
    """Headers with X-User-Role absent entirely."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_with_empty_user_id(role: str) -> Dict[str, str]:
    """Headers whose X-User-ID is present but empty.

    The value must be the empty string, never a run of spaces: a whitespace
    value can be rejected client-side and would never reach the server.
    """
    return {"X-User-ID": "", "X-User-Role": role, "Content-Type": "application/json"}


def headers_with_empty_role(user_id: str) -> Dict[str, str]:
    """Headers whose X-User-Role is present but empty."""
    return {
        "X-User-ID": user_id,
        "X-User-Role": "",
        "Content-Type": "application/json",
    }
