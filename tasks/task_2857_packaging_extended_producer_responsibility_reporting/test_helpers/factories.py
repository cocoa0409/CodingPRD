"""Request payload factories.

Field names and declared types follow the PRD exactly: `data_start`, `data_end`,
`effective_from`, `effective_to`, `fieldwork_start` and `fieldwork_end` are
`YYYY-MM-DD` dates, while `registration_deadline`, `submission_open`,
`submission_deadline` and `current_utc` are ISO 8601 UTC instants. Money is
always an integer count of cents and never a string.
"""

import itertools
from typing import Any, Dict, List, Optional

from .constants import (
    ADMIN_FEE_BPS_HIGH_BREADTH,
    ADMIN_FEE_BPS_LOW,
    BASE_MEMBERSHIP_FEE_CENTS,
    BREADTH_REVENUE_THRESHOLD_USD,
    BREADTH_TONNAGE_THRESHOLD_KG,
    GLASS_ONLY_RATES,
    REGISTRATION_DEADLINE_DEFAULT,
)
from .types import (
    EcoModPolicy,
    FeeRoundingOrder,
    ObligationBasis,
)

_gtin_counter = itertools.count(1)


def unique_gtin() -> str:
    """A fresh fourteen-digit global trade item number."""
    return f"{next(_gtin_counter):014d}"


# ---------------------------------------------------------------------------
# State programs and reporting periods
# ---------------------------------------------------------------------------
def state_program_payload(
    state_code: str = "CA",
    obligation_basis: str = ObligationBasis.ENTITY_LEVEL,
    eco_mod_policy: str = EcoModPolicy.BONUS_MALUS,
    fee_rounding_order: str = FeeRoundingOrder.PER_LINE_THEN_SUM,
    small_producer_revenue_threshold_usd: int = BREADTH_REVENUE_THRESHOLD_USD,
    small_producer_tonnage_threshold_kg: float = BREADTH_TONNAGE_THRESHOLD_KG,
    exempt_product_categories: Optional[List[str]] = None,
    verification_required_threshold_kg: float = 3000,
    registration_deadline: str = REGISTRATION_DEADLINE_DEFAULT,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "state_code": state_code,
        "obligation_basis": obligation_basis,
        "eco_mod_policy": eco_mod_policy,
        "fee_rounding_order": fee_rounding_order,
        "small_producer_revenue_threshold_usd": small_producer_revenue_threshold_usd,
        "small_producer_tonnage_threshold_kg": small_producer_tonnage_threshold_kg,
        "exempt_product_categories": (
            [] if exempt_product_categories is None else list(exempt_product_categories)
        ),
        "verification_required_threshold_kg": verification_required_threshold_kg,
        "registration_deadline": registration_deadline,
    }
    payload.update(overrides)
    return payload


