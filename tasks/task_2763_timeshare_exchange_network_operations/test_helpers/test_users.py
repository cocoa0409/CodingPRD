"""Role headers for the four roles of PRD §2.1.

`Member` and `ResortManager` identities are looked up: a `Member` caller's
`X-User-ID` must be a real `Member.id` and a `ResortManager` caller's
`X-User-ID` must be a real `Resort.id` (PRD §2.1). Ownership-gated calls must
therefore use the per-instance builders below, never a shared constant.
`NetworkOperator` and `DisputeAnalyst` are opaque handles that are never
looked up, so shared constants are the canonical form for them.
"""

from prd_bench_local_runner.testing import build_user_headers

OPERATOR_ID = "operator-console-1"
ANALYST_ID = "dispute-analyst-1"

TEST_USERS = {
    # Opaque identities — never looked up, so a constant is canonical.
    "operator_headers": build_user_headers(OPERATOR_ID, "NetworkOperator"),
    "analyst_headers": build_user_headers(ANALYST_ID, "DisputeAnalyst"),
    # Entity-backed identities — these constants are only valid for tests that
    # deliberately exercise a non-existent acting identity.
    "unknown_member_headers": build_user_headers(
        "00000000-0000-0000-0000-000000000000", "Member"
    ),
    "unknown_resort_manager_headers": build_user_headers(
        "00000000-0000-0000-0000-000000000000", "ResortManager"
    ),
}


def make_member_headers(member_id: str) -> dict:
    """Headers for a `Member` caller; `member_id` must be a real `Member.id`."""
    return build_user_headers(member_id, "Member")


def make_resort_manager_headers(resort_id: str) -> dict:
    """Headers for a `ResortManager` caller; `resort_id` must be a real `Resort.id`."""
    return build_user_headers(resort_id, "ResortManager")


def make_operator_headers(operator_id: str = OPERATOR_ID) -> dict:
    """Headers for a `NetworkOperator` caller (opaque identifier)."""
    return build_user_headers(operator_id, "NetworkOperator")


def make_analyst_headers(analyst_id: str = ANALYST_ID) -> dict:
    """Headers for a `DisputeAnalyst` caller (opaque handle)."""
    return build_user_headers(analyst_id, "DisputeAnalyst")


def make_headers(user_id: str, role: str) -> dict:
    """Headers for an arbitrary role string, including unrecognised ones."""
    return build_user_headers(user_id, role)


OPERATOR_HEADERS = TEST_USERS["operator_headers"]
ANALYST_HEADERS = TEST_USERS["analyst_headers"]
