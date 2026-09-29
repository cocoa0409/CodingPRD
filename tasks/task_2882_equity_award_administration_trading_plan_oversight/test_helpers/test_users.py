"""Pre-built identity headers for every role the PRD defines.

Five of the six roles are opaque operator identities, so a shared constant is
the canonical form for them. The sixth, ``Participant``, is entity-backed: its
``X-User-ID`` must be the ``id`` of the acting participant row, so any
ownership-gated call MUST use :func:`make_participant_headers` with that row's
real id.
"""

from prd_bench_local_runner.testing import build_user_headers

# Canonical opaque operator identifiers.
ADMIN_USER_ID = "admin-1"
ADMIN_USER_ID_ALT = "admin-2"
BOARD_USER_ID = "board-1"
BOARD_USER_ID_ALT = "board-2"
OFFICER_USER_ID = "officer-1"
OFFICER_USER_ID_ALT = "officer-2"
COMPLIANCE_USER_ID = "compliance-1"
COMPLIANCE_USER_ID_ALT = "compliance-2"
AUDITOR_USER_ID = "auditor-1"

TEST_USERS = {
    "admin_headers": build_user_headers(ADMIN_USER_ID, "PlanAdministrator"),
    "admin_alt_headers": build_user_headers(ADMIN_USER_ID_ALT, "PlanAdministrator"),
    "board_headers": build_user_headers(BOARD_USER_ID, "BoardMember"),
    "board_alt_headers": build_user_headers(BOARD_USER_ID_ALT, "BoardMember"),
    "officer_headers": build_user_headers(OFFICER_USER_ID, "DelegatedOfficer"),
    "officer_alt_headers": build_user_headers(OFFICER_USER_ID_ALT, "DelegatedOfficer"),
    "compliance_headers": build_user_headers(COMPLIANCE_USER_ID, "ComplianceOfficer"),
    "compliance_alt_headers": build_user_headers(
        COMPLIANCE_USER_ID_ALT, "ComplianceOfficer"
    ),
    "auditor_headers": build_user_headers(AUDITOR_USER_ID, "Auditor"),
    # Fallback only - never use this on an ownership-gated call.
    "participant_headers": build_user_headers("participant-unbound", "Participant"),
}

ADMIN = TEST_USERS["admin_headers"]
ADMIN_ALT = TEST_USERS["admin_alt_headers"]
BOARD = TEST_USERS["board_headers"]
BOARD_ALT = TEST_USERS["board_alt_headers"]
OFFICER = TEST_USERS["officer_headers"]
OFFICER_ALT = TEST_USERS["officer_alt_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]
COMPLIANCE_ALT = TEST_USERS["compliance_alt_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


def make_participant_headers(participant_id: str) -> dict:
    """Headers for the Participant role. ``participant_id`` must be the id of the
    acting participant row, because ownership checks compare a resource's
    participant foreign key to ``X-User-ID``."""
    return build_user_headers(participant_id, "Participant")


def make_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlanAdministrator")


def make_board_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "BoardMember")


def make_officer_headers(user_id: str) -> dict:
    """Headers for a DelegatedOfficer. ``user_id`` must equal the
    ``delegate_user_id`` of the delegation being exercised."""
    return build_user_headers(user_id, "DelegatedOfficer")


def make_compliance_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_auditor_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Auditor")


def make_headers(user_id, role: str) -> dict:
    """Generic builder. ``user_id`` may be None to omit the identity header, or
    ``""`` to send it blank."""
    headers = {"Content-Type": "application/json"}
    if user_id is not None:
        headers["X-User-ID"] = user_id
    if role is not None:
        headers["X-Role"] = role
    return headers


def make_headers_canonical_role_spelling(user_id: str, role: str) -> dict:
    """Identity headers using the PRD's canonical ``X-Role`` spelling."""
    return {
        "X-User-ID": user_id,
        "X-Role": role,
        "Content-Type": "application/json",
    }
