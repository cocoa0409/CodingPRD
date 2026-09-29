"""
TypedDict shapes for every entity the API returns (PRD §2.4, §6).

Mutable entities carry the common system fields ``id``, ``created_at``,
``updated_at`` and ``version``. The three append-only entities
(RuntimeReading, RenewalSurvey, LedgerEntry) are immutable rows and therefore
carry only ``id`` and ``created_at`` — no ``updated_at`` and no ``version``.
"""

from typing import List, Optional, TypedDict


class MutableEntity(TypedDict):
    """System fields shared by every mutable entity."""

    id: str
    created_at: str
    updated_at: str
    version: int


class ImmutableEntity(TypedDict):
    """System fields shared by every append-only entity."""

    id: str
    created_at: str


class Property(MutableEntity):
    name: str
    state_code: str
    billing_mode: str
    benefit_tier: str
    damage_waiver_enabled: bool
    aqg_enabled: bool
    credit_limit_cents: int
    status: str
    suspend_reason: Optional[str]
    outstanding_balance_cents: int
    unit_count: int


class Unit(MutableEntity):
    property_id: str
    unit_label: str
    hvac_system_type: str
    filter_slot_count: int
    return_grille_count: int
    nominal_size_code: str
    actual_measured_size_code: Optional[str]
    size_capture_count: int
    status: str


class FilterSku(MutableEntity):
    sku_code: str
    size_code: str
    thickness_inches: int
    merv_rating: int
    unit_cost_cents: int
    ship_weight_oz: int
    pack_quantity: int
    status: str


class Resident(MutableEntity):
    full_name: str
    email: str
    household_size: int
    has_pets: bool
    smoker: bool
    allergy_flag: bool
    status: str


class Subscription(MutableEntity):
    resident_id: str
    unit_id: str
    property_id: str
    assigned_sku_id: Optional[str]
    predecessor_subscription_id: Optional[str]
    billing_party: str
    enrollment_channel: str
    lease_start_date: str
    lease_end_date: str
    status: str
    installation_posture: str
    ship_cadence_days: int
    filters_per_shipment: int
    monthly_fee_cents: int
    entitled_benefit_codes: List[str]
    next_ship_date: Optional[str]
    shipment_sequence_counter: int
    activated_at: Optional[str]
    cancel_effective_date: Optional[str]
    cancel_reason: Optional[str]
    gross_prorated_credit_cents: int
    waiver_credit_pct: str
    unreturned_fee_gross_cents: int
    unreturned_fee_net_cents: int
    net_settlement_cents: int
    latest_detection_method: Optional[str]
    latest_evidence_score: Optional[int]


class Shipment(MutableEntity):
    subscription_id: str
    sku_id: str
    sequence_number: int
    scheduled_ship_date: str
    quantity: int
    tracking_code: Optional[str]
    shipped_at: Optional[str]
    delivered_at: Optional[str]
    returned_at: Optional[str]
    unreturned_fee_cents: int
    status: str


class RuntimeReading(ImmutableEntity):
    unit_id: str
    window_start: str
    window_end: str
    runtime_minutes: int
    static_pressure_delta_pa: int
    source: str


class RenewalSurvey(ImmutableEntity):
    subscription_id: str
    installed_last_shipment: bool
    filters_on_hand_count: int
    self_reported_change_date: Optional[str]
    submitted_at: str


class NonInstallCase(MutableEntity):
    subscription_id: str
    detection_method: str
    evidence_score: int
    suspect_threshold: int
    confirm_threshold: int
    opened_at: str
    notice_sent_at: Optional[str]
    remediation_deadline: Optional[str]
    remediation_note: Optional[str]
    status: str


class Claim(MutableEntity):
    subscription_id: str
    claim_type: str
    incident_date: str
    requested_amount_cents: int
    description: str
    provisional_amount_cents: Optional[int]
    approved_amount_cents: Optional[int]
    triaged_by_user_id: Optional[str]
    decided_by_user_id: Optional[str]
    info_request_round: int
    paid_at: Optional[str]
    reversal_reason: Optional[str]
    status: str


class BenefitEntitlement(MutableEntity):
    subscription_id: str
    benefit_code: str
    state: str
    suspended_by_property_event: bool
    effective_from: Optional[str]
    terminated_at: Optional[str]
    forfeit_reason: Optional[str]


class LedgerEntry(ImmutableEntity):
    subscription_id: str
    entry_type: str
    amount_cents: int
    billed_party: str
    period_start: Optional[str]
    period_end: Optional[str]
    source_ref_id: str
    memo: Optional[str]


class SubscriptionTransfer(MutableEntity):
    subscription_id: str
    to_unit_id: str
    effective_date: str
    remapped_sku_id: Optional[str]
    proration_credit_cents: int
    proration_charge_cents: int
    net_adjustment_cents: int
    successor_subscription_id: Optional[str]
    rejection_reason: Optional[str]
    status: str


# Entities whose rows are append-only: no updated_at, no version.
IMMUTABLE_ENTITY_NAMES = ["RuntimeReading", "RenewalSurvey", "LedgerEntry"]
