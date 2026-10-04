"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    RESEARCHER = "Researcher"
    TRIAGER = "Triager"
    PROGRAM_ADMIN = "ProgramAdmin"
    PLATFORM_ADMIN = "PlatformAdmin"


class ProgramStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CLOSED = "CLOSED"


class ProgramVisibility(str, Enum):
    PUBLIC = "PUBLIC"
    PRIVATE = "PRIVATE"


class AssetCriticality(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class AssetStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class ResearcherStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    BANNED = "BANNED"


class TaxDocumentStatus(str, Enum):
    MISSING = "MISSING"
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"


class ResearcherTier(str, Enum):
    NOVICE = "NOVICE"
    ESTABLISHED = "ESTABLISHED"
    ELITE = "ELITE"


class InvitationStatus(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"


class ReportStatus(str, Enum):
    NEW = "NEW"
    TRIAGED = "TRIAGED"
    NEEDS_INFO = "NEEDS_INFO"
    VALIDATED = "VALIDATED"
    RESOLVED = "RESOLVED"
    DUPLICATE = "DUPLICATE"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    INFORMATIVE = "INFORMATIVE"


class SeverityFinal(str, Enum):
    NONE = "NONE"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class VulnerabilityClass(str, Enum):
    XSS = "XSS"
    SQLI = "SQLI"
    CSRF = "CSRF"
    SSRF = "SSRF"
    AUTHZ = "AUTHZ"
    RCE = "RCE"
    OTHER = "OTHER"


class AwardType(str, Enum):
    BOUNTY = "BOUNTY"
    BONUS = "BONUS"
    RETEST = "RETEST"


class AwardStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    BLOCKED = "BLOCKED"
    PAID = "PAID"
    VOID = "VOID"


class AwardBlockReason(str, Enum):
    SANCTIONED_COUNTRY = "SANCTIONED_COUNTRY"
    TAX_DOCUMENT = "TAX_DOCUMENT"


class DisclosureStatus(str, Enum):
    REQUESTED = "REQUESTED"
    UNDER_NEGOTIATION = "UNDER_NEGOTIATION"
    AGREED = "AGREED"
    PUBLISHED = "PUBLISHED"
    DENIED = "DENIED"


class TicketStatus(str, Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    FIXED = "FIXED"
    VERIFIED = "VERIFIED"
    WONT_FIX = "WONT_FIX"


class BlackoutWindow(TypedDict):
    starts_at: str
    ends_at: str


# All entities carry the full common set (id, created_at, updated_at, version).


class Program(TypedDict, total=False):
    id: str
    name: str
    visibility: str
    status: str
    min_reputation: int
    response_sla_hours: int
    resolution_sla_days: int
    disclosure_window_days: int
    first_report_bonus_pct: float
    retest_award_cents: int
    bonus_cap_cents: int
    exposure_modifier: float
    bounty_pool_cents: int
    bounty_reserved_cents: int
    bounty_paid_cents: int
    total_withheld_cents: int
    available_pool_cents: int
    blackout_windows: List[BlackoutWindow]
    created_at: str
    updated_at: str
    version: int


class ScopeAsset(TypedDict, total=False):
    id: str
    program_id: str
    name: str
    asset_identifier: str
    criticality: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ScopeVersion(TypedDict, total=False):
    id: str
    program_id: str
    effective_from: str
    effective_to: Optional[str]
    in_scope_asset_ids: List[str]
    safe_harbor_text: Optional[str]
    version_seq: int
    created_at: str
    updated_at: str
    version: int


class Researcher(TypedDict, total=False):
    id: str
    handle: str
    email: str
    country_code: str
    status: str
    strike_count: int
    suspension_ends_at: Optional[str]
    reputation_lifetime: int
    reputation_rolling180: int
    tier: str
    tax_document_status: str
    tax_document_type: Optional[str]
    conduct_log: List[Dict[str, Any]]
    created_at: str
    updated_at: str
    version: int


class ProgramInvitation(TypedDict, total=False):
    id: str
    program_id: str
    researcher_id: str
    status: str
    issued_at: str
    expires_at: str
    reputation_at_issue: int
    created_at: str
    updated_at: str
    version: int


class Report(TypedDict, total=False):
    id: str
    program_id: str
    asset_id: str
    researcher_id: str
    duplicate_of_id: Optional[str]
    scope_version_id: str
    title: str
    description: str
    vulnerability_class: str
    status: str
    impact: Optional[int]
    exploitability: Optional[int]
    affected_scope: Optional[int]
    severity_score_base: Optional[float]
    severity_score_adjusted: Optional[float]
    severity_final: Optional[str]
    tier_at_validation: Optional[str]
    is_first_validated_report: Optional[bool]
    submitted_at: str
    first_response_at: Optional[str]
    triaged_at: Optional[str]
    validated_at: Optional[str]
    resolved_at: Optional[str]
    response_due_at: str
    resolution_due_at: Optional[str]
    response_breached: bool
    resolution_breached: bool
    created_at: str
    updated_at: str
    version: int


class Award(TypedDict, total=False):
    id: str
    report_id: str
    researcher_id: str
    award_type: str
    status: str
    amount_cents: int
    capped_by_pool: bool
    block_reason: Optional[str]
    withheld_cents: int
    net_paid_cents: int
    proposed_at: str
    approved_at: Optional[str]
    paid_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DisclosureRequest(TypedDict, total=False):
    id: str
    report_id: str
    researcher_id: str
    status: str
    proposed_publish_at: str
    agreed_publish_at: Optional[str]
    negotiation_round: int
    created_at: str
    updated_at: str
    version: int


class RemediationTicket(TypedDict, total=False):
    id: str
    report_id: str
    external_ref: str
    status: str
    due_at: str
    verified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
