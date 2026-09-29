"""
Acting identities and the header builders that carry them.

The contract splits the six roles in two.  Four of them — ``PracticeAdmin``,
``PharmacyTech``, ``BillingSpecialist`` and ``ComplianceOfficer`` — carry an
opaque operator identifier that is never compared to any row, so a fixed string
is enough and several distinct strings are needed where a segregation-of-duties
rule compares two of them.  The other two — ``RetinaSpecialist`` and ``Patient``
— must carry the ``id`` of a stored row, so their headers can only be built once
that row exists.
"""

from typing import Dict, Optional

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_BILLING_SPECIALIST,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_PATIENT,
    ROLE_PHARMACY_TECH,
    ROLE_PRACTICE_ADMIN,
    ROLE_RETINA_SPECIALIST,
)

# --------------------------------------------------------------------------
# Opaque operator identifiers
#
# Each owner gets its own string.  The two compliance-officer identifiers are
# deliberately distinct because a recall may not be closed by the officer who
# opened it, and the practice-admin / tech / billing identifiers are distinct so
# that a trace never confuses two operators.
# --------------------------------------------------------------------------
ADMIN_USER_ID = "U-ADMIN-1"
TECH_USER_ID = "U-TECH-1"
TECH_USER_ID_ALT = "night-shift-terminal-3"
BILLING_USER_ID = "U-BILL-1"
COMPLIANCE_USER_ID = "U-CO-1"
COMPLIANCE_USER_ID_2 = "U-CO-2"
COMPLIANCE_USER_ID_3 = "U-CO-3"

# An unknown role name, used to exercise the unknown-role rejection.
UNKNOWN_ROLE_NAME = "Concierge"

# A syntactically valid UUID that resolves to no Clinician and no Patient row.
UNRESOLVABLE_IDENTITY = "11111111-1111-4111-8111-111111111111"

# The four opaque-identity roles keyed by role name.
TEST_USERS: Dict[str, Dict[str, str]] = {
    ROLE_PRACTICE_ADMIN: {"user_id": ADMIN_USER_ID, "role": ROLE_PRACTICE_ADMIN},
    ROLE_PHARMACY_TECH: {"user_id": TECH_USER_ID, "role": ROLE_PHARMACY_TECH},
    ROLE_BILLING_SPECIALIST: {"user_id": BILLING_USER_ID, "role": ROLE_BILLING_SPECIALIST},
    ROLE_COMPLIANCE_OFFICER: {"user_id": COMPLIANCE_USER_ID, "role": ROLE_COMPLIANCE_OFFICER},
}


def headers_for(role: str, user_id: str) -> Dict[str, str]:
    """Build the two auth headers plus ``Content-Type`` for an arbitrary pairing."""
    return build_user_headers(user_id, role)


def admin_headers(user_id: str = ADMIN_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_PRACTICE_ADMIN)


def tech_headers(user_id: str = TECH_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_PHARMACY_TECH)


def billing_headers(user_id: str = BILLING_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_BILLING_SPECIALIST)


def compliance_headers(user_id: str = COMPLIANCE_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_COMPLIANCE_OFFICER)


def specialist_headers(clinician_id: str) -> Dict[str, str]:
    """
    Build ``RetinaSpecialist`` headers.  ``clinician_id`` must be the ``id`` of a
    stored Clinician row or the request is refused before anything else is read.
    """
    return build_user_headers(clinician_id, ROLE_RETINA_SPECIALIST)


def patient_headers(patient_id: str) -> Dict[str, str]:
    """
    Build ``Patient`` headers.  ``patient_id`` must be the ``id`` of a stored
    Patient row.
    """
    return build_user_headers(patient_id, ROLE_PATIENT)


def headers_omitting(base: Dict[str, str], *names: str) -> Dict[str, str]:
    """
    Copy ``base`` with the named headers removed entirely.

    Absence is expressed by omission rather than by a whitespace-only value: a
    header carrying only spaces is not "empty" on the wire and the HTTP client
    rejects it outright.
    """
    return {key: value for key, value in base.items() if key not in names}


def headers_blanking(base: Dict[str, str], *names: str) -> Dict[str, str]:
    """Copy ``base`` with the named headers set to the empty string."""
    out = dict(base)
    for name in names:
        out[name] = ""
    return out


def with_role(base: Dict[str, str], role: Optional[str]) -> Dict[str, str]:
    """Copy ``base`` overriding only ``X-User-Role``."""
    out = dict(base)
    if role is None:
        out.pop("X-User-Role", None)
    else:
        out["X-User-Role"] = role
    return out


def with_user_id(base: Dict[str, str], user_id: str) -> Dict[str, str]:
    """Copy ``base`` overriding only ``X-User-ID``."""
    out = dict(base)
    out["X-User-ID"] = user_id
    return out
