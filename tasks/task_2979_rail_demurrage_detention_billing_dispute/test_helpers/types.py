"""TypedDict shapes for every persisted resource.

Per PRD 2.4 most resources carry ``id``, ``created_at``, ``updated_at`` and
``version``.  ``CarNotification`` and ``DisputeEvidence`` are deliberately
lighter and carry only ``id`` and ``created_at`` - their TypedDicts therefore
omit ``updated_at`` and ``version`` entirely.
"""

from typing import Any, Dict, List, Optional, TypedDict


class CommonFields(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


class LightFields(TypedDict):
    """PRD 2.4 - a car notification and a piece of dispute evidence carry
    only ``id`` and ``created_at``."""

    id: str
    created_at: str


class Customer(CommonFields):
    customer_code: str
    name: str
    serving_station_code: str
    notification_method: str
    normal_daily_placement_capacity: int
    status: str
    billing_posture: str
    credit_hold_reason: Optional[str]
    credit_balance_cents: int
    dispute_posture: str


class Facility(CommonFields):
    facility_code: str
    kind: str
    storage_clock_mode: str
    gate_open_hour: int
    gate_close_hour: int
    car_spot_capacity: int
    switch_buffer_minutes: int
    storage_free_hours: int
    storage_daily_rate_cents: int
    operates_weekends: bool
    access_mode: str
    access_mode_reason: Optional[str]
    occupied_spot_count: int
    last_switch_at: Optional[str]


class RailCar(CommonFields):
    car_mark: str
    ownership: str
    car_type: str
    capacity_tons: int
    active_cycle_count: int


class TariffRuleSet(CommonFields):
    tariff_code: str
    car_ownership_scope: str
    free_time_hours_railroad: int
    free_time_hours_private: int
    tier1_day_count: int
    tier2_day_count: int
    tier1_rate_cents_railroad: int
    tier2_rate_cents_railroad: int
    tier3_rate_cents_railroad: int
    tier1_rate_cents_private: int
    tier2_rate_cents_private: int
    tier3_rate_cents_private: int
    weekend_excluded: bool
    notification_grace_hours: int
    adjudication_days_base: int
    status: str
    challenge_count: int


class PlacementCycle(CommonFields):
    customer_id: str
    rail_car_id: str
    facility_id: str
    tariff_rule_set_id: str
    waybill_number: str
    movement_status: str
    billing_status: str
    constructive_placement_at: Optional[str]
    constructive_reason_code: Optional[str]
    notification_sent_at: Optional[str]
    notification_acknowledged_at: Optional[str]
    actual_placement_at: Optional[str]
    released_at: Optional[str]
    clock_basis: str
    clock_start_at: Optional[str]
    free_time_expires_at: Optional[str]
    free_days: int
    chargeable_days: int
    early_release_days: int
    refusal_count: int
    refusal_reason: Optional[str]
    void_reason: Optional[str]


class CarNotification(LightFields):
    placement_cycle_id: str
    channel: str
    sent_at: str
    acknowledged_at: Optional[str]
    sequence_number: int
    delivery_status: str


class DemurrageCharge(CommonFields):
    placement_cycle_id: str
    invoice_id: Optional[str]
    charge_kind: str
    computation_basis: Optional[str]
    status: str
    chargeable_days: int
    bunching_exempt_days: int
    billable_days: int
    gross_amount_cents: int
    credit_applied_cents: int
    net_amount_cents: int


class Invoice(CommonFields):
    customer_id: str
    billing_period_start: str
    billing_period_end: str
    status: str
    attached_charge_count: int
    total_gross_cents: int
    total_credit_cents: int
    total_net_cents: int
    agreement_credit_cents: int
    dispute_count: int
    dispute_deadline_at: Optional[str]


class AverageAgreement(CommonFields):
    customer_id: str
    agreement_month: str
    credit_cap_ratio: float
    status: str
    credit_days_earned: int
    debit_days_incurred: int
    net_days: int
    agreement_credit_cents: int


class BunchingClaim(CommonFields):
    customer_id: str
    cluster_window_start: str
    cluster_window_end: str
    method: str
    status: str
    baseline_per_day: int
    delivered_car_count: int
    exempt_days_granted: int
    cluster_chargeable_days: int
    exempted_cycle_ids: List[str]


class DemurrageDispute(CommonFields):
    invoice_id: str
    customer_id: str
    demurrage_charge_id: Optional[str]
    bunching_claim_id: Optional[str]
    supersedes_dispute_id: Optional[str]
    scope: str
    grounds: str
    narrative: str
    claimed_credit_cents: int
    status: str
    decision: str
    round_number: int
    info_request_count: int
    target_charge_count: int
    evidence_weight: int
    allowed_credit_cents: int
    allowance_pct: Optional[float]
    decision_rationale: Optional[str]
    submitted_at: Optional[str]
    adjudication_due_at: Optional[str]
    first_level_adjudicator_id: Optional[str]
    appeal_adjudicator_id: Optional[str]


class DisputeEvidence(LightFields):
    demurrage_dispute_id: str
    evidence_type: str
    observed_at: str
    description: str
    weight_points: int


class RegulatoryComplaint(CommonFields):
    demurrage_dispute_id: str
    tariff_rule_set_id: Optional[str]
    complaint_type: str
    docket_narrative: str
    docket_number: str
    status: str
    filed_at: str
    response_due_at: str
    answer_narrative: Optional[str]
    ordered_credit_cents: int


# Convenience aliases used by fixtures that return loose bags of ids.
Json = Dict[str, Any]
Headers = Dict[str, str]
