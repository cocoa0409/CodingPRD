"""Typed shapes and enum vocabularies for the Interlibrary Loan API.

Every resource carries a server-minted `id` and a `created_at` instant. All of
them except `PatronNotification` also carry `updated_at` and `version`; the
notification TypedDict therefore deliberately omits both.
"""

from typing import Any, Dict, List, Optional, TypedDict


# --- Roles -------------------------------------------------------------------
class UserRole:
    PATRON = "Patron"
    ILL_BORROWING_STAFF = "IllBorrowingStaff"
    PARTNER_AGENT = "PartnerAgent"
    ACQUISITIONS_LIBRARIAN = "AcquisitionsLibrarian"
    CONSORTIUM_ACCOUNTANT = "ConsortiumAccountant"
    LIBRARY_ADMIN = "LibraryAdmin"


ALL_ROLES = (
    UserRole.PATRON,
    UserRole.ILL_BORROWING_STAFF,
    UserRole.PARTNER_AGENT,
    UserRole.ACQUISITIONS_LIBRARIAN,
    UserRole.CONSORTIUM_ACCOUNTANT,
    UserRole.LIBRARY_ADMIN,
)


# --- Enum vocabularies -------------------------------------------------------
class PatronType:
    FACULTY = "FACULTY"
    GRAD = "GRAD"
    UNDERGRAD = "UNDERGRAD"
    STAFF = "STAFF"


class PatronStatus:
    ACTIVE = "ACTIVE"
    BLOCKED = "BLOCKED"
    WITHDRAWN = "WITHDRAWN"


class InfractionKind:
    LOST = "LOST"
    DAMAGED = "DAMAGED"
    LATE_RETURN = "LATE_RETURN"
    UNCLAIMED = "UNCLAIMED"
    UNPAID_CHARGE = "UNPAID_CHARGE"


class PartnerStatus:
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    WITHDRAWN = "WITHDRAWN"


class FeeWaiverMode:
    NONE = "NONE"
    FULL = "FULL"
    CAPPED = "CAPPED"


class SettlementMode:
    GROSS = "GROSS"
    NET = "NET"


class AgreementStatus:
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"


class MaterialType:
    LOAN = "LOAN"
    COPY = "COPY"


class SelectionPolicy:
    LANDED_COST = "LANDED_COST"
    MANUAL_RANK = "MANUAL_RANK"


class RotaEntryStatus:
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class ItemType:
    BOOK = "BOOK"
    ARTICLE = "ARTICLE"
    CHAPTER = "CHAPTER"
    THESIS = "THESIS"
    MEDIA = "MEDIA"


class LocalHoldingStatus:
    NONE = "NONE"
    HELD_AVAILABLE = "HELD_AVAILABLE"
    HELD_CHECKED_OUT = "HELD_CHECKED_OUT"
    ON_ORDER = "ON_ORDER"


class LicensedAccessStatus:
    NONE = "NONE"
    LICENSED_FULL = "LICENSED_FULL"
    LICENSED_EMBARGOED = "LICENSED_EMBARGOED"


class ServiceType:
    LOAN = "LOAN"
    COPY = "COPY"


class DeliveryMode:
    PICKUP = "PICKUP"
    ELECTRONIC = "ELECTRONIC"
    MAIL = "MAIL"


class RequestStatus:
    SUBMITTED = "SUBMITTED"
    COPYRIGHT_HOLD = "COPYRIGHT_HOLD"
    SOURCING = "SOURCING"
    OFFER_PENDING = "OFFER_PENDING"
    SUPPLY_COMMITTED = "SUPPLY_COMMITTED"
    IN_TRANSIT = "IN_TRANSIT"
    ON_HOLD_SHELF = "ON_HOLD_SHELF"
    WITH_PATRON = "WITH_PATRON"
    RETURN_IN_TRANSIT = "RETURN_IN_TRANSIT"
    DELIVERED_ELECTRONIC = "DELIVERED_ELECTRONIC"
    ESCALATED_POD = "ESCALATED_POD"
    CLOSED = "CLOSED"
    CLOSED_WITH_DAMAGE = "CLOSED_WITH_DAMAGE"
    CLOSED_LOST = "CLOSED_LOST"
    UNCLAIMED = "UNCLAIMED"
    CANCELLED = "CANCELLED"
    UNFILLED = "UNFILLED"
    FILLED_BY_PURCHASE = "FILLED_BY_PURCHASE"


