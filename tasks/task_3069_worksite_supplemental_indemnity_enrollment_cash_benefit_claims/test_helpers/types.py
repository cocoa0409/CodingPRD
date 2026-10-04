"""Shared shapes and domain vocabulary for the Worksite Indemnity API tests.

The API talks JSON end to end, so these are lightweight aliases plus the status and
role vocabularies the PRD names. Identifiers are server-minted UUID strings with no
type prefix.
"""

from typing import Any, Dict, List, Tuple

# A JSON object as decoded from a response body or handed to a request body.
JsonObject = Dict[str, Any]
JsonList = List[Any]

# The two request headers every authenticated call must carry.
Headers = Dict[str, str]

# Query-string filters for a list endpoint.
Filters = Dict[str, Any]

# ``validate_paginated`` hands back the row list and the pagination block together.
PaginatedResult = Tuple[JsonList, JsonObject]

# Identifiers are server-minted UUID strings with no type prefix.
ResourceId = str

# Instants are ISO 8601 UTC strings (``2026-09-01T00:00:00Z``).
Instant = str

# --- Employer group lifecycle ---
GROUP_PROSPECT = "PROSPECT"
GROUP_ACTIVE = "ACTIVE"
GROUP_SUSPENDED = "SUSPENDED"
GROUP_TERMINATED = "TERMINATED"

# --- Counselor lifecycle ---
COUNSELOR_ACTIVE = "ACTIVE"
COUNSELOR_SUSPENDED = "SUSPENDED"
COUNSELOR_TERMINATED = "TERMINATED"

# --- Enrollment campaign lifecycle ---
CAMPAIGN_DRAFT = "DRAFT"
CAMPAIGN_OPEN = "OPEN"
CAMPAIGN_LOCKED = "LOCKED"
CAMPAIGN_MET = "MET"
CAMPAIGN_FAILED = "FAILED"
CAMPAIGN_CLOSED = "CLOSED"

# --- Policy series lifecycle ---
SERIES_DRAFT = "DRAFT"
SERIES_ACTIVE = "ACTIVE"
SERIES_RETIRED = "RETIRED"

# --- Benefit schedule lifecycle ---
SCHEDULE_DRAFT = "DRAFT"
SCHEDULE_PUBLISHED = "PUBLISHED"
SCHEDULE_SUPERSEDED = "SUPERSEDED"

# --- Employee lifecycle ---
EMPLOYEE_ACTIVE = "ACTIVE"
EMPLOYEE_TERMINATED = "TERMINATED"

# --- Policy lifecycle ---
POLICY_APPLIED = "APPLIED"
POLICY_ISSUED = "ISSUED"
POLICY_ACTIVE = "ACTIVE"
POLICY_LAPSED = "LAPSED"
POLICY_PORTED = "PORTED"
POLICY_DECLINED = "DECLINED"
POLICY_CANCELLED = "CANCELLED"

# --- Claim lifecycle ---
CLAIM_SUBMITTED = "SUBMITTED"
CLAIM_UNDER_REVIEW = "UNDER_REVIEW"
CLAIM_APPROVED = "APPROVED"
CLAIM_PAID = "PAID"
CLAIM_DENIED = "DENIED"
CLAIM_APPEALED = "APPEALED"
CLAIM_VOIDED = "VOIDED"

# --- Claim denial reasons ---
DENIAL_PRE_EXISTING = "PRE_EXISTING"
DENIAL_CAP_EXHAUSTED = "CAP_EXHAUSTED"
DENIAL_INSUFFICIENT_DOCUMENTS = "INSUFFICIENT_DOCUMENTS"
DENIAL_NOT_COVERED = "NOT_COVERED"
DENIAL_POLICY_INACTIVE = "POLICY_INACTIVE"

# --- Claim document lifecycle and types ---
DOC_RECEIVED = "RECEIVED"
DOC_ACCEPTED = "ACCEPTED"
DOC_REJECTED = "REJECTED"

DOC_TYPE_DIAGNOSIS_PROOF = "DIAGNOSIS_PROOF"
DOC_TYPE_PROCEDURE_PROOF = "PROCEDURE_PROOF"
DOC_TYPE_ITEMIZED_BILL = "ITEMIZED_BILL"
DOC_TYPE_ATTENDING_PHYSICIAN_STATEMENT = "ATTENDING_PHYSICIAN_STATEMENT"

