"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    ApplicationStatus,
    BackgroundStatus,
    CertCode,
    CredentialStatus,
    DocType,
    DocumentStatus,
    EmployerStatus,
    FeeModel,
    InterviewStatus,
    InvoiceKind,
    InvoiceStatus,
    LicenseVerificationStatus,
    NurseStatus,
    OfferStatus,
    PlacementStatus,
    RequisitionStatus,
    ScreeningOverallStatus,
    Shift,
    Specialty,
    SubscriptionTier,
)


def _assert_common_fields(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be an integer >= 1"
    )


def assert_nurse(data: dict):
    _assert_common_fields(data, "Nurse")
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    assert isinstance(data.get("email"), str) and data["email"]
    assert isinstance(data.get("home_state"), str) and len(data["home_state"]) == 2
    assert data.get("primary_specialty") in {s.value for s in Specialty}
    assert isinstance(data.get("years_experience"), int)
    assert data.get("desired_shift") in {s.value for s in Shift}
    assert isinstance(data.get("desired_hourly_rate_cents"), int)
    assert isinstance(data.get("max_commute_miles"), int)
    assert isinstance(data.get("current_employer_name"), str)
    assert isinstance(data.get("confidentiality_exclusions"), list)
    assert data.get("status") in {s.value for s in NurseStatus}
    assert isinstance(data.get("license_verified"), bool)
    assert isinstance(data.get("active_application_count"), int)


def assert_license_verification(data: dict):
    _assert_common_fields(data, "LicenseVerification")
    assert isinstance(data.get("nurse_id"), str)
    assert isinstance(data.get("license_number"), str) and data["license_number"]
    assert isinstance(data.get("license_state"), str) and len(data["license_state"]) == 2
    assert isinstance(data.get("expiry_date"), str)
    assert data.get("status") in {s.value for s in LicenseVerificationStatus}


