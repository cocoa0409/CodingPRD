"""Pre-built role headers for every role in the PRD.

Six of the seven roles carry an opaque operator identifier in X-User-ID.
VoiceTalentUser is the exception: its X-User-ID is the id of the acting
VoiceTalent row, so ownership-gated calls MUST use make_voice_talent_headers()
with the real talent id.
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import ADAPTOR_1, REVIEWER_1

# Shared constants — safe for opaque roles and for calls that exercise no
# per-row ownership check.
TEST_USERS = {
    "production_coordinator_headers": build_user_headers(
        "coordinator-1", "ProductionCoordinator"
    ),
    "adaptor_headers": build_user_headers(ADAPTOR_1, "Adaptor"),
    "native_reviewer_headers": build_user_headers(REVIEWER_1, "NativeReviewer"),
    "casting_director_headers": build_user_headers("casting-1", "CastingDirector"),
    "mix_engineer_headers": build_user_headers("mixer-1", "MixEngineer"),
    "platform_admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
    # Fallback only: never use for a respond-hold call, which is ownership-gated.
    "voice_talent_headers": build_user_headers("talent-anon", "VoiceTalentUser"),
}


def make_production_coordinator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ProductionCoordinator")


def make_adaptor_headers(user_id: str) -> dict:
    """The operator id recorded as adapted_by_user_id on the adaptation."""
    return build_user_headers(user_id, "Adaptor")


def make_native_reviewer_headers(user_id: str) -> dict:
    """The operator id recorded as reviewed_by_user_id / reviewer_user_id."""
    return build_user_headers(user_id, "NativeReviewer")


def make_casting_director_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "CastingDirector")


def make_mix_engineer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "MixEngineer")


def make_platform_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_voice_talent_headers(talent_id: str) -> dict:
    """For VoiceTalentUser. Pass the real VoiceTalent.id: every ownership check
    compares the targeted assignment's talent_id against X-User-ID."""
    return build_user_headers(talent_id, "VoiceTalentUser")


PC = TEST_USERS["production_coordinator_headers"]
ADAPTOR = TEST_USERS["adaptor_headers"]
REVIEWER = TEST_USERS["native_reviewer_headers"]
CASTING = TEST_USERS["casting_director_headers"]
MIXER = TEST_USERS["mix_engineer_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]
