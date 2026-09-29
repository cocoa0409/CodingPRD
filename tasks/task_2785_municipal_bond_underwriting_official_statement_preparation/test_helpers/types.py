"""Domain vocabulary for the municipal bond underwriting / official statement API.

Every literal in this module is copied verbatim from PRD.md so that test bodies
never spell an enum value inline.
"""


class UserRole:
    """PRD section 2.1 -- the six recognised values of ``X-User-Role``."""

    ISSUER_OFFICIAL = "IssuerOfficial"
    MUNICIPAL_ADVISOR = "MunicipalAdvisor"
    UNDERWRITER = "Underwriter"
    BOND_COUNSEL = "BondCounsel"
    RATING_ANALYST = "RatingAnalyst"
    COMPLIANCE_OFFICER = "ComplianceOfficer"

    ALL = (
        ISSUER_OFFICIAL,
        MUNICIPAL_ADVISOR,
        UNDERWRITER,
        BOND_COUNSEL,
        RATING_ANALYST,
        COMPLIANCE_OFFICER,
    )
    # Roles whose X-User-ID must resolve to a domain row (PRD section 2.1).
    ENTITY_BACKED = (ISSUER_OFFICIAL, MUNICIPAL_ADVISOR, UNDERWRITER)
    # Roles whose X-User-ID is an opaque identifier (PRD section 2.1).
    OPAQUE = (BOND_COUNSEL, RATING_ANALYST, COMPLIANCE_OFFICER)


class EntityType:
    """PRD section 3.1 -- governmental character of an issuer."""

    CITY = "CITY"
    COUNTY = "COUNTY"
    SCHOOL_DISTRICT = "SCHOOL_DISTRICT"
    AUTHORITY = "AUTHORITY"
    STATE = "STATE"

    ALL = (CITY, COUNTY, SCHOOL_DISTRICT, AUTHORITY, STATE)


class FirmType:
    """PRD section 3.1 -- registered capacity of a firm."""

    UNDERWRITER = "UNDERWRITER"
    MUNICIPAL_ADVISOR = "MUNICIPAL_ADVISOR"
    DUAL_REGISTERED = "DUAL_REGISTERED"

    ALL = (UNDERWRITER, MUNICIPAL_ADVISOR, DUAL_REGISTERED)
    # Firm types that may back a MunicipalAdvisor actor (PRD section 2.1).
    ADMITS_ADVISOR = (MUNICIPAL_ADVISOR, DUAL_REGISTERED)
    # Firm types that may back an Underwriter actor (PRD section 2.1).
    ADMITS_UNDERWRITER = (UNDERWRITER, DUAL_REGISTERED)


class TaxStatus:
    """PRD section 3.2 -- federal tax treatment of the series."""

    TAX_EXEMPT = "TAX_EXEMPT"
    TAXABLE = "TAXABLE"
    AMT = "AMT"

    ALL = (TAX_EXEMPT, TAXABLE, AMT)


class SaleMethod:
    """PRD section 3.6 -- the sale-method fork."""

    UNDETERMINED = "UNDETERMINED"
    COMPETITIVE = "COMPETITIVE"
    NEGOTIATED = "NEGOTIATED"

    ALL = (UNDETERMINED, COMPETITIVE, NEGOTIATED)
    # Values a client may actually supply to designate-sale-method.
    DESIGNATABLE = (COMPETITIVE, NEGOTIATED)


class GrossSpreadBasis:
    """PRD section 3.8 -- frozen at designation, selects the spread formula."""

    UNDETERMINED = "UNDETERMINED"
    COMPETITIVE = "COMPETITIVE"
    NEGOTIATED = "NEGOTIATED"

    ALL = (UNDETERMINED, COMPETITIVE, NEGOTIATED)


class DealStatus:
    """PRD sections 3.2, 3.6, 3.8, 3.9 -- the deal state machine."""

    DRAFT = "DRAFT"
    STRUCTURING = "STRUCTURING"
    PRICING_COMPETITIVE = "PRICING_COMPETITIVE"
    PRICING_NEGOTIATED = "PRICING_NEGOTIATED"
    PRICED = "PRICED"
    AWARDED = "AWARDED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"

    ALL = (
        DRAFT,
        STRUCTURING,
        PRICING_COMPETITIVE,
        PRICING_NEGOTIATED,
        PRICED,
        AWARDED,
        CLOSED,
        CANCELLED,
    )
    PRICING_BRANCHES = (PRICING_COMPETITIVE, PRICING_NEGOTIATED)
    TERMINAL = (CLOSED, CANCELLED)
    CANCELLABLE = (
        DRAFT,
        STRUCTURING,
        PRICING_COMPETITIVE,
        PRICING_NEGOTIATED,
        PRICED,
    )


