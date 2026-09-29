"""Role headers.

PRD 2.1 splits the seven roles into two groups. `PlatformAdmin`,
`ValetOpsManager`, `ComplianceOfficer` and `BillingAnalyst` are opaque: their
`X-User-ID` resolves to no stored row, so any stable string works and the
constants below are reused everywhere. `PropertyManager`, `Valet` and
`Resident` are entity-backed: the `X-User-ID` must equal the id of the
Property / ValetContractor / Resident the caller acts as, otherwise the
request is rejected with ERR_NOT_RESOURCE_OWNER. Those three therefore have
builders that take the entity id created by the test.
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import OPERATORS
from .types import UserRole

# ------------------------------------------------------------------ opaque
PLATFORM_ADMIN = build_user_headers(
    OPERATORS["PLATFORM_ADMIN"], UserRole.PLATFORM_ADMIN.value
)
VALET_OPS_MANAGER = build_user_headers(
    OPERATORS["VALET_OPS_MANAGER"], UserRole.VALET_OPS_MANAGER.value
)
COMPLIANCE_SCREENER = build_user_headers(
    OPERATORS["COMPLIANCE_SCREENER"], UserRole.COMPLIANCE_OFFICER.value
)
COMPLIANCE_AUDITOR = build_user_headers(
    OPERATORS["COMPLIANCE_AUDITOR"], UserRole.COMPLIANCE_OFFICER.value
)
ANALYST_DRAFTER = build_user_headers(
    OPERATORS["ANALYST_DRAFTER"], UserRole.BILLING_ANALYST.value
)
ANALYST_ISSUER = build_user_headers(
    OPERATORS["ANALYST_ISSUER"], UserRole.BILLING_ANALYST.value
)

TEST_USERS = {
    "PLATFORM_ADMIN": PLATFORM_ADMIN,
    "VALET_OPS_MANAGER": VALET_OPS_MANAGER,
    "COMPLIANCE_SCREENER": COMPLIANCE_SCREENER,
    "COMPLIANCE_AUDITOR": COMPLIANCE_AUDITOR,
    "ANALYST_DRAFTER": ANALYST_DRAFTER,
    "ANALYST_ISSUER": ANALYST_ISSUER,
}


# ----------------------------------------------------------- entity backed
def make_property_manager_headers(property_id):
    """Headers for the PropertyManager of `property_id`."""
    return build_user_headers(property_id, UserRole.PROPERTY_MANAGER.value)


def make_valet_headers(contractor_id):
    """Headers for the Valet whose ValetContractor row is `contractor_id`."""
    return build_user_headers(contractor_id, UserRole.VALET.value)


def make_resident_headers(resident_id):
    """Headers for the Resident whose row is `resident_id`."""
    return build_user_headers(resident_id, UserRole.RESIDENT.value)


def make_headers(user_id, role):
    """Headers for an arbitrary user id / role pair."""
    return build_user_headers(user_id, role)


def make_missing_role_headers(user_id="anonymous-1"):
    """Headers carrying an X-User-ID but a blank X-User-Role.

    The blank value must be a real empty string, not whitespace, so the HTTP
    layer actually transmits the header and the API is the component that
    judges it.
    """
    headers = build_user_headers(user_id, "")
    headers["X-User-Role"] = ""
    return headers


def make_undeclared_role_headers(user_id="stranger-1", role="TrashInspector"):
    """Headers naming a role the PRD does not declare."""
    return build_user_headers(user_id, role)
