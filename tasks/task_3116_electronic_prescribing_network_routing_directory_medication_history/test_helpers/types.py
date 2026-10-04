"""Domain types for the electronic prescribing network: status enums, role enum,
and entity TypedDicts.

Every resource in this API carries a system-minted `id`, `created_at`, `updated_at`
and `version` (PRD §2.5), so every entity below is a full common-field resource.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Enumerations ─────────────────────────────────────

class ParticipantType(str, Enum):
    PRESCRIBER_CLINIC = "PRESCRIBER_CLINIC"
    PHARMACY = "PHARMACY"
    PAYER = "PAYER"
    HUB = "HUB"


class CertificationStatus(str, Enum):
    UNCERTIFIED = "UNCERTIFIED"
    IN_CERTIFICATION = "IN_CERTIFICATION"
    CERTIFIED = "CERTIFIED"
    SUSPENDED = "SUSPENDED"


class CertificationTestCode(str, Enum):
    CONNECTIVITY = "CONNECTIVITY"
    SCRIPT_NEW_RX = "SCRIPT_NEW_RX"
    SCRIPT_REFILL = "SCRIPT_REFILL"
    SCRIPT_CHANGE_CANCEL = "SCRIPT_CHANGE_CANCEL"
    MED_HISTORY = "MED_HISTORY"
    BENEFIT_COST = "BENEFIT_COST"
    ELIGIBILITY_FORMULARY = "ELIGIBILITY_FORMULARY"


class TestOutcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class VolumeBillingMode(str, Enum):
    MONTHLY = "MONTHLY"
    ROLLING_90_DAY = "ROLLING_90_DAY"


class FallbackChannel(str, Enum):
    FAX = "FAX"
    PRINT = "PRINT"


class DeliveryReachability(str, Enum):
    FULL = "FULL"
    AT_RISK = "AT_RISK"
    UNREACHABLE = "UNREACHABLE"


class ServiceSet(str, Enum):
    NEW_RX = "NEW_RX"
    REFILL_RX = "REFILL_RX"
    CHANGE_CANCEL = "CHANGE_CANCEL"
    MED_HISTORY = "MED_HISTORY"
    BENEFIT_COST = "BENEFIT_COST"
    ELIGIBILITY_FORMULARY = "ELIGIBILITY_FORMULARY"


class EndpointRole(str, Enum):
    SENDER = "SENDER"
    RECEIVER = "RECEIVER"
    BOTH = "BOTH"


class ServiceLevel(str, Enum):
    ELIGIBLE_A = "ELIGIBLE_A"
    ELIGIBLE_B = "ELIGIBLE_B"
    ELIGIBLE_C = "ELIGIBLE_C"


class MessageStandard(str, Enum):
    NCPDP_SCRIPT_2017071 = "NCPDP_SCRIPT_2017071"
    NCPDP_SCRIPT_2022011 = "NCPDP_SCRIPT_2022011"


class EndpointStatus(str, Enum):
    PENDING_CERT = "PENDING_CERT"
    ACTIVE = "ACTIVE"
    DEGRADED = "DEGRADED"
    DISABLED = "DISABLED"


class TransactionType(str, Enum):
    NEW_RX = "NEW_RX"
    REFILL_REQUEST = "REFILL_REQUEST"
    REFILL_RESPONSE = "REFILL_RESPONSE"
    CHANGE_REQUEST = "CHANGE_REQUEST"
    CHANGE_RESPONSE = "CHANGE_RESPONSE"
    CANCEL_REQUEST = "CANCEL_REQUEST"
    CANCEL_RESPONSE = "CANCEL_RESPONSE"


class ControlledSchedule(str, Enum):
    NON_CONTROLLED = "NON_CONTROLLED"
    SCHEDULE_II = "SCHEDULE_II"
    SCHEDULE_III = "SCHEDULE_III"
    SCHEDULE_IV = "SCHEDULE_IV"
    SCHEDULE_V = "SCHEDULE_V"


class ClinicalStatus(str, Enum):
    DRAFT = "DRAFT"
    SIGNED = "SIGNED"
    ROUTED = "ROUTED"
    DELIVERED = "DELIVERED"
    UNDELIVERABLE = "UNDELIVERABLE"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class RoutingStatus(str, Enum):
    NOT_ROUTED = "NOT_ROUTED"
    ROUTING = "ROUTING"
    ROUTED = "ROUTED"
    BACKUP_SELECTION = "BACKUP_SELECTION"
    FALLBACK_PENDING = "FALLBACK_PENDING"
    FALLBACK_SENT = "FALLBACK_SENT"
    ROUTE_FAILED = "ROUTE_FAILED"


class Significance(str, Enum):
    STANDARD = "STANDARD"
    CRITICAL = "CRITICAL"


class IdentityProofingStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    PASSED = "PASSED"
    FAILED = "FAILED"


class TwoFactorStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    PENDING = "PENDING"
    PASSED = "PASSED"
    LOCKED = "LOCKED"
    FAILED = "FAILED"


class SessionStatus(str, Enum):
    OPEN = "OPEN"
    SIGNED = "SIGNED"
    ABANDONED = "ABANDONED"


class AttemptOutcome(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    REJECTED = "REJECTED"
    UNDELIVERABLE = "UNDELIVERABLE"


class AttemptChannel(str, Enum):
    NETWORK = "NETWORK"
    FAX = "FAX"
    PRINT = "PRINT"


class ConsentScope(str, Enum):
    MEDICATION_HISTORY = "MEDICATION_HISTORY"
    BENEFIT_CHECK = "BENEFIT_CHECK"
    BOTH = "BOTH"


class ConsentStatus(str, Enum):
    NONE = "NONE"
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class BatchStatus(str, Enum):
    PENDING = "PENDING"
    AGGREGATING = "AGGREGATING"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"


class BatchTriggerReason(str, Enum):
    PRESCRIBER_QUERY = "PRESCRIBER_QUERY"
    CONSENT_GRANT = "CONSENT_GRANT"
    SCHEDULED_REFRESH = "SCHEDULED_REFRESH"


class HistorySourceType(str, Enum):
    PHARMACY_FILL = "PHARMACY_FILL"
    PAYER_CLAIM = "PAYER_CLAIM"


class FormularyStatus(str, Enum):
    UNKNOWN = "UNKNOWN"
    PREFERRED = "PREFERRED"
    NON_PREFERRED = "NON_PREFERRED"
    NOT_COVERED = "NOT_COVERED"
    PRIOR_AUTH_REQUIRED = "PRIOR_AUTH_REQUIRED"


class CoverageStatus(str, Enum):
    UNKNOWN = "UNKNOWN"
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class CheckStatus(str, Enum):
    PENDING = "PENDING"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"


class PricingVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class FeeDirection(str, Enum):
    SENT = "SENT"
    RECEIVED = "RECEIVED"


class FeeEntryStatus(str, Enum):
    PARTIAL = "PARTIAL"
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class FeeEntryType(str, Enum):
    CHARGE = "CHARGE"
    CORRECTION = "CORRECTION"
    MANUAL_REVERSAL = "MANUAL_REVERSAL"


class FeeTier(str, Enum):
    FREE = "FREE"
    STANDARD = "STANDARD"
    VOLUME = "VOLUME"


class UserRole(str, Enum):
    NETWORK_OPERATOR = "NetworkOperator"
    PARTICIPANT_ADMIN = "ParticipantAdmin"
    PRESCRIBER = "Prescriber"
    PHARMACY = "Pharmacy"
    HUB_OPERATOR = "HubOperator"
    PATIENT_SERVICE = "PatientService"


# ─── Entity TypedDicts (all resources carry the full common field set) ───

class NetworkParticipant(TypedDict):
    id: str
    name: str
    participant_type: str
    npi: str
    certification_status: str
    certification_tests_passed: List[str]
    volume_billing_mode: str
    directory_listed: bool
    delivery_reachability: str
    open_route_attempt_count: int
    fallback_channel: str
    fax_number: Optional[str]
    plan_copay_cents: int
    plan_coinsurance_pct: float
    plan_deductible_cents: int
    plan_deductible_met_cents: int
    plan_brand_fee_cents: int
    formulary_preferred_pct: float
    plan_benefit_cap_cents: int
    created_at: str
    updated_at: str
    version: int


class DirectoryEndpoint(TypedDict):
    id: str
    participant_id: str
    service_set: str
    endpoint_role: str
    service_level: str
    sla_response_minutes: int
    message_standard: str
    effective_from: str
    effective_to: Optional[str]
    status: str
    reported_attempt_count: int
    acknowledged_count: int
    reliability_ratio: float
    reliability_ratio_ewma: float
    created_at: str
    updated_at: str
    version: int


class Prescription(TypedDict):
    id: str
    prescriber_id: str
    receiving_pharmacy_id: str
    patient_id: str
    drug_ndc: str
    transaction_type: str
    controlled_schedule: str
    message_standard: str
    days_supply: int
    quantity: int
    refills_authorized: int
    refills_used: int
    is_controlled: bool
    clinical_status: str
    routing_status: str
    significance: str
    monitored_under_consent: bool
    routing_attempt_count: int
    routed_endpoint_id: Optional[str]
    active_routing_attempt_id: Optional[str]
    signature_audit_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SigningSession(TypedDict):
    id: str
    prescription_id: str
    prescriber_id: str
    opened_at: str
    identity_proofing_status: str
    two_factor_status: str
    otp_challenge_code: Optional[str]
    otp_attempt_count: int
    session_status: str
    signed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RoutingAttempt(TypedDict):
    id: str
    prescription_id: str
    attempt_no: int
    channel: str
    target_endpoint_id: Optional[str]
    outcome: str
    failure_code: Optional[str]
    error_code_returned: Optional[str]
    reported_at: Optional[str]
    correction_entry_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Patient(TypedDict):
    id: str
    full_name: str
    date_of_birth: str
    home_state: str
    covered_plan_payer_id: Optional[str]
    discard_on_revoke: bool
    consent_status: str
    consent_version: int
    history_record_count: int
    created_at: str
    updated_at: str
    version: int


class PatientConsent(TypedDict):
    id: str
    patient_id: str
    scope: str
    duration_days: int
    status: str
    granted_at: str
    expires_at: str
    revoked_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MedicationHistoryBatch(TypedDict):
    id: str
    patient_id: str
    trigger_reason: str
    status: str
    subscription_generation: int
    consent_version_snapshot: int
    source_record_count: int
    record_count: int
    superseded_count: int
    batch_cost_cents: int
    created_at: str
    updated_at: str
    version: int


class MedicationHistoryRecord(TypedDict):
    id: str
    patient_id: str
    source_type: str
    source_participant_id: str
    drug_ndc: str
    fill_date: str
    days_supply: int
    quantity: int
    dedupe_key: str
    is_superseded: bool
    aggregation_batch_id: Optional[str]
    retracted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BenefitCheck(TypedDict):
    id: str
    prescription_id: str
    patient_id: str
    payer_id: str
    benchmark_price_cents: int
    formulary_status: str
    coverage_status: str
    check_status: str
    pricing_variant: str
    deductible_met_snapshot_cents: int
    estimated_patient_pay_cents: int
    estimated_plan_pay_cents: int
    created_at: str
    updated_at: str
    version: int


class TransactionFeeEntry(TypedDict):
    id: str
    participant_id: str
    month_key: str
    transaction_type: str
    direction: str
    transaction_count: int
    fee_tier: str
    fee_cents: int
    status: str
    entry_type: str
    previous_count: Optional[int]
    new_count: Optional[int]
    reversal_of_entry_id: Optional[str]
    reversal_entry_id: Optional[str]
    period_net_total_cents: int
    created_at: str
    updated_at: str
    version: int