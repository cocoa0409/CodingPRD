"""Operator identities and their request headers (PRD §2.1).

Six of the seven roles carry an opaque `X-User-ID` that the server never
resolves against a stored row, so those header dicts are module-level
constants. `Participant` is the one entity-backed role — its `X-User-ID` is the
`id` of the acting `Participant` row — so its headers must be built per human
with `participant_headers(participant_id)`.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_COURSE_DESIGNER,
    ROLE_OBSTACLE_MARSHAL,
    ROLE_PARTICIPANT,
    ROLE_PERMIT_OFFICER,
    ROLE_RACE_DIRECTOR,
    ROLE_SAFETY_OFFICER,
    ROLE_SITE_OPS_LEAD,
    USER_DESIGNER_1,
    USER_DESIGNER_2,
    USER_DIRECTOR_1,
    USER_DIRECTOR_2,
    USER_DUAL_HAT,
    USER_MARSHAL_1,
    USER_MARSHAL_2,
    USER_MARSHAL_7,
    USER_OFFICER_1,
    USER_OFFICER_2,
    USER_OPS_1,
    USER_OPS_2,
    USER_SAFETY_1,
    USER_SAFETY_2,
)

# ─── Opaque-identity roles ──────────────────────────────────────────────

OFFICER = build_user_headers(USER_OFFICER_1, ROLE_PERMIT_OFFICER)
OFFICER_2 = build_user_headers(USER_OFFICER_2, ROLE_PERMIT_OFFICER)
DESIGNER = build_user_headers(USER_DESIGNER_1, ROLE_COURSE_DESIGNER)
DESIGNER_2 = build_user_headers(USER_DESIGNER_2, ROLE_COURSE_DESIGNER)
DIRECTOR = build_user_headers(USER_DIRECTOR_1, ROLE_RACE_DIRECTOR)
DIRECTOR_2 = build_user_headers(USER_DIRECTOR_2, ROLE_RACE_DIRECTOR)
SAFETY = build_user_headers(USER_SAFETY_1, ROLE_SAFETY_OFFICER)
SAFETY_2 = build_user_headers(USER_SAFETY_2, ROLE_SAFETY_OFFICER)
OPS = build_user_headers(USER_OPS_1, ROLE_SITE_OPS_LEAD)
OPS_2 = build_user_headers(USER_OPS_2, ROLE_SITE_OPS_LEAD)
MARSHAL = build_user_headers(USER_MARSHAL_1, ROLE_OBSTACLE_MARSHAL)
MARSHAL_2 = build_user_headers(USER_MARSHAL_2, ROLE_OBSTACLE_MARSHAL)
MARSHAL_7 = build_user_headers(USER_MARSHAL_7, ROLE_OBSTACLE_MARSHAL)

# One human wearing two hats: files the land-use application as a
# CourseDesigner and then attempts to rule on it as a PermitOfficer under the
# very same X-User-ID (PRD §2.7).
DUAL_HAT_DESIGNER = build_user_headers(USER_DUAL_HAT, ROLE_COURSE_DESIGNER)
DUAL_HAT_OFFICER = build_user_headers(USER_DUAL_HAT, ROLE_PERMIT_OFFICER)

# The marshal who recorded a disputed attempt, wearing the RaceDirector hat in
# order to try to adjudicate the protest against their own observation.
DUAL_HAT_MARSHAL = build_user_headers(USER_MARSHAL_7, ROLE_OBSTACLE_MARSHAL)
DUAL_HAT_MARSHAL_AS_DIRECTOR = build_user_headers(USER_MARSHAL_7, ROLE_RACE_DIRECTOR)

#: The five roles the PRD authorises to read a venue, a permit or a course.
READER_HEADERS_BY_ROLE: Dict[str, Dict[str, str]] = {
    ROLE_PERMIT_OFFICER: OFFICER,
    ROLE_COURSE_DESIGNER: DESIGNER,
    ROLE_RACE_DIRECTOR: DIRECTOR,
    ROLE_SAFETY_OFFICER: SAFETY,
    ROLE_SITE_OPS_LEAD: OPS,
    ROLE_OBSTACLE_MARSHAL: MARSHAL,
}


# ─── The entity-backed role ─────────────────────────────────────────────


def participant_headers(participant_id: str) -> Dict[str, str]:
    """Headers for the Participant whose own row id is `participant_id`."""
    return build_user_headers(participant_id, ROLE_PARTICIPANT)


# ─── Arbitrary and malformed identities ─────────────────────────────────


def headers_for(user_id: str, role: str) -> Dict[str, str]:
    """Arbitrary user/role pairing, for identity-separation probes."""
    return build_user_headers(user_id, role)


def headers_missing_user_id(role: str) -> Dict[str, str]:
    """Headers carrying a role but no X-User-ID at all."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_missing_role(user_id: str) -> Dict[str, str]:
    """Headers carrying an operator id but no X-User-Role at all."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_blank_user_id(role: str) -> Dict[str, str]:
    """Headers whose X-User-ID is present but empty.

    The value is the empty string, never whitespace: a whitespace-only header
    value is rejected by the HTTP client before the request is ever sent.
    """
    return {"X-User-ID": "", "X-User-Role": role, "Content-Type": "application/json"}


def headers_blank_role(user_id: str) -> Dict[str, str]:
    """Headers whose X-User-Role is present but empty (never whitespace)."""
    return {
        "X-User-ID": user_id,
        "X-User-Role": "",
        "Content-Type": "application/json",
    }
