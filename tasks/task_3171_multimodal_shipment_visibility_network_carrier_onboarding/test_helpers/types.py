"""Domain types for the Multimodal Shipment Visibility API.

Status enums, role names and the field shapes of every resource the contract
declares. TrackingEvent, HeartbeatRecord and OpsRun are append-only child
records: they carry only ``id`` and ``created_at`` as common properties and
have no ``updated_at`` or ``version``.
"""

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ── Role names (spelled exactly as the contract spells them) ────────────────

ROLE_PLATFORM_ADMIN = "PlatformAdmin"
ROLE_NETWORK_OPS = "NetworkOps"
ROLE_CARRIER_REP = "CarrierRep"
ROLE_SHIPPER_REP = "ShipperRep"
ROLE_CUSTOMER_SERVICE = "CustomerService"
ROLE_CONSIGNEE_REP = "ConsigneeRep"


class Channel(str, Enum):
    TELEMATICS = "TELEMATICS"
    TMS = "TMS"
    MANUAL = "MANUAL"


class Mode(str, Enum):
    OCEAN = "OCEAN"
    RAIL = "RAIL"
    PARCEL = "PARCEL"
    TRUCKLOAD = "TRUCKLOAD"


class ConnectionStatus(str, Enum):
    DRAFT = "DRAFT"
    CREDENTIALS_SUBMITTED = "CREDENTIALS_SUBMITTED"
    TESTING = "TESTING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    RETIRED = "RETIRED"


class HealthStatus(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    CRITICAL = "CRITICAL"


class TrackingStatus(str, Enum):
    BOOKED = "BOOKED"
    IN_TRANSIT = "IN_TRANSIT"
    EXCEPTION = "EXCEPTION"
    OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class IdentityState(str, Enum):
    UNRESOLVED = "UNRESOLVED"
    MATCHED_PROVISIONAL = "MATCHED_PROVISIONAL"
    MATCHED_CONFIRMED = "MATCHED_CONFIRMED"


class DataFreshness(str, Enum):
    FRESH = "FRESH"
    STALE = "STALE"


class EtaVariant(str, Enum):
    SCHEDULED_BASELINE = "SCHEDULED_BASELINE"
    TELEMETRY_BLENDED = "TELEMETRY_BLENDED"


class EventType(str, Enum):
    DEPARTED = "DEPARTED"
    ARRIVED_WAYPOINT = "ARRIVED_WAYPOINT"
    POSITION_UPDATE = "POSITION_UPDATE"
    DELAY_REPORTED = "DELAY_REPORTED"
    RECOVERED = "RECOVERED"
    OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY"
    DELIVERED = "DELIVERED"


class LinkStatus(str, Enum):
    PROPOSED = "PROPOSED"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"


class AlertType(str, Enum):
    DELAY_RISK = "DELAY_RISK"
    CONNECTION_DEGRADED = "CONNECTION_DEGRADED"


class AlertSeverity(str, Enum):
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class AlertStatus(str, Enum):
    OPEN = "OPEN"
    ESCALATED = "ESCALATED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"


class AlertResolution(str, Enum):
    DELAY_CONFIRMED = "DELAY_CONFIRMED"
    FALSE_ALARM = "FALSE_ALARM"
    DELIVERY_OBSERVED = "DELIVERY_OBSERVED"


class AppointmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    MISSED = "MISSED"
    VOIDED = "VOIDED"


class FacilityStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class FacilityType(str, Enum):
    ORIGIN = "ORIGIN"
    DESTINATION = "DESTINATION"
    BOTH = "BOTH"


class GranteeType(str, Enum):
    CARRIER = "CARRIER"
    CONSIGNEE = "CONSIGNEE"


class GrantScope(str, Enum):
    ETA_ONLY = "ETA_ONLY"
    FULL_TRACE = "FULL_TRACE"


class GrantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


# ── Entity shapes ────────────────────────────────────────────────────────────


class Carrier(TypedDict, total=False):
    id: str
    carrier_name: str
    scac_code: str
    created_at: str
    updated_at: str
    version: int


class Shipper(TypedDict, total=False):
    id: str
    company_name: str
    created_at: str
    updated_at: str
    version: int


class Consignee(TypedDict, total=False):
    id: str
    shipper_id: str
    company_name: str
    destination_code: str
    created_at: str
    updated_at: str
    version: int


class CarrierConnection(TypedDict, total=False):
    id: str
    carrier_id: str
    channel: str
    supported_modes: List[str]
    status: str
    credential_ref: Optional[str]
    testing_window_start: Optional[str]
    testing_window_end: Optional[str]
    cadence_minutes: int
    data_quality_score: Optional[int]
    instantaneous_quality_score: Optional[int]
    health_status: Optional[str]
    missed_heartbeat_streak: int
    last_heartbeat_at: Optional[str]
    suspended_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PurchaseOrder(TypedDict, total=False):
    id: str
    shipper_id: str
    po_number: str
    destination_code: str
    booking_reference: str
    confirmed_link_count: int
    created_at: str
    updated_at: str
    version: int


class Facility(TypedDict, total=False):
    id: str
    facility_name: str
    facility_type: str
    status: str
    total_dwell_minutes: int
    detention_exposure_minutes: int
    appointment_adherence_pct: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict, total=False):
    id: str
    shipper_id: str
    carrier_id: str
    connection_id: str
    mode: str
    tracking_reference: str
    mode_reference: str
    destination_code: str
    po_reference_claim: str
    planned_departure_at: str
    planned_arrival_at: str
    tracking_status: str
    identity_state: str
    data_freshness: str
    eta_at: Optional[str]
    eta_variant: str
    eta_confidence_halfwidth_minutes: Optional[int]
    actual_delay_minutes: int
    created_at: str
    updated_at: str
    version: int


class TrackingEvent(TypedDict, total=False):
    # Append-only child record: id + created_at only, no updated_at/version.
    id: str
    shipment_id: str
    event_time: str
    event_type: str
    delay_minutes: int
    is_late: bool
    voided: bool
    created_at: str


class ShipmentIdentityLink(TypedDict, total=False):
    id: str
    shipment_id: str
    purchase_order_id: str
    match_score: float
    status: str
    created_at: str
    updated_at: str
    version: int


class ExceptionAlert(TypedDict, total=False):
    id: str
    shipment_id: str
    alert_type: str
    severity: str
    assigned_queue: str
    status: str
    opened_at: str
    resolution: Optional[str]
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Appointment(TypedDict, total=False):
    id: str
    facility_id: str
    shipment_id: str
    window_start: str
    window_end: str
    status: str
    actual_arrival_at: Optional[str]
    actual_departure_at: Optional[str]
    dwell_minutes: Optional[int]
    adherent: Optional[bool]
    exposure_minutes: Optional[int]
    created_at: str
    updated_at: str
    version: int


class DataShareGrant(TypedDict, total=False):
    id: str
    shipper_id: str
    grantee_type: str
    grantee_id: str
    scope: str
    effective_from: str
    expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class HeartbeatRecord(TypedDict, total=False):
    # Append-only child record: id + created_at only, no updated_at/version.
    id: str
    connection_id: str
    reported_at: str
    recorded_at: str
    payload_completeness_pct: int
    on_time: bool
    created_at: str


class OpsRun(TypedDict, total=False):
    # Append-only record: id + created_at only, no updated_at/version.
    id: str
    run_index: int
    executed_at: str
    connections_degraded: int
    testing_connections_reset: int
    etas_recomputed: int
    alerts_created: int
    alerts_escalated: int
    created_at: str
