"""Pre-built role headers for every role in the PRD.

Opaque roles (PlatformAdmin, RateFilingAdmin, ClaimsAdjuster) may use the
shared constants anywhere. Entity-backed roles (HospitalStaff -> Hospital.id,
PetOwner -> Policy.id) MUST be built per instance with the make_*_headers
builders whenever the call is ownership-gated; the shared constants exist
only for non-ownership tests.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — canonical shared form.
    "platform_admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
    "rate_filing_admin_headers": build_user_headers("rateadmin-1", "RateFilingAdmin"),
    "adjuster_1_headers": build_user_headers("adj-1", "ClaimsAdjuster"),
    "adjuster_2_headers": build_user_headers("adj-2", "ClaimsAdjuster"),
    # Entity-backed roles — fallback only for non-ownership tests.
    "hospital_staff_headers": build_user_headers("test-hospital-staff-1", "HospitalStaff"),
    "pet_owner_headers": build_user_headers("test-pet-owner-1", "PetOwner"),
}


def make_hospital_staff_headers(hospital_id: str) -> dict:
    """HospitalStaff is entity-backed by Hospital: X-User-ID must equal the
    acting hospital's id for ownership-gated calls."""
    return build_user_headers(hospital_id, "HospitalStaff")


def make_pet_owner_headers(policy_id: str) -> dict:
    """PetOwner is entity-backed by Policy: X-User-ID must equal the owner's
    policy id for ownership-gated calls."""
    return build_user_headers(policy_id, "PetOwner")


def make_adjuster_headers(adjuster_user_id: str) -> dict:
    """ClaimsAdjuster is opaque, but appeal resolution records the adjudicator's
    X-User-ID for the segregation-of-duties check, so distinct adjuster ids
    matter. Build a header set for a specific adjuster id."""
    return build_user_headers(adjuster_user_id, "ClaimsAdjuster")
