"""TypedDict shapes for every resource the presort bureau API returns.

These document the exact field set each resource carries so that a test can be
read against the contract without re-deriving it. Two resources are append-only
records of history and are deliberately leaner: ``AddressHygieneRun`` and
``VerificationFinding`` carry only ``id`` and ``created_at`` — no ``updated_at``
and no ``version``. Every other resource carries the full identity set.
"""

from typing import List, Optional, TypedDict


class FullIdentity(TypedDict):
    """The identity fields every mutable resource carries."""

    id: str
    created_at: str
    updated_at: str
    version: int


class AppendOnlyIdentity(TypedDict):
    """The identity fields the two append-only history records carry."""

    id: str
    created_at: str


class Client(FullIdentity):
    name: str
    client_code: str
    service_fee_rate_per_thousand_cents: int
    billing_terms: str
    commingle_opt_in: bool
    status: str
    suspension_reason: Optional[str]
    unbilled_postage_cents: int
    lifetime_pieces_mailed: int


class PermitAccount(FullIdentity):
    client_id: str
    permit_number: str
    payment_method: str
    annual_fee_paid_through_utc: str
    balance_cents: int
    reserved_cents: int
    status: str


class MailJob(FullIdentity):
    client_id: str
    permit_account_id: str
    commingle_batch_id: Optional[str]
    mail_class: str
    processing_category: str
    declared_piece_count: int
    declared_weight_oz_per_piece: float
    status: str
    accepted_piece_count: int
    hygiene_run_count: int
    rework_count: int
    address_quality_pct: Optional[float]
    move_update_compliant: Optional[bool]
    postage_due_cents: int
    mailed_at_utc: Optional[str]
    cancel_reason: Optional[str]


class AddressHygieneRun(AppendOnlyIdentity):
    mail_job_id: str
    submitted_piece_count: int
    cass_matched_count: int
    ncoa_move_updated_count: int
    undeliverable_removed_count: int
    move_update_age_days: int
    run_index: int
    net_piece_count: int
    address_quality_pct: float
    move_update_compliant: bool


class EntryFacility(FullIdentity):
    facility_code: str
    facility_type: str
    zip3: str
    dock_capacity_pallets_per_slot: int
    drop_ship_discount_bp: int
    served_zip3_list: List[str]
    status: str


class CommingleBatch(FullIdentity):
    entry_facility_id: str
    mail_class: str
    processing_category: str
    status: str
    member_job_count: int
    total_piece_count: int
    container_count: int
    achieved_tier: str
    rate_mills_per_piece: int
    batch_postage_cents: int


class BatchMember(FullIdentity):
    commingle_batch_id: str
    mail_job_id: str
    contributed_piece_count: int
    share_basis_pct: Optional[float]
    allocated_postage_cents: int
    allocated_adjustment_cents: int


class SortContainer(FullIdentity):
    commingle_batch_id: str
    container_type: str
    destination_zip3: str
    sort_level: str
    piece_count: int
    qualifies: bool
    placard_id: Optional[str]
    sequence_index: int
    zone: int
    committed_days: int
    status: str


class DropShipment(FullIdentity):
    commingle_batch_id: str
    entry_facility_id: str
    window_start_utc: str
    window_end_utc: str
    pallet_count: int
    status: str
    deposited_at_utc: Optional[str]
    cancel_reason: Optional[str]


class PostageStatement(FullIdentity):
    commingle_batch_id: str
    permit_account_id: str
    prepared_by_user_id: str
    submitted_by_user_id: Optional[str]
    verified_by_user_id: Optional[str]
    statement_piece_count: int
    rate_mills_per_piece: int
    declared_postage_cents: int
    adjustment_cents: int
    verified_postage_cents: int
    verification_error_count: int
    revision_index: int
    status: str
    void_reason: Optional[str]


class VerificationFinding(AppendOnlyIdentity):
    postage_statement_id: str
    finding_type: str
    affected_piece_count: int
    assessed_by_user_id: str
    severity: str
    surcharge_cents: int


class ServiceLevelRecord(FullIdentity):
    sort_container_id: str
    zone: int
    committed_days: int
    piece_count: int
    deposited_at_utc: str
    actual_delivery_days: Optional[int]
    scanned_at_utc: Optional[str]
    on_time: Optional[bool]


class ClientInvoice(FullIdentity):
    client_id: str
    period_start_utc: str
    period_end_utc: str
    postage_cents: int
    adjustment_cents: int
    service_fee_cents: int
    total_cents: int
    included_job_count: int
    billed_piece_count: int
    status: str
    paid_amount_cents: int


class ServiceLevelIndex(TypedDict):
    """The computed read hanging off a client."""

    zone_weighted_index: Optional[float]
    piece_weighted_index: Optional[float]
    record_count: int
    on_time_count: int


class StandalonePostageEstimate(TypedDict):
    """The computed read hanging off a mail job."""

    piece_count: int
    standalone_tier: str
    standalone_rate_mills_per_piece: int
    standalone_postage_cents: int


class ClockSetting(TypedDict):
    """The response of a logical-clock advance."""

    current_utc: str
    no_show_shipment_ids: List[str]


# Field sets used by the common-field assertions.
CLIENT_FIELDS = tuple(Client.__annotations__)
PERMIT_ACCOUNT_FIELDS = tuple(PermitAccount.__annotations__)
MAIL_JOB_FIELDS = tuple(MailJob.__annotations__)
ADDRESS_HYGIENE_RUN_FIELDS = tuple(AddressHygieneRun.__annotations__)
ENTRY_FACILITY_FIELDS = tuple(EntryFacility.__annotations__)
COMMINGLE_BATCH_FIELDS = tuple(CommingleBatch.__annotations__)
BATCH_MEMBER_FIELDS = tuple(BatchMember.__annotations__)
SORT_CONTAINER_FIELDS = tuple(SortContainer.__annotations__)
DROP_SHIPMENT_FIELDS = tuple(DropShipment.__annotations__)
POSTAGE_STATEMENT_FIELDS = tuple(PostageStatement.__annotations__)
VERIFICATION_FINDING_FIELDS = tuple(VerificationFinding.__annotations__)
SERVICE_LEVEL_RECORD_FIELDS = tuple(ServiceLevelRecord.__annotations__)
CLIENT_INVOICE_FIELDS = tuple(ClientInvoice.__annotations__)
