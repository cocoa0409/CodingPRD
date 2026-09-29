"""Domain types for the youth sports accident insurance program.

Status enums, role enum and entity TypedDicts. Every entity in this API carries
the common resource properties (``id``, ``created_at``, ``updated_at``,
``version``), so every TypedDict below declares all four.
"""
from enum import Enum
from typing import Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    PROGRAM_ADMINISTRATOR = "ProgramAdministrator"
    LEAGUE_ADMINISTRATOR = "LeagueAdministrator"
    LEAGUE_OFFICIAL = "LeagueOfficial"
    CLAIMS_EXAMINER = "ClaimsExaminer"
    MEDICAL_REVIEWER = "MedicalReviewer"
    GUARDIAN_PORTAL = "GuardianPortal"


class LeagueSanctioningStatus(str, Enum):
    SANCTIONED = "SANCTIONED"
    PROBATION = "PROBATION"
    SUSPENDED = "SUSPENDED"


class HazardClass(str, Enum):
    CLASS_1_LOW = "CLASS_1_LOW"
    CLASS_2_MODERATE = "CLASS_2_MODERATE"
    CLASS_3_HIGH = "CLASS_3_HIGH"
    CLASS_4_CONTACT = "CLASS_4_CONTACT"


class ServiceCategory(str, Enum):
    EMERGENCY_ROOM = "EMERGENCY_ROOM"
    SURGERY = "SURGERY"
    DIAGNOSTIC_IMAGING = "DIAGNOSTIC_IMAGING"
    PHYSICAL_THERAPY = "PHYSICAL_THERAPY"
    DENTAL = "DENTAL"
    AMBULANCE = "AMBULANCE"
    PHYSICIAN_OFFICE = "PHYSICIAN_OFFICE"


class LeaguePolicyStatus(str, Enum):
    QUOTED = "QUOTED"
    BOUND = "BOUND"
    ACTIVE = "ACTIVE"
    RUN_OFF = "RUN_OFF"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class CoveragePosture(str, Enum):
    OPEN = "OPEN"
    CLAIMS_REVIEW = "CLAIMS_REVIEW"
    FROZEN = "FROZEN"


class CoverageBasisElection(str, Enum):
    EXCESS_ONLY = "EXCESS_ONLY"
    FULL_EXCESS_PERMITTED = "FULL_EXCESS_PERMITTED"


class ExperienceTier(str, Enum):
    PREFERRED = "PREFERRED"
    STANDARD = "STANDARD"
    ADVERSE = "ADVERSE"
    DECLINE = "DECLINE"


class RenewalQuoteStatus(str, Enum):
    NONE = "NONE"
    QUOTED = "QUOTED"
    ACCEPTED = "ACCEPTED"


class RenewalLossExperienceBasis(str, Enum):
    INCURRED = "INCURRED"
    PAID_ONLY = "PAID_ONLY"


class RosterStatus(str, Enum):
    ROSTERED = "ROSTERED"
    INACTIVE = "INACTIVE"


class EnrollmentStatus(str, Enum):
    ENROLLED = "ENROLLED"
    WITHDRAWN = "WITHDRAWN"


class EnrollmentCoverageStatus(str, Enum):
    COVERED = "COVERED"
    LIFETIME_EXHAUSTED = "LIFETIME_EXHAUSTED"
    WITHDRAWN_NO_COVERAGE = "WITHDRAWN_NO_COVERAGE"


class FamilyPlanType(str, Enum):
    HMO = "HMO"
    PPO = "PPO"
    HDHP = "HDHP"
    MEDICAID = "MEDICAID"
    TRICARE = "TRICARE"


