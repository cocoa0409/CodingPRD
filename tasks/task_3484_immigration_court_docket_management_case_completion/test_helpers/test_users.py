"""Pre-built role headers for the three PRD roles.

- ``CourtAdministrator`` and ``BoardMember`` identities are opaque operator
  identifiers; the shared constants are their canonical form.
- ``ImmigrationJudge`` is entity-backed by the ``Judge`` resource: the PRD
  requires the ``X-User-ID`` of an ImmigrationJudge caller to be the ``id`` of
  an existing ``Judge`` (an unresolvable id is rejected with
  ``ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER``, HTTP 400 — even on reads).
  Every successful judge call MUST therefore be made with
  ``make_judge_headers(judge["id"])`` (or another existing Judge id), never
  with the shared ``judge_headers`` constant.  The shared constant exists ONLY
  for tests that exercise the unresolvable-identity rejection itself.
"""

from prd_bench_local_runner.testing import NON_EXISTENT_UUID, build_user_headers

DEFAULT_ADMIN_USER_ID = "admin-01"
DEFAULT_BOARD_MEMBER_USER_ID = "bm-01"

TEST_USERS = {
    # Opaque role: canonical shared form.
    "admin_headers": build_user_headers(DEFAULT_ADMIN_USER_ID, "CourtAdministrator"),
    # Opaque role: canonical shared form.
    "board_headers": build_user_headers(DEFAULT_BOARD_MEMBER_USER_ID, "BoardMember"),
    # Entity-backed role (Judge).  Fallback ONLY for tests expecting the
    # unresolvable-identity 400; successful judge calls need a real Judge id.
    "judge_headers": build_user_headers(NON_EXISTENT_UUID, "ImmigrationJudge"),
}


def make_admin_headers(user_id: str = DEFAULT_ADMIN_USER_ID) -> dict:
    """CourtAdministrator headers; the id is opaque (not compared to resources)."""
    return build_user_headers(user_id, "CourtAdministrator")


def make_board_headers(user_id: str = DEFAULT_BOARD_MEMBER_USER_ID) -> dict:
    """BoardMember headers; the id is opaque (recorded on decided appeals)."""
    return build_user_headers(user_id, "BoardMember")


def make_judge_headers(user_id: str) -> dict:
    """ImmigrationJudge headers.  ``user_id`` MUST be the id of an existing
    Judge — pass the actual ``judge["id"]`` whenever the call must succeed
    (ownership checks compare it against ``case.assigned_judge_id`` or
    ``hearing.judge_id``)."""
    return build_user_headers(user_id, "ImmigrationJudge")
