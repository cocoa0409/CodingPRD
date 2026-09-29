"""TypedDicts and status vocabularies for the EPR reporting domain (PRD 2.4, 3).

Every one of the twelve resource types carries the common fields `id`,
`created_at`, `updated_at` and `version`, so each entity TypedDict extends
CommonFields.
"""

from typing import Any, Dict, List, Optional, TypedDict


class UserRole:
    PROGRAM_REGULATOR = "ProgramRegulator"
    PRODUCER_COMPLIANCE_OFFICER = "ProducerComplianceOfficer"
    PRO_ADMINISTRATOR = "ProAdministrator"
    INDEPENDENT_VERIFIER = "IndependentVerifier"


ALL_ROLES = [
    UserRole.PROGRAM_REGULATOR,
    UserRole.PRODUCER_COMPLIANCE_OFFICER,
    UserRole.PRO_ADMINISTRATOR,
    UserRole.INDEPENDENT_VERIFIER,
]


class ProducerStatus:
    DRAFT = "DRAFT"
    OBLIGATION_DETERMINED = "OBLIGATION_DETERMINED"


class ObligatedPartyRole:
    UNDETERMINED = "UNDETERMINED"
    BRAND_OWNER = "BRAND_OWNER"
    IMPORTER = "IMPORTER"
    DOMESTIC_LICENSOR = "DOMESTIC_LICENSOR"
    NOT_OBLIGATED = "NOT_OBLIGATED"


class SkuStatus:
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"


class ComponentStatus:
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class ObligationBasis:
    ENTITY_LEVEL = "ENTITY_LEVEL"
    GROUP_LEVEL = "GROUP_LEVEL"


class EcoModPolicy:
    BONUS_MALUS = "BONUS_MALUS"
    DISCOUNT_ONLY = "DISCOUNT_ONLY"


class FeeRoundingOrder:
    PER_LINE_THEN_SUM = "PER_LINE_THEN_SUM"
    SUM_THEN_ROUND = "SUM_THEN_ROUND"


class FeeScheduleStatus:
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class RegistrationStatus:
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class ExemptionStatus:
    UNDETERMINED = "UNDETERMINED"
    OBLIGATED = "OBLIGATED"
    EXEMPT_SMALL_PRODUCER = "EXEMPT_SMALL_PRODUCER"
    EXEMPT_CATEGORY = "EXEMPT_CATEGORY"


class CompliancePosture:
    UNDETERMINED = "UNDETERMINED"
    COMPLIANT = "COMPLIANT"
    AT_RISK = "AT_RISK"
    DELINQUENT = "DELINQUENT"


class MembershipStatus:
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    PROBATION = "PROBATION"
    REJECTED = "REJECTED"
    TERMINATED = "TERMINATED"


class FeePaymentStatus:
    OUTSTANDING = "OUTSTANDING"
    PAID = "PAID"


class SubmissionStatus:
    DRAFT = "DRAFT"
    BLOCKED = "BLOCKED"
    SUBMITTED = "SUBMITTED"
    UNDER_VERIFICATION = "UNDER_VERIFICATION"
    VERIFIED = "VERIFIED"
    CORRECTION_REQUIRED = "CORRECTION_REQUIRED"
    FINALIZED = "FINALIZED"
    REJECTED = "REJECTED"


class ReportFeeStatus:
    UNASSESSED = "UNASSESSED"
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"
    INVOICED = "INVOICED"
    VOIDED = "VOIDED"


class FeeVariant:
    NONE = "NONE"
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class EngagementStatus:
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    OPINION_ISSUED = "OPINION_ISSUED"


class Opinion:
    UNQUALIFIED = "UNQUALIFIED"
    QUALIFIED = "QUALIFIED"
    ADVERSE = "ADVERSE"


class InvoiceStatus:
    ISSUED = "ISSUED"
    VOID = "VOID"


class UnitsBasis:
    BASELINE_UNITS = "BASELINE_UNITS"
    PROJECTED_UNITS = "PROJECTED_UNITS"


class SuspensionReason:
    PRODUCER_REDETERMINATION_REQUIRED = "PRODUCER_REDETERMINATION_REQUIRED"


