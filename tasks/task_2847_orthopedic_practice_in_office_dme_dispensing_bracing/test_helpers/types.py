"""Typed shapes for the entities the API returns.

Money is always an integer count of cents, never a decimal string. Rates are
plain decimal fractions. Instants are ISO-8601 UTC strings with exactly three
fractional digits; calendar dates are plain YYYY-MM-DD strings.

Every entity except the coverage verification carries the common identity
fields (`id`, `created_at`, `updated_at`, `version`); the coverage
verification carries only `id` and `created_at`, so its shape below omits the
other two on purpose.
"""

from typing import Any, Dict, List, Optional, TypedDict


class Clinic(TypedDict, total=False):
    id: str
    name: str
    state_code: str
    accreditation_body: str
    accreditation_expires_on: str
    ioas_supervision_level: str
    dispensing_specialties: List[str]
    dispensing_status: str
    stockout_par_level_count: int
    created_at: str
    updated_at: str
    version: int


class Physician(TypedDict, total=False):
    id: str
    clinic_id: str
    full_name: str
    npi: str
    specialty: str
    group_member: bool
    stark_disclosure_on_file: bool
    created_at: str
    updated_at: str
    version: int


class Fitter(TypedDict, total=False):
    id: str
    clinic_id: str
    full_name: str
    credential: str
    credential_expires_on: str
    privilege_scope: str
    fitting_minutes_booked: int
    created_at: str
    updated_at: str
    version: int


class Supplier(TypedDict, total=False):
    id: str
    name: str
    accreditation_body: str
    accreditation_expires_on: str
    promised_turnaround_days: int
    dmepos_standards_attested: bool
    custom_fab_capable: bool
    quality_hold: bool
    turnaround_score: int
    accepted_fab_order_count: int
    created_at: str
    updated_at: str
    version: int


class DeviceProduct(TypedDict, total=False):
    id: str
    supplier_id: str
    hcpcs_code: str
    description: str
    category: str
    specialty: str
    same_or_similar_group: str
    reasonable_useful_lifetime_months: int
    allowed_amount_cents: int
    cash_price_cents: int
    unit_cost_cents: int
    requires_prior_auth: bool
    ioas_supervision_required: str
    created_at: str
    updated_at: str
    version: int


class ClinicParLevel(TypedDict, total=False):
    id: str
    clinic_id: str
    product_id: str
    par_min_qty: int
    par_max_qty: int
    on_hand_qty: int
    reserved_qty: int
    available_qty: int
    lifetime_received_qty: int
    lifetime_dispensed_qty: int
    lifetime_restocked_qty: int
    lifetime_destroyed_qty: int
    stock_posture: str
    created_at: str
    updated_at: str
    version: int


class Patient(TypedDict, total=False):
    id: str
    clinic_id: str
    full_name: str
    dob: str
    payer_type: str
    member_id: str
    medicare_beneficiary: bool
    created_at: str
    updated_at: str
    version: int


class DispenseEncounter(TypedDict, total=False):
    id: str
    clinic_id: str
    patient_id: str
    product_id: str
    ordering_physician_id: str
    mn_physician_id: Optional[str]
    ioas_attesting_physician_id: Optional[str]
    fitter_id: Optional[str]
    refit_of_encounter_id: Optional[str]
    quantity: int
    service_date: str
    clinical_status: str
    financial_status: str
    compliance_hold: bool
    hold_reason: Optional[str]
    mn_diagnosis_code: Optional[str]
    mn_functional_deficit: Optional[str]
    mn_expected_duration_months: Optional[int]
    mn_signed_at: Optional[str]
    ioas_supervision_level_observed: Optional[str]
    ioas_attested_at: Optional[str]
    covered_units: Optional[int]
    patient_responsibility_cents: Optional[int]
    billable_amount_cents: Optional[int]
    responsibility_variant: Optional[str]
    delivery_signature_role: Optional[str]
    delivered_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CoverageVerification(TypedDict, total=False):
    """Append-only and immutable: it carries no `updated_at` and no `version`."""

    id: str
    encounter_id: str
    verification_seq: int
    covered: bool
    deductible_remaining_cents: int
    coinsurance_pct: float
    valid_for_days: int
    allowed_amount_cents_snapshot: int
    verified_at: str
    expires_at: str
    same_or_similar_conflict: bool
    prior_delivered_encounter_id: Optional[str]
    prior_delivered_on: Optional[str]
    months_since_prior_delivery: Optional[int]
    created_at: str


class PriorAuthRequest(TypedDict, total=False):
    id: str
    encounter_id: str
    requested_units: int
    approved_units: Optional[int]
    auth_number: Optional[str]
    status: str
    appeal_round: int
    appeal_note: Optional[str]
    submitted_at: str
    decision_at: Optional[str]
    expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AbnNotice(TypedDict, total=False):
    id: str
    encounter_id: str
    notice_seq: int
    reason_non_covered: str
    status: str
    unit_net_price_cents: int
    estimated_subtotal_cents: int
    dispensing_fee_cents: int
    estimated_cost_cents: int
    option_selected: Optional[str]
    signed_by: Optional[str]
    patient_signed_at: Optional[str]
    witness_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FittingRecord(TypedDict, total=False):
    id: str
    encounter_id: str
    fitter_id: str
    fitting_start_at: str
    fitting_end_at: str
    fitting_minutes: int
    measurement_set: Dict[str, Any]
    fit_outcome: str
    adjustment_note: Optional[str]
    delivery_signature_role: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CustomFabOrder(TypedDict, total=False):
    id: str
    encounter_id: str
    supplier_id: str
    status: str
    promised_turnaround_days_snapshot: int
    promised_delivery_on: str
    submitted_at: str
    first_delivered_at: Optional[str]
    accepted_at: Optional[str]
    adjustment_rounds: int
    first_delivery_days: Optional[int]
    total_elapsed_days: Optional[int]
    projected_turnaround_score: Optional[int]
    final_turnaround_score: Optional[int]
    created_at: str
    updated_at: str
    version: int


class ProductReturn(TypedDict, total=False):
    id: str
    encounter_id: str
    reason: str
    return_note: Optional[str]
    status: str
    condition: Optional[str]
    quantity_returned: int
    days_since_delivery: int
    restock_eligible: Optional[bool]
    device_component_cents: Optional[int]
    fitting_component_cents: Optional[int]
    device_refund_cents: Optional[int]
    fitting_refund_cents: Optional[int]
    refund_cents: Optional[int]
    restock_fee_cents: Optional[int]
    refit_encounter_id: Optional[str]
    inspected_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DispensingSummary(TypedDict, total=False):
    clinic_id: str
    dispensing_status: str
    stockout_par_level_count: int
    units_received_total: int
    units_on_hand_total: int
    units_reserved_total: int
    units_dispensed_total: int
    units_restocked_total: int
    units_destroyed_total: int
    units_accounted_total: int
    gross_charged_cents: int
    refunded_cents: int
    restock_fee_retained_cents: int
    net_cash_position_cents: int
