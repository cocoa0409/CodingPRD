"""Request payload builders for the Practice Acquisition Integration API.

Every money amount is emitted as a JSON number of integer cents and every rate
as a JSON number of basis points, exactly as the PRD declares. Date fields are
emitted as `YYYY-MM-DD` calendar dates; only the logical clock takes a full
ISO-8601 instant, and `make_clock_instant` guarantees that shape.
"""

from typing import Any, Dict, Optional

from .constants import (
    CHART_TYPE_STRUCTURED,
    CONVERSION_TYPE_PROVIDER_BASED_DEPARTMENT,
    CR_CONCLUSION_REASONABLE,
    LICENSE_EXPIRY_A,
    METHOD_INCOME_APPROACH,
    METHOD_MARKET_APPROACH,
    METHOD_NARRATIVE,
    MODEL_BASE_PLUS_INCENTIVE,
    NPI_A,
    OPINION_TYPE_COMMERCIAL_REASONABLENESS,
    OPINION_TYPE_FMV,
    PAYER_TYPE_COMMERCIAL,
    PHYSICIAN_NAME_A,
    POLICY_FORM_OCCURRENCE,
    ROLE_CODE_MA,
    SOURCE_SYSTEM_ATHENA,
    SPECIALTY_CARDIOLOGY,
    SPECIALTY_PRIMARY_CARE,
    STANDARD_FMV_EBITDA_CENTS,
    STANDARD_FMV_EFFECTIVE_ON,
    STANDARD_FMV_MULTIPLE_BPS,
    STANDARD_PLAN_BASE_CENTS,
    STANDARD_PLAN_CF_CENTS_PER_WRVU,
    STANDARD_PLAN_PROJECTED_WRVU,
    STANDARD_PLAN_THRESHOLD_WRVU,
    STARK_BONA_FIDE_EMPLOYMENT,
    STRUCTURE_ASSET,
    STRUCTURE_EQUITY,
    TASK_COMPLIANCE_TRAINING,
    CONTRACT_FORM_ASSIGNABLE,
    LIABILITY_EQUIPMENT_LEASE,
)

Payload = Dict[str, Any]


def _merge(base: Payload, overrides: Payload) -> Payload:
    """Overlay overrides onto base; an explicit None override is preserved."""
    merged = dict(base)
    merged.update(overrides)
    return merged


def make_clock_instant(date: str, time_of_day: str = "00:00:00") -> str:
    """Build the full ISO-8601 instant the clock endpoint requires."""
    return f"{date}T{time_of_day}Z"


# --- Acquisition ------------------------------------------------------------


def acquisition_payload(**overrides: Any) -> Payload:
    """The canonical PRIMARY_CARE / ASSET / OCCURRENCE acquisition."""
    return _merge(
        {
            "target_practice_name": "Lakeside Family Medicine",
            "specialty": SPECIALTY_PRIMARY_CARE,
            "structure": STRUCTURE_ASSET,
            "malpractice_policy_form": POLICY_FORM_OCCURRENCE,
            "annual_malpractice_premium_cents": 4_800_000,
            "trailing_annual_collections_cents": 500_000_000,
            "target_close_on": "2026-11-01",
            "required_staff_headcount": 5,
            "retention_pool_total_cents": 3_000_000,
            "escrow_total_cents": 10_000_000,
        },
        overrides,
    )


def cardiology_acquisition_payload(**overrides: Any) -> Payload:
    """The canonical CARDIOLOGY / EQUITY second acquisition."""
    return _merge(
        {
            "target_practice_name": "Northgate Cardiology Associates",
            "specialty": SPECIALTY_CARDIOLOGY,
            "structure": STRUCTURE_EQUITY,
            "malpractice_policy_form": POLICY_FORM_OCCURRENCE,
            "annual_malpractice_premium_cents": 9_600_000,
            "trailing_annual_collections_cents": 900_000_000,
            "target_close_on": "2026-12-01",
            "required_staff_headcount": 8,
            "retention_pool_total_cents": 6_000_000,
            "escrow_total_cents": 20_000_000,
        },
        overrides,
    )


def acquisition_status_payload(target_status: str, **overrides: Any) -> Payload:
    return _merge({"target_status": target_status}, overrides)


def compliance_clearance_payload(
    target_clearance: str, clearance_note: str = "Compliance review update", **overrides: Any
) -> Payload:
    return _merge(
        {"target_clearance": target_clearance, "clearance_note": clearance_note},
        overrides,
    )


# --- Physician --------------------------------------------------------------


