"""Domain vocabulary for the Inland Marine Equipment Floater Underwriting API.

Every literal in this module is transcribed from the product requirements
document: the four rating territories, the nine policy statuses, the six
coverage part types, the eight contractors-equipment classes, the eight ledger
entry types and so on. Tests import these names instead of repeating bare
strings so that a vocabulary drift shows up as an import error rather than as a
silently mismatched assertion.

Ledger entries are the one resource that does not carry the four common
system-managed properties: a ledger entry is immutable once written, so it
carries only ``id`` and ``created_at``.
"""

from typing import Any, Dict, List, Optional

try:  # pragma: no cover - typing shim for older interpreters
    from typing import TypedDict
except ImportError:  # pragma: no cover
    from typing_extensions import TypedDict  # type: ignore


# ─── Roles ────────────────────────────────────────────────────────────────────

class Role:
    """The five roles the service recognises, spelled exactly as the header."""

    ACTUARY = "Actuary"
    UNDERWRITER = "Underwriter"
    UNDERWRITING_MANAGER = "UnderwritingManager"
    CLAIMS_ADJUSTER = "ClaimsAdjuster"
    POLICYHOLDER = "Policyholder"

    ALL = [ACTUARY, UNDERWRITER, UNDERWRITING_MANAGER, CLAIMS_ADJUSTER, POLICYHOLDER]


# ─── Territories ──────────────────────────────────────────────────────────────

class TerritoryCode:
    """The four rating territories every territory-valued field draws from."""

    T1_COASTAL = "T1_COASTAL"
    T2_URBAN = "T2_URBAN"
    T3_INLAND = "T3_INLAND"
    T4_REMOTE = "T4_REMOTE"

    ALL = [T1_COASTAL, T2_URBAN, T3_INLAND, T4_REMOTE]


# ─── Policy ───────────────────────────────────────────────────────────────────

class PolicyStatus:
    DRAFT = "DRAFT"
    QUOTED = "QUOTED"
    REFERRED = "REFERRED"
    DECLINED = "DECLINED"
    BOUND = "BOUND"
    IN_FORCE = "IN_FORCE"
    SUSPENDED = "SUSPENDED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"

    ALL = [DRAFT, QUOTED, REFERRED, DECLINED, BOUND, IN_FORCE, SUSPENDED,
           CANCELLED, EXPIRED]
    TERMINAL = [DECLINED, CANCELLED, EXPIRED]
    MUTABLE = [DRAFT, QUOTED, REFERRED, BOUND, IN_FORCE, SUSPENDED]


class ReferralStatus:
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"

    ALL = [NOT_REQUIRED, PENDING, APPROVED, DECLINED]


class ReferralDecision:
    APPROVE = "APPROVE"
    DECLINE = "DECLINE"


class CancellationReason:
    INSURED_REQUEST = "INSURED_REQUEST"
    NON_REPORTING = "NON_REPORTING"
    UNDERWRITING = "UNDERWRITING"

    ALL = [INSURED_REQUEST, NON_REPORTING, UNDERWRITING]


# ─── Coverage part ────────────────────────────────────────────────────────────

class PartType:
    SCHEDULED_EQUIPMENT = "SCHEDULED_EQUIPMENT"
    BLANKET_EQUIPMENT = "BLANKET_EQUIPMENT"
    RENTED_LEASED = "RENTED_LEASED"
    INSTALLATION_FLOATER = "INSTALLATION_FLOATER"
    TRANSIT = "TRANSIT"
    REPORTING_FORM = "REPORTING_FORM"

    ALL = [SCHEDULED_EQUIPMENT, BLANKET_EQUIPMENT, RENTED_LEASED,
           INSTALLATION_FLOATER, TRANSIT, REPORTING_FORM]
    EQUIPMENT_BEARING = [SCHEDULED_EQUIPMENT, BLANKET_EQUIPMENT, RENTED_LEASED,
                         REPORTING_FORM]


class ValuationBasis:
    ACV = "ACV"
    REPLACEMENT_COST = "REPLACEMENT_COST"
    AGREED_VALUE = "AGREED_VALUE"
    STATED_AMOUNT = "STATED_AMOUNT"

    ALL = [ACV, REPLACEMENT_COST, AGREED_VALUE, STATED_AMOUNT]
    STATED_VALUE_REQUIRED = [AGREED_VALUE, STATED_AMOUNT]


class RatingBasis:
    SCHEDULED = "SCHEDULED"
    BLANKET = "BLANKET"

    ALL = [SCHEDULED, BLANKET]


class CoveragePartStatus:
    ACTIVE = "ACTIVE"
    VOID = "VOID"

    ALL = [ACTIVE, VOID]


class ReportingFrequency:
    MONTHLY = "MONTHLY"
    QUARTERLY = "QUARTERLY"

    ALL = [MONTHLY, QUARTERLY]


