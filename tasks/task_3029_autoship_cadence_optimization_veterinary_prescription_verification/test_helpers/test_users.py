"""Pre-built role headers for every role declared in the PRD (PRD §2.1).

`Customer`'s X-User-ID is the id of an acting Pet and `ClinicContact`'s is the id
of an acting Veterinarian; both roles therefore have per-instance builders and the
shared constants are fallbacks for calls that do not exercise ownership.
The remaining five roles carry opaque operator identifiers.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # entity_backed:Pet — shared constant is a fallback for non-ownership calls only.
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
    # entity_backed:Veterinarian — fallback for non-ownership calls only.
    "clinic_contact_headers": build_user_headers("test-clinic-contact-1", "ClinicContact"),
    # opaque operator identifiers.
    "pharmacy_technician_headers": build_user_headers("test-pharmacy-tech-1", "PharmacyTechnician"),
    "pharmacy_manager_headers": build_user_headers("test-pharmacy-manager-1", "PharmacyManager"),
    "customer_service_headers": build_user_headers("test-customer-service-1", "CustomerService"),
    "compliance_officer_headers": build_user_headers("test-compliance-officer-1", "ComplianceOfficer"),
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
}

# Header with no identity at all, for header-presence checks.
ANONYMOUS_HEADERS = {"Content-Type": "application/json"}


def make_customer_headers(pet_id: str) -> dict:
    """For Customer (entity_backed:Pet). Pass the acting Pet's id whenever the call
    is ownership-gated so the resource's foreign key matches X-User-ID."""
    return build_user_headers(pet_id, "Customer")


def make_clinic_contact_headers(vet_id: str) -> dict:
    """For ClinicContact (entity_backed:Veterinarian). Pass the acting Veterinarian's
    id whenever the call is ownership-gated."""
    return build_user_headers(vet_id, "ClinicContact")