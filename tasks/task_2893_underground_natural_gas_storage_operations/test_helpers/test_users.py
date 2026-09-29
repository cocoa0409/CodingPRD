"""Acting identities for every request the suite makes.

PRD §2.1 splits identity in two. For the four operator-staff roles "the
`X-User-ID` value is an opaque operator identifier that is not tied to any
persisted entity", so those headers are plain constants. For `Shipper`,
"`X-User-ID` is the `id` of the acting `Shipper` record", so shipper headers
must be built from a real entity id at test time.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_COMPLIANCE_OFFICER,
    ROLE_FIELD_OPERATOR,
    ROLE_INTEGRITY_ENGINEER,
    ROLE_SCHEDULING_COORDINATOR,
    ROLE_SHIPPER,
)

# ─── Opaque operator identifiers ───────────────────────────────────────────
OPERATOR_A_ID = "op-a"
OPERATOR_B_ID = "op-b"
ENGINEER_A_ID = "eng-a"
ENGINEER_B_ID = "eng-b"
COORDINATOR_A_ID = "coord-a"
COORDINATOR_B_ID = "coord-b"
OFFICER_A_ID = "officer-a"
OFFICER_B_ID = "officer-b"

FIELD_OPERATOR = build_user_headers(OPERATOR_A_ID, ROLE_FIELD_OPERATOR)
FIELD_OPERATOR_B = build_user_headers(OPERATOR_B_ID, ROLE_FIELD_OPERATOR)
INTEGRITY_ENGINEER = build_user_headers(ENGINEER_A_ID, ROLE_INTEGRITY_ENGINEER)
INTEGRITY_ENGINEER_B = build_user_headers(ENGINEER_B_ID, ROLE_INTEGRITY_ENGINEER)
SCHEDULING_COORDINATOR = build_user_headers(COORDINATOR_A_ID, ROLE_SCHEDULING_COORDINATOR)
SCHEDULING_COORDINATOR_B = build_user_headers(COORDINATOR_B_ID, ROLE_SCHEDULING_COORDINATOR)
COMPLIANCE_OFFICER = build_user_headers(OFFICER_A_ID, ROLE_COMPLIANCE_OFFICER)
COMPLIANCE_OFFICER_B = build_user_headers(OFFICER_B_ID, ROLE_COMPLIANCE_OFFICER)

# The opaque operator identifier each staff header carries, keyed by a readable
# label. PRD §2.1: the server "records it where a workflow demands an audit
# trail -- as `recorded_by_user_id` on a mechanical integrity test, as
# `completed_by_user_id` on a remediation program, and as `prepared_by_user_id`
# and `submitted_by_user_id` on a regulatory report", so a test that asserts one
# of those audit fields compares it against the id its acting header sent.
STAFF_USER_IDS: Dict[str, str] = {
    "FieldOperator": OPERATOR_A_ID,
    "FieldOperatorB": OPERATOR_B_ID,
    "IntegrityEngineer": ENGINEER_A_ID,
    "IntegrityEngineerB": ENGINEER_B_ID,
    "SchedulingCoordinator": COORDINATOR_A_ID,
    "SchedulingCoordinatorB": COORDINATOR_B_ID,
    "ComplianceOfficer": OFFICER_A_ID,
    "ComplianceOfficerB": OFFICER_B_ID,
}

# Every staff role keyed by its role string, for parametrized role sweeps.
STAFF_HEADERS_BY_ROLE: Dict[str, Dict[str, str]] = {
    ROLE_FIELD_OPERATOR: FIELD_OPERATOR,
    ROLE_INTEGRITY_ENGINEER: INTEGRITY_ENGINEER,
    ROLE_SCHEDULING_COORDINATOR: SCHEDULING_COORDINATOR,
    ROLE_COMPLIANCE_OFFICER: COMPLIANCE_OFFICER,
}


def make_shipper_headers(shipper_id: str) -> Dict[str, str]:
    """Headers for a `Shipper` acting as the entity whose `id` is shipper_id."""
    return build_user_headers(shipper_id, ROLE_SHIPPER)


def headers_for_role(role: str, shipper_id: str = None) -> Dict[str, str]:
    """Headers for any of the five roles; Shipper needs a real entity id."""
    if role == ROLE_SHIPPER:
        assert shipper_id is not None, "Shipper headers require a Shipper.id"
        return make_shipper_headers(shipper_id)
    return dict(STAFF_HEADERS_BY_ROLE[role])


# ─── Malformed identity headers (PRD §2.1 rung 1) ──────────────────────────
# "If either header is absent, present but empty, or if `X-User-Role` names
# anything other than one of the five roles below" -> ERR_UNAUTHENTICATED.
NO_AUTH_HEADERS: Dict[str, str] = {"Content-Type": "application/json"}


def headers_missing_role(user_id: str = OPERATOR_A_ID) -> Dict[str, str]:
    """X-User-ID present, X-User-Role absent entirely."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_missing_user_id(role: str = ROLE_FIELD_OPERATOR) -> Dict[str, str]:
    """X-User-Role present, X-User-ID absent entirely."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_empty_user_id(role: str = ROLE_FIELD_OPERATOR) -> Dict[str, str]:
    """X-User-ID present but the empty string -- not whitespace, not omitted."""
    return {"X-User-ID": "", "X-User-Role": role, "Content-Type": "application/json"}


def headers_empty_role(user_id: str = OPERATOR_A_ID) -> Dict[str, str]:
    """X-User-Role present but the empty string."""
    return {"X-User-ID": user_id, "X-User-Role": "", "Content-Type": "application/json"}


def headers_unknown_role(
    user_id: str = ENGINEER_A_ID, role: str = "ReservoirEngineer"
) -> Dict[str, str]:
    """A syntactically fine role string that names no role in the contract."""
    return {"X-User-ID": user_id, "X-User-Role": role, "Content-Type": "application/json"}
