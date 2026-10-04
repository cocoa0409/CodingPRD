"""Domain types: entity TypedDicts, status enums, role enum.

Every principal resource in this API carries the common system-managed fields
`id`, `created_at`, `updated_at` and `version`.
"""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    NETWORK_ADMIN = "NetworkAdmin"
    PRACTICE_ADMIN = "PracticeAdmin"
    REVENUE_CYCLE_MANAGER = "RevenueCycleManager"
    PAYER_ADJUDICATOR = "PayerAdjudicator"
    NETWORK_ANALYST = "NetworkAnalyst"
    PLATFORM_ADMIN = "PlatformAdmin"


class PracticeAffiliationStatus(str, Enum):
    PROSPECTIVE = "PROSPECTIVE"
    AFFILIATED = "AFFILIATED"
    SUSPENDED = "SUSPENDED"
    DEPARTING = "DEPARTING"
    DEPARTED = "DEPARTED"


class PathwaySteeringStatus(str, Enum):
    NOT_ADOPTED = "NOT_ADOPTED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class TierLevel(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


class PracticePricingAgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    SUPERSEDED = "SUPERSEDED"
    REJECTED = "REJECTED"


class DrugPurchaseOrderStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    CONFIRMED = "CONFIRMED"
    BACKORDERED = "BACKORDERED"
    SHIPPED = "SHIPPED"
    RECEIVED = "RECEIVED"
    CANCELLED = "CANCELLED"


class InventoryLotStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    QUARANTINED = "QUARANTINED"
    EXPIRED = "EXPIRED"
    DEPLETED = "DEPLETED"


class PatientTreatmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ADMINISTERED = "ADMINISTERED"
    BILLED = "BILLED"
    VOIDED = "VOIDED"


class PayerClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ADJUDICATED_PAID = "ADJUDICATED_PAID"
    DENIED = "DENIED"
    APPEALED = "APPEALED"
    VOIDED = "VOIDED"


class RebateQualificationStatus(str, Enum):
    PENDING = "PENDING"
    QUALIFIED = "QUALIFIED"
    DISQUALIFIED = "DISQUALIFIED"
    PAID = "PAID"
    RECLAIMED = "RECLAIMED"


class ShortageAllocationStatus(str, Enum):
    GRANTED = "GRANTED"
    PARTIALLY_COMMITTED = "PARTIALLY_COMMITTED"
    FULLY_COMMITTED = "FULLY_COMMITTED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class AffiliationContractStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    DEPARTURE_NOTICE = "DEPARTURE_NOTICE"
    UNWIND_IN_PROGRESS = "UNWIND_IN_PROGRESS"
    TERMINATED = "TERMINATED"


# --- Entity shapes (common_fields: id, created_at, updated_at, version) -----

class OncologyNetwork(TypedDict, total=False):
    id: str
    name: str
    network_agreement_code: str
    rebate_market_share_threshold_pct: float
    rebate_min_compliance_score: float
    compliance_report_grace_days: int
    shortage_allocation_method: str
    payment_terms_days: int
    tier_market_share_boundaries: list
    allocation_epoch_index: int
    is_commercial_terms_frozen: bool
    created_at: str
    updated_at: str
    version: int


class Practice(TypedDict, total=False):
    id: str
    network_id: str
    practice_name: str
    practice_npi: str
    state_code: str
    drug_shortage_baseline_units: int
    denial_ratio_threshold_pct: float
    denied_claim_count: int
    settled_claim_count: int
    pathway_steering_target_pct: float
    affiliation_status: str
    pathway_steering_status: str
    tier_level: str
    trailing_12m_network_purchases_cents: int
    pathway_adherence_pct: float
    unsettled_balance_cents: int
    is_rebate_qualified: bool
    departure_effective_epoch_index: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Provider(TypedDict, total=False):
    id: str
    practice_id: str
    full_name: str
    npi: str
    specialty: str
    is_billing_provider: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class DrugProduct(TypedDict, total=False):
    id: str
    network_id: str
    ndc: str
    brand_name: str
    generic_name: str
    therapeutic_class: str
    unit_type: str
    network_base_price_cents: int
    is_shortage_candidate: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class PracticePricingAgreement(TypedDict, total=False):
    id: str
    practice_id: str
    tier_level: str
    discount_pct: float
    routing_includes_out_of_scope: bool
    effective_from: str
    effective_to: Optional[str]
    status: str
    approved_by_user_id: Optional[str]
    submitted_by_user_id: Optional[str]
    status_changed_by: str
    superseded_by_agreement_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DrugPurchaseOrder(TypedDict, total=False):
    id: str
    practice_id: str
    drug_product_id: str
    shortage_allocation_id: Optional[str]
    quantity_units: int
    unit_price_cents: int
    extended_cost_cents: int
    pricing_tier_applied: str
    status: str
    submitted_at: str
    received_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InventoryLot(TypedDict, total=False):
    id: str
    practice_id: str
    drug_product_id: str
    purchase_order_id: str
    lot_number: str
    quantity_received: int
    quantity_remaining: int
    wastage_units: int
    absorbed_cost_basis_cents: int
    waste_cost_basis_cents: int
    acquisition_cost_cents_per_unit: int
    expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class LotConsumption(TypedDict, total=False):
    id: str
    treatment_id: str
    inventory_lot_id: str
    quantity_consumed: int
    cost_basis_cents: int
    consumption_sequence: int
    is_wastage: bool
    created_at: str
    updated_at: str
    version: int


