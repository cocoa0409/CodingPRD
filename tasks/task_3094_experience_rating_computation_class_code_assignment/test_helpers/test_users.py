"""Pre-built role headers for every role named in the PRD (section 2.1).

Opaque roles may share a constant header set. Entity-backed roles
(CarrierDataReporter, VoluntaryCarrierRepresentative on Carrier;
EmployerRepresentative on Employer) must be built per instance with the
acting entity's id whenever a call is ownership-gated.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants - safe for opaque roles, and for entity-backed roles in
# tests that do not exercise ownership.
TEST_USERS = {
    "bureau_admin_headers": build_user_headers("test-bureau-admin-1", "BureauAdmin"),
    "carrier_data_reporter_headers": build_user_headers(
        "test-carrier-reporter-1", "CarrierDataReporter"
    ),
    "bureau_analyst_headers": build_user_headers("test-bureau-analyst-1", "BureauAnalyst"),
    "inspector_headers": build_user_headers("test-inspector-1", "Inspector"),
    "employer_representative_headers": build_user_headers(
        "test-employer-rep-1", "EmployerRepresentative"
    ),
    "pool_administrator_headers": build_user_headers(
        "test-pool-admin-1", "PoolAdministrator"
    ),
    "voluntary_carrier_representative_headers": build_user_headers(
        "test-voluntary-carrier-rep-1", "VoluntaryCarrierRepresentative"
    ),
    "underwriter_headers": build_user_headers("test-underwriter-1", "Underwriter"),
    "underwriter_other_headers": build_user_headers("test-underwriter-2", "Underwriter"),
}


def make_carrier_data_reporter_headers(carrier_id: str) -> dict:
    """CarrierDataReporter is backed by a Carrier; pass the carrier's id."""
    return build_user_headers(carrier_id, "CarrierDataReporter")


def make_voluntary_carrier_representative_headers(carrier_id: str) -> dict:
    """VoluntaryCarrierRepresentative is backed by a Carrier; pass its id."""
    return build_user_headers(carrier_id, "VoluntaryCarrierRepresentative")


def make_employer_representative_headers(employer_id: str) -> dict:
    """EmployerRepresentative is backed by an Employer; pass the employer's id."""
    return build_user_headers(employer_id, "EmployerRepresentative")


def make_underwriter_headers(user_id: str) -> dict:
    """Underwriter is opaque but segregated: pick a distinct user id per actor."""
    return build_user_headers(user_id, "Underwriter")
