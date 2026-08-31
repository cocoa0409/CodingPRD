"""Pre-built role headers for every role in the PRD (§2.1)."""

from prd_bench_local_runner.testing import build_user_headers

# Shared constants.
#   HrAdmin and UnionRep carry opaque operator identifiers that the server never
#   compares to any entity id, so the shared constant is the canonical form.
#   Evaluator, Teacher and AppealPanelist are backed by persisted entities; the
#   shared constant is only safe for calls that never reach an ownership check.
TEST_USERS = {
    "hr_admin_headers": build_user_headers("hr-admin-01", "HrAdmin"),
    "hr_admin_2_headers": build_user_headers("hr-admin-02", "HrAdmin"),
    "union_rep_headers": build_user_headers("union-rep-01", "UnionRep"),
    "evaluator_headers": build_user_headers("test-evaluator-1", "Evaluator"),
    "teacher_headers": build_user_headers("test-teacher-1", "Teacher"),
    "appeal_panelist_headers": build_user_headers("test-panelist-1", "AppealPanelist"),
}

# Operator identifiers used by the tenure segregation-of-duties rule.
HR_RECOMMENDER_ID = "hr-recommender-01"
HR_DECIDER_ID = "hr-decider-02"


def make_hr_admin_headers(user_id: str) -> dict:
    """For HrAdmin. X-User-ID is an opaque operator identifier; a tenure
    recommendation stamps it onto the educator and the decision compares it."""
    return build_user_headers(user_id, "HrAdmin")


def make_evaluator_headers(evaluator_id: str) -> dict:
    """For Evaluator. Pass the acting Evaluator record's id: ownership checks
    compare the resource's evaluator_id to X-User-ID."""
    return build_user_headers(evaluator_id, "Evaluator")


def make_teacher_headers(educator_id: str) -> dict:
    """For Teacher. Pass the acting Educator record's id: ownership checks
    compare the resource's educator_id to X-User-ID."""
    return build_user_headers(educator_id, "Teacher")


def make_appeal_panelist_headers(evaluator_id: str) -> dict:
    """For AppealPanelist. X-User-ID is likewise the id of an Evaluator record."""
    return build_user_headers(evaluator_id, "AppealPanelist")


def make_union_rep_headers(user_id: str = "union-rep-01") -> dict:
    """For UnionRep. X-User-ID is an opaque operational identifier."""
    return build_user_headers(user_id, "UnionRep")


HR_RECOMMENDER_HEADERS = make_hr_admin_headers(HR_RECOMMENDER_ID)
HR_DECIDER_HEADERS = make_hr_admin_headers(HR_DECIDER_ID)
