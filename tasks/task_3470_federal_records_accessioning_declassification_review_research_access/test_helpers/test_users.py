"""Pre-built role headers for the twelve PRD §2.1 roles.

Identity model (PRD §2.1):
- Opaque roles (PlatformAdmin, Anonymous, AppraisalArchivist,
  ProcessingArchivist, DeclassReviewer, ChiefArchivist, ResearchRoomStaff,
  FoiaOfficer, FoiaAppealsOfficer): X-User-ID is an operator identifier the
  server records on workflow stamps but never compares to an entity id, so a
  shared constant per identity is canonical.
- Entity-backed roles: RecordsOfficer and AgencyLiaison are backed by an
  Agency id, Researcher by a ResearcherRegistration id.  Their ownership-gated
  calls must use ``make_<role>_headers(entity["id"])`` — never the shared
  fallback constant, whose X-User-ID matches no real entity.

Segregation of duties (PRD §1, §3.1, §3.9) needs distinct identities on the
same logical desk: the schedule appraiser must differ from the decider
(APPRAISER vs CHIEF_ARCHIVIST here), and the FOIA adjudicator must differ
from the appeals decider (FOIA_OFFICER vs FOIA_APPEALS_OFFICER).  A second
appraiser (APPRAISER_2) and a second adjudicator (FOIA_OFFICER_2) are
provided for resubmission and re-adjudication flows that must NOT collide
with the first actor's stamped id.
"""

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# ─── Opaque operator identifiers (design-canonical spellings) ────────────────
ADMIN_USER_ID = "admin-1"
ANONYMOUS_USER_ID = "anon-1"
APPRAISER_USER_ID = "arch-ap-1"
APPRAISER_2_USER_ID = "arch-ap-2"
PROCESSING_ARCHIVIST_USER_ID = "arch-pro-1"
DECLASS_REVIEWER_USER_ID = "rev-1"
CHIEF_ARCHIVIST_USER_ID = "arch-chief-1"
RESEARCH_ROOM_STAFF_USER_ID = "staff-1"
FOIA_OFFICER_USER_ID = "foia-1"
FOIA_OFFICER_2_USER_ID = "foia-2"
FOIA_APPEALS_OFFICER_USER_ID = "foia-ap-1"


# ─── Shared header constants ─────────────────────────────────────────────────
TEST_USERS = {
    # Opaque roles — canonical form.
    "admin_headers": build_user_headers(ADMIN_USER_ID, UserRole.PLATFORM_ADMIN.value),
    "anonymous_headers": build_user_headers(ANONYMOUS_USER_ID, UserRole.ANONYMOUS.value),
    "appraiser_headers": build_user_headers(APPRAISER_USER_ID, UserRole.APPRAISAL_ARCHIVIST.value),
    "appraiser_2_headers": build_user_headers(APPRAISER_2_USER_ID, UserRole.APPRAISAL_ARCHIVIST.value),
    "processing_archivist_headers": build_user_headers(
        PROCESSING_ARCHIVIST_USER_ID, UserRole.PROCESSING_ARCHIVIST.value
    ),
    "declass_reviewer_headers": build_user_headers(DECLASS_REVIEWER_USER_ID, UserRole.DECLASS_REVIEWER.value),
    "chief_archivist_headers": build_user_headers(CHIEF_ARCHIVIST_USER_ID, UserRole.CHIEF_ARCHIVIST.value),
    "research_room_staff_headers": build_user_headers(
        RESEARCH_ROOM_STAFF_USER_ID, UserRole.RESEARCH_ROOM_STAFF.value
    ),
    "foia_officer_headers": build_user_headers(FOIA_OFFICER_USER_ID, UserRole.FOIA_OFFICER.value),
    "foia_officer_2_headers": build_user_headers(FOIA_OFFICER_2_USER_ID, UserRole.FOIA_OFFICER.value),
    "foia_appeals_officer_headers": build_user_headers(
        FOIA_APPEALS_OFFICER_USER_ID, UserRole.FOIA_APPEALS_OFFICER.value
    ),
    # Entity-backed roles — FALLBACK ONLY, for tests that do not exercise
    # ownership (e.g. 400-on-bad-payload, 404-on-missing-resource probes).
    # Any ownership-gated call MUST use the make_*_headers builders below
    # with the real entity id.
    "records_officer_headers": build_user_headers("test-agency-1", UserRole.RECORDS_OFFICER.value),
    "agency_liaison_headers": build_user_headers("test-agency-1", UserRole.AGENCY_LIAISON.value),
    "researcher_headers": build_user_headers("test-researcher-1", UserRole.RESEARCHER.value),
}


# ─── Per-instance builders (mandatory for entity-backed roles) ───────────────
def make_records_officer_headers(agency_id):
    """RecordsOfficer headers whose X-User-ID IS the acting Agency's id
    (PRD §2.1 entity-backed ownership)."""
    return build_user_headers(agency_id, UserRole.RECORDS_OFFICER.value)


def make_agency_liaison_headers(agency_id):
    """AgencyLiaison headers whose X-User-ID IS the acting Agency's id."""
    return build_user_headers(agency_id, UserRole.AGENCY_LIAISON.value)


def make_researcher_headers(researcher_id):
    """Researcher headers whose X-User-ID IS the acting
    ResearcherRegistration's id."""
    return build_user_headers(researcher_id, UserRole.RESEARCHER.value)


def make_headers(user_id, role):
    """Arbitrary role/identity pairing, including deliberate cross-wirings
    (e.g. a FoiaOfficer role carrying the adjudicator's id on decide-appeal
    to probe segregation of duties)."""
    return build_user_headers(user_id, role)
