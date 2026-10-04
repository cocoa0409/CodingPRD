"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants. Safe for the opaque roles (ProgramAdmin, BranchManager,
# FieldOfficer) and for any test that does not exercise ownership. For the
# entity-backed roles (CenterManager, Member) the shared constant is a fallback
# only — ownership-gated calls MUST use make_center_manager_headers /
# make_member_headers with the actual entity id, because ownership checks
# compare X-User-ID against the persisted entity id.
TEST_USERS = {
    "program_admin_headers": build_user_headers("test-program-admin-1", "ProgramAdmin"),
    "branch_manager_headers": build_user_headers("test-branch-manager-1", "BranchManager"),
    "center_manager_headers": build_user_headers("test-center-manager-1", "CenterManager"),
    "field_officer_headers": build_user_headers("test-field-officer-1", "FieldOfficer"),
    "member_headers": build_user_headers("test-member-1", "Member"),
    # A second opaque BranchManager identity, used where segregation of duties
    # requires the reconciler to differ from the meeting closer.
    "branch_manager_b_headers": build_user_headers("test-branch-manager-2", "BranchManager"),
}


def make_center_manager_headers(manager_id: str) -> dict:
    """For CenterManager (entity-backed): X-User-ID must equal the acting
    CenterManager's id whenever the call is ownership-gated (meeting open /
    attendance / collections / close / cancel, training scheduling)."""
    return build_user_headers(manager_id, "CenterManager")


def make_member_headers(member_id: str) -> dict:
    """For Member (entity-backed): X-User-ID must equal the acting Member's id
    whenever the call is ownership-gated (consensus votes, savings withdrawals
    and closures)."""
    return build_user_headers(member_id, "Member")
