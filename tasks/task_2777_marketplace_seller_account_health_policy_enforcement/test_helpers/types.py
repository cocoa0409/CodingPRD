"""Enumerations for every closed value set the PRD declares.

Each enum is a `str` subclass so members compare equal to the wire value and
can be dropped straight into a JSON payload.
"""

from enum import Enum


class Role(str, Enum):
    """PRD §2.1: "The five roles are Anonymous, Seller, PolicyInvestigator,
    AppealReviewer, and ComplianceOfficer."""

    ANONYMOUS = "Anonymous"
    SELLER = "Seller"
    POLICY_INVESTIGATOR = "PolicyInvestigator"
    APPEAL_REVIEWER = "AppealReviewer"
    COMPLIANCE_OFFICER = "ComplianceOfficer"


class EnforcementState(str, Enum):
    """PRD §2.5: the enforcement dimension."""

    ACTIVE = "ACTIVE"
    WATCHLIST = "WATCHLIST"
    RESTRICTED = "RESTRICTED"
    SUSPENDED = "SUSPENDED"
    BANNED = "BANNED"


class DisbursementState(str, Enum):
    """PRD §2.5: the funds dimension."""

    NORMAL = "NORMAL"
    RESERVE_HELD = "RESERVE_HELD"
    FULL_HOLD = "FULL_HOLD"


class BanReason(str, Enum):
    RELATED_ACCOUNT_CONFIRMED = "RELATED_ACCOUNT_CONFIRMED"
    ESCALATION_EXHAUSTED = "ESCALATION_EXHAUSTED"


class PolicyCategory(str, Enum):
    LISTING_ACCURACY = "LISTING_ACCURACY"
    INTELLECTUAL_PROPERTY = "INTELLECTUAL_PROPERTY"
    RESTRICTED_PRODUCT = "RESTRICTED_PRODUCT"
    REVIEW_MANIPULATION = "REVIEW_MANIPULATION"
    SHIPPING_PERFORMANCE = "SHIPPING_PERFORMANCE"


class RemovalScope(str, Enum):
    LISTING = "LISTING"
    ACCOUNT = "ACCOUNT"


class ListingState(str, Enum):
    ACTIVE = "ACTIVE"
    SUPPRESSED = "SUPPRESSED"
    REMOVED = "REMOVED"


class SnapshotSource(str, Enum):
    PLATFORM_PIPELINE = "PLATFORM_PIPELINE"
    MANUAL_CORRECTION = "MANUAL_CORRECTION"


class MetricTier(str, Enum):
    EXEMPT = "EXEMPT"
    BREACHING = "BREACHING"
    AT_RISK = "AT_RISK"
    HEALTHY = "HEALTHY"


class BreachedMetric(str, Enum):
    ORDER_DEFECT_RATE = "ORDER_DEFECT_RATE"
    LATE_SHIPMENT_RATE = "LATE_SHIPMENT_RATE"
    CANCELLATION_RATE = "CANCELLATION_RATE"
    VALID_TRACKING_RATE = "VALID_TRACKING_RATE"


class ViolationState(str, Enum):
    REPORTED = "REPORTED"
    UNDER_INVESTIGATION = "UNDER_INVESTIGATION"
    SUBSTANTIATED = "SUBSTANTIATED"
    DISMISSED = "DISMISSED"


class ReporterType(str, Enum):
    RIGHTS_OWNER = "RIGHTS_OWNER"
    BUYER = "BUYER"
    PLATFORM_AUTOMATION = "PLATFORM_AUTOMATION"
    REGULATOR = "REGULATOR"


class AdjudicationOutcome(str, Enum):
    SUBSTANTIATED = "SUBSTANTIATED"
    DISMISSED = "DISMISSED"


class ActionType(str, Enum):
    WARNING = "WARNING"
    LISTING_REMOVAL = "LISTING_REMOVAL"
    ACCOUNT_SUSPENSION = "ACCOUNT_SUSPENSION"


class ActionState(str, Enum):
    ISSUED = "ISSUED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    UPHELD = "UPHELD"
    VACATED = "VACATED"


