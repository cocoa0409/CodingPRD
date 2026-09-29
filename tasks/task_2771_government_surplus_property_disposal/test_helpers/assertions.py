"""Entity assertions and the PRD's conserved-quantity invariant checkers."""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

_DISPOSITION_STATUSES = [
    "INTAKE", "ASSESSED", "SCREENING", "AWARDED_TRANSFER", "AUCTION_ELIGIBLE",
    "LISTED", "SOLD", "RELEASED", "RETAINED", "DESTROYED",
]
_CLEARANCE_STATUSES = ["NOT_REQUIRED", "REQUIRED_PENDING", "CLEARED", "BLOCKED"]


# ─── Shared identity / audit assertions (PRD §2.5) ────────────────────────

def assert_identity_fields(data: dict) -> None:
    """Every row carries a server-minted UUID id and an ISO 8601 created_at."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )


def assert_versioned_fields(data: dict) -> None:
    """Rows outside the append-only pair also carry updated_at and version."""
    assert_identity_fields(data)
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer starting at 1, got {data.get('version')!r}"
    )


def assert_append_only_fields(data: dict) -> None:
    """The PRD gives ConditionAssessment and ClearanceCertificate only id and
    created_at, so neither may be asserted to carry updated_at or version."""
    assert_identity_fields(data)


# ─── Per-entity assertions ────────────────────────────────────────────────

def assert_agency(data: dict) -> None:
    assert_versioned_fields(data)
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 160
    assert isinstance(data["agency_code"], str) and 1 <= len(data["agency_code"]) <= 24
    assert data["agency_type"] in (
        "STATE_AGENCY", "LOCAL_GOVERNMENT", "ELIGIBLE_NONPROFIT"
    )
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert data["federal_donee_status"] in ("NONE", "CERTIFIED", "SUSPENDED")
    assert isinstance(data["proceeds_account_balance_cents"], int)
    assert data["proceeds_account_balance_cents"] >= 0, (
        "proceeds_account_balance_cents may never go below zero"
    )
    assert isinstance(data["posted_distribution_count"], int)
    assert data["posted_distribution_count"] >= 0


def assert_turn_in(data: dict) -> None:
    assert_versioned_fields(data)
    assert isinstance(data["turning_in_agency_id"], str)
    assert isinstance(data["custody_location"], str)
    assert 1 <= len(data["custody_location"]) <= 120
    assert data["status"] in ("DRAFT", "SUBMITTED", "ACCEPTED", "REJECTED", "CLOSED")
    assert isinstance(data["asset_count"], int) and data["asset_count"] >= 0
    assert isinstance(data["appraised_total_cents"], int)
    assert data["appraised_total_cents"] >= 0


def assert_surplus_asset(data: dict) -> None:
    assert_versioned_fields(data)
    assert isinstance(data["turn_in_id"], str)
    assert data["category"] in (
        "VEHICLE", "IT_EQUIPMENT", "FURNITURE", "HEAVY_EQUIPMENT",
        "RESTRICTED_MILITARY",
    )
    assert isinstance(data["description"], str) and 1 <= len(data["description"]) <= 200
    assert isinstance(data["acquisition_cost_cents"], int)
    assert data["acquisition_cost_cents"] > 0
    assert data["disposition_status"] in _DISPOSITION_STATUSES
    assert data["clearance_status"] in _CLEARANCE_STATUSES
    if data.get("fair_market_value_cents") is not None:
        assert isinstance(data["fair_market_value_cents"], int)
        assert data["fair_market_value_cents"] >= 0, (
            "fair_market_value_cents floors at zero and never goes negative"
        )
    if data.get("demil_code") is not None:
        assert data["demil_code"] in ("A", "B", "C", "D", "Q")
    if data.get("condition_code") is not None:
        assert data["condition_code"] in ("C1", "C2", "C3", "C4", "C5", "C6", "C7")


def assert_condition_assessment(data: dict) -> None:
    assert_append_only_fields(data)
    assert isinstance(data["asset_id"], str)
    assert isinstance(data["assessor_user_id"], str) and data["assessor_user_id"]
    assert data["condition_code"] in ("C1", "C2", "C3", "C4", "C5", "C6", "C7")
    assert isinstance(data["functional"], bool)
    assert isinstance(data["repair_cost_estimate_cents"], int)
    assert data["repair_cost_estimate_cents"] >= 0
    assert isinstance(data["assessed_on"], str)
    assert isinstance(data["superseded"], bool)


def assert_clearance_certificate(data: dict) -> None:
    assert_append_only_fields(data)
    assert isinstance(data["asset_id"], str)
    assert data["cert_type"] in ("DATA_SANITIZATION", "DEMILITARIZATION")
    assert data["method"] in (
        "NIST_CLEAR", "NIST_PURGE", "DEGAUSS", "MUTILATE", "DESTROY"
    )
    assert isinstance(data["technician_user_id"], str) and data["technician_user_id"]
    assert isinstance(data["serials_verified"], bool)
    assert isinstance(data["certified_on"], str)


def assert_screening_cycle(data: dict) -> None:
    assert_versioned_fields(data)
    assert isinstance(data["asset_id"], str)
    assert isinstance(data["tier_window_days"], int)
    assert 1 <= data["tier_window_days"] <= 60
    assert data["current_tier"] in (
        "STATE_AGENCY", "LOCAL_GOVERNMENT", "ELIGIBLE_NONPROFIT", "PUBLIC_SALE"
    )
    assert data["status"] in ("OPEN", "AWARDED", "EXHAUSTED", "CANCELLED")
    assert isinstance(data["tier_advance_count"], int)
    assert data["tier_advance_count"] >= 0
    assert isinstance(data["open_request_count"], int)
    assert data["open_request_count"] >= 0
    assert is_iso8601_timestamp(data["tier_opened_at"])
    assert is_iso8601_timestamp(data["tier_deadline_at"])


def assert_screening_request(data: dict) -> None:
    assert_versioned_fields(data)
    assert isinstance(data["screening_cycle_id"], str)
    assert isinstance(data["requesting_agency_id"], str)
    assert isinstance(data["intended_use"], str) and 1 <= len(data["intended_use"]) <= 200
    assert isinstance(data["justification"], str)
    assert 1 <= len(data["justification"]) <= 500
    assert data["tier_at_submission"] in (
        "STATE_AGENCY", "LOCAL_GOVERNMENT", "ELIGIBLE_NONPROFIT"
    )
    assert data["status"] in ("SUBMITTED", "INFO_REQUESTED", "APPROVED", "DENIED")
    assert isinstance(data["resubmission_count"], int)
    assert data["resubmission_count"] >= 0
    if data.get("denial_reason") is not None:
        assert data["denial_reason"] in (
            "LOST_AWARD", "TRANSFER_VOIDED", "CYCLE_CANCELLED"
        )


def assert_transfer_order(data: dict) -> None:
    assert_versioned_fields(data)
    assert isinstance(data["asset_id"], str)
    assert isinstance(data["recipient_agency_id"], str)
    assert isinstance(data["screening_request_id"], str)
    for field in ("base_transfer_cents", "handling_fee_cents", "transfer_price_cents"):
        assert isinstance(data[field], int), f"{field} must be whole cents"
        assert data[field] >= 0
    assert data["status"] in ("ISSUED", "ACKNOWLEDGED", "COMPLETED", "VOIDED")
    assert isinstance(data["issued_by_user_id"], str) and data["issued_by_user_id"]


def assert_sale_venue(data: dict) -> None:
    assert_versioned_fields(data)
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 120
    assert isinstance(data["venue_code"], str) and 1 <= len(data["venue_code"]) <= 24
    assert isinstance(data["concurrent_lot_capacity"], int)
    assert data["concurrent_lot_capacity"] >= 1
    assert 0 <= float(data["buyer_premium_pct"]) <= 0.30
    assert 0 <= float(data["sales_tax_pct"]) <= 0.15
    assert data["status"] in ("ACTIVE", "CLOSED")
    assert isinstance(data["active_lot_count"], int) and data["active_lot_count"] >= 0


def assert_auction_lot(data: dict) -> None:
    assert_versioned_fields(data)
    assert isinstance(data["asset_id"], str)
    assert isinstance(data["venue_id"], str)
    assert isinstance(data["lot_number"], str) and data["lot_number"]
    assert isinstance(data["reserve_price_cents"], int)
    assert data["reserve_price_cents"] >= 2500, (
        "the reserve never falls below the 2500-cent floor"
    )
    assert data["reserve_source"] in ("COMPUTED", "OFFICER_OVERRIDE")
    assert isinstance(data["required_deposit_cents"], int)
    assert data["required_deposit_cents"] >= 0
    assert data["status"] in (
        "DRAFT", "OPEN", "CLOSED_MET", "CLOSED_NO_SALE", "SETTLED", "CANCELLED"
    )
    assert isinstance(data["high_bid_cents"], int) and data["high_bid_cents"] >= 0
    assert isinstance(data["bid_count"], int) and data["bid_count"] >= 0


def assert_bidder(data: dict) -> None:
    assert_versioned_fields(data)
    assert isinstance(data["legal_name"], str) and 1 <= len(data["legal_name"]) <= 160
    assert isinstance(data["email"], str) and data["email"]
    assert data["bidder_type"] in ("INDIVIDUAL", "BUSINESS")
    assert data["status"] in ("PENDING", "REGISTERED", "SUSPENDED", "DEBARRED")
    for field in (
        "deposit_paid_cents", "deposit_held_cents", "deposit_applied_cents",
        "deposit_forfeited_cents", "winning_lot_count",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer"
        assert data[field] >= 0, f"{field} may never go below zero"
    assert_deposit_custody_invariant(data)


def assert_bid(data: dict) -> None:
    assert_versioned_fields(data)
    assert isinstance(data["auction_lot_id"], str)
    assert isinstance(data["bidder_id"], str)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["status"] in ("ACTIVE", "OUTBID", "WINNING", "RETRACTED")
    assert is_iso8601_timestamp(data["placed_at"])


def assert_sale_invoice(data: dict) -> None:
    assert_versioned_fields(data)
    assert isinstance(data["auction_lot_id"], str)
    assert isinstance(data["bidder_id"], str)
    for field in (
        "hammer_price_cents", "buyer_premium_cents", "sales_tax_cents",
        "total_due_cents", "amount_paid_cents", "deposit_applied_cents",
        "balance_due_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be whole cents"
        assert data[field] >= 0, f"{field} may never go below zero"
    assert data["status"] in (
        "ISSUED", "PARTIALLY_PAID", "PAID", "DEFAULTED", "VOIDED"
    )
    assert is_iso8601_timestamp(data["due_at"])
    assert_invoice_money_lines(data)


def assert_proceeds_distribution(data: dict) -> None:
    assert_versioned_fields(data)
    assert isinstance(data["auction_lot_id"], str)
    assert isinstance(data["beneficiary_agency_id"], str)
    assert data["basis"] in ("ACCRUAL", "CASH")
    for field in (
        "distributable_base_cents", "service_fee_cents", "cost_recovery_cents",
        "net_to_agency_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be whole cents"
        assert data[field] >= 0, f"{field} may never go below zero"
    assert data["status"] in ("CALCULATED", "POSTED", "SUPERSEDED", "REVERSED")


# ─── Domain invariant checkers ────────────────────────────────────────────

def assert_deposit_custody_invariant(bidder: dict) -> None:
    """Deposit custody: paid equals held plus applied plus forfeited."""
    total = (
        bidder["deposit_held_cents"]
        + bidder["deposit_applied_cents"]
        + bidder["deposit_forfeited_cents"]
    )
    assert bidder["deposit_paid_cents"] == total, (
        "deposit_paid_cents must equal deposit_held_cents + deposit_applied_cents + "
        f"deposit_forfeited_cents; got {bidder['deposit_paid_cents']} vs {total}"
    )


def assert_invoice_money_lines(invoice: dict) -> None:
    """total_due_cents is the exact sum of the three money lines, and
    balance_due_cents is total_due_cents minus amount_paid_cents."""
    expected_total = (
        invoice["hammer_price_cents"]
        + invoice["buyer_premium_cents"]
        + invoice["sales_tax_cents"]
    )
    assert invoice["total_due_cents"] == expected_total, (
        "total_due_cents must be hammer_price_cents + buyer_premium_cents + "
        f"sales_tax_cents; got {invoice['total_due_cents']} vs {expected_total}"
    )
    expected_balance = invoice["total_due_cents"] - invoice["amount_paid_cents"]
    assert invoice["balance_due_cents"] == expected_balance, (
        "balance_due_cents must be total_due_cents - amount_paid_cents; got "
        f"{invoice['balance_due_cents']} vs {expected_balance}"
    )


def assert_proceeds_net(distribution: dict) -> None:
    """net_to_agency_cents floors at zero after the fee and recovery deductions."""
    raw = (
        distribution["distributable_base_cents"]
        - distribution["service_fee_cents"]
        - distribution["cost_recovery_cents"]
    )
    assert distribution["net_to_agency_cents"] == max(0, raw), (
        "net_to_agency_cents must be max(0, base - service fee - cost recovery); got "
        f"{distribution['net_to_agency_cents']} vs {max(0, raw)}"
    )


def assert_proceeds_ledger_invariant(agencies: list, distributions: list) -> None:
    """The sum of every organization's ledger balance equals the sum of
    net_to_agency_cents over POSTED distributions."""
    balances = sum(a["proceeds_account_balance_cents"] for a in agencies)
    posted = sum(
        d["net_to_agency_cents"] for d in distributions if d["status"] == "POSTED"
    )
    assert balances == posted, (
        "SUM(proceeds_account_balance_cents) must equal SUM(net_to_agency_cents) over "
        f"POSTED distributions; got {balances} vs {posted}"
    )


def assert_lot_rollups(lot: dict, bids: list) -> None:
    """high_bid_cents is the maximum amount over ACTIVE and WINNING bids (zero
    when there are none) and bid_count counts ACTIVE, WINNING and OUTBID bids."""
    live = [b["amount_cents"] for b in bids if b["status"] in ("ACTIVE", "WINNING")]
    expected_high = max(live) if live else 0
    assert lot["high_bid_cents"] == expected_high, (
        f"high_bid_cents must be {expected_high}, got {lot['high_bid_cents']}"
    )
    expected_count = len(
        [b for b in bids if b["status"] in ("ACTIVE", "WINNING", "OUTBID")]
    )
    assert lot["bid_count"] == expected_count, (
        f"bid_count must be {expected_count}, got {lot['bid_count']}"
    )
