"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    ACCOUNT_ADMIN = "AccountAdmin"
    PARTNER_MANAGER = "PartnerManager"
    LOGISTICS_AGENT = "LogisticsAgent"


class SmartAccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class CompliancePosture(str, Enum):
    COMPLIANT = "COMPLIANT"
    GRACE = "GRACE"
    NON_COMPLIANT = "NON_COMPLIANT"


class PartnerOrgStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class DelegationScope(str, Enum):
    LICENSING = "LICENSING"
    SERVICE_CONTRACTS = "SERVICE_CONTRACTS"
    FULL = "FULL"


class DelegationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class VirtualAccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class LicenseModel(str, Enum):
    PERPETUAL = "PERPETUAL"
    SUBSCRIPTION = "SUBSCRIPTION"


class FeatureTier(str, Enum):
    ESSENTIALS = "ESSENTIALS"
    ADVANTAGE = "ADVANTAGE"
    PREMIER = "PREMIER"


class ComplianceState(str, Enum):
    COMPLIANT = "COMPLIANT"
    IN_GRACE = "IN_GRACE"
    OUT_OF_COMPLIANCE = "OUT_OF_COMPLIANCE"


class RegistrationState(str, Enum):
    PENDING = "PENDING"
    REGISTERED = "REGISTERED"
    DEREGISTERED = "DEREGISTERED"
    RETIRED = "RETIRED"


class AssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class UsageReportStatus(str, Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class ComplianceEventType(str, Enum):
    OVERAGE_DETECTED = "OVERAGE_DETECTED"
    GRACE_STARTED = "GRACE_STARTED"
    GRACE_EXPIRED = "GRACE_EXPIRED"
    RESTORED_TO_COMPLIANCE = "RESTORED_TO_COMPLIANCE"


class MilestoneType(str, Enum):
    END_OF_SALE = "END_OF_SALE"
    END_OF_LIFE = "END_OF_LIFE"
    END_OF_SUPPORT = "END_OF_SUPPORT"


class ServiceLevel(str, Enum):
    DEPOT_RETURN = "DEPOT_RETURN"
    ADVANCE_NBD = "ADVANCE_NBD"
    ADVANCE_4H = "ADVANCE_4H"


class SupportTier(str, Enum):
    SOFTWARE_ONLY = "SOFTWARE_ONLY"
    SOFTWARE_HARDWARE = "SOFTWARE_HARDWARE"
    FULL = "FULL"


class ContractStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class CoverageStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    VOIDED = "VOIDED"


class RmaStatus(str, Enum):
    OPENED = "OPENED"
    REPLACEMENT_SHIPPED = "REPLACEMENT_SHIPPED"
    REPLACEMENT_DELIVERED = "REPLACEMENT_DELIVERED"
    DEFECTIVE_RETURNED = "DEFECTIVE_RETURNED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class TransferReason(str, Enum):
    HARDWARE_REFRESH = "HARDWARE_REFRESH"
    ACCOUNT_REORG = "ACCOUNT_REORG"
    PARTNER_EXIT = "PARTNER_EXIT"


class TransferStatus(str, Enum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXECUTED = "EXECUTED"
    CANCELLED = "CANCELLED"


# --- Entity TypedDicts (PRD §2.4: common entities carry version; append-only do not) ---


class SmartAccount(TypedDict, total=False):
    id: str
    account_ref: str
    display_name: str
    status: str
    managing_partner_id: Optional[str]
    compliance_posture: str
    created_at: str
    updated_at: str
    version: int


class PartnerOrg(TypedDict, total=False):
    id: str
    partner_ref: str
    display_name: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PartnerDelegation(TypedDict, total=False):
    id: str
    partner_org_id: str
    smart_account_id: str
    scope: str
    status: str
    granted_at: str
    revoked_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class VirtualAccount(TypedDict, total=False):
    id: str
    smart_account_id: str
    name: str
    status: str
    created_at: str
    updated_at: str
    version: int


class LicensePool(TypedDict, total=False):
    id: str
    virtual_account_id: str
    sku: str
    license_model: str
    feature_tier: str
    purchased_quantity: int
    consumed_quantity: int
    compliance_state: str
    grace_deadline: Optional[str]
    overage_detected_at: Optional[str]
    subscription_expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Device(TypedDict, total=False):
    id: str
    virtual_account_id: str
    serial_number: str
    product_family: str
    registration_state: str
    registered_at: Optional[str]
    last_sync_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DeviceLicenseAssignment(TypedDict, total=False):
    id: str
    device_id: str
    license_pool_id: str
    quantity: int
    status: str
    assigned_at: str
    created_at: str
    updated_at: str
    version: int


# Append-only (no updated_at / version) per PRD §2.4
class UsageReport(TypedDict, total=False):
    id: str
    device_id: str
    reported_at: str
    lines: List[Dict[str, Any]]
    status: str
    rejection_reason: Optional[str]
    created_at: str


class ComplianceEvent(TypedDict, total=False):
    id: str
    license_pool_id: str
    event_type: str
    occurred_at: str
    consumed_quantity: int
    purchased_quantity: int
    created_at: str


class ProductLifecycleMilestone(TypedDict, total=False):
    id: str
    product_family: str
    milestone_type: str
    effective_date: str
    created_at: str


class ServiceContract(TypedDict, total=False):
    id: str
    smart_account_id: str
    contract_number: str
    service_level: str
    support_tier: str
    start_date: str
    end_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ContractCoverage(TypedDict, total=False):
    id: str
    service_contract_id: str
    device_id: str
    status: str
    covered_from: str
    created_at: str
    updated_at: str
    version: int


class RmaCase(TypedDict, total=False):
    id: str
    contract_coverage_id: str
    device_id: str
    failure_description: str
    status: str
    ship_by: Optional[str]
    opened_at: str
    sla_breached: bool
    created_at: str
    updated_at: str
    version: int


class LicenseTransferRequest(TypedDict, total=False):
    id: str
    source_pool_id: str
    target_virtual_account_id: str
    quantity: int
    reason: str
    status: str
    requested_by_partner_org_id: Optional[str]
    decided_by: Optional[str]
    created_at: str
    updated_at: str
    version: int
