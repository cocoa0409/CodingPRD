"""Pre-built role headers for every role in the PRD.

No role in this program is backed by a persisted entity: X-User-ID is an opaque
operator identifier for every role, so no per-instance builder is required and
ownership is never inferred from identity.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "protocol_coordinator_headers": build_user_headers("test-protocol-coordinator-1", "ProtocolCoordinator"),
    "irb_reviewer_headers": build_user_headers("test-irb-reviewer-1", "IRBReviewer"),
    "intake_coordinator_headers": build_user_headers("test-intake-coordinator-1", "IntakeCoordinator"),
    "housing_coordinator_headers": build_user_headers("test-housing-coordinator-1", "HousingCoordinator"),
    "patient_support_officer_headers": build_user_headers("test-patient-support-officer-1", "PatientSupportOfficer"),
    "affiliate_clinic_coordinator_headers": build_user_headers("test-affiliate-clinic-coordinator-1", "AffiliateClinicCoordinator"),
    "survivorship_coordinator_headers": build_user_headers("test-survivorship-coordinator-1", "SurvivorshipCoordinator"),
    "any_headers": build_user_headers("test-any-1", "Any"),
}