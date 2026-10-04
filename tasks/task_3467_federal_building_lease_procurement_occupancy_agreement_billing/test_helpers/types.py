"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.6, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    GSA_ADMIN = "GSAAdmin"
    GSA_LEASING_OFFICER = "GSALeasingOfficer"
    GSA_PROPERTY_MANAGER = "GSAPropertyManager"
    AGENCY_MANAGER = "AgencyManager"
    LESSOR_REP = "LessorRep"


class AgencyStatus(str, Enum):
    ACTIVE = "ACTIVE"


class OwnershipType(str, Enum):
    FEDERALLY_OWNED = "FEDERALLY_OWNED"
    LEASED_STOCK = "LEASED_STOCK"


class BuildingStatus(str, Enum):
    ACTIVE = "ACTIVE"
    UNDER_CONSTRUCTION = "UNDER_CONSTRUCTION"


class RequirementStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    NEEDS_REVISION = "NEEDS_REVISION"
    VALIDATED = "VALIDATED"
    SOLICITING = "SOLICITING"
    AWARDED = "AWARDED"


class DeliveryMethod(str, Enum):
    STANDARD = "STANDARD"
    NEW_CONSTRUCTION = "NEW_CONSTRUCTION"


class NeedType(str, Enum):
    SCIF = "SCIF"
    LAB = "LAB"
    WAREHOUSE = "WAREHOUSE"
    SECURE_STORAGE = "SECURE_STORAGE"


class OfferStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_EVALUATION = "UNDER_EVALUATION"
    SELECTED = "SELECTED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class RejectionReason(str, Enum):
    AUTO_NOT_SELECTED = "AUTO_NOT_SELECTED"
    WITHDRAWN_BY_LESSOR = "WITHDRAWN_BY_LESSOR"


class EscalationMethod(str, Enum):
    BASE_YEAR_STOP = "BASE_YEAR_STOP"
    CPI_INDEXED = "CPI_INDEXED"


class LeaseStatus(str, Enum):
    AWARDED = "AWARDED"
    COMMENCED = "COMMENCED"
    EXPIRING = "EXPIRING"
    EXPIRED = "EXPIRED"
    SUCCEEDED = "SUCCEEDED"


class TiAmortMethod(str, Enum):
    ANNUITY = "ANNUITY"
    STRAIGHT_LINE = "STRAIGHT_LINE"


class ExpirationOption(str, Enum):
    SUCCEEDING_LEASE = "SUCCEEDING_LEASE"
    RELOCATION = "RELOCATION"
    REPLACEMENT_CONSTRUCTION = "REPLACEMENT_CONSTRUCTION"


class PlanStatus(str, Enum):
    OPEN = "OPEN"
    OPTION_SELECTED = "OPTION_SELECTED"
    EXECUTED = "EXECUTED"
    CANCELLED = "CANCELLED"


class OaStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"


class PricingSource(str, Enum):
    LEASE_PASS_THROUGH = "LEASE_PASS_THROUGH"
    OWNED_MARKET = "OWNED_MARKET"


class BillStatus(str, Enum):
    ISSUED = "ISSUED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"


class AlterationStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ESTIMATED = "ESTIMATED"
    APPROVED = "APPROVED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class FundingMethod(str, Enum):
    LUMP_SUM = "LUMP_SUM"
    AMORTIZED = "AMORTIZED"


class LumpChargeStatus(str, Enum):
    NONE = "NONE"
    PENDING = "PENDING"
    BILLED = "BILLED"
    REVERSED = "REVERSED"


class TicketStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    VERIFIED = "VERIFIED"


class TicketCategory(str, Enum):
    MAINTENANCE = "MAINTENANCE"
    SECURITY = "SECURITY"
    CLEANING = "CLEANING"


class TicketSeverity(str, Enum):
    CRITICAL = "CRITICAL"
    ROUTINE = "ROUTINE"


class SurveyStatus(str, Enum):
    RECORDED = "RECORDED"
    FINALIZED = "FINALIZED"


class SurveyMethod(str, Enum):
    SPACE_BASED = "SPACE_BASED"
    HEADCOUNT_BASED = "HEADCOUNT_BASED"


class ReductionStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    EXECUTED = "EXECUTED"


# All entities carry the standard system-managed fields (PRD §2.6):
# id, created_at, updated_at, version.