TERMINAL_REQUEST_STATUSES = (
    RequestStatus.CLOSED,
    RequestStatus.CLOSED_WITH_DAMAGE,
    RequestStatus.CLOSED_LOST,
    RequestStatus.UNCLAIMED,
    RequestStatus.CANCELLED,
    RequestStatus.UNFILLED,
    RequestStatus.FILLED_BY_PURCHASE,
)


class UnfilledReason:
    NONE = "NONE"
    ATTEMPTS_EXHAUSTED = "ATTEMPTS_EXHAUSTED"
    TRANSIT_LOST = "TRANSIT_LOST"


class OfferStatus:
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class DeclineReason:
    NONE = "NONE"
    NOT_HELD = "NOT_HELD"
    IN_USE = "IN_USE"
    POLICY = "POLICY"
    COST = "COST"


class ClearanceMethod:
    CONTU_FREE = "CONTU_FREE"
    ROYALTY_PAID = "ROYALTY_PAID"
    PRE_WINDOW_EXEMPT = "PRE_WINDOW_EXEMPT"


class ClearanceStatus:
    ACTIVE = "ACTIVE"
    VOIDED = "VOIDED"


class ShipmentDirection:
    INBOUND = "INBOUND"
    RETURN = "RETURN"


class ShipmentStatus:
    IN_TRANSIT = "IN_TRANSIT"
    RECEIVED = "RECEIVED"
    CONFIRMED_OK = "CONFIRMED_OK"
    CONFIRMED_DAMAGED = "CONFIRMED_DAMAGED"
    CONFIRMED_LOST = "CONFIRMED_LOST"
    LOST_IN_TRANSIT = "LOST_IN_TRANSIT"


class ShipmentCondition:
    OK = "OK"
    DAMAGED = "DAMAGED"
    LOST = "LOST"


class CustodyStatus:
    AWAITING_PICKUP = "AWAITING_PICKUP"
    WITH_PATRON = "WITH_PATRON"
    RETURN_PREPARED = "RETURN_PREPARED"
    UNCLAIMED_RETURN_PREPARED = "UNCLAIMED_RETURN_PREPARED"
    RETURNED_TO_LENDER = "RETURNED_TO_LENDER"
    DECLARED_LOST = "DECLARED_LOST"


class BillingStatus:
    NO_CHARGE = "NO_CHARGE"
    FINE_ACCRUED = "FINE_ACCRUED"
    DAMAGE_BILLED = "DAMAGE_BILLED"
    LOST_BILLED = "LOST_BILLED"
    CHARGE_SETTLED = "CHARGE_SETTLED"
    CHARGE_WAIVED = "CHARGE_WAIVED"


class RecallStatus:
    NONE = "NONE"
    RECALL_ISSUED = "RECALL_ISSUED"
    RECALL_HONORED = "RECALL_HONORED"
    RECALL_BREACHED = "RECALL_BREACHED"


class DeliveryStatus:
    AVAILABLE = "AVAILABLE"
    EXPIRED = "EXPIRED"
    EXHAUSTED = "EXHAUSTED"


class PodOrderStatus:
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    RECEIVED = "RECEIVED"
    CANCELLED = "CANCELLED"


class PodDecision:
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class LendingChargeStatus:
    OPEN = "OPEN"
    INVOICED = "INVOICED"


class InvoiceStatus:
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PAID = "PAID"
    DISPUTED = "DISPUTED"
    SUPERSEDED = "SUPERSEDED"


class InvoiceDirection:
    PAYABLE = "PAYABLE"
    RECEIVABLE = "RECEIVABLE"


