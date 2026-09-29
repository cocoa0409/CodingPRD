"""Pre-built authentication headers for each role.

The five operator roles carry an opaque `X-User-ID` that is never compared against
any entity's `id`, so a module-level constant per role is sufficient — and several
distinct ids per role are provided because the two segregation-of-duties checks
compare one operator's id against another's recorded id.

The `Pilot` role is different: `X-User-ID` is the `id` of the acting `Pilot`
entity, so pilot headers must always be built from a real pilot id with
`make_pilot_headers`.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import Role

# ---------------------------------------------------------------------------
# Opaque operator identifiers
# ---------------------------------------------------------------------------

COMPLIANCE_OFFICER_ID = "officer-compliance-001"
COMPLIANCE_OFFICER_ID_2 = "officer-compliance-002"

AIRSPACE_AUTHORITY_ID = "officer-airspace-001"
AIRSPACE_AUTHORITY_ID_2 = "officer-airspace-002"

SAFETY_REVIEWER_ID = "officer-safety-001"
SAFETY_REVIEWER_ID_2 = "officer-safety-002"

WAIVER_APPROVER_ID = "officer-waiver-001"
WAIVER_APPROVER_ID_2 = "officer-waiver-002"

INVESTIGATION_OFFICER_ID = "officer-investigation-001"
INVESTIGATION_OFFICER_ID_2 = "officer-investigation-002"


# ---------------------------------------------------------------------------
# Ready-made header dicts for the opaque operator roles
# ---------------------------------------------------------------------------

COMPLIANCE_OFFICER = build_user_headers(COMPLIANCE_OFFICER_ID, Role.COMPLIANCE_OFFICER.value)
COMPLIANCE_OFFICER_2 = build_user_headers(COMPLIANCE_OFFICER_ID_2, Role.COMPLIANCE_OFFICER.value)

AIRSPACE_AUTHORITY = build_user_headers(AIRSPACE_AUTHORITY_ID, Role.AIRSPACE_AUTHORITY.value)
AIRSPACE_AUTHORITY_2 = build_user_headers(AIRSPACE_AUTHORITY_ID_2, Role.AIRSPACE_AUTHORITY.value)

SAFETY_REVIEWER = build_user_headers(SAFETY_REVIEWER_ID, Role.SAFETY_REVIEWER.value)
SAFETY_REVIEWER_2 = build_user_headers(SAFETY_REVIEWER_ID_2, Role.SAFETY_REVIEWER.value)

WAIVER_APPROVER = build_user_headers(WAIVER_APPROVER_ID, Role.WAIVER_APPROVER.value)
WAIVER_APPROVER_2 = build_user_headers(WAIVER_APPROVER_ID_2, Role.WAIVER_APPROVER.value)

INVESTIGATION_OFFICER = build_user_headers(
    INVESTIGATION_OFFICER_ID, Role.INVESTIGATION_OFFICER.value
)
INVESTIGATION_OFFICER_2 = build_user_headers(
    INVESTIGATION_OFFICER_ID_2, Role.INVESTIGATION_OFFICER.value
)

TEST_USERS: Dict[str, Dict[str, str]] = {
    "compliance_officer": COMPLIANCE_OFFICER,
    "compliance_officer_2": COMPLIANCE_OFFICER_2,
    "airspace_authority": AIRSPACE_AUTHORITY,
    "airspace_authority_2": AIRSPACE_AUTHORITY_2,
    "safety_reviewer": SAFETY_REVIEWER,
    "safety_reviewer_2": SAFETY_REVIEWER_2,
    "waiver_approver": WAIVER_APPROVER,
    "waiver_approver_2": WAIVER_APPROVER_2,
    "investigation_officer": INVESTIGATION_OFFICER,
    "investigation_officer_2": INVESTIGATION_OFFICER_2,
}


# ---------------------------------------------------------------------------
# The entity-backed Pilot role
# ---------------------------------------------------------------------------


def make_pilot_headers(pilot_id: str) -> Dict[str, str]:
    """Headers for a pilot acting on their own resources.

    `X-User-ID` is the `id` of the acting `Pilot` entity, which is what every
    ownership comparison is made against.
    """
    return build_user_headers(pilot_id, Role.PILOT.value)


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Headers for an arbitrary user id / role pair."""
    return build_user_headers(user_id, role)


# ---------------------------------------------------------------------------
# Malformed authentication headers
#
# A header that is present but empty or whitespace-only must be rejected exactly
# like an absent one. Empty strings are used deliberately: a value made of spaces
# is still a legal HTTP header value, whereas some clients reject other shapes.
# ---------------------------------------------------------------------------


def headers_missing_user_id(role: str) -> Dict[str, str]:
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_missing_role(user_id: str) -> Dict[str, str]:
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_empty_user_id(role: str) -> Dict[str, str]:
    return {"X-User-ID": "", "X-User-Role": role, "Content-Type": "application/json"}


def headers_empty_role(user_id: str) -> Dict[str, str]:
    return {"X-User-ID": user_id, "X-User-Role": "", "Content-Type": "application/json"}


def headers_whitespace_user_id(role: str) -> Dict[str, str]:
    return {"X-User-ID": "   ", "X-User-Role": role, "Content-Type": "application/json"}


def headers_whitespace_role(user_id: str) -> Dict[str, str]:
    return {"X-User-ID": user_id, "X-User-Role": "   ", "Content-Type": "application/json"}


def headers_unknown_role(user_id: str = "someone") -> Dict[str, str]:
    """An `X-User-Role` value that is not one of the six declared roles."""
    return build_user_headers(user_id, "AirTrafficController")


NO_HEADERS: Dict[str, str] = {"Content-Type": "application/json"}
