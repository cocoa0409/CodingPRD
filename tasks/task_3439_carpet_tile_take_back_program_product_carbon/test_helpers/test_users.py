"""Pre-built role headers for every role in PRD §2.1.

All six roles are opaque-identity: the server never compares X-User-ID to any
entity id. Ownership instead compares X-User-ID against recorded strings —
``created_by`` for Specifier-owned resources and the site's ``contractor_name``
for Installer-side operations (validation priority 3) — and segregation of
duties compares it against ``submitted_by`` / ``created_by``.

Use the shared constants in TEST_USERS only when the call is not ownership- or
segregation-gated. Whenever a fixture or test needs the caller to own a
specific resource (or to differ from its creator), build headers with the
per-instance ``make_*_headers`` builders:

- Installer acting on a site: ``make_installer_headers(site["contractor_name"])``
- Specifier acting on their own resource:
  ``make_specifier_headers(resource["created_by"])``
- Verifier clearing a report: any id != report["submitted_by"]
  (the shared verifier_headers, "ver-dana", already differs from the shared
  manager id "sm-carol" used to submit in the standard fixtures).
- ClaimsApprover reviewing a claim: any id != claim["created_by"].
"""
from prd_bench_local_runner.testing import build_user_headers

# Canonical operator identities used across the standard fixtures. These are
# plain opaque strings (PRD §2.1); they are conventions of this suite, chosen
# so ownership and segregation-of-duties relationships are satisfiable.
DEFAULT_ADMIN_ID = "pa-admin"
DEFAULT_MANAGER_ID = "sm-carol"
DEFAULT_VERIFIER_ID = "ver-dana"
DEFAULT_APPROVER_ID = "ap-erin"
DEFAULT_SPECIFIER_ID = "spec-ada"
DEFAULT_INSTALLER_ID = "inst-bob"

# A second specifier identity, for created_by ownership-mismatch tests.
ALT_SPECIFIER_ID = "spec-eve"

TEST_USERS = {
    "admin_headers": build_user_headers(DEFAULT_ADMIN_ID, "PlatformAdmin"),
    "manager_headers": build_user_headers(DEFAULT_MANAGER_ID, "SustainabilityManager"),
    "verifier_headers": build_user_headers(DEFAULT_VERIFIER_ID, "Verifier"),
    "approver_headers": build_user_headers(DEFAULT_APPROVER_ID, "ClaimsApprover"),
    "specifier_headers": build_user_headers(DEFAULT_SPECIFIER_ID, "Specifier"),
    "installer_headers": build_user_headers(DEFAULT_INSTALLER_ID, "Installer"),
}


def make_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SustainabilityManager")


def make_verifier_headers(user_id: str) -> dict:
    """Verifier headers. For CLEAR/FAIL the id must differ from the report's
    submitted_by (segregation of duties)."""
    return build_user_headers(user_id, "Verifier")


def make_approver_headers(user_id: str) -> dict:
    """ClaimsApprover headers. For review the id must differ from the claim's
    created_by (segregation of duties)."""
    return build_user_headers(user_id, "ClaimsApprover")


def make_specifier_headers(user_id: str) -> dict:
    """Specifier headers. For ownership-gated calls pass the resource's
    created_by (site registration, order/take-back cancel, package issuance
    against sites the caller registered)."""
    return build_user_headers(user_id, "Specifier")


def make_installer_headers(user_id: str) -> dict:
    """Installer headers. For ownership-gated calls (install, decommission,
    zone lay, order match/complete, take-back schedule/collect) pass the
    site's recorded contractor_name string."""
    return build_user_headers(user_id, "Installer")
