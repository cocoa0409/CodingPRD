"""Domain types for the Implant Device UDI Tracking service.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.  Every one of the fourteen persisted resource types carries the
same four common properties (`id`, `created_at`, `updated_at`, `version`), so
every TypedDict below lists all four.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ─── Roles ────────────────────────────────────────────────────────────────

class UserRole(str, Enum):
    RECEIVING_TECH = "ReceivingTech"
    INVENTORY_LEAD = "InventoryLead"
    CIRC_CLINICIAN = "CircClinician"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    REVENUE_INTEGRITY_ANALYST = "RevenueIntegrityAnalyst"
    VENDOR_REP = "VendorRep"


ALL_ROLES = [r.value for r in UserRole]


# ─── Status enums ─────────────────────────────────────────────────────────

class VendorStanding(str, Enum):
    ACTIVE = "ACTIVE"
    HOLD = "HOLD"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"


class BillingTrigger(str, Enum):
    ON_IMPLANT = "ON_IMPLANT"
    ON_RECEIPT = "ON_RECEIPT"


class ReconciliationMethod(str, Enum):
    UNIT_MATCH = "UNIT_MATCH"
    PERIOD_TRUEUP = "PERIOD_TRUEUP"


class CatalogCategory(str, Enum):
    HIGH_COST_IMPLANT = "HIGH_COST_IMPLANT"
    STANDARD_IMPLANT = "STANDARD_IMPLANT"
    ACCESSORY = "ACCESSORY"


class LotStatus(str, Enum):
    QUARANTINE = "QUARANTINE"
    AVAILABLE = "AVAILABLE"
    RECALLED = "RECALLED"
    EXPIRED = "EXPIRED"
    DEPLETED = "DEPLETED"


class CustodyState(str, Enum):
    QUARANTINED = "QUARANTINED"
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    IMPLANTED = "IMPLANTED"
    EXPLANTED = "EXPLANTED"
    RECALL_HOLD = "RECALL_HOLD"
    EXPIRED = "EXPIRED"
    WASTED = "WASTED"
    RETURNED_TO_VENDOR = "RETURNED_TO_VENDOR"
    DISPOSED = "DISPOSED"


class BillingState(str, Enum):
    NOT_BILLABLE = "NOT_BILLABLE"
    BILLABLE = "BILLABLE"
    INVOICED = "INVOICED"
    RECONCILED = "RECONCILED"
    CREDIT_PENDING = "CREDIT_PENDING"
    CREDITED = "CREDITED"


class Ownership(str, Enum):
    CONSIGNED = "CONSIGNED"
    OWNED = "OWNED"


class RegistryConsent(str, Enum):
    GRANTED = "GRANTED"
    DECLINED = "DECLINED"
    UNKNOWN = "UNKNOWN"


class CaseStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"
    ABORTED = "ABORTED"


class ReadinessStatus(str, Enum):
    READY = "READY"
    BLOCKED_RESERVATION = "BLOCKED_RESERVATION"
    BLOCKED_DOCUMENTATION = "BLOCKED_DOCUMENTATION"
    BLOCKED_REGISTRY = "BLOCKED_REGISTRY"
    BLOCKED_CHARGE = "BLOCKED_CHARGE"


class ImplantRecordStatus(str, Enum):
    DOCUMENTED = "DOCUMENTED"
    VERIFIED = "VERIFIED"
    AMENDED = "AMENDED"
    EXPLANTED = "EXPLANTED"
    VOIDED = "VOIDED"


class Laterality(str, Enum):
    LEFT = "LEFT"
    RIGHT = "RIGHT"
    BILATERAL = "BILATERAL"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ChargeStatus(str, Enum):
    DRAFT = "DRAFT"
    POSTED = "POSTED"
    CORRECTION_REQUIRED = "CORRECTION_REQUIRED"
    FINALIZED = "FINALIZED"
    VOIDED = "VOIDED"


class CaptureVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class RegistrySubmissionStatus(str, Enum):
    REQUIRED = "REQUIRED"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    EXEMPT = "EXEMPT"


class FieldActionStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    IN_REMEDIATION = "IN_REMEDIATION"
    CLOSED = "CLOSED"


class ActionClass(str, Enum):
    CLASS_I = "CLASS_I"
    CLASS_II = "CLASS_II"
    CLASS_III = "CLASS_III"


class ScopeType(str, Enum):
    CATALOG = "CATALOG"
    LOT = "LOT"
    SERIAL_RANGE = "SERIAL_RANGE"


class NotificationStatus(str, Enum):
    PENDING = "PENDING"
    NOTIFIED = "NOTIFIED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    UNREACHABLE = "UNREACHABLE"
    CLOSED = "CLOSED"


class InvoiceStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    MATCHED = "MATCHED"
    VARIANCE_HOLD = "VARIANCE_HOLD"
    DISPUTED = "DISPUTED"
    APPROVED = "APPROVED"


class ExplantStatus(str, Enum):
    RECORDED = "RECORDED"
    RETURN_AUTHORIZED = "RETURN_AUTHORIZED"
    SHIPPED = "SHIPPED"
    CREDIT_ISSUED = "CREDIT_ISSUED"
    CREDIT_DENIED = "CREDIT_DENIED"
    DISPOSED_LOCALLY = "DISPOSED_LOCALLY"


class ExplantReason(str, Enum):
    DEVICE_FAILURE = "DEVICE_FAILURE"
    INFECTION = "INFECTION"
    RECALL = "RECALL"
    UPGRADE = "UPGRADE"
    OTHER = "OTHER"


class Disposition(str, Enum):
    RETURN_TO_VENDOR = "RETURN_TO_VENDOR"
    DISPOSE_LOCALLY = "DISPOSE_LOCALLY"


class OnHandDisposition(str, Enum):
    RETURN_TO_VENDOR = "RETURN_TO_VENDOR"
    DISPOSE = "DISPOSE"


# ─── Entity shapes ────────────────────────────────────────────────────────

class Vendor(TypedDict):
    id: str
    name: str
    vendor_code: str
    standing: str
    open_consignment_liability_cents: int
    recall_open_count: int
    created_at: str
    updated_at: str
    version: int


class ConsignmentAgreement(TypedDict):
    id: str
    vendor_id: str
    agreement_code: str
    status: str
    billing_trigger: str
    reconciliation_method: str
    invoice_tolerance_bps: int
    price_list_version: int
    period_start_utc: str
    period_end_utc: str
    replenishment_days: int
    created_at: str
    updated_at: str
    version: int


class CatalogItem(TypedDict):
    id: str
    vendor_id: str
    device_identifier: str
    description: str
    category: str
    list_charge_cents: int
    charge_code: str
    registry_required: bool
    shelf_life_days: int
    on_hand_available_qty: int
    created_at: str
    updated_at: str
    version: int


class Lot(TypedDict):
    id: str
    catalog_item_id: str
    lot_number: str
    expiration_date: str
    status: str
    received_at_utc: str
    received_by_user_id: str
    released_by_user_id: Optional[str]
    received_qty: int
    on_hand_qty: int
    consumed_qty: int
    created_at: str
    updated_at: str
    version: int


class DeviceUnit(TypedDict):
    id: str
    lot_id: str
    consignment_agreement_id: Optional[str]
    vendor_invoice_id: Optional[str]
    reserved_case_id: Optional[str]
    replaced_unit_id: Optional[str]
    udi_serial: str
    udi_di_snapshot: str
    custody_state: str
    billing_state: str
    ownership: str
    acquisition_cost_cents: int
    contract_price_cents: Optional[int]
    price_list_version_at_billing: Optional[int]
    implanted_at_utc: Optional[str]
    expired_at_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Patient(TypedDict):
    id: str
    mrn: str
    display_name: str
    registry_consent: str
    implant_count: int
    created_at: str
    updated_at: str
    version: int


class SurgicalCase(TypedDict):
    id: str
    patient_id: str
    case_number: str
    or_room_code: str
    scheduled_start_utc: str
    scheduled_end_utc: str
    surgeon_code: str
    status: str
    readiness_status: str
    blocked_reservation_count: int
    total_posted_charge_cents: int
    implant_record_count: int
    created_at: str
    updated_at: str
    version: int


class ImplantRecord(TypedDict):
    id: str
    surgical_case_id: str
    device_unit_id: str
    patient_id: str
    status: str
    udi_di: str
    udi_pi_serial: str
    anatomic_site: str
    laterality: str
    documented_by_user_id: str
    verified_by_user_id: Optional[str]
    documented_at_utc: str
    verified_at_utc: Optional[str]
    amendment_count: int
    created_at: str
    updated_at: str
    version: int


class ChargeCapture(TypedDict):
    id: str
    implant_record_id: str
    charge_code: str
    quantity: int
    status: str
    provisional_charge_cents: int
    final_charge_cents: Optional[int]
    variance_cents: Optional[int]
    effective_charge_cents: int
    capture_variant: str
    created_at: str
    updated_at: str
    version: int


class RegistrySubmission(TypedDict):
    id: str
    implant_record_id: str
    status: str
    completeness_score: int
    registry_code: Optional[str]
    submitted_at_utc: Optional[str]
    adjudicated_at_utc: Optional[str]
    rejection_reason: Optional[str]
    resubmission_count: int
    deadline_utc: str
    created_at: str
    updated_at: str
    version: int


class FieldAction(TypedDict):
    id: str
    vendor_id: str
    catalog_item_id: str
    action_code: str
    action_class: str
    scope_type: str
    lot_numbers: Optional[List[str]]
    serial_low: Optional[str]
    serial_high: Optional[str]
    status: str
    effective_from_utc: str
    published_at_utc: Optional[str]
    implanted_cohort_size: int
    on_hand_cohort_size: int
    notification_open_count: int
    created_at: str
    updated_at: str
    version: int


class RecallNotification(TypedDict):
    id: str
    field_action_id: str
    implant_record_id: str
    patient_id: str
    status: str
    due_utc: str
    outcome_note: Optional[str]
    escalation_level: int
    created_at: str
    updated_at: str
    version: int


class VendorInvoice(TypedDict):
    id: str
    vendor_id: str
    consignment_agreement_id: str
    invoice_number: str
    submitted_total_cents: int
    device_unit_ids: List[str]
    status: str
    expected_total_cents: Optional[int]
    variance_cents: Optional[int]
    variance_bps: Optional[int]
    reconciliation_variant: Optional[str]
    credit_applied_cents: Optional[int]
    net_payable_cents: Optional[int]
    matched_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    override_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExplantRecord(TypedDict):
    id: str
    implant_record_id: str
    replacement_device_unit_id: Optional[str]
    status: str
    reason: str
    explanted_at_utc: str
    return_authorization_no: Optional[str]
    credit_expected_cents: int
    credit_issued_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int