class Agency(TypedDict, total=False):
    id: str
    bureau_code: str
    name: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Building(TypedDict, total=False):
    id: str
    building_name: str
    address: str
    region_code: str
    ownership_type: str
    security_capability: int
    total_sf: int
    available_sf: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SpaceRequirement(TypedDict, total=False):
    id: str
    agency_id: str
    title: str
    base_headcount: int
    annual_growth_pct: float
    target_occupancy_year: int
    sf_per_person: int
    special_needs: list
    region_code: str
    mission_points: int
    population_points: int
    size_points: int
    criticality_points: int
    status: str
    projected_headcount: Optional[int]
    required_security_level: Optional[int]
    required_usable_sf: Optional[int]
    survey_summary: Optional[str]
    delivery_method: str
    source_plan_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LeaseOffer(TypedDict, total=False):
    id: str
    requirement_id: str
    building_id: str
    lessor_name: str
    shell_rate_per_sf_yr_cents: int
    operating_rate_per_sf_yr_cents: int
    base_year_tax_per_sf_yr_cents: int
    escalation_method: str
    ti_allowance_per_sf_cents: int
    free_rent_months: int
    term_years: int
    valid_until: str
    status: str
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Lease(TypedDict, total=False):
    id: str
    requirement_id: str
    building_id: str
    offer_id: str
    agency_id: str
    succeeds_lease_id: Optional[str]
    shell_rate_per_sf_yr_cents: int
    operating_rate_per_sf_yr_cents: int
    base_year_tax_per_sf_yr_cents: int
    escalation_method: str
    free_rent_months: int
    term_months: int
    leased_sf: int
    ti_allowance_total_cents: int
    status: str
    awarded_date: str
    commencement_date: Optional[str]
    end_date: Optional[str]
    ti_buildout_cost_cents: Optional[int]
    ti_amort_method: Optional[str]
    cpi_base_index: Optional[float]
    ti_amortized_principal_cents: Optional[int]
    ti_schedule_monthly_cents: List[int]
    tax_statements: list
    current_tax_per_sf_yr_cents: int
    current_cpi_index: Optional[float]
    executed_option: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExpirationPlan(TypedDict, total=False):
    id: str
    lease_id: str
    status: str
    selected_option: Optional[str]
    option_costs: list
    recommended_option: Optional[str]
    cost_params: dict
    outcome_lease_id: Optional[str]
    outcome_requirement_id: Optional[str]
    outcome_building_id: Optional[str]
    executed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OccupancyAgreement(TypedDict, total=False):
    id: str
    lease_id: Optional[str]
    building_id: Optional[str]
    agency_id: str
    assigned_sf: int
    start_date: str
    end_date: str
    shell_equivalent_rate_per_sf_yr_cents: Optional[int]
    operating_rate_per_sf_yr_cents: Optional[int]
    pricing_source: str
    status: str
    pending_service_credit_cents: int
    receivable_outstanding_cents: int
    terminal_writeoff_cents: int
    amendment_history: list
    created_at: str
    updated_at: str
    version: int


class RentBill(TypedDict, total=False):
    id: str
    oa_id: str
    billing_month: str
    shell_cents: int
    operating_cents: int
    tax_escalation_cents: int
    ti_amortization_cents: int
    alteration_amortization_cents: int
    lump_sum_charges_cents: int
    abatement_credit_cents: int
    fee_cents: int
    service_credit_applied_cents: int
    total_cents: int
    amount_paid_cents: int
    payments: list
    status: str
    created_at: str
    updated_at: str
    version: int


class AlterationRequest(TypedDict, total=False):
    id: str
    oa_id: str
    title: str
    description: str
    scope_sf: int
    status: str
    estimated_cost_cents: Optional[int]
    work_start_date: Optional[str]
    work_end_date: Optional[str]
    funding_method: Optional[str]
    completion_date: Optional[str]
    amortization_months: Optional[int]
    monthly_amort_cents: Optional[int]
    amortization_start_month: Optional[str]
    amortization_balance_cents: Optional[float]
    lump_charge_status: str
    created_at: str
    updated_at: str
    version: int


class ServiceTicket(TypedDict, total=False):
    id: str
    building_id: str
    reported_oa_id: str
    category: str
    severity: str
    description: str
    status: str
    sla_hours: int
    resolved_at: Optional[str]
    verified_at: Optional[str]
    sla_breached: Optional[bool]
    credit_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class UtilizationSurvey(TypedDict, total=False):
    id: str
    oa_id: str
    method: str
    measured_headcount: int
    utilized_sf: int
    measured_at: str
    status: str
    utilization_rate: Optional[float]
    recommended_release_sf: Optional[int]
    reduction_action_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SpaceReductionAction(TypedDict, total=False):
    id: str
    oa_id: str
    survey_id: str
    recommended_release_sf: int
    status: str
    executed_release_sf: Optional[int]
    executed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
