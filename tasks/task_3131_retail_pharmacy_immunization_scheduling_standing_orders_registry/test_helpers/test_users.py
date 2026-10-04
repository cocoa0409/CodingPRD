"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
TEST_USERS = {
    "store_manager_headers": build_user_headers("user-mgr-1", "StoreManager"),
    "pharmacist_headers": build_user_headers("user-pharm-1", "Pharmacist"),
    "technician_headers": build_user_headers("user-tech-1", "PharmacyTechnician"),
    "immunizer_headers": build_user_headers("user-imm-1", "Immunizer"),
    "observer_headers": build_user_headers("user-obs-1", "ObservationMonitor"),
    "compliance_headers": build_user_headers("user-co-1", "ComplianceOfficer"),
    # Patient role is entity_backed — the shared constant is a fallback for
    # non-ownership tests only (e.g., 400-on-bad-payload, 404-on-missing).
    "patient_headers": build_user_headers("test-patient-1", "Patient"),
}


def make_patient_headers(user_id: str) -> dict:
    """For Patient (entity_backed:Patient). Pass the actual Patient.id as user_id
    whenever the call is ownership-gated (booking/cancel/quote)."""
    return build_user_headers(user_id, "Patient")


def make_store_manager_headers(user_id: str = "user-mgr-1") -> dict:
    return build_user_headers(user_id, "StoreManager")


def make_pharmacist_headers(user_id: str = "user-pharm-1") -> dict:
    return build_user_headers(user_id, "Pharmacist")


def make_technician_headers(user_id: str = "user-tech-1") -> dict:
    return build_user_headers(user_id, "PharmacyTechnician")


def make_immunizer_headers(user_id: str = "user-imm-1") -> dict:
    return build_user_headers(user_id, "Immunizer")


def make_observer_headers(user_id: str = "user-obs-1") -> dict:
    return build_user_headers(user_id, "ObservationMonitor")


def make_compliance_headers(user_id: str = "user-co-1") -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")
