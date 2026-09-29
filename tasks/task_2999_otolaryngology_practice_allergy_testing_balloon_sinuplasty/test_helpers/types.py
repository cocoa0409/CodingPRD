"""Typed shapes for every resource the service returns.

Twelve of the thirteen resources carry the common mutation trio described in
PRD 2.4 -- ``created_at``, ``updated_at`` and ``version``. ``ReactionEvent`` is
the single exception: it is an immutable ledger row that carries ``id`` and
``created_at`` only, so its shape below deliberately omits ``updated_at`` and
``version``.
"""

from typing import Any, Dict, List, Optional

try:  # pragma: no cover - typing_extensions is only needed on older runtimes
    from typing import TypedDict
except ImportError:  # pragma: no cover
    from typing_extensions import TypedDict


class MutableResource(TypedDict):
    """The identity and mutation-tracking fields shared by twelve resources."""

    id: str
    created_at: str
    updated_at: str
    version: int


class ImmutableResource(TypedDict):
    """The identity fields of a resource that is never rewritten."""

    id: str
    created_at: str


class PayerPolicy(MutableResource, total=False):
    payer_name: str
    plan_code: str
    requires_prior_auth: bool
    min_medical_management_days: int
    requires_ct_within_months: int
    min_documented_criteria: int
    max_balloon_devices: int
    covered_pct_bps: int
    allergy_serum_covered: bool
    observation_floor_minutes: int
    device_trial_days: int
    restock_fee_bps: int
    restock_fee_floor_cents: int
    auth_validity_days: int
    appliance_covered: bool


class Patient(MutableResource, total=False):
    payer_policy_id: str
    mrn: str
    full_name: str
    date_of_birth: str
    age_months: int
    antihistamine_last_dose_at: Optional[str]
    epinephrine_on_file: bool
    dermatographism: bool
    prior_systemic_reaction_count: int
    sensitized_antigen_count: int
    risk_score: int
    risk_score_variant: str
    supervision_tier: str
    immunotherapy_escalation_step: int
    immunotherapy_status: str
    last_dose_administered_at: Optional[str]


class AllergyTestOrder(MutableResource, total=False):
    patient_id: str
    panel_code: str
    method: str
    status: str
    antigen_count: int
    billed_units: int
    practice_charge_cents: int
    patient_responsibility_cents: int
    observation_required_minutes: int
    ordered_by_user_id: str
    administered_by_user_id: Optional[str]
    administered_at: Optional[str]
    positive_antigen_count: Optional[int]
    worst_systemic_grade: Optional[int]
    abort_reason: Optional[str]


class ReactionEvent(ImmutableResource, total=False):
    """PRD 2.4: a reaction event carries no ``updated_at`` and no ``version``."""

    allergy_test_order_id: Optional[str]
    immunotherapy_dose_id: Optional[str]
    systemic_grade: int
    local_wheal_mm: float
    onset_minutes: int
    epinephrine_given: bool
    recorded_by_user_id: str
    occurred_at: str


class ImmunotherapyVial(MutableResource, total=False):
    patient_id: str
    supply_lot_id: str
    dilution_code: str
    label_text: str
    volume_ml_initial: float
    volume_ml_remaining: float
    volume_ml_dispensed_total: float
    volume_ml_wasted: float
    expires_at: str
    status: str
    mixed_by_user_id: str
    verified_by_user_id: Optional[str]
    requires_supervised_administration: bool
    discard_reason: Optional[str]


class ImmunotherapyDose(MutableResource, total=False):
    immunotherapy_vial_id: str
    patient_id: str
    escalation_step_at_dose: int
    volume_ml: float
    observation_required_minutes: int
    administered_at: str
    administered_by_user_id: str
    supervising_user_id: Optional[str]
    observation_cleared_at: Optional[str]
    status: str
    reaction_grade: int
    gap_days_at_dose: int


