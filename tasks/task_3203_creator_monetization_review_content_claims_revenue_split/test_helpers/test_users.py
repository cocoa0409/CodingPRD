"""Pre-built role headers for every role named in the PRD (PRD §2.1).

Two PRD roles are entity-backed: ``Creator`` (X-User-ID is a Channel.id) and
``RightsHolder`` (X-User-ID is a ReferenceFile.id).  The shared constants below
are usable only by calls that do not exercise ownership; every ownership-gated
call must use the ``make_*_headers`` builders with the real entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for non-ownership-gated calls.
TEST_USERS = {
    "anonymous_headers": build_user_headers("test-anonymous-1", "Anonymous"),
    "any_headers": build_user_headers("test-any-1", "Any"),
    "moderator_headers": build_user_headers("test-moderator-1", "Moderator"),
    "reviewer_headers": build_user_headers("test-reviewer-1", "Reviewer"),
    "monetization_reviewer_headers": build_user_headers(
        "test-monetization-reviewer-1", "MonetizationReviewer"
    ),
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    # entity_backed:Creator — fallback for calls that do not check ownership.
    "creator_headers": build_user_headers("test-creator-1", "Creator"),
    # entity_backed:RightsHolder — fallback for calls that do not check ownership.
    "rights_holder_headers": build_user_headers("test-rights-holder-1", "RightsHolder"),
}


# ─── Per-instance builders — required for entity-backed roles ───

def make_creator_headers(channel_id: str) -> dict:
    """For Creator (entity_backed:Channel).  Pass the acting Channel.id whenever
    the call is ownership-gated (any creation beneath, or mutation of, that
    channel)."""
    return build_user_headers(channel_id, "Creator")


def make_rights_holder_headers(reference_file_id: str) -> dict:
    """For RightsHolder (entity_backed:ReferenceFile).  Pass the acting
    ReferenceFile.id whenever the call is ownership-gated (appeals, resolutions
    and takedowns against a claim originating from that reference)."""
    return build_user_headers(reference_file_id, "RightsHolder")


def make_no_role_headers(user_id: str = "test-no-role-1") -> dict:
    """A caller that presents an identity but omits X-User-Role entirely."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def make_unknown_role_headers(user_id: str = "test-unknown-role-1") -> dict:
    """A caller whose declared role is not one of the eight PRD role names."""
    return build_user_headers(user_id, "SuperUser")