# ─── Rate development ─────────────────────────────────────────────────────────

class EquipmentType:
    EXCAVATOR = "EXCAVATOR"
    CRANE = "CRANE"
    LOADER = "LOADER"
    DOZER = "DOZER"
    GENERATOR = "GENERATOR"
    COMPRESSOR = "COMPRESSOR"
    SCAFFOLDING = "SCAFFOLDING"
    SURVEY_INSTRUMENT = "SURVEY_INSTRUMENT"

    ALL = [EXCAVATOR, CRANE, LOADER, DOZER, GENERATOR, COMPRESSOR, SCAFFOLDING,
           SURVEY_INSTRUMENT]


class TheftHazardGrade:
    A = "A"
    B = "B"
    C = "C"
    D = "D"

    ALL = [A, B, C, D]


class RateRuleStatus:
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    RETIRED = "RETIRED"

    ALL = [DRAFT, PUBLISHED, RETIRED]


# ─── Equipment items ──────────────────────────────────────────────────────────

class Ownership:
    """Ownership of a scheduled unit."""

    OWNED = "OWNED"
    RENTED = "RENTED"
    LEASED = "LEASED"

    ALL = [OWNED, RENTED, LEASED]
    LOSS_OF_USE_ELIGIBLE = [RENTED, LEASED]


class EquipmentItemStatus:
    RATED = "RATED"
    ACTIVE = "ACTIVE"
    REMOVED = "REMOVED"
    TOTALED = "TOTALED"

    ALL = [RATED, ACTIVE, REMOVED, TOTALED]
    ON_RISK = [RATED, ACTIVE]


# ─── Jobsites ─────────────────────────────────────────────────────────────────

class JobsiteStatus:
    UNSURVEYED = "UNSURVEYED"
    SURVEYED = "SURVEYED"
    RELEASED = "RELEASED"

    ALL = [UNSURVEYED, SURVEYED, RELEASED]


class SecurityTier:
    TIER_0 = "TIER_0"
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"

    ALL = [TIER_0, TIER_1, TIER_2, TIER_3]


# ─── Installation floaters ────────────────────────────────────────────────────

class FloaterStatus:
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    TERMINATED_ACCEPTANCE = "TERMINATED_ACCEPTANCE"
    TERMINATED_OCCUPANCY = "TERMINATED_OCCUPANCY"
    EXPIRED = "EXPIRED"
    VOIDED = "VOIDED"

    ALL = [PENDING, ACTIVE, TERMINATED_ACCEPTANCE, TERMINATED_OCCUPANCY,
           EXPIRED, VOIDED]
    LIVE = [PENDING, ACTIVE]
    TERMINAL = [TERMINATED_ACCEPTANCE, TERMINATED_OCCUPANCY, EXPIRED, VOIDED]


class TerminationTrigger:
    ACCEPTANCE = "ACCEPTANCE"
    OCCUPANCY = "OCCUPANCY"
    EXPIRY = "EXPIRY"
    CANCELLATION = "CANCELLATION"

    ALL = [ACCEPTANCE, OCCUPANCY, EXPIRY, CANCELLATION]


class TerminationReason:
    """The two reasons a floater may be terminated by request."""

    ACCEPTANCE = "ACCEPTANCE"
    OCCUPANCY = "OCCUPANCY"

    ALL = [ACCEPTANCE, OCCUPANCY]


# ─── Transit ──────────────────────────────────────────────────────────────────

class VehicleOwnership:
    OWNED = "OWNED"
    HIRED = "HIRED"

    ALL = [OWNED, HIRED]


class VehicleStatus:
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    SUSPENDED = "SUSPENDED"

    ALL = [PENDING_APPROVAL, APPROVED, SUSPENDED]


class ShipmentStatus:
    PLANNED = "PLANNED"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    LOST = "LOST"
    CANCELLED = "CANCELLED"

    ALL = [PLANNED, IN_TRANSIT, DELIVERED, LOST, CANCELLED]
    OCCUPYING = [PLANNED, IN_TRANSIT]
    TERMINAL = [DELIVERED, LOST, CANCELLED]


class CatastropheTier:
    CAT_TIER_1 = "CAT_TIER_1"
    CAT_TIER_2 = "CAT_TIER_2"
    CAT_TIER_3 = "CAT_TIER_3"

    ALL = [CAT_TIER_1, CAT_TIER_2, CAT_TIER_3]


# ─── Reporting forms ──────────────────────────────────────────────────────────

class ValueReportStatus:
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    PENALIZED = "PENALIZED"
    DELINQUENT = "DELINQUENT"
    SUPERSEDED = "SUPERSEDED"

    ALL = [SUBMITTED, ACCEPTED, PENALIZED, DELINQUENT, SUPERSEDED]
    EARNING = [ACCEPTED, PENALIZED]


