"""Domain types: entity TypedDicts, status enums, and the role enum.

All enum values are the exact strings the PRD pins.  Every entity in this
platform carries the common system-managed fields (id, created_at,
updated_at, version) per PRD section 2.11, so every TypedDict includes them.
"""

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# --- Roles (PRD section 2.1) --------------------------------------------------


class UserRole(str, Enum):
    GROWER_MANAGER = "GrowerManager"
    DEALER_TECHNICIAN = "DealerTechnician"
    INDEPENDENT_TECHNICIAN = "IndependentTechnician"
    AGRONOMIST = "Agronomist"
    COOP_ANALYST = "CoopAnalyst"
    PARTNER_APP = "PartnerApp"
    PLATFORM_ADMIN = "PlatformAdmin"
    SYSTEM = "System"


# --- Status and field enums ---------------------------------------------------


class OrgStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class DealerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ServiceTier(str, Enum):
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"


class ModemStatus(str, Enum):
    UNPROVISIONED = "UNPROVISIONED"
    PROVISIONING = "PROVISIONING"
    PROVISION_FAILED = "PROVISION_FAILED"
    PROVISIONED = "PROVISIONED"


class ProvisioningOutcome(str, Enum):
    PROVISION_SUCCEEDED = "PROVISION_SUCCEEDED"
    PROVISION_FAILED = "PROVISION_FAILED"


class LifecycleStatus(str, Enum):
    REGISTERED = "REGISTERED"
    ACTIVATED = "ACTIVATED"
    IN_SERVICE = "IN_SERVICE"


class ConnectivityPosture(str, Enum):
    OFFLINE = "OFFLINE"
    NO_PLAN = "NO_PLAN"
    PLAN_SUSPENDED = "PLAN_SUSPENDED"
    THROTTLED = "THROTTLED"
    EXHAUSTED = "EXHAUSTED"
    CONNECTED = "CONNECTED"


class PlanTier(str, Enum):
    BASIC = "BASIC"
    STANDARD = "STANDARD"
    UNLIMITED = "UNLIMITED"


class ProrationMethod(str, Enum):
    CALENDAR_DAY = "CALENDAR_DAY"
    THIRTY_DAY = "THIRTY_DAY"


class PlanStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class UsagePosture(str, Enum):
    NORMAL = "NORMAL"
    THROTTLED = "THROTTLED"
    EXHAUSTED = "EXHAUSTED"


class FieldStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class CropType(str, Enum):
    CORN = "CORN"
    SOY = "SOY"
    WHEAT = "WHEAT"
    COTTON = "COTTON"


class PrescriptionStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    SENT = "SENT"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    SUPERSEDED = "SUPERSEDED"


class GranteeType(str, Enum):
    AGRONOMIST = "AGRONOMIST"
    COOPERATIVE = "COOPERATIVE"
    DEALER = "DEALER"
    THIRD_PARTY_APP = "THIRD_PARTY_APP"


class DataScope(str, Enum):
    TELEMATICS = "TELEMATICS"
    AGRONOMIC = "AGRONOMIC"
    DIAGNOSTICS = "DIAGNOSTICS"


class GrantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class TicketType(str, Enum):
    REMOTE_DIAGNOSTIC = "REMOTE_DIAGNOSTIC"
    SOFTWARE_UPDATE = "SOFTWARE_UPDATE"


class TicketStatus(str, Enum):
    REQUESTED = "REQUESTED"
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    CONSUMED = "CONSUMED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


#: The requester_ref_id the platform records on tickets it mints for deliveries.
PLATFORM_REQUESTER_REF = "platform"


class TechnicianKind(str, Enum):
    DEALER = "DEALER"
    INDEPENDENT = "INDEPENDENT"


class DiagnosticDetailLevel(str, Enum):
    EXTENDED = "EXTENDED"
    BASIC = "BASIC"


class SessionStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class SessionCloseReason(str, Enum):
    COMPLETED = "COMPLETED"
    ACCESS_WITHDRAWN = "ACCESS_WITHDRAWN"


class PackageStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    WITHDRAWN = "WITHDRAWN"


class DeliveryStatus(str, Enum):
    AWAITING_CONSENT = "AWAITING_CONSENT"
    CONSENT_GRANTED = "CONSENT_GRANTED"
    DOWNLOADING = "DOWNLOADING"
    INSTALLED = "INSTALLED"
    FAILED = "FAILED"
    DECLINED = "DECLINED"
    CANCELLED = "CANCELLED"


#: failure_reason written by the connectivity-loss cascade.
FAILURE_REASON_CONNECTIVITY_LOST = "CONNECTIVITY_LOST"


class FeatureCode(str, Enum):
    AUTO_GUIDANCE = "AUTO_GUIDANCE"
    SECTION_CONTROL = "SECTION_CONTROL"
    VARIABLE_RATE_SPREAD = "VARIABLE_RATE_SPREAD"
    TELEMATICS_PREMIUM = "TELEMATICS_PREMIUM"


