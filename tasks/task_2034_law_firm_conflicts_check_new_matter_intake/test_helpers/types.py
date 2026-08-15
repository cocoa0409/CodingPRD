"""Domain types: entity TypedDicts, status enums, role enum.

Every resource carries the common envelope (id, created_at, updated_at, version)
per PRD section 2.4 — all entities in this PRD are versioned rows.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class PartyType(str, Enum):
    CORPORATION = "CORPORATION"
    INDIVIDUAL = "INDIVIDUAL"
    PARTNERSHIP = "PARTNERSHIP"
    TRUST = "TRUST"
    GOVERNMENT = "GOVERNMENT"


class PracticeGroup(str, Enum):
    LITIGATION = "LITIGATION"
    CORPORATE = "CORPORATE"
    TAX = "TAX"
    IP = "IP"


class HireType(str, Enum):
    INTERNAL = "INTERNAL"
    LATERAL = "LATERAL"


class AttorneyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LATERAL_PENDING = "LATERAL_PENDING"


class MatterLifecycle(str, Enum):
    INTAKE = "INTAKE"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    DECLINED = "DECLINED"


class ClearanceStatus(str, Enum):
    UNCHECKED = "UNCHECKED"
    HITS_PENDING = "HITS_PENDING"
    CLEARED = "CLEARED"
    BLOCKED = "BLOCKED"
    WAIVED = "WAIVED"


class RoleInMatter(str, Enum):
    ADVERSE = "ADVERSE"
    WITNESS = "WITNESS"
    RELATED = "RELATED"


class CheckKind(str, Enum):
    INTAKE = "INTAKE"
    LATERAL_SWEEP = "LATERAL_SWEEP"


class SearchVariant(str, Enum):
    STRICT = "STRICT"
    PHONETIC = "PHONETIC"


class ConflictCheckStatus(str, Enum):
    COMPLETED = "COMPLETED"
    SUPERSEDED = "SUPERSEDED"


class MatchedVia(str, Enum):
    DIRECT = "DIRECT"
    ALIAS = "ALIAS"
    AFFILIATE = "AFFILIATE"
    LATERAL = "LATERAL"


class ReviewStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    DISMISSED = "DISMISSED"
    WAIVED = "WAIVED"
    STALE = "STALE"


class WallReason(str, Enum):
    CONFLICT_CONFIRMED = "CONFLICT_CONFIRMED"
    LATERAL_IMPUTATION = "LATERAL_IMPUTATION"
    CLIENT_REQUEST = "CLIENT_REQUEST"


class WallStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LIFTED = "LIFTED"


class WaiverStatus(str, Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    CONSENTED = "CONSENTED"
    DECLINED = "DECLINED"
    APPROVED = "APPROVED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class LetterStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    COUNTERSIGNED = "COUNTERSIGNED"
    SUPERSEDED = "SUPERSEDED"
    VOID = "VOID"


class CreditBand(str, Enum):
    PRIME = "PRIME"
    STANDARD = "STANDARD"
    SUBPRIME = "SUBPRIME"


class DepositStatus(str, Enum):
    PENDING = "PENDING"
    PARTIALLY_FUNDED = "PARTIALLY_FUNDED"
    FUNDED = "FUNDED"


class UserRole(str, Enum):
    FIRM_ADMIN = "FirmAdmin"
    INTAKE_SPECIALIST = "IntakeSpecialist"
    RESPONSIBLE_ATTORNEY = "ResponsibleAttorney"
    CONFLICTS_PARTNER = "ConflictsPartner"
    BILLING_CLERK = "BillingClerk"
    CLIENT = "Client"


class Alias(TypedDict, total=False):
    alias_name: str
    normalized_alias: str


class Party(TypedDict, total=False):
    id: str
    legal_name: str
    party_type: str
    aliases: List[Alias]
    normalized_name: str
    phonetic_key: str
    affiliate_of_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Attorney(TypedDict, total=False):
    id: str
    full_name: str
    bar_number: str
    practice_group: str
    hire_type: str
    lateral_employed_from: Optional[str]
    lateral_employed_to: Optional[str]
    prior_client_names: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Matter(TypedDict, total=False):
    id: str
    matter_title: str
    client_party_id: str
    responsible_attorney_id: str
    practice_group: str
    lifecycle_status: str
    clearance_status: str
    matter_number: Optional[str]
    opened_at: Optional[str]
    closed_at: Optional[str]
    decline_reason: str
    created_at: str
    updated_at: str
    version: int


class MatterParty(TypedDict, total=False):
    id: str
    matter_id: str
    party_id: str
    role_in_matter: str
    created_at: str
    updated_at: str
    version: int


class ConflictCheck(TypedDict, total=False):
    id: str
    matter_id: str
    check_kind: str
    search_variant: str
    match_threshold: int
    status: str
    hit_count: int
    lateral_attorney_id: Optional[str]
    query_label: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ConflictHit(TypedDict, total=False):
    id: str
    check_id: str
    matched_party_id: str
    matched_matter_id: str
    matched_via: str
    match_score: int
    review_status: str
    reviewed_by_attorney_id: Optional[str]
    review_note: str
    lateral_attorney_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EthicalWall(TypedDict, total=False):
    id: str
    matter_id: str
    reason: str
    memo: str
    excluded_attorney_ids: List[str]
    status: str
    lifted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WaiverRequest(TypedDict, total=False):
    id: str
    matter_id: str
    conflict_hit_id: str
    requested_by_attorney_id: str
    proposed_terms: str
    status: str
    sent_at: Optional[str]
    expires_at: Optional[str]
    consent_document_ref: Optional[str]
    decline_reason: str
    approved_by_attorney_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FeeLine(TypedDict):
    description: str
    hours: float
    rate_cents: int


class EngagementLetter(TypedDict, total=False):
    id: str
    matter_id: str
    scope_text: str
    fee_lines: List[FeeLine]
    fee_estimate_cents: int
    status: str
    issued_at: Optional[str]
    countersigned_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CreditAssessment(TypedDict, total=False):
    id: str
    matter_id: str
    score: int
    band: str
    assessed_at: str
    created_at: str
    updated_at: str
    version: int


class RetainerDeposit(TypedDict, total=False):
    id: str
    matter_id: str
    required_cents: int
    funded_total_cents: int
    refunded_total_cents: int
    received_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
