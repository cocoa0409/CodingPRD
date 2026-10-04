"""Payload factories — input fields only, one per resource."""

from .constants import (
    CLOCK_START_UTC,
    TEST_DEFAULTS,
)


# ─── Region ───────────────────────────────────────────

def create_region_payload(**overrides) -> dict:
    payload = {
        "name": "Test Region",
        "state_codes": ["CA"],
        "margin_target_pct": TEST_DEFAULTS["REGION_MARGIN_TARGET_PCT"],
        "capitation_index": TEST_DEFAULTS["REGION_CAPITATION_INDEX"],
    }
    payload.update(overrides)
    return payload


# ─── Member ───────────────────────────────────────────

def create_member_payload(attributed_provider_id=None, **overrides) -> dict:
    payload = {
        "member_ref": "M-T-1",
        "plan_product": "COMMERCIAL_HMO",
        "benefit_tier": "TIER_1",
        "risk_score": 1.0,
        "coverage_effective_date": TEST_DEFAULTS["COVERAGE_EFFECTIVE_DATE"],
    }
    if attributed_provider_id is not None:
        payload["attributed_provider_id"] = attributed_provider_id
    payload.update(overrides)
    return payload


# ─── CareSite ─────────────────────────────────────────

def create_care_site_payload(**overrides) -> dict:
    payload = {
        "site_name": "Test Medical Office",
        "site_type": "MEDICAL_OFFICE",
        "licensed_beds": 0,
        "staffing_fte_budget": TEST_DEFAULTS["SITE_STAFFING_FTE_BUDGET"],
        "facility_investment_budget_cents": 2000000,
    }
    payload.update(overrides)
    return payload


# ─── Department ───────────────────────────────────────

def create_department_payload(**overrides) -> dict:
    payload = {
        "specialty": "PRIMARY_CARE",
        "appointment_slots_budgeted": TEST_DEFAULTS["DEPARTMENT_SLOTS"],
        "wait_threshold_days": TEST_DEFAULTS["DEPARTMENT_WAIT_THRESHOLD_DAYS"],
    }
    payload.update(overrides)
    return payload


# ─── Provider ─────────────────────────────────────────

def create_provider_payload(**overrides) -> dict:
    payload = {
        "provider_name": "Dr Test",
        "specialty": "PRIMARY_CARE",
        "compensation_model": "SALARY",
        "base_component_cents": TEST_DEFAULTS["PROVIDER_BASE_COMPONENT_CENTS"],
        "panel_size_target": TEST_DEFAULTS["PROVIDER_PANEL_SIZE_TARGET"],
    }
    payload.update(overrides)
    return payload


# ─── NetworkService ───────────────────────────────────

def create_network_service_payload(**overrides) -> dict:
    payload = {
        "service_code": "PRIMARY_CARE",
        "service_name": "Primary care",
        "availability_status": "AVAILABLE",
        "capacity_note": "Ample capacity",
    }
    payload.update(overrides)
    return payload


# ─── Appointment ──────────────────────────────────────

def create_appointment_payload(department_id, provider_id, member_id,
                               expected_member_version, **overrides) -> dict:
    payload = {
        "department_id": department_id,
        "provider_id": provider_id,
        "member_id": member_id,
        "appointment_type": "ROUTINE",
        "start_utc": "2026-09-10T09:00:00Z",
        "duration_minutes": 20,
        "expected_member_version": expected_member_version,
    }
    payload.update(overrides)
    return payload


# ─── Referral ─────────────────────────────────────────

def create_referral_payload(member_id, requesting_department_id,
                            target_department_id, expected_member_version,
                            **overrides) -> dict:
    payload = {
        "member_id": member_id,
        "requesting_department_id": requesting_department_id,
        "target_department_id": target_department_id,
        "service_code": "PRIMARY_CARE",
        "referral_type": "INTERNAL",
        "authorization_exception": False,
        "exception_reason": "SERVICE_UNAVAILABLE_IN_NETWORK",
        "external_contract_count": 0,
        "expected_member_version": expected_member_version,
    }
    payload.update(overrides)
    return payload


# ─── OutsideServiceClaim ──────────────────────────────

def create_outside_service_claim_payload(member_id, expected_member_version,
                                         **overrides) -> dict:
    payload = {
        "member_id": member_id,
        "vendor_name": "Test Vendor",
        "service_code": "RADIOLOGY",
        "claim_type": "CONTRACTED",
        "emergency_flag": False,
        "billed_amount_cents": 420000,
        "provider_type": "NON_CONTRACTED",
        "claim_line_number": 1,
        "emergency_inject_once": False,
        "derived_claim_type": "CONTRACTED",
        "expected_member_version": expected_member_version,
    }
    payload.update(overrides)
    return payload


# ─── RegionalBudget ───────────────────────────────────

def create_regional_budget_payload(**overrides) -> dict:
    payload = {
        "period": TEST_DEFAULTS["BUDGET_PERIOD"],
        "staffing_budget_cents": TEST_DEFAULTS["BUDGET_STAFFING_CENTS"],
        "outside_services_budget_cents": TEST_DEFAULTS["BUDGET_OUTSIDE_SERVICES_CENTS"],
        "facility_investment_cents": TEST_DEFAULTS["BUDGET_FACILITY_INVESTMENT_CENTS"],
        "system_deductible_cents": TEST_DEFAULTS["BUDGET_SYSTEM_DEDUCTIBLE_CENTS"],
    }
    payload.update(overrides)
    return payload


# ─── CapacityPlan ─────────────────────────────────────

def create_capacity_plan_payload(department_id, **overrides) -> dict:
    payload = {
        "department_id": department_id,
        "period": TEST_DEFAULTS["BUDGET_PERIOD"],
        "budgeted_slots": 100,
        "panel_target": 3,
    }
    payload.update(overrides)
    return payload


# ─── MemberTransfer ───────────────────────────────────

def create_member_transfer_payload(member_id, from_region_id, to_region_id,
                                   expected_member_version, **overrides) -> dict:
    payload = {
        "member_id": member_id,
        "from_region_id": from_region_id,
        "to_region_id": to_region_id,
        "effective_utc": "2026-09-10T00:00:00Z",
        "expected_member_version": expected_member_version,
    }
    payload.update(overrides)
    return payload


# ─── QualityMetric ────────────────────────────────────

def create_quality_metric_payload(accountable_provider_id, **overrides) -> dict:
    payload = {
        "metric_code": "QUALITY_COMPOSITE",
        "period": TEST_DEFAULTS["BUDGET_PERIOD"],
        "target_value": 80,
        "accountable_provider_id": accountable_provider_id,
    }
    payload.update(overrides)
    return payload


# ─── ReferentialIntegration ───────────────────────────

def create_referential_integration_payload(**overrides) -> dict:
    payload = {
        "integration_type": "MEDICAL_GROUP",
        "risk_sharing_model": "CAPITATED",
        "bound_effective_date": CLOCK_START_UTC,
        "cost_reporting_basis_cents": 10000000,
        "shared_savings_rate": 0.0,
        "per_diem_days": 0,
        "per_diem_rate_cents": 0,
        "per_diem_cap_cents": 0,
        "interim_claim_count": 0,
    }
    payload.update(overrides)
    return payload


# ─── Platform controls ────────────────────────────────

def set_clock_payload(to_iso8601=CLOCK_START_UTC) -> dict:
    return {"to_iso8601": to_iso8601}