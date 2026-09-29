"""Ready-made identity headers for each of the six roles of PRD 2.1.

Two roles carry an ``X-User-ID`` that the server compares against a persisted
row: a ``ClubAdministrator``'s id is the id of the acting ``Club`` and a
``Member``'s id is the id of the acting ``Member``.  Those two therefore need a
builder that takes the entity id.  The four remaining roles carry an opaque
operator identifier the server never compares to an entity id, so a fixed
string is enough -- except for the ``SafeSportOfficer``, where the segregation
of duties rules compare one officer's recorded ``X-User-ID`` against another's,
so several distinct officer principals are provided.
"""

from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_CLUB_ADMIN,
    ROLE_COMPLIANCE_AUDITOR,
    ROLE_MEMBER,
    ROLE_NGB_ADMIN,
    ROLE_SAFESPORT_OFFICER,
    ROLE_SCREENING_VENDOR,
)

# Opaque operator identifiers.  The officer identifiers are meaningful to the
# tests because PRD 2.1 records them and later compares them.
NGB_ADMIN_USER_ID = "ngb_admin"
SCREENING_VENDOR_USER_ID = "vendor_ops"
COMPLIANCE_AUDITOR_USER_ID = "auditor_prime"
OFFICER_INTAKE_USER_ID = "so_intake"
OFFICER_IMPOSE_USER_ID = "so_impose"
OFFICER_REVIEW_USER_ID = "so_review"
OFFICER_CLOSER_USER_ID = "so_closer"
OFFICER_ADJUDICATOR_USER_ID = "so_adjudicator"

TEST_USERS: Dict[str, Dict[str, str]] = {
    "ngb_admin": {"user_id": NGB_ADMIN_USER_ID, "role": ROLE_NGB_ADMIN},
    "screening_vendor": {
        "user_id": SCREENING_VENDOR_USER_ID,
        "role": ROLE_SCREENING_VENDOR,
    },
    "compliance_auditor": {
        "user_id": COMPLIANCE_AUDITOR_USER_ID,
        "role": ROLE_COMPLIANCE_AUDITOR,
    },
    "officer_intake": {
        "user_id": OFFICER_INTAKE_USER_ID,
        "role": ROLE_SAFESPORT_OFFICER,
    },
    "officer_impose": {
        "user_id": OFFICER_IMPOSE_USER_ID,
        "role": ROLE_SAFESPORT_OFFICER,
    },
    "officer_review": {
        "user_id": OFFICER_REVIEW_USER_ID,
        "role": ROLE_SAFESPORT_OFFICER,
    },
    "officer_closer": {
        "user_id": OFFICER_CLOSER_USER_ID,
        "role": ROLE_SAFESPORT_OFFICER,
    },
    "officer_adjudicator": {
        "user_id": OFFICER_ADJUDICATOR_USER_ID,
        "role": ROLE_SAFESPORT_OFFICER,
    },
}

# --- Fixed-identity header dicts ---------------------------------------
NGB_ADMIN_HEADERS = build_user_headers(NGB_ADMIN_USER_ID, ROLE_NGB_ADMIN)
SCREENING_VENDOR_HEADERS = build_user_headers(
    SCREENING_VENDOR_USER_ID, ROLE_SCREENING_VENDOR
)
COMPLIANCE_AUDITOR_HEADERS = build_user_headers(
    COMPLIANCE_AUDITOR_USER_ID, ROLE_COMPLIANCE_AUDITOR
)
OFFICER_INTAKE_HEADERS = build_user_headers(
    OFFICER_INTAKE_USER_ID, ROLE_SAFESPORT_OFFICER
)
OFFICER_IMPOSE_HEADERS = build_user_headers(
    OFFICER_IMPOSE_USER_ID, ROLE_SAFESPORT_OFFICER
)
OFFICER_REVIEW_HEADERS = build_user_headers(
    OFFICER_REVIEW_USER_ID, ROLE_SAFESPORT_OFFICER
)
OFFICER_CLOSER_HEADERS = build_user_headers(
    OFFICER_CLOSER_USER_ID, ROLE_SAFESPORT_OFFICER
)
OFFICER_ADJUDICATOR_HEADERS = build_user_headers(
    OFFICER_ADJUDICATOR_USER_ID, ROLE_SAFESPORT_OFFICER
)


# --- Entity-backed identity builders -----------------------------------
def make_club_admin_headers(club_id: str) -> Dict[str, str]:
    """Headers for the administrator of the club whose ``id`` is ``club_id``."""
    return build_user_headers(club_id, ROLE_CLUB_ADMIN)


def make_member_headers(member_id: str) -> Dict[str, str]:
    """Headers for the member whose ``id`` is ``member_id`` acting for themself."""
    return build_user_headers(member_id, ROLE_MEMBER)


def make_officer_headers(user_id: str) -> Dict[str, str]:
    """Headers for a named SafeSport officer principal."""
    return build_user_headers(user_id, ROLE_SAFESPORT_OFFICER)


def make_ngb_admin_headers(user_id: str = NGB_ADMIN_USER_ID) -> Dict[str, str]:
    """Headers for a named governing-body operator."""
    return build_user_headers(user_id, ROLE_NGB_ADMIN)


def make_auditor_headers(
    user_id: str = COMPLIANCE_AUDITOR_USER_ID,
) -> Dict[str, str]:
    """Headers for a named compliance auditor principal."""
    return build_user_headers(user_id, ROLE_COMPLIANCE_AUDITOR)


def make_headers_with_role(user_id: str, role: str) -> Dict[str, str]:
    """Headers carrying an arbitrary role string, including undeclared ones."""
    return build_user_headers(user_id, role)


NO_IDENTITY_HEADERS: Dict[str, str] = {"Content-Type": "application/json"}