class LicenseType(str, Enum):
    PERPETUAL = "PERPETUAL"
    TERM = "TERM"


class LicenseStatus(str, Enum):
    PURCHASED = "PURCHASED"
    ACTIVATED = "ACTIVATED"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class ClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    SETTLED = "SETTLED"


class ClaimDecision(str, Enum):
    APPROVE = "APPROVE"
    DENY = "DENY"


class PartnerStatus(str, Enum):
    REGISTERED = "REGISTERED"
    CERTIFICATION_REVIEW = "CERTIFICATION_REVIEW"
    CERTIFIED = "CERTIFIED"
    EXPIRED = "EXPIRED"


class CertDecision(str, Enum):
    CERTIFY = "CERTIFY"
    FAIL = "FAIL"


# --- Entity TypedDicts (all carry the common fields of PRD section 2.11) ------


class Organization(TypedDict):
    id: str
    name: str
    region_code: str
    right_to_repair_enabled: bool
    independent_session_max_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Dealer(TypedDict):
    id: str
    dealer_code: str
    name: str
    region_code: str
    service_tier: str
    status: str
    warranty_reserve_cents: int
    warranty_paid_cents: int
    created_at: str
    updated_at: str
    version: int


class Machine(TypedDict):
    id: str
    organization_id: str
    serial_number: str
    model_code: str
    selling_dealer_id: str
    manufacture_date: str
    modem_imei: str
    modem_status: str
    provisioning_attempts: int
    modem_firmware_version: Optional[str]
    lifecycle_status: str
    connectivity_posture: str
    active_license_count: int
    activating_dealer_id: Optional[str]
    activated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DataPlan(TypedDict):
    id: str
    organization_id: str
    machine_id: str
    tier: str
    proration_method: str
    status: str
    monthly_price_cents: int
    used_mb: float
    usage_posture: str
    cycle_anchor_day: Optional[int]
    cycle_start_date: Optional[str]
    last_proration_charge_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class FieldBoundary(TypedDict):
    id: str
    organization_id: str
    name: str
    season_year: int
    area_hectares: float
    status: str
    created_at: str
    updated_at: str
    version: int


class PrescriptionZone(TypedDict):
    zone_id: str
    rate_l_per_ha: float
    area_ha: float


class Prescription(TypedDict):
    id: str
    organization_id: str
    field_boundary_id: str
    machine_id: str
    crop_type: str
    zones: List[PrescriptionZone]
    valid_from: str
    valid_until: str
    status: str
    revision: int
    total_product_liters: Optional[float]
    weighted_avg_rate_l_per_ha: Optional[float]
    superseded_by_id: Optional[str]
    applied_total_liters: Optional[float]
    applied_coverage_ha: Optional[float]
    applied_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DataShareGrant(TypedDict):
    id: str
    organization_id: str
    grantee_type: str
    grantee_ref_id: str
    scopes: List[str]
    valid_from: str
    valid_until: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ConsentTicket(TypedDict):
    id: str
    organization_id: str
    machine_id: str
    ticket_type: str
    requester_ref_id: str
    status: str
    expires_at: str
    granted_at: Optional[str]
    bound_session_id: Optional[str]
    bound_delivery_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DiagnosticSession(TypedDict):
    id: str
    machine_id: str
    organization_id: str
    dealer_id: Optional[str]
    consent_ticket_id: str
    technician_kind: str
    diagnostic_detail_level: str
    status: str
    opened_at: str
    closed_at: Optional[str]
    closed_reason: Optional[str]
    fault_found: Optional[bool]
    created_at: str
    updated_at: str
    version: int


class SoftwarePackage(TypedDict):
    id: str
    package_code: str
    target_model_code: str
    firmware_version: str
    size_mb: int
    mandatory: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class UpdateDelivery(TypedDict):
    id: str
    machine_id: str
    package_id: str
    consent_ticket_id: str
    status: str
    download_attempts: int
    failure_reason: Optional[str]
    installed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FeatureLicense(TypedDict):
    id: str
    machine_id: str
    feature_code: str
    license_type: str
    term_months: Optional[int]
    fee_cents: int
    status: str
    activated_at: Optional[str]
    expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict):
    id: str
    machine_id: str
    organization_id: str
    dealer_id: str
    claim_amount_cents: int
    parts_amount_cents: int
    description: str
    status: str
    coverage_pct_applied: Optional[float]
    payout_cents: Optional[int]
    decided_at: Optional[str]
    settled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class IntegrationPartner(TypedDict):
    id: str
    name: str
    api_quota_calls_per_day: int
    status: str
    certification_expires_on: Optional[str]
    calls_today: int
    calls_window_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class UptimePrediction(TypedDict):
    optimistic_score: float
    conservative_score: float
    window_hours: int
    filled_hours: int
    bridged_hours: int
    parts_recommendation: str


class DataPullResult(TypedDict):
    organization_id: str
    scope: str
    record_count: int
    calls_remaining_today: int