class DisclosureClearance:
    """PRD section 2.9 -- derived tri-state on the deal."""

    PENDING = "PENDING"
    CLEARED = "CLEARED"
    BLOCKED = "BLOCKED"

    ALL = (PENDING, CLEARED, BLOCKED)


class HandoffStatus:
    """PRD section 3.9 -- post-issuance handoff status on the deal."""

    NOT_STARTED = "NOT_STARTED"
    READY = "READY"

    ALL = (NOT_STARTED, READY)


class RatingBasis:
    """PRD sections 3.2, 3.3 -- whose rating a maturity is marketed on."""

    UNDERLYING = "UNDERLYING"
    ENHANCED = "ENHANCED"

    ALL = (UNDERLYING, ENHANCED)


class EnhancementType:
    """PRD section 3.3 -- form the credit enhancement takes."""

    BOND_INSURANCE = "BOND_INSURANCE"
    LETTER_OF_CREDIT = "LETTER_OF_CREDIT"
    STATE_INTERCEPT = "STATE_INTERCEPT"

    ALL = (BOND_INSURANCE, LETTER_OF_CREDIT, STATE_INTERCEPT)


class EnhancementStatus:
    """PRD sections 3.3, 3.9 -- enhancement lifecycle."""

    PROPOSED = "PROPOSED"
    COMMITTED = "COMMITTED"
    WITHDRAWN = "WITHDRAWN"
    DECLINED = "DECLINED"

    ALL = (PROPOSED, COMMITTED, WITHDRAWN, DECLINED)
    TERMINAL = (WITHDRAWN, DECLINED)


class OfficialStatementStatus:
    """PRD section 3.4 -- the official statement review loop and its exits."""

    DRAFTING = "DRAFTING"
    IN_REVIEW = "IN_REVIEW"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    PRELIMINARY_POSTED = "PRELIMINARY_POSTED"
    FINAL_POSTED = "FINAL_POSTED"
    SUPERSEDED = "SUPERSEDED"
    WITHDRAWN = "WITHDRAWN"

    ALL = (
        DRAFTING,
        IN_REVIEW,
        REVISION_REQUESTED,
        PRELIMINARY_POSTED,
        FINAL_POSTED,
        SUPERSEDED,
        WITHDRAWN,
    )
    # PRD section 3.4: statuses that a newly created statement supersedes.
    SUPERSEDABLE = (DRAFTING, IN_REVIEW, REVISION_REQUESTED)
    # PRD section 3.4: statuses withdrawn when the owning deal is cancelled.
    WITHDRAWABLE_ON_DEAL_CANCEL = (
        DRAFTING,
        IN_REVIEW,
        REVISION_REQUESTED,
        PRELIMINARY_POSTED,
    )
    # PRD section 2.9: clearance is CLEARED only from these three.
    CLEARED_STATUSES = (IN_REVIEW, PRELIMINARY_POSTED, FINAL_POSTED)
    # PRD section 2.9: clearance is BLOCKED only from these two.
    BLOCKED_STATUSES = (REVISION_REQUESTED, WITHDRAWN)
    TERMINAL = (FINAL_POSTED, SUPERSEDED, WITHDRAWN)


class SectionType:
    """PRD section 3.4 -- disclosure categories."""

    RISK_FACTOR = "RISK_FACTOR"
    TAX_MATTERS = "TAX_MATTERS"
    CONTINUING_DISCLOSURE = "CONTINUING_DISCLOSURE"
    UNDERWRITING = "UNDERWRITING"
    GENERAL = "GENERAL"

    ALL = (RISK_FACTOR, TAX_MATTERS, CONTINUING_DISCLOSURE, UNDERWRITING, GENERAL)
    # PRD section 3.4: the four mandatory categories; GENERAL never contributes.
    MANDATORY = (RISK_FACTOR, TAX_MATTERS, CONTINUING_DISCLOSURE, UNDERWRITING)


