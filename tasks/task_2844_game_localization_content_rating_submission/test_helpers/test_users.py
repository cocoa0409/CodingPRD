"""Pre-built identity headers for the seven roles (§2.1).

Six roles carry an opaque operator identifier; several distinct identifiers are
provided per role so that the three segregation-of-duties splits and the
review-entry separation can be exercised without ad-hoc header building.

``TalentAgent`` is entity-backed: its ``X-User-ID`` must be the ``id`` of the
acting ``VoiceTalent`` row, so it is only ever built through
``make_talent_agent_headers(voice_talent_id)``.
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_COMPLIANCE_OFFICER,
    ROLE_LOCALIZATION_PRODUCER,
    ROLE_LQA_TESTER,
    ROLE_PLATFORM_ADMIN,
    ROLE_RATING_BOARD_LIAISON,
    ROLE_TALENT_AGENT,
    ROLE_TRANSLATION_VENDOR,
)

# ─── Opaque operator identifiers ───────────────────────────────────────

PRODUCER_USER_ID = "producer-1"
PRODUCER_2_USER_ID = "producer-2"
VENDOR_USER_ID = "vendor-1"
VENDOR_2_USER_ID = "vendor-2"

# Distinct LqaTester identities: opening, logging, verifying and closing are
# all separated duties, so each needs its own operator.
LQA_OPENER_USER_ID = "lqa-opener-1"
LQA_LOGGER_USER_ID = "lqa-logger-1"
LQA_VERIFIER_USER_ID = "lqa-verifier-1"
LQA_CLOSER_USER_ID = "lqa-closer-1"

COMPLIANCE_USER_ID = "compliance-1"
COMPLIANCE_2_USER_ID = "compliance-2"
BOARD_USER_ID = "board-1"
BOARD_2_USER_ID = "board-2"
ADMIN_USER_ID = "admin-1"

# ─── Ready-made header dictionaries ────────────────────────────────────

PRODUCER = build_user_headers(PRODUCER_USER_ID, ROLE_LOCALIZATION_PRODUCER)
PRODUCER_2 = build_user_headers(PRODUCER_2_USER_ID, ROLE_LOCALIZATION_PRODUCER)
VENDOR = build_user_headers(VENDOR_USER_ID, ROLE_TRANSLATION_VENDOR)
VENDOR_2 = build_user_headers(VENDOR_2_USER_ID, ROLE_TRANSLATION_VENDOR)

LQA_OPENER = build_user_headers(LQA_OPENER_USER_ID, ROLE_LQA_TESTER)
LQA_LOGGER = build_user_headers(LQA_LOGGER_USER_ID, ROLE_LQA_TESTER)
LQA_VERIFIER = build_user_headers(LQA_VERIFIER_USER_ID, ROLE_LQA_TESTER)
LQA_CLOSER = build_user_headers(LQA_CLOSER_USER_ID, ROLE_LQA_TESTER)

COMPLIANCE = build_user_headers(COMPLIANCE_USER_ID, ROLE_COMPLIANCE_OFFICER)
COMPLIANCE_2 = build_user_headers(COMPLIANCE_2_USER_ID, ROLE_COMPLIANCE_OFFICER)
BOARD = build_user_headers(BOARD_USER_ID, ROLE_RATING_BOARD_LIAISON)
BOARD_2 = build_user_headers(BOARD_2_USER_ID, ROLE_RATING_BOARD_LIAISON)
ADMIN = build_user_headers(ADMIN_USER_ID, ROLE_PLATFORM_ADMIN)


def make_talent_agent_headers(voice_talent_id: str) -> dict:
    """Headers for the agent acting on behalf of one specific voice talent."""
    return build_user_headers(voice_talent_id, ROLE_TALENT_AGENT)


def make_headers(user_id: str, role: str) -> dict:
    """Headers for an arbitrary identity, for role-permission probes."""
    return build_user_headers(user_id, role)


# One representative identity per role, for role-permission sweeps.
HEADERS_BY_ROLE = {
    ROLE_LOCALIZATION_PRODUCER: PRODUCER,
    ROLE_TRANSLATION_VENDOR: VENDOR,
    ROLE_LQA_TESTER: LQA_OPENER,
    ROLE_COMPLIANCE_OFFICER: COMPLIANCE,
    ROLE_RATING_BOARD_LIAISON: BOARD,
    ROLE_PLATFORM_ADMIN: ADMIN,
}

# Headers with a missing X-User-ID / X-User-Role, and an unrecognised role.
HEADERS_WITHOUT_USER_ID = {
    "X-User-Role": ROLE_LOCALIZATION_PRODUCER,
    "Content-Type": "application/json",
}
HEADERS_WITHOUT_ROLE = {
    "X-User-ID": PRODUCER_USER_ID,
    "Content-Type": "application/json",
}
HEADERS_UNKNOWN_ROLE = build_user_headers(PRODUCER_USER_ID, "LocalisationProducer")
