"""Domain types: entity TypedDicts, status enums, role enum.

Field names follow the PRD exactly. Primary resources carry id, created_at,
updated_at, version (PRD §2.5). Holdings rows, committee votes, and client
notices are immutable ledger-style records carrying only id and created_at.
"""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    RESEARCH_OPS = "ResearchOps"
    ANALYST = "Analyst"
    LICENSE_ADMIN = "LicenseAdmin"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    FUND_COMPANY_REP = "FundCompanyRep"


class CompanyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    OFFBOARDED = "OFFBOARDED"


class CommercialRelationship(str, Enum):
    NONE = "NONE"
    LICENSED_CLIENT = "LICENSED_CLIENT"
    INDEX_LICENSEE = "INDEX_LICENSEE"


class FundStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    LIQUIDATED = "LIQUIDATED"


class AssetClass(str, Enum):
    EQUITY = "EQUITY"
    BOND = "BOND"
    CASH = "CASH"
    OTHER = "OTHER"


class Sector(str, Enum):
    TECH = "TECH"
    HEALTH = "HEALTH"
    FINANCE = "FINANCE"
    ENERGY = "ENERGY"
    CONSUMER = "CONSUMER"
    INDUSTRIAL = "INDUSTRIAL"
    MIXED = "MIXED"


class MethodologyKind(str, Enum):
    QUANTITATIVE = "QUANTITATIVE"
    ANALYST = "ANALYST"


class MethodologyStatus(str, Enum):
    DRAFT = "DRAFT"
    EFFECTIVE = "EFFECTIVE"
    SUPERSEDED = "SUPERSEDED"
    RETIRED = "RETIRED"


class ChangeStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    EFFECTIVE = "EFFECTIVE"
    WITHDRAWN = "WITHDRAWN"


class RatingKind(str, Enum):
    QUANTITATIVE = "QUANTITATIVE"
    ANALYST = "ANALYST"


class RatingStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    COMMITTEE_REVIEW = "COMMITTEE_REVIEW"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"
    WITHDRAWN = "WITHDRAWN"
    RESTATED = "RESTATED"


class SuppressionReason(str, Enum):
    NONE = "NONE"
    CONFLICT_HOLD = "CONFLICT_HOLD"
    DISPUTE_HOLD = "DISPUTE_HOLD"


