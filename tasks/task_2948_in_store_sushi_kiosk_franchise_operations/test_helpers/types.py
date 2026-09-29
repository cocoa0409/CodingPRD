"""Typed shapes for every resource the API returns.

Resources carry ``id`` and ``created_at``; most also carry ``updated_at`` and a
``version`` that starts at 1 and increases by one on every mutation. Cold-chain
readings and discard events are append-only and carry neither, which is why they
have their own base shape.

All keys are optional at the type level so that tests can assert on the subset
of fields a given endpoint is specified to return.
"""

from typing import Any, Optional, TypedDict


class ResourceBase(TypedDict, total=False):
    """Identity and audit fields shared by versioned resources."""

    id: str
    created_at: str
    updated_at: str
    version: int


class AppendOnlyBase(TypedDict, total=False):
    """Identity fields for append-only records, which are never updated."""

    id: str
    created_at: str


class PosSalesFeedLine(TypedDict, total=False):
    """One per-pack-lot register line inside a POS sales feed."""

    pack_lot_id: str
    units_sold: int
    was_markdown: bool


class KioskRiskSummary(TypedDict, total=False):
    """The computed risk decomposition read for one kiosk."""

    kiosk_id: str
    minor_open: int
    major_open: int
    critical_open: int
    approved_variance_count: int
    quarantined_lot_count: int
    clean_audit_credit: int
    raw_risk_points: int
    risk_points: int
    sanitation_posture: str
    posture_forced_by_critical: bool


class HostStore(ResourceBase, total=False):
    """HostStore resource as returned by the API."""

    name: Optional[str]
    banner_chain: Optional[str]
    store_number: Optional[str]
    state_code: Optional[str]
    weekly_traffic_count: Optional[int]
    sushi_space_sqft: Optional[int]
    refrigerated_case_linear_ft: Optional[float]
    refrigerated_case_capacity_packs: Optional[int]
    pos_integration_status: Optional[str]
    pos_terminal_count: Optional[int]
    attested_sushi_space_sqft: Optional[int]
    attested_case_linear_ft: Optional[float]
    last_attested_on: Optional[str]
    space_compliance_state: Optional[str]


class LicenseAgreement(ResourceBase, total=False):
    """LicenseAgreement resource as returned by the API."""

    host_store_id: Optional[str]
    status: Optional[str]
    revenue_share_model: Optional[str]
    markdown_policy: Optional[str]
    min_space_sqft_obligation: Optional[int]
    min_case_linear_ft_obligation: Optional[float]
    space_credit_cents_per_sqft: Optional[int]
    effective_from: Optional[str]
    effective_to: Optional[str]
    space_shortfall_sqft: Optional[int]
    active_kiosk_count: Optional[int]
    lifetime_share_accrued_cents: Optional[int]
    suspension_reason: Optional[str]


class Kiosk(ResourceBase, total=False):
    """Kiosk resource as returned by the API."""

    license_agreement_id: Optional[str]
    kiosk_code: Optional[str]
    case_footprint_sqft: Optional[int]
    lead_chef_id: Optional[str]
    operational_state: Optional[str]
    sanitation_posture: Optional[str]
    daily_pack_cap: Optional[int]
    certified_chef_count: Optional[int]
    risk_points: Optional[int]
    open_critical_finding_count: Optional[int]
    consecutive_clean_audits: Optional[int]
    commissioned_on: Optional[str]
    suspension_reason: Optional[str]


class Chef(ResourceBase, total=False):
    """Chef resource as returned by the API."""

    full_name: Optional[str]
    assigned_kiosk_id: Optional[str]
    status: Optional[str]
    training_hours_logged: Optional[float]
    food_handler_cert_expires_at: Optional[str]
    haccp_cert_expires_at: Optional[str]
    valid_cert_count: Optional[int]


class Certification(ResourceBase, total=False):
    """Certification resource as returned by the API."""

    chef_id: Optional[str]
    cert_type: Optional[str]
    exam_score: Optional[float]
    issued_at: Optional[str]
    valid_days: Optional[int]
    expires_at: Optional[str]
    status: Optional[str]
    revocation_reason: Optional[str]


class ProductionPlan(ResourceBase, total=False):
    """ProductionPlan resource as returned by the API."""

    kiosk_id: Optional[str]
    production_date: Optional[str]
    traffic_forecast: Optional[int]
    status: Optional[str]
    planned_pack_count: Optional[int]
    planned_rice_kg: Optional[float]
    posture_factor_applied: Optional[float]
    binding_cap_source: Optional[str]
    actual_pack_count: Optional[int]
    forecast_variance_pct: Optional[float]
    superseded_plan_id: Optional[str]
    void_reason: Optional[str]


class RiceBatch(ResourceBase, total=False):
    """RiceBatch resource as returned by the API."""

    production_plan_id: Optional[str]
    chef_id: Optional[str]
    rice_kg: Optional[float]
    vinegar_liters: Optional[float]
    hold_start_at: Optional[str]
    hold_end_at: Optional[str]
    status: Optional[str]
    measured_ph: Optional[float]
    ph_measured_at: Optional[str]
    max_temp_c: Optional[float]
    exposure_minutes: Optional[int]
    max_pack_yield: Optional[int]
    documented_ph: Optional[float]
    documented_hold_minutes: Optional[int]
    corrective_narrative: Optional[str]
    variance_submitted_by_chef_id: Optional[str]
    variance_reviewed_by_user_id: Optional[str]
    rejection_reason: Optional[str]


