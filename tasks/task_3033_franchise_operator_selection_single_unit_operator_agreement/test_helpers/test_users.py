"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
TEST_USERS = {
    "system_admin_headers": build_user_headers("test-sysadmin-1", "SystemAdmin"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "candidate_headers": build_user_headers("test-candidate-1", "Candidate"),
    "field_consultant_headers": build_user_headers("test-field-consultant-1", "FieldConsultant"),
    "selection_committee_headers": build_user_headers("test-selection-committee-1", "SelectionCommittee"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "operator_headers": build_user_headers("test-operator-1", "Operator"),
    "finance_admin_headers": build_user_headers("test-finance-admin-1", "FinanceAdmin"),
}


# Per-instance builders — required for every entity_backed role.
def make_candidate_headers(user_id: str) -> dict:
    """For Candidate (entity_backed:Candidate). Pass the actual Candidate.id as
    user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Candidate")


def make_operator_headers(user_id: str) -> dict:
    """For Operator (entity_backed:Operator). Pass the actual Operator.id as
    user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Operator")
