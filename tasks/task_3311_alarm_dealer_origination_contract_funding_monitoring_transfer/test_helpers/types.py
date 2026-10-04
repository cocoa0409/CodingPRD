"""Domain types: entity TypedDicts, status enums, role enum.

Entities that carry the common server-managed block (``id``/``created_at``/
``updated_at``/``version``) are declared in full. Append-only log rows are not
declared separately here: every persisted resource in this API carries the
common block per §2.5 of the PRD.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# ─── Enumerations ─────────────────────────────────────

class DealerStanding(str, Enum):
    ACTIVE = "ACTIVE"
    WATCH = "WATCH"
    SUSPENDED = "SUSPENDED"


class QualityTier(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


class SourceChannel(str, Enum):
    DIRECT = "DIRECT"
    DEALER = "DEALER"


class EquipmentConfigCode(str, Enum):
    BASE = "BASE"
    PREMIUM = "PREMIUM"
    ELITE = "ELITE"


class ContractStatus(str, Enum):
    PENDING_VALIDATION = "PENDING_VALIDATION"
    ACTIVE = "ACTIVE"
    DELINQUENT = "DELINQUENT"
    CANCELLED = "CANCELLED"
    ASSUMED = "ASSUMED"


class CancelledFromStatus(str, Enum):
    PENDING_VALIDATION = "PENDING_VALIDATION"
    ACTIVE = "ACTIVE"
    DELINQUENT = "DELINQUENT"


class PackageStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    FUNDED = "FUNDED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"


class CustomerStatus(str, Enum):
    PENDING_ACTIVATION = "PENDING_ACTIVATION"
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"
    ASSUMED = "ASSUMED"


class SiteOccupancyStatus(str, Enum):
    OCCUPIED = "OCCUPIED"
    VACATED = "VACATED"


class InstallStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ProvisionState(str, Enum):
    UNPROVISIONED = "UNPROVISIONED"
    PROVISIONED = "PROVISIONED"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class VerificationOutcome(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    FALSE_ALARM = "FALSE_ALARM"


class DispatchStatus(str, Enum):
    REQUESTED = "REQUESTED"
    DISPATCHED = "DISPATCHED"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"
    CLOSED = "CLOSED"


class ReductionActionType(str, Enum):
    WATCH = "WATCH"
    TRAINING_REQUIRED = "TRAINING_REQUIRED"
    SERVICE_REQUIRED = "SERVICE_REQUIRED"


class ReductionActionStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


class ServiceVisitStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SCHEDULED = "SCHEDULED"
    PERFORMED = "PERFORMED"
    CANCELLED = "CANCELLED"


class WorkType(str, Enum):
    REPAIR = "REPAIR"
    WARRANTY_REPAIR = "WARRANTY_REPAIR"


class BillingRoute(str, Enum):
    CUSTOMER = "CUSTOMER"
    DEALER_HOLDBACK = "DEALER_HOLDBACK"


class OwnershipStatus(str, Enum):
    CURRENT = "CURRENT"
    SUPERSEDED = "SUPERSEDED"


class AssumptionRequestStatus(str, Enum):
    PENDING_NEGOTIATION = "PENDING_NEGOTIATION"
    REJECTED = "REJECTED"
    ACCEPTED = "ACCEPTED"
    COMPLETED = "COMPLETED"


class RescissionRequestStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    CHANNEL_MANAGER = "ChannelManager"
    DEALER = "Dealer"
    FUNDING_ANALYST = "FundingAnalyst"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    MONITORING_OPERATOR = "MonitoringOperator"
    SERVICE_COORDINATOR = "ServiceCoordinator"
    CUSTOMER = "Customer"


# ─── Entity TypedDicts ────────────────────────────────

class Dealer(TypedDict):
    id: str
    dealer_code: str
    legal_name: str
    holdback_rate: float
    quality_tier: str
    standing: str
    chargeback_balance_due_cents: int
    holdback_reserve_cents: int
    funded_package_count: int
    chargeback_rate_12mo_sum: int
    funding_package_count_12mo: int
    created_at: str
    updated_at: str
    version: int


class Contract(TypedDict):
    id: str
    contract_number: Optional[str]
    source_channel: str
    dealer_id: Optional[str]
    customer_id: str
    dealer_package_id: Optional[str]
    equipment_config_code: str
    credit_score: int
    contract_term_months: int
    monthly_monitoring_cents: int
    capex_cents: int
    funding_amount_cents: int
    holdback_cents: int
    holdback_remaining_cents: int
    dealer_holdback_sweep_cents: int
    contract_status: str
    equipment_financed_cents: int
    financed_charge_at_apr_cents: int
    equipment_payment_cents: int
    post_warranty_cents: int
    warranty_months: int
    assumption_count: int
    funding_points: float
    attrition_checked_at: Optional[str]
    activated_at: Optional[str]
    cancelled_at: Optional[str]
    cancelled_from_status: Optional[str]
    chargeback_exempt: bool
    equipment_financing_disclosed: Optional[bool]
    validation_failure_code: Optional[str]
    monitoring_hold_until: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DealerPackage(TypedDict):
    id: str
    dealer_id: str
    package_reference: str
    submitted_at: Optional[str]
    package_status: str
    package_capex_cents: int
    package_holdback_cents: int
    package_funding_amount_cents: int
    funded_count: int
    declined_count: int
    submitted_contract_count: int
    expires_at: Optional[str]
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict):
    id: str
    full_name: str
    email: str
    phone: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Site(TypedDict):
    id: str
    contract_id: str
    address_line: str
    city: str
    state_code: str
    postal_code: str
    occupancy_status: str
    created_at: str
    updated_at: str
    version: int


class Installation(TypedDict):
    id: str
    contract_id: str
    scheduled_at: str
    duration_minutes: int
    installation_engineer_id: str
    install_status: str
    equipment_config_code: Optional[str]
    activation_committed: bool
    created_at: str
    updated_at: str
    version: int


class MonitoringAccount(TypedDict):
    id: str
    contract_id: str
    central_station_host: Optional[str]
    monitoring_account_number: Optional[str]
    provision_state: str
    activation_gate_met: bool
    created_at: str
    updated_at: str
    version: int


class AlarmEvent(TypedDict):
    id: str
    monitoring_account_id: str
    signal_source: str
    occurred_at: str
    entered_at_utc: str
    verification_outcome: str
    verified_at: Optional[str]
    counted_for_false_alarm: bool
    counted_for_window_total: bool
    created_at: str
    updated_at: str
    version: int


class DispatchRequest(TypedDict):
    id: str
    alarm_event_id: str
    dispatch_status: str
    requested_at: str
    dispatched_at: Optional[str]
    abort_reason: str
    created_at: str
    updated_at: str
    version: int


class AlarmReductionAction(TypedDict):
    id: str
    monitoring_account_id: str
    action_type: str
    triggered_at: str
    resolved_at: Optional[str]
    action_status: str
    created_at: str
    updated_at: str
    version: int


class AttritionSweep(TypedDict):
    id: str
    sweep_month: str
    ran_at: str
    evaluated_count: int
    delinquent_count: int
    resumed_count: int
    flagged_contract_ids: List[str]
    created_at: str
    updated_at: str
    version: int


class AttritionFlag(TypedDict):
    id: str
    attrition_sweep_id: str
    contract_id: str
    cohort_month: str
    flagged_at: str
    created_at: str
    updated_at: str
    version: int


class ServiceVisit(TypedDict):
    id: str
    contract_id: str
    scheduled_at: str
    duration_minutes: int
    work_type: str
    technician_id: str
    warranty_status_at_visit: Optional[bool]
    billing_route: Optional[str]
    billed_cents: int
    dealer_sweep_cents: int
    allowed_duration_minutes: int
    visit_status: str
    performed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ContractOwner(TypedDict):
    id: str
    contract_id: str
    customer_id: str
    ownership_status: str
    started_at: str
    ended_at: Optional[str]
    assumption_request_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AssumptionRequest(TypedDict):
    id: str
    contract_id: str
    incoming_customer_id: str
    incoming_credit_score: int
    residence_state_code: str
    request_status: str
    rejection_count: int
    accepted_at: Optional[str]
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RescissionRequest(TypedDict):
    id: str
    contract_id: str
    operator_id: str
    days_since_funding: int
    request_status: str
    approved_by: Optional[str]
    approved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int