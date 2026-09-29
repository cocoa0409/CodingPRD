"""Caller identities and their header builders (PRD S2.1).

PRD S2.1 splits identity semantics in two:

* For ``RecordsCoordinator``, ``DataReporter``, ``PeerReviewer``,
  ``ManagingEditor`` and ``LegalCounsel``, ``X-User-ID`` "is an opaque operator
  identifier not tied to any persisted entity", so these are fixed literals.
* For ``ExpertReviewer``, "``X-User-ID`` is the ``id`` of the acting
  ``ExpertReviewer`` row", so its headers must be built per instance from a
  registered reviewer's id -- hence :func:`expert_reviewer_headers`.

Two distinct identities are provided for the coordinator and for the peer
reviewer because the segregation-of-duties rule of PRD S2.1 compares the
caller's opaque id to a recorded one, and a test of that rule needs a *second*
distinct operator to act as the non-author reviewer.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from . import constants as C

# --------------------------------------------------------------------------
# Opaque operator identifiers
# --------------------------------------------------------------------------

COORDINATOR_ID = "coord-001"
COORDINATOR_ALT_ID = "coord-002"
REPORTER_ID = "rep-001"
REPORTER_ALT_ID = "rep-002"
PEER_REVIEWER_ID = "peer-001"
PEER_REVIEWER_ALT_ID = "peer-002"
EDITOR_ID = "editor-001"
EDITOR_ALT_ID = "editor-002"
LEGAL_ID = "legal-001"

TEST_USERS: Dict[str, Dict[str, str]] = {
    "coordinator": {"user_id": COORDINATOR_ID, "role": C.ROLE_RECORDS_COORDINATOR},
    "coordinator_alt": {
        "user_id": COORDINATOR_ALT_ID,
        "role": C.ROLE_RECORDS_COORDINATOR,
    },
    "reporter": {"user_id": REPORTER_ID, "role": C.ROLE_DATA_REPORTER},
    "reporter_alt": {"user_id": REPORTER_ALT_ID, "role": C.ROLE_DATA_REPORTER},
    "peer_reviewer": {"user_id": PEER_REVIEWER_ID, "role": C.ROLE_PEER_REVIEWER},
    "peer_reviewer_alt": {
        "user_id": PEER_REVIEWER_ALT_ID,
        "role": C.ROLE_PEER_REVIEWER,
    },
    "editor": {"user_id": EDITOR_ID, "role": C.ROLE_MANAGING_EDITOR},
    "editor_alt": {"user_id": EDITOR_ALT_ID, "role": C.ROLE_MANAGING_EDITOR},
    "legal": {"user_id": LEGAL_ID, "role": C.ROLE_LEGAL_COUNSEL},
}


# --------------------------------------------------------------------------
# Per-role header builders
# --------------------------------------------------------------------------


def coordinator_headers(user_id: str = COORDINATOR_ID) -> Dict[str, str]:
    """Headers for a ``RecordsCoordinator`` caller."""
    return build_user_headers(user_id, C.ROLE_RECORDS_COORDINATOR)


def reporter_headers(user_id: str = REPORTER_ID) -> Dict[str, str]:
    """Headers for a ``DataReporter`` caller."""
    return build_user_headers(user_id, C.ROLE_DATA_REPORTER)


def peer_reviewer_headers(user_id: str = PEER_REVIEWER_ID) -> Dict[str, str]:
    """Headers for a ``PeerReviewer`` caller."""
    return build_user_headers(user_id, C.ROLE_PEER_REVIEWER)


def editor_headers(user_id: str = EDITOR_ID) -> Dict[str, str]:
    """Headers for a ``ManagingEditor`` caller."""
    return build_user_headers(user_id, C.ROLE_MANAGING_EDITOR)


def legal_headers(user_id: str = LEGAL_ID) -> Dict[str, str]:
    """Headers for a ``LegalCounsel`` caller."""
    return build_user_headers(user_id, C.ROLE_LEGAL_COUNSEL)


def expert_reviewer_headers(reviewer_id: str) -> Dict[str, str]:
    """Headers for an ``ExpertReviewer`` caller.

    ``reviewer_id`` must be the ``id`` of a registered ``ExpertReviewer`` row:
    PRD S2.1 makes that row's id the caller's ``X-User-ID``.
    """
    return build_user_headers(reviewer_id, C.ROLE_EXPERT_REVIEWER)


def headers_for_role(role: str, user_id: str = "probe-001") -> Dict[str, str]:
    """Headers for an arbitrary named role -- used by role-matrix probes."""
    return build_user_headers(user_id, role)


# --------------------------------------------------------------------------
# Malformed-identity builders for the PRD S2.1 rejection probes
# --------------------------------------------------------------------------


def headers_missing_user_id() -> Dict[str, str]:
    """Headers with ``X-User-ID`` absent entirely (PRD S2.1: "absent")."""
    return {"X-User-Role": C.ROLE_MANAGING_EDITOR, "Content-Type": "application/json"}


def headers_missing_role() -> Dict[str, str]:
    """Headers with ``X-User-Role`` absent entirely (PRD S2.1: "absent")."""
    return {"X-User-ID": EDITOR_ID, "Content-Type": "application/json"}


def headers_empty_user_id() -> Dict[str, str]:
    """Headers whose ``X-User-ID`` is the empty string (PRD S2.1: "empty").

    The value must be ``""`` and never whitespace: ``requests`` raises
    ``InvalidHeader`` on a header value made of spaces, which would abort the
    test before the server ever saw the probe.
    """
    return {
        "X-User-ID": "",
        "X-User-Role": C.ROLE_MANAGING_EDITOR,
        "Content-Type": "application/json",
    }


def headers_empty_role() -> Dict[str, str]:
    """Headers whose ``X-User-Role`` is the empty string (PRD S2.1: "empty")."""
    return {
        "X-User-ID": EDITOR_ID,
        "X-User-Role": "",
        "Content-Type": "application/json",
    }


def headers_unknown_role(role: str = "Publisher") -> Dict[str, str]:
    """Headers naming a role outside the six of PRD S2.1."""
    return build_user_headers(EDITOR_ID, role)