def assert_certification(data: dict):
    """Certification rows are immutable: id + created_at only, no updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), "Certification.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "Certification.created_at must be ISO 8601"
    )
    assert "updated_at" not in data, "Certification must not carry updated_at"
    assert "version" not in data, "Certification must not carry version"
    assert isinstance(data.get("nurse_id"), str)
    assert data.get("cert_code") in {c.value for c in CertCode}
    assert isinstance(data.get("expires_on"), str)


def assert_employer(data: dict):
    _assert_common_fields(data, "Employer")
    assert isinstance(data.get("legal_name"), str) and data["legal_name"]
    assert isinstance(data.get("facility_state"), str) and len(data["facility_state"]) == 2
    assert data.get("fee_model") in {f.value for f in FeeModel}
    assert data.get("subscription_tier") in {t.value for t in SubscriptionTier}
    assert isinstance(data.get("sla_response_hours"), int)
    assert isinstance(data.get("guarantee_days"), int)
    assert isinstance(data.get("placement_fee_bps"), int)
    assert isinstance(data.get("credit_balance_cents"), int)
    assert data.get("credit_balance_cents") >= 0
    assert data.get("status") in {s.value for s in EmployerStatus}


def assert_requisition(data: dict):
    _assert_common_fields(data, "Requisition")
    assert isinstance(data.get("employer_id"), str)
    assert data.get("specialty") in {s.value for s in Specialty}
    assert isinstance(data.get("unit_name"), str) and data["unit_name"]
    assert isinstance(data.get("required_certs"), list)
    assert isinstance(data.get("facility_state"), str) and len(data["facility_state"]) == 2
    assert isinstance(data.get("distance_from_facility_miles"), int)
    assert data.get("shift") in {s.value for s in Shift}
    assert isinstance(data.get("offered_hourly_rate_cents"), int)
    assert isinstance(data.get("openings_total"), int)
    assert isinstance(data.get("openings_filled"), int)
    assert 0 <= data["openings_filled"] <= data["openings_total"]
    assert data.get("status") in {s.value for s in RequisitionStatus}


def assert_match(data: dict):
    """Match rows are regenerated artifacts: id + created_at only."""
    assert is_valid_uuid(data.get("id", "")), "Match.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "Match.created_at must be ISO 8601"
    assert "updated_at" not in data, "Match must not carry updated_at"
    assert "version" not in data, "Match must not carry version"
    assert isinstance(data.get("nurse_id"), str)
    assert isinstance(data.get("requisition_id"), str)
    assert isinstance(data.get("match_score"), int)
    assert 0 <= data["match_score"] <= 100
    assert isinstance(data.get("suppressed"), bool)
    assert isinstance(data.get("generated_at"), str)


def assert_application(data: dict):
    _assert_common_fields(data, "Application")
    assert isinstance(data.get("requisition_id"), str)
    assert isinstance(data.get("nurse_id"), str)
    assert isinstance(data.get("employer_id"), str)
    assert isinstance(data.get("proposed_hourly_rate_cents"), int)
    assert data.get("proposed_shift") in {s.value for s in Shift}
    assert data.get("status") in {s.value for s in ApplicationStatus}
    assert isinstance(data.get("response_deadline_at"), str)
    assert isinstance(data.get("revision_count"), int) and data["revision_count"] >= 0
    assert isinstance(data.get("deadline_extended"), bool)


def assert_interview(data: dict):
    _assert_common_fields(data, "Interview")
    assert isinstance(data.get("application_id"), str)
    assert isinstance(data.get("starts_at"), str)
    assert isinstance(data.get("ends_at"), str)
    assert data.get("status") in {s.value for s in InterviewStatus}
    assert isinstance(data.get("scheduled_by_employer_at"), str)


def assert_offer(data: dict):
    _assert_common_fields(data, "Offer")
    assert isinstance(data.get("application_id"), str)
    assert isinstance(data.get("offered_hourly_rate_cents"), int)
    assert isinstance(data.get("start_date"), str)
    assert data.get("status") in {s.value for s in OfferStatus}
    assert isinstance(data.get("offer_expires_at"), str)
    assert isinstance(data.get("issued_at"), str)


def assert_screening(data: dict):
    _assert_common_fields(data, "Screening")
    assert isinstance(data.get("application_id"), str)
    assert data.get("credential_status") in {s.value for s in CredentialStatus}
    assert data.get("background_status") in {s.value for s in BackgroundStatus}
    assert data.get("overall_status") in {s.value for s in ScreeningOverallStatus}


def assert_screening_overall_consistent(data: dict):
    """overall_status is the derived compound of the two independent axes."""
    cred = data["credential_status"]
    back = data["background_status"]
    overall = data["overall_status"]
    if cred == CredentialStatus.FAILED.value or back == BackgroundStatus.FLAGGED.value:
        assert overall == ScreeningOverallStatus.BLOCKED.value
    elif cred == CredentialStatus.VERIFIED.value and back == BackgroundStatus.CLEARED.value:
        assert overall == ScreeningOverallStatus.COMPLETE.value
    else:
        assert overall == ScreeningOverallStatus.IN_PROGRESS.value


def assert_document(data: dict):
    _assert_common_fields(data, "OnboardingDocument")
    assert isinstance(data.get("application_id"), str)
    assert data.get("doc_type") in {d.value for d in DocType}
    assert data.get("status") in {s.value for s in DocumentStatus}


def assert_placement(data: dict):
    _assert_common_fields(data, "Placement")
    for key in ("application_id", "requisition_id", "nurse_id", "employer_id"):
        assert isinstance(data.get(key), str)
    assert isinstance(data.get("hourly_rate_cents"), int)
    assert isinstance(data.get("annualized_salary_cents"), int)
    assert isinstance(data.get("start_date"), str)
    assert isinstance(data.get("guarantee_ends_on"), str)
    assert data.get("status") in {s.value for s in PlacementStatus}


def assert_invoice(data: dict):
    _assert_common_fields(data, "Invoice")
    assert isinstance(data.get("employer_id"), str)
    assert data.get("invoice_kind") in {k.value for k in InvoiceKind}
    assert isinstance(data.get("amount_due_cents"), int)
    assert isinstance(data.get("amount_credited_cents"), int)
    assert 0 <= data["amount_credited_cents"] <= data["amount_due_cents"]
    assert data.get("status") in {s.value for s in InvoiceStatus}