class ResolutionReason(str, Enum):
    APPEAL_GRANTED = "APPEAL_GRANTED"
    APPEAL_DENIED = "APPEAL_DENIED"
    ESCALATION_GRANTED = "ESCALATION_GRANTED"
    ESCALATION_DENIED = "ESCALATION_DENIED"


class PoaState(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    RETURNED_FOR_REVISION = "RETURNED_FOR_REVISION"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class PoaDecision(str, Enum):
    ACCEPT = "ACCEPT"
    RETURN = "RETURN"
    REJECT = "REJECT"


class AppealState(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    ESCALATED_REVIEW = "ESCALATED_REVIEW"
    FINAL_DENIED = "FINAL_DENIED"


class AppealOutcome(str, Enum):
    GRANTED = "GRANTED"
    DENIED = "DENIED"


class EscalationOutcome(str, Enum):
    GRANTED_ON_ESCALATION = "GRANTED_ON_ESCALATION"
    FINAL_DENIED = "FINAL_DENIED"


class DenialReason(str, Enum):
    REPEAT_OFFENSE = "REPEAT_OFFENSE"
    INSUFFICIENT_POA = "INSUFFICIENT_POA"
    EVIDENCE_UPHELD = "EVIDENCE_UPHELD"
    RESTRICTED_PRODUCT_RISK = "RESTRICTED_PRODUCT_RISK"


class HoldType(str, Enum):
    RESERVE = "RESERVE"
    FULL_HOLD = "FULL_HOLD"


class ReserveBasis(str, Enum):
    ROLLING = "ROLLING"
    CLAIM_EXPOSURE = "CLAIM_EXPOSURE"
    NONE = "NONE"


class HoldState(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    FORFEITED = "FORFEITED"


class ReleaseReason(str, Enum):
    MANUAL = "MANUAL"
    INVESTIGATION_CLOSED = "INVESTIGATION_CLOSED"
    APPEAL_GRANTED = "APPEAL_GRANTED"
    SUPERSEDED_BY_FULL_HOLD = "SUPERSEDED_BY_FULL_HOLD"


class RiskTier(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


class LinkState(str, Enum):
    DETECTED = "DETECTED"
    CONFIRMED = "CONFIRMED"
    DISMISSED = "DISMISSED"


class LinkDecision(str, Enum):
    CONFIRMED = "CONFIRMED"
    DISMISSED = "DISMISSED"


class MatchedSignal(str, Enum):
    TAX_ID = "TAX_ID"
    BANK_TOKEN = "BANK_TOKEN"
    ADDRESS = "ADDRESS"
    EMAIL_DOMAIN = "EMAIL_DOMAIN"
    DEVICE = "DEVICE"


class TemplateCode(str, Enum):
    REGISTRATION_FLAGGED = "REGISTRATION_FLAGGED"
    HEALTH_BREACH = "HEALTH_BREACH"
    ACTION_ISSUED = "ACTION_ISSUED"
    POA_DECISION = "POA_DECISION"
    APPEAL_DECISION = "APPEAL_DECISION"
    ESCALATION_DECISION = "ESCALATION_DECISION"
    FUNDS_HELD = "FUNDS_HELD"
    FUNDS_RELEASED = "FUNDS_RELEASED"
    ACCOUNT_BANNED = "ACCOUNT_BANNED"


class RelatedEntityType(str, Enum):
    SELLER = "SELLER"
    HEALTH_EVALUATION = "HEALTH_EVALUATION"
    ENFORCEMENT_ACTION = "ENFORCEMENT_ACTION"
    PLAN_OF_ACTION = "PLAN_OF_ACTION"
    APPEAL = "APPEAL"
    DISBURSEMENT_HOLD = "DISBURSEMENT_HOLD"
    RELATED_ACCOUNT_LINK = "RELATED_ACCOUNT_LINK"


class NotificationState(str, Enum):
    SENT = "SENT"
    SUPERSEDED = "SUPERSEDED"