def physician_payload(acquisition_id: str, **overrides: Any) -> Payload:
    return _merge(
        {
            "acquisition_id": acquisition_id,
            "npi": NPI_A,
            "full_name": PHYSICIAN_NAME_A,
            "specialty": SPECIALTY_PRIMARY_CARE,
            "board_certified": True,
            "state_license_expires_on": LICENSE_EXPIRY_A,
        },
        overrides,
    )


# --- Valuation opinion ------------------------------------------------------


def market_fmv_payload(
    acquisition_id: str, expected_acquisition_version: int, **overrides: Any
) -> Payload:
    return _merge(
        {
            "acquisition_id": acquisition_id,
            "expected_acquisition_version": expected_acquisition_version,
            "opinion_type": OPINION_TYPE_FMV,
            "method": METHOD_MARKET_APPROACH,
            "normalized_ebitda_cents": STANDARD_FMV_EBITDA_CENTS,
            "market_multiple_bps": STANDARD_FMV_MULTIPLE_BPS,
            "independence_attested": True,
            "effective_on": STANDARD_FMV_EFFECTIVE_ON,
        },
        overrides,
    )


def income_fmv_payload(
    acquisition_id: str, expected_acquisition_version: int, **overrides: Any
) -> Payload:
    return _merge(
        {
            "acquisition_id": acquisition_id,
            "expected_acquisition_version": expected_acquisition_version,
            "opinion_type": OPINION_TYPE_FMV,
            "method": METHOD_INCOME_APPROACH,
            "normalized_ebitda_cents": 240_000_000,
            "projection_years": 3,
            "ebitda_growth_bps": 300,
            "discount_rate_bps": 1400,
            "terminal_growth_bps": 250,
            "independence_attested": True,
            "effective_on": STANDARD_FMV_EFFECTIVE_ON,
        },
        overrides,
    )


def cr_opinion_payload(
    acquisition_id: str, expected_acquisition_version: int, **overrides: Any
) -> Payload:
    return _merge(
        {
            "acquisition_id": acquisition_id,
            "expected_acquisition_version": expected_acquisition_version,
            "opinion_type": OPINION_TYPE_COMMERCIAL_REASONABLENESS,
            "method": METHOD_NARRATIVE,
            "cr_conclusion": CR_CONCLUSION_REASONABLE,
            "independence_attested": True,
            "effective_on": STANDARD_FMV_EFFECTIVE_ON,
        },
        overrides,
    )


def opinion_status_payload(target_status: str, **overrides: Any) -> Payload:
    return _merge({"target_status": target_status}, overrides)


# --- Compensation plan ------------------------------------------------------


def compensation_plan_payload(
    acquisition_id: str,
    expected_acquisition_version: int,
    physician_id: str,
    **overrides: Any,
) -> Payload:
    """The canonical BASE_PLUS_INCENTIVE plan: 29,800,000 cents, 68.33rd percentile."""
    return _merge(
        {
            "acquisition_id": acquisition_id,
            "expected_acquisition_version": expected_acquisition_version,
            "physician_id": physician_id,
            "model_type": MODEL_BASE_PLUS_INCENTIVE,
            "base_salary_cents": STANDARD_PLAN_BASE_CENTS,
            "conversion_factor_cents_per_wrvu": STANDARD_PLAN_CF_CENTS_PER_WRVU,
            "threshold_wrvu": STANDARD_PLAN_THRESHOLD_WRVU,
            "projected_annual_wrvu": STANDARD_PLAN_PROJECTED_WRVU,
            "includes_referral_credit": False,
            "stark_exception": STARK_BONA_FIDE_EMPLOYMENT,
            "fmv_justification_on_file": False,
        },
        overrides,
    )


def plan_status_payload(target_status: str, **overrides: Any) -> Payload:
    return _merge({"target_status": target_status}, overrides)


# --- Liability item ---------------------------------------------------------


def liability_item_payload(acquisition_id: str, **overrides: Any) -> Payload:
    return _merge(
        {
            "acquisition_id": acquisition_id,
            "category": LIABILITY_EQUIPMENT_LEASE,
            "description": "Imaging equipment lease assumed at close",
            "estimated_amount_cents": 2_500_000,
        },
        overrides,
    )


def disposition_payload(target_disposition: str, **overrides: Any) -> Payload:
    return _merge({"target_disposition": target_disposition}, overrides)


# --- Payer contract ---------------------------------------------------------


def payer_contract_payload(acquisition_id: str, **overrides: Any) -> Payload:
    return _merge(
        {
            "acquisition_id": acquisition_id,
            "payer_name": "Aetna Choice",
            "payer_type": PAYER_TYPE_COMMERCIAL,
            "contract_form": CONTRACT_FORM_ASSIGNABLE,
            "notice_days_required": 90,
            "effective_on": "2026-11-01",
            "terminates_on": "2027-10-31",
            "annual_revenue_share_bps": 2500,
            "committee_slots_per_cycle": 2,
        },
        overrides,
    )


