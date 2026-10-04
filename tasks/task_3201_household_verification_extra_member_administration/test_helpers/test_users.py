"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles (PlatformAdmin, SupportAgent) and
# for tests that do not exercise entity-backed ownership checks.
TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "support_headers": build_user_headers("test-support-1", "SupportAgent"),
    # Entity-backed roles: fallbacks for non-ownership tests only.
    "owner_headers": build_user_headers("test-owner-1", "AccountOwner"),
    "household_member_headers": build_user_headers("test-household-1", "HouseholdMember"),
    "extra_member_headers": build_user_headers("test-extra-1", "ExtraMember"),
}


# Per-instance builders — required for every entity-backed role. Pass the
# actual Member.id whenever the call is ownership-gated (which is almost
# every member-role call).
def make_owner_headers(member_id: str) -> dict:
    """AccountOwner headers; member_id must be the account's OWNER Member id."""
    return build_user_headers(member_id, "AccountOwner")


def make_household_member_headers(member_id: str) -> dict:
    """HouseholdMember headers; member_id must be a HOUSEHOLD Member id."""
    return build_user_headers(member_id, "HouseholdMember")


def make_extra_member_headers(member_id: str) -> dict:
    """ExtraMember headers; member_id must be an EXTRA Member id."""
    return build_user_headers(member_id, "ExtraMember")
