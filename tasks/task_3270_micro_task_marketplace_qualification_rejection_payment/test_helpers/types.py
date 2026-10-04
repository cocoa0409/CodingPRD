"""
Domain types for the Micro-Task Marketplace API.

Entity TypedDicts, status enumerations and the role enumeration, derived from
the resource descriptions in the PRD. Resources created with the standard field
set carry ``id``, ``created_at``, ``updated_at`` and ``version``; the append-only
``Review`` audit record carries only ``id`` and ``created_at``.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Roles ───────────────────────────────────────────────────────────────────

class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    REQUESTER = "Requester"
    WORKER = "Worker"
    PLATFORM_ADMIN = "PlatformAdmin"


# ─── Enumerations ────────────────────────────────────────────────────────────

class RequesterStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    PENDING_REVIEW = "PENDING_REVIEW"


class SuspensionReason(str, Enum):
    NONE = "NONE"
    ABUSE_AUTO = "ABUSE_AUTO"
    ADMIN_MANUAL = "ADMIN_MANUAL"


class WorkerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class Country(str, Enum):
    US = "US"
    IN = "IN"
    PH = "PH"
    BR = "BR"


class HitStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    DISPATCHED = "DISPATCHED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class AssignmentStatus(str, Enum):
    ACCEPTED = "ACCEPTED"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    DISPUTED = "DISPUTED"
    RETURNED = "RETURNED"
    EXPIRED = "EXPIRED"


class DepositStatus(str, Enum):
    PENDING = "PENDING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class PayoutStatus(str, Enum):
    HELD_FOR_VETTING = "HELD_FOR_VETTING"
    PAID = "PAID"
    REJECTED = "REJECTED"


class PaymentMethod(str, Enum):
    BANK_TRANSFER = "BANK_TRANSFER"
    PAYPAL = "PAYPAL"
    GIFT_CARD = "GIFT_CARD"


class QualificationKind(str, Enum):
    SYSTEM = "SYSTEM"
    REQUESTER = "REQUESTER"


class QualificationGrantSource(str, Enum):
    CASCADE = "CASCADE"
    EXAM = "EXAM"


class QualificationGrantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class ExamOutcome(str, Enum):
    PASSED = "PASSED"
    FAILED = "FAILED"


class ReviewKind(str, Enum):
    APPROVAL = "APPROVAL"
    REJECTION = "REJECTION"
    BONUS = "BONUS"


class ActorRole(str, Enum):
    REQUESTER = "REQUESTER"
    REVIEWER = "REVIEWER"
    PLATFORM_ADMIN = "PLATFORM_ADMIN"


class VerificationOutcome(str, Enum):
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"


class DepositOutcome(str, Enum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class ResolutionDecision(str, Enum):
    APPROVE = "APPROVE"
    UPHOLD = "UPHOLD"


# ─── Entities ────────────────────────────────────────────────────────────────
# ``common_fields: true`` entities carry id + created_at + updated_at + version.

class Requester(TypedDict, total=False):
    id: str
    name: str
    prepaid_balance_cents: int
    escrowed_cents: int
    lifetime_spent_cents: int
    approved_count: int
    rejected_count: int
    lifetime_rejection_rate_pct: int
    abuse_score: int
    task_abuse_flag: bool
    suspension_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Worker(TypedDict, total=False):
    id: str
    display_name: str
    country: str
    approval_rate_pct: int
    approved_count: int
    rejected_count: int
    returned_count: int
    expired_count: int
    total_earned_cents: int
    withdrawable_cents: int
    identity_verified: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class WorkerQualification(TypedDict, total=False):
    id: str
    worker_id: str
    qualification_type_id: str
    score: int
    source: str
    status: str
    created_at: str
    updated_at: str
    version: int


class QualificationType(TypedDict, total=False):
    id: str
    name: str
    kind: str
    exam_available: bool
    auto_assign_threshold_pct: int
    default_score: int
    created_at: str
    updated_at: str
    version: int


class QualificationExam(TypedDict, total=False):
    id: str
    qualification_type_id: str
    passing_score: int
    max_attempts: int
    retake_cooldown_days: int
    created_at: str
    updated_at: str
    version: int


class QualificationExamAttempt(TypedDict, total=False):
    id: str
    exam_id: str
    sequence: int
    score: int
    outcome: str
    created_at: str
    updated_at: str
    version: int


class HIT(TypedDict, total=False):
    id: str
    requester_id: str
    title: str
    reward_cents: int
    required_qualification_ids: List[str]
    max_assignments: int
    assignment_duration_minutes: int
    time_limit_minutes: int
    bonus_budget_cents: int
    funds_required_cents: int
    escrowed_cents: int
    accepted_count: int
    assignment_count: int
    committed_assignments: int
    spent_rewards_cents: int
    spent_bonus_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Assignment(TypedDict, total=False):
    id: str
    hit_id: str
    worker_id: str
    sequence: int
    deadline_at: str
    review_expires_at: Optional[str]
    submitted_at: Optional[str]
    approved_at: Optional[str]
    bonus_cents: int
    eligible_for_approval: bool
    approval_rate_effect_applied: bool
    committed: bool
    assignment_expired: bool
    rejection_reason: Optional[str]
    dispute_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RequesterDeposit(TypedDict, total=False):
    id: str
    requester_id: str
    amount_cents: int
    status: str
    escrowed_cents: int
    refunded_cents: int
    created_at: str
    updated_at: str
    version: int


class PayoutRequest(TypedDict, total=False):
    id: str
    worker_id: str
    payment_method: str
    amount_cents: int
    hold_until_at: str
    identity_verified_at: Optional[str]
    status: str
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Review is append-only: ONLY id and created_at — no updated_at, no version.
class Review(TypedDict, total=False):
    id: str
    assignment_id: str
    actor_requester_id: str
    actor_role: str
    kind: str
    bonus_cents: int
    abuse_points: int
    reason: Optional[str]
    created_at: str