class DecisionReason:
    SUPERSEDED_BY_NEW_MEMBERSHIP = "SUPERSEDED_BY_NEW_MEMBERSHIP"
    REGISTRATION_REJECTED = "REGISTRATION_REJECTED"
    REGISTRATION_WITHDRAWN = "REGISTRATION_WITHDRAWN"


class VoidReason:
    REPORT_CORRECTION_REQUIRED = "REPORT_CORRECTION_REQUIRED"


class CommonFields(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


class PackagingComponent(TypedDict, total=False):
    component_seq: int
    material_type: str
    unit_weight_grams: float
    recyclability_class: str
    pcr_content_pct: int
    is_reusable: bool
    status: str


class MaterialRate(TypedDict, total=False):
    material_type: str
    tier_min_kg: float
    tier_max_kg: Optional[float]
    rate_cents_per_kg: int


class Producer(CommonFields, total=False):
    legal_name: str
    parent_producer_id: Optional[str]
    brand_owner_flag: bool
    importer_of_record_flag: bool
    domestic_licensor_flag: bool
    annual_gross_revenue_usd: int
    contact_email: str
    status: str
    obligated_party_role: str
    annual_packaging_weight_kg: float
    determination_stale: bool
    assessed_fee_balance_cents: int


class Sku(CommonFields, total=False):
    producer_id: str
    gtin: str
    name: str
    product_category: str
    units_sold_annual_estimate: int
    components: List[PackagingComponent]
    unit_packaging_weight_grams: float
    status: str
    revision_count: int


class StateProgram(CommonFields, total=False):
    state_code: str
    obligation_basis: str
    eco_mod_policy: str
    fee_rounding_order: str
    small_producer_revenue_threshold_usd: int
    small_producer_tonnage_threshold_kg: float
    exempt_product_categories: List[str]
    verification_required_threshold_kg: float
    registration_deadline: str


class ReportingPeriod(CommonFields, total=False):
    state_program_id: str
    period_label: str
    data_start: str
    data_end: str
    submission_open: str
    submission_deadline: str
    correction_window_days: int


class Pro(CommonFields, total=False):
    name: str
    contact_email: str


class FeeSchedule(CommonFields, total=False):
    pro_id: str
    state_program_id: str
    effective_from: str
    effective_to: Optional[str]
    membership_fee_cents: int
    admin_fee_bps_low: int
    admin_fee_bps_high: int
    material_rates: List[MaterialRate]
    status: str


class Registration(CommonFields, total=False):
    producer_id: str
    state_program_id: str
    status: str
    exemption_status: str
    exemption_basis_applied: Optional[str]
    assessed_group_revenue_usd: Optional[int]
    assessed_group_weight_kg: Optional[float]
    reported_weight_kg_ytd: float
    compliance_posture: str
    suspension_reason: Optional[str]
    submitted_at: Optional[str]


class Membership(CommonFields, total=False):
    registration_id: str
    pro_id: str
    fee_schedule_id: str
    status: str
    membership_fee_cents: int
    fee_payment_status: str
    fee_schedule_version_pinned: Optional[int]
    decision_reason: Optional[str]


class PackagingReport(CommonFields, total=False):
    registration_id: str
    reporting_period_id: str
    submission_status: str
    fee_status: str
    total_weight_kg: float
    fee_basis_weight_kg: float
    tier_basis_kg: Optional[float]
    fee_subtotal_cents: int
    fee_variant_applied: Optional[str]
    verification_required: bool
    correction_round: int
    correction_due_at: Optional[str]
    submitted_by_user_id: Optional[str]
    line_count: int


class ReportLine(CommonFields, total=False):
    packaging_report_id: str
    sku_id: str
    units_sold: int
    line_weight_kg: float
    fee_exempt: bool
    line_fee_exact_cents: float
    line_fee_cents: int
    eco_mod_detail: List[Dict[str, Any]]


class VerificationEngagement(CommonFields, total=False):
    packaging_report_id: str
    verifier_user_id: str
    assigned_by_user_id: str
    fieldwork_start: str
    fieldwork_end: str
    status: str
    opinion: Optional[str]
    findings_note: Optional[str]
    round_index: int
    opinion_issued_at: Optional[str]


class Invoice(CommonFields, total=False):
    packaging_report_id: str
    membership_id: str
    fee_subtotal_cents: int
    admin_fee_bps_applied: int
    admin_fee_cents: int
    total_cents: int
    status: str
    void_reason: Optional[str]
