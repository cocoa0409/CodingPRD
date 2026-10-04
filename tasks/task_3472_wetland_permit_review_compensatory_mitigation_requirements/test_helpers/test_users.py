"""Pre-built role headers for every role in the PRD (§2.1).

`X-User-ID` semantics differ by role (PRD §2.1):
- `Applicant` is entity-backed: `X-User-ID` must equal the acting `Applicant`
  entity's `id`, and ownership checks compare it against the resource's
  applicant foreign key (§2.9). Always build these per instance with
  `make_applicant_headers(applicant["id"])`.
- The other five roles are opaque operator identifiers. Two
  segregation-of-duties gates compare them against recorded identifiers
  (§2.9): render-decision rejects the application's `screening_reviewer_id`,
  and confirm-violation rejects the case's `opened_by_officer_id`.

Canonical operator ids below keep those gates deterministic: the default
decision engineer (de-9) always differs from the default screener (rev-1),
and the default confirming officer (eo-2) always differs from the default
opener (eo-1).
"""
from prd_bench_local_runner.testing import build_user_headers

# Canonical opaque operator identifiers.
SYSTEM_ADMIN_USER_ID = "admin-1"
REVIEWER_USER_ID = "rev-1"          # default screener / reviewer
REVIEWER_2_USER_ID = "rev-2"        # second reviewer
DISTRICT_ENGINEER_USER_ID = "de-1"  # JD issuance, bank approval, extensions
DECISION_ENGINEER_USER_ID = "de-9"  # render-decision (never the screener)
AGENCY_REVIEWER_USER_ID = "epa-1"   # EPA filer
AGENCY_REVIEWER_2_USER_ID = "fws-1" # FWS filer
OFFICER_OPENER_USER_ID = "eo-1"     # opens cases (may never confirm them)
OFFICER_CONFIRMER_USER_ID = "eo-2"  # confirms / resolves / verifies
OFFICER_3_USER_ID = "eo-3"          # third officer

# An explicit empty header set: requests sent with these headers carry neither
# X-User-ID nor X-User-Role and must be rejected with ERR_MISSING_AUTH.
NO_AUTH_HEADERS = {}

TEST_USERS = {
    # Opaque roles — shared constants are the canonical form.
    "system_admin_headers": build_user_headers(SYSTEM_ADMIN_USER_ID, "SystemAdmin"),
    "reviewer_headers": build_user_headers(REVIEWER_USER_ID, "Reviewer"),
    "reviewer_2_headers": build_user_headers(REVIEWER_2_USER_ID, "Reviewer"),
    "district_engineer_headers": build_user_headers(
        DISTRICT_ENGINEER_USER_ID, "DistrictEngineer"
    ),
    "decision_engineer_headers": build_user_headers(
        DECISION_ENGINEER_USER_ID, "DistrictEngineer"
    ),
    "agency_reviewer_headers": build_user_headers(
        AGENCY_REVIEWER_USER_ID, "AgencyReviewer"
    ),
    "agency_reviewer_2_headers": build_user_headers(
        AGENCY_REVIEWER_2_USER_ID, "AgencyReviewer"
    ),
    "officer_opener_headers": build_user_headers(
        OFFICER_OPENER_USER_ID, "EnforcementOfficer"
    ),
    "officer_confirmer_headers": build_user_headers(
        OFFICER_CONFIRMER_USER_ID, "EnforcementOfficer"
    ),
    "officer_3_headers": build_user_headers(OFFICER_3_USER_ID, "EnforcementOfficer"),
    # entity_backed:Applicant — shared constant is a fallback ONLY for tests
    # whose outcome does not depend on owning the subject resource (400/404/
    # role-denial probes). Any ownership-gated call MUST use
    # make_applicant_headers(applicant["id"]) instead.
    "applicant_headers": build_user_headers("test-applicant-1", "Applicant"),
}


# Per-instance builders.
def make_applicant_headers(user_id: str) -> dict:
    """Applicant is entity_backed: pass the actual Applicant.id as user_id
    whenever the call is ownership-gated (PRD §2.1, §2.9)."""
    return build_user_headers(user_id, "Applicant")


def make_system_admin_headers(user_id: str = SYSTEM_ADMIN_USER_ID) -> dict:
    return build_user_headers(user_id, "SystemAdmin")


def make_reviewer_headers(user_id: str = REVIEWER_USER_ID) -> dict:
    return build_user_headers(user_id, "Reviewer")


def make_district_engineer_headers(user_id: str = DISTRICT_ENGINEER_USER_ID) -> dict:
    """For the render-decision segregation-of-duties gate, pass the recorded
    screening reviewer id (e.g. make_district_engineer_headers("rev-1")) to
    trigger ERR_SEGREGATION_OF_DUTIES, or any other id to pass it."""
    return build_user_headers(user_id, "DistrictEngineer")


def make_agency_reviewer_headers(user_id: str = AGENCY_REVIEWER_USER_ID) -> dict:
    return build_user_headers(user_id, "AgencyReviewer")


def make_enforcement_officer_headers(user_id: str = OFFICER_CONFIRMER_USER_ID) -> dict:
    """For the confirm-violation segregation-of-duties gate, pass the case's
    opener id (make_enforcement_officer_headers("eo-1")) to trigger
    ERR_SEGREGATION_OF_DUTIES, or any other id to pass it."""
    return build_user_headers(user_id, "EnforcementOfficer")
