"""Domain types: entity TypedDicts, status enums, role enum.

Entities carrying `common_fields: true` expose id / created_at / updated_at / version.
The one append-only exception, GivingPartnerVetting, exposes only id and created_at.
"""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    GIVING_PARTNER_COORDINATOR = "GivingPartnerCoordinator"
    GIVING_PARTNER_ORG = "GivingPartnerOrg"
    PROVISIONING_PARTNER = "ProvisioningPartner"
    ALLOCATION_PLANNER = "AllocationPlanner"
    FULFILLMENT_OPERATOR = "FulfillmentOperator"
    CUSTOMER_SERVICE = "CustomerService"
    MARKETING_MANAGER = "MarketingManager"
    IMPACT_AUDITOR = "ImpactAuditor"
    # The product-design role named in the endpoint table.
    PRODUCT_DESIGNER = "ProductDesigner"


class GivingPartnerStatus(str, Enum):
    CANDIDATE = "CANDIDATE"
    VETTING = "VETTING"
    APPROVED = "APPROVED"
    SUSPENDED = "SUSPENDED"
    REJECTED = "REJECTED"
    REJECTED_FINAL = "REJECTED_FINAL"
    INACTIVE = "INACTIVE"


GIVING_PARTNER_STATUSES = [s.value for s in GivingPartnerStatus]

PARTNER_TYPES = [
    "HOMELESS_SHELTER",
    "DOMESTIC_VIOLENCE_SHELTER",
    "YOUTH_OUTREACH",
    "VETERAN_OUTREACH",
    "DISASTER_RELIEF",
    "COMMUNITY_HEALTH_CLINIC",
]

OPERATING_REGIONS = ["NORTHEAST", "SOUTHEAST", "MIDWEST", "SOUTHWEST", "WEST"]

NEED_TIERS = ["CRITICAL", "HIGH", "MODERATE", "LOW"]

VETTING_OUTCOMES = [
    "REQUESTED",
    "DOCUMENTS_SUBMITTED",
    "EVALUATING",
    "APPROVED",
    "REJECTED",
    "EXPIRED",
]

CAPACITY_PROFILE_STATUSES = ["ACTIVE", "EXHAUSTED", "LOCKED", "SUPERSEDED"]

PRODUCT_KINDS = ["ATHLETIC_SOCK", "APPAREL_TOP", "UNDERGARMENT", "SLEEP_ACCESSORY"]

DESIGN_CHANNELS = ["DONATION_ONLY", "DUAL_CHANNEL"]

OBLIGATION_MODELS = ["AT_SALE", "AT_VESTING"]

PRODUCT_STATUSES = ["DRAFT", "ACTIVE", "RETIRED", "ARCHIVED"]

PRODUCT_LINE_STATUSES = [
    "DRAFT", "ACTIVE", "COMMITTED", "RETIRED", "VESTED", "SUNSET", "ARCHIVED",
]

DESIGN_VARIANT_CODES = ["donation_specific", "retail_dual", "none"]

LIABILITY_STATUSES = ["ACCUMULATING", "FROZEN", "CARRIED", "AUDIT_LOCKED", "CLOSED"]

ALLOCATION_STATUSES = [
    "PENDING_ALLOCATION", "APPROVED", "SHIPPED", "PARTIALLY_RECEIVED",
    "RECEIVED", "CANCELLED", "REVERSED",
]

ALLOCATION_KINDS = ["ALLOCATION", "REVERSAL"]

PRIORITY_TIERS = ["EMERGENCY", "CRITICAL", "HIGH", "MODERATE"]

DISTRIBUTION_STATUSES = [
    "SHIPPED", "PARTIALLY_RECEIVED", "RECEIVED", "COMPLETED",
    "DISCREPANCY_CLAIMED", "WRITTEN_OFF", "VOIDED",
]

SEASON_STATUSES = ["PLANNED", "OPEN", "FROZEN", "CLOSED", "FINALIZED"]

CLAIM_STATUSES = [
    "DRAFT", "SUBSTANTIATED", "OVERSTATED", "UNSUBSTANTIATED",
    "SEASON_RESTRICTED", "REVOKED", "EXPIRED",
]

REFERENCE_PERIODS = ["CALENDAR_YEAR", "ROLLING_TWELVE_MONTHS", "SEASON"]

ORDER_STATUSES = [
    "CREATED", "PAID", "DONATION_SATISFIED", "PARTIALLY_REFUNDED",
    "REFUNDED", "CANCELLED",
]

FULFILLMENT_STATUSES = ["PLACED", "PICKED", "SHIPPED", "DELIVERED", "CANCELLED"]

ORDER_LINE_STATUSES = [
    "OPEN", "RETURN_REQUESTED", "RETURN_APPROVED", "RETURNED_CREDITED",
    "EXCHANGED_REPLACED", "EXEMPTED",
]

RETURN_REASONS = ["SIZE", "DEFECT", "CHANGE_OF_MIND", "GOODWILL"]

RETURN_STATUSES = ["REQUESTED", "APPROVED", "REJECTED", "CREDITED", "EXCHANGED"]

AUDIT_KINDS = ["ANNUAL_IMPACT", "PARTNER_PERFORMANCE"]

AUDIT_STATUSES = ["SCHEDULED", "IN_PROGRESS", "FINALIZED", "REOPENED"]

PERFORMANCE_GRADES = ["EXEMPLARY", "SATISFACTORY", "MONITORED", "PROBATION"]


# ---------------------------------------------------------------------------
# Entity TypedDicts — common_fields: true
# ---------------------------------------------------------------------------

