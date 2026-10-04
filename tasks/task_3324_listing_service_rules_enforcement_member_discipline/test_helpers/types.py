"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    ASSOCIATION_STAFF = "AssociationStaff"
    MEMBER = "Member"
    GRIEVANCE_MEMBER = "GrievanceMember"
    HEARING_PANELIST = "HearingPanelist"


class ConsolidationState(str, Enum):
    ACTIVE = "ACTIVE"
    MERGING = "MERGING"
    MERGED = "MERGED"


class PolicyRevisionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class CompDisplayMode(str, Enum):
    COMP_DISPLAY_ON = "COMP_DISPLAY_ON"
    COMP_DISPLAY_OFF = "COMP_DISPLAY_OFF"


class MembershipState(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class MlsAccessState(str, Enum):
    ENABLED = "ENABLED"
    DISABLED = "DISABLED"


class OfficeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class DuesPeriodStatus(str, Enum):
    OPEN = "OPEN"
    BILLED = "BILLED"
    RECONCILED = "RECONCILED"


class DuesInvoiceStatus(str, Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    WAIVED = "WAIVED"


class ListingStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    PENDING = "PENDING"
    SOLD = "SOLD"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class AccuracyFlag(str, Enum):
    CLEAN = "CLEAN"
    FLAGGED = "FLAGGED"


class RuleCode(str, Enum):
    LATE_LISTING = "LATE_LISTING"
    LATE_STATUS = "LATE_STATUS"
    INACCURACY = "INACCURACY"
    CLEAR_COOP = "CLEAR_COOP"
    COMP_OFFER = "COMP_OFFER"
    FEED_ABUSE = "FEED_ABUSE"


class CitationSource(str, Enum):
    STAFF = "STAFF"
    AUTO_LATE_LISTING = "AUTO_LATE_LISTING"
    AUTO_LATE_STATUS = "AUTO_LATE_STATUS"


class CitationStatus(str, Enum):
    OPEN = "OPEN"
    HEARING_PENDING = "HEARING_PENDING"
    PAID = "PAID"
    WAIVED = "WAIVED"
    ESCALATED = "ESCALATED"


class FineScheduleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class EthicsCaseStatus(str, Enum):
    FILED = "FILED"
    GRIEVANCE_SCREENING = "GRIEVANCE_SCREENING"
    DISMISSED = "DISMISSED"
    HEARING_SCHEDULED = "HEARING_SCHEDULED"
    HEARD = "HEARD"
    DECIDED = "DECIDED"
    APPEALED = "APPEALED"
    FINAL = "FINAL"


class ScreeningOutcome(str, Enum):
    DISMISSED = "DISMISSED"
    FORWARDED = "FORWARDED"


class ArbitrationCaseStatus(str, Enum):
    FILED = "FILED"
    MEDIATION_OFFERED = "MEDIATION_OFFERED"
    MEDIATED = "MEDIATED"
    ARBITRATION_SCHEDULED = "ARBITRATION_SCHEDULED"
    HEARD = "HEARD"
    AWARDED = "AWARDED"


class MediationOutcome(str, Enum):
    SETTLED = "SETTLED"
    DECLINED = "DECLINED"


class HearingPanelCaseType(str, Enum):
    CITATION = "CITATION"
    ETHICS = "ETHICS"
    ARBITRATION = "ARBITRATION"


class HearingPanelStatus(str, Enum):
    CONVENED = "CONVENED"
    HEARING_HELD = "HEARING_HELD"
    DECIDED = "DECIDED"


class PanelDecision(str, Enum):
    UPHOLD = "UPHOLD"
    OVERTURN = "OVERTURN"


class DataLicenseScope(str, Enum):
    IDX = "IDX"
    VOW = "VOW"
    BACKOFFICE = "BACKOFFICE"


class DataLicenseStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class FeedSyncState(str, Enum):
    CURRENT = "CURRENT"
    STALE = "STALE"


class ConsolidationEventStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    EXECUTED = "EXECUTED"
    CANCELLED = "CANCELLED"


class Association(TypedDict, total=False):
    id: str
    association_code: str
    name: str
    consolidation_state: str
    consolidated_into_id: Optional[str]
    membership_dues_cents: int
    late_fee_tier1_cents: int
    late_fee_tier2_cents: int
    sanction_credit_cap_cents: int
    created_at: str
    updated_at: str
    version: int


class PolicyRevision(TypedDict, total=False):
    id: str
    association_id: str
    revision_code: str
    effective_at: str
    comp_display_mode: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict, total=False):
    id: str
    association_id: str
    member_nr: str
    full_name: str
    membership_state: str
    mls_access_state: str
    sanction_credit_balance_cents: int
    strikes_12m: int
    hearing_panel_exclusions: List[str]
    created_at: str
    updated_at: str
    version: int


class Office(TypedDict, total=False):
    id: str
    association_id: str
    office_code: str
    broker_member_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DuesPeriod(TypedDict, total=False):
    id: str
    association_id: str
    year: int
    period_start_date: str
    due_date: str
    grace_end_date: str
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DuesInvoice(TypedDict, total=False):
    id: str
    dues_period_id: str
    member_id: str
    base_amount_cents: int
    days_overdue_at_issue: int
    late_fee_cents: int
    credit_applied_cents: int
    amount_due_cents: int
    status: str
    paid_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Listing(TypedDict, total=False):
    id: str
    office_id: str
    listing_member_id: str
    mls_number: str
    property_address: str
    list_price_cents: int
    public_marketing_at: Optional[str]
    status: str
    accuracy_flag: str
    policy_revision_id: Optional[str]
    offer_comp_cents: int
    activated_at: Optional[str]
    status_changed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StatusChange(TypedDict, total=False):
    id: str
    listing_id: str
    from_status: str
    to_status: str
    business_effective_at: str
    recorded_at: str
    late_by_hours: int
    auto_citation_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Citation(TypedDict, total=False):
    id: str
    association_id: str
    member_id: str
    listing_id: Optional[str]
    rule_code: str
    source: str
    fine_schedule_key: str
    fine_amount_cents: int
    hearing_requested: bool
    assessed_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class FineSchedule(TypedDict, total=False):
    id: str
    association_id: str
    rule_code: str
    fine_amount_cents: int
    effective_from: str
    effective_to: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class EthicsCase(TypedDict, total=False):
    id: str
    association_id: str
    complainant_member_id: str
    respondent_member_id: str
    article_code: str
    grievance_review_due_at: str
    screening_outcome: Optional[str]
    filed_at: str
    status: str
    sanction_cents: int
    created_at: str
    updated_at: str
    version: int


class ArbitrationCase(TypedDict, total=False):
    id: str
    association_id: str
    complainant_member_id: str
    respondent_member_id: str
    listing_id: str
    claim_amount_cents: int
    filed_at: str
    status: str
    award_amount_cents: int
    procuring_cause_factor_scores: Dict[str, Any]
    created_at: str
    updated_at: str
    version: int


class HearingPanel(TypedDict, total=False):
    id: str
    association_id: str
    case_type: str
    case_id: str
    selected_member_ids: List[str]
    convene_at: Optional[str]
    decision: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DataLicense(TypedDict, total=False):
    id: str
    association_id: str
    licensee_name: str
    scope: str
    display_ruleset_version: int
    listing_field_allowlist: List[str]
    status: str
    feed_sync_state: str
    last_audit_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ConsolidationEvent(TypedDict, total=False):
    """Append-only style entity: carries id + created_at only (no updated_at, no version)."""
    id: str
    survivor_association_id: str
    absorbed_association_id: str
    effective_at: str
    status: str
    created_at: str
