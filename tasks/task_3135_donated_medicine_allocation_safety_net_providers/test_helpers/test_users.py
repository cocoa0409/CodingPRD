"""Caller identities for the eight declared roles.

Seven roles are opaque: their ``X-User-ID`` is never matched against a stored
entity, so a stable identifier is enough. ``SiteCoordinator`` is entity-backed
by ``RecipientSite``: ownership checks compare the resource's site foreign key
(or, for allocation requests, ``requested_by_user_id``) to ``X-User-ID``, so
ownership-gated calls must use :func:`make_site_coordinator_headers` with the
actual site id.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

ROLE_PLATFORM_ADMIN = "PlatformAdmin"
ROLE_QA_PHARMACIST = "QAPharmacist"
ROLE_COMPLIANCE_OFFICER = "ComplianceOfficer"
ROLE_ALLOCATION_OFFICER = "AllocationOfficer"
ROLE_LOGISTICS_COORDINATOR = "LogisticsCoordinator"
ROLE_SITE_COORDINATOR = "SiteCoordinator"
ROLE_EMERGENCY_MANAGER = "EmergencyManager"
ROLE_DONOR_REPORTING_OFFICER = "DonorReportingOfficer"

# Stable opaque identifiers for the non-entity-backed roles. The primary
# AllocationOfficer and ComplianceOfficer ids double as the "drafter" and
# "reviewer" identities where the PRD's segregation-of-duties rules compare
# user ids; ALTERNATE ids exist for the "a different officer" scenarios.
TEST_USERS: Dict[str, Dict[str, str]] = {
    "platform_admin": {"id": "11111111-1111-4111-8111-111111111111", "role": ROLE_PLATFORM_ADMIN},
    "qa_pharmacist": {"id": "22222222-2222-4222-8222-222222222222", "role": ROLE_QA_PHARMACIST},
    "compliance_officer": {"id": "33333333-3333-4333-8333-333333333333", "role": ROLE_COMPLIANCE_OFFICER},
    "allocation_officer": {"id": "44444444-4444-4444-8444-444444444444", "role": ROLE_ALLOCATION_OFFICER},
    "logistics_coordinator": {"id": "55555555-5555-4555-8555-555555555555", "role": ROLE_LOGISTICS_COORDINATOR},
    "emergency_manager": {"id": "66666666-6666-4666-8666-666666666666", "role": ROLE_EMERGENCY_MANAGER},
    "donor_reporting_officer": {"id": "77777777-7777-4777-8777-777777777777", "role": ROLE_DONOR_REPORTING_OFFICER},
}

PLATFORM_ADMIN_HEADERS = build_user_headers(TEST_USERS["platform_admin"]["id"], ROLE_PLATFORM_ADMIN)
QA_PHARMACIST_HEADERS = build_user_headers(TEST_USERS["qa_pharmacist"]["id"], ROLE_QA_PHARMACIST)
COMPLIANCE_OFFICER_HEADERS = build_user_headers(
    TEST_USERS["compliance_officer"]["id"], ROLE_COMPLIANCE_OFFICER
)
ALLOCATION_OFFICER_HEADERS = build_user_headers(
    TEST_USERS["allocation_officer"]["id"], ROLE_ALLOCATION_OFFICER
)
LOGISTICS_COORDINATOR_HEADERS = build_user_headers(
    TEST_USERS["logistics_coordinator"]["id"], ROLE_LOGISTICS_COORDINATOR
)
EMERGENCY_MANAGER_HEADERS = build_user_headers(
    TEST_USERS["emergency_manager"]["id"], ROLE_EMERGENCY_MANAGER
)
DONOR_REPORTING_OFFICER_HEADERS = build_user_headers(
    TEST_USERS["donor_reporting_officer"]["id"], ROLE_DONOR_REPORTING_OFFICER
)


def make_platform_admin_headers(user_id: str = TEST_USERS["platform_admin"]["id"]) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_PLATFORM_ADMIN)


def make_qa_pharmacist_headers(user_id: str = TEST_USERS["qa_pharmacist"]["id"]) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_QA_PHARMACIST)


def make_compliance_officer_headers(user_id: str = TEST_USERS["compliance_officer"]["id"]) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_COMPLIANCE_OFFICER)


def make_allocation_officer_headers(user_id: str = TEST_USERS["allocation_officer"]["id"]) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_ALLOCATION_OFFICER)


def make_logistics_coordinator_headers(user_id: str = TEST_USERS["logistics_coordinator"]["id"]) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_LOGISTICS_COORDINATOR)


def make_emergency_manager_headers(user_id: str = TEST_USERS["emergency_manager"]["id"]) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_EMERGENCY_MANAGER)


def make_donor_reporting_officer_headers(user_id: str = TEST_USERS["donor_reporting_officer"]["id"]) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_DONOR_REPORTING_OFFICER)


def make_site_coordinator_headers(site_id: str) -> Dict[str, str]:
    """Headers for a SiteCoordinator acting for the RecipientSite with this id.

    Ownership-gated calls (request cancel, delivery confirmation, report
    create/submit) MUST be made with these headers carrying the real site id;
    a fixed opaque id would never match the resource's site foreign key.
    """
    return build_user_headers(site_id, ROLE_SITE_COORDINATOR)
