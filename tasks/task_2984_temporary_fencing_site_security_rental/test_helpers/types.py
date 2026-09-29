"""TypedDict shapes for the eleven resource types of the PRD.

Every one of the eleven resource types carries the common fields of PRD §2.4 —
``id``, ``created_at``, ``updated_at`` and ``version`` — because the PRD states
explicitly that no entity in this system is exempt.
"""

from typing import Any, Dict, List, Optional, TypedDict


class CommonFields(TypedDict):
    """PRD §2.4 common fields, carried by all eleven resource types."""

    id: str
    created_at: str
    updated_at: str
    version: int


class Municipality(CommonFields, total=False):
    name: str
    jurisdiction_code: str
    permit_lead_time_days: int
    max_concurrent_closure_linear_feet: int
    permit_review_rounds_allowed: int
    rental_tax_rate_bp: int
    allows_solid_wind_screen: bool
    committed_closure_linear_feet: int


class CustomerAccount(CommonFields, total=False):
    legal_name: str
    billing_email: str
    credit_limit_cents: int
    open_balance_cents: int
    lifetime_credited_cents: int
    credit_hold_flag: bool


class Jobsite(CommonFields, total=False):
    customer_account_id: str
    municipality_id: str
    site_label: str
    address_line: str
    site_condition: str
    phase_count: int
    requires_sidewalk_closure: bool


class FenceProduct(CommonFields, total=False):
    code: str
    category: str
    description: str
    panel_length_ft: Optional[int]
    unit_monthly_rate_cents: int
    replacement_cost_cents_per_unit: int
    fleet_age_months: int
    wind_load_rating_mph: Optional[int]
    owned_count: int
    available_count: int
    reserved_count: int
    deployed_count: int
    damaged_count: int
    lost_count: int


class Crew(CommonFields, total=False):
    crew_code: str
    depot_code: str
    daily_capacity_hours: float
    certified_for_solid_screen: bool


class PricedLine(TypedDict, total=False):
    line_type: str
    product_code: Optional[str]
    quantity: int
    amount_cents: int


class Quote(CommonFields, total=False):
    jobsite_id: str
    status: str
    contract_type: str
    linear_feet: int
    panel_product_code: str
    panel_unit_count: int
    term_months: int
    wind_screen: str
    addon_lines: List[Dict[str, Any]]
    tier_rate_cents_per_ft: int
    monthly_recurring_cents: int
    install_labor_cents: int
    permit_handling_fee_cents: int
    one_time_cents: int
    priced_lines: List[PricedLine]
    accepted_by_name: Optional[str]
    issued_at_utc: Optional[str]
    valid_through_utc: Optional[str]


class PermitApplication(CommonFields, total=False):
    jobsite_id: str
    status: str
    closure_linear_feet: int
    closure_start_utc: str
    closure_end_utc: str
    sidewalk_closure_type: str
    revision_round: int
    submitted_at_utc: Optional[str]
    decided_at_utc: Optional[str]
    reviewer_note: Optional[str]
    required_change_summary: Optional[str]


class FleetCommitment(TypedDict, total=False):
    product_code: str
    unit_count: int


class RentalContract(CommonFields, total=False):
    quote_id: str
    jobsite_id: str
    customer_account_id: str
    contract_type: str
    lifecycle_status: str
    billing_status: str
    current_phase: int
    pinned_quote_version: int
    ordered_linear_feet: int
    deployed_linear_feet: int
    monthly_recurring_cents: int
    install_labor_cents: int
    permit_handling_fee_cents: int
    one_time_cents: int
    fleet_commitments: List[FleetCommitment]
    addons_deployed: bool
    cancellation_fee_cents: int
    billing_anchor_utc: Optional[str]
    billed_through_utc: Optional[str]
    terms_acknowledged_by: str


class WorkOrder(CommonFields, total=False):
    contract_id: str
    work_order_type: str
    status: str
    ordered_linear_feet: int
    completed_linear_feet: Optional[int]
    crew_id: Optional[str]
    scheduled_start_utc: Optional[str]
    scheduled_end_utc: Optional[str]
    estimated_labor_hours: Optional[float]
    reserved_unit_counts: List[FleetCommitment]
    phase_from: Optional[int]
    phase_to: Optional[int]
    predecessor_work_order_id: Optional[str]
    predecessor_relation: Optional[str]
    completed_by_user_id: Optional[str]
    abort_reason_code: Optional[str]
    cancel_reason_code: Optional[str]


class InvoiceLine(TypedDict, total=False):
    line_type: str
    product_code: Optional[str]
    quantity: int
    amount_cents: int


class Invoice(CommonFields, total=False):
    contract_id: str
    customer_account_id: str
    invoice_kind: str
    status: str
    lines: List[InvoiceLine]
    subtotal_cents: int
    tax_cents: int
    late_fee_cents: int
    total_cents: int
    amount_paid_cents: int
    issued_at_utc: str
    due_at_utc: str
    issued_by_user_id: str
    void_reason_code: Optional[str]
    period_start_utc: Optional[str]
    period_end_utc: Optional[str]
    billable_days: int


class UnitReturn(TypedDict, total=False):
    product_code: str
    returned: int
    damaged: int
    missing: int


class RemovalReconciliation(CommonFields, total=False):
    contract_id: str
    work_order_id: str
    status: str
    deployed_snapshot: List[FleetCommitment]
    unit_returns: List[UnitReturn]
    assessment_variant: Optional[str]
    loss_charge_cents: int
    damage_charge_cents: int
    theft_police_report_number: Optional[str]
    auditor_note: Optional[str]
    finalized_by_user_id: Optional[str]
