"""TypedDict shapes for every entity the API returns.

Every entity except JournalPosting carries the common fields id, created_at,
updated_at and version. JournalPosting is append-only and carries only id and
created_at, so its shape deliberately omits updated_at and version.
"""

from typing import Any, Dict, List, Optional, TypedDict


class CommonFields(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


class HotelProperty(CommonFields, total=False):
    name: str
    room_count_total: int
    standard_room_rate_amount: float
    occupancy_tax_rate_pct: float
    fb_tax_rate_pct: float
    service_charge_pct: float
    large_ticket_threshold_amount: float
    large_party_discount_pct: float
    late_checkout_grace_minutes: int
    allowance_manager_threshold_amount: float
    allowance_controller_threshold_amount: float
    rate_variance_tolerance_pct: float
    settlement_variance_tolerance_amount: float
    card_authorization_valid_days: int
    city_ledger_fee_pct: float
    no_show_charge_policy: str


class Outlet(CommonFields, total=False):
    property_id: str
    outlet_code: str
    outlet_name: str
    outlet_type: str
    requires_shift_settlement: bool
    status: str


class AccountingPeriod(CommonFields, total=False):
    property_id: str
    period_month: str
    status: str
    gl_control_total_amount: Optional[float]
    subsystem_total_amount: Optional[float]
    tie_out_variance_amount: Optional[float]
    tie_out_attempt_count: int
    tied_out_by_user_id: Optional[str]
    tied_out_at: Optional[str]
    audit_trail_retention_until_date: Optional[str]


class BusinessDate(CommonFields, total=False):
    property_id: str
    accounting_period_id: str
    business_date: str
    status: str
    out_of_order_room_count: int
    benchmark_calendar_room_revenue_amount: Optional[float]
    benchmark_weekday_room_revenue_amount: Optional[float]
    rooms_available_count: int
    rooms_occupied_count: int
    room_night_revenue_amount: float
    other_room_revenue_amount: float
    room_revenue_amount: float
    tax_revenue_amount: float
    outlet_revenue_amount: float
    closed_outlet_ticket_count: int
    allowance_credit_amount: float
    total_revenue_amount: float
    occupancy_pct: float
    adr_amount: float
    revpar_amount: float
    settlement_variance_total_amount: float
    unresolved_settlement_batch_count: int
    ledger_control_amount: float
    declined_authorization_count: int
    city_ledger_swept_folio_count: int
    city_ledger_transferred_balance_total_amount: float
    city_ledger_fee_total_amount: float
    reopen_count: int


class Folio(CommonFields, total=False):
    property_id: str
    arrival_business_date_id: str
    confirmation_code: str
    guest_name: str
    room_number: str
    nights_count: int
    contracted_rate_amount: float
    rate_plan_code: str
    market_segment: str
    settlement_method: str
    scheduled_checkout_at: str
    actual_checkout_at: Optional[str]
    is_comp: bool
    credit_limit_amount: Optional[float]
    stay_status: str
    settlement_status: str
    rate_variance_pct: float
    charges_total_amount: float
    credits_total_amount: float
    balance_amount: float
    settlement_hold: bool


class JournalPosting(TypedDict, total=False):
    """Append-only: id and created_at only, no updated_at and no version."""

    id: str
    created_at: str
    folio_id: Optional[str]
    ledger_account_id: Optional[str]
    business_date_id: str
    outlet_ticket_id: Optional[str]
    allowance_id: Optional[str]
    reverses_posting_id: Optional[str]
    charge_type: str
    amount: float
    night_index: Optional[int]
    source_channel: str
    reason_code: Optional[str]
    posted_by_user_id: str
    memo: Optional[str]


class OutletTicket(CommonFields, total=False):
    outlet_id: str
    business_date_id: str
    room_charge_folio_id: Optional[str]
    ticket_number: str
    gross_amount: float
    settlement_type: str
    opened_at: str
    transmitted_at: Optional[str]
    status: str
    service_charge_amount: float
    taxable_base_amount: float
    tax_amount: float
    large_party_discount_amount: float
    total_amount: float
    closed_by_user_id: Optional[str]
    closed_at: Optional[str]
    voided_at: Optional[str]


class SettlementBatch(CommonFields, total=False):
    business_date_id: str
    outlet_id: str
    tender_type: str
    shift_start_at: str
    shift_end_at: str
    declared_amount: float
    system_amount: Optional[float]
    variance_amount: Optional[float]
    status: str
    recount_round: int
    declared_by_user_id: str
    accepted_by_user_id: Optional[str]


class LedgerAccount(CommonFields, total=False):
    property_id: str
    ledger_type: str
    account_code: str
    gl_account_code: str
    opening_balance_amount: float
    credit_limit_amount: Optional[float]
    current_balance_amount: float


class Allowance(CommonFields, total=False):
    folio_id: str
    business_date_id: str
    reverses_allowance_id: Optional[str]
    reason_code: Optional[str]
    requested_amount: float
    approved_amount: Optional[float]
    narrative: Optional[str]
    supporting_document_reference: Optional[str]
    status: str
    required_approval_role: str
    revision_round: int
    requested_by_user_id: str
    approved_by_user_id: Optional[str]
    submitted_at: Optional[str]
    approved_at: Optional[str]


class AuthorizationDocument(CommonFields, total=False):
    property_id: str
    folio_id: Optional[str]
    allowance_id: Optional[str]
    doc_type: str
    authorized_by_name: str
    document_reference: str
    authorized_rate_amount: Optional[float]
    valid_from_date: str
    valid_to_date: str
    status: str
    reviewed_by_user_id: Optional[str]
    filed_by_user_id: str
    reviewed_at: Optional[str]


class CardAuthorization(CommonFields, total=False):
    folio_id: str
    obtained_at: str
    authorized_amount: float
    status: str
    follow_up_status: str
    decline_code: Optional[str]
    aging_days: int
    captured_amount: Optional[float]
    resolved_by_user_id: Optional[str]
    follow_up_note: Optional[str]


class RevenueReport(CommonFields, total=False):
    business_date_id: str
    pace_basis: str
    rooms_available_count: int
    rooms_occupied_count: int
    occupancy_pct: float
    adr_amount: float
    revpar_amount: float
    room_revenue_amount: float
    tax_revenue_amount: float
    outlet_revenue_amount: float
    total_revenue_amount: float
    benchmark_room_revenue_amount: Optional[float]
    pace_index_pct: Optional[float]
    status: str
    recipient_role_list: List[str]
    distributed_at: Optional[str]
    generated_by_user_id: str


Headers = Dict[str, str]
Payload = Dict[str, Any]
