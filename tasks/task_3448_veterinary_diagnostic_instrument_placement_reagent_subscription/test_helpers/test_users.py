"""Pre-built role headers for the five PRD roles (PRD §2.1).

Identity model (PRD §2.1):
- ``ClinicManager`` is ENTITY-BACKED: ``X-User-ID`` must be the ``id`` of the
  acting Clinic. Ownership checks compare the resource's ``clinic_id``
  against ``X-User-ID`` and reject mismatches with
  ``ERR_CLINIC_OWNERSHIP_MISMATCH`` (403). Any ownership-gated call MUST
  therefore use ``make_clinic_manager_headers(clinic["id"])`` — never the
  shared ``TEST_USERS["clinic_manager_headers"]`` constant, whose id matches
  no real clinic and would be rejected everywhere.
- The other four roles are OPAQUE: their ``X-User-ID`` is never compared to
  any resource id, so the shared constants in ``TEST_USERS`` are canonical.

``TEST_USERS`` entries remain useful for tests whose outcome does not depend
on owning the subject resource (400-on-bad-payload, 404-on-missing-resource,
RBAC rejection tests) and for deliberately mismatched-ownership tests.
"""
from prd_bench_local_runner.testing import build_user_headers

__all__ = [
    "TEST_USERS",
    "make_platform_admin_headers", "make_finance_reviewer_headers",
    "make_clinic_manager_headers", "make_field_service_engineer_headers",
    "make_laboratory_technician_headers",
]

# Shared constants — canonical for the four opaque roles; the ClinicManager
# entry is a FALLBACK for non-ownership tests only (see module docstring).
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "finance_reviewer_headers": build_user_headers("test-finance-reviewer-1", "FinanceReviewer"),
    "clinic_manager_headers": build_user_headers("test-clinic-manager-1", "ClinicManager"),
    "field_service_engineer_headers": build_user_headers("test-field-service-engineer-1", "FieldServiceEngineer"),
    "laboratory_technician_headers": build_user_headers("test-laboratory-technician-1", "LaboratoryTechnician"),
}


def make_platform_admin_headers(user_id: str = "test-platform-admin-1") -> dict:
    """PlatformAdmin (opaque identity): clock, GPAs, clinics, activation, closes."""
    return build_user_headers(user_id, "PlatformAdmin")


def make_finance_reviewer_headers(user_id: str = "test-finance-reviewer-1") -> dict:
    """FinanceReviewer (opaque): approve, resolve-renegotiation, record-payment."""
    return build_user_headers(user_id, "FinanceReviewer")


def make_clinic_manager_headers(user_id: str) -> dict:
    """ClinicManager (entity_backed: Clinic). Pass the ACTUAL clinic id whenever
    the call is ownership-gated — drafting agreements, renegotiation requests,
    reagent orders, test orders, and the owning clinic's caseload updates all
    compare X-User-ID to the resource's clinic_id (PRD §2.1, §2.9 tier 3)."""
    return build_user_headers(user_id, "ClinicManager")


def make_field_service_engineer_headers(user_id: str = "test-field-service-engineer-1") -> dict:
    """FieldServiceEngineer (opaque): analyzers, service cases."""
    return build_user_headers(user_id, "FieldServiceEngineer")


def make_laboratory_technician_headers(user_id: str = "test-laboratory-technician-1") -> dict:
    """LaboratoryTechnician (opaque): send-out RECEIVE / RECORD_RESULT."""
    return build_user_headers(user_id, "LaboratoryTechnician")
