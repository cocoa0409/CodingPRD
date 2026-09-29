"""Ready-made identity headers for each of the seven roles (PRD 2.1).

Six of the seven roles carry an **opaque** ``X-User-ID`` that the server never
resolves to a stored entity, so a fixed literal per role is sufficient and two
distinct literals per role are provided wherever a segregation-of-duties test
needs a second principal in the same capacity.

``LodgingOperator`` is the one entity-backed role: its ``X-User-ID`` is the
``id`` of the acting lodging business, so operator headers can only be built
once the business exists.  Use :func:`operator_headers`.
"""
from typing import Dict, Optional

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# --------------------------------------------------------------------------
# Opaque principals.  Two identities are published for every role that takes
# part in a separation-of-duties comparison (PRD 2.11).
# --------------------------------------------------------------------------
ADMIN_USER_ID = "district-admin-01"
ADMIN_2_USER_ID = "district-admin-02"
BOARD_MEMBER_USER_ID = "board-member-01"
BOARD_MEMBER_2_USER_ID = "board-member-02"
DMO_LIAISON_USER_ID = "dmo-liaison-01"
DMO_LIAISON_2_USER_ID = "dmo-liaison-02"
HEARING_OFFICER_USER_ID = "hearing-officer-01"
HEARING_OFFICER_2_USER_ID = "hearing-officer-02"
AUDITOR_USER_ID = "auditor-01"
AUDITOR_2_USER_ID = "auditor-02"
PUBLIC_VIEWER_USER_ID = "public-viewer-01"

ADMIN = build_user_headers(ADMIN_USER_ID, UserRole.DISTRICT_ADMINISTRATOR.value)
ADMIN_2 = build_user_headers(ADMIN_2_USER_ID, UserRole.DISTRICT_ADMINISTRATOR.value)
BOARD_MEMBER = build_user_headers(BOARD_MEMBER_USER_ID, UserRole.BOARD_MEMBER.value)
BOARD_MEMBER_2 = build_user_headers(BOARD_MEMBER_2_USER_ID, UserRole.BOARD_MEMBER.value)
DMO_LIAISON = build_user_headers(DMO_LIAISON_USER_ID, UserRole.DMO_LIAISON.value)
DMO_LIAISON_2 = build_user_headers(DMO_LIAISON_2_USER_ID, UserRole.DMO_LIAISON.value)
HEARING_OFFICER = build_user_headers(
    HEARING_OFFICER_USER_ID, UserRole.HEARING_OFFICER.value
)
HEARING_OFFICER_2 = build_user_headers(
    HEARING_OFFICER_2_USER_ID, UserRole.HEARING_OFFICER.value
)
AUDITOR = build_user_headers(AUDITOR_USER_ID, UserRole.INDEPENDENT_AUDITOR.value)
AUDITOR_2 = build_user_headers(AUDITOR_2_USER_ID, UserRole.INDEPENDENT_AUDITOR.value)
PUBLIC_VIEWER = build_user_headers(PUBLIC_VIEWER_USER_ID, UserRole.PUBLIC_VIEWER.value)

#: The headers of every role, keyed by the role string the PRD publishes.
HEADERS_BY_ROLE: Dict[str, Dict[str, str]] = {
    UserRole.DISTRICT_ADMINISTRATOR.value: ADMIN,
    UserRole.BOARD_MEMBER.value: BOARD_MEMBER,
    UserRole.DMO_LIAISON.value: DMO_LIAISON,
    UserRole.HEARING_OFFICER.value: HEARING_OFFICER,
    UserRole.INDEPENDENT_AUDITOR.value: AUDITOR,
    UserRole.PUBLIC_VIEWER.value: PUBLIC_VIEWER,
}

#: The five roles whose identity is opaque and needs no backing entity, plus
#: PublicViewer; LodgingOperator is deliberately absent because it is
#: entity-backed and must name a real lodging business.
OPAQUE_ROLES = tuple(HEADERS_BY_ROLE)


def operator_headers(lodging_business_id: str) -> Dict[str, str]:
    """Headers for a ``LodgingOperator`` acting as the named lodging business.

    PRD 2.1: "When ``X-User-Role`` is ``LodgingOperator``, ``X-User-ID`` is the
    ``id`` of the acting lodging business".
    """
    return build_user_headers(lodging_business_id, UserRole.LODGING_OPERATOR.value)


def headers_for_role(role: str, lodging_business_id: Optional[str] = None) -> Dict[str, str]:
    """Headers for an arbitrary role string, entity-backed or opaque."""
    if role == UserRole.LODGING_OPERATOR.value:
        assert lodging_business_id is not None, (
            "LodgingOperator headers need the id of the acting lodging business"
        )
        return operator_headers(lodging_business_id)
    return build_user_headers("opaque-%s-01" % role.lower(), role)


# --------------------------------------------------------------------------
# Malformed identity headers.  PRD 2.1: a request that omits either header,
# sends either as empty, or names a role outside the set of seven is rejected
# with ERR_UNAUTHENTICATED.  An empty value is sent as the empty string, which
# is what "sends either as empty" means on the wire.
# --------------------------------------------------------------------------
#: No identity headers at all — the shape the ten public reads are served in.
NO_HEADERS: Optional[Dict[str, str]] = None

#: X-User-Role present, X-User-ID absent.
MISSING_USER_ID = {
    "X-User-Role": UserRole.DISTRICT_ADMINISTRATOR.value,
    "Content-Type": "application/json",
}

#: X-User-ID present, X-User-Role absent.
MISSING_ROLE = {
    "X-User-ID": ADMIN_USER_ID,
    "Content-Type": "application/json",
}

#: X-User-ID sent as the empty string.
EMPTY_USER_ID = build_user_headers("", UserRole.DISTRICT_ADMINISTRATOR.value)

#: X-User-Role sent as the empty string.
EMPTY_ROLE = build_user_headers(ADMIN_USER_ID, "")

#: A role string outside the set of seven.
UNKNOWN_ROLE = build_user_headers(ADMIN_USER_ID, "TourismCzar")

#: A LodgingOperator identity that resolves to no lodging business at all
#: (PRD 2.1: ERR_OPERATOR_IDENTITY_UNKNOWN, before any path id is looked up).
UNKNOWN_OPERATOR = build_user_headers(
    "00000000-0000-4000-8000-000000000000", UserRole.LODGING_OPERATOR.value
)
