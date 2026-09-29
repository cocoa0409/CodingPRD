"""Domain types: entity TypedDicts, status enums, role enum.

Two resource types are append-only ledger rows and therefore carry only ``id``
and ``created_at`` — ``FeedbackEntry`` and ``UsageReport``.  Their TypedDicts
deliberately omit ``updated_at`` and ``version``.
"""

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ─── Roles ────────────────────────────────────────────────────────────────────

class UserRole(str, Enum):
    CONSORTIUM_ADMIN = "ConsortiumAdmin"
    MEMBER_LIBRARIAN = "MemberLibrarian"
    LICENSE_NEGOTIATOR = "LicenseNegotiator"
    VENDOR_REP = "VendorRep"
    ACCESS_ENGINEER = "AccessEngineer"


# ─── Status enums ─────────────────────────────────────────────────────────────

class MemberStanding(str, Enum):
    IN_GOOD_STANDING = "IN_GOOD_STANDING"
    OVER_COMMITTED = "OVER_COMMITTED"


class TrialStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    ENDORSED = "ENDORSED"
    DECLINED = "DECLINED"
    WITHDRAWN = "WITHDRAWN"


class NegotiationStatus(str, Enum):
    DRAFTING = "DRAFTING"
    VENDOR_REVIEW = "VENDOR_REVIEW"
    COUNTERED = "COUNTERED"
    AGREED = "AGREED"
    SIGNED = "SIGNED"


class CommitmentStatus(str, Enum):
    PLEDGED = "PLEDGED"
    CONFIRMED = "CONFIRMED"
    WITHDRAWN = "WITHDRAWN"
    RELEASED = "RELEASED"


class ContractStatus(str, Enum):
    PENDING_ACTIVATION = "PENDING_ACTIVATION"
    ACTIVE = "ACTIVE"
    NOTICE_GIVEN = "NOTICE_GIVEN"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class AccessStatus(str, Enum):
    UNCONFIGURED = "UNCONFIGURED"
    CONFIGURED = "CONFIGURED"
    DEGRADED = "DEGRADED"
    SUSPENDED = "SUSPENDED"
    POST_CANCELLATION = "POST_CANCELLATION"


class AuthConfigStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"


class IncidentStatus(str, Enum):
    OPEN = "OPEN"
    DIAGNOSED = "DIAGNOSED"
    RESOLVED = "RESOLVED"
    REOPENED = "REOPENED"


class RenewalDecisionStatus(str, Enum):
    DRAFT = "DRAFT"
    VOTING = "VOTING"
    DECIDED_RENEW = "DECIDED_RENEW"
    DECIDED_CANCEL = "DECIDED_CANCEL"
    DECIDED_RESTRUCTURE = "DECIDED_RESTRUCTURE"
    EXECUTED = "EXECUTED"
    REVERTED = "REVERTED"
    SUPERSEDED = "SUPERSEDED"


class ArchivalCheckStatus(str, Enum):
    PENDING = "PENDING"
    ATTESTED = "ATTESTED"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"


class CostPerUseBand(str, Enum):
    EXCELLENT = "EXCELLENT"
    GOOD = "GOOD"
    POOR = "POOR"
    NO_USE = "NO_USE"


# ─── Entities carrying the full quartet (id/created_at/updated_at/version) ────

class Member(TypedDict):
    id: str
    name: str
    fte_count: int
    carnegie_class: str
    budget_ceiling_cents: int
    annual_committed_cents: int
    standing: str
    created_at: str
    updated_at: str
    version: int


class Vendor(TypedDict):
    id: str
    name: str
    archival_agency_code: Optional[str]
    vpat_on_file: bool
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict):
    id: str
    vendor_id: str
    name: str
    base_list_price_cents: int
    title_count: int
    inflation_cap_pct: float
    cancellation_notice_days: int
    perpetual_access_mode_offered: str
    ill_mode_offered: str
    text_mining_offered: bool
    tier_bands: List[Dict[str, Any]]
    created_at: str
    updated_at: str
    version: int


