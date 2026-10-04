"""Domain types: entity TypedDicts, status enums, role enum.

Every top-level resource in this API carries the full common field set
(id, created_at, updated_at, version) — no entity omits updated_at or version.
"""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    COMPLIANCE_REVIEWER = "ComplianceReviewer"
    CLAIM_ADJUDICATOR = "ClaimAdjudicator"
    TRADE_IN_INSPECTOR = "TradeInInspector"
    SELLER = "Seller"
    CONSUMER = "Consumer"
    SYSTEM = "System"
    ANONYMOUS = "Anonymous"


class SellerOnboardingState(str, Enum):
    APPLICANT = "APPLICANT"
    DOCUMENT_VERIFIED = "DOCUMENT_VERIFIED"
    AUDIT_SCHEDULED = "AUDIT_SCHEDULED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUSPENDED = "SUSPENDED"


class SellerPerformanceTier(str, Enum):
    ELITE = "ELITE"
    STANDARD = "STANDARD"
    PROBATION = "PROBATION"
    SUSPENDED = "SUSPENDED"


class AuditState(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    PASSED = "PASSED"
    FAILED = "FAILED"


class ListingState(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    LISTED = "LISTED"
    DELISTED = "DELISTED"
    SUSPENDED = "SUSPENDED"
    WITHDRAWN = "WITHDRAWN"


class CosmeticGrade(str, Enum):
    FLAWLESS = "FLAWLESS"
    GOOD = "GOOD"
    FAIR = "FAIR"
    POOR = "POOR"


class FunctionalGrade(str, Enum):
    FULLY_FUNCTIONAL = "FULLY_FUNCTIONAL"
    MINOR_FAULTS = "MINOR_FAULTS"
    MAJOR_FAULTS = "MAJOR_FAULTS"


class CarrierLockStatus(str, Enum):
    UNLOCKED = "UNLOCKED"
    LOCKED = "LOCKED"
    UNKNOWN = "UNKNOWN"


class PartProvenance(str, Enum):
    OEM_ONLY = "OEM_ONLY"
    OEM_EQUIVALENT = "OEM_EQUIVALENT"
    AFTERMARKET = "AFTERMARKET"


class VerificationState(str, Enum):
    OPEN = "OPEN"
    DISCLOSED = "DISCLOSED"
    VOIDED = "VOIDED"


class ReservationState(str, Enum):
    ACTIVE = "ACTIVE"
    REPAIRING = "REPAIRING"
    REPLACED = "REPLACED"
    SUSPENDED = "SUSPENDED"
    COMPLETED = "COMPLETED"


class ClaimState(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    RESOLVED = "RESOLVED"


class ResolutionType(str, Enum):
    REPAIR = "REPAIR"
    REPLACE = "REPLACE"


class SectionState(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class TradeInState(str, Enum):
    SUBMITTED = "SUBMITTED"
    INSPECTED = "INSPECTED"
    PRICE_REVISED = "PRICE_REVISED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class DefinitionState(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class Seller(TypedDict):
    id: str
    legal_name: str
    country_code: str
    refurbishment_capacity_units: int
    onboarding_state: str
    performance_tier: str
    latest_score_id: Optional[str]
    exposure_floor_cents: int
    suspension_trigger_count: int
    blocklisted: bool
    created_at: str
    updated_at: str
    version: int


class SellerAuditRecord(TypedDict):
    id: str
    seller_id: str
    audit_state: str
    audit_scheduled_for: str
    audit_scope_note: str
    audit_score: Optional[int]
    auditor_user_id: Optional[str]
    declared_monthly_throughput: int
    created_at: str
    updated_at: str
    version: int


class DeviceListing(TypedDict):
    id: str
    seller_id: str
    model_code: str
    imei: str
    cosmetic_grade: str
    functional_grade: str
    battery_health_pct: int
    carrier_lock_status: str
    part_provenance: str
    provenance_doc_digest: Optional[str]
    serving_seller_id: str
    servicing_seller_id: str
    listing_state: str
    active_reservation_days: int
    unit_reserve_per_day_cents: int
    mystery_shop_disclosed: bool
    servicing_reservation_id: Optional[str]
    list_price_cents: int
    created_at: str
    updated_at: str
    version: int


class MysteryShopVerification(TypedDict):
    id: str
    seller_id: str
    listing_id: str
    verification_state: str
    rationale_code: str
    ordered_cosmetic_grade: str
    received_cosmetic_grade: Optional[str]
    measured_battery_health_pct: Optional[int]
    value_at_risk: int
    reserved_units_delta: int
    exposure_floor_delta_cents: int
    verification_start: str
    verification_end: str
    verifier_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WarrantyReservation(TypedDict):
    id: str
    listing_id: str
    originated_claim_id: Optional[str]
    warranty_state: str
    activated_on: str
    warranty_period_days: int
    expired_on: str
    reserved_units: int
    unit_reserve_per_day_cents: int
    claims_filed_count: int
    repair_obligation_cents: int
    replacement_obligation_cents: int
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict):
    id: str
    listing_id: str
    routed_seller_id: Optional[str]
    claim_state: str
    resolution_type: Optional[str]
    resolution_obligation_cents: Optional[int]
    claim_reason_code: str
    diagnostic_evidence_digest: Optional[str]
    return_carrier: Optional[str]
    return_shipment_cents: int
    seller_funded_amount_cents: int
    claim_reserve_cents: int
    replacement_listing_id: Optional[str]
    on_time_flag: bool
    evidence_included: bool
    created_at: str
    updated_at: str
    version: int


class SellerServiceScore(TypedDict):
    id: str
    seller_id: str
    section_opened_on: str
    section_state: str
    section_closed_on: Optional[str]
    claim_failure_rate_pct: float
    on_time_resolution_pct: float
    grading_compliance_pct: float
    return_rate_pct: float
    service_score: float
    threshold_breached: bool
    created_at: str
    updated_at: str
    version: int


class TradeInSubmission(TypedDict):
    id: str
    customer_ref: str
    submitted_model_code: str
    submission_state: str
    self_declared_cosmetic_grade: str
    self_declared_functional_grade: str
    self_declared_battery_health_pct: int
    self_declared_carrier_lock_status: str
    provisional_quote_cents: int
    inspected_cosmetic_grade: Optional[str]
    inspected_functional_grade: Optional[str]
    inspected_battery_health_pct: Optional[int]
    inspected_carrier_lock_status: Optional[str]
    inspection_fee_cents: int
    final_quote_cents: Optional[int]
    acceptance_deadline: Optional[str]
    revision_count: int
    created_at: str
    updated_at: str
    version: int


class GradingDefinition(TypedDict):
    id: str
    definition_code: str
    definition_state: str
    cosmetic_thresholds: dict
    functional_thresholds: dict
    battery_floor_pct: int
    effective_from: str
    retired_on: Optional[str]
    binding_definition_id: Optional[str]
    created_at: str
    updated_at: str
    version: int