class SinuplastyCase(MutableResource, total=False):
    patient_id: str
    laterality: str
    sinuses: List[str]
    planned_device_count: int
    ct_study_date: Optional[str]
    documented_therapies: List[Dict[str, Any]]
    documented_criteria_codes: List[str]
    evaluation_variant: str
    criteria_met_count: int
    contiguous_management_days: int
    cumulative_management_days: int
    candidacy_status: str
    status: str
    revision_round: int
    submitted_by_user_id: Optional[str]
    pinned_policy_version: Optional[int]
    authorized_device_count: int
    auth_expires_at: Optional[str]
    payer_reference: Optional[str]
    documented_by_user_id: Optional[str]


class DiagnosticStudy(MutableResource, total=False):
    patient_id: str
    study_type: str
    status: str
    pta_db_hl: Optional[float]
    word_recognition_pct: Optional[float]
    ahi: Optional[float]
    recommendation: Optional[str]
    performed_at: Optional[str]
    performed_by_user_id: Optional[str]
    interpreted_by_user_id: Optional[str]
    superseded_dispense_count: int


class DeviceDispense(MutableResource, total=False):
    diagnostic_study_id: str
    supply_lot_id: str
    device_type: str
    device_serial: str
    ear: str
    price_cents: int
    dispensed_at: str
    trial_end_at: str
    fit_status: str
    billing_status: str
    adjustment_count: int
    days_used: int
    refund_variant: Optional[str]
    restock_fee_cents: int
    refund_cents: int
    dispensed_by_user_id: str
    settled_by_user_id: Optional[str]


class EndoscopeAsset(MutableResource, total=False):
    serial_number: str
    model: str
    status: str
    cycle_count: int
    last_reprocessed_at: Optional[str]
    hld_expires_at: Optional[str]
    mec_test_due: bool
    consecutive_mec_failures: int
    reprocessing_started_by_user_id: Optional[str]
    last_used_by_user_id: Optional[str]


class SupplyLot(MutableResource, total=False):
    item_type: str
    lot_number: str
    quantity_received: int
    quantity_on_hand: int
    quantity_reserved: int
    quantity_consumed: int
    quantity_wasted: int
    available_quantity: int
    expires_at: str
    status: str


class SurgeryCenterBlock(MutableResource, total=False):
    center_name: str
    block_start_at: str
    block_end_at: str
    max_concurrent_cases: int
    overnight_capable: bool
    booked_case_count: int
    booked_minutes: int
    capacity_minutes: int
    utilization_bps: int
    status: str


class ProcedureBooking(MutableResource, total=False):
    patient_id: str
    sinuplasty_case_id: Optional[str]
    endoscope_asset_id: Optional[str]
    surgery_center_block_id: Optional[str]
    supply_lot_id: Optional[str]
    procedure_type: str
    venue: str
    start_at: str
    end_at: str
    duration_minutes: int
    physician_user_id: str
    planned_device_count: int
    devices_used_count: int
    overnight_observation_required: bool
    requires_physician_presence: bool
    attending_physician_user_id: Optional[str]
    scope_reassignment_required: bool
    supply_shortfall_flag: bool
    status: str
    cancel_reason: Optional[str]


class CandidacyEvaluation(TypedDict, total=False):
    """The nine-field projection returned by the candidacy-evaluation read."""

    evaluation_variant: str
    criteria_met_count: int
    admissible_criteria_codes: List[str]
    contiguous_management_days: int
    cumulative_management_days: int
    management_days_metric: int
    min_documented_criteria_required: int
    min_medical_management_days_required: int
    candidacy_status: str


# Every resource that carries the mutation trio of PRD 2.4.
MUTABLE_RESOURCE_NAMES = (
    "PayerPolicy",
    "Patient",
    "AllergyTestOrder",
    "ImmunotherapyVial",
    "ImmunotherapyDose",
    "SinuplastyCase",
    "DiagnosticStudy",
    "DeviceDispense",
    "EndoscopeAsset",
    "SupplyLot",
    "SurgeryCenterBlock",
    "ProcedureBooking",
)

# The one resource that does not.
IMMUTABLE_RESOURCE_NAMES = ("ReactionEvent",)
