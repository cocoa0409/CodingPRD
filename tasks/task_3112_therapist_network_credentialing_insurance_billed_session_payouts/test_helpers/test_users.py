"""Pre-built role headers for every role the PRD declares.

`OpsAdmin`, `ComplianceOfficer`, `PayrollService` and `Anonymous` are opaque
identities, so a shared constant is their canonical form. `Clinician` and
`Patient` are entity-backed: their `X-User-ID` must equal a real entity's `id`,
so any ownership-gated call must use the per-instance builders below.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "ops_admin_headers": build_user_headers("test-ops-admin-1", "OpsAdmin"),
    "compliance_officer_headers": build_user_headers("test-compliance-1", "ComplianceOfficer"),
    "payroll_service_headers": build_user_headers("test-payroll-1", "PayrollService"),
    # Opaque-but-unauthenticated caller: no usable role is declared, which is
    # exactly what the authentication probe needs.
    "anonymous_headers": build_user_headers("test-anon-1", "Anonymous"),
    # entity_backed roles — these shared constants are fallbacks only; use the
    # builders below whenever the call is ownership-gated.
    "clinician_headers": build_user_headers("test-clinician-1", "Clinician"),
    "patient_headers": build_user_headers("test-patient-1", "Patient"),
}

# Header sets used to prove the authentication layer, not the authorization one.
MISSING_ROLE_HEADERS = {"X-User-ID": "test-missing-role-1", "Content-Type": "application/json"}
MISSING_USER_ID_HEADERS = {"X-User-Role": "OpsAdmin", "Content-Type": "application/json"}
UNDECLARED_ROLE_HEADERS = {
    "X-User-ID": "test-undeclared-1",
    "X-User-Role": "TherapistSupervisor",
    "Content-Type": "application/json",
}


def make_clinician_headers(clinician_id: str) -> dict:
    """For the Clinician role (entity_backed:Clinician). Pass the actual
    Clinician.id so ownership checks resolve."""
    return build_user_headers(clinician_id, "Clinician")


def make_patient_headers(patient_id: str) -> dict:
    """For the Patient role (entity_backed:PatientClient). Pass the actual
    PatientClient.id so the patient's own-resource scope resolves."""
    return build_user_headers(patient_id, "Patient")