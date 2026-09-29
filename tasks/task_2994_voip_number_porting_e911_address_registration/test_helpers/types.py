"""TypedDict shapes for every entity the API returns.

Field lists follow the PRD entity narratives. Per PRD §2.5 most resources carry
`id`, `created_at`, `updated_at` and `version`; `Carrier` and `CallAttempt` are
immutable and carry `id` and `created_at` only, with no `updated_at` and no
`version`.
"""
from typing import Any, Dict, List, Optional, TypedDict


class CommonFields(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int


class ImmutableCommonFields(TypedDict, total=False):
    id: str
    created_at: str


class Account(CommonFields, total=False):
    account_number: str
    billing_name: str
    service_state_code: str
    status: str
    intl_calling_enabled: bool
    intl_daily_cap_cents: int
    e911_compliance_posture: str
    fee_liability_cents: int
    ported_number_count: int


class Carrier(ImmutableCommonFields, total=False):
    name: str
    ocn: str
    csr_match_policy: str
    porting_buffer_minutes: int
    foc_business_days: int


class Jurisdiction(CommonFields, total=False):
    state_code: str
    county_fips: str
    fee_type: str
    monthly_fee_cents: int
    remit_day_of_month: int
    pending_fee_cents: int
    remitted_fee_cents: int
    last_remitted_period: Optional[str]


class NumberBlock(CommonFields, total=False):
    jurisdiction_id: str
    npa_nxx: str
    total_capacity: int
    max_concurrent_reservations: int
    minted_count: int
    available_count: int
    reserved_count: int
    assigned_count: int
    parked_count: int


class PhoneNumber(CommonFields, total=False):
    block_id: str
    line_number: str
    e164: str
    status: str
    assigned_account_id: Optional[str]
    parked_until: Optional[str]
    park_cycle_count: int


class NumberReservation(CommonFields, total=False):
    block_id: str
    account_id: str
    number_id: Optional[str]
    purpose: str
    reserved_from: str
    reserved_until: str
    status: str
    released_reason: Optional[str]


class PortRequest(CommonFields, total=False):
    account_id: str
    losing_carrier_id: str
    requested_numbers: List[str]
    claimed_account_number: str
    claimed_pin: str
    claimed_billing_name: str
    claimed_address_line1: str
    claimed_zip: str
    status: str
    resubmission_count: int
    last_rejection_code: Optional[str]
    last_match_points: Optional[int]
    last_mismatch_fields: List[str]
    validated_at: Optional[str]
    earliest_cutover_at: Optional[str]
    created_by_user_id: str


class CarrierAccountSnapshot(CommonFields, total=False):
    port_request_id: str
    account_number_on_file: str
    pin_on_file: str
    billing_name_on_file: str
    address_line1_on_file: str
    zip_on_file: str
    match_points: int
    mismatch_fields: List[str]
    threshold_applied: int
    match_status: str
    superseded_at: Optional[str]


class CutoverSlot(CommonFields, total=False):
    carrier_id: str
    window_start: str
    window_end: str
    status: str
    booked_port_request_id: Optional[str]
    booked_at: Optional[str]


class TemporaryBridge(CommonFields, total=False):
    port_request_id: str
    reservation_id: str
    bridge_number_id: str
    status: str
    activated_at: Optional[str]
    released_at: Optional[str]


class Device(CommonFields, total=False):
    account_id: str
    mac_address: str
    device_type: str
    nomadic: bool
    assigned_number_id: Optional[str]
    registration_status: str
    calling_status: str
    toll_fraud_score: int
    fraud_block_count: int
    last_network_report_at: Optional[str]
    reported_state_code: Optional[str]
    reported_postal_code: Optional[str]
    registration_prompt_deadline: str


class E911Registration(CommonFields, total=False):
    device_id: str
    account_id: str
    jurisdiction_id: str
    address_line1: str
    unit: str
    city: str
    state_code: str
    postal_code: str
    normalized_location_key: str
    verification_status: str
    effective_from: str
    verified_at: Optional[str]
    superseded_at: Optional[str]
    rejection_note: Optional[str]


class CallAttempt(ImmutableCommonFields, total=False):
    device_id: str
    destination_e164: str
    destination_country_code: str
    requested_duration_seconds: int
    decision: str
    decision_error_id: Optional[str]
    billable_minutes: int
    rate_cents_per_minute: int
    estimated_base_cents: int
    realtime_risk_score: int
    day_subtotal_cents: int
    surcharge_pct_applied: int
    projected_day_total_cents: int


class FeeAssessment(CommonFields, total=False):
    account_id: str
    jurisdiction_id: str
    period_month: str
    variant: str
    unit_basis: str
    billable_units: int
    unit_fee_breakdown: List[int]
    amount_cents: int
    status: str
    assessed_by_user_id: str
    voided_by_user_id: Optional[str]
    remitted_at: Optional[str]


class ClockReading(TypedDict, total=False):
    current_utc: str
    previous_utc: Optional[str]


JsonDict = Dict[str, Any]

__all__ = [
    "Account",
    "Carrier",
    "Jurisdiction",
    "NumberBlock",
    "PhoneNumber",
    "NumberReservation",
    "PortRequest",
    "CarrierAccountSnapshot",
    "CutoverSlot",
    "TemporaryBridge",
    "Device",
    "E911Registration",
    "CallAttempt",
    "FeeAssessment",
    "ClockReading",
    "CommonFields",
    "ImmutableCommonFields",
    "JsonDict",
]