class InvoiceSettleAction:
    PAY = "PAY"
    DISPUTE = "DISPUTE"
    REINSTATE = "REINSTATE"


class ChargeSettlementAction:
    PAY = "PAY"
    WAIVE = "WAIVE"


class NotificationKind:
    REQUEST_SUBMITTED = "REQUEST_SUBMITTED"
    COPYRIGHT_HOLD = "COPYRIGHT_HOLD"
    READY_FOR_PICKUP = "READY_FOR_PICKUP"
    ELECTRONIC_DELIVERY_READY = "ELECTRONIC_DELIVERY_READY"
    RECALL_ISSUED = "RECALL_ISSUED"
    UNCLAIMED = "UNCLAIMED"
    DAMAGE_BILLED = "DAMAGE_BILLED"
    LOST_BILLED = "LOST_BILLED"
    REQUEST_UNFILLED = "REQUEST_UNFILLED"
    POD_APPROVED = "POD_APPROVED"
    PURCHASE_RECEIVED = "PURCHASE_RECEIVED"
    DELIVERY_EXPIRED = "DELIVERY_EXPIRED"
    REQUEST_CANCELLED = "REQUEST_CANCELLED"


class NotificationChannel:
    EMAIL = "EMAIL"


# --- Entity shapes -----------------------------------------------------------
class CommonFields(TypedDict, total=False):
    """`id` plus `created_at`, `updated_at` and the mutation `version`."""

    id: str
    created_at: str
    updated_at: str
    version: int


class Patron(CommonFields, total=False):
    external_id: str
    full_name: str
    email: str
    patron_type: str
    department: str
    max_open_requests: int
    max_concurrent_loans: int
    unpaid_balance_cap_cents: int
    status: str
    historical_lost_count: int
    historical_damaged_count: int
    historical_late_return_count: int
    historical_unclaimed_count: int
    historical_unpaid_cents: int
    lost_count: int
    damaged_count: int
    late_return_count: int
    unclaimed_count: int
    unpaid_balance_cents: int
    pending_charge_cents: int
    open_request_count: int
    provisional_risk_score: int
    final_risk_score: int


class Partner(CommonFields, total=False):
    code: str
    name: str
    consortium_code: str
    base_lending_fee_cents: int
    avg_turnaround_days: int
    ships_physical: bool
    supplies_electronic: bool
    allows_renewals: bool
    loan_period_days: int
    max_renewals: int
    status: str
    borrowed_from_count: int
    lent_to_count: int
    net_borrow_imbalance_items: int
    borrow_payable_cents: int
    lend_receivable_cents: int


class ReciprocityAgreement(CommonFields, total=False):
    partner_id: str
    fee_waiver_mode: str
    settlement_mode: str
    turnaround_guarantee_days: int
    effective_from: str
    effective_to: str
    capped_waiver_cents: int
    balance_tolerance_items: int
    supersedes_agreement_id: Optional[str]
    status: str


class Rota(CommonFields, total=False):
    name: str
    material_type: str
    selection_policy: str
    max_attempts: int
    auto_escalate_pod: bool
    offer_response_hours: int


class RotaEntry(CommonFields, total=False):
    rota_id: str
    partner_id: str
    manual_rank: int
    quoted_fee_cents: int
    quoted_turnaround_days: int
    is_enabled: bool
    status: str


class BibItem(CommonFields, total=False):
    title: str
    item_type: str
    publication_year: int
    issn: Optional[str]
    isbn: Optional[str]
    journal_title: Optional[str]
    local_holding_status: str
    licensed_access_status: str
    embargo_months: int
    list_price_cents: int


class IllRequest(CommonFields, total=False):
    patron_id: str
    bib_item_id: str
    rota_id: str
    service_type: str
    delivery_mode: str
    needed_by: str
    max_supply_fee_cents: int
    pages_requested: Optional[int]
    intake_user_id: str
    copyright_required: bool
    status: str
    unfilled_reason: str
    attempt_count: int
    days_available_at_source: Optional[int]
    committed_partner_id: Optional[str]
    committed_fee_cents: int
    committed_loan_period_days: Optional[int]
    rush_surcharge_cents: int
    royalty_cents: int
    gross_charge_cents: int
    subsidy_cents: int
    net_patron_charge_cents: int
    fulfilled_at: Optional[str]
    closed_at: Optional[str]