def novation_payload(action: str, **overrides: Any) -> Payload:
    return _merge({"action": action}, overrides)


# --- Credentialing package --------------------------------------------------


def credentialing_package_payload(
    acquisition_id: str,
    physician_id: str,
    payer_contract_id: str,
    submitted_on: str = "2026-08-03",
    **overrides: Any,
) -> Payload:
    return _merge(
        {
            "acquisition_id": acquisition_id,
            "physician_id": physician_id,
            "payer_contract_id": payer_contract_id,
            "submitted_on": submitted_on,
        },
        overrides,
    )


def package_status_payload(target_status: str, **overrides: Any) -> Payload:
    return _merge({"target_status": target_status}, overrides)


# --- EHR migration batch ----------------------------------------------------


def ehr_migration_batch_payload(acquisition_id: str, **overrides: Any) -> Payload:
    return _merge(
        {
            "acquisition_id": acquisition_id,
            "batch_label": "BATCH-A",
            "source_system": SOURCE_SYSTEM_ATHENA,
            "chart_type": CHART_TYPE_STRUCTURED,
            "record_count": 20000,
            "last_encounter_on": "2026-07-15",
            "contains_minor_records": False,
        },
        overrides,
    )


def batch_progress_payload(action: str, **overrides: Any) -> Payload:
    return _merge({"action": action}, overrides)


def reconcile_payload(validated_count: int, defect_count: int, **overrides: Any) -> Payload:
    return _merge(
        {
            "action": "RECONCILE",
            "validated_count": validated_count,
            "defect_count": defect_count,
        },
        overrides,
    )


# --- Staff transition offer -------------------------------------------------


def staff_offer_payload(acquisition_id: str, **overrides: Any) -> Payload:
    return _merge(
        {
            "acquisition_id": acquisition_id,
            "staff_member_name": "Teo Marchetti",
            "role_code": ROLE_CODE_MA,
            "legacy_annual_wage_cents": 3_600_000,
            "legacy_pto_hours": 40,
            "credited_service_months": 30,
            "offer_expires_on": "2026-10-15",
        },
        overrides,
    )


def offer_status_payload(target_status: str, **overrides: Any) -> Payload:
    return _merge({"target_status": target_status}, overrides)


# --- Billing conversion -----------------------------------------------------


def billing_conversion_payload(acquisition_id: str, **overrides: Any) -> Payload:
    return _merge(
        {
            "acquisition_id": acquisition_id,
            "site_name": "Lakeside Main Campus",
            "conversion_type": CONVERSION_TYPE_PROVIDER_BASED_DEPARTMENT,
            "required_notice_count": 1200,
            "notified_patient_count": 1200,
            "notices_issued_on": "2026-10-02",
            "effective_on": "2026-11-01",
        },
        overrides,
    )


def conversion_status_payload(target_status: str, **overrides: Any) -> Payload:
    return _merge({"target_status": target_status}, overrides)


# --- Readiness task ---------------------------------------------------------


def readiness_task_payload(acquisition_id: str, **overrides: Any) -> Payload:
    return _merge(
        {
            "acquisition_id": acquisition_id,
            "task_code": TASK_COMPLIANCE_TRAINING,
            "is_blocking": True,
            "due_on": "2026-10-25",
        },
        overrides,
    )


def task_status_payload(target_status: str, **overrides: Any) -> Payload:
    return _merge({"target_status": target_status}, overrides)


# --- Performance report -----------------------------------------------------


def performance_report_payload(
    acquisition_id: str,
    physician_id: str,
    applied_comp_plan_id: str,
    period_start_on: str = "2026-08-01",
    period_end_on: str = "2026-08-31",
    actual_wrvu: int = 700,
    actual_collections_cents: int = 4_000_000,
    **overrides: Any,
) -> Payload:
    return _merge(
        {
            "acquisition_id": acquisition_id,
            "physician_id": physician_id,
            "applied_comp_plan_id": applied_comp_plan_id,
            "period_start_on": period_start_on,
            "period_end_on": period_end_on,
            "actual_wrvu": actual_wrvu,
            "actual_collections_cents": actual_collections_cents,
        },
        overrides,
    )


def without(payload: Payload, *fields: str) -> Payload:
    """Return a copy of `payload` with the named fields removed."""
    return {key: value for key, value in payload.items() if key not in fields}


def with_field(payload: Payload, field: str, value: Optional[Any]) -> Payload:
    updated = dict(payload)
    updated[field] = value
    return updated
