"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership. Entity-backed roles use these only where ownership is not checked.
TEST_USERS = {
    "intake_headers": build_user_headers("test-intake-1", "IntakeCoordinator"),
    "lab_liaison_headers": build_user_headers("test-liaison-1", "LabLiaison"),
    "supervisor_headers": build_user_headers("test-supervisor-1", "CenterSupervisor"),
    # entity_backed:Phlebotomist — fallback for calls that are not ownership-gated.
    "phlebotomist_headers": build_user_headers("test-phlebotomist-1", "Phlebotomist"),
    # entity_backed:Patient — fallback for calls that are not ownership-gated.
    "patient_headers": build_user_headers("test-patient-1", "Patient"),
    # entity_backed:ServiceCenter — fallback for calls that are not ownership-gated.
    "lab_system_headers": build_user_headers("test-lab-system-1", "LabSystem"),
}


# ─── Per-instance builders — required for every entity-backed role ────────────

def make_phlebotomist_headers(phlebotomist_id: str) -> dict:
    """For Phlebotomist (entity_backed:Phlebotomist). Pass the actual
    Phlebotomist.id whenever the call is ownership-gated."""
    return build_user_headers(phlebotomist_id, "Phlebotomist")


def make_patient_headers(patient_id: str) -> dict:
    """For Patient (entity_backed:Patient). Pass the actual Patient.id whenever
    the call is ownership-gated (the server compares it to the linked order's
    patient_id)."""
    return build_user_headers(patient_id, "Patient")


def make_lab_system_headers(service_center_id: str) -> dict:
    """For LabSystem (entity_backed:ServiceCenter). Pass the actual
    ServiceCenter.id whenever the call is ownership-gated."""
    return build_user_headers(service_center_id, "LabSystem")


# A role the server does not recognize, used for the missing-auth probe.
UNKNOWN_ROLE_HEADERS = build_user_headers("test-unknown-1", "NotARole")
NO_AUTH_HEADERS: dict = {}