class FamilyPlanCoverageState(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class FamilyPlanVerificationStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    NO_COVERAGE_ATTESTED = "NO_COVERAGE_ATTESTED"


class ActivityType(str, Enum):
    PRACTICE = "PRACTICE"
    GAME = "GAME"
    SANCTIONED_TRAVEL = "SANCTIONED_TRAVEL"
    TRYOUT = "TRYOUT"
    TEAM_SOCIAL = "TEAM_SOCIAL"


class SanctionedActivityStatus(str, Enum):
    PENDING_SANCTION = "PENDING_SANCTION"
    SANCTIONED = "SANCTIONED"
    REJECTED = "REJECTED"


class ActivityRejectionReason(str, Enum):
    OFFICIAL_DECLINED = "OFFICIAL_DECLINED"
    POLICY_FROZEN = "POLICY_FROZEN"


class BodyPart(str, Enum):
    HEAD_NECK = "HEAD_NECK"
    SHOULDER_ARM = "SHOULDER_ARM"
    HAND_WRIST = "HAND_WRIST"
    TORSO = "TORSO"
    HIP_GROIN = "HIP_GROIN"
    KNEE = "KNEE"
    ANKLE_FOOT = "ANKLE_FOOT"
    DENTAL = "DENTAL"
    OTHER = "OTHER"


class SeverityTier(str, Enum):
    MINOR = "MINOR"
    MODERATE = "MODERATE"
    SEVERE = "SEVERE"
    CATASTROPHIC = "CATASTROPHIC"


class InjuryReportStatus(str, Enum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    RETURNED_FOR_CORRECTION = "RETURNED_FOR_CORRECTION"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class InjuryReportRejectionReason(str, Enum):
    OFFICIAL_DECLINED = "OFFICIAL_DECLINED"
    LIFETIME_BENEFIT_EXHAUSTED = "LIFETIME_BENEFIT_EXHAUSTED"
    ACTIVITY_NOT_SANCTIONED = "ACTIVITY_NOT_SANCTIONED"


class ClaimAdjudicationStatus(str, Enum):
    PENDING_COORDINATION = "PENDING_COORDINATION"
    UNDER_ADJUDICATION = "UNDER_ADJUDICATION"
    APPROVED = "APPROVED"
    PAID = "PAID"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class ClaimCoordinationStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    EOB_REQUESTED = "EOB_REQUESTED"
    EOB_RECEIVED = "EOB_RECEIVED"
    NO_OTHER_COVERAGE_CONFIRMED = "NO_OTHER_COVERAGE_CONFIRMED"
    EOB_WAIVED = "EOB_WAIVED"


class CoordinationBasis(str, Enum):
    EXCESS_OF_OTHER = "EXCESS_OF_OTHER"
    FULL_EXCESS = "FULL_EXCESS"


class CatCertificationStatus(str, Enum):
    NONE = "NONE"
    CERTIFIED = "CERTIFIED"
    REVOKED = "REVOKED"


class ClaimDenialReason(str, Enum):
    NO_BENEFIT_PAYABLE = "NO_BENEFIT_PAYABLE"
    ENROLLMENT_WITHDRAWN = "ENROLLMENT_WITHDRAWN"


class NetworkStatus(str, Enum):
    IN_NETWORK = "IN_NETWORK"
    OUT_OF_NETWORK = "OUT_OF_NETWORK"


class ProviderBillStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    REPRICED = "REPRICED"
    ADJUDICATED = "ADJUDICATED"
    DENIED = "DENIED"
    VOIDED = "VOIDED"


class CoordinationRecordStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class PayeeType(str, Enum):
    PROVIDER = "PROVIDER"
    FAMILY_REIMBURSEMENT = "FAMILY_REIMBURSEMENT"


class BenefitLayer(str, Enum):
    BASE = "BASE"
    CATASTROPHIC = "CATASTROPHIC"


class BenefitPaymentStatus(str, Enum):
    ISSUED = "ISSUED"
    VOIDED = "VOIDED"


class League(TypedDict):
    id: str
    name: str
    league_code: str
    state_code: str
    governing_body_code: str
    contact_email: str
    sanctioning_status: str
    in_force_policy_count: int
    created_at: str
    updated_at: str
    version: int


class SportClassification(TypedDict):
    id: str
    sport_code: str
    sport_name: str
    hazard_class: str
    base_rate_per_participant_cents: int
    deductible_cents: int
    per_injury_limit_cents: int
    cat_attachment_point_cents: int
    aggregate_limit_cents: int
    cat_lifetime_max_cents: int
    minimum_participants: int
    travel_buffer_minutes: int
    service_category_caps: Dict[str, int]
    hazard_load_bps: int
    created_at: str
    updated_at: str
    version: int


class LeaguePolicy(TypedDict):
    id: str
    league_id: str
    sport_classification_id: str
    term_effective_date: str
    term_expiration_date: str
    enrolled_participant_count: int
    coverage_basis_election: str
    cat_layer_elected: bool
    status: str
    coverage_posture: str
    cancel_reason: Optional[str]
    gross_premium_cents: int
    cat_layer_charge_cents: int
    premium_subtotal_cents: int
    volume_credit_bps: int
    volume_credit_cents: int
    annual_premium_cents: int
    deductible_cents: int
    per_injury_limit_cents: int
    cat_attachment_point_cents: int
    aggregate_limit_cents: int
    cat_lifetime_max_cents: int
    paid_loss_cents: int
    reserve_cents: int
    incurred_loss_cents: int
    open_claim_count: int
    incurred_loss_ratio_bps: int
    paid_loss_ratio_bps: int
    experience_tier: str
    renewal_quote_status: str
    renewal_loss_experience_basis: Optional[str]
    renewal_quote_effective_date: Optional[str]
    renewal_enrolled_participant_count: Optional[int]
    renewal_loss_ratio_bps: Optional[int]
    renewal_experience_tier: Optional[str]
    renewal_experience_modifier_bps: Optional[int]
    renewal_base_premium_cents: Optional[int]
    renewal_quoted_premium_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Participant(TypedDict):
    id: str
    league_id: str
    first_name: str
    last_name: str
    date_of_birth: str
    guardian_email: str
    guardian_phone: Optional[str]
    roster_status: str
    enrolled_policy_count: int
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict):
    id: str
    participant_id: str
    league_policy_id: str
    enrolled_on_date: str
    status: str
    withdrawn_on_date: Optional[str]
    lifetime_cat_benefit_used_cents: int
    coverage_status: str
    created_at: str
    updated_at: str
    version: int


class FamilyHealthPlan(TypedDict):
    id: str
    participant_id: str
    carrier_name: str
    policy_number: str
    plan_type: str
    individual_deductible_cents: int
    coinsurance_bps: int
    effective_date: str
    termination_date: Optional[str]
    coverage_state: str
    verification_status: str
    verified_at: Optional[str]
    verified_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SanctionedActivity(TypedDict):
    id: str
    league_policy_id: str
    activity_type: str
    venue_name: str
    starts_at: str
    ends_at: str
    travel_buffer_minutes: int
    status: str
    sanctioning_official_id: Optional[str]
    rejection_reason: Optional[str]
    is_covered_activity: bool
    created_at: str
    updated_at: str
    version: int


class InjuryReport(TypedDict):
    id: str
    enrollment_id: str
    sanctioned_activity_id: str
    injury_datetime: str
    body_part: str
    injury_description: str
    severity_tier: str
    reported_on_date: str
    days_to_report: int
    status: str
    correction_round_count: int
    correction_note: Optional[str]
    verifying_official_id: Optional[str]
    verified_at: Optional[str]
    official_attestation: Optional[str]
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict):
    id: str
    injury_report_id: str
    league_policy_id: str
    enrollment_id: str
    adjudication_status: str
    coordination_status: str
    eob_requested_at: Optional[str]
    coordination_basis: Optional[str]
    reserve_amount_cents: int
    allowed_amount_total_cents: int
    other_insurance_paid_cents: int
    deductible_applied_cents: int
    benefit_before_limit_cents: int
    base_layer_benefit_cents: int
    cat_layer_benefit_cents: int
    benefit_payable_cents: int
    paid_base_cents: int
    paid_cat_cents: int
    paid_to_date_cents: int
    balance_billed_total_cents: int
    family_responsibility_total_cents: int
    cat_certification_status: str
    cat_certified_at: Optional[str]
    cat_certified_by_user_id: Optional[str]
    cat_certification_note: Optional[str]
    cat_revocation_reason: Optional[str]
    adjudicated_at: Optional[str]
    adjudicated_by_user_id: Optional[str]
    denial_reason: Optional[str]
    withdrawal_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProviderBill(TypedDict):
    id: str
    claim_id: str
    provider_npi: str
    provider_name: str
    network_status: str
    service_category: str
    service_date: str
    billed_charge_cents: int
    fee_schedule_amount_cents: int
    negotiated_amount_cents: int
    scheduled_cap_cents: int
    allowed_amount_cents: int
    balance_billed_cents: int
    family_responsibility_cents: int
    other_plan_paid_cents: int
    status: str
    repriced_at: Optional[str]
    repriced_by_user_id: Optional[str]
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CoordinationRecord(TypedDict):
    id: str
    claim_id: str
    provider_bill_id: str
    family_health_plan_id: str
    eob_received_date: str
    other_plan_allowed_cents: int
    other_plan_paid_cents: int
    patient_responsibility_cents: int
    status: str
    superseded_by_record_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BenefitPayment(TypedDict):
    id: str
    claim_id: str
    provider_bill_id: str
    payee_type: str
    layer: str
    amount_cents: int
    status: str
    issued_at: Optional[str]
    issued_by_user_id: Optional[str]
    void_reason: Optional[str]
    voided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
