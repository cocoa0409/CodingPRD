"""Domain types for the Portable Restroom Rental API.

Entity shapes and enumerations exactly as named by the PRD. Money fields are
integers denominated in whole cents; gallons, unit counts and density
percentages are likewise integers.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ─── Roles ────────────────────────────────────────────────────────────────

class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    SALES_REP = "SalesRep"
    PERMIT_COORDINATOR = "PermitCoordinator"
    DISPATCH_PLANNER = "DispatchPlanner"
    DRIVER_OPERATOR = "DriverOperator"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    CUSTOMER_CONTACT = "CustomerContact"


ALL_SEVEN_ROLES = [
    UserRole.PLATFORM_ADMIN.value,
    UserRole.SALES_REP.value,
    UserRole.PERMIT_COORDINATOR.value,
    UserRole.DISPATCH_PLANNER.value,
    UserRole.DRIVER_OPERATOR.value,
    UserRole.COMPLIANCE_OFFICER.value,
    UserRole.CUSTOMER_CONTACT.value,
]


# ─── Enumerations ─────────────────────────────────────────────────────────

class AccountType(str, Enum):
    CONSTRUCTION = "CONSTRUCTION"
    EVENT = "EVENT"
    MUNICIPAL = "MUNICIPAL"


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class AccessClass(str, Enum):
    OPEN_LOT = "OPEN_LOT"
    GATED = "GATED"
    STAIR_ACCESS = "STAIR_ACCESS"
    CRANE_ONLY = "CRANE_ONLY"


class SitePermitStatus(str, Enum):
    NONE = "NONE"
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class SitePosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    BLOCKED = "BLOCKED"


class PermitKind(str, Enum):
    PLACEMENT = "PLACEMENT"
    RIGHT_OF_WAY = "RIGHT_OF_WAY"


class PermitFilingStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class UnitClass(str, Enum):
    STANDARD_PORTABLE = "STANDARD_PORTABLE"
    ADA_PORTABLE = "ADA_PORTABLE"
    HANDWASH_STATION = "HANDWASH_STATION"
    TRAILER_2STALL = "TRAILER_2STALL"
    TRAILER_8STALL = "TRAILER_8STALL"


class AssetUnitStatus(str, Enum):
    IN_YARD = "IN_YARD"
    DEPLOYED = "DEPLOYED"
    IN_REPAIR = "IN_REPAIR"
    RETIRED = "RETIRED"


class WasteClass(str, Enum):
    GREYWATER = "GREYWATER"
    BLACKWATER = "BLACKWATER"
    MIXED = "MIXED"


class DisposalSiteStatus(str, Enum):
    ACCEPTING = "ACCEPTING"
    CLOSED = "CLOSED"


class ServiceDay(str, Enum):
    MON = "MON"
    TUE = "TUE"
    WED = "WED"
    THU = "THU"
    FRI = "FRI"
    SAT = "SAT"
    SUN = "SUN"


class RouteStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ContractKind(str, Enum):
    EVENT = "EVENT"
    CONSTRUCTION = "CONSTRUCTION"


class SeasonCode(str, Enum):
    PEAK = "PEAK"
    SHOULDER = "SHOULDER"
    OFF = "OFF"


class ConstructionPhase(str, Enum):
    SITEWORK = "SITEWORK"
    VERTICAL = "VERTICAL"
    FINISHES = "FINISHES"
    EVENT_NA = "EVENT_NA"


class FulfillmentState(str, Enum):
    DRAFT = "DRAFT"
    QUOTED = "QUOTED"
    ACTIVE = "ACTIVE"
    DEMOBILIZED = "DEMOBILIZED"
    CLOSED = "CLOSED"


class BillingState(str, Enum):
    UNBILLED = "UNBILLED"
    INVOICED = "INVOICED"
    REBILL_REQUIRED = "REBILL_REQUIRED"
    SETTLED = "SETTLED"


class QuoteVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    RECONCILED = "RECONCILED"


class ScheduleState(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class VisitKind(str, Enum):
    SETUP = "SETUP"
    SERVICE = "SERVICE"
    TEARDOWN = "TEARDOWN"
    RERUN = "RERUN"


class VisitState(str, Enum):
    PLANNED = "PLANNED"
    EN_ROUTE = "EN_ROUTE"
    SERVICED = "SERVICED"
    MISSED = "MISSED"
    CANCELLED = "CANCELLED"
    RERUN_SCHEDULED = "RERUN_SCHEDULED"


class ManifestState(str, Enum):
    OPEN = "OPEN"
    SEALED = "SEALED"
    ACCEPTED = "ACCEPTED"


class ChargeKind(str, Enum):
    DAMAGE = "DAMAGE"
    TIP_OVER = "TIP_OVER"
    RELOCATION = "RELOCATION"
    MISSED_SERVICE_CREDIT = "MISSED_SERVICE_CREDIT"


class ChargeSeverity(str, Enum):
    MINOR = "MINOR"
    MODERATE = "MODERATE"
    TOTAL_LOSS = "TOTAL_LOSS"


class ChargeState(str, Enum):
    ASSESSED = "ASSESSED"
    DISPUTED = "DISPUTED"
    UPHELD = "UPHELD"
    WAIVED = "WAIVED"


class DeploymentState(str, Enum):
    RESERVED = "RESERVED"
    DEPLOYED = "DEPLOYED"
    RETURNED = "RETURNED"


# ─── Entity shapes ────────────────────────────────────────────────────────
# Every collection carries id, created_at, updated_at and version, with the
# single exception of QuoteLine, which carries only id and created_at.

class RentalAccount(TypedDict):
    id: str
    legal_name: str
    account_type: str
    credit_terms_days: int
    status: str
    open_credit_balance_cents: int
    billing_hold: bool
    created_at: str
    updated_at: str
    version: int


class ServiceSite(TypedDict):
    id: str
    account_id: str
    site_label: str
    jurisdiction_code: str
    access_class: str
    right_of_way_required: bool
    gate_open_minute: int
    gate_close_minute: int
    max_truck_length_ft: int
    deployed_unit_count: int
    permit_status: str
    site_posture: str
    created_at: str
    updated_at: str
    version: int


class PlacementPermit(TypedDict):
    id: str
    site_id: str
    permit_kind: str
    authority_ref: str
    effective_from: str
    effective_to: str
    status: str
    revision_round: int
    rejection_reason: Optional[str]
    submitted_by_user_id: Optional[str]
    authority_decision_ref: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AssetUnit(TypedDict):
    id: str
    asset_tag: str
    unit_class: str
    yard_code: str
    tare_length_ft: int
    status: str
    damage_strikes: int
    tip_over_count: int
    created_at: str
    updated_at: str
    version: int


class DisposalSite(TypedDict):
    id: str
    site_code: str
    daily_gallon_cap: int
    accepted_waste_classes: List[str]
    status: str
    committed_gallons_today: int
    created_at: str
    updated_at: str
    version: int


class Route(TypedDict):
    id: str
    route_code: str
    service_day: str
    truck_capacity_units: int
    waste_capacity_gallons: int
    status: str
    committed_units: int
    density_planned_pct: int
    density_realized_pct: int
    last_run_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RentalContract(TypedDict):
    id: str
    account_id: str
    site_id: str
    contract_kind: str
    term_start: str
    term_end: str
    headcount: int
    event_duration_hours: int
    service_frequency_per_week: int
    season_code: str
    construction_phase: str
    ada_required: bool
    fulfillment_state: str
    billing_state: str
    quoted_cents: int
    reconciled_cents: int
    invoice_subtotal_cents: int
    charge_debits_cents: int
    credit_accrued_cents: int
    net_billable_cents: int
    created_at: str
    updated_at: str
    version: int


class QuoteLine(TypedDict):
    """Immutable pricing artefact: it carries only id and created_at."""
    id: str
    contract_id: str
    quote_variant: str
    unit_class: str
    quantity: int
    unit_rate_cents: int
    extended_cents: int
    escalated_cents: int
    is_superseded: bool
    created_at: str


class UnitDeployment(TypedDict):
    id: str
    contract_id: str
    asset_unit_id: str
    site_id: str
    deploy_from: str
    deploy_to: str
    state: str
    relocation_count: int
    created_at: str
    updated_at: str
    version: int


class ServiceSchedule(TypedDict):
    id: str
    contract_id: str
    route_id: str
    service_day: str
    window_start_minute: int
    window_end_minute: int
    units_on_route: int
    state: str
    created_at: str
    updated_at: str
    version: int


class ServiceVisit(TypedDict):
    id: str
    schedule_id: str
    route_id: str
    visit_kind: str
    scheduled_date: str
    window_start_minute: int
    window_end_minute: int
    state: str
    gallons_pumped: int
    units_serviced: int
    missed_reason: Optional[str]
    rerun_of_visit_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WasteManifest(TypedDict):
    id: str
    route_id: str
    disposal_site_id: str
    manifest_date: str
    waste_class: str
    gallons_total: int
    state: str
    created_at: str
    updated_at: str
    version: int


class ChargeEvent(TypedDict):
    id: str
    contract_id: str
    asset_unit_id: Optional[str]
    charge_kind: str
    severity: Optional[str]
    amount_cents: int
    state: str
    assessed_by_user_id: str
    assessed_at: str
    resolved_by_user_id: Optional[str]
    dispute_reason: Optional[str]
    resolution_note: Optional[str]
    source_visit_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
