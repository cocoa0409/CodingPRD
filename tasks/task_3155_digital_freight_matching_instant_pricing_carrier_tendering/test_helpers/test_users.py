"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

SHIPPER_ROLE = "Shipper"
CARRIER_ROLE = "Carrier"
COMPLIANCE_REVIEWER_ROLE = "ComplianceReviewer"
CLAIMS_ADJUSTER_ROLE = "ClaimsAdjuster"
PLATFORM_ADMIN_ROLE = "PlatformAdmin"
ANONYMOUS_ROLE = "Anonymous"

# Shared constants: safe for the opaque roles, and for tests that do not
# exercise ownership.  Shipper and Carrier are entity_backed, so the shared
# constants below are fallbacks for non-ownership calls only.
TEST_USERS = {
    "shipper_headers": build_user_headers("test-shipper-1", SHIPPER_ROLE),
    "carrier_headers": build_user_headers("test-carrier-1", CARRIER_ROLE),
    "compliance_reviewer_headers": build_user_headers("test-compliance-1", COMPLIANCE_REVIEWER_ROLE),
    "claims_adjuster_headers": build_user_headers("test-adjuster-1", CLAIMS_ADJUSTER_ROLE),
    "platform_admin_headers": build_user_headers("test-admin-1", PLATFORM_ADMIN_ROLE),
    "anonymous_headers": build_user_headers("anon-opaque-value", ANONYMOUS_ROLE),
}


def make_shipper_headers(shipper_id: str) -> dict:
    """For the Shipper role (entity_backed:Shipper).  Pass the actual Shipper.id
    as user_id whenever the call is ownership-gated."""
    return build_user_headers(shipper_id, SHIPPER_ROLE)


def make_carrier_headers(carrier_id: str) -> dict:
    """For the Carrier role (entity_backed:Carrier).  Pass the actual Carrier.id
    as user_id whenever the call is ownership-gated."""
    return build_user_headers(carrier_id, CARRIER_ROLE)


def make_compliance_reviewer_headers(operator_id="test-compliance-1") -> dict:
    return build_user_headers(operator_id, COMPLIANCE_REVIEWER_ROLE)


def make_claims_adjuster_headers(operator_id="test-adjuster-1") -> dict:
    return build_user_headers(operator_id, CLAIMS_ADJUSTER_ROLE)


def make_platform_admin_headers(operator_id="test-admin-1") -> dict:
    return build_user_headers(operator_id, PLATFORM_ADMIN_ROLE)


def make_anonymous_headers(opaque_id="anon-opaque-value") -> dict:
    return build_user_headers(opaque_id, ANONYMOUS_ROLE)


def headers_for_role(role: str, user_id: str = None) -> dict:
    """Generic builder for parametrized unauthorized-role checks."""
    if user_id is None:
        user_id = f"test-{role.lower()}-1"
    return build_user_headers(user_id, role)