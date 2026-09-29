"""TypedDict shapes for every persisted resource and computed read.

Per PRD §2.5 most resources carry `id`, `created_at`, `updated_at` and
`version`. Two record types are write-once audit rows and "therefore carry only
`id` and `created_at` — both `updated_at` and `version` are absent from them":
ContinuingEducationRecord and FolioCharge.
"""

from typing import Any, Dict, List, Optional, TypedDict


class CommonFields(TypedDict):
    """PRD §2.5 full common block."""
    id: str
    created_at: str
    updated_at: str
    version: int


class AuditRowFields(TypedDict):
    """PRD §2.5 write-once audit row: only `id` and `created_at`."""
    id: str
    created_at: str


# ---------------------------------------------------------------------------
# Menu and inventory
# ---------------------------------------------------------------------------

class TreatmentType(CommonFields):
    code: str
    name: str
    duration_minutes: int
    room_class_required: str
    required_skill_code: str
    required_scope_level: str
    base_price_cents: int
    contraindication_codes: List[str]
    retail_product_line: Optional[str]
    required_consent_version: Optional[str]
    high_demand: bool


class TreatmentRoom(CommonFields):
    code: str
    room_class: str
    capacity_guests: int
    turnover_buffer_minutes: int
    hourly_fixed_cost_cents: int
    status: str
    booked_minutes_total: int


# ---------------------------------------------------------------------------
# Roster and credentials
# ---------------------------------------------------------------------------

class Therapist(CommonFields):
    full_name: str
    employment_type: str
    commission_tier: str
    base_hourly_cost_cents: int
    practice_state_code: str
    status: str
    suspension_reason: Optional[str]
    assigned_minutes_total: int


class TherapistLicense(CommonFields):
    therapist_id: str
    license_number: str
    license_type: str
    state_code: str
    issued_on: str
    expires_on: str
    current_period_start_on: str
    ce_hours_required: float
    verification_status: str
    credited_ce_hours: float
    submitted_by_user_id: str
    reviewed_by_user_id: Optional[str]
    review_note: Optional[str]
    verified_at: Optional[str]


class CertificationGrant(CommonFields):
    therapist_id: str
    skill_code: str
    scope_level: str
    granted_on: str
    expires_on: str
    status: str
    revoked_by_user_id: Optional[str]
    reason_note: Optional[str]


class ContinuingEducationRecord(AuditRowFields):
    """Immutable audit row — no `updated_at`, no `version` (PRD §2.5)."""
    license_id: str
    course_code: str
    category: str
    ce_hours: float
    completed_on: str
    recorded_by_user_id: str


class ShiftBlock(CommonFields):
    therapist_id: str
    block_type: str
    start_at: str
    end_at: str
    note: Optional[str]


# ---------------------------------------------------------------------------
# Guest and intake
# ---------------------------------------------------------------------------

class Guest(CommonFields):
    full_name: str
    resort_room_number: str
    loyalty_tier: str
    folio_limit_cents: int
    folio_balance_cents: int
    late_cancel_count: int
    no_show_strikes: int
    booking_privilege: str
    authoritative_intake_form_id: Optional[str]
    screened_condition_codes: List[str]


class IntakeForm(CommonFields):
    guest_id: str
    status: str
    condition_codes: List[str]
    medications: List[str]
    flagged_condition_codes: List[str]
    consent_version: Optional[str]
    consent_signed_at: Optional[str]
    amendment_round: int
    screened_by_user_id: Optional[str]
    screened_at: Optional[str]
    overridden_by_user_id: Optional[str]
    override_reason: Optional[str]


# ---------------------------------------------------------------------------
# Appointment and downstream
# ---------------------------------------------------------------------------

class Appointment(CommonFields):
    guest_id: str
    treatment_type_id: str
    room_id: str
    therapist_id: str
    start_at: str
    end_at: str
    scheduled_duration_minutes: int
    actual_duration_minutes: Optional[int]
    schedule_status: str
    clearance_status: str
    clearance_block_reason: Optional[str]
    assignment_mode: str
    high_demand_slot: bool
    quoted_price_cents: int
    realized_price_cents: Optional[int]
    gratuity_cents: int
    cancellation_charge_cents: int
    cancel_reason: Optional[str]
    started_at: Optional[str]
    completed_at: Optional[str]


class RetailAttachment(CommonFields):
    appointment_id: str
    product_sku: str
    product_line: str
    amount_cents: int
    status: str
    resolved_by_user_id: Optional[str]
    resolved_at: Optional[str]


class SettlementRecord(CommonFields):
    appointment_id: str
    variant: str
    status: str
    basis_duration_minutes: int
    realized_price_cents: int
    retail_revenue_cents: int
    service_charge_bp: int
    service_charge_pool_cents: int
    gratuity_cents: int
    distributable_pool_cents: int
    therapist_share_cents: int
    support_pool_cents: int
    house_share_cents: int
    therapist_commission_cents: int
    retail_commission_cents: int
    labor_cost_cents: int
    room_fixed_cost_cents: int
    folio_total_cents: int
    net_margin_cents: int


class FolioCharge(AuditRowFields):
    """Immutable audit row — no `updated_at`, no `version` (PRD §2.5)."""
    guest_id: str
    appointment_id: str
    kind: str
    amount_cents: int
    memo: Optional[str]
    posted_at: str


# ---------------------------------------------------------------------------
# Computed reads
# ---------------------------------------------------------------------------

class ClockState(TypedDict):
    current_utc: str


class CeCompliance(TypedDict):
    variant: str
    window_start_on: str
    window_end_on: str
    credited_hours: float
    ethics_hours_credited: float
    ce_hours_required: float
    shortfall_hours: float
    ethics_requirement_met: bool
    compliant: bool


class RoomUtilizationRow(TypedDict):
    room_id: str
    room_code: str
    occupied_minutes: int
    utilization_pct: float
    revenue_cents: int
    labor_cost_cents: int
    room_fixed_cost_cents: int
    net_margin_cents: int
    revenue_per_room_hour_cents: int


class RoomUtilizationReport(TypedDict):
    from_at: str
    to_at: str
    window_minutes: int
    rooms: List[RoomUtilizationRow]


class RetailAttachmentReport(TypedDict):
    from_at: str
    to_at: str
    eligible_appointment_count: int
    purchased_count: int
    purchased_amount_cents: int
    commission_cents: int
    attach_rate_pct: float


class ComplianceSweep(TypedDict):
    swept_at: str
    expired_license_ids: List[str]
    suspended_therapist_ids: List[str]
    blocked_appointment_ids: List[str]
    auto_cancelled_appointment_ids: List[str]
    expired_attachment_ids: List[str]


JsonDict = Dict[str, Any]
