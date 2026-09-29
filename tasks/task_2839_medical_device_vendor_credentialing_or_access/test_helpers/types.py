"""Request payload shapes and persisted field inventories.

The ``TypedDict`` classes mirror the request bodies the PRD's endpoint table
declares, field for field and JSON type for JSON type: ``unit_cost_cents``,
``tray_count``, ``spd_bay_count`` and the version echoes are JSON numbers, and
every instant is a full ISO 8601 UTC instant string rather than a bare date.

The ``*_FIELDS`` tuples are the persisted field inventories of section 3, used
by the assertion helpers to check that a created row exposes every declared
field. ``COMMON_FIELDS`` is the four-property set of section 2.5;
``EVENT_COMMON_FIELDS`` is the two-property subset a ``ComplianceSweep`` carries.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

try:  # pragma: no cover - typing convenience only
    from typing import TypedDict
except ImportError:  # pragma: no cover
    from typing_extensions import TypedDict  # type: ignore

JsonDict = Dict[str, Any]

# ── Section 2.5: common resource properties ───────────────────────────────────
COMMON_FIELDS = ("id", "created_at", "updated_at", "version")
EVENT_COMMON_FIELDS = ("id", "created_at")


class FacilityPayload(TypedDict, total=False):
    name: str
    code: str
    spd_turnaround_hours: int
    spd_bay_count: int
    badge_lead_minutes: int
    badge_grace_minutes: int
    restricted_escort_required: bool


class VendorPayload(TypedDict):
    legal_name: str
    vendor_code: str


class VendorRepPayload(TypedDict):
    vendor_id: str
    full_name: str
    email: str


class RevokeAccessPayload(TypedDict):
    reason: str


class CredentialPayload(TypedDict):
    vendor_rep_id: str
    credential_type: str
    issued_at_utc: str
    expires_at_utc: str
    document_reference: str


class CredentialDecisionPayload(TypedDict, total=False):
    decision: str
    rejection_reason: str


class SurgicalCasePayload(TypedDict, total=False):
    facility_id: str
    case_number: str
    procedure_name: str
    scheduled_start_utc: str
    scheduled_end_utc: str
    restriction_level: str
    implant_required: bool


class ReschedulePayload(TypedDict):
    new_scheduled_start_utc: str
    new_scheduled_end_utc: str


class CancelPayload(TypedDict):
    cancellation_reason: str


class AuthorizationPayload(TypedDict):
    surgical_case_id: str
    vendor_rep_id: str
    requested_role: str


class AuthorizationDecisionPayload(TypedDict, total=False):
    decision: str
    escort_user_id: str


class AuthorizationRevokePayload(TypedDict, total=False):
    revoked_reason: str


class PirPayload(TypedDict, total=False):
    vendor_id: str
    facility_id: str
    product_name: str
    product_catalog_number: str
    manufacturer: str
    is_implant: bool
    unit_cost_cents: int
    expected_vendor_version: int
    supersedes_request_id: Optional[str]


class ClinicalReviewPayload(TypedDict, total=False):
    decision: str
    review_note: str


class ValueAnalysisPayload(TypedDict, total=False):
    decision: str
    decision_note: str


class LoanerSetPayload(TypedDict):
    surgical_case_id: str
    approved_product_id: str
    tray_count: int
    reprocessing_complexity: str
    expected_case_version: int


class ReceivePayload(TypedDict, total=False):
    delivered_at_utc: str


class CheckInPayload(TypedDict):
    case_rep_authorization_id: str


class AttachEscortPayload(TypedDict):
    escort_user_id: str


class IncidentPayload(TypedDict, total=False):
    surgical_case_id: str
    vendor_rep_id: str
    incident_type: str
    severity: str
    narrative: str
    approved_product_id: Optional[str]


class AdjudicatePayload(TypedDict, total=False):
    outcome: str
    adjudication_note: str


class AccessAppealPayload(TypedDict):
    vendor_rep_id: str
    grounds: str


class AppealDecisionPayload(TypedDict, total=False):
    decision: str
    decision_rationale: str


class ClockPayload(TypedDict):
    current_utc: str


# ── Persisted field inventories (PRD section 3) ───────────────────────────────
FACILITY_FIELDS = (
    "name",
    "code",
    "spd_turnaround_hours",
    "spd_bay_count",
    "badge_lead_minutes",
    "badge_grace_minutes",
    "restricted_escort_required",
)

VENDOR_FIELDS = (
    "legal_name",
    "vendor_code",
    "provisional_compliance_score",
    "adjudicated_compliance_score",
    "scorecard_tier",
    "compliance_status",
    "access_quota_in_effect",
    "authorizations_used_epoch",
    "late_fee_balance_cents",
    "open_pir_count",
    "last_sweep_epoch",
)

VENDOR_REP_FIELDS = (
    "vendor_id",
    "full_name",
    "email",
    "access_status",
    "credential_posture",
    "suspension_reason",
    "ever_credentialed",
    "open_authorization_count",
    "revoked_by_user_id",
    "revoked_at_utc",
    "reinstated_at_utc",
)

CREDENTIAL_FIELDS = (
    "vendor_rep_id",
    "credential_type",
    "issued_at_utc",
    "expires_at_utc",
    "document_reference",
    "status",
    "verified_by_user_id",
    "verified_at_utc",
    "rejection_reason",
)

SURGICAL_CASE_FIELDS = (
    "facility_id",
    "case_number",
    "procedure_name",
    "scheduled_start_utc",
    "scheduled_end_utc",
    "original_scheduled_start_utc",
    "restriction_level",
    "implant_required",
    "status",
    "vendor_coverage_status",
    "implant_readiness_status",
    "approved_rep_count",
    "revoked_authorization_count",
    "reschedule_count",
)

AUTHORIZATION_FIELDS = (
    "surgical_case_id",
    "vendor_rep_id",
    "requested_role",
    "requested_by_user_id",
    "status",
    "escort_required",
    "escort_user_id",
    "decided_by_user_id",
    "decided_at_utc",
    "revoked_reason",
    "badge_window_start_utc",
    "badge_window_end_utc",
    "epoch_number",
)

PIR_FIELDS = (
    "vendor_id",
    "facility_id",
    "supersedes_request_id",
    "product_name",
    "product_catalog_number",
    "manufacturer",
    "is_implant",
    "unit_cost_cents",
    "status",
    "revision_round",
    "clinical_sponsor_user_id",
    "clinical_reviewed_at_utc",
    "value_analysis_user_id",
    "decided_at_utc",
)

APPROVED_PRODUCT_FIELDS = (
    "product_introduction_request_id",
    "product_name",
    "product_catalog_number",
    "manufacturer",
    "is_implant",
    "unit_cost_cents",
    "pinned_pir_version",
    "approved_at_utc",
    "approval_expires_at_utc",
    "status",
    "suspended_reason",
)

LOANER_SET_FIELDS = (
    "surgical_case_id",
    "approved_product_id",
    "tray_count",
    "reprocessing_complexity",
    "pinned_deadline_utc",
    "required_delivery_deadline_utc",
    "delivered_at_utc",
    "late_minutes_pinned_basis",
    "late_minutes_current_basis",
    "assessed_late_fee_cents",
    "fee_status",
    "status",
    "spd_occupation_start_utc",
    "spd_occupation_end_utc",
)

CHECK_IN_FIELDS = (
    "case_rep_authorization_id",
    "badge_serial",
    "badge_status",
    "escort_status",
    "issued_at_utc",
    "valid_from_utc",
    "valid_until_utc",
    "escort_user_id",
    "escort_attached_at_utc",
    "checked_out_at_utc",
)

INCIDENT_FIELDS = (
    "surgical_case_id",
    "vendor_rep_id",
    "approved_product_id",
    "incident_type",
    "severity",
    "narrative",
    "reported_by_user_id",
    "reported_at_utc",
    "status",
    "adjudicated_outcome",
    "adjudicated_by_user_id",
    "adjudicated_at_utc",
    "score_weight",
)

ACCESS_APPEAL_FIELDS = (
    "vendor_rep_id",
    "grounds",
    "filed_for_revoked_at_utc",
    "filed_at_utc",
    "appeal_deadline_utc",
    "status",
    "decided_by_user_id",
    "decided_at_utc",
    "decision_rationale",
)

COMPLIANCE_SWEEP_FIELDS = (
    "epoch_number",
    "previous_epoch_number",
    "swept_at_utc",
    "credentials_expired_count",
    "credentials_warned_count",
    "reps_suspended_count",
    "reps_reinstated_count",
    "authorizations_revoked_count",
    "badges_voided_count",
    "badges_expired_count",
    "approvals_expired_count",
    "incidents_closed_count",
    "vendors_rescored_count",
)

SCORECARD_FIELDS = (
    "vendor_id",
    "provisional_compliance_score",
    "adjudicated_compliance_score",
    "scorecard_tier",
    "compliance_status",
    "access_quota_in_effect",
    "authorizations_used_epoch",
    "utilization_ratio",
    "late_fee_balance_cents",
    "lapsed_rep_count",
    "substantiated_incident_count",
    "open_incident_count",
    "late_delivery_count",
    "last_sweep_epoch",
)

# The twelve addressable single-resource reads, in the order section 2.9 lists
# their 404 identifiers.
ADDRESSABLE_ENTITY_PATHS: List[str] = [
    "/vendor-access/facilities/{id}",
    "/vendor-access/vendors/{id}",
    "/vendor-access/vendor-reps/{id}",
    "/vendor-access/credentials/{id}/decide",
    "/vendor-access/surgical-cases/{id}",
    "/vendor-access/case-rep-authorizations/{id}",
    "/vendor-access/product-introduction-requests/{id}",
    "/vendor-access/approved-products/{id}",
    "/vendor-access/loaner-sets/{id}",
    "/vendor-access/kiosk-check-ins/{id}",
    "/vendor-access/incidents/{id}",
    "/vendor-access/access-appeals/{id}",
]
