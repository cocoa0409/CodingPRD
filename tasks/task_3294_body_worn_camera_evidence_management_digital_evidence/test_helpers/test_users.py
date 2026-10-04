"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise
# ownership. For the entity-backed roles (Officer, Supervisor) the shared
# constant is a fallback only; ownership-gated calls MUST use the per-instance
# builders below with the real Officer id.
TEST_USERS = {
    "agency_admin_headers": build_user_headers("test-admin-1", "AgencyAdmin"),
    "device_coordinator_headers": build_user_headers("test-dc-1", "DeviceCoordinator"),
    "redaction_technician_headers": build_user_headers("tech-1", "RedactionTechnician"),
    "records_officer_headers": build_user_headers("ro-1", "RecordsOfficer"),
    "prosecutor_headers": build_user_headers("test-pros-1", "Prosecutor"),
    "defense_counsel_headers": build_user_headers("test-def-1", "DefenseCounsel"),
    # entity-backed fallbacks (non-ownership tests only)
    "officer_headers": build_user_headers("test-officer-1", "Officer"),
    "supervisor_headers": build_user_headers("test-supervisor-1", "Supervisor"),
}


def make_officer_headers(user_id: str) -> dict:
    """For Officer (entity-backed). Pass the actual Officer.id as user_id
    whenever the call is ownership-gated (upload/reverify/dock/undock/etc.)."""
    return build_user_headers(user_id, "Officer")


def make_supervisor_headers(user_id: str) -> dict:
    """For Supervisor (entity-backed). Pass the id of an officer ranked
    SERGEANT or LIEUTENANT as user_id."""
    return build_user_headers(user_id, "Supervisor")


def make_records_officer_headers(user_id: str) -> dict:
    """For RecordsOfficer (opaque). Use a distinct user_id when segregation of
    duties against a specific technician id is under test."""
    return build_user_headers(user_id, "RecordsOfficer")


def make_redaction_technician_headers(user_id: str) -> dict:
    """For RedactionTechnician (opaque). The user_id is recorded as the
    submitter identity for segregation-of-duties checks."""
    return build_user_headers(user_id, "RedactionTechnician")


def make_prosecutor_headers(user_id: str = "test-pros-1") -> dict:
    return build_user_headers(user_id, "Prosecutor")


def make_defense_counsel_headers(user_id: str = "test-def-1") -> dict:
    return build_user_headers(user_id, "DefenseCounsel")
