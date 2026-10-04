"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
TEST_USERS = {
    "staff_headers": build_user_headers("test-staff-1", "AssociationStaff"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "member_headers": build_user_headers("test-member-1", "Member"),
    "grievance_headers": build_user_headers("test-grievance-1", "GrievanceMember"),
    "panelist_headers": build_user_headers("test-panelist-1", "HearingPanelist"),
}


# Per-instance builders — required for every entity_backed role.
def make_member_headers(user_id: str) -> dict:
    """For Member (entity_backed:Member). Pass the actual Member.id as user_id
    whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Member")


def make_grievance_headers(user_id: str) -> dict:
    """For GrievanceMember (entity_backed:Member). Pass the acting Member.id."""
    return build_user_headers(user_id, "GrievanceMember")


def make_panelist_headers(user_id: str) -> dict:
    """For HearingPanelist (entity_backed:Member). Pass the seated Member.id."""
    return build_user_headers(user_id, "HearingPanelist")


def make_staff_headers(user_id: str = "test-staff-1") -> dict:
    """AssociationStaff is opaque; any id works."""
    return build_user_headers(user_id, "AssociationStaff")
