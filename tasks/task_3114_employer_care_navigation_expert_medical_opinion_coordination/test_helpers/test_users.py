"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise
# member ownership.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("pa-admin-1", "PlatformAdmin"),
    "employer_admin_headers": build_user_headers("ea-1", "EmployerAdmin"),
    "member_headers": build_user_headers("test-member-1", "Member"),
    "nurse_navigator_headers": build_user_headers("nn-1", "NurseNavigator"),
    "care_advocate_headers": build_user_headers("adv-1", "CareAdvocate"),
    "physician_advisor_headers": build_user_headers("pa-phys-1", "PhysicianAdvisor"),
    "records_specialist_headers": build_user_headers("rs-1", "RecordsSpecialist"),
    "expert_reviewer_headers": build_user_headers("er-1", "ExpertReviewer"),
    "billing_advocate_headers": build_user_headers("ba-1", "BillingAdvocate"),
    "plan_administrator_headers": build_user_headers("pa-1", "PlanAdministrator"),
}


# Per-instance builders — required for entity_backed roles. Member is the only
# entity_backed role: X-User-ID must equal the actual Member.id for any
# ownership-gated call.
def make_member_headers(member_id: str) -> dict:
    """For Member (entity_backed:Member). Pass the actual Member.id as user_id
    whenever the call is ownership-gated."""
    return build_user_headers(member_id, "Member")


def make_nurse_navigator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "NurseNavigator")


def make_care_advocate_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "CareAdvocate")


def make_physician_advisor_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PhysicianAdvisor")


def make_records_specialist_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "RecordsSpecialist")


def make_expert_reviewer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ExpertReviewer")


def make_billing_advocate_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "BillingAdvocate")


def make_plan_administrator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlanAdministrator")


def make_platform_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_employer_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "EmployerAdmin")
