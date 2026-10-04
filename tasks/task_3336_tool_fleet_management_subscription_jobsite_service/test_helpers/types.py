"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the PRD §2.4 (common properties), §3 entity descriptions.
UsageEvent and EndOfTermSettlement are append-only: they carry only id and
created_at (no updated_at, no version).
"""
from enum import Enum
from typing import TypedDict, Optional, List


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class RateCardStatus(str, Enum):
    ACTIVE = "ACTIVE"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    ENDING = "ENDING"
    CLOSED = "CLOSED"


class AssetStatus(str, Enum):
    REGISTERED = "REGISTERED"
    DEPLOYED = "DEPLOYED"
    IN_TRANSIT = "IN_TRANSIT"
    IN_REPAIR = "IN_REPAIR"
    LOST = "LOST"
    RETIRED = "RETIRED"


class LoanerStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    DISPATCHED = "DISPATCHED"
    RETURNED = "RETURNED"
    DECOMMISSIONED = "DECOMMISSIONED"


class TicketStatus(str, Enum):
    OPENED = "OPENED"
    PICKUP_SCHEDULED = "PICKUP_SCHEDULED"
    IN_SHOP = "IN_SHOP"
    LOANER_DISPATCHED = "LOANER_DISPATCHED"
    QUALITY_CHECK = "QUALITY_CHECK"
    CLOSED = "CLOSED"
    REOPENED = "REOPENED"


class ClaimStatus(str, Enum):
    REPORTED = "REPORTED"
    POLICE_VERIFIED = "POLICE_VERIFIED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"


class OrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    FULFILLED = "FULFILLED"
    REJECTED = "REJECTED"


class CaseStatus(str, Enum):
    OPEN = "OPEN"
    DOCUMENTED = "DOCUMENTED"
    REJECTED = "REJECTED"


class ToolCategory(str, Enum):
    DRILL = "DRILL"
    SAW = "SAW"
    BREAKER = "BREAKER"
    MEASURING = "MEASURING"
    ANCHORING = "ANCHORING"


class WeightClass(str, Enum):
    LIGHT = "LIGHT"
    HEAVY = "HEAVY"


class EndOfTermOption(str, Enum):
    BUYOUT = "BUYOUT"
    RENEWAL = "RENEWAL"
    RETURN = "RETURN"


class UserRole(str, Enum):
    FLEET_ADMIN = "FleetAdmin"
    CONTRACTOR_MANAGER = "ContractorManager"
    JOBSITE_SUPERVISOR = "JobsiteSupervisor"
    SERVICE_COORDINATOR = "ServiceCoordinator"
    CLAIMS_ADJUSTER = "ClaimsAdjuster"
    FIELD_ENGINEER = "FieldEngineer"


# --- entity shapes (id + created_at + updated_at + version on common entities) ---

class ContractorAccount(TypedDict):
    id: str
    company_name: str
    tax_id: str
    credit_limit_cents: int
    status: str
    outstanding_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class RateCard(TypedDict):
    id: str
    code: str
    tool_category: str
    base_monthly_rate_cents: int
    tier2_threshold: int
    tier2_monthly_rate_cents: int
    tier3_threshold: int
    tier3_monthly_rate_cents: int
    min_monthly_fee_cents: int
    effective_from: str
    effective_to: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ToolModel(TypedDict):
    id: str
    model_code: str
    category: str
    replacement_value_cents: int
    weight_class: str
    created_at: str
    updated_at: str
    version: int


class FleetAgreement(TypedDict):
    id: str
    account_id: str
    agreement_number: str
    term_months: int
    start_date: str
    end_date: str
    status: str
    end_of_term_option: str
    fleet_size_target: int
    billed_this_month_cents: int
    theft_claim_count: int
    created_at: str
    updated_at: str
    version: int


class ToolAsset(TypedDict):
    id: str
    agreement_id: str
    tool_model_id: str
    serial_number: str
    tag_code: str
    status: str
    current_jobsite_id: Optional[str]
    pending_jobsite_id: Optional[str]
    commissioned_on: Optional[str]
    utilization_minutes_current_month: int
    created_at: str
    updated_at: str
    version: int


class Jobsite(TypedDict):
    id: str
    account_id: str
    name: str
    address: str
    capacity_assets: int
    geofence_radius_m: int
    deployed_asset_count: int
    created_at: str
    updated_at: str
    version: int


class UsageEvent(TypedDict):
    id: str
    asset_id: str
    started_at: str
    ended_at: str
    minutes: int
    created_at: str


class LoanerUnit(TypedDict):
    id: str
    tool_model_id: str
    serial_number: str
    status: str
    assigned_ticket_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RepairTicket(TypedDict):
    id: str
    asset_id: str
    opened_at: str
    promised_return_by: str
    loaner_requested: bool
    loaner_unit_id: Optional[str]
    closed_at: Optional[str]
    sla_breach_credit_cents: int
    status: str
    reopen_count: int
    created_at: str
    updated_at: str
    version: int


class TheftClaim(TypedDict):
    id: str
    asset_id: str
    reported_at: str
    police_report_number: Optional[str]
    police_report_filed_at: Optional[str]
    verified_by: Optional[str]
    approved_replacement_value_cents: int
    deductible_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ConsumableProduct(TypedDict):
    id: str
    sku: str
    name: str
    unit_price_cents: int
    pack_size: int
    requires_application_approval: bool
    created_at: str
    updated_at: str
    version: int


class ConsumableOrder(TypedDict):
    id: str
    account_id: str
    lines: List[dict]
    status: str
    total_cents: int
    submitted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SupportCase(TypedDict):
    id: str
    account_id: str
    kind: str
    jobsite_id: str
    scheduled_for: str
    approved_by_engineer_id: Optional[str]
    documentation_url: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class EndOfTermSettlement(TypedDict):
    id: str
    agreement_id: str
    option: str
    provisional_amount_cents: int
    final_amount_cents: Optional[int]
    finalized: bool
    created_at: str
