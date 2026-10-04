"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


class PatronStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class CredentialStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    REVOKED = "REVOKED"


class LibraryStatus(str, Enum):
    ACTIVE = "ACTIVE"
    WITHDRAWN = "WITHDRAWN"


class WorkAvailability(str, Enum):
    AVAILABLE = "AVAILABLE"
    EMBARGOED = "EMBARGOED"
    WITHDRAWN = "WITHDRAWN"


class ScanBatchStatus(str, Enum):
    OPEN = "OPEN"
    SEALED = "SEALED"
    REJECTED = "REJECTED"


class ScanItemStatus(str, Enum):
    DEPOSITED = "DEPOSITED"
    LENDABLE = "LENDABLE"
    ON_LOAN = "ON_LOAN"
    RETIRED = "RETIRED"


class ConditionGrade(str, Enum):
    FINE = "FINE"
    GOOD = "GOOD"
    FAIR = "FAIR"
    FRAGILE = "FRAGILE"


class LoanKind(str, Enum):
    STANDARD = "STANDARD"
    SHORT_READ = "SHORT_READ"


class LoanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETURNED = "RETURNED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class WaitlistEntryStatus(str, Enum):
    OPEN = "OPEN"
    OFFERED = "OFFERED"
    CLAIMED = "CLAIMED"
    EXPIRED_OFFER = "EXPIRED_OFFER"
    CANCELLED = "CANCELLED"


class CrawlJobStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    BLOCKED = "BLOCKED"
    CANCELLED = "CANCELLED"


class PlaybackStatus(str, Enum):
    PLAYABLE = "PLAYABLE"
    SUPPRESSED = "SUPPRESSED"


class PlaybackMode(str, Enum):
    FULL = "FULL"
    DEGRADED = "DEGRADED"
    SUPPRESSED = "SUPPRESSED"
    NOT_FOUND = "NOT_FOUND"


class DirectiveScope(str, Enum):
    CRAWL_ONLY = "CRAWL_ONLY"
    PLAYBACK_ONLY = "PLAYBACK_ONLY"
    BOTH = "BOTH"


class DirectiveStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETRACTED = "RETRACTED"


class SubjectKind(str, Enum):
    WORK = "WORK"
    CAPTURE_URL_PREFIX = "CAPTURE_URL_PREFIX"


class RightsRequestStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    LEGAL_HOLD = "LEGAL_HOLD"
    UPHELD_REMOVED = "UPHELD_REMOVED"
    DISMISSED = "DISMISSED"


class GrantStatus(str, Enum):
    OPEN = "OPEN"
    EXHAUSTED = "EXHAUSTED"
    CLOSED = "CLOSED"


class BudgetLineCategory(str, Enum):
    STORAGE = "STORAGE"
    BANDWIDTH = "BANDWIDTH"
    SCAN_LABOR = "SCAN_LABOR"
    PETABYTE_INSURANCE = "PETABYTE_INSURANCE"


class BudgetLineStatus(str, Enum):
    OPEN = "OPEN"
    SETTLED = "SETTLED"
    RELEASED = "RELEASED"


class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    ADMIN = "Admin"
    PATRON = "Patron"
    ACCESSIBILITY_OFFICER = "AccessibilityOfficer"
    LIBRARY_ADMIN = "LibraryAdmin"
    SCAN_OPERATOR = "ScanOperator"
    CRAWL_OPERATOR = "CrawlOperator"
    LEGAL_REVIEWER = "LegalReviewer"
    FINANCE_ADMIN = "FinanceAdmin"


class Patron(TypedDict, total=False):
    id: str
    email: str
    full_name: str
    status: str
    active_loan_count: int
    strike_count: int
    max_concurrent_loans: int
    created_at: str
    updated_at: str
    version: int


class AccessibilityCredential(TypedDict, total=False):
    id: str
    patron_id: str
    certifier_reference: str
    status: str
    decided_by: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PartnerLibrary(TypedDict, total=False):
    id: str
    library_code: str
    display_name: str
    storage_commitment_years: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Work(TypedDict, total=False):
    id: str
    title: str
    author: str
    publication_year: int
    availability: str
    created_at: str
    updated_at: str
    version: int


class ScanBatch(TypedDict, total=False):
    id: str
    operator_code: str
    status: str
    item_count: int
    page_count: int
    created_at: str
    updated_at: str
    version: int


class ScanItem(TypedDict, total=False):
    id: str
    batch_id: str
    work_id: str
    owning_library_id: str
    page_count: int
    condition_grade: str
    status: str
    lendable: bool
    created_at: str
    updated_at: str
    version: int


class Loan(TypedDict, total=False):
    id: str
    item_id: str
    patron_id: str
    loan_kind: str
    status: str
    checked_out_at: str
    due_at: str
    renewed: bool
    created_at: str
    updated_at: str
    version: int


class WaitlistEntry(TypedDict, total=False):
    id: str
    work_id: str
    patron_id: str
    status: str
    offered_at: Optional[str]
    offer_expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CrawlJob(TypedDict, total=False):
    id: str
    seed_url: str
    at_risk: bool
    scheduled_at: str
    requests_per_minute: int
    status: str
    captures_produced: int
    duplicates_skipped: int
    storage_cost_cents: int
    created_at: str
    updated_at: str
    version: int


class Capture(TypedDict, total=False):
    # immutable: carries ONLY id + created_at (no updated_at, no version)
    id: str
    crawl_job_id: str
    url: str
    content_hash: str
    captured_at: str
    has_dynamic_content: bool
    playback_status: str
    created_at: str


class ExclusionDirective(TypedDict, total=False):
    id: str
    url_prefix: str
    scope: str
    status: str
    reason: str
    created_at: str
    updated_at: str
    version: int


class RightsRequest(TypedDict, total=False):
    id: str
    subject_kind: str
    work_id: Optional[str]
    url_prefix: Optional[str]
    claimant_name: str
    filed_by: str
    status: str
    reviewed_by: Optional[str]
    decided_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FundingGrant(TypedDict, total=False):
    id: str
    donor_name: str
    amount_cents: int
    reserved_cents: int
    spent_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class BudgetLine(TypedDict, total=False):
    id: str
    grant_id: str
    category: str
    budget_reservation_cents: int
    actual_spend_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int
