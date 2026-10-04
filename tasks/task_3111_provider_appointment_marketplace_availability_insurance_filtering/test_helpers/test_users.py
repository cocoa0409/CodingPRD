"""Pre-built role headers for every role in the PRD.

Shared constants are safe for opaque roles (OpsAdmin, Anonymous) and for tests
that never exercise ownership gating. Entity-backed roles (Patient, Provider,
PracticeStaff) MUST use the per-instance builders with the actual entity id
whenever the call is ownership-gated — otherwise every ownership check rejects
the request because the string X-User-ID never matches a real entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles: shared constants are the canonical form.
    "ops_admin_headers": build_user_headers("test-ops-admin-1", "OpsAdmin"),
    "anonymous_headers": build_user_headers("test-anon-1", "Anonymous"),
    # Entity-backed roles: shared constants are a fallback ONLY for tests whose
    # outcome does not depend on ownership (e.g. 400/404 checks).
    "patient_headers": build_user_headers("test-patient-1", "Patient"),
    "provider_headers": build_user_headers("test-provider-1", "Provider"),
    "practice_staff_headers": build_user_headers("test-practice-1", "PracticeStaff"),
}


def make_patient_headers(patient_id: str) -> dict:
    """For Patient (entity_backed:Patient). Pass the actual Patient.id."""
    return build_user_headers(patient_id, "Patient")


def make_provider_headers(provider_id: str) -> dict:
    """For Provider (entity_backed:Provider). Pass the actual Provider.id."""
    return build_user_headers(provider_id, "Provider")


def make_practice_staff_headers(practice_id: str) -> dict:
    """For PracticeStaff (entity_backed:Practice). Pass the actual Practice.id."""
    return build_user_headers(practice_id, "PracticeStaff")


def make_ops_admin_headers(user_id: str = "test-ops-admin-1") -> dict:
    """For OpsAdmin (opaque)."""
    return build_user_headers(user_id, "OpsAdmin")


def make_anonymous_headers(user_id: str = "test-anon-1") -> dict:
    """For Anonymous (opaque)."""
    return build_user_headers(user_id, "Anonymous")