class ProposalStatus(str, Enum):
    OPEN = "OPEN"
    QUORUM_MET = "QUORUM_MET"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class Vote(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    ABSTAIN = "ABSTAIN"


class LicenseeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class Tier(str, Enum):
    DISPLAY = "DISPLAY"
    REDISTRIBUTION = "REDISTRIBUTION"
    DERIVED_WORKS = "DERIVED_WORKS"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class SeatStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class AuditStatus(str, Enum):
    OPEN = "OPEN"
    FINDINGS_FILED = "FINDINGS_FILED"
    CLOSED_NO_ACTION = "CLOSED_NO_ACTION"
    CLOSED_WITH_PENALTY = "CLOSED_WITH_PENALTY"


class DisputedField(str, Enum):
    HOLDINGS = "HOLDINGS"
    TRAILING_RETURN_3Y = "TRAILING_RETURN_3Y"
    TRAILING_RETURN_5Y = "TRAILING_RETURN_5Y"
    RISK_SCORE = "RISK_SCORE"
    CATEGORY = "CATEGORY"


class DisputeStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_INVESTIGATION = "UNDER_INVESTIGATION"
    RESOLVED_ACCEPTED = "RESOLVED_ACCEPTED"
    RESOLVED_REJECTED = "RESOLVED_REJECTED"


class IndexStatus(str, Enum):
    DRAFT = "DRAFT"
    LIVE = "LIVE"
    SUSPENDED = "SUSPENDED"
    RETIRED = "RETIRED"


class FlagKind(str, Enum):
    COMMERCIAL_RATING_CONFLICT = "COMMERCIAL_RATING_CONFLICT"
    INDEX_LICENSOR_CONFLICT = "INDEX_LICENSOR_CONFLICT"


class FlagStatus(str, Enum):
    OPEN = "OPEN"
    WAIVED = "WAIVED"
    RESOLVED = "RESOLVED"


class NoticeChannel(str, Enum):
    EMAIL = "EMAIL"
    PORTAL = "PORTAL"
    API = "API"


class FundCompany(TypedDict, total=False):
    id: str
    legal_name: str
    company_status: str
    commercial_relationship: str
    open_dispute_count: int
    quality_score_bp: int
    created_at: str
    updated_at: str
    version: int


class Fund(TypedDict, total=False):
    id: str
    fund_company_id: str
    ticker: str
    inception_date: str
    fund_status: str
    category_id: Optional[str]
    category_assignment_revision: int
    trailing_return_3y_bp: int
    trailing_return_5y_bp: Optional[int]
    risk_score_bp: int
    created_at: str
    updated_at: str
    version: int


class Holding(TypedDict, total=False):
    # Immutable ledger-style record: id + created_at only (no updated_at/version)
    id: str
    fund_id: str
    as_of_date: str
    security_ticker: str
    asset_class: str
    sector: str
    weight_bp: int
    created_at: str


class Category(TypedDict, total=False):
    id: str
    category_code: str
    dominant_asset_class: str
    dominant_sector: str
    min_weight_bp: int
    active: bool
    created_at: str
    updated_at: str
    version: int


class Methodology(TypedDict, total=False):
    id: str
    methodology_code: str
    methodology_kind: str
    version_number: int
    effective_from: str
    effective_to: Optional[str]
    methodology_status: str
    weight_return_bp: int
    weight_risk_bp: int
    rating_ceilings: list
    created_at: str
    updated_at: str
    version: int


class MethodologyChange(TypedDict, total=False):
    id: str
    methodology_id: str
    change_status: str
    restatement_required: bool
    effective_date: str
    client_notice_sent: bool
    restated_rating_count: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Rating(TypedDict, total=False):
    id: str
    fund_id: str
    methodology_id: str
    rating_kind: str
    stars: Optional[int]
    analyst_grade: Optional[str]
    rating_status: str
    as_of_date: str
    provisional_stars: Optional[int]
    restatement_of_id: Optional[str]
    suppression_reason: str
    created_at: str
    updated_at: str
    version: int


class RatingProposal(TypedDict, total=False):
    id: str
    rating_id: str
    proposed_grade: str
    proposed_by: str
    proposal_status: str
    approvals: int
    rejections: int
    created_at: str
    updated_at: str
    version: int


class CommitteeVote(TypedDict, total=False):
    # Immutable ledger-style record: id + created_at only
    id: str
    proposal_id: str
    voter_id: str
    vote: str
    created_at: str


class Licensee(TypedDict, total=False):
    id: str
    licensee_name: str
    licensee_status: str
    arrears_cents: int
    created_at: str
    updated_at: str
    version: int


class LicenseAgreement(TypedDict, total=False):
    id: str
    licensee_id: str
    tier: str
    seat_limit: int
    seats_in_use: int
    effective_from: str
    effective_to: Optional[str]
    agreement_status: str
    base_fee_cents: int
    audit_count: int
    created_at: str
    updated_at: str
    version: int


class SeatEntitlement(TypedDict, total=False):
    id: str
    agreement_id: str
    workstation_user_id: str
    seat_status: str
    entitled_data_scope: str
    created_at: str
    updated_at: str
    version: int


class LicenseAudit(TypedDict, total=False):
    id: str
    agreement_id: str
    audit_status: str
    unlicensed_uses_found: int
    penalty_cents: int
    created_at: str
    updated_at: str
    version: int


class DataDispute(TypedDict, total=False):
    id: str
    fund_id: str
    raised_by_company_id: str
    disputed_field: str
    corrected_value: Optional[int]
    dispute_status: str
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class IndexDefinition(TypedDict, total=False):
    id: str
    index_code: str
    methodology_id: str
    max_constituents: int
    single_constituent_cap_bp: int
    index_status: str
    licensed_agreement_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class IndexConstituent(TypedDict, total=False):
    # Immutable ledger-style record: id + created_at only
    id: str
    index_id: str
    fund_id: str
    target_weight_bp: int
    final_weight_bp: Optional[int]
    created_at: str


class ConflictFlag(TypedDict, total=False):
    id: str
    fund_id: str
    flag_kind: str
    flag_status: str
    blocking: bool
    created_at: str
    updated_at: str
    version: int


class ClientNotice(TypedDict, total=False):
    # Immutable ledger-style record: id + created_at only
    id: str
    methodology_change_id: str
    licensee_id: str
    notice_channel: str
    notice_sent_at: str
    created_at: str
