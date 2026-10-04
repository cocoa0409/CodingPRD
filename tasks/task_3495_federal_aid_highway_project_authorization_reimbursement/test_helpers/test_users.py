"""Pre-built role headers for the five roles in the PRD (§2.1).

All five roles are opaque identities: X-User-ID is an opaque operator
identifier that is never compared against any resource id. It IS recorded
for attribution, and two segregation-of-duties gates compare recorded
identifiers for inequality:

  * ChangeOrder: the state-concur caller's X-User-ID must differ from
    requested_by_user_id (PRD §3.8).
  * Audit: the auditor's X-User-ID must differ from the final voucher's
    decided_by_user_id (PRD §3.9).

Fixtures and tests exercising either gate MUST use two header entries with
different X-User-ID values — the "*_alt" entries below exist for that.
"""
from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# Canonical user ids per role (primary and alternate).
USER_IDS = {
    "platform_admin": "test-platform-admin-1",
    "state_dot_planner": "test-state-dot-planner-1",
    "state_dot_engineer": "test-state-dot-engineer-1",
    "state_dot_engineer_alt": "test-state-dot-engineer-2",
    "fhwa_division_admin": "test-fhwa-division-admin-1",
    "fhwa_reviewer": "test-fhwa-reviewer-1",
    "fhwa_reviewer_alt": "test-fhwa-reviewer-2",
}

TEST_USERS = {
    "platform_admin": build_user_headers(
        USER_IDS["platform_admin"], UserRole.PLATFORM_ADMIN.value
    ),
    "state_dot_planner": build_user_headers(
        USER_IDS["state_dot_planner"], UserRole.STATE_DOT_PLANNER.value
    ),
    "state_dot_engineer": build_user_headers(
        USER_IDS["state_dot_engineer"], UserRole.STATE_DOT_ENGINEER.value
    ),
    # Alternate engineer: concur side of the change-order SoD gate.
    "state_dot_engineer_alt": build_user_headers(
        USER_IDS["state_dot_engineer_alt"], UserRole.STATE_DOT_ENGINEER.value
    ),
    "fhwa_division_admin": build_user_headers(
        USER_IDS["fhwa_division_admin"], UserRole.FHWA_DIVISION_ADMIN.value
    ),
    "fhwa_reviewer": build_user_headers(
        USER_IDS["fhwa_reviewer"], UserRole.FHWA_REVIEWER.value
    ),
    # Alternate reviewer: auditor side of the audit SoD gate (the primary
    # reviewer is the default decider of the final voucher).
    "fhwa_reviewer_alt": build_user_headers(
        USER_IDS["fhwa_reviewer_alt"], UserRole.FHWA_REVIEWER.value
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders — for tests that need a fresh operator id on demand
# (e.g. a third engineer, or a bespoke segregation-of-duties pair).
# ---------------------------------------------------------------------------
def make_platform_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, UserRole.PLATFORM_ADMIN.value)


def make_state_dot_planner_headers(user_id: str) -> dict:
    return build_user_headers(user_id, UserRole.STATE_DOT_PLANNER.value)


def make_state_dot_engineer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, UserRole.STATE_DOT_ENGINEER.value)


def make_fhwa_division_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, UserRole.FHWA_DIVISION_ADMIN.value)


def make_fhwa_reviewer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, UserRole.FHWA_REVIEWER.value)


def make_headers(user_id: str, role: str) -> dict:
    """Generic builder for ad-hoc user/role pairs (role spelled PRD-exactly)."""
    return build_user_headers(user_id, role)