class ReviewStatus:
    """PRD section 3.4 -- per-section review state."""

    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    NEEDS_REVISION = "NEEDS_REVISION"

    ALL = (DRAFT, APPROVED, NEEDS_REVISION)
    # PRD section 3.4: both entry paths into approval.
    APPROVABLE_FROM = (DRAFT, NEEDS_REVISION)


class UndertakingStatus:
    """PRD section 3.4 -- continuing disclosure undertaking lifecycle."""

    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"

    ALL = (DRAFT, ACTIVE, SUPERSEDED)


class RatingAgency:
    """PRD section 3.5 -- the four rating agencies."""

    MOODYS = "MOODYS"
    SP = "SP"
    FITCH = "FITCH"
    KBRA = "KBRA"

    ALL = (MOODYS, SP, FITCH, KBRA)


class EngagementStatus:
    """PRD section 3.5 -- rating engagement lifecycle."""

    REQUESTED = "REQUESTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    INFO_REQUESTED = "INFO_REQUESTED"
    RATED = "RATED"
    WITHDRAWN = "WITHDRAWN"

    ALL = (REQUESTED, UNDER_REVIEW, INFO_REQUESTED, RATED, WITHDRAWN)
    TERMINAL = (RATED, WITHDRAWN)
    # PRD section 3.5: engagements withdrawn when the owning deal is cancelled.
    WITHDRAWABLE_ON_DEAL_CANCEL = (REQUESTED, UNDER_REVIEW, INFO_REQUESTED)


class Outlook:
    """PRD section 3.5 -- rating outlook."""

    POSITIVE = "POSITIVE"
    STABLE = "STABLE"
    NEGATIVE = "NEGATIVE"
    DEVELOPING = "DEVELOPING"

    ALL = (POSITIVE, STABLE, NEGATIVE, DEVELOPING)


class PresentationStatus:
    """PRD section 3.5 -- rating presentation lifecycle."""

    SCHEDULED = "SCHEDULED"
    HELD = "HELD"
    CANCELLED = "CANCELLED"

    ALL = (SCHEDULED, HELD, CANCELLED)
    TERMINAL = (HELD, CANCELLED)


class CascadeReason:
    """PRD sections 3.3, 3.4, 3.9 -- reasons written by cascades, never by clients."""

    DISCLOSURE_BLOCKED = "DISCLOSURE_BLOCKED"
    DEAL_CANCELLED = "DEAL_CANCELLED"
    DISCLOSURE_BLOCKED_PENDING_OS_REVISION = "DISCLOSURE_BLOCKED_PENDING_OS_REVISION"


class MemberRole:
    """PRD section 3.6 -- syndicate seat role."""

    SENIOR_MANAGER = "SENIOR_MANAGER"
    CO_MANAGER = "CO_MANAGER"
    SELLING_GROUP = "SELLING_GROUP"

    ALL = (SENIOR_MANAGER, CO_MANAGER, SELLING_GROUP)
    # PRD section 3.7: MEMBER and STOCK orders require one of these.
    SYNDICATE_DEMAND_ELIGIBLE = (SENIOR_MANAGER, CO_MANAGER)


class MemberStatus:
    """PRD section 3.6 -- syndicate seat state."""

    ACTIVE = "ACTIVE"
    RESIGNED = "RESIGNED"

    ALL = (ACTIVE, RESIGNED)


class PeriodType:
    """PRD section 3.7 -- investor class of an order period."""

    RETAIL = "RETAIL"
    INSTITUTIONAL = "INSTITUTIONAL"

    ALL = (RETAIL, INSTITUTIONAL)


class PriorityPolicy:
    """PRD section 3.7 -- which order types a period admits."""

    STANDARD_PRIORITY = "STANDARD_PRIORITY"
    RETAIL_ONLY = "RETAIL_ONLY"

    ALL = (STANDARD_PRIORITY, RETAIL_ONLY)


class OrderPeriodStatus:
    """PRD section 3.7 -- order period lifecycle."""

    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"

    ALL = (SCHEDULED, OPEN, CLOSED, SETTLED, CANCELLED)
    TERMINAL = (SETTLED, CANCELLED)
    # PRD section 3.7: periods cancelled by deal cancellation.
    CANCELLABLE_ON_DEAL_CANCEL = (SCHEDULED, OPEN, CLOSED)


