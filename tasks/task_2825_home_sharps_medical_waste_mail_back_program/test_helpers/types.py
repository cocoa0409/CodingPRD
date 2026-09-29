"""Domain types: status enums, role enum and entity TypedDicts for the
home-sharps mail-back program described by the PRD.

Two resources are append-only event records and therefore carry only `id` and
`created_at` (PRD 2.4): SponsorLedgerEntry and AutoShipRun. Their TypedDicts
deliberately omit `updated_at` and `version`.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles (PRD 2.1)
# --------------------------------------------------------------------------
class Role(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    SPONSOR_REPRESENTATIVE = "SponsorRepresentative"
    PATIENT = "Patient"
    LOGISTICS_COORDINATOR = "LogisticsCoordinator"
    INTAKE_TECHNICIAN = "IntakeTechnician"
    DESTRUCTION_OFFICER = "DestructionOfficer"


ALL_ROLES = [r.value for r in Role]


# --------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------
class HouseholdSharpsClassification(str, Enum):
    REGULATED_MEDICAL_WASTE = "REGULATED_MEDICAL_WASTE"
    CONDITIONALLY_EXEMPT = "CONDITIONALLY_EXEMPT"
    HOUSEHOLD_EXEMPT = "HOUSEHOLD_EXEMPT"


class PostalService(str, Enum):
    USPS_PARCEL_SELECT_MAILBACK = "USPS_PARCEL_SELECT_MAILBACK"
    UPS_GROUND_MEDICAL = "UPS_GROUND_MEDICAL"


class HazardClass(str, Enum):
    UN3291_SHARPS_ONLY = "UN3291_SHARPS_ONLY"
    UN3291_REGULATED_MEDICAL_WASTE = "UN3291_REGULATED_MEDICAL_WASTE"


class ContainerSize(str, Enum):
    ONE_QUART = "ONE_QUART"
    TWO_GALLON = "TWO_GALLON"
    THREE_GALLON = "THREE_GALLON"
    EIGHT_GALLON = "EIGHT_GALLON"


class PackagingSpecStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class TreatmentFacilityStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class SponsorType(str, Enum):
    MANUFACTURER = "MANUFACTURER"
    HEALTH_PLAN = "HEALTH_PLAN"


class SponsorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class SponsorshipProgramStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"


class LedgerEntryType(str, Enum):
    RESERVATION = "RESERVATION"
    RESERVATION_RELEASE = "RESERVATION_RELEASE"
    COMMITMENT = "COMMITMENT"
    COMMITMENT_REVERSAL = "COMMITMENT_REVERSAL"
    FUNDING_ADJUSTMENT = "FUNDING_ADJUSTMENT"


class TherapyType(str, Enum):
    INSULIN_PEN_NEEDLES = "INSULIN_PEN_NEEDLES"
    INSULIN_SYRINGES = "INSULIN_SYRINGES"
    AUTOINJECTOR_PENS = "AUTOINJECTOR_PENS"
    INFUSION_SETS = "INFUSION_SETS"
    LANCETS_ONLY = "LANCETS_ONLY"


class PatientStatus(str, Enum):
    PENDING_ELIGIBILITY = "PENDING_ELIGIBILITY"
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"
    ENROLLED = "ENROLLED"
    SUSPENDED = "SUSPENDED"
    WITHDRAWN = "WITHDRAWN"


class EnrollmentStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_SPONSOR_APPROVAL = "PENDING_SPONSOR_APPROVAL"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    REJECTED = "REJECTED"
    TERMINATED = "TERMINATED"


class KitStatus(str, Enum):
    ISSUED = "ISSUED"
    ACTIVE_FILLING = "ACTIVE_FILLING"
    SEALED = "SEALED"
    IN_TRANSIT = "IN_TRANSIT"
    RECEIVED = "RECEIVED"
    RETURNED_TO_PATIENT = "RETURNED_TO_PATIENT"
    DESTROYED = "DESTROYED"
    VOIDED = "VOIDED"


class ReturnLabelStatus(str, Enum):
    PRINTED = "PRINTED"
    ACTIVATED = "ACTIVATED"
    VOIDED = "VOIDED"


class TransportStatus(str, Enum):
    TENDERED = "TENDERED"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    LOST = "LOST"


class ConformanceStatus(str, Enum):
    UNSCREENED = "UNSCREENED"
    CONFORMING = "CONFORMING"
    NON_CONFORMING = "NON_CONFORMING"
    REMEDIATED = "REMEDIATED"


class TransportEventType(str, Enum):
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    LOST = "LOST"


class NonConformanceReasonCode(str, Enum):
    UNAPPROVED_WASTE_TYPE = "UNAPPROVED_WASTE_TYPE"
    LOOSE_SHARPS_IN_BOX = "LOOSE_SHARPS_IN_BOX"
    UNSEALED_CONTAINER = "UNSEALED_CONTAINER"
    OVERFILLED_CONTAINER = "OVERFILLED_CONTAINER"
    WEIGHT_EXCEEDS_SPEC = "WEIGHT_EXCEEDS_SPEC"
    MISSING_ABSORBENT = "MISSING_ABSORBENT"


class NonConformanceStatus(str, Enum):
    OPEN = "OPEN"
    CUSTOMER_NOTIFIED = "CUSTOMER_NOTIFIED"
    RESOLVED = "RESOLVED"


class NotificationChannel(str, Enum):
    EMAIL = "EMAIL"
    PHONE = "PHONE"
    POSTAL_MAIL = "POSTAL_MAIL"


class RemediationAction(str, Enum):
    RETURN_TO_PATIENT = "RETURN_TO_PATIENT"
    ON_SITE_REPACK = "ON_SITE_REPACK"
    DISPOSE_AS_RMW = "DISPOSE_AS_RMW"


class DestructionCertificateStatus(str, Enum):
    ISSUED = "ISSUED"
    VOIDED = "VOIDED"


class KitVoidReason(str, Enum):
    SUPERSEDED_BY_REPLACEMENT = "SUPERSEDED_BY_REPLACEMENT"
    SHIPMENT_LOST = "SHIPMENT_LOST"
    ENROLLMENT_PAUSED = "ENROLLMENT_PAUSED"
    ENROLLMENT_TERMINATED = "ENROLLMENT_TERMINATED"


# --------------------------------------------------------------------------
# Entity shapes
# --------------------------------------------------------------------------
class StateSharpsRule(TypedDict):
    id: str
    state_code: str
    household_sharps_classification: str
    mail_back_permitted: bool
    max_container_volume_liters: float
    certificate_retention_years: int
    requires_state_manifest: bool
    notification_deadline_hours: int
    created_at: str
    updated_at: str
    version: int


class PackagingSpec(TypedDict):
    id: str
    spec_code: str
    un_specification_code: str
    postal_service: str
    hazard_class: str
    max_gross_weight_grams: int
    allowed_container_sizes: List[str]
    requires_absorbent: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class TreatmentFacility(TypedDict):
    id: str
    name: str
    state_rule_id: str
    permit_number: str
    accepted_hazard_classes: List[str]
    daily_intake_capacity_units: int
    pending_intake_units: int
    destroyed_units_total: int
    certificates_issued_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Sponsor(TypedDict):
    id: str
    legal_name: str
    sponsor_type: str
    contact_email: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SponsorshipProgram(TypedDict):
    id: str
    sponsor_id: str
    program_code: str
    funding_ceiling_cents: int
    per_kit_allowance_cents: int
    reserved_cents: int
    committed_cents: int
    available_cents: int
    kits_issued_count: int
    kits_settled_count: int
    provisional_total_cents: int
    final_total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SponsorLedgerEntry(TypedDict):
    """Append-only accounting record: carries only `id` and `created_at` as
    system fields (PRD 2.4)."""
    id: str
    sponsorship_program_id: str
    kit_id: Optional[str]
    entry_type: str
    amount_cents: int
    sequence_no: int
    reserved_after_cents: int
    committed_after_cents: int
    available_after_cents: int
    memo: Optional[str]
    created_at: str


class Patient(TypedDict):
    id: str
    full_name: str
    state_rule_id: str
    therapy_type: str
    weekly_sharps_count: int
    contact_email: str
    status: str
    screening_risk_score: int
    audit_risk_score: int
    suspended_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict):
    id: str
    patient_id: str
    sponsorship_program_id: str
    cadence_days: int
    kits_authorized: int
    requested_container_size: Optional[str]
    kits_issued: int
    next_autoship_due_date: Optional[str]
    activated_at: Optional[str]
    sponsor_decision_note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Kit(TypedDict):
    id: str
    enrollment_id: str
    required_units: int
    container_size: str
    capacity_units: int
    volume_liters: float
    provisional_cost_cents: int
    fill_units: Optional[int]
    sealed_gross_weight_grams: Optional[int]
    issued_at: str
    acknowledged_at: Optional[str]
    seal_deadline_date: str
    supersedes_kit_id: Optional[str]
    auto_ship_run_id: Optional[str]
    void_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ReturnLabel(TypedDict):
    id: str
    kit_id: str
    packaging_spec_id: str
    postal_service: str
    tracking_number: str
    valid_from: str
    valid_until: str
    activated_at: Optional[str]
    voided_at: Optional[str]
    void_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict):
    id: str
    kit_id: str
    return_label_id: str
    treatment_facility_id: str
    scheduled_intake_date: str
    declared_gross_weight_grams: int
    observed_gross_weight_grams: Optional[int]
    state_manifest_number: Optional[str]
    custody_units: int
    tendered_at: str
    delivered_at: Optional[str]
    screened_by_user_id: Optional[str]
    transport_status: str
    conformance_status: str
    created_at: str
    updated_at: str
    version: int


class NonConformanceEvent(TypedDict):
    id: str
    shipment_id: str
    reason_code: str
    notification_deadline_at: str
    notified_at: Optional[str]
    notification_channel: Optional[str]
    remediation_action: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DestructionCertificate(TypedDict):
    id: str
    shipment_id: str
    kit_id: str
    treatment_facility_id: str
    certificate_number: str
    issued_by_user_id: str
    destroyed_units: int
    destruction_date: str
    retention_until_date: str
    final_kit_cost_cents: int
    rebate_pct_applied: float
    void_reason: Optional[str]
    voided_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AutoShipRun(TypedDict):
    """Append-only run record: carries only `id` and `created_at` as system
    fields (PRD 2.4)."""
    id: str
    as_of_date: str
    run_at: str
    enrollments_evaluated: int
    kits_created: int
    kits_skipped_not_due: int
    kits_skipped_risk: int
    kits_skipped_unfilled: int
    kits_skipped_funding: int
    created_kit_ids: List[str]
    created_at: str
