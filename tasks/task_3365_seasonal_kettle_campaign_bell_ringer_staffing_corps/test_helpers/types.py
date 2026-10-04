"""Domain types: entity TypedDicts, status enums, role enum.

All thirteen top-level resources carry the four system-managed properties
described in PRD §2.5 (id, created_at, updated_at, version), so every
TypedDict below declares them.
"""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    TERRITORIAL_COMMANDER = "TerritorialCommander"
    DIVISIONAL_OFFICER = "DivisionalOfficer"
    CORPS_OFFICER = "CorpsOfficer"
    KETTLE_COORDINATOR = "KettleCoordinator"
    VOLUNTEER_COORDINATOR = "VolunteerCoordinator"
    BELL_RINGER = "BellRinger"
    COUNTING_ROOM_TELLER = "CountingRoomTeller"
    FINANCE_OFFICER = "FinanceOfficer"
    ASSISTANCE_CASEWORKER = "AssistanceCaseworker"
    PROGRAM_DIRECTOR = "ProgramDirector"
    DISASTER_SERVICES_COORDINATOR = "DisasterServicesCoordinator"
    DIGITAL_GIVING_PROCESSOR = "DigitalGivingProcessor"
    HOST_SITE_MANAGER = "HostSiteManager"


class UnitType(str, Enum):
    CORPS = "CORPS"
    DIVISION = "DIVISION"
    AREA_COMMAND = "AREA_COMMAND"
    TERRITORY = "TERRITORY"


class CampaignStatus(str, Enum):
    PLANNING = "PLANNING"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class PermissionStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class ExclusivityScope(str, Enum):
    EXCLUSIVE = "EXCLUSIVE"
    NON_EXCLUSIVE = "NON_EXCLUSIVE"


class KettleLocationStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class Placement(str, Enum):
    INDOOR = "INDOOR"
    OUTDOOR = "OUTDOOR"
    DRIVE_THROUGH = "DRIVE_THROUGH"


class PerformanceTier(str, Enum):
    UNRATED = "UNRATED"
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"
    PLATINUM = "PLATINUM"


class RingerType(str, Enum):
    VOLUNTEER = "VOLUNTEER"
    PAID_SEASONAL = "PAID_SEASONAL"


class ScreeningStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    PENDING = "PENDING"
    CLEARED = "CLEARED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"


class EngagementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    SEPARATED = "SEPARATED"


class ShiftStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class ShiftKind(str, Enum):
    REGULAR = "REGULAR"
    RELIEF = "RELIEF"
    DOUBLE = "DOUBLE"


class DepositStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    VARIANCE_HOLD = "VARIANCE_HOLD"
    DEPOSITED = "DEPOSITED"
    RECONCILED = "RECONCILED"


class GivingChannel(str, Enum):
    QR = "QR"
    SMS = "SMS"
    TERMINAL = "TERMINAL"
    ONLINE = "ONLINE"


class AttributionStatus(str, Enum):
    RECEIVED = "RECEIVED"
    UNATTRIBUTED = "UNATTRIBUTED"
    ATTRIBUTED = "ATTRIBUTED"
    REVERSED = "REVERSED"


class ProgramType(str, Enum):
    TOY = "TOY"
    FOOD = "FOOD"
    COAT = "COAT"
    HYGIENE = "HYGIENE"


class AssistanceProgramStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class EligibilityStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    SCREENING = "SCREENING"
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"
    WAITLISTED = "WAITLISTED"
    APPROVED = "APPROVED"
    DISTRIBUTION_SCHEDULED = "DISTRIBUTION_SCHEDULED"
    DISTRIBUTED = "DISTRIBUTED"
    NO_SHOW = "NO_SHOW"


class DistributionStatus(str, Enum):
    NOT_SCHEDULED = "NOT_SCHEDULED"
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"


class CorpsProgramCategory(str, Enum):
    YOUTH = "YOUTH"
    SENIOR = "SENIOR"
    WORSHIP = "WORSHIP"
    COMMUNITY = "COMMUNITY"


class CorpsProgramStatus(str, Enum):
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    COMPLETED = "COMPLETED"


class IncidentCommandLevel(str, Enum):
    TYPE_1 = "TYPE_1"
    TYPE_2 = "TYPE_2"
    TYPE_3 = "TYPE_3"
    TYPE_4 = "TYPE_4"
    TYPE_5 = "TYPE_5"


class DeploymentStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    STAGED = "STAGED"
    DEPLOYED = "DEPLOYED"
    DEMOBILIZED = "DEMOBILIZED"
    DENIED = "DENIED"
    CANCELLED = "CANCELLED"


class ReallocationStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    APPLIED = "APPLIED"
    REJECTED = "REJECTED"


