"""Caller identities, one per role, with distinct user ids per owner.

Eight of the nine roles carry an opaque ``X-User-ID`` that the server only
records; the ``Distributor`` role's ``X-User-ID`` *is* the distributor row's
id, so its headers must be built from a registered row (PRD 2.1).
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_BUILD_TECHNICIAN,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_DESIGN_ENGINEER,
    ROLE_DESIGN_REVIEWER,
    ROLE_DISTRIBUTOR,
    ROLE_PLANT_ADMIN,
    ROLE_PRODUCTION_PLANNER,
    ROLE_QUALITY_CERTIFIER,
    ROLE_TEST_ENGINEER,
)

# ── Opaque user ids, distinct per acting party ────────────────────────────────

USER_DESIGN_ENGINEER = "u-design-engineer-1"
USER_DESIGN_ENGINEER_OTHER = "u-design-engineer-2"
USER_DESIGN_REVIEWER = "u-design-reviewer-1"
USER_DESIGN_REVIEWER_OTHER = "u-design-reviewer-2"
USER_PRODUCTION_PLANNER = "u-production-planner-1"
USER_BUILD_TECHNICIAN = "u-build-technician-1"
USER_BUILD_TECHNICIAN_OTHER = "u-build-technician-2"
USER_TEST_ENGINEER = "u-test-engineer-1"
USER_TEST_ENGINEER_OTHER = "u-test-engineer-2"
USER_QUALITY_CERTIFIER = "u-quality-certifier-1"
USER_QUALITY_CERTIFIER_OTHER = "u-quality-certifier-2"
USER_COMPLIANCE_OFFICER = "u-compliance-officer-1"
USER_PLANT_ADMIN = "u-plant-admin-1"

# ── Ready-made header dicts ──────────────────────────────────────────────────

DESIGN_ENGINEER = build_user_headers(USER_DESIGN_ENGINEER, ROLE_DESIGN_ENGINEER)
DESIGN_ENGINEER_OTHER = build_user_headers(
    USER_DESIGN_ENGINEER_OTHER, ROLE_DESIGN_ENGINEER
)
DESIGN_REVIEWER = build_user_headers(USER_DESIGN_REVIEWER, ROLE_DESIGN_REVIEWER)
DESIGN_REVIEWER_OTHER = build_user_headers(
    USER_DESIGN_REVIEWER_OTHER, ROLE_DESIGN_REVIEWER
)
PRODUCTION_PLANNER = build_user_headers(
    USER_PRODUCTION_PLANNER, ROLE_PRODUCTION_PLANNER
)
BUILD_TECHNICIAN = build_user_headers(USER_BUILD_TECHNICIAN, ROLE_BUILD_TECHNICIAN)
BUILD_TECHNICIAN_OTHER = build_user_headers(
    USER_BUILD_TECHNICIAN_OTHER, ROLE_BUILD_TECHNICIAN
)
TEST_ENGINEER = build_user_headers(USER_TEST_ENGINEER, ROLE_TEST_ENGINEER)
TEST_ENGINEER_OTHER = build_user_headers(USER_TEST_ENGINEER_OTHER, ROLE_TEST_ENGINEER)
QUALITY_CERTIFIER = build_user_headers(USER_QUALITY_CERTIFIER, ROLE_QUALITY_CERTIFIER)
QUALITY_CERTIFIER_OTHER = build_user_headers(
    USER_QUALITY_CERTIFIER_OTHER, ROLE_QUALITY_CERTIFIER
)
COMPLIANCE_OFFICER = build_user_headers(
    USER_COMPLIANCE_OFFICER, ROLE_COMPLIANCE_OFFICER
)
PLANT_ADMIN = build_user_headers(USER_PLANT_ADMIN, ROLE_PLANT_ADMIN)


def make_distributor_headers(distributor_id: str) -> Dict[str, str]:
    """Headers for a ``Distributor`` caller acting as the given row."""
    return build_user_headers(distributor_id, ROLE_DISTRIBUTOR)


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Headers for an arbitrary user id / role pair."""
    return build_user_headers(user_id, role)


def headers_for_role(role: str, distributor_id: str = None) -> Dict[str, str]:
    """A representative caller for the named role.

    ``Distributor`` requires the id of a registered distributor row, because
    for that role the ``X-User-ID`` header is the row id itself.
    """
    if role == ROLE_DISTRIBUTOR:
        assert distributor_id is not None, "Distributor callers need a row id"
        return make_distributor_headers(distributor_id)
    return build_user_headers("u-%s-1" % role.lower(), role)


# ── Malformed identities for the authentication gate (PRD 2.1) ───────────────

NO_HEADERS: Dict[str, str] = {"Content-Type": "application/json"}

MISSING_USER_ID: Dict[str, str] = {
    "X-User-Role": ROLE_PLANT_ADMIN,
    "Content-Type": "application/json",
}

MISSING_ROLE: Dict[str, str] = {
    "X-User-ID": USER_PLANT_ADMIN,
    "Content-Type": "application/json",
}

# A truly empty string, never a whitespace-only value.
EMPTY_USER_ID: Dict[str, str] = {
    "X-User-ID": "",
    "X-User-Role": ROLE_PLANT_ADMIN,
    "Content-Type": "application/json",
}

EMPTY_ROLE: Dict[str, str] = {
    "X-User-ID": USER_PLANT_ADMIN,
    "X-User-Role": "",
    "Content-Type": "application/json",
}

UNDECLARED_ROLE: Dict[str, str] = {
    "X-User-ID": USER_PLANT_ADMIN,
    "X-User-Role": "PlantSupervisor",
    "Content-Type": "application/json",
}