def reporting_period_payload(
    period_label: str = "CA-2026-H1",
    data_start: str = "2026-07-01",
    data_end: str = "2027-01-01",
    submission_open: str = "2026-07-01T00:00:00Z",
    submission_deadline: str = "2026-12-31T23:59:59Z",
    correction_window_days: int = 30,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "period_label": period_label,
        "data_start": data_start,
        "data_end": data_end,
        "submission_open": submission_open,
        "submission_deadline": submission_deadline,
        "correction_window_days": correction_window_days,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Producers
# ---------------------------------------------------------------------------
def producer_payload(
    legal_name: str = "Northlake Beverages LLC",
    brand_owner_flag: bool = True,
    importer_of_record_flag: bool = False,
    domestic_licensor_flag: bool = False,
    annual_gross_revenue_usd: int = 5000000,
    contact_email: str = "compliance@northlake.example",
    parent_producer_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "legal_name": legal_name,
        "brand_owner_flag": brand_owner_flag,
        "importer_of_record_flag": importer_of_record_flag,
        "domestic_licensor_flag": domestic_licensor_flag,
        "annual_gross_revenue_usd": annual_gross_revenue_usd,
        "contact_email": contact_email,
    }
    if parent_producer_id is not None:
        payload["parent_producer_id"] = parent_producer_id
    payload.update(overrides)
    return payload


def restate_revenue_payload(
    annual_gross_revenue_usd: int, reason: str = "Audited restatement"
) -> Dict[str, Any]:
    return {
        "annual_gross_revenue_usd": annual_gross_revenue_usd,
        "reason": reason,
    }


# ---------------------------------------------------------------------------
# Stock keeping units and components
# ---------------------------------------------------------------------------
def sku_payload(
    producer_id: str,
    gtin: Optional[str] = None,
    name: str = "Sparkling Water 750ml",
    product_category: str = "BEVERAGE",
    units_sold_annual_estimate: int = 110,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "producer_id": producer_id,
        "gtin": gtin if gtin is not None else unique_gtin(),
        "name": name,
        "product_category": product_category,
        "units_sold_annual_estimate": units_sold_annual_estimate,
    }
    payload.update(overrides)
    return payload


def component_payload(
    material_type: str = "GLASS",
    unit_weight_grams: float = 50.0,
    recyclability_class: str = "READILY_RECYCLABLE",
    pcr_content_pct: int = 0,
    is_reusable: bool = False,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "material_type": material_type,
        "unit_weight_grams": unit_weight_grams,
        "recyclability_class": recyclability_class,
        "pcr_content_pct": pcr_content_pct,
        "is_reusable": is_reusable,
    }
    payload.update(overrides)
    return payload


def revise_packaging_payload(
    components: List[Dict[str, Any]], reason: str = "Lightweighting programme"
) -> Dict[str, Any]:
    return {"components": components, "reason": reason}


def redesign_projection_payload(
    state_program_id: str,
    fee_schedule_id: str,
    tier_basis_kg: float,
    units_basis: str,
    candidate_components: List[Dict[str, Any]],
    projected_units: Optional[int] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "state_program_id": state_program_id,
        "fee_schedule_id": fee_schedule_id,
        "tier_basis_kg": tier_basis_kg,
        "units_basis": units_basis,
        "candidate_components": candidate_components,
    }
    if projected_units is not None:
        payload["projected_units"] = projected_units
    return payload


# ---------------------------------------------------------------------------
# Organisations and fee schedules
# ---------------------------------------------------------------------------
def pro_payload(
    name: str = "Circular Stewardship Alliance",
    contact_email: str = "ops@csa.example",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"name": name, "contact_email": contact_email}
    payload.update(overrides)
    return payload


def material_rate(
    material_type: str,
    tier_min_kg: float,
    tier_max_kg: Optional[float],
    rate_cents_per_kg: int,
) -> Dict[str, Any]:
    return {
        "material_type": material_type,
        "tier_min_kg": tier_min_kg,
        "tier_max_kg": tier_max_kg,
        "rate_cents_per_kg": rate_cents_per_kg,
    }


def fee_schedule_payload(
    pro_id: str,
    state_program_id: str,
    effective_from: str = "2026-01-01",
    effective_to: Optional[str] = None,
    membership_fee_cents: int = BASE_MEMBERSHIP_FEE_CENTS,
    admin_fee_bps_low: int = ADMIN_FEE_BPS_LOW,
    admin_fee_bps_high: int = ADMIN_FEE_BPS_HIGH_BREADTH,
    material_rates: Optional[List[Dict[str, Any]]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "pro_id": pro_id,
        "state_program_id": state_program_id,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "membership_fee_cents": membership_fee_cents,
        "admin_fee_bps_low": admin_fee_bps_low,
        "admin_fee_bps_high": admin_fee_bps_high,
        "material_rates": (
            [dict(row) for row in GLASS_ONLY_RATES]
            if material_rates is None
            else [dict(row) for row in material_rates]
        ),
    }
    payload.update(overrides)
    return payload


def publish_payload(expected_pro_version: int) -> Dict[str, Any]:
    return {"expected_pro_version": expected_pro_version}


# ---------------------------------------------------------------------------
# Registrations, memberships, reports
# ---------------------------------------------------------------------------
def registration_payload(producer_id: str, state_program_id: str) -> Dict[str, Any]:
    return {"producer_id": producer_id, "state_program_id": state_program_id}


def decision_payload(decision: str, reason: Optional[str] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    if reason is not None:
        payload["reason"] = reason
    return payload


def suspend_payload(suspension_reason: str = "AUDIT_OPEN") -> Dict[str, Any]:
    return {"suspension_reason": suspension_reason}


def withdraw_payload(reason: str = "exiting the state market") -> Dict[str, Any]:
    return {"reason": reason}


def membership_payload(
    registration_id: str,
    pro_id: str,
    fee_schedule_id: str,
    expected_registration_version: int,
) -> Dict[str, Any]:
    return {
        "registration_id": registration_id,
        "pro_id": pro_id,
        "fee_schedule_id": fee_schedule_id,
        "expected_registration_version": expected_registration_version,
    }


def fee_payment_payload(amount_cents: int) -> Dict[str, Any]:
    return {"amount_cents": amount_cents}


def report_payload(registration_id: str, reporting_period_id: str) -> Dict[str, Any]:
    return {
        "registration_id": registration_id,
        "reporting_period_id": reporting_period_id,
    }


def report_line_payload(sku_id: str, units_sold: int) -> Dict[str, Any]:
    return {"sku_id": sku_id, "units_sold": units_sold}


def assess_payload(variant: str) -> Dict[str, Any]:
    return {"variant": variant}


# ---------------------------------------------------------------------------
# Verification engagements and invoices
# ---------------------------------------------------------------------------
def engagement_payload(
    packaging_report_id: str,
    verifier_user_id: str,
    fieldwork_start: str = "2026-08-05",
    fieldwork_end: str = "2026-08-10",
) -> Dict[str, Any]:
    return {
        "packaging_report_id": packaging_report_id,
        "verifier_user_id": verifier_user_id,
        "fieldwork_start": fieldwork_start,
        "fieldwork_end": fieldwork_end,
    }


def opinion_payload(opinion: str, findings_note: Optional[str] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"opinion": opinion}
    if findings_note is not None:
        payload["findings_note"] = findings_note
    return payload


def invoice_payload(packaging_report_id: str, membership_id: str) -> Dict[str, Any]:
    return {
        "packaging_report_id": packaging_report_id,
        "membership_id": membership_id,
    }


def void_payload(void_reason: str = "Issued against the wrong billing contact") -> Dict[str, Any]:
    return {"void_reason": void_reason}
