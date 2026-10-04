"""Domain types: entity TypedDicts, status enums, role enum.

Every entity in this API carries the same four system-managed properties
(id, created_at, updated_at, version), so every TypedDict below carries all four.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    ORGANIZATION_USER = "OrganizationUser"
    PLATFORM_VERIFIER = "PlatformVerifier"
    DATA_CONSUMER = "DataConsumer"
    PLATFORM_ADMIN = "PlatformAdmin"


class OrgType(str, Enum):
    C501C3 = "501C3"
    C501C4 = "501C4"
    C501C6 = "501C6"
    C501C7 = "501C7"
    C527 = "527"
    OTHER = "OTHER"


class ProfileStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    MERGED = "MERGED"
    DISSOLVED = "DISSOLVED"


class VerificationLevel(str, Enum):
    SELF_REPORTED = "SELF_REPORTED"
    DOCUMENT_VERIFIED = "DOCUMENT_VERIFIED"
    INDEPENDENTLY_AUDITED = "INDEPENDENTLY_AUDITED"


class DisclosureLevel(str, Enum):
    PUBLIC = "PUBLIC"
    RESTRICTED = "RESTRICTED"
    WITHHELD = "WITHHELD"


class ProgramStatus(str, Enum):
    ACTIVE = "ACTIVE"


class LeadershipStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"


class DemographicCategory(str, Enum):
    RACE_ETHNICITY = "RACE_ETHNICITY"
    GENDER_IDENTITY = "GENDER_IDENTITY"
    AGE_BAND = "AGE_BAND"
    LGBTQIA = "LGBTQIA"
    DISABILITY = "DISABILITY"
    VETERAN = "VETERAN"


class FormType(str, Enum):
    FORM_990 = "FORM_990"
    FORM_990_EZ = "FORM_990_EZ"
    FORM_990_PF = "FORM_990_PF"


class FilingSource(str, Enum):
    IRS_BULK_XML = "IRS_BULK_XML"
    ORG_UPLOAD = "ORG_UPLOAD"
    MANUAL_ENTRY = "MANUAL_ENTRY"


class FilingStatus(str, Enum):
    RECEIVED = "RECEIVED"
    EXTRACTED = "EXTRACTED"
    EXTRACTION_FAILED = "EXTRACTION_FAILED"
    NORMALIZED = "NORMALIZED"
    DISPUTED = "DISPUTED"
    SUPERSEDED = "SUPERSEDED"
    VOIDED = "VOIDED"


class RawFormat(str, Enum):
    USD_WHOLE = "USD_WHOLE"
    USD_THOUSANDS = "USD_THOUSANDS"
    USD_MILLIONS = "USD_MILLIONS"
    PLAIN_INTEGER = "PLAIN_INTEGER"


class NormalizationStatus(str, Enum):
    PENDING = "PENDING"
    NORMALIZED = "NORMALIZED"
    CORRECTED = "CORRECTED"
    CONFLICT = "CONFLICT"


class SealLevel(str, Enum):
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"
    PLATINUM = "PLATINUM"


class SealStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"
    REVOKED = "REVOKED"


class LicenseTier(str, Enum):
    RESEARCHER = "RESEARCHER"
    FUNDER = "FUNDER"
    PLATFORM = "PLATFORM"


class PermittedUse(str, Enum):
    AGGREGATE_RESEARCH = "AGGREGATE_RESEARCH"
    GRANTMAKING_DUE_DILIGENCE = "GRANTMAKING_DUE_DILIGENCE"
    PLATFORM_REDISTRIBUTION = "PLATFORM_REDISTRIBUTION"
    MARKETING_PROSPECTING = "MARKETING_PROSPECTING"


class LicenseStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"


class DatasetScope(str, Enum):
    ORGANIZATION_PROFILES = "ORGANIZATION_PROFILES"
    FILING_FINANCIALS = "FILING_FINANCIALS"
    GRANT_HISTORY = "GRANT_HISTORY"
    LEADERSHIP_COMPENSATION = "LEADERSHIP_COMPENSATION"


class UsageEventStatus(str, Enum):
    POSTED = "POSTED"
    VOIDED = "VOIDED"


class GrantStatus(str, Enum):
    RECORDED = "RECORDED"
    VOIDED = "VOIDED"


class TaxonomySource(str, Enum):
    FUNDER_SUPPLIED = "FUNDER_SUPPLIED"
    AUTO_CODED = "AUTO_CODED"
    UNCODED = "UNCODED"


class RecipientMatchStatus(str, Enum):
    UNMATCHED = "UNMATCHED"
    AMBIGUOUS = "AMBIGUOUS"
    MATCHED = "MATCHED"


class CorrectionStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    ACCEPTED = "ACCEPTED"
    PARTIALLY_ACCEPTED = "PARTIALLY_ACCEPTED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class CorrectionDecision(str, Enum):
    CLAIM = "CLAIM"
    RETURN_FOR_INFO = "RETURN_FOR_INFO"
    ACCEPT = "ACCEPT"
    PARTIALLY_ACCEPT = "PARTIALLY_ACCEPT"
    REJECT = "REJECT"
    WITHDRAW = "WITHDRAW"


class IdentityCaseType(str, Enum):
    MERGE = "MERGE"
    DISSOLUTION = "DISSOLUTION"
    NAME_CHANGE = "NAME_CHANGE"


class IdentityCaseStatus(str, Enum):
    OPEN = "OPEN"
    FINALIZED = "FINALIZED"
    WITHDRAWN = "WITHDRAWN"


class IdentityDecision(str, Enum):
    FINALIZE = "FINALIZE"
    WITHDRAW = "WITHDRAW"


# ---------------------------------------------------------------------------
# Entity shapes (all carry id + created_at + updated_at + version)
# ---------------------------------------------------------------------------

class Organization(TypedDict):
    id: str
    legal_name: str
    display_name: Optional[str]
    former_legal_names: List[str]
    ein: str
    org_type: str
    state_code: str
    ntee_code: Optional[str]
    ntee_code_verified: bool
    mission_statement: Optional[str]
    profile_status: str
    verification_level: str
    verification_evidence_count: int
    transparency_seal_level: str
    seal_expires_on: Optional[str]
    provisional_completeness_score: int
    verified_completeness_score: int
    profile_completeness_score: int
    disclosure_pct: float
    total_revenue_cents: int
    latest_filing_tax_year: Optional[int]
    distinct_funder_count: int
    active_license_count: int
    open_correction_count: int
    last_profile_editor_user_id: str
    successor_organization_id: Optional[str]
    dissolution_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Program(TypedDict):
    id: str
    organization_id: str
    program_name: str
    subject_code: Optional[str]
    population_served: Optional[str]
    disclosure_level: str
    is_verified: bool
    status: str
    fiscal_year: int
    created_at: str
    updated_at: str
    version: int


class Filing(TypedDict):
    id: str
    organization_id: str
    form_type: str
    form_version_year: int
    tax_year: int
    revision_number: int
    superseded_by_revision_number: Optional[int]
    pre_supersede_status: Optional[str]
    coverage_start: str
    coverage_end: str
    source: str
    status: str
    extracted_field_count: int
    total_revenue_cents: int
    extraction_confidence_pct: Optional[float]
    is_verified: bool
    created_at: str
    updated_at: str
    version: int


class ExtractedField(TypedDict):
    id: str
    filing_id: str
    line_code: str
    raw_value: str
    raw_format: str
    schedule_code: Optional[str]
    is_revenue_component: bool
    normalized_value_cents: Optional[int]
    normalization_status: str
    is_verified: bool
    correction_count: int
    confidence_pct: float
    created_at: str
    updated_at: str
    version: int


class LeadershipMember(TypedDict):
    id: str
    organization_id: str
    full_name: str
    office_title: str
    is_officer: bool
    is_independent: bool
    is_verified: bool
    disclosure_level: str
    compensation_cents: int
    service_start: str
    service_end: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DemographicRecord(TypedDict):
    id: str
    organization_id: str
    category: str
    value_code: str
    disclosure_level: str
    is_verified: bool
    fiscal_year: int
    created_at: str
    updated_at: str
    version: int


class TransparencySeal(TypedDict):
    id: str
    organization_id: str
    level: str
    disclosure_pct_at_award: float
    awarded_on: str
    expires_on: str
    renewal_window_opens_on: str
    renewal_attempt_count: int
    last_renewal_fee_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Grant(TypedDict):
    id: str
    recipient_organization_id: str
    funder_organization_id: str
    funder_name_raw: str
    recipient_name_raw: str
    recipient_ein: Optional[str]
    amount_cents: int
    fiscal_year: int
    subject_code: Optional[str]
    taxonomy_source: str
    match_score: int
    recipient_match_status: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DataLicense(TypedDict):
    id: str
    licensee_organization_id: str
    tier: str
    permitted_use: str
    term_start: str
    term_end: str
    status: str
    projected_annual_records: int
    included_records: int
    records_accessed: int
    overage_records: int
    projected_annual_fee_cents: int
    final_annual_fee_cents: int
    overage_flag: bool
    auto_renew: bool
    created_at: str
    updated_at: str
    version: int


class LicenseUsageEvent(TypedDict):
    id: str
    license_id: str
    dataset_scope: str
    record_count: int
    purpose_code: str
    status: str
    occurred_at: str
    created_at: str
    updated_at: str
    version: int


class CorrectionRequest(TypedDict):
    id: str
    organization_id: str
    target_extracted_field_id: str
    requested_value: str
    evidence_url: str
    justification: str
    status: str
    submitted_by_user_id: str
    decided_by_user_id: Optional[str]
    review_note: Optional[str]
    requested_at: str
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class IdentityResolutionCase(TypedDict):
    id: str
    subject_organization_id: str
    surviving_organization_id: Optional[str]
    case_type: str
    new_legal_name: Optional[str]
    effective_date: str
    status: str
    resolution_note: Optional[str]
    reassigned_grant_count: int
    finalized_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
