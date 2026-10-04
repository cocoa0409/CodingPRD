"""Pre-built role headers for every role the PRD declares.

The PRD states that ``X-User-ID`` is an opaque operator identifier for every
role — including ``PlatformAdmin``, ``StoreManager`` and the rest — and that no
ownership comparison is ever performed against it. The shared constants below
are therefore safe for every call, and there are no entity-backed roles needing
per-instance builders.
"""

from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "store_manager_headers": build_user_headers("test-store-manager-1", "StoreManager"),
    "veterinary_staff_headers": build_user_headers("test-vet-staff-1", "VeterinaryStaff"),
    "grooming_staff_headers": build_user_headers("test-grooming-staff-1", "GroomingStaff"),
    "vaccination_staff_headers": build_user_headers("test-vaccination-staff-1", "VaccinationStaff"),
    "compliance_officer_headers": build_user_headers("test-compliance-officer-1", "ComplianceOfficer"),
    "pharmacy_staff_headers": build_user_headers("test-pharmacy-staff-1", "PharmacyStaff"),
    "training_staff_headers": build_user_headers("test-training-staff-1", "TrainingStaff"),
    "any_headers": build_user_headers("test-any-1", "Any"),
}

# A header set naming a role outside the declared enumeration, and a header set
# with the role omitted entirely — used by the §2.1 framing claims.
UNDECLARED_ROLE_HEADERS = {
    "X-User-ID": "test-outsider-1",
    "X-User-Role": "RegionalDirector",
    "Content-Type": "application/json",
}
MISSING_ROLE_HEADERS = {
    "X-User-ID": "test-outsider-2",
    "Content-Type": "application/json",
}
MISSING_USER_ID_HEADERS = {
    "X-User-Role": "PlatformAdmin",
    "Content-Type": "application/json",
}