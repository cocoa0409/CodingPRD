"""Pre-built role headers for every role in the PRD.

Entity-backed roles (Prescriber, Patient) must be built per-instance via the
make_*_headers builders with the actual entity id; the shared constants for
those roles are fallbacks for non-ownership tests only.
"""
from prd_bench_local_runner.testing import build_user_headers

from .constants import USER_IDS

TEST_USERS = {
    "platform_admin_headers": build_user_headers(USER_IDS["PLATFORM_ADMIN"], "PlatformAdmin"),
    "coverage_reviewer_headers": build_user_headers(USER_IDS["COVERAGE_REVIEWER"], "CoverageReviewer"),
    "fulfillment_agent_headers": build_user_headers(USER_IDS["FULFILLMENT_AGENT"], "FulfillmentAgent"),
    "billing_agent_headers": build_user_headers(USER_IDS["BILLING_AGENT"], "BillingAgent"),
    "warranty_reviewer_headers": build_user_headers(USER_IDS["WARRANTY_REVIEWER"], "WarrantyReviewer"),
    "quality_engineer_headers": build_user_headers(USER_IDS["QUALITY_ENGINEER"], "QualityEngineer"),
    "patient_support_agent_headers": build_user_headers(USER_IDS["PATIENT_SUPPORT_AGENT"], "PatientSupportAgent"),
    # entity_backed fallbacks — only for tests that do not exercise ownership.
    "prescriber_headers": build_user_headers("test-prescriber-fallback", "Prescriber"),
    "patient_headers": build_user_headers("test-patient-fallback", "Patient"),
}


def make_prescriber_headers(prescriber_id: str) -> dict:
    """Prescriber is entity-backed: X-User-ID must equal the acting
    prescriber's id for ownership-gated calls (e.g. prescription cancel)."""
    return build_user_headers(prescriber_id, "Prescriber")


def make_patient_headers(patient_id: str) -> dict:
    """Patient is entity-backed: X-User-ID must equal the acting patient's id
    for ownership-gated calls (bindings, early-failure reports, claims)."""
    return build_user_headers(patient_id, "Patient")