class GivingPartner(TypedDict, total=False):
    id: str
    legal_name: str
    partner_type: str
    operating_region: str
    operating_state_code: str
    service_radius_miles: int
    registry_id: str
    ein: str
    founded_year: int
    unduplicated_recipients_per_facility: int
    need_tier: str
    registry_verified: bool
    status: str
    vetting_round: int
    latest_vetting_round_id: Optional[str]
    total_rejections: int
    need_score: int
    capacity_utilization_units: int
    impact_units_total: int
    impact_units_retail_equivalent: int
    avg_distribution_completion_days: Optional[float]
    claim_attributed_units: int
    attributed_percentage: float
    entrance_returns_units: int
    partner_performance_grade: Optional[str]
    last_vetted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PartnerCapacityProfile(TypedDict, total=False):
    id: str
    partner_id: str
    season_code: str
    max_allocatable_units: int
    reserved_units: int
    committed_units: int
    capacity_utilization_units: int
    effective_from: str
    effective_to: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DonationProduct(TypedDict, total=False):
    id: str
    product_name: str
    product_kind: str
    design_channel: str
    design_weight_score: int
    obligation_model: str
    approved_donation_ratio_units: int
    retail_price_cents: int
    unit_cost_cents: int
    is_reusable: bool
    status: str
    active_season_code: Optional[str]
    obligation_units_total: int
    created_at: str
    updated_at: str
    version: int


class DonationProductLine(TypedDict, total=False):
    id: str
    donation_product_id: str
    gtin: str
    unit_size_label: str
    is_essential_good: bool
    donation_eligible: bool
    obligation_units: int
    unit_obligation_cost_cents: int
    design_variant_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DonationLiability(TypedDict, total=False):
    id: str
    donation_product_id: str
    impact_season_id: str
    donation_liability_units: int
    final_liability_units: int
    provisional_liability_units: int
    obligation_units: int
    accrued_obligation_cents: int
    donation_cost_cents: int
    donation_credit_units: int
    frozen_units: int
    required_stated_units: int
    carried_in_units: int
    carried_out_units: int
    status: str
    freeze_recorded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DonationAllocation(TypedDict, total=False):
    id: str
    giving_partner_id: str
    impact_season_id: str
    donation_product_id: str
    donation_liability_id: str
    claim_id: str
    allocation_kind: str
    allocated_units: int
    priority_tier: str
    rank_score: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DonationDistribution(TypedDict, total=False):
    id: str
    allocation_id: str
    shipped_units: int
    received_units: int
    impact_units_confirmed: int
    discrepancy_units: int
    shipment_reference: str
    carrier_code: str
    shipped_at: Optional[str]
    received_at: Optional[str]
    exception_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ImpactSeason(TypedDict, total=False):
    id: str
    season_code: str
    starts_at: str
    ends_at: str
    freezes_at: str
    liability_carry_in_units: int
    claim_frozen_units_total: int
    opening_carry_obligation_cents: int
    requested_season_code: Optional[str]
    is_final: bool
    attributed_units_total: int
    attributed_percentage_total: float
    total_shipped_units: int
    total_received_units: int
    liability_reconciliation_delta: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MarketingClaim(TypedDict, total=False):
    id: str
    donation_product_id: str
    partner_id: str
    stated_donation_units: int
    stated_ratio_text: str
    winback_multiplier: int
    stated_reference_period: str
    substantiated_donation_units: int
    substantiated_ratio_value: float
    status: str
    created_at: str
    updated_at: str
    version: int


class SalesOrder(TypedDict, total=False):
    id: str
    order_number: str
    channel: str
    status: str
    fulfillment_status: str
    ordered_units: int
    returned_units: int
    fulfilled_units: int
    refunded_cents: int
    placed_at: str
    paid_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SalesOrderLine(TypedDict, total=False):
    id: str
    sales_order_id: str
    donation_product_id: str
    donation_product_line_id: str
    quantity: int
    unit_price_cents: int
    line_discount_cents: int
    return_window_days: int
    obligated_units: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ReturnRequest(TypedDict, total=False):
    id: str
    sales_order_line_id: str
    donation_liability_id: str
    request_reason: str
    requested_units: int
    is_exchange: bool
    replacement_product_id: Optional[str]
    replacement_is_donation_good: bool
    status: str
    terminal_outcome: Optional[str]
    refund_amount_cents: int
    liability_delta_units: int
    window_expires_at: str
    created_at: str
    updated_at: str
    version: int


class ImpactAudit(TypedDict, total=False):
    id: str
    impact_season_id: str
    claim_id: str
    audit_kind: str
    claimed_donation_units: int
    shipped_units_verified: int
    received_units_verified: int
    unit_clearance_rate: Optional[float]
    scorecard_total: int
    transaction_test_sample_size: int
    transaction_test_exceptions: int
    partner_performance_grade: str
    liability_reconciliation_delta: int
    status: str
    finalization_error_message: Optional[str]
    finalized_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Entity TypedDict — common_fields: false (append-only: id + created_at only)
# ---------------------------------------------------------------------------

class GivingPartnerVetting(TypedDict, total=False):
    id: str
    partner_id: str
    round_number: int
    outcome: str
    registry_check_passed: bool
    tax_check_passed: bool
    on_site_check_passed: bool
    capacity_check_passed: bool
    need_verification_points: int
    need_verification_evidence: str
    valid_until: str
    outcome_message: str
    created_at: str
    # NOTE: deliberately no updated_at and no version.