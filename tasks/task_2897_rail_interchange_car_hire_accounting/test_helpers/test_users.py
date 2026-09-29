"""Role header builders (PRD §2.1).

``X-User-Role`` names the caller's function and ``X-User-ID`` identifies the
acting railroad.  ``InterchangeClerk``, ``CarHireAccountant``,
``RepairBillingAgent`` and ``FleetOwner`` are entity-backed: their
``X-User-ID`` must be the ``id`` of a registered ``Railroad``, so those headers
can only be built once the railroad rows exist.  ``ClearinghouseAdmin`` is
opaque and is not compared against any entity id, so it works with no
``X-User-ID`` header at all.

Every distinct railroad therefore gets a DISTINCT ``X-User-ID`` -- never a
shared constant -- because the segregation-of-duties rules of §3 compare the
acting id against the resource's railroad-valued fields.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

ROLE_CLEARINGHOUSE_ADMIN = "ClearinghouseAdmin"
ROLE_INTERCHANGE_CLERK = "InterchangeClerk"
ROLE_CAR_HIRE_ACCOUNTANT = "CarHireAccountant"
ROLE_REPAIR_BILLING_AGENT = "RepairBillingAgent"
ROLE_FLEET_OWNER = "FleetOwner"

ALL_ROLES = (
    ROLE_CLEARINGHOUSE_ADMIN,
    ROLE_INTERCHANGE_CLERK,
    ROLE_CAR_HIRE_ACCOUNTANT,
    ROLE_REPAIR_BILLING_AGENT,
    ROLE_FLEET_OWNER,
)

ENTITY_BACKED_ROLES = (
    ROLE_INTERCHANGE_CLERK,
    ROLE_CAR_HIRE_ACCOUNTANT,
    ROLE_REPAIR_BILLING_AGENT,
    ROLE_FLEET_OWNER,
)

#: The opaque operator identifier used for the clearinghouse when a value is
#: supplied at all.  It is not tied to any persisted entity.
CLEARINGHOUSE_OPERATOR_ID = "clearinghouse-operator-1"

#: Shared, role-keyed header dicts for the opaque role.  The four entity-backed
#: roles cannot appear here because their id is only known at runtime.
TEST_USERS: Dict[str, Dict[str, str]] = {
    ROLE_CLEARINGHOUSE_ADMIN: {
        "X-User-Role": ROLE_CLEARINGHOUSE_ADMIN,
        "X-User-ID": CLEARINGHOUSE_OPERATOR_ID,
        "Content-Type": "application/json",
    },
}


def admin_headers() -> Dict[str, str]:
    """Clearinghouse headers carrying an opaque operator id."""
    return dict(TEST_USERS[ROLE_CLEARINGHOUSE_ADMIN])


def admin_headers_without_user_id() -> Dict[str, str]:
    """Clearinghouse headers with no ``X-User-ID`` header at all."""
    return {
        "X-User-Role": ROLE_CLEARINGHOUSE_ADMIN,
        "Content-Type": "application/json",
    }


def make_headers(role: str, railroad_id: str) -> Dict[str, str]:
    """Headers for ``role`` acting as the railroad ``railroad_id``."""
    return build_user_headers(railroad_id, role)


def make_interchange_clerk_headers(railroad_id: str) -> Dict[str, str]:
    """Interchange clerk acting for the railroad ``railroad_id``."""
    return build_user_headers(railroad_id, ROLE_INTERCHANGE_CLERK)


def make_car_hire_accountant_headers(railroad_id: str) -> Dict[str, str]:
    """Car hire accountant acting for the railroad ``railroad_id``."""
    return build_user_headers(railroad_id, ROLE_CAR_HIRE_ACCOUNTANT)


def make_repair_billing_agent_headers(railroad_id: str) -> Dict[str, str]:
    """Repair billing agent acting for the railroad ``railroad_id``."""
    return build_user_headers(railroad_id, ROLE_REPAIR_BILLING_AGENT)


def make_fleet_owner_headers(railroad_id: str) -> Dict[str, str]:
    """Fleet owner acting for the railroad ``railroad_id``."""
    return build_user_headers(railroad_id, ROLE_FLEET_OWNER)


def headers_missing_role() -> Dict[str, str]:
    """Headers with no ``X-User-Role`` key at all."""
    return {"Content-Type": "application/json"}


def headers_with_empty_role(railroad_id: str = "") -> Dict[str, str]:
    """Headers whose ``X-User-Role`` is the empty string (never whitespace)."""
    headers = {"X-User-Role": "", "Content-Type": "application/json"}
    if railroad_id:
        headers["X-User-ID"] = railroad_id
    return headers


def headers_with_unknown_role(railroad_id: str = "") -> Dict[str, str]:
    """Headers naming a role outside the five declared roles."""
    headers = {"X-User-Role": "YardMaster", "Content-Type": "application/json"}
    if railroad_id:
        headers["X-User-ID"] = railroad_id
    return headers


def headers_missing_user_id(role: str) -> Dict[str, str]:
    """Entity-backed role headers with the ``X-User-ID`` header omitted."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_with_unknown_railroad(role: str, railroad_id: str) -> Dict[str, str]:
    """Entity-backed role headers naming a railroad id that is not registered."""
    return build_user_headers(railroad_id, role)
