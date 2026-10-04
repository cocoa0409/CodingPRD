"""Domain types: entity TypedDicts, status enums, role enum.

Every entity in this system is declared with common fields (PRD 2.11), so each
TypedDict carries id, created_at, updated_at and version.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    FRANCHISE_ADMIN = "FranchiseAdmin"
    FRANCHISEE_OPERATOR = "FranchiseeOperator"
    COMPLIANCE_AUDITOR = "ComplianceAuditor"


class Trade(str, Enum):
    PLUMBING = "PLUMBING"
    ELECTRICAL = "ELECTRICAL"
    HVAC = "HVAC"
    RESTORATION = "RESTORATION"
    CLEANING = "CLEANING"
    PEST = "PEST"
    APPLIANCE = "APPLIANCE"


class CertificationLevel(str, Enum):
    APPRENTICE = "APPRENTICE"
    JOURNEYMAN = "JOURNEYMAN"
    MASTER = "MASTER"


class EntityType(str, Enum):
    LLC = "LLC"
    CORPORATION = "CORPORATION"
    SOLE_PROPRIETOR = "SOLE_PROPRIETOR"
    PARTNERSHIP = "PARTNERSHIP"


class FranchiseeStatus(str, Enum):
    PROSPECT = "PROSPECT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class TerritoryStatus(str, Enum):
    DEFINED = "DEFINED"
    OFFERED = "OFFERED"
    AWARDED = "AWARDED"
    ACTIVE = "ACTIVE"
    EXPANSION_REQUESTED = "EXPANSION_REQUESTED"
    PENDING_REALLOCATION = "PENDING_REALLOCATION"
    RECLAIMED = "RECLAIMED"


class AgreementLifecycleStatus(str, Enum):
    DRAFT = "DRAFT"
    OFFERED = "OFFERED"
    ACTIVE = "ACTIVE"
    RENEWAL_PENDING = "RENEWAL_PENDING"
    TRANSFER_PENDING = "TRANSFER_PENDING"
    TERMINATED = "TERMINATED"
    EXPIRED = "EXPIRED"


class StandardsStatus(str, Enum):
    COMPLIANT = "COMPLIANT"
    WATCH = "WATCH"
    REMEDIATION_REQUIRED = "REMEDIATION_REQUIRED"
    DEFAULT = "DEFAULT"


class ReferralStatus(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    COMPLETED = "COMPLETED"
    DISPUTED = "DISPUTED"
    SETTLED = "SETTLED"


class LeadSource(str, Enum):
    CALL_CENTER = "CALL_CENTER"
    WEB = "WEB"
    NATIONAL_ACCOUNT = "NATIONAL_ACCOUNT"


class IncomeBand(str, Enum):
    BAND_1 = "BAND_1"
    BAND_2 = "BAND_2"
    BAND_3 = "BAND_3"
    BAND_4 = "BAND_4"


class LeadStatus(str, Enum):
    RECEIVED = "RECEIVED"
    ALLOCATED = "ALLOCATED"
    CONVERTED = "CONVERTED"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"


class AccountType(str, Enum):
    NATIONAL_ACCOUNT = "NATIONAL_ACCOUNT"
    PROPERTY_MANAGER = "PROPERTY_MANAGER"


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class WorkOrderSource(str, Enum):
    NATIONAL_ACCOUNT = "NATIONAL_ACCOUNT"
    PROPERTY_MANAGER = "PROPERTY_MANAGER"
    CALL_CENTER_LEAD = "CALL_CENTER_LEAD"
    CROSS_BRAND_REFERRAL = "CROSS_BRAND_REFERRAL"
    DIRECT = "DIRECT"


class WorkOrderPriority(str, Enum):
    EMERGENCY = "EMERGENCY"
    URGENT = "URGENT"
    STANDARD = "STANDARD"


class WorkOrderStatus(str, Enum):
    CREATED = "CREATED"
    DISPATCHED = "DISPATCHED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    SLA_BREACHED = "SLA_BREACHED"


class AuditKind(str, Enum):
    ANNOUNCED = "ANNOUNCED"
    MYSTERY_SHOP = "MYSTERY_SHOP"


class AuditStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CONDUCTED = "CONDUCTED"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class RemediationStatus(str, Enum):
    NONE = "NONE"
    OPEN = "OPEN"
    SUBMITTED = "SUBMITTED"
    RE_VERIFICATION = "RE_VERIFICATION"
    RESOLVED = "RESOLVED"
    ESCALATED = "ESCALATED"
    DEFAULTED = "DEFAULTED"


class AuditOutcome(str, Enum):
    PASS = "PASS"
    WATCH = "WATCH"
    FAIL = "FAIL"


class StatementStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PAID = "PAID"
    VOIDED = "VOIDED"


class AssignmentKind(str, Enum):
    INITIAL_AWARD = "INITIAL_AWARD"
    RESALE = "RESALE"
    TRANSFER = "TRANSFER"
    TERRITORY_REALLOCATION = "TERRITORY_REALLOCATION"


class TransferKind(str, Enum):
    RESALE = "RESALE"
    TRANSFER = "TRANSFER"
    TERRITORY_REALLOCATION = "TERRITORY_REALLOCATION"


class TransferStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CLOSED = "CLOSED"


# --- entity shapes (all carry common fields: id/created_at/updated_at/version) ---

class Brand(TypedDict):
    id: str
    brand_code: str
    display_name: str
    trade: str
    royalty_rate: float
    national_ad_fund_rate: float
    min_certification_level: str
    cross_brand_fee_table: dict
    audit_cycle_months: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Franchisee(TypedDict):
    id: str
    legal_name: str
    principal_name: str
    entity_type: str
    shared_services_enrolled: bool
    status: str
    active_brand_count: int
    active_agreement_count: int
    allocated_households: int
    lead_cost_balance_cents: int
    standards_score: float
    standards_score_basis: str
    created_at: str
    updated_at: str
    version: int


class Territory(TypedDict):
    id: str
    territory_code: str
    brand_id: str
    franchisee_id: Optional[str]
    parent_territory_id: Optional[str]
    source_of_reallocation_id: Optional[str]
    household_count: int
    postal_codes: List[str]
    protected: bool
    expansion_right_households: int
    allocated_households: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FranchiseAgreement(TypedDict):
    id: str
    agreement_number: str
    franchisee_id: str
    brand_id: str
    territory_id: str
    signed_on: str
    initial_term_months: int
    expires_on: str
    certification_level: str
    royalty_rate_override: Optional[float]
    lifecycle_status: str
    standards_status: str
    effective_royalty_rate: float
    cumulative_royalty_cents: int
    cumulative_referral_net_cents: int
    open_remediation_count: int
    audit_due_iso: Optional[str]
    renewal_clock_iso: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Referral(TypedDict):
    id: str
    referral_code: str
    originating_agreement_id: str
    receiving_agreement_id: str
    customer_household_ref: str
    job_description: str
    estimated_job_value_cents: int
    settled_job_value_cents: int
    referral_fee_rate: float
    referral_fee_cents: int
    fee_variant: str
    accepted_clock_iso: Optional[str]
    expires_clock_iso: str
    settled_clock_iso: Optional[str]
    dispute_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Lead(TypedDict):
    id: str
    brand_id: str
    source: str
    household_income_band: str
    estimated_value_cents: int
    allocated_agreement_id: Optional[str]
    received_clock_iso: str
    allocated_clock_iso: Optional[str]
    allocation_hold_until_iso: Optional[str]
    released_clock_iso: Optional[str]
    lead_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class NationalAccount(TypedDict):
    id: str
    account_name: str
    account_type: str
    contracted_brands: List[str]
    service_level_hours: int
    sla_credit_per_breach_cents: int
    breach_tolerance: int
    annual_commitment_cents: int
    open_breach_count: int
    sla_credit_accrued_cents: int
    accumulated_revenue_cents: int
    commitment_attainment_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class WorkOrder(TypedDict):
    id: str
    agreement_id: str
    source: str
    national_account_id: Optional[str]
    lead_id: Optional[str]
    referral_id: Optional[str]
    priority: str
    service_level_hours: int
    parts_cents: int
    dispatched_clock_iso: Optional[str]
    sla_due_iso: Optional[str]
    closed_clock_iso: Optional[str]
    labor_cents: int
    revenue_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class BrandStandardsAudit(TypedDict):
    id: str
    agreement_id: str
    auditor_operator_id: Optional[str]
    audit_kind: str
    conducted_iso: str
    raw_score: float
    findings_count: int
    critical_findings_count: int
    weighted_score: float
    outcome: str
    audit_status: str
    remediation_status: str
    remediation_owner_operator_id: Optional[str]
    remediation_verifier_operator_id: Optional[str]
    verification_audit_id: Optional[str]
    remediation_due_iso: Optional[str]
    remediation_opened_clock_iso: Optional[str]
    remediation_resolved_clock_iso: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RoyaltyStatement(TypedDict):
    id: str
    agreement_id: str
    period_start: str
    period_end: str
    gross_revenue_cents: int
    royalty_cents: int
    ad_fund_cents: int
    referral_offset_cents: int
    net_remittance_cents: int
    accrual_variant: str
    issued_clock_iso: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class TerritoryAssignment(TypedDict):
    id: str
    territory_id: str
    franchisee_id: str
    source_agreement_id: str
    assignment_kind: str
    assigned_on: str
    released_on: Optional[str]
    active: bool
    created_at: str
    updated_at: str
    version: int


class TransferApplication(TypedDict):
    id: str
    agreement_id: str
    territory_id: str
    applicant_franchisee_id: str
    transfer_kind: str
    purchase_price_cents: int
    target_territory_ids: List[str]
    transfer_fee_cents: int
    reviewer_operator_id: Optional[str]
    approval_operator_id: Optional[str]
    reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int