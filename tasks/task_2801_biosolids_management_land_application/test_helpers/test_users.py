"""Identity headers for every role declared by the contract.

Two roles carry meaning beyond the role name:

* ``FacilityOperator`` - the acting facility's ``id`` travels in ``X-User-ID``,
  so operator headers are minted per facility with ``make_operator_headers``.
* ``Farmer`` - the caller's ``X-User-ID`` is compared against the agreement's
  ``farmer_user_id``, so farmer headers are minted per farmer with
  ``make_farmer_headers``.

The remaining roles are opaque identifiers that are only recorded on the rows
they touch, so a stable default per role is enough. ``ComplianceOfficer`` gets
two distinct identities because one endpoint compares the caller against the
officer who certified a batch.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_AGRONOMIST,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_FACILITY_OPERATOR,
    ROLE_FARMER,
    ROLE_LAB_ANALYST,
    ROLE_PUBLIC_LIAISON,
)

# Stable identifiers for the opaque roles.
CERTIFYING_OFFICER_ID = "officer-cert-1"
CLOSING_OFFICER_ID = "officer-close-2"
LAB_ANALYST_ID = "lab-analyst-1"
AGRONOMIST_ID = "agronomist-1"
PUBLIC_LIAISON_ID = "liaison-1"
DEFAULT_FARMER_ID = "farmer-jones"
OTHER_FARMER_ID = "farmer-smith"
DEFAULT_OPERATOR_ID = "operator-unbound-1"


def make_operator_headers(facility_id: str = DEFAULT_OPERATOR_ID) -> Dict[str, str]:
    """Headers for a FacilityOperator acting as the given facility."""
    return build_user_headers(facility_id, ROLE_FACILITY_OPERATOR)


def make_farmer_headers(farmer_user_id: str = DEFAULT_FARMER_ID) -> Dict[str, str]:
    """Headers for a Farmer identified by the id named on the agreement."""
    return build_user_headers(farmer_user_id, ROLE_FARMER)


def make_officer_headers(user_id: str = CERTIFYING_OFFICER_ID) -> Dict[str, str]:
    """Headers for a ComplianceOfficer under a chosen identity."""
    return build_user_headers(user_id, ROLE_COMPLIANCE_OFFICER)


def make_lab_analyst_headers(user_id: str = LAB_ANALYST_ID) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_LAB_ANALYST)


def make_agronomist_headers(user_id: str = AGRONOMIST_ID) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_AGRONOMIST)


def make_liaison_headers(user_id: str = PUBLIC_LIAISON_ID) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_PUBLIC_LIAISON)


def make_headers(role: str, user_id: str) -> Dict[str, str]:
    """Headers for an arbitrary role/identity pair."""
    return build_user_headers(user_id, role)


# Ready-made headers for the identity-free roles.
OPERATOR_HEADERS = make_operator_headers()
LAB_ANALYST_HEADERS = make_lab_analyst_headers()
OFFICER_HEADERS = make_officer_headers()
CERTIFYING_OFFICER_HEADERS = make_officer_headers(CERTIFYING_OFFICER_ID)
CLOSING_OFFICER_HEADERS = make_officer_headers(CLOSING_OFFICER_ID)
AGRONOMIST_HEADERS = make_agronomist_headers()
FARMER_HEADERS = make_farmer_headers()
OTHER_FARMER_HEADERS = make_farmer_headers(OTHER_FARMER_ID)
LIAISON_HEADERS = make_liaison_headers()

NO_IDENTITY_HEADERS: Dict[str, str] = {"Content-Type": "application/json"}
MISSING_ROLE_HEADERS: Dict[str, str] = {
    "X-User-ID": AGRONOMIST_ID,
    "Content-Type": "application/json",
}
MISSING_USER_ID_HEADERS: Dict[str, str] = {
    "X-User-Role": ROLE_AGRONOMIST,
    "Content-Type": "application/json",
}
BLANK_IDENTITY_HEADERS: Dict[str, str] = {
    "X-User-ID": "",
    "X-User-Role": "",
    "Content-Type": "application/json",
}
UNRECOGNISED_ROLE_HEADERS: Dict[str, str] = build_user_headers(
    "stranger-1", "PlantManager"
)

HEADERS_BY_ROLE = {
    ROLE_FACILITY_OPERATOR: OPERATOR_HEADERS,
    ROLE_LAB_ANALYST: LAB_ANALYST_HEADERS,
    ROLE_COMPLIANCE_OFFICER: OFFICER_HEADERS,
    ROLE_AGRONOMIST: AGRONOMIST_HEADERS,
    ROLE_FARMER: FARMER_HEADERS,
    ROLE_PUBLIC_LIAISON: LIAISON_HEADERS,
}
