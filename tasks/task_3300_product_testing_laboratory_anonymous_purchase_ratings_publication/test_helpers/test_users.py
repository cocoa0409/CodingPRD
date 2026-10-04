"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
TEST_USERS = {
    "lab_manager_headers": build_user_headers("lm-1", "LabManager"),
    "editorial_director_headers": build_user_headers("ed-1", "EditorialDirector"),
    "methodology_officer_headers": build_user_headers("mo-1", "MethodologyOfficer"),
    "purchasing_agent_headers": build_user_headers("pa-1", "PurchasingAgent"),
    "compliance_officer_headers": build_user_headers("co-1", "ComplianceOfficer"),
    "lab_technician_headers": build_user_headers("lt-1", "LabTechnician"),
    "survey_director_headers": build_user_headers("sd-1", "SurveyDirector"),
    "content_editor_headers": build_user_headers("ce-1", "ContentEditor"),
    "safety_officer_headers": build_user_headers("so-1", "SafetyOfficer"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "member_headers": build_user_headers("member-fallback", "Member"),
}


# Per-instance builders — required for every entity_backed role.
def make_member_headers(user_id: str) -> dict:
    """For Member (entity_backed:Member). Pass the actual Member.id as user_id
    whenever the call is ownership-gated (survey response, subscription actions,
    reading own record, member-gated publication reads)."""
    return build_user_headers(user_id, "Member")


# Convenience builders with explicit user ids for the opaque roles, used when a
# test needs to control the actor id (e.g. SoD pairs).
def make_lab_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "LabManager")


def make_editorial_director_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "EditorialDirector")


def make_purchasing_agent_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PurchasingAgent")


def make_compliance_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")