class FishLot(ResourceBase, total=False):
    """FishLot resource as returned by the API."""

    kiosk_id: Optional[str]
    species: Optional[str]
    supplier_code: Optional[str]
    harvest_method: Optional[str]
    net_weight_kg: Optional[float]
    received_at: Optional[str]
    receiving_temp_c: Optional[float]
    status: Optional[str]
    parasite_destruction_required: Optional[bool]
    destruction_method: Optional[str]
    freeze_start_at: Optional[str]
    freeze_end_at: Optional[str]
    freeze_min_temp_c: Optional[float]
    freeze_effective_hours: Optional[float]
    parasite_destruction_compliant: Optional[bool]
    attested_by_chef_id: Optional[str]
    cold_chain_breach_minutes: Optional[int]
    allocated_kg: Optional[float]
    remaining_kg: Optional[float]
    quarantine_reason: Optional[str]


class ColdChainReading(AppendOnlyBase, total=False):
    """ColdChainReading resource as returned by the API."""

    fish_lot_id: Optional[str]
    recorded_at: Optional[str]
    temp_c: Optional[float]
    interval_minutes_from_previous: Optional[int]
    breach_minutes_attributed: Optional[int]
    lot_breach_minutes_after: Optional[int]


class PackLot(ResourceBase, total=False):
    """PackLot resource as returned by the API."""

    rice_batch_id: Optional[str]
    fish_lot_id: Optional[str]
    sku_code: Optional[str]
    pack_count: Optional[int]
    list_price_cents: Optional[int]
    produced_at: Optional[str]
    shelf_expiry_at: Optional[str]
    status: Optional[str]
    markdown_price_cents: Optional[int]
    advisory_markdown_price_cents: Optional[int]
    markdown_variant_applied: Optional[str]
    consumed_fish_kg: Optional[float]
    sold_count: Optional[int]
    discarded_count: Optional[int]
    unsold_count: Optional[int]
    void_reason: Optional[str]


class DiscardEvent(AppendOnlyBase, total=False):
    """DiscardEvent resource as returned by the API."""

    pack_lot_id: Optional[str]
    reason: Optional[str]
    discarded_count: Optional[int]
    unit_value_cents: Optional[int]
    discard_value_cents: Optional[int]
    settlement_credit_eligible: Optional[bool]
    recorded_by_user_id: Optional[str]


class PosSalesFeed(ResourceBase, total=False):
    """PosSalesFeed resource as returned by the API."""

    host_store_id: Optional[str]
    business_date: Optional[str]
    gross_sales_cents: Optional[int]
    markdown_sales_cents: Optional[int]
    full_price_units: Optional[int]
    markdown_units: Optional[int]
    lines: list[PosSalesFeedLine]
    status: Optional[str]
    reconciled_unit_total: Optional[int]
    rejection_reason: Optional[str]


class SettlementStatement(ResourceBase, total=False):
    """SettlementStatement resource as returned by the API."""

    license_agreement_id: Optional[str]
    period_start: Optional[str]
    period_end: Optional[str]
    status: Optional[str]
    gross_sales_cents: Optional[int]
    markdown_sales_cents: Optional[int]
    settlement_base_cents: Optional[int]
    binding_share_cents: Optional[int]
    advisory_share_cents: Optional[int]
    variance_cents: Optional[int]
    space_shortfall_credit_cents: Optional[int]
    period_discard_value_cents: Optional[int]
    discard_credit_cents: Optional[int]
    net_due_cents: Optional[int]
    binding_variant: Optional[str]
    revision_round: Optional[int]
    created_by_user_id: Optional[str]
    issued_by_user_id: Optional[str]
    superseded_statement_id: Optional[str]
    dispute_reason: Optional[str]
    revision_note: Optional[str]
    void_reason: Optional[str]
    paid_amount_cents: Optional[int]
    paid_at: Optional[str]


class FoodSafetyAudit(ResourceBase, total=False):
    """FoodSafetyAudit resource as returned by the API."""

    kiosk_id: Optional[str]
    scheduled_for: Optional[str]
    status: Optional[str]
    opened_by_user_id: Optional[str]
    verified_by_user_id: Optional[str]
    round_count: Optional[int]
    critical_finding_count: Optional[int]
    open_finding_count: Optional[int]
    score: Optional[int]
    closure_outcome: Optional[str]


class AuditFinding(ResourceBase, total=False):
    """AuditFinding resource as returned by the API."""

    audit_id: Optional[str]
    severity: Optional[str]
    finding_code: Optional[str]
    description: Optional[str]
    status: Optional[str]
    risk_points: Optional[int]
    correction_note: Optional[str]
    waiver_rationale: Optional[str]


JsonDict = dict[str, Any]
