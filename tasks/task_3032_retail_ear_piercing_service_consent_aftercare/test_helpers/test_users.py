"""Pre-built role headers for every role in the API.

``Piercer`` and ``Customer`` are entity-backed roles: their ``X-User-ID``
must equal the ``id`` of the acting row, so any ownership-gated call has to
use the per-instance builders below rather than the shared constants.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "intake_associate_headers": build_user_headers("test-intake-1", "IntakeAssociate"),
    "store_manager_headers": build_user_headers("test-manager-1", "StoreManager"),
    "compliance_officer_headers": build_user_headers("test-compliance-1", "ComplianceOfficer"),
    "sterilization_technician_headers": build_user_headers("test-sterilization-1", "SterilizationTechnician"),
    "anonymous_headers": build_user_headers("test-anonymous-1", "Anonymous"),
    "any_authenticated_headers": build_user_headers("test-reader-1", "AnyAuthenticated"),
    # entity-backed fallbacks — use only for calls that are not ownership-gated.
    "piercer_headers": build_user_headers("00000000-0000-4000-8000-000000000001", "Piercer"),
    "customer_headers": build_user_headers("00000000-0000-4000-8000-000000000002", "Customer"),
}


def make_piercer_headers(user_id: str) -> dict:
    """For the ``Piercer`` role (entity-backed). Pass the acting Piercer row's ``id``
    whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Piercer")


def make_customer_headers(user_id: str) -> dict:
    """For the ``Customer`` role (entity-backed). Pass the acting Customer row's ``id``
    whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Customer")