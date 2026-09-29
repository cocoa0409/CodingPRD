"""Pre-built request headers for each acting identity.

Four of the six roles act under an opaque operator identifier. A ``Mixer``
acts under the ``id`` of its own mixer record, so mixer headers are built per
instance with :func:`mixer_headers`. A ``ClientReviewer`` acts under the opaque
string recorded on the project as ``client_user_id``.
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ADMIN_USER_ID,
    CLIENT_USER_ID,
    EDITOR_USER_ID,
    OTHER_CLIENT_USER_ID,
    QC_ONE_USER_ID,
    QC_TWO_USER_ID,
    ROLE_CLIENT_REVIEWER,
    ROLE_FACILITY_ADMIN,
    ROLE_MIXER,
    ROLE_POST_SUPERVISOR,
    ROLE_QC_OPERATOR,
    ROLE_SOUND_EDITOR,
    SUPERVISOR_TWO_USER_ID,
    SUPERVISOR_USER_ID,
)

ADMIN_HEADERS = build_user_headers(ADMIN_USER_ID, ROLE_FACILITY_ADMIN)
SUPERVISOR_HEADERS = build_user_headers(SUPERVISOR_USER_ID, ROLE_POST_SUPERVISOR)
SUPERVISOR_TWO_HEADERS = build_user_headers(SUPERVISOR_TWO_USER_ID, ROLE_POST_SUPERVISOR)
EDITOR_HEADERS = build_user_headers(EDITOR_USER_ID, ROLE_SOUND_EDITOR)
QC_ONE_HEADERS = build_user_headers(QC_ONE_USER_ID, ROLE_QC_OPERATOR)
QC_TWO_HEADERS = build_user_headers(QC_TWO_USER_ID, ROLE_QC_OPERATOR)
CLIENT_HEADERS = build_user_headers(CLIENT_USER_ID, ROLE_CLIENT_REVIEWER)
OTHER_CLIENT_HEADERS = build_user_headers(OTHER_CLIENT_USER_ID, ROLE_CLIENT_REVIEWER)


def mixer_headers(mixer_id: str) -> dict:
    """Headers for the mixer whose record ``id`` is ``mixer_id``."""
    return build_user_headers(mixer_id, ROLE_MIXER)


def qc_headers(user_id: str) -> dict:
    """Headers for an arbitrary QC operator identifier."""
    return build_user_headers(user_id, ROLE_QC_OPERATOR)


def supervisor_headers(user_id: str) -> dict:
    """Headers for an arbitrary post-supervisor identifier."""
    return build_user_headers(user_id, ROLE_POST_SUPERVISOR)


def client_headers(user_id: str) -> dict:
    """Headers for an arbitrary client-reviewer identifier."""
    return build_user_headers(user_id, ROLE_CLIENT_REVIEWER)


def headers_with_role(role: str, user_id: str = ADMIN_USER_ID) -> dict:
    """Headers naming an arbitrary role, used for authorisation matrices."""
    return build_user_headers(user_id, role)


def headers_missing_user_id(role: str = ROLE_POST_SUPERVISOR) -> dict:
    """Headers that omit ``X-User-ID`` entirely."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_blank_user_id(role: str = ROLE_POST_SUPERVISOR) -> dict:
    """Headers whose ``X-User-ID`` is the empty string."""
    return {"X-User-ID": "", "X-User-Role": role, "Content-Type": "application/json"}


def headers_missing_role(user_id: str = SUPERVISOR_USER_ID) -> dict:
    """Headers that omit ``X-User-Role`` entirely."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_unknown_role(user_id: str = SUPERVISOR_USER_ID) -> dict:
    """Headers naming a role that is not one of the six declared roles."""
    return build_user_headers(user_id, "SoundDesigner")


def headers_no_auth() -> dict:
    """Headers carrying neither identity header."""
    return {"Content-Type": "application/json"}
