"""Prebuilt request headers for the six declared roles.

All six roles carry an opaque identity: the PRD states the server never compares
``X-User-ID`` against any resource's ``id``.  Distinct identifiers still matter,
because segregation of duties is enforced on ``X-User-ID`` and never on the role
-- two different individuals both holding ``RouteEngineer`` are what the rule
requires.  The builders below make that explicit for every accountability point.
"""

from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# Individual operators, one identifier per person.
USER_IDS: Dict[str, str] = {
    "route_engineer": "eng-alice",
    "route_engineer_second": "eng-bob",
    "route_engineer_third": "eng-carol",
    "route_engineer_fourth": "eng-dave",
    "field_surveyor": "survey-dana",
    "permit_coordinator": "coord-erin",
    "authority_reviewer": "city-reviewer-1",
    "authority_reviewer_second": "city-reviewer-2",
    "authority_reviewer_rail": "rail-reviewer-1",
    "authority_reviewer_highway": "dot-reviewer-1",
    "pole_owner": "telco-1",
    "pole_owner_second": "telco-owner-1",
    "pole_owner_municipal": "muni-light-1",
    "pole_owner_electric": "electric-1",
    "network_records_admin": "records-frank",
}


def make_route_engineer_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.ROUTE_ENGINEER.value)


def make_field_surveyor_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.FIELD_SURVEYOR.value)


def make_permit_coordinator_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.PERMIT_COORDINATOR.value)


def make_authority_reviewer_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.AUTHORITY_REVIEWER.value)


def make_pole_owner_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.POLE_OWNER.value)


def make_network_records_admin_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.NETWORK_RECORDS_ADMIN.value)


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Build headers for an arbitrary role string, declared or not."""

    return build_user_headers(user_id, role)


TEST_USERS: Dict[str, Dict[str, str]] = {
    # RouteEngineer -- four distinct individuals so both segregation-of-duties
    # rules (stamping vs submitting, certifying vs stamping) can be exercised.
    "route_engineer": make_route_engineer_headers(USER_IDS["route_engineer"]),
    "route_engineer_second": make_route_engineer_headers(USER_IDS["route_engineer_second"]),
    "route_engineer_third": make_route_engineer_headers(USER_IDS["route_engineer_third"]),
    "route_engineer_fourth": make_route_engineer_headers(USER_IDS["route_engineer_fourth"]),
    "field_surveyor": make_field_surveyor_headers(USER_IDS["field_surveyor"]),
    "permit_coordinator": make_permit_coordinator_headers(USER_IDS["permit_coordinator"]),
    "authority_reviewer": make_authority_reviewer_headers(USER_IDS["authority_reviewer"]),
    "authority_reviewer_second": make_authority_reviewer_headers(
        USER_IDS["authority_reviewer_second"]
    ),
    "authority_reviewer_rail": make_authority_reviewer_headers(USER_IDS["authority_reviewer_rail"]),
    "authority_reviewer_highway": make_authority_reviewer_headers(
        USER_IDS["authority_reviewer_highway"]
    ),
    "pole_owner": make_pole_owner_headers(USER_IDS["pole_owner"]),
    "pole_owner_second": make_pole_owner_headers(USER_IDS["pole_owner_second"]),
    "pole_owner_municipal": make_pole_owner_headers(USER_IDS["pole_owner_municipal"]),
    "pole_owner_electric": make_pole_owner_headers(USER_IDS["pole_owner_electric"]),
    "network_records_admin": make_network_records_admin_headers(
        USER_IDS["network_records_admin"]
    ),
}


def headers_missing_user_id(role: str) -> Dict[str, str]:
    """Headers with the ``X-User-ID`` header absent entirely."""

    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_missing_role(user_id: str) -> Dict[str, str]:
    """Headers with the ``X-User-Role`` header absent entirely."""

    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_blank_user_id(role: str) -> Dict[str, str]:
    """Headers whose ``X-User-ID`` is present but blank -- an empty string."""

    return {"X-User-ID": "", "X-User-Role": role, "Content-Type": "application/json"}


def headers_blank_role(user_id: str) -> Dict[str, str]:
    """Headers whose ``X-User-Role`` is present but blank -- an empty string."""

    return {"X-User-ID": user_id, "X-User-Role": "", "Content-Type": "application/json"}
