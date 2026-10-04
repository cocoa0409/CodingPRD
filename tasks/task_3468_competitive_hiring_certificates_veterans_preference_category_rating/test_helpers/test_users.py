"""Pre-built role headers for every role in the PRD (§2.1).

Applicant is entity-backed: X-User-ID must equal the Applicant.id, so
ownership-gated calls MUST use make_applicant_headers(applicant["id"]).
The registration nuance (PRD §2.1): under the Applicant role the supplied
X-User-ID is ignored at registration, so the shared constant is safe there.

SME authorship binds X-User-ID to the assessment's recorded sme_user_id, so
submit/resubmit calls MUST use make_sme_headers(<the creating X-User-ID>).

The other roles are opaque operator IDs; the shared constants are canonical.
"""
from prd_bench_local_runner.testing import build_user_headers

# Opaque operator IDs used across the suite. "sme-1"/"suit-1"/"sec-1" are
# distinct so segregation-of-duties checks pass by default.
SME_USER_ID = "sme-1"
SUITABILITY_REVIEWER_ID = "suit-1"
SECURITY_ADJUDICATOR_ID = "sec-1"
OPM_DELEGATE_ID = "opm-1"
HR_SPECIALIST_ID = "hr-1"
HIRING_MANAGER_ID = "hm-1"
SELECTING_OFFICIAL_ID = "so-1"
PLATFORM_ADMIN_ID = "admin-1"

TEST_USERS = {
    # Entity-backed role: fallback for non-ownership calls only (e.g. registration,
    # where the supplied X-User-ID is ignored, or 403/404 denial probes).
    "applicant_headers": build_user_headers("applicant-1", "Applicant"),
    # Opaque roles: shared constant is the canonical form.
    "hr_specialist_headers": build_user_headers(HR_SPECIALIST_ID, "HRSpecialist"),
    "hiring_manager_headers": build_user_headers(HIRING_MANAGER_ID, "HiringManager"),
    "sme_headers": build_user_headers(SME_USER_ID, "SME"),
    "selecting_official_headers": build_user_headers(SELECTING_OFFICIAL_ID, "SelectingOfficial"),
    "opm_delegate_headers": build_user_headers(OPM_DELEGATE_ID, "OPMDelegate"),
    "suitability_reviewer_headers": build_user_headers(SUITABILITY_REVIEWER_ID, "SuitabilityReviewer"),
    "security_adjudicator_headers": build_user_headers(SECURITY_ADJUDICATOR_ID, "SecurityAdjudicator"),
    "platform_admin_headers": build_user_headers(PLATFORM_ADMIN_ID, "PlatformAdmin"),
}


def make_applicant_headers(user_id: str) -> dict:
    """Entity-backed role: pass the actual Applicant.id whenever the call is
    ownership-gated (read own record/applications/documents/appeals/offers,
    apply, upload, appeal, respond)."""
    return build_user_headers(user_id, "Applicant")


def make_sme_headers(user_id: str) -> dict:
    """Opaque role, but submit/resubmit requires X-User-ID == assessment.sme_user_id.
    Pass the same id used at assessment creation."""
    return build_user_headers(user_id, "SME")


def make_hr_specialist_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "HRSpecialist")


def make_hiring_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "HiringManager")


def make_selecting_official_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SelectingOfficial")


def make_opm_delegate_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "OPMDelegate")


def make_suitability_reviewer_headers(user_id: str) -> dict:
    """Distinct ids per offer for segregation-of-duties control."""
    return build_user_headers(user_id, "SuitabilityReviewer")


def make_security_adjudicator_headers(user_id: str) -> dict:
    """Must differ from the offer's suitability reviewer id."""
    return build_user_headers(user_id, "SecurityAdjudicator")


def make_platform_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")
