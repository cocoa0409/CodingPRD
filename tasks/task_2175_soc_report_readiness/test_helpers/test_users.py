"""Pre-built role headers for every role in the PRD."""

from prd_bench_local_runner.testing import build_user_headers

# Opaque operator identifiers. For every role but SubserviceContact the PRD
# treats X-User-ID as an opaque operator id that is never compared to an
# entity's id, so a shared constant is safe.
COMPLIANCE_LEAD_ID = "cl-1"
CONTROL_OWNER_ID = "own-1"
EVIDENCE_REVIEWER_ID = "rev-1"
AUDITOR_ID = "aud-1"
ACCOUNT_EXECUTIVE_ID = "ae-1"
PLATFORM_ADMIN_ID = "pa-1"

TEST_USERS = {
    "compliance_lead_headers": build_user_headers(COMPLIANCE_LEAD_ID, "ComplianceLead"),
    "control_owner_headers": build_user_headers(CONTROL_OWNER_ID, "ControlOwner"),
    "evidence_reviewer_headers": build_user_headers(EVIDENCE_REVIEWER_ID, "EvidenceReviewer"),
    "auditor_headers": build_user_headers(AUDITOR_ID, "Auditor"),
    "account_executive_headers": build_user_headers(ACCOUNT_EXECUTIVE_ID, "AccountExecutive"),
    "platform_admin_headers": build_user_headers(PLATFORM_ADMIN_ID, "PlatformAdmin"),
}

# Headers with no identity at all, for the missing-header check.
NO_AUTH_HEADERS = {"Content-Type": "application/json"}


def make_compliance_lead_headers(user_id: str) -> dict:
    """ComplianceLead acting as a specific opaque operator id."""
    return build_user_headers(user_id, "ComplianceLead")


def make_control_owner_headers(user_id: str) -> dict:
    """ControlOwner acting as a specific opaque operator id; pass the value that
    was assigned as the control's owner_user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "ControlOwner")


def make_evidence_reviewer_headers(user_id: str) -> dict:
    """EvidenceReviewer acting as a specific opaque operator id."""
    return build_user_headers(user_id, "EvidenceReviewer")


def make_auditor_headers(user_id: str) -> dict:
    """Auditor acting as a specific opaque operator id."""
    return build_user_headers(user_id, "Auditor")


def make_account_executive_headers(user_id: str) -> dict:
    """AccountExecutive acting as a specific opaque operator id."""
    return build_user_headers(user_id, "AccountExecutive")


def make_platform_admin_headers(user_id: str) -> dict:
    """PlatformAdmin acting as a specific opaque operator id."""
    return build_user_headers(user_id, "PlatformAdmin")


def make_subservice_contact_headers(subservice_organization_id: str) -> dict:
    """SubserviceContact headers. X-User-ID *is* the acting subservice
    organization's own id, so always pass the real organization's id."""
    return build_user_headers(subservice_organization_id, "SubserviceContact")


def make_headers(user_id: str, role: str) -> dict:
    """Arbitrary (user_id, role) pair, including undeclared role strings."""
    return build_user_headers(user_id, role)