# --- Wellness benefit lifecycle ---
WELLNESS_SUBMITTED = "SUBMITTED"
WELLNESS_APPROVED = "APPROVED"
WELLNESS_PAID = "PAID"
WELLNESS_DENIED = "DENIED"

# --- Payroll cycle lifecycle ---
CYCLE_OPEN = "OPEN"
CYCLE_FINALIZED = "FINALIZED"
CYCLE_RECONCILED = "RECONCILED"
CYCLE_CLOSED = "CLOSED"

# --- Deduction line lifecycle ---
LINE_POSTED = "POSTED"
LINE_REVERSED = "REVERSED"

# --- Premium modes / tax treatment ---
PREMIUM_PRE_TAX = "PRE_TAX"
PREMIUM_POST_TAX = "POST_TAX"

# --- Proration conventions ---
PRORATION_DAILY = "DAILY"
PRORATION_HALF_MONTH = "HALF_MONTH"

# --- Product lines ---
PRODUCT_ACCIDENT = "ACCIDENT"
PRODUCT_HOSPITAL = "HOSPITAL"
PRODUCT_CRITICAL_ILLNESS = "CRITICAL_ILLNESS"

__all__ = [
    "JsonObject",
    "JsonList",
    "Headers",
    "Filters",
    "PaginatedResult",
    "ResourceId",
    "Instant",
    "GROUP_PROSPECT",
    "GROUP_ACTIVE",
    "GROUP_SUSPENDED",
    "GROUP_TERMINATED",
    "COUNSELOR_ACTIVE",
    "COUNSELOR_SUSPENDED",
    "COUNSELOR_TERMINATED",
    "CAMPAIGN_DRAFT",
    "CAMPAIGN_OPEN",
    "CAMPAIGN_LOCKED",
    "CAMPAIGN_MET",
    "CAMPAIGN_FAILED",
    "CAMPAIGN_CLOSED",
    "SERIES_DRAFT",
    "SERIES_ACTIVE",
    "SERIES_RETIRED",
    "SCHEDULE_DRAFT",
    "SCHEDULE_PUBLISHED",
    "SCHEDULE_SUPERSEDED",
    "EMPLOYEE_ACTIVE",
    "EMPLOYEE_TERMINATED",
    "POLICY_APPLIED",
    "POLICY_ISSUED",
    "POLICY_ACTIVE",
    "POLICY_LAPSED",
    "POLICY_PORTED",
    "POLICY_DECLINED",
    "POLICY_CANCELLED",
    "CLAIM_SUBMITTED",
    "CLAIM_UNDER_REVIEW",
    "CLAIM_APPROVED",
    "CLAIM_PAID",
    "CLAIM_DENIED",
    "CLAIM_APPEALED",
    "CLAIM_VOIDED",
    "DENIAL_PRE_EXISTING",
    "DENIAL_CAP_EXHAUSTED",
    "DENIAL_INSUFFICIENT_DOCUMENTS",
    "DENIAL_NOT_COVERED",
    "DENIAL_POLICY_INACTIVE",
    "DOC_RECEIVED",
    "DOC_ACCEPTED",
    "DOC_REJECTED",
    "DOC_TYPE_DIAGNOSIS_PROOF",
    "DOC_TYPE_PROCEDURE_PROOF",
    "DOC_TYPE_ITEMIZED_BILL",
    "DOC_TYPE_ATTENDING_PHYSICIAN_STATEMENT",
    "WELLNESS_SUBMITTED",
    "WELLNESS_APPROVED",
    "WELLNESS_PAID",
    "WELLNESS_DENIED",
    "CYCLE_OPEN",
    "CYCLE_FINALIZED",
    "CYCLE_RECONCILED",
    "CYCLE_CLOSED",
    "LINE_POSTED",
    "LINE_REVERSED",
    "PREMIUM_PRE_TAX",
    "PREMIUM_POST_TAX",
    "PRORATION_DAILY",
    "PRORATION_HALF_MONTH",
    "PRODUCT_ACCIDENT",
    "PRODUCT_HOSPITAL",
    "PRODUCT_CRITICAL_ILLNESS",
]