# ─── Claims ───────────────────────────────────────────────────────────────────

class AdjustmentStatus:
    OPEN = "OPEN"
    INSPECTED = "INSPECTED"
    REPAIR_APPROVED = "REPAIR_APPROVED"
    TOTAL_LOSS_DECLARED = "TOTAL_LOSS_DECLARED"
    SETTLED = "SETTLED"
    CLOSED = "CLOSED"

    ALL = [OPEN, INSPECTED, REPAIR_APPROVED, TOTAL_LOSS_DECLARED, SETTLED,
           CLOSED]
    SETTLEABLE = [REPAIR_APPROVED, TOTAL_LOSS_DECLARED]


class SalvageStatus:
    NOT_APPLICABLE = "NOT_APPLICABLE"
    PENDING = "PENDING"
    RECOVERED = "RECOVERED"
    WAIVED = "WAIVED"

    ALL = [NOT_APPLICABLE, PENDING, RECOVERED, WAIVED]


class LossType:
    THEFT = "THEFT"
    COLLISION = "COLLISION"
    FIRE = "FIRE"
    WINDSTORM = "WINDSTORM"
    VANDALISM = "VANDALISM"

    ALL = [THEFT, COLLISION, FIRE, WINDSTORM, VANDALISM]


class AdjustmentBasis:
    REPAIR = "REPAIR"
    TOTAL_LOSS = "TOTAL_LOSS"

    ALL = [REPAIR, TOTAL_LOSS]


# ─── Ledgers ──────────────────────────────────────────────────────────────────

class Ledger:
    PREMIUM = "PREMIUM"
    LOSS = "LOSS"

    ALL = [PREMIUM, LOSS]


class LedgerEntryType:
    INITIAL_PREMIUM = "INITIAL_PREMIUM"
    ENDORSEMENT_PREMIUM = "ENDORSEMENT_PREMIUM"
    ENDORSEMENT_RETURN = "ENDORSEMENT_RETURN"
    REPORTING_ADJUSTMENT = "REPORTING_ADJUSTMENT"
    LATE_REPORTING_PENALTY = "LATE_REPORTING_PENALTY"
    CANCELLATION_RETURN = "CANCELLATION_RETURN"
    CLAIM_SETTLEMENT = "CLAIM_SETTLEMENT"
    SALVAGE_RECOVERY = "SALVAGE_RECOVERY"

    ALL = [INITIAL_PREMIUM, ENDORSEMENT_PREMIUM, ENDORSEMENT_RETURN,
           REPORTING_ADJUSTMENT, LATE_REPORTING_PENALTY, CANCELLATION_RETURN,
           CLAIM_SETTLEMENT, SALVAGE_RECOVERY]
    PREMIUM_BOOK = [INITIAL_PREMIUM, ENDORSEMENT_PREMIUM, ENDORSEMENT_RETURN,
                    REPORTING_ADJUSTMENT, LATE_REPORTING_PENALTY,
                    CANCELLATION_RETURN]
    LOSS_BOOK = [CLAIM_SETTLEMENT, SALVAGE_RECOVERY]


# ─── Resource shapes ──────────────────────────────────────────────────────────
#
# Every resource except the ledger entry carries id, created_at, updated_at and
# version. The dicts below are declared total=False because most endpoints
# return the full resource while a computed read returns only its own fields.