# common_fields: true — carries id + created_at + updated_at + version
class Unit(TypedDict):
    id: str
    name: str
    unit_type: str
    parent_unit_id: Optional[str]
    territory_code: str
    canteen_pool_size: int
    committed_canteen_count: int
    oversight_level: int
    created_at: str
    updated_at: str
    version: int


class Campaign(TypedDict):
    id: str
    name: str
    season_year: int
    starts_on: str
    ends_on: str
    status: str
    goal_cents: int
    labor_budget_cents: int
    total_raised_cents: int
    labor_committed_cents: int
    active_location_count: int
    created_at: str
    updated_at: str
    version: int


class HostSite(TypedDict):
    id: str
    campaign_id: str
    retailer_name: str
    store_number: str
    city: str
    state_code: str
    permission_status: str
    permission_starts_on: str
    permission_ends_on: str
    exclusivity_scope: str
    max_kettles: int
    active_kettle_count: int
    created_at: str
    updated_at: str
    version: int


class KettleLocation(TypedDict):
    id: str
    host_site_id: str
    campaign_id: str
    location_code: str
    placement: str
    status: str
    placement_starts_on: str
    placement_ends_on: str
    daily_required_minutes: int
    covered_minutes: int
    location_total_cents: int
    cents_per_hour: int
    performance_tier: str
    created_at: str
    updated_at: str
    version: int


class BellRinger(TypedDict):
    id: str
    full_name: str
    email: str
    ringer_type: str
    corps_id: str
    date_of_birth: str
    screening_status: str
    screening_expires_at: Optional[str]
    engagement_status: str
    reliability_score: int
    hourly_rate_cents: int
    scheduled_hours: float
    created_at: str
    updated_at: str
    version: int


class Shift(TypedDict):
    id: str
    kettle_location_id: str
    bell_ringer_id: str
    starts_at: str
    ends_at: str
    break_minutes: int
    shift_kind: str
    status: str
    paid_hours: float
    paid_amount_cents: int
    checked_in_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class KettleCollection(TypedDict):
    id: str
    kettle_location_id: str
    collected_on: str
    declared_cents: int
    coin_cents: int
    currency_cents: int
    check_cents: int
    counted_total_cents: int
    variance_cents: int
    handling_fee_cents: int
    deposit_status: str
    deposited_cents: int
    deposit_reference: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DigitalGiving(TypedDict):
    id: str
    kettle_location_id: Optional[str]
    campaign_id: str
    unit_id: str
    amount_cents: int
    channel: str
    occurred_at: str
    external_ref: str
    attribution_status: str
    attributed_cents: int
    reversed_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AssistanceProgram(TypedDict):
    id: str
    campaign_id: str
    name: str
    program_type: str
    intake_opens_on: str
    intake_closes_on: str
    household_cap: int
    per_household_limit_cents: int
    status: str
    accepted_application_count: int
    created_at: str
    updated_at: str
    version: int


class AssistanceApplication(TypedDict):
    id: str
    program_id: str
    applicant_name: str
    household_size: int
    annual_income_cents: int
    verified_income_cents: int
    eligibility_status: str
    provisional_score: int
    eligibility_score: int
    distribution_site_unit_id: Optional[str]
    distribution_scheduled_at: Optional[str]
    distribution_slot_minutes: int
    distribution_status: str
    pickup_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CorpsProgram(TypedDict):
    id: str
    unit_id: str
    name: str
    category: str
    capacity: int
    waitlist_enabled: bool
    status: str
    enrolled_count: int
    waitlist_count: int
    meeting_pattern: str
    created_at: str
    updated_at: str
    version: int


class DisasterDeployment(TypedDict):
    id: str
    unit_id: str
    incident_name: str
    incident_command_level: str
    requested_canteens: int
    command_authority: str
    status: str
    assigned_canteen_count: int
    deployed_at: Optional[str]
    demobilized_at: Optional[str]
    deployment_cost_cents: int
    created_at: str
    updated_at: str
    version: int


class ReallocationDecision(TypedDict):
    id: str
    campaign_id: str
    from_location_id: str
    to_location_id: str
    moved_hours: float
    effective_on: str
    rationale: str
    status: str
    expected_lift_cents: int
    applied_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CampaignSummary(TypedDict):
    campaign_id: str
    status: str
    goal_cents: int
    total_raised_cents: int
    collections_counted_cents: int
    digital_attributed_cents: int
    attainment_pct: int
    active_location_count: int
    labor_committed_cents: int
    labor_budget_cents: int


class LocationPerformance(TypedDict):
    location_id: str
    location_total_cents: int
    covered_minutes: int
    covered_hours: int
    cents_per_hour: int
    performance_index: int
    performance_tier: str
    coverage_pct: int
    understaffed: bool
