"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise
# ownership of an entity-backed role's resource.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "board_headers": build_user_headers("test-board-1", "AccreditationBoard"),
    "studio_rep_headers": build_user_headers("test-studio-1", "StudioRep"),
    # entity_backed fallbacks — only for non-ownership-gated calls
    "critic_headers": build_user_headers("test-critic-1", "Critic"),
    "audience_member_headers": build_user_headers("test-member-1", "AudienceMember"),
}


def make_critic_headers(user_id: str) -> dict:
    """For Critic (entity_backed:Critic). Pass the actual Critic.id as user_id
    whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Critic")


def make_audience_member_headers(user_id: str) -> dict:
    """For AudienceMember (entity_backed:AudienceMember). Pass the actual
    AudienceMember.id as user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "AudienceMember")