class CommonFields(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int


class Policy(CommonFields, total=False):
    policyholder_name: str
    territory_code: str
    effective_date: str
    expiration_date: str
    term_days: int
    minimum_premium_cents: int
    status: str
    referral_status: str
    referral_required: bool
    referral_note: Optional[str]
    referred_by_user_id: Optional[str]
    referral_decided_by_user_id: Optional[str]
    cancellation_reason: Optional[str]
    cancel_effective_date: Optional[str]
    quoted_at: Optional[str]
    bound_at: Optional[str]
    in_force_at: Optional[str]
    occupancy_termination_count: int
    sum_of_part_premiums_cents: int
    scheduled_basis_premium_cents: int
    blanket_basis_premium_cents: int
    written_premium_cents: int
    premium_balance_cents: int
    incurred_loss_cents: int
    total_insured_value_cents: int


class CoveragePart(CommonFields, total=False):
    policy_id: str
    part_type: str
    valuation_basis: str
    rating_basis: str
    status: str
    deductible_cents: int
    aggregate_limit_cents: int
    aggregate_available_cents: int
    aggregate_paid_net_cents: int
    blanket_limit_cents: Optional[int]
    coinsurance_pct_bp: Optional[int]
    per_item_limit_cents: Optional[int]
    loss_of_use_daily_limit_cents: Optional[int]
    loss_of_use_max_days: Optional[int]
    transit_owned_limit_cents: Optional[int]
    transit_hired_limit_cents: Optional[int]
    catastrophe_limit_cents: Optional[int]
    reporting_frequency: Optional[str]
    reporting_annual_rate_bp: Optional[int]
    reporting_limit_cents: Optional[int]
    rated_premium_cents: int
    deposit_premium_cents: Optional[int]
    earned_reported_premium_cents: int
    latest_report_period_end_date: Optional[str]


class RateRule(CommonFields, total=False):
    equipment_type: str
    territory_code: str
    age_band_min_years: int
    age_band_max_years: int
    base_rate_bp: int
    theft_hazard_grade: str
    replacement_cost_index_bp: int
    status: str
    published_at: Optional[str]


class EquipmentItem(CommonFields, total=False):
    coverage_part_id: str
    description: str
    equipment_type: str
    model_year: int
    original_cost_cents: int
    ownership: str
    stated_value_cents: Optional[int]
    geo_tracker_installed: bool
    valuation_basis: str
    assigned_jobsite_id: Optional[str]
    status: str
    removed_at: Optional[str]
    applied_rate_rule_id: Optional[str]
    age_years_at_rating: int
    insured_value_cents: int
    applied_base_rate_bp: int
    applied_credit_bp: int
    rated_premium_cents: int


class Jobsite(CommonFields, total=False):
    name: str
    territory_code: str
    status: str
    fenced: bool
    lighting: bool
    alarm_monitored: bool
    guarded_24h: bool
    security_score: int
    security_tier: str
    active_floater_count: int
    surveyed_at: Optional[str]


class InstallationFloater(CommonFields, total=False):
    coverage_part_id: str
    jobsite_id: str
    project_name: str
    installed_value_limit_cents: int
    coverage_start_date: str
    coverage_end_date: str
    term_days: int
    status: str
    rated_premium_cents: int
    earned_premium_cents: int
    unearned_return_cents: int
    termination_trigger: Optional[str]
    termination_date: Optional[str]


class Vehicle(CommonFields, total=False):
    unit_label: str
    ownership: str
    per_conveyance_limit_cents: int
    carrier_name: Optional[str]
    approval_expires_on: Optional[str]
    status: str
    approved_at: Optional[str]
    in_transit_value_cents: int


class TransitShipment(CommonFields, total=False):
    coverage_part_id: str
    vehicle_id: str
    origin_territory_code: str
    destination_territory_code: str
    departure_at: str
    arrival_at: str
    declared_value_cents: int
    catastrophe_zone: bool
    applicable_limit_cents: int
    status: str
    departed_at: Optional[str]
    delivered_at: Optional[str]


class ValueReport(CommonFields, total=False):
    coverage_part_id: str
    period_start_date: str
    period_end_date: str
    period_days: int
    due_date: str
    reported_value_cents: int
    status: str
    submitted_at: Optional[str]
    period_earned_premium_cents: int
    late_penalty_cents: int
    superseded_by_report_id: Optional[str]


class Claim(CommonFields, total=False):
    policy_id: str
    coverage_part_id: str
    loss_date: str
    loss_type: str
    equipment_item_id: Optional[str]
    transit_shipment_id: Optional[str]
    installation_floater_id: Optional[str]
    adjustment_status: str
    salvage_status: str
    repair_estimate_cents: Optional[int]
    actual_value_at_loss_cents: Optional[int]
    valuation_at_loss_cents: Optional[int]
    constructive_total_loss_threshold_cents: Optional[int]
    claim_limit_cents: Optional[int]
    underreporting_factor_bp: int
    repair_basis_settlement_cents: Optional[int]
    total_loss_basis_settlement_cents: Optional[int]
    adjustment_basis: Optional[str]
    settlement_amount_cents: Optional[int]
    settlement_paid_cents: Optional[int]
    loss_of_use_days_claimed: int
    loss_of_use_paid_cents: int
    salvage_proceeds_cents: Optional[int]
    salvage_credit_cents: int
    inspected_by_user_id: Optional[str]
    declared_by_user_id: Optional[str]
    settled_by_user_id: Optional[str]


class LedgerEntry(TypedDict, total=False):
    """A ledger entry carries only id and created_at of the common properties."""

    id: str
    created_at: str
    policy_id: str
    claim_id: Optional[str]
    coverage_part_id: Optional[str]
    entry_type: str
    ledger: str
    amount_cents: int
    memo: str
    effective_date: str


# Field names that must never appear on a ledger entry representation.
LEDGER_ENTRY_FORBIDDEN_FIELDS = ["updated_at", "version"]

# The four system-managed properties every other resource carries.
COMMON_RESOURCE_FIELDS = ["id", "created_at", "updated_at", "version"]

JsonDict = Dict[str, Any]
JsonList = List[Dict[str, Any]]
