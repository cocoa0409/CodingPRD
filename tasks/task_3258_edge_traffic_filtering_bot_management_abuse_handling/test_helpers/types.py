"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List, Any


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    ZONE_ADMIN = "ZoneAdmin"
    TRUST_SAFETY_ANALYST = "TrustSafetyAnalyst"
    NETWORK_PLANNER = "NetworkPlanner"
    ANONYMOUS = "Anonymous"


class PlanTier(str, Enum):
    FREE = "FREE"
    PRO = "PRO"
    BUSINESS = "BUSINESS"
    ENTERPRISE = "ENTERPRISE"


class ZoneStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    MOVED = "MOVED"
    DELETED = "DELETED"


class OnboardingType(str, Enum):
    FULL = "FULL"
    PARTIAL = "PARTIAL"


class DosSensitivity(str, Enum):
    DEFAULT = "DEFAULT"
    LOW = "LOW"
    HIGH = "HIGH"


class DdosEventStatus(str, Enum):
    ACTIVATED = "ACTIVATED"
    ENDED = "ENDED"


class PurgeRequestStatus(str, Enum):
    QUEUED = "QUEUED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"


class PurgeType(str, Enum):
    PURGE_ALL = "PURGE_ALL"
    PURGE_URL = "PURGE_URL"


class IpBlockStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    CONFIRMED = "CONFIRMED"
    EXPIRED = "EXPIRED"


class IpVersion(str, Enum):
    V4 = "V4"
    V6 = "V6"


class AbuseReportStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    REVIEWING = "REVIEWING"
    FORWARDED = "FORWARDED"
    ACTION_TAKEN = "ACTION_TAKEN"
    CLOSED = "CLOSED"


class AbuseCategory(str, Enum):
    PHISHING = "PHISHING"
    MALWARE = "MALWARE"
    CSAM = "CSAM"
    SPAM = "SPAM"
    COPYRIGHT = "COPYRIGHT"
    OTHER = "OTHER"


class RoutingMode(str, Enum):
    HOSTED = "HOSTED"
    PROXIED = "PROXIED"


class BotClassification(str, Enum):
    HONEYPOT_BOT = "HONEYPOT_BOT"
    VERIFIED_BOT = "VERIFIED_BOT"
    HUMAN = "HUMAN"
    LIKELY_AUTOMATED = "LIKELY_AUTOMATED"


class Account(TypedDict, total=False):
    id: str
    company_name: str
    plan_tier: str
    account_email: str
    support_response_sla_hours: int
    created_at: str
    updated_at: str
    version: int


class Pop(TypedDict, total=False):
    id: str
    code: str
    capacity_baseline_gbps: int
    maintenance_windows: List[dict]
    status: str
    effective_capacity_gbps: Optional[int]
    planned_utilization_pct: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Zone(TypedDict, total=False):
    id: str
    account_id: str
    domain_name: str
    onboarding_type: str
    origin_host_email: str
    status: str
    dns_records: List[dict]
    bot_fight_mode: bool
    dos_sensitivity: str
    dos_mitigation_active: bool
    origin_shield_pop_code: Optional[str]
    edge_ttl_seconds: int
    cache_reserve: bool
    last_purged_at: Optional[str]
    honeypot_paths: List[str]
    traffic_rules: List[dict]
    ruleset_subscriptions: List[dict]
    bot_action_bands: List[dict]
    bot_classifications: List[dict]
    active_rules_count: int
    disabled_managed_rules_count: int
    false_positive_rate_pct: int
    created_at: str
    updated_at: str
    version: int


class DdosEvent(TypedDict, total=False):
    id: str
    zone_id: str
    observed_rps: int
    baseline_rps: int
    trigger_threshold_rps: int
    auto_mitigated: bool
    status: str
    activated_at: str
    expires_at: str
    created_at: str
    updated_at: str
    version: int


class PurgeRequest(TypedDict, total=False):
    id: str
    zone_id: str
    purge_type: str
    urls: Optional[List[str]]
    status: str
    requested_at: str
    origin_shield_degraded: bool
    created_at: str
    updated_at: str
    version: int


class IpBlock(TypedDict, total=False):
    id: str
    zone_id: str
    ip: str
    ip_version: str
    reason: str
    status: str
    confirmed_at: Optional[str]
    expires_at: str
    blocked_seconds_total: Optional[int]
    created_at: str
    updated_at: str
    version: int


class AbuseReport(TypedDict, total=False):
    id: str
    zone_id: str
    reporter_email: str
    category: str
    description: str
    target_url: str
    reporter_trust_score: int
    priority_score: int
    routing_mode: str
    forwarded_to: Optional[str]
    status: str
    forwarded_at: Optional[str]
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
