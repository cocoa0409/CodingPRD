"""Pre-built role headers for every role in the PRD.

Two kinds of entries:

- Shared constants in TEST_USERS for the six opaque roles (the server records
  but never entity-compares their X-User-ID). These carry distinct operator
  ids so segregation-of-duties and certifier-identity assertions can tell
  them apart.
- Per-instance builders for the two entity-backed roles. Respondent calls
  must carry the acting Establishment's id; AccreditedMedia calls must carry
  the acting MediaOutlet's id. Ownership-gated fixtures MUST call these
  builders with the real entity id — the shared fallback constants below
  never equal a real entity id and exist only for tests whose outcome does
  not depend on ownership (e.g., role-before-existence rejections).
"""
from prd_bench_local_runner.testing import build_user_headers

# Distinct opaque operator ids used across the design recipes.
ADMIN_USER_ID = "admin-1"
METHODOLOGIST_USER_ID = "methodologist-1"
COLLECTOR_USER_ID = "collector-1"
ANALYST_USER_ID = "analyst-1"
ANALYST_2_USER_ID = "analyst-2"
DISCLOSURE_OFFICER_USER_ID = "officer-7"
RELEASE_MANAGER_USER_ID = "release-manager-1"

# Clearly-not-an-entity fallback ids (never equal a real Establishment or
# MediaOutlet id, which is a server-minted UUID).
FALLBACK_RESPONDENT_USER_ID = "00000000-0000-4000-8000-0000000000aa"
FALLBACK_MEDIA_USER_ID = "00000000-0000-4000-8000-0000000000bb"

TEST_USERS = {
    # Opaque roles — canonical shared form.
    "program_admin_headers": build_user_headers(ADMIN_USER_ID, "ProgramAdmin"),
    "survey_methodologist_headers": build_user_headers(METHODOLOGIST_USER_ID, "SurveyMethodologist"),
    "collection_officer_headers": build_user_headers(COLLECTOR_USER_ID, "CollectionOfficer"),
    "estimation_analyst_headers": build_user_headers(ANALYST_USER_ID, "EstimationAnalyst"),
    "estimation_analyst_2_headers": build_user_headers(ANALYST_2_USER_ID, "EstimationAnalyst"),
    "disclosure_officer_headers": build_user_headers(DISCLOSURE_OFFICER_USER_ID, "DisclosureOfficer"),
    "release_manager_headers": build_user_headers(RELEASE_MANAGER_USER_ID, "ReleaseManager"),
    # Entity-backed roles — fallback for NON-ownership tests only.
    "respondent_headers": build_user_headers(FALLBACK_RESPONDENT_USER_ID, "Respondent"),
    "accredited_media_headers": build_user_headers(FALLBACK_MEDIA_USER_ID, "AccreditedMedia"),
}


def make_respondent_headers(establishment_id: str) -> dict:
    """Respondent is entity-backed by Establishment: pass the acting
    establishment's id whenever the call is ownership-gated (lifecycle
    ACCEPT/DECLINE/SUSPEND, report create, report SUBMIT)."""
    return build_user_headers(establishment_id, "Respondent")


def make_accredited_media_headers(media_outlet_id: str) -> dict:
    """AccreditedMedia is entity-backed by MediaOutlet: pass the acting
    outlet's id whenever the call is ownership-gated (bulletin reads)."""
    return build_user_headers(media_outlet_id, "AccreditedMedia")


def make_disclosure_officer_headers(user_id: str) -> dict:
    """DisclosureOfficer is opaque, but segregation-of-duties tests need to
    choose the reviewer id freely (e.g., reusing the certifier's id)."""
    return build_user_headers(user_id, "DisclosureOfficer")


def make_estimation_analyst_headers(user_id: str) -> dict:
    """EstimationAnalyst is opaque; certification records this user id in
    certified_by_user_id, so tests choose it deliberately."""
    return build_user_headers(user_id, "EstimationAnalyst")