class SupplyOffer(CommonFields, total=False):
    request_id: str
    partner_id: str
    attempt_seq: int
    quoted_fee_cents: int
    quoted_turnaround_days: int
    effective_fee_cents: int
    landed_cost_cents: int
    imbalance_penalty_cents: int
    offered_at: str
    offered_by_user_id: str
    decline_reason: str
    respond_by: str
    status: str


class CopyrightClearance(CommonFields, total=False):
    request_id: str
    issn: str
    calendar_year: int
    method: str
    sequence_in_year: int
    royalty_cents: int
    pages_covered: Optional[int]
    approved_by_user_id: Optional[str]
    status: str


class Shipment(CommonFields, total=False):
    request_id: str
    direction: str
    status: str
    carrier: Optional[str]
    tracking_code: Optional[str]
    insured_value_cents: int
    shipped_at: str
    received_at: Optional[str]
    confirmed_at: Optional[str]
    condition: Optional[str]


class LoanRecord(CommonFields, total=False):
    request_id: str
    received_at: str
    original_due_at: str
    due_at: str
    pickup_expires_at: str
    picked_up_at: Optional[str]
    return_prepared_at: Optional[str]
    max_renewals: int
    renewals_allowed: bool
    renewal_count: int
    replacement_cost_cents: int
    inbound_tracking_code: Optional[str]
    custody_status: str
    billing_status: str
    recall_status: str
    recall_due_at: Optional[str]
    overdue_fine_cents: int
    damage_fee_cents: int
    lost_replacement_cents: int
    lender_processing_fee_cents: int
    total_charge_cents: int
    paid_overdue_cents: int
    paid_damage_cents: int
    paid_lost_cents: int
    paid_processing_cents: int
    total_paid_cents: int
    outstanding_cents: int


class ElectronicDelivery(CommonFields, total=False):
    request_id: str
    partner_id: Optional[str]
    file_token: str
    pages_delivered: int
    delivered_at: str
    expires_at: str
    max_downloads: int
    download_count: int
    status: str


class PurchaseOnDemandOrder(CommonFields, total=False):
    request_id: str
    vendor: str
    list_price_cents: int
    escalated_by_user_id: str
    decided_by_user_id: Optional[str]
    decision_note: Optional[str]
    decided_at: Optional[str]
    received_at: Optional[str]
    status: str


class PartnerInvoice(CommonFields, total=False):
    partner_id: str
    period_month: str
    period_start: str
    period_end: str
    borrow_line_count: int
    lend_line_count: int
    payable_total_cents: int
    receivable_total_cents: int
    settlement_variant: str
    gross_amount_cents: int
    net_amount_cents: int
    direction: str
    status: str
    issued_at: Optional[str]
    settled_at: Optional[str]
    dispute_reason: Optional[str]


class LendingCharge(CommonFields, total=False):
    partner_id: str
    item_title: str
    service_type: str
    charge_cents: int
    incurred_at: str
    status: str


class PatronNotification(TypedDict, total=False):
    """Append-only notice: carries only `id` and `created_at` from the common set."""

    id: str
    created_at: str
    request_id: str
    kind: str
    channel: str
    subject: str
    sent_at: str


class OpsRunSummary(TypedDict, total=False):
    ran_at: str
    agreements_expired: int
    offers_expired: int
    recalls_breached: int
    pickups_abandoned: int
    deliveries_expired: int
    shipments_lost: int
    requests_escalated: int
    requests_unfilled: int
    patrons_blocked: int


class CopyrightUsageReport(TypedDict, total=False):
    issn: str
    calendar_year: int
    counted_fill_count: int
    free_fills_remaining: int
    royalty_paid_count: int
    pre_window_exempt_count: int


JsonDict = Dict[str, Any]
JsonList = List[Any]
