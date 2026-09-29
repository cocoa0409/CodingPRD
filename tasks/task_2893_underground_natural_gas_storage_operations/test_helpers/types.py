"""TypedDict shapes for every persisted record the API returns.

PRD §2.4: "Every business record in the system carries an `id` ... and a
`created_at` ... Most records additionally carry `updated_at` ... and
`version`. ... The single exception is the balancing ledger. An
`ImbalanceLedgerEntry` is append-only and immutable once written, so it carries
only `id` and `created_at`; it has neither `updated_at` nor `version`, and those
keys must be absent from its representation."

Every TypedDict below therefore inherits from CommonFields except
ImbalanceLedgerEntry, which inherits from AppendOnlyFields.
"""

from typing import Any, Dict, List, Optional, TypedDict


class CommonFields(TypedDict):
    """id + created_at + updated_at + version."""

    id: str
    created_at: str
    updated_at: str
    version: int


class AppendOnlyFields(TypedDict):
    """id + created_at only -- no updated_at, no version."""

    id: str
    created_at: str


class DeliverabilityCurvePoint(TypedDict):
    inventory_pct: float
    withdrawal_dth_per_day: int
    injection_dth_per_day: int


class StorageField(CommonFields, total=False):
    name: str
    field_code: str
    total_capacity_dth: int
    cushion_gas_dth: int
    base_pressure_psig: int
    pressure_span_psig: int
    max_pressure_psig: int
    deliverability_curve: List[DeliverabilityCurvePoint]
    deliverability_method: str
    season: str
    opening_working_gas_dth: float
    max_working_gas_dth: float
    working_gas_inventory_dth: float
    retained_fuel_pool_dth: float
    fuel_gas_used_dth: float
    inventory_pct: float
    current_pressure_psig: int
    deliverability_tier: str
    max_injection_rate_dth_per_day: int
    max_withdrawal_rate_dth_per_day: int
    wells_in_service_count: int
    field_posture: str


class Well(CommonFields, total=False):
    storage_field_id: str
    well_name: str
    well_type: str
    rated_rate_dth_per_day: int
    last_mit_passed_at: str
    mit_due_at: str
    casing_pressure_psig: int
    operational_state: str
    integrity_state: str
    shut_in_reason: Optional[str]
    service_change_count: int


class MechanicalIntegrityTest(CommonFields, total=False):
    well_id: str
    test_type: str
    scheduled_start_at: str
    scheduled_end_at: str
    status: str
    outcome: Optional[str]
    result_pressure_psig: Optional[int]
    recorded_by_user_id: Optional[str]
    recorded_at: Optional[str]


class RemediationProgram(CommonFields, total=False):
    well_id: str
    triggering_mit_id: str
    status: str
    opened_at: str
    due_at: str
    completed_by_user_id: Optional[str]
    completed_at: Optional[str]
    verification_notes: Optional[str]


class CompressorUnit(CommonFields, total=False):
    storage_field_id: str
    unit_code: str
    rated_horsepower: int
    derate_factor: float
    status: str
    lifetime_fuel_dth: float
    scheduled_run_count: int


class CompressorRun(CommonFields, total=False):
    compressor_unit_id: str
    window_start_at: str
    window_end_at: str
    allocated_horsepower: int
    mode: str
    duration_hours: float
    effective_horsepower: float
    utilization_ratio: float
    utilization_band: str
    status: str
    fuel_consumed_dth: Optional[float]


class Shipper(CommonFields, total=False):
    legal_name: str
    duns_number: str
    penalty_threshold_usd: float
    outstanding_penalty_usd: float
    credit_status: str


class StorageContract(CommonFields, total=False):
    shipper_id: str
    storage_field_id: str
    contract_code: str
    service_class: str
    max_storage_quantity_dth: int
    max_daily_injection_dth: int
    max_daily_withdrawal_dth: int
    term_start_date: str
    term_end_date: str
    commodity_rate_usd_per_dth: float
    index_price_usd_per_dth: float
    cash_out_method: str
    status: str
    activated_at: Optional[str]
    inventory_balance_dth: float
    imbalance_dth: float
    cash_out_amount_usd: float
    cash_out_through_date: Optional[str]
    scheduled_injection_dth: int
    scheduled_withdrawal_dth: int


class Nomination(CommonFields, total=False):
    contract_id: str
    gas_day: str
    direction: str
    nominated_volume_dth: int
    confirmed_volume_dth: int
    curtailed_volume_dth: int
    revision_round: int
    status: str
    submitted_at: Optional[str]
    confirmed_at: Optional[str]
    superseded_by_nomination_id: Optional[str]


class GasMovementTicket(CommonFields, total=False):
    nomination_id: str
    well_id: str
    actual_volume_dth: int
    status: str
    fuel_retention_dth: Optional[float]
    net_volume_dth: Optional[float]
    commodity_charge_usd: Optional[float]
    volume_discount_usd: Optional[float]
    fuel_charge_usd: Optional[float]
    total_charge_usd: Optional[float]
    confirmed_at: Optional[str]
    reversal_reason: Optional[str]


class ImbalanceLedgerEntry(AppendOnlyFields, total=False):
    """No updated_at and no version -- PRD §2.4 and §3.7."""

    contract_id: str
    entry_type: str
    gas_day: Optional[str]
    volume_dth: float
    amount_usd: float
    origin_note: str


class EmergencyEvent(CommonFields, total=False):
    storage_field_id: str
    well_id: Optional[str]
    event_type: str
    severity: str
    detected_at: str
    status: str
    evacuation_radius_m: int
    responder_notes: Optional[str]
    contained_at: Optional[str]
    closed_at: Optional[str]


class RegulatoryReport(CommonFields, total=False):
    storage_field_id: str
    report_type: str
    period_start_date: str
    period_end_date: str
    measured_inventory_dth: float
    book_inventory_dth: float
    variance_dth: float
    variance_pct: float
    open_finding_count: int
    status: str
    prepared_by_user_id: str
    submitted_by_user_id: Optional[str]
    agency_outcome: Optional[str]
    agency_response_note: Optional[str]


Payload = Dict[str, Any]