class OrderType:
    """PRD section 3.7 -- priority tier of an order, tier one through four."""

    RETAIL = "RETAIL"
    INSTITUTIONAL_PRIORITY = "INSTITUTIONAL_PRIORITY"
    MEMBER = "MEMBER"
    STOCK = "STOCK"

    ALL = (RETAIL, INSTITUTIONAL_PRIORITY, MEMBER, STOCK)
    # PRD section 3.7: the waterfall's tier order, one through four.
    TIER_ORDER = (RETAIL, INSTITUTIONAL_PRIORITY, MEMBER, STOCK)


class OrderStatus:
    """PRD sections 3.7, 3.9 -- order lifecycle."""

    PENDING = "PENDING"
    ALLOTTED = "ALLOTTED"
    PARTIALLY_ALLOTTED = "PARTIALLY_ALLOTTED"
    UNFILLED = "UNFILLED"
    CANCELLED = "CANCELLED"

    ALL = (PENDING, ALLOTTED, PARTIALLY_ALLOTTED, UNFILLED, CANCELLED)
    # PRD section 3.7: statuses that count toward par already allotted.
    ALLOTTED_ANY = (ALLOTTED, PARTIALLY_ALLOTTED)
    # PRD section 3.7: statuses returned to PENDING by a reopen.
    REOPENABLE = (ALLOTTED, PARTIALLY_ALLOTTED, UNFILLED)
    # PRD section 3.9: statuses cancelled by deal cancellation.
    CANCELLABLE_ON_DEAL_CANCEL = (PENDING, ALLOTTED, PARTIALLY_ALLOTTED, UNFILLED)


class DocType:
    """PRD section 3.9 -- the seven closing document types."""

    BOND_OPINION = "BOND_OPINION"
    TAX_CERTIFICATE = "TAX_CERTIFICATE"
    ISSUE_PRICE_CERTIFICATE = "ISSUE_PRICE_CERTIFICATE"
    CONTINUING_DISCLOSURE_AGREEMENT = "CONTINUING_DISCLOSURE_AGREEMENT"
    UNDERWRITER_RECEIPT = "UNDERWRITER_RECEIPT"
    G17_DISCLOSURE_LETTER = "G17_DISCLOSURE_LETTER"
    NOTICE_OF_SALE_CERTIFICATE = "NOTICE_OF_SALE_CERTIFICATE"

    ALL = (
        BOND_OPINION,
        TAX_CERTIFICATE,
        ISSUE_PRICE_CERTIFICATE,
        CONTINUING_DISCLOSURE_AGREEMENT,
        UNDERWRITER_RECEIPT,
        G17_DISCLOSURE_LETTER,
        NOTICE_OF_SALE_CERTIFICATE,
    )
    # PRD section 3.9: the five documents every award creates.
    ALWAYS_CREATED = (
        BOND_OPINION,
        TAX_CERTIFICATE,
        ISSUE_PRICE_CERTIFICATE,
        CONTINUING_DISCLOSURE_AGREEMENT,
        UNDERWRITER_RECEIPT,
    )
    # PRD section 2.8 / 3.9: the never-waivable pair.
    NEVER_WAIVABLE = (BOND_OPINION, TAX_CERTIFICATE)


class ExecutionStatus:
    """PRD section 3.9 -- closing document execution state."""

    PENDING = "PENDING"
    EXECUTED = "EXECUTED"
    WAIVED = "WAIVED"

    ALL = (PENDING, EXECUTED, WAIVED)
    # PRD section 3.9: closing counts EXECUTED and WAIVED alike.
    SATISFIED = (EXECUTED, WAIVED)


# PRD section 3.9: signatory role each document type names, keyed by doc_type.
SIGNATORY_ROLE_BY_DOC_TYPE = {
    DocType.BOND_OPINION: UserRole.BOND_COUNSEL,
    DocType.TAX_CERTIFICATE: UserRole.ISSUER_OFFICIAL,
    DocType.ISSUE_PRICE_CERTIFICATE: UserRole.UNDERWRITER,
    DocType.CONTINUING_DISCLOSURE_AGREEMENT: UserRole.ISSUER_OFFICIAL,
    DocType.UNDERWRITER_RECEIPT: UserRole.UNDERWRITER,
    DocType.G17_DISCLOSURE_LETTER: UserRole.UNDERWRITER,
    DocType.NOTICE_OF_SALE_CERTIFICATE: UserRole.MUNICIPAL_ADVISOR,
}
