"""Caller identities for the six declared roles.

Two roles are entity-backed: a SchoolLiaison presents the id of the School it
signs for, and a CorpsMember presents the id of its own member record. Those
two get per-instance builders, and any ownership-gated call MUST be made with
``make_school_liaison_headers(school["id"]``) / ``make_corps_member_headers(
member["id"])`` — never with a shared constant, because an opaque identifier
never equals a real entity id and every ownership check would reject it.

The other four roles treat ``X-User-ID`` as an opaque operator identifier, so
stable shared constants are canonical for them. Two stipend administrators
exist so the segregation-of-duties rule (approver != creator) can be
exercised both ways.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# Opaque operator identifiers for the non-entity-backed roles.
TEST_USERS: Dict[str, Dict[str, str]] = {
    "site_director": {"id": "sd-1", "role": UserRole.SITE_DIRECTOR.value},
    "program_manager": {"id": "pm-1", "role": UserRole.PROGRAM_MANAGER.value},
    "stipend_admin_1": {"id": "sa-1", "role": UserRole.STIPEND_ADMINISTRATOR.value},
    "stipend_admin_2": {"id": "sa-2", "role": UserRole.STIPEND_ADMINISTRATOR.value},
    "applicant_jordan": {"id": "app-jordan", "role": UserRole.APPLICANT.value},
    "applicant_riley": {"id": "app-riley", "role": UserRole.APPLICANT.value},
    "applicant_casey": {"id": "app-casey", "role": UserRole.APPLICANT.value},
    "applicant_devon": {"id": "app-devon", "role": UserRole.APPLICANT.value},
}

# Ready-made header dicts for the opaque roles.
SITE_DIRECTOR_HEADERS = build_user_headers(TEST_USERS["site_director"]["id"], UserRole.SITE_DIRECTOR.value)
PROGRAM_MANAGER_HEADERS = build_user_headers(TEST_USERS["program_manager"]["id"], UserRole.PROGRAM_MANAGER.value)
STIPEND_ADMIN_1_HEADERS = build_user_headers(TEST_USERS["stipend_admin_1"]["id"], UserRole.STIPEND_ADMINISTRATOR.value)
STIPEND_ADMIN_2_HEADERS = build_user_headers(TEST_USERS["stipend_admin_2"]["id"], UserRole.STIPEND_ADMINISTRATOR.value)


def make_applicant_headers(user_id: str) -> Dict[str, str]:
    """Applicant is opaque; the id only distinguishes applicant personas."""
    return build_user_headers(user_id, UserRole.APPLICANT.value)


def make_school_liaison_headers(school_id: str) -> Dict[str, str]:
    """SchoolLiaison is entity-backed: pass the acting School's id.

    Mandatory on every school-scoped liaison write (signing, amendment
    confirmation, report review); ownership compares X-User-ID to the
    school's id.
    """
    return build_user_headers(school_id, UserRole.SCHOOL_LIAISON.value)


def make_corps_member_headers(member_id: str) -> Dict[str, str]:
    """CorpsMember is entity-backed: pass the acting CorpsMember's id.

    Mandatory for hour logging (corps_member_id must equal X-User-ID) and for
    the member-self reads.
    """
    return build_user_headers(member_id, UserRole.CORPS_MEMBER.value)
