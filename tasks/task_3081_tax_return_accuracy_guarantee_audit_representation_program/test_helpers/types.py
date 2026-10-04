"""Domain types: entity TypedDicts, status enums, role enum for the tax accuracy program."""
from enum import Enum
from typing import Any, List, Optional, TypedDict


class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    OFFICE_MANAGER = "OfficeManager"
    CASE_MANAGER = "CaseManager"
    CLIENT = "Client"
    PREPARER = "Preparer"
    ENROLLED_AGENT = "EnrolledAgent"


class OfficePosture(str, Enum):
    OK = "OK"
    WATCH = "WATCH"
    PROBATION = "PROBATION"


class PreparerTier(str, Enum):
    ASSOCIATE = "ASSOCIATE"
    SENIOR = "SENIOR"
    MASTER = "MASTER"
    ENROLLED_AGENT = "ENROLLED_AGENT"


class CredentialStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class RemediationStatus(str, Enum):
    NONE = "NONE"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"


class ComponentCode(str, Enum):
    C1040_SIMPLE = "1040_SIMPLE"
    C1040_ITEMIZED = "1040_ITEMIZED"
    C1040_BUSINESS = "1040_BUSINESS"
    C1040_MULTI_STATE = "1040_MULTI_STATE"
    AMENDED_RETURN = "AMENDED_RETURN"
    PRIOR_YEAR_REVIEW = "PRIOR_YEAR_REVIEW"


class FilingKind(str, Enum):
    ORIGINAL = "ORIGINAL"
    AMENDED = "AMENDED"


class TaxReturnStatus(str, Enum):
    PREPARING = "PREPARING"
    FILED = "FILED"


class ProductTier(str, Enum):
    STANDARD = "STANDARD"
    PLUS = "PLUS"


class ProductStatus(str, Enum):
    ACTIVE = "ACTIVE"
    VOID = "VOID"


class AuthorityType(str, Enum):
    FEDERAL = "FEDERAL"
    STATE = "STATE"


class NoticeStatus(str, Enum):
    OPEN = "OPEN"
    PAID = "PAID"
    ABATED = "ABATED"
    WITHDRAWN = "WITHDRAWN"


class ClaimStatus(str, Enum):
    TRIAGE = "TRIAGE"
    INFO_NEEDED = "INFO_NEEDED"
    SCOPE_CONFIRMED = "SCOPE_CONFIRMED"
    ASSIGNED = "ASSIGNED"
    REPRESENTING = "REPRESENTING"
    RESOLVED = "RESOLVED"
    REOPENED = "REOPENED"
    DENIED = "DENIED"


class ClaimScope(str, Enum):
    IN_SCOPE = "IN_SCOPE"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"


class ErrorAttribution(str, Enum):
    PREPARER_ERROR = "PREPARER_ERROR"
    CLIENT_DATA_ERROR = "CLIENT_DATA_ERROR"


class AssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class PoaStatus(str, Enum):
    DRAFT = "DRAFT"
    EXECUTED = "EXECUTED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class RemediationActionStatus(str, Enum):
    OPEN = "OPEN"
    COMPLETED = "COMPLETED"


class Office(TypedDict, total=False):
    id: str
    name: str
    region_code: str
    posture: str
    last_close_period: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Preparer(TypedDict, total=False):
    id: str
    office_id: str
    full_name: str
    tier: str
    credential_status: str
    remediation_status: str
    created_at: str
    updated_at: str
    version: int


class Client(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    created_at: str
    updated_at: str
    version: int


class TaxReturn(TypedDict, total=False):
    id: str
    client_id: str
    office_id: str
    preparer_id: str
    tax_year: int
    components: List[str]
    filing_kind: str
    original_return_id: Optional[str]
    status: str
    quoted_fee_cents: int
    final_fee_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class ProtectionProduct(TypedDict, total=False):
    id: str
    return_id: str
    tier: str
    premium_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AuthorityNotice(TypedDict, total=False):
    id: str
    return_id: str
    claim_id: Optional[str]
    authority_type: str
    notice_reference: str
    tax_delta_cents: int
    penalty_cents: int
    issued_at: str
    due_at: str
    interest_cents: Optional[int]
    paid_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict, total=False):
    id: str
    return_id: str
    notice_id: str
    protection_product_id: str
    status: str
    scope: Optional[str]
    error_attribution: Optional[str]
    scoped_by_user_id: Optional[str]
    payout_interest_cents: int
    payout_penalty_cents: int
    payout_base_cents: int
    payout_total_cents: int
    final_liability_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class EnrolledAgent(TypedDict, total=False):
    id: str
    full_name: str
    license_number: str
    max_parallel: int
    created_at: str
    updated_at: str
    version: int


class RepresentationAssignment(TypedDict, total=False):
    id: str
    claim_id: str
    agent_id: str
    window_start: str
    window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PowerOfAttorney(TypedDict, total=False):
    id: str
    claim_id: str
    agent_id: str
    expires_at: str
    executed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RemediationAction(TypedDict, total=False):
    id: str
    preparer_id: str
    due_at: str
    completed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class OfficeEscrow(TypedDict, total=False):
    id: str
    office_id: str
    funded_cents: int
    paid_out_cents: int
    expected_accrual_cents: int
    created_at: str
    updated_at: str
    version: int


class OfficeQualitySnapshot(TypedDict, total=False):
    id: str
    office_id: str
    period_month: str
    returns_examined: int
    returns_with_defects: int
    defect_rate: Any
    quality_score: int
    posture_after: str
    created_at: str
    updated_at: str
    version: int
