"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


class PublicationStatus(str, Enum):
    PENDING = "PENDING"
    ACCREDITED = "ACCREDITED"
    PROBATION = "PROBATION"
    REVOKED = "REVOKED"


class CriticStatus(str, Enum):
    APPLIED = "APPLIED"
    ACCREDITED = "ACCREDITED"
    UNDER_REVIEW = "UNDER_REVIEW"
    PROBATION = "PROBATION"
    REVOKED = "REVOKED"


class AccreditationReviewStatus(str, Enum):
    FILED = "FILED"
    IN_REVIEW = "IN_REVIEW"
    UPHELD = "UPHELD"
    REVOKED = "REVOKED"
    DISMISSED = "DISMISSED"


class TitlePosture(str, Enum):
    SETUP = "SETUP"
    OPEN = "OPEN"
    RETIRED = "RETIRED"


class ReleaseStatus(str, Enum):
    UPCOMING = "UPCOMING"
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class ReviewStatus(str, Enum):
    INGESTED = "INGESTED"
    PUBLISHED = "PUBLISHED"
    FLAGGED = "FLAGGED"
    WITHDRAWN = "WITHDRAWN"


class TicketVerificationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class AudienceRatingStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    INVALIDATED = "INVALIDATED"


class BombingIncidentStatus(str, Enum):
    OPEN = "OPEN"
    CONFIRMED = "CONFIRMED"
    DISMISSED = "DISMISSED"
    RESOLVED = "RESOLVED"


class DisputeStatus(str, Enum):
    FILED = "FILED"
    TRIAGED = "TRIAGED"
    UPHELD = "UPHELD"
    REJECTED = "REJECTED"


class Classification(str, Enum):
    FRESH = "FRESH"
    ROTTEN = "ROTTEN"


class Certification(str, Enum):
    NONE = "NONE"
    CERTIFIED_FRESH = "CERTIFIED_FRESH"
    CERTIFIED_ROTTEN = "CERTIFIED_ROTTEN"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    ACCREDITATION_BOARD = "AccreditationBoard"
    CRITIC = "Critic"
    STUDIO_REP = "StudioRep"
    AUDIENCE_MEMBER = "AudienceMember"
