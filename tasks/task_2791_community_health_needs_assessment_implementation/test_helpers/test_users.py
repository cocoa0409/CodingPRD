"""Pre-built header bundles for each role, plus builders for extra identities.

``X-User-ID`` is an opaque operator identifier for five of the six roles.  For a
``PartnerRepresentative`` it must be the ``id`` of the acting responsible party,
so that identity can only be built once the party exists — hence the builder.
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import Role

OFFICER_USER_ID = "u_officer_1"
OFFICER_2_USER_ID = "u_officer_2"
STEWARD_USER_ID = "u_steward_1"
BOARD_USER_ID = "u_board_1"
COMPLIANCE_USER_ID = "u_compliance_1"
COMPLIANCE_2_USER_ID = "u_compliance_2"
PUBLIC_USER_ID = "u_public_1"

OFFICER = build_user_headers(OFFICER_USER_ID, Role.COMMUNITY_BENEFIT_OFFICER)
OFFICER_2 = build_user_headers(OFFICER_2_USER_ID, Role.COMMUNITY_BENEFIT_OFFICER)
STEWARD = build_user_headers(STEWARD_USER_ID, Role.DATA_STEWARD)
BOARD = build_user_headers(BOARD_USER_ID, Role.BOARD_CHAIR)
COMPLIANCE = build_user_headers(COMPLIANCE_USER_ID, Role.COMPLIANCE_OFFICER)
COMPLIANCE_2 = build_user_headers(COMPLIANCE_2_USER_ID, Role.COMPLIANCE_OFFICER)
PUBLIC = build_user_headers(PUBLIC_USER_ID, Role.PUBLIC_VIEWER)

TEST_USERS: Dict[str, Dict[str, str]] = {
    "officer": OFFICER,
    "officer_2": OFFICER_2,
    "steward": STEWARD,
    "board": BOARD,
    "compliance": COMPLIANCE,
    "compliance_2": COMPLIANCE_2,
    "public": PUBLIC,
}


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Header bundle for an arbitrary user id / role pair."""
    return build_user_headers(user_id, role)


def make_officer_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, Role.COMMUNITY_BENEFIT_OFFICER)


def make_steward_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, Role.DATA_STEWARD)


def make_board_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, Role.BOARD_CHAIR)


def make_compliance_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, Role.COMPLIANCE_OFFICER)


def make_partner_representative_headers(party_id: str) -> Dict[str, str]:
    """Identity of the partner acting for the responsible party ``party_id``.

    ``X-User-ID`` is the id of the acting responsible party, which is what the
    counterparty comparison on a partner signature reads.
    """
    return build_user_headers(party_id, Role.PARTNER_REPRESENTATIVE)


def make_public_viewer_headers(user_id: str = PUBLIC_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, Role.PUBLIC_VIEWER)


def headers_for_role(role: str, user_id: str = "u_generic_1") -> Dict[str, str]:
    """Header bundle for any of the six declared role names."""
    return build_user_headers(user_id, role)
