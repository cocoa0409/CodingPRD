"""Pre-built role headers for every role in the PRD (§2.1).

Identity model (PRD §2.1):
  - Applicant is entity-backed: X-User-ID IS the acting Applicant record's id.
    Ownership-gated calls MUST use make_applicant_headers(applicant["id"]) —
    the shared fallback below is only for tests that do not exercise ownership
    (e.g. 400-on-bad-payload probes, 404 probes, or deliberate intruder calls).
  - PlatformAdmin, ProgramOfficer, HostCommission, NationalReviewer,
    CampusReviewer and Anonymous carry opaque operator identifiers, never
    compared to any entity id. The server may record them (e.g. reviewer_id
    on a posted score), so reviewers come in distinct numbered identities:
    the one-score-per-(application, stage, reviewer) rule means quorum needs
    TWO distinct reviewer ids per stage family.
"""
from prd_bench_local_runner.testing import build_user_headers

# ---------------------------------------------------------------------------
# Shared constants — canonical for opaque roles; the Applicant entry is a
# fallback for non-ownership tests only (see module docstring).
# ---------------------------------------------------------------------------
TEST_USERS = {
    "platform_admin_headers": build_user_headers("pa-1", "PlatformAdmin"),
    "program_officer_headers": build_user_headers("po-1", "ProgramOfficer"),
    "host_commission_headers": build_user_headers("hc-1", "HostCommission"),
    "national_reviewer_headers": build_user_headers("nr-1", "NationalReviewer"),
    "national_reviewer_2_headers": build_user_headers("nr-2", "NationalReviewer"),
    "campus_reviewer_headers": build_user_headers("cr-1", "CampusReviewer"),
    "campus_reviewer_2_headers": build_user_headers("cr-2", "CampusReviewer"),
    "anonymous_headers": build_user_headers("anon-1", "Anonymous"),
    # entity-backed fallback — never equals a real Applicant.id; use only
    # where ownership of the target resource is irrelevant to the assertion.
    "applicant_headers": build_user_headers("test-applicant-1", "Applicant"),
}


# ---------------------------------------------------------------------------
# Per-instance builders
# ---------------------------------------------------------------------------

def make_applicant_headers(user_id: str) -> dict:
    """For the entity-backed Applicant role. Pass the actual Applicant.id as
    user_id whenever the call is ownership-gated (application create/patch/
    transition, placement-round ACCEPT/DECLINE, report submit/resubmit,
    residency stays / waiver requests, own-record GETs)."""
    return build_user_headers(user_id, "Applicant")


def make_platform_admin_headers(user_id: str = "pa-1") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_program_officer_headers(user_id: str = "po-1") -> dict:
    return build_user_headers(user_id, "ProgramOfficer")


def make_host_commission_headers(user_id: str = "hc-1") -> dict:
    return build_user_headers(user_id, "HostCommission")


def make_national_reviewer_headers(user_id: str) -> dict:
    """Distinct user_id per reviewer — one score per (application, stage,
    reviewer); quorum needs two distinct NationalReviewer identities."""
    return build_user_headers(user_id, "NationalReviewer")


def make_campus_reviewer_headers(user_id: str) -> dict:
    """Distinct user_id per reviewer — campus quorum needs two distinct
    CampusReviewer identities."""
    return build_user_headers(user_id, "CampusReviewer")


def make_anonymous_headers(user_id: str = "anon-1") -> dict:
    return build_user_headers(user_id, "Anonymous")