class PatientTreatment(TypedDict, total=False):
    id: str
    practice_id: str
    provider_id: str
    drug_product_id: str
    pathway_protocol_id: str
    patient_reference: str
    regimen_code: str
    payer_name: str
    admin_fee_cents: int
    policy_admin_fee_cents: int
    administered_units: int
    dose_count: int
    vial_yield_units: int
    administered_at: str
    unmet_dose_units: int
    dose_allocations: list
    is_pathway_concordant: bool
    settlement_priority: int
    acquisition_cost_basis_cents: int
    wastage_cost_basis_cents: int
    wastage_units: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PayerClaim(TypedDict, total=False):
    id: str
    practice_id: str
    treatment_id: str
    payer_name: str
    billed_amount_cents: int
    allowed_amount_cents: int
    paid_amount_cents: int
    billed_admin_fee_cents: int
    written_off_admin_fee_cents: int
    denial_reason_code: Optional[str]
    appeal_round: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RebateProgram(TypedDict, total=False):
    id: str
    network_id: str
    program_name: str
    drug_ndc_scope: str
    market_share_threshold_pct: float
    rebate_pct: float
    compliance_min_score: float
    period_epoch_index: int
    weight_reporting_compliance: int
    weight_adherence_steering: int
    weight_transparency: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RebateQualification(TypedDict, total=False):
    id: str
    practice_id: str
    rebate_program_id: str
    period_epoch_index: int
    market_share_pct: float
    compliance_score: float
    is_qualified: bool
    rebate_amount_cents: int
    holdback_cents: int
    compliance_report_submitted_at: Optional[str]
    compact_discount_credit_cents: int
    compliance_report_verified: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class PathwayProtocol(TypedDict, total=False):
    id: str
    network_id: str
    protocol_code: str
    indication: str
    on_pathway_regimen_codes: list
    declared_regimen_codes: list
    off_pathway_penalty_score: float
    version_label: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PracticeManagementAgreement(TypedDict, total=False):
    id: str
    practice_id: str
    service_line: str
    fee_basis: str
    fee_rate: float
    fixed_fee_cents: int
    per_fte_fee_cents: int
    fte_count: int
    term_start: str
    term_end: str
    accrued_fee_cents: int
    active_month_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ResearchParticipation(TypedDict, total=False):
    id: str
    practice_id: str
    network_id: str
    study_protocol_number: str
    study_phase: str
    sponsor_name: str
    target_enrollment: int
    enrolled_participant_count: int
    site_status: str
    created_at: str
    updated_at: str
    version: int


class DrugShortage(TypedDict, total=False):
    id: str
    network_id: str
    drug_product_id: str
    reported_at: str
    supply_available_units: int
    allocation_method: str
    allocated_units: int
    unallocated_units: int
    unclaimed_authorization_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ShortageAllocation(TypedDict, total=False):
    id: str
    shortage_id: str
    practice_id: str
    allocated_units: int
    consumption_authorization_cents: int
    consumed_authorization_cents: int
    committed_units: int
    allocation_rank: int
    expires_epoch_index: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AffiliationContract(TypedDict, total=False):
    id: str
    practice_id: str
    contract_type: str
    term_start: str
    term_end: str
    notice_period_days: int
    pricing_agreements_unwound: bool
    open_orders_closed: bool
    rebate_holdback_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int