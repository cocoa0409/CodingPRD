"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import List, Optional, TypedDict


class SubscriptionTier(str, Enum):
    BASIC = "BASIC"
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"


class AnalysisVariant(str, Enum):
    LEXICAL_V1 = "LEXICAL_V1"
    CONTEXTUAL_V2 = "CONTEXTUAL_V2"


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class MemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REMOVED = "REMOVED"


class AgeBand(str, Enum):
    CHILD_9_UNDER = "CHILD_9_UNDER"
    PRETEEN_10_12 = "PRETEEN_10_12"
    TEEN_13_15 = "TEEN_13_15"
    OLDER_TEEN_16_17 = "OLDER_TEEN_16_17"


class MonitoringSensitivity(str, Enum):
    LENIENT = "LENIENT"
    STANDARD = "STANDARD"
    STRICT = "STRICT"


class ProfileStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class Platform(str, Enum):
    ANDROID = "ANDROID"
    IOS = "IOS"
    CHROMEBOOK = "CHROMEBOOK"


class PairingStatus(str, Enum):
    PAIRED = "PAIRED"
    UNPAIRED = "UNPAIRED"


class DevicePosture(str, Enum):
    NORMAL = "NORMAL"
    BYPASS_WATCH = "BYPASS_WATCH"
    LOCKDOWN = "LOCKDOWN"


class ServiceType(str, Enum):
    MESSAGING = "MESSAGING"
    SOCIAL = "SOCIAL"
    EMAIL = "EMAIL"


class ConsentStatus(str, Enum):
    AWAITING_CONSENT = "AWAITING_CONSENT"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    REVOKED = "REVOKED"


class Direction(str, Enum):
    INBOUND = "INBOUND"
    OUTBOUND = "OUTBOUND"


class SignalCategory(str, Enum):
    BULLYING = "BULLYING"
    SELF_HARM = "SELF_HARM"
    EXPLICIT = "EXPLICIT"
    PREDATORY_CONTACT = "PREDATORY_CONTACT"


class Severity(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    SEVERE = "SEVERE"


class AlertStatus(str, Enum):
    DELIVERED = "DELIVERED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"
    REOPENED = "REOPENED"


class CaseStatus(str, Enum):
    OPEN = "OPEN"
    GUIDANCE_ISSUED = "GUIDANCE_ISSUED"
    RESOURCE_REFERRED = "RESOURCE_REFERRED"
    CRISIS_ESCALATED = "CRISIS_ESCALATED"
    LEGAL_REPORTED = "LEGAL_REPORTED"
    CLOSED = "CLOSED"


class Weekday(str, Enum):
    MON = "MON"
    TUE = "TUE"
    WED = "WED"
    THU = "THU"
    FRI = "FRI"
    SAT = "SAT"
    SUN = "SUN"


class WindowKind(str, Enum):
    BLOCKED = "BLOCKED"
    ALLOWED = "ALLOWED"


class WindowStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"


class RuleKind(str, Enum):
    CATEGORY_BLOCK = "CATEGORY_BLOCK"
    DOMAIN_BLOCK = "DOMAIN_BLOCK"
    DOMAIN_ALLOW = "DOMAIN_ALLOW"


class RuleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"


class BypassKind(str, Enum):
    VPN = "VPN"
    SECONDARY_ACCOUNT = "SECONDARY_ACCOUNT"
    TIMEZONE_SHIFT = "TIMEZONE_SHIFT"
    UNINSTALL_ATTEMPT = "UNINSTALL_ATTEMPT"


class GrantStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class Jurisdiction(str, Enum):
    MANDATED_REPORTING = "MANDATED_REPORTING"
    DISCRETIONARY = "DISCRETIONARY"


class DistrictStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class LinkStatus(str, Enum):
    PENDING_CONSENT = "PENDING_CONSENT"
    ACTIVE = "ACTIVE"
    WITHDRAWN = "WITHDRAWN"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    PARENT = "Parent"
    SCHOOL_ADMIN = "SchoolAdmin"
    DEVICE_AGENT = "DeviceAgent"


class FamilyAccount(TypedDict, total=False):
    id: str
    family_name: str
    primary_contact_email: str
    subscription_tier: str
    analysis_variant: str
    account_status: str
    device_limit: int
    device_count: int
    open_escalation_count: int
    last_proration_charge_cents: int
    billing_period_start: str
    billing_period_end: str
    created_at: str
    updated_at: str
    version: int


class ParentMember(TypedDict, total=False):
    id: str
    family_account_id: str
    display_name: str
    email: str
    is_primary: bool
    member_status: str
    created_at: str
    updated_at: str
    version: int


class ChildProfile(TypedDict, total=False):
    id: str
    family_account_id: str
    display_name: str
    birth_year: int
    age_band: str
    monitoring_sensitivity: str
    profile_status: str
    open_alert_count: int
    created_at: str
    updated_at: str
    version: int


class Device(TypedDict, total=False):
    id: str
    child_profile_id: str
    platform: str
    nickname: str
    pairing_status: str
    device_posture: str
    bypass_strike_count: int
    created_at: str
    updated_at: str
    version: int


class ServiceConnection(TypedDict, total=False):
    id: str
    child_profile_id: str
    service_type: str
    external_handle: str
    consent_status: str
    created_at: str
    updated_at: str
    version: int


class Signal(TypedDict):
    category: str
    weight: int


class ContentItem(TypedDict, total=False):
    id: str
    service_connection_id: str
    occurred_at: str
    direction: str
    thread_depth: int
    signals: List[Signal]
    raw_text: str
    analysis_variant_used: str
    risk_score: int
    severity: str
    alert_created: bool
    alert_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Alert(TypedDict, total=False):
    id: str
    child_profile_id: str
    content_item_id: str
    category: str
    severity: str
    excerpt_text: str
    alert_status: str
    escalation_case_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EscalationCase(TypedDict, total=False):
    id: str
    alert_id: str
    child_profile_id: str
    case_status: str
    crisis_resource_codes: List[str]
    legal_report_due_at: Optional[str]
    legal_report_filed_at: Optional[str]
    overdue: bool
    district_link_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ScreenTimeWindow(TypedDict, total=False):
    id: str
    device_id: str
    weekday: str
    start_minute: int
    end_minute: int
    window_kind: str
    window_status: str
    created_at: str
    updated_at: str
    version: int


class FilterRule(TypedDict, total=False):
    id: str
    child_profile_id: str
    rule_kind: str
    target: str
    rule_status: str
    created_at: str
    updated_at: str
    version: int


class BypassEvent(TypedDict, total=False):
    id: str
    device_id: str
    bypass_kind: str
    detected_at: str
    counted_in_strikes: bool
    created_at: str
    updated_at: str
    version: int


class DeviceAccessGrant(TypedDict, total=False):
    id: str
    device_id: str
    start_at: str
    end_at: str
    reason: str
    grant_status: str
    created_at: str
    updated_at: str
    version: int


class District(TypedDict, total=False):
    id: str
    district_name: str
    contact_email: str
    jurisdiction: str
    district_status: str
    open_obligation_count: int
    created_at: str
    updated_at: str
    version: int


class DistrictLink(TypedDict, total=False):
    id: str
    district_id: str
    child_profile_id: str
    link_status: str
    pending_legal_report: bool
    consented_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
