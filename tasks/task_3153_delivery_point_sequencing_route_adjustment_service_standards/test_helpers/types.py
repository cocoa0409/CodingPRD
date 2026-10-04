"""Domain types: entity TypedDicts, status enums, role enum.

Field names follow the PRD verbatim. Two resource kinds are append-only or
computed-read records (ServiceStandardQuery and DeliveryScanEvent) and carry
only ``id`` and ``created_at``; every other resource additionally carries
``updated_at`` and ``version``.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    PLATFORM_ADMIN = "PlatformAdmin"
    ADDRESS_MANAGEMENT_SPECIALIST = "AddressManagementSpecialist"
    ROUTE_SUPERVISOR = "RouteSupervisor"
    POSTMASTER = "Postmaster"
    CARRIER = "Carrier"
    CUSTOMER_SERVICE_REP = "CustomerServiceRep"
    SERVICE_STANDARDS_ADMIN = "ServiceStandardsAdmin"


class FacilityType(str, Enum):
    P_AND_DC = "P_AND_DC"
    S_AND_DC = "S_AND_DC"
    NDC = "NDC"
    ANEX = "ANEX"


class RegionClass(str, Enum):
    CONTIGUOUS = "CONTIGUOUS"
    NON_CONTIGUOUS = "NON_CONTIGUOUS"


class FacilityStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DECOMMISSIONED = "DECOMMISSIONED"


class OccupancyStatus(str, Enum):
    UNDER_CONSTRUCTION = "UNDER_CONSTRUCTION"
    OCCUPIED = "OCCUPIED"
    VACANT = "VACANT"
    SEASONAL = "SEASONAL"
    DISCONTINUED = "DISCONTINUED"


class PointKind(str, Enum):
    RESIDENTIAL = "RESIDENTIAL"
    BUSINESS = "BUSINESS"
    CENTRALIZED = "CENTRALIZED"
    PO_BOX = "PO_BOX"


class DeliveryRestriction(str, Enum):
    NONE = "NONE"
    BUSINESS_ONLY_HOURS = "BUSINESS_ONLY_HOURS"
    GATED_CODE_ON_FILE = "GATED_CODE_ON_FILE"
    NO_SECURE_LOCATION = "NO_SECURE_LOCATION"


class CarrierClass(str, Enum):
    REGULAR = "REGULAR"
    CITY_ASSISTANT = "CITY_ASSISTANT"
    RURAL = "RURAL"
    AUXILIARY = "AUXILIARY"


class CarrierStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ON_ROUTE = "ON_ROUTE"
    DETAILED = "DETAILED"
    INACTIVE = "INACTIVE"


class RouteType(str, Enum):
    CITY = "CITY"
    RURAL = "RURAL"
    HIGHWAY_CONTRACT = "HIGHWAY_CONTRACT"


class RouteStatus(str, Enum):
    STANDARD = "STANDARD"
    UNDER_EVALUATION = "UNDER_EVALUATION"
    UNDER_ADJUSTMENT = "UNDER_ADJUSTMENT"
    SUSPENDED = "SUSPENDED"


class DeliveryOrderGroup(str, Enum):
    PARK_LOOP = "PARK_LOOP"
    MOUNTED = "MOUNTED"
    WALKING = "WALKING"
    DISMOUNT = "DISMOUNT"


class EvaluationKind(str, Enum):
    FULL_COUNT = "FULL_COUNT"
    MINI_SURVEY = "MINI_SURVEY"
    SPECIAL_INSPECTION = "SPECIAL_INSPECTION"


class ConsultationOutcome(str, Enum):
    PENDING = "PENDING"
    CONCURRED = "CONCURRED"
    DISPUTED = "DISPUTED"
    WAIVED = "WAIVED"


class EvaluationStatus(str, Enum):
    INITIATED = "INITIATED"
    DATA_COLLECTION = "DATA_COLLECTION"
    CONSULTATION_SCHEDULED = "CONSULTATION_SCHEDULED"
    CONSULTED = "CONSULTED"
    CLOSED_ADOPTED = "CLOSED_ADOPTED"
    CLOSED_REJECTED = "CLOSED_REJECTED"


class AdjustmentStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EFFECTIVE = "EFFECTIVE"
    WITHDRAWN = "WITHDRAWN"


class AuxiliaryStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CURTAILED = "CURTAILED"
    DENIED = "DENIED"


class MoveKind(str, Enum):
    INDIVIDUAL = "INDIVIDUAL"
    FAMILY = "FAMILY"
    BUSINESS = "BUSINESS"


class MoveType(str, Enum):
    PERMANENT = "PERMANENT"
    TEMPORARY = "TEMPORARY"


class ForwardingStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class ValidationStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class HoldDisposition(str, Enum):
    ACCUMULATE_DELIVER_ON_END = "ACCUMULATE_DELIVER_ON_END"
    CARRIER_PICKUP = "CARRIER_PICKUP"


class HoldStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class MailClass(str, Enum):
    FIRST_CLASS = "FIRST_CLASS"
    PRIORITY = "PRIORITY"
    GROUND_ADVANTAGE = "GROUND_ADVANTAGE"
    PERIODICALS = "PERIODICALS"
    MARKETING = "MARKETING"


class RuleStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class VariantUsed(str, Enum):
    CONTIGUOUS = "CONTIGUOUS"
    NON_CONTIGUOUS = "NON_CONTIGUOUS"


class ScanCode(str, Enum):
    DELIVERED = "DELIVERED"
    ATTEMPTED_NO_ACCESS = "ATTEMPTED_NO_ACCESS"
    VACANT_CONFIRMED = "VACANT_CONFIRMED"
    FORWARDED = "FORWARDED"
    HELD_AT_OFFICE = "HELD_AT_OFFICE"
    REFUSED = "REFUSED"


class InquiryKind(str, Enum):
    MISSING_MAIL = "MISSING_MAIL"
    LATE_DELIVERY = "LATE_DELIVERY"
    WRONG_DELIVERY = "WRONG_DELIVERY"
    HOLD_NOT_HONORED = "HOLD_NOT_HONORED"
    FORWARD_NOT_RECEIVED = "FORWARD_NOT_RECEIVED"


class InquiryChannel(str, Enum):
    PHONE = "PHONE"
    WEB = "WEB"
    WALK_IN = "WALK_IN"


class InquiryStatus(str, Enum):
    OPEN = "OPEN"
    INVESTIGATING = "INVESTIGATING"
    RESOLVED = "RESOLVED"
    RESOLVED_FINAL = "RESOLVED_FINAL"
    CLOSED_ABANDONED = "CLOSED_ABANDONED"


class ResolutionCode(str, Enum):
    FOUND_AND_DELIVERED = "FOUND_AND_DELIVERED"
    SENDER_CONTACTED = "SENDER_CONTACTED"
    FORWARD_CONFIRMED = "FORWARD_CONFIRMED"
    NO_ERROR_FOUND = "NO_ERROR_FOUND"


class ProcessingFacility(TypedDict, total=False):
    id: str
    facility_code: str
    facility_type: str
    region_class: str
    dispatch_cutoff_local: str
    operating_days: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DeliveryUnit(TypedDict, total=False):
    id: str
    unit_code: str
    office_name: str
    delivery_office_facility_id: str
    case_slot_count_per_route: int
    universal_service_obligation: bool
    scan_compliance_target: float
    active_route_count: int
    created_at: str
    updated_at: str
    version: int


class DeliveryPoint(TypedDict, total=False):
    id: str
    delivery_unit_id: str
    active_route_id: Optional[str]
    address_line1: str
    city: str
    state_code: str
    zip11: str
    point_kind: str
    occupancy_status: str
    vacant_since_date: Optional[str]
    vacancy_days: int
    is_deliverable: bool
    delivery_restriction: str
    created_at: str
    updated_at: str
    version: int


class Carrier(TypedDict, total=False):
    id: str
    delivery_unit_id: str
    employee_id: str
    full_name: str
    carrier_class: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CarrierRoute(TypedDict, total=False):
    id: str
    delivery_unit_id: str
    route_code: str
    assigned_carrier_id: str
    route_type: str
    status: str
    base_evaluated_minutes: int
    current_evaluated_minutes: int
    active_delivery_point_count: int
    under_evaluation_since: Optional[str]
    auxiliary_relief_minutes: int
    created_at: str
    updated_at: str
    version: int


class RouteSequenceEntry(TypedDict, total=False):
    id: str
    carrier_route_id: str
    delivery_point_id: str
    line_of_travel_order: int
    case_slot_letters: int
    case_slot_flats: int
    delivery_order_group: str
    created_at: str
    updated_at: str
    version: int


class RouteEvaluation(TypedDict, total=False):
    id: str
    carrier_route_id: str
    evaluation_kind: str
    count_week_start: str
    letters_count_total: int
    flats_count_total: int
    parcels_count_total: int
    actual_street_minutes_total: int
    office_minutes_total: int
    modeled_street_minutes_total: int
    evaluated_daily_minutes: int
    consultation_outcome: str
    status: str
    recollection_used: bool
    created_at: str
    updated_at: str
    version: int


class RouteAdjustment(TypedDict, total=False):
    id: str
    route_evaluation_id: str
    proposed_evaluated_minutes: int
    points_transferred_out: List[dict]
    status: str
    effective_date: str
    approver_user_id: Optional[str]
    submitter_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AuxiliaryAssignment(TypedDict, total=False):
    id: str
    carrier_route_id: str
    helper_carrier_id: str
    service_date: str
    scheduled_minutes: int
    projected_overrun_minutes: int
    seasonal_surge_flag: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class ChangeOfAddress(TypedDict, total=False):
    id: str
    delivery_unit_id: str
    old_delivery_point_id: str
    new_address_line1: str
    new_city: str
    new_state_code: str
    new_zip11: str
    move_kind: str
    move_type: str
    begin_date: str
    end_date: Optional[str]
    supersedes_coa_id: Optional[str]
    forwarding_status: str
    validation_status: str
    created_at: str
    updated_at: str
    version: int


class HoldMail(TypedDict, total=False):
    id: str
    delivery_unit_id: str
    delivery_point_id: str
    hold_start_date: str
    hold_end_date: str
    disposition: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceStandardRule(TypedDict, total=False):
    id: str
    origin_facility_id: str
    dest_facility_id: str
    mail_class: str
    service_days: int
    non_contiguous_extra_days: int
    effective_from: str
    effective_to: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only computed read: carries ONLY id + created_at (no updated_at, no version)
class ServiceStandardQuery(TypedDict, total=False):
    id: str
    origin_facility_id: str
    dest_facility_id: str
    mail_class: str
    acceptance_date: str
    acceptance_time_local: str
    committed_delivery_date: str
    committed_service_days: int
    variant_used: str
    created_at: str


# Append-only scan record: carries ONLY id + created_at (no updated_at, no version)
class DeliveryScanEvent(TypedDict, total=False):
    id: str
    carrier_route_id: str
    delivery_point_id: str
    carrier_id: str
    scan_code: str
    scan_datetime: str
    gps_within_geofence: bool
    is_compliant: bool
    created_at: str


class CustomerInquiry(TypedDict, total=False):
    id: str
    delivery_unit_id: str
    delivery_point_id: str
    related_scan_event_id: Optional[str]
    inquiry_kind: str
    opened_by_channel: str
    status: str
    resolution_code: Optional[str]
    sla_due_datetime: str
    reopened_count: int
    created_at: str
    updated_at: str
    version: int