class Trial(TypedDict):
    id: str
    product_id: str
    member_id: str
    status: str
    start_date: str
    end_date: str
    criteria: List[Dict[str, Any]]
    provisional_score: Optional[float]
    final_score: Optional[float]
    quorum_penalty_applied: bool
    feedback_count: int
    distinct_stakeholder_group_count: int
    created_at: str
    updated_at: str
    version: int


class Negotiation(TypedDict):
    id: str
    product_id: str
    trial_id: str
    status: str
    target_term_start: str
    target_term_end: str
    requested_ill_mode: str
    requested_text_mining: bool
    requested_accessibility_conformance: str
    requested_perpetual_access: str
    granted_ill_mode: Optional[str]
    granted_text_mining: Optional[bool]
    granted_accessibility_conformance: Optional[str]
    granted_perpetual_access: Optional[str]
    round_count: int
    vendor_counter_price_cents: Optional[int]
    agreed_price_cents: Optional[int]
    last_vendor_disposition: Optional[str]
    last_submitted_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Commitment(TypedDict):
    id: str
    product_id: str
    member_id: str
    subscription_id: Optional[str]
    status: str
    projected_price_cents: int
    tier_price_cents: Optional[int]
    applied_discount_pct: float
    participant_count_at_pricing: int
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict):
    id: str
    negotiation_id: str
    product_id: str
    contract_status: str
    access_status: str
    negotiated_price_cents: int
    activation_start_date: str
    term_start: str
    term_end: str
    entitled_title_count: int
    perpetual_access_mode: str
    notice_deadline_date: str
    access_health_score: int
    degrade_count: int
    sla_credit_cents: int
    renewal_term_count: int
    created_at: str
    updated_at: str
    version: int


class AuthConfig(TypedDict):
    id: str
    subscription_id: str
    auth_method: str
    auth_realm_code: str
    ip_ranges: List[str]
    proxy_prefix: Optional[str]
    verification_status: str
    last_probe_result: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AccessIncident(TypedDict):
    id: str
    subscription_id: str
    member_id: str
    symptom_code: str
    off_campus: bool
    status: str
    root_cause_code: Optional[str]
    remedy_code: Optional[str]
    reopen_count: int
    created_at: str
    updated_at: str
    version: int


class RenewalDecision(TypedDict):
    id: str
    subscription_id: str
    status: str
    recommended_action: str
    resolved_action: Optional[str]
    vendor_requested_increase_pct: float
    capped_increase_pct: Optional[float]
    cost_per_use_cents: Optional[int]
    cost_per_use_band: Optional[str]
    loyalty_credit_cents: int
    sla_credit_applied_cents: int
    offer_price_cents: Optional[int]
    titles_out: List[str]
    titles_in: List[str]
    delta_price_cents: Optional[int]
    ballots: List[Dict[str, Any]]
    yes_count: int
    quorum_met: bool
    created_at: str
    updated_at: str
    version: int


class ArchivalDepositCheck(TypedDict):
    id: str
    subscription_id: str
    agency_code: str
    status: str
    deposited_title_count: int
    attested_title_count: Optional[int]
    coverage_pct: Optional[float]
    created_at: str
    updated_at: str
    version: int


# ─── Append-only rows: only id + created_at, no updated_at, no version ────────

class FeedbackEntry(TypedDict):
    id: str
    trial_id: str
    stakeholder_group: str
    criterion_code: str
    score: int
    comment: Optional[str]
    submitted_during_status: str
    submitted_by_user_id: str
    created_at: str


class UsageReport(TypedDict):
    id: str
    subscription_id: str
    member_id: str
    period_month: str
    full_text_requests: int
    searches: int
    denials: int
    created_at: str


# ─── Analysis payloads (read-only projections) ───────────────────────────────

class CostPerUseAnalysis(TypedDict):
    usage_count: int
    cost_per_use_cents: Optional[int]
    band: str
    settled_invoice_total_cents: int


class InvoiceAllocationLine(TypedDict):
    commitment_id: str
    member_id: str
    allocated_cents: int
    fte_weight: int


class InvoiceAllocation(TypedDict):
    total_cents: int
    lines: List[InvoiceAllocationLine]
    residual_cents: int
    residual_assigned_commitment_id: Optional[str]


class ClockState(TypedDict):
    current_utc: str
    activated_subscription_ids: List[str]
    expired_subscription_ids: List[str]
