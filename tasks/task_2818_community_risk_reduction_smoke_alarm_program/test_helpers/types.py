"""Response shapes for the program's entities.

Entities that carry the PRD's common lifecycle fields expose ``id``,
``created_at``, ``updated_at`` and ``version``. The three append-only records -
zone assessments, follow-up contacts and fire incidents - are never updated after
creation, so they carry only ``id`` and ``created_at``.
"""

from typing import Any, Dict, List, Optional, TypedDict


class MutableRecord(TypedDict):
    """Fields shared by every updatable entity."""

    id: str
    created_at: str
    updated_at: str
    version: int


class AppendOnlyRecord(TypedDict):
    """Fields shared by every append-only entity."""

    id: str
    created_at: str


class RiskZone(MutableRecord, total=False):
    zone_code: str
    name: str
    parent_zone_id: Optional[str]
    zone_kind: str
    occupied_units: int
    structure_fire_count_5yr: int
    fire_injury_count_5yr: int
    pre_1980_unit_pct: float
    senior_household_pct: float
    under5_household_pct: float
    disability_household_pct: float
    assumed_alarm_absence_pct: float
    daily_visit_cap: int
    assessment_status: str
    risk_score: Optional[float]
    risk_tier: Optional[str]
    assessment_basis: Optional[str]
    current_assessment_id: Optional[str]
    service_start_date: Optional[str]
    surveyed_units: int
    surveyed_units_without_alarm: int
    post_service_alarm_loss_units: int
    served_household_count: int


class ZoneAssessment(AppendOnlyRecord, total=False):
    zone_id: str
    sequence_no: int
    basis: str
    incident_density_per_1000: float
    injury_density_per_1000: float
    incident_points: float
    injury_points: float
    building_points: float
    vulnerability_points: float
    alarm_points: float
    alarm_gap_pct: float
    risk_score: float
    risk_tier: str
    surveyed_units_at_assessment: int
    assessed_by_user_id: str


class Household(MutableRecord, total=False):
    zone_id: str
    address_line: str
    occupant_count: int
    sleeping_areas_count: int
    storeys: int
    children_under5: int
    adults_65plus: int
    mobility_impaired_occupants: int
    hearing_impaired_occupants: int
    fuel_burning_appliance: bool
    attached_garage: bool
    preferred_language: str
    referral_partner_id: Optional[str]
    required_smoke_devices: int
    required_co_devices: int
    required_strobe_devices: int
    priority_band: str
    status: str
    canvass_attempt_count: int
    last_visit_completed_at: Optional[str]
    alarm_retention_flag: Optional[bool]


class Crew(MutableRecord, total=False):
    crew_code: str
    member_count: int
    certification_level: str
    max_daily_minutes: int
    status: str


class CanvassRoute(MutableRecord, total=False):
    zone_id: str
    crew_id: str
    service_date: str
    window_start_utc: str
    window_end_utc: str
    planned_slots: int
    booked_slot_count: int
    status: str
    closure_note: Optional[str]


class HomeSafetyVisit(MutableRecord, total=False):
    household_id: str
    route_id: str
    scheduled_start_utc: str
    scheduled_end_utc: str
    demand_minutes: int
    appointment_option: str
    contact_channel: str
    occupies_crew_calendar: bool
    visit_status: str
    install_status: str
    education_status: str
    education_topics: Optional[List[str]]
    escape_plan_walkthrough: Optional[bool]
    occupant_present: Optional[bool]
    pre_existing_working_smoke_alarms: Optional[int]
    pre_existing_working_co_alarms: Optional[int]
    install_outcome: Optional[str]
    deferral_reason: Optional[str]
    occupant_signature_name: Optional[str]
    completed_at: Optional[str]
    cancelled_at: Optional[str]
    cancel_reason: Optional[str]


class DeviceLot(MutableRecord, total=False):
    funding_grant_id: str
    sku: str
    device_type: str
    unit_cost_cents: int
    received_qty: int
    on_hand_qty: int
    reserved_qty: int
    consumed_qty: int
    expiry_date: str
    status: str


class AlarmInstallation(MutableRecord, total=False):
    visit_id: str
    device_lot_id: str
    device_type: str
    placement_location: str
    storey: int
    serial_number: Optional[str]
    status: str
    installed_by_crew_id: str
    verified_by_crew_id: Optional[str]
    installed_at: Optional[str]
    verified_at: Optional[str]
    voided_at: Optional[str]
    voided_reason: Optional[str]
    reserved_cost_cents: int
    reimbursable_cents: int


class Partner(MutableRecord, total=False):
    org_name: str
    org_type: str
    contact_email: str
    agreement_signed: bool
    referral_count: int


class PartnerGrant(MutableRecord, total=False):
    partner_id: str
    grant_code: str
    authorized_cents: int
    period_start_date: str
    period_end_date: str
    allowed_device_types: List[str]
    unit_rate_cents_by_type: Dict[str, int]
    reimbursement_basis: str
    reimbursement_pct: float
    indirect_rate_pct: float
    match_pct: float
    status: str
    reserved_cents: int
    committed_cents: int
    available_cents: int
    reported_grant_share_cents: int


class GrantReport(MutableRecord, total=False):
    grant_id: str
    period_start_date: str
    period_end_date: str
    is_final_report: bool
    status: str
    revision_no: int
    installation_count: int
    household_count: int
    served_zone_count: int
    reimbursable_total_cents: int
    direct_cost_cents: int
    indirect_cents: int
    total_project_cents: int
    partner_match_required_cents: int
    grant_share_cents: int
    zone_outcomes: List[Dict[str, Any]]
    compiled_by_user_id: str
    submitted_by_user_id: Optional[str]
    attestation_name: Optional[str]
    submitted_at: Optional[str]
    last_decision: Optional[str]
    reviewer_note: Optional[str]


class EscapePlan(MutableRecord, total=False):
    household_id: str
    primary_exit_per_sleeping_area: bool
    secondary_exit_count: int
    meeting_point_description: str
    drill_scheduled_date: Optional[str]
    status: str
    issued_channel: Optional[str]
    issued_at: Optional[str]
    verified_at: Optional[str]
    lapsed_at: Optional[str]
    lapse_reason: Optional[str]
    reissue_count: int


class FollowUpContact(AppendOnlyRecord, total=False):
    household_id: str
    attempt_no: int
    contact_method: str
    outcome: str
    alarms_present_count: Optional[int]
    plan_practiced: Optional[bool]
    days_since_visit: int
    contacted_by_user_id: str


class FireIncident(AppendOnlyRecord, total=False):
    zone_id: str
    incident_number: str
    occurred_at: str
    working_alarm_present: bool
    injuries: int
    fatalities: int


class ZoneOutcomeSummary(TypedDict, total=False):
    zone_id: str
    service_start_date: Optional[str]
    baseline_fire_count: int
    post_fire_count: int
    baseline_fire_rate_per_1000: Optional[float]
    post_fire_rate_per_1000: Optional[float]
    rate_delta_pct: Optional[float]
    baseline_injuries: int
    post_injuries: int
    injury_delta: int
    served_household_count: int
    retention_eligible_count: int
    retention_rate_pct: Optional[float]
