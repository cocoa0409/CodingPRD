"""Pre-built role headers for every role in the PRD (§2.1).

``Veteran`` and ``Appraiser`` are entity-backed roles: their ``X-User-ID`` must
equal the acting entity's ``id``.  For those two roles the shared constants are
only fallbacks for tests that do not exercise ownership; ownership-gated calls
must go through the per-instance builders with the real entity id.
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import Role

LOAN_OFFICER_USER_ID = "lo-1"
LOAN_OFFICER_9_USER_ID = "lo-9"
UNDERWRITER_USER_ID = "uw-1"
UNDERWRITER_9_USER_ID = "uw-9"
PROGRAM_ADMIN_USER_ID = "admin-1"

# Shared constants.
LOAN_OFFICER: Dict[str, str] = build_user_headers(LOAN_OFFICER_USER_ID, Role.LOAN_OFFICER)
UNDERWRITER: Dict[str, str] = build_user_headers(UNDERWRITER_USER_ID, Role.UNDERWRITER)
PROGRAM_ADMIN: Dict[str, str] = build_user_headers(PROGRAM_ADMIN_USER_ID, Role.PROGRAM_ADMIN)
# Fallback-only constants for the entity-backed roles (non-ownership tests).
VETERAN: Dict[str, str] = build_user_headers("veteran-anon", Role.VETERAN)
APPRAISER: Dict[str, str] = build_user_headers("appraiser-anon", Role.APPRAISER)

TEST_USERS: Dict[str, Dict[str, str]] = {
    "veteran_headers": VETERAN,
    "loan_officer_headers": LOAN_OFFICER,
    "underwriter_headers": UNDERWRITER,
    "appraiser_headers": APPRAISER,
    "program_admin_headers": PROGRAM_ADMIN,
}


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Header bundle for an arbitrary user id / role pair."""
    return build_user_headers(user_id, role)


def make_veteran_headers(veteran_id: str) -> Dict[str, str]:
    """Veteran is entity-backed: pass the acting Veteran's id as user_id."""
    return build_user_headers(veteran_id, Role.VETERAN)


def make_appraiser_headers(appraiser_id: str) -> Dict[str, str]:
    """Appraiser is entity-backed: pass the acting Appraiser's id as user_id."""
    return build_user_headers(appraiser_id, Role.APPRAISER)


def make_loan_officer_headers(user_id: str = LOAN_OFFICER_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, Role.LOAN_OFFICER)


def make_underwriter_headers(user_id: str = UNDERWRITER_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, Role.UNDERWRITER)


def make_program_admin_headers(user_id: str = PROGRAM_ADMIN_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, Role.PROGRAM_ADMIN)
