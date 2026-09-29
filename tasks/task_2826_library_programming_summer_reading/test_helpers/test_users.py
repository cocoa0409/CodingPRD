"""Role header builders for the four roles the API recognises.

Three of the roles authenticate with an opaque staff identifier that the server
merely records (as ``offered_by_user_id``, ``executed_by_user_id`` or
``recorded_by_user_id``). The ``Reader`` role is different: "When `X-User-Role` is
`Reader`, by contrast, `X-User-Id` is the `id` of the acting `Participant`
record", so reader headers must be built from a real participant identifier,
which is what ``make_reader_headers`` is for.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_PROGRAM_COORDINATOR,
    ROLE_PROGRAM_MANAGER,
    ROLE_READER,
    ROLE_SCREENING_OFFICER,
)

# --------------------------------------------------------------------------
# Opaque staff identifiers
# --------------------------------------------------------------------------
MANAGER_USER_ID = "mgr-001"
# A second manager identity: segregation of duties refuses an execute by the
# same user that made the offer, so the offering and executing identities must
# differ.
SECOND_MANAGER_USER_ID = "mgr-002"
COORDINATOR_USER_ID = "coord-001"
SECOND_COORDINATOR_USER_ID = "coord-002"
SCREENING_OFFICER_USER_ID = "screen-001"

MANAGER_HEADERS = build_user_headers(MANAGER_USER_ID, ROLE_PROGRAM_MANAGER)
SECOND_MANAGER_HEADERS = build_user_headers(
    SECOND_MANAGER_USER_ID, ROLE_PROGRAM_MANAGER
)
COORDINATOR_HEADERS = build_user_headers(
    COORDINATOR_USER_ID, ROLE_PROGRAM_COORDINATOR
)
SECOND_COORDINATOR_HEADERS = build_user_headers(
    SECOND_COORDINATOR_USER_ID, ROLE_PROGRAM_COORDINATOR
)
SCREENING_OFFICER_HEADERS = build_user_headers(
    SCREENING_OFFICER_USER_ID, ROLE_SCREENING_OFFICER
)


def make_manager_headers(user_id: str) -> Dict[str, str]:
    """Manager headers under a caller-chosen opaque staff identifier."""
    return build_user_headers(user_id, ROLE_PROGRAM_MANAGER)


def make_coordinator_headers(user_id: str) -> Dict[str, str]:
    """Coordinator headers under a caller-chosen opaque staff identifier."""
    return build_user_headers(user_id, ROLE_PROGRAM_COORDINATOR)


def make_screening_officer_headers(user_id: str) -> Dict[str, str]:
    """Screening officer headers under a caller-chosen staff identifier."""
    return build_user_headers(user_id, ROLE_SCREENING_OFFICER)


def make_reader_headers(participant_id: str) -> Dict[str, str]:
    """Reader headers whose ``X-User-Id`` is the participant's own identifier.

    Ownership-gated reader calls compare this value against the
    ``{participant_id}`` in the path, so passing anything other than a real
    participant identifier is how a test provokes an ownership refusal.
    """
    return build_user_headers(participant_id, ROLE_READER)


# --------------------------------------------------------------------------
# Malformed authentication headers
# --------------------------------------------------------------------------
# "A request that omits either header, or sends either as an empty string, is
# rejected with ERR_UNAUTHENTICATED (401)."
NO_AUTH_HEADERS: Dict[str, str] = {"Content-Type": "application/json"}

MISSING_ROLE_HEADERS: Dict[str, str] = {
    "X-User-ID": MANAGER_USER_ID,
    "Content-Type": "application/json",
}

MISSING_USER_ID_HEADERS: Dict[str, str] = {
    "X-User-Role": ROLE_PROGRAM_MANAGER,
    "Content-Type": "application/json",
}

EMPTY_ROLE_HEADERS: Dict[str, str] = build_user_headers(MANAGER_USER_ID, "")
EMPTY_USER_ID_HEADERS: Dict[str, str] = build_user_headers(
    "", ROLE_PROGRAM_MANAGER
)

# "An unrecognised role, or a recognised role that the endpoint does not list,
# is rejected with ERR_UNAUTHORIZED (403)."
UNKNOWN_ROLE_HEADERS: Dict[str, str] = build_user_headers(
    "someone-001", "LibraryVolunteer"
)

READER_ROLE_NAME = ROLE_READER
