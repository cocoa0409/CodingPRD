"""Entity assertions, timestamp-family checkers, and PRD-pinned calculators.

STATUS-CODE CONVENTION (PRD §4): every resource-creating operation —
denominations, fed orders, lots, runs, programs, products, collectors,
orders, subscriptions, billing cycles (create an invoice), bullion issues,
authorized purchasers, allocations, error-coin cases — responds 201. All
other successful operations respond 200. The framework's validate_success
defaults to 200, so EVERY create assertion must either pass
expected_status=201 explicitly or call validate_created() below. Never rely
on the 200 default at a create call site.

TIMESTAMP FAMILIES (PRD §2.5): the system family (created_at, updated_at,
api_request_timestamp) renders with exactly three fractional digits
(e.g. 2026-09-01T00:00:00.000Z). The domain family (planned_start,
planned_end, release_datetime, sales_window_start, sales_window_end,
offer_expires_at, current_utc) renders as the clock reads / as supplied at
input, with NO millisecond normalization. Date-typed fields (due_date,
planned_delivery_date, next_billing_date) render as ISO calendar dates.
"""
import re
from decimal import ROUND_HALF_UP, Decimal

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_success,
)

from .constants import (
    ADMIN_FEE_PCT,
    BRACKET_BPS_100_TO_499OZ,
    BRACKET_BPS_500OZ_PLUS,
    BRACKET_BPS_UNDER_100OZ,
    BRACKET_BOUNDARY_HIGH_OZ,
    BRACKET_BOUNDARY_LOW_OZ,
    FREE_SHIPPING_MIN_UNITS,
    PREMIUM_BPS_DENOMINATOR,
    SHIPPING_TIER1_CENTS,
    SHIPPING_TIER1_MAX_UNITS,
    SHIPPING_TIER2_CENTS,
    SHIPPING_TIER2_MAX_UNITS,
    SUBSCRIBER_DISCOUNT_PCT,
    TIER_BPS,
)
from .types import (
    AllocationStatus,
    AuthorizedPurchaserStatus,
    AuthorizedPurchaserTier,
    BullionIssueStatus,
    BullionMetal,
    Commodity,
    ErrorCoinCaseStatus,
    Facility,
    FedOrderStatus,
    InvoiceStatus,
    LotStatus,
    OrderAllocationStatus,
    OrderDerivedStatus,
    OrderPaymentStatus,
    ProductStatus,
    ProductType,
    ProgramStatus,
    RunStatus,
    SubscriptionFrequency,
    SubscriptionStatus,
    Vault,
)

_SYSTEM_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# --- Response helpers -------------------------------------------------------------

def validate_created(response) -> dict:
    """Validate a 201 Created response envelope (all create endpoints)."""
    return validate_success(response, expected_status=201)


# --- Timestamp family assertions (PRD §2.5) ----------------------------------------

def assert_system_timestamp(value: str, label: str = "timestamp"):
    """System family: ISO 8601 UTC with EXACTLY three fractional digits."""
    assert isinstance(value, str) and _SYSTEM_TS_RE.match(value), (
        f"{label} must be ISO 8601 UTC with exactly 3 fractional digits "
        f"(e.g. 2026-09-01T00:00:00.000Z), got {value!r}"
    )


def assert_domain_timestamp(value: str, label: str = "timestamp"):
    """Domain family: a valid ISO 8601 UTC instant rendered as supplied /
    as the clock reads — no millisecond normalization required."""
    assert is_iso8601_timestamp(value), (
        f"{label} must be an ISO 8601 UTC timestamp, got {value!r}"
    )


def assert_iso_date(value: str, label: str = "date"):
    """Date-typed field: ISO 8601 calendar date (YYYY-MM-DD)."""
    assert isinstance(value, str) and _ISO_DATE_RE.match(value), (
        f"{label} must be an ISO 8601 calendar date (YYYY-MM-DD), got {value!r}"
    )


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a dashed UUID, got {data.get('id')!r}"
    assert_system_timestamp(data.get("created_at", ""), "created_at")
    assert_system_timestamp(data.get("updated_at", ""), "updated_at")
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer >= 1, got {data.get('version')!r}"
    )


def _values(enum_cls):
    return [m.value for m in enum_cls]


# --- Per-entity assertions ----------------------------------------------------------

def assert_denomination(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["face_value_cents"], int) and data["face_value_cents"] >= 1
    assert isinstance(data["blank_budget_cost_cents"], (int, float))
    assert isinstance(data["striking_cost_cents"], (int, float))
    assert isinstance(data["blanks_per_tonne"], int) and data["blanks_per_tonne"] > 0
    assert isinstance(data["blank_stock_pieces"], int) and data["blank_stock_pieces"] >= 0
    assert isinstance(data["budgeted_unit_seigniorage_cents"], (int, float))


def assert_federal_reserve_order(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["fiscal_year"], int)
    assert isinstance(data["denomination_code"], str) and data["denomination_code"]
    assert isinstance(data["quantity_ordered_pieces"], int) and data["quantity_ordered_pieces"] > 0
    assert_iso_date(data["due_date"], "due_date")
    assert data["status"] in _values(FedOrderStatus)
    assert isinstance(data["quantity_fulfilled_pieces"], int) and data["quantity_fulfilled_pieces"] >= 0
    assert isinstance(data["budgeted_seigniorage_cents"], (int, float))
    assert data.get("realized_seigniorage_cents") is None or isinstance(
        data["realized_seigniorage_cents"], (int, float)), (
        "realized_seigniorage_cents stays null until FULFILLED"
    )


def assert_metal_procurement_lot(data: dict):
    _assert_common_fields(data)
    assert data["commodity"] in _values(Commodity)
    assert isinstance(data["denomination_code"], str) and data["denomination_code"]
    assert isinstance(data["quantity_tonnes"], int) and data["quantity_tonnes"] > 0
    assert isinstance(data["budget_price_cents_per_tonne"], int)
    if data.get("locked_unit_price_cents_per_tonne") is not None:
        assert isinstance(data["locked_unit_price_cents_per_tonne"], int)
    assert isinstance(data["order_spot_cents_per_tonne"], int)
    assert data["vault"] in _values(Vault)
    assert_iso_date(data["planned_delivery_date"], "planned_delivery_date")
    assert data["status"] in _values(LotStatus)
    assert isinstance(data["blanks_produced"], int) and data["blanks_produced"] > 0
    assert data.get("realized_cost_cents") is None or isinstance(data["realized_cost_cents"], int), (
        "realized_cost_cents stays null until DELIVERED"
    )


def assert_production_run(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("fed_order_id", "")), "fed_order_id must be a UUID"
    assert data["facility"] in _values(Facility)
    assert isinstance(data["press_line"], str) and data["press_line"]
    assert_domain_timestamp(data["planned_start"], "planned_start")
    assert_domain_timestamp(data["planned_end"], "planned_end")
    assert isinstance(data["planned_quantity"], int) and data["planned_quantity"] > 0
    assert data["status"] in _values(RunStatus)
    assert data["status"] != RunStatus.INSPECTION.value, (
        "INSPECTION is entered and resolved within the inspect call; never persisted"
    )
    assert isinstance(data["reserved_blanks"], int) and data["reserved_blanks"] >= 0
    assert isinstance(data["produced_pieces"], int) and data["produced_pieces"] >= 0
    assert isinstance(data["scrapped_pieces"], int) and data["scrapped_pieces"] >= 0
    assert isinstance(data["rework_count"], int) and data["rework_count"] >= 0


def assert_commemorative_program(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["statute_reference"], str) and data["statute_reference"]
    assert isinstance(data["max_mintage_legal"], int) and data["max_mintage_legal"] > 0
    assert isinstance(data["surcharge_cents_per_unit"], int) and data["surcharge_cents_per_unit"] >= 0
    assert isinstance(data["beneficiary_name"], str) and data["beneficiary_name"]
    assert isinstance(data["beneficiary_cap_cents"], int) and data["beneficiary_cap_cents"] >= 0
    assert isinstance(data["direct_costs_cents"], int) and data["direct_costs_cents"] >= 0
    assert_domain_timestamp(data["sales_window_start"], "sales_window_start")
    assert_domain_timestamp(data["sales_window_end"], "sales_window_end")
    assert data["status"] in _values(ProgramStatus)
    assert isinstance(data["design_revision_count"], int) and data["design_revision_count"] >= 0
    assert isinstance(data["created_by_user_id"], str) and data["created_by_user_id"]
    assert isinstance(data["gross_receipts_cents"], int)
    assert isinstance(data["surcharge_accrued_cents"], int)
    assert isinstance(data["net_proceeds_cents"], int)
    assert isinstance(data["disbursed_cents"], int)


def assert_numismatic_product(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["product_code"], str) and data["product_code"]
    assert data.get("program_id") is None or is_valid_uuid(data["program_id"]), (
        "program_id is null for non-commemorative products"
    )
    assert isinstance(data["product_family"], str) and data["product_family"]
    assert data["product_type"] in _values(ProductType)
    assert isinstance(data["price_cents"], int) and data["price_cents"] > 0
    assert isinstance(data["mintage_limit"], int) and data["mintage_limit"] > 0
    assert isinstance(data["household_order_limit"], int) and data["household_order_limit"] > 0
    assert_domain_timestamp(data["release_datetime"], "release_datetime")
    assert isinstance(data["subscription_eligible"], bool)
    assert data["status"] in _values(ProductStatus)
    assert isinstance(data["allocated_units"], int) and data["allocated_units"] >= 0
    assert isinstance(data["remaining_units"], int)
    assert data["allocated_units"] + data["remaining_units"] == data["mintage_limit"], (
        "remaining_units is always the limit minus the allocated count"
    )


def assert_collector(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert isinstance(data["household_id"], str) and data["household_id"]


def assert_numismatic_order(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("collector_id", "")), "collector_id comes from X-User-ID"
    assert is_valid_uuid(data.get("product_id", "")), "product_id must be a UUID"
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["total_cents"], int) and data["total_cents"] > 0
    assert data["payment_status"] in _values(OrderPaymentStatus)
    assert data["allocation_status"] in _values(OrderAllocationStatus)
    assert data["status"] in _values(OrderDerivedStatus)


def assert_order_derived_status(data: dict):
    """PRD §3.6: CANCELLED iff RELEASED; COMPLETED iff PAID and ALLOCATED; else ACTIVE."""
    expected = (
        OrderDerivedStatus.CANCELLED.value if data["allocation_status"] == OrderAllocationStatus.RELEASED.value
        else OrderDerivedStatus.COMPLETED.value
        if (data["payment_status"] == OrderPaymentStatus.PAID.value
            and data["allocation_status"] == OrderAllocationStatus.ALLOCATED.value)
        else OrderDerivedStatus.ACTIVE.value
    )
    assert data["status"] == expected, (
        f"derived status must be {expected} for payment={data['payment_status']} "
        f"allocation={data['allocation_status']}, got {data['status']}"
    )


def assert_subscription(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("collector_id", "")), "collector_id comes from X-User-ID"
    assert is_valid_uuid(data.get("product_id", "")), "product_id must be a UUID"
    assert isinstance(data["units_per_cycle"], int) and data["units_per_cycle"] >= 1
    assert data["frequency"] in _values(SubscriptionFrequency)
    assert data["status"] in _values(SubscriptionStatus)
    assert_iso_date(data["next_billing_date"], "next_billing_date")
    assert isinstance(data["cycles_billed"], int) and data["cycles_billed"] >= 0


def assert_subscription_invoice(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("subscription_id", "")), "subscription_id must be a UUID"
    assert isinstance(data["period_index"], int) and data["period_index"] >= 1
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
    assert isinstance(data["attempts"], int) and data["attempts"] >= 0
    assert data["status"] in _values(InvoiceStatus)


def assert_bullion_issue(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["metal"] in _values(BullionMetal)
    assert isinstance(data["unit_weight_oz"], (int, float)) and data["unit_weight_oz"] > 0
    assert isinstance(data["total_pool_units"], int) and data["total_pool_units"] > 0
    assert isinstance(data["remaining_pool_units"], int) and data["remaining_pool_units"] >= 0
    assert data["remaining_pool_units"] <= data["total_pool_units"]
    assert isinstance(data["offer_window_hours"], int) and data["offer_window_hours"] > 0
    assert data["status"] in _values(BullionIssueStatus)


def assert_authorized_purchaser(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["tier"] in _values(AuthorizedPurchaserTier)
    assert data["status"] in _values(AuthorizedPurchaserStatus)


def assert_bullion_allocation(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("bullion_issue_id", "")), "bullion_issue_id must be a UUID"
    assert is_valid_uuid(data.get("authorized_purchaser_id", "")), "authorized_purchaser_id must be a UUID"
    assert isinstance(data["quantity_units"], int) and data["quantity_units"] >= 1
    assert isinstance(data["offered_by_user_id"], str) and data["offered_by_user_id"]
    assert_domain_timestamp(data["offer_expires_at"], "offer_expires_at")
    assert data.get("total_price_cents") is None or isinstance(data["total_price_cents"], int), (
        "total_price_cents stays null until CONFIRMED"
    )
    assert data["status"] in _values(AllocationStatus)


def assert_error_coin_case(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("production_run_id", "")), "production_run_id must be a UUID"
    assert isinstance(data["error_pieces"], int) and data["error_pieces"] > 0
    assert isinstance(data["reported_by_user_id"], str) and data["reported_by_user_id"]
    assert data["status"] in _values(ErrorCoinCaseStatus)
    assert data.get("destroyed_by_user_ids") is None or (
        isinstance(data["destroyed_by_user_ids"], list)
        and len(data["destroyed_by_user_ids"]) == 2
    ), "destroyed_by_user_ids stays null until DESTROYED, then holds both certifier ids"


def assert_report_envelope(data: dict, report_type: str):
    """Computed report shape (PRD §2.9): { report_type, rows: [...] }."""
    assert data.get("report_type") == report_type, (
        f"report_type must echo {report_type!r}, got {data.get('report_type')!r}"
    )
    assert isinstance(data.get("rows"), list), "report data must carry a rows array"


def assert_blank_conservation(row: dict):
    """Blank-stock reconciliation invariant (PRD §2.9): on_hand + reserved +
    produced + scrapped == delivered, for one seigniorage-report row."""
    total = (
        row["blanks_on_hand_pieces"] + row["blanks_reserved_pieces"]
        + row["blanks_produced_pieces"] + row["blanks_scrapped_pieces"]
    )
    assert total == row["blanks_delivered_pieces"], (
        f"blank conservation violated: {row['blanks_on_hand_pieces']} + "
        f"{row['blanks_reserved_pieces']} + {row['blanks_produced_pieces']} + "
        f"{row['blanks_scrapped_pieces']} != {row['blanks_delivered_pieces']}"
    )


# --- PRD-pinned calculators (expected values; exact Decimal arithmetic) --------------

def round_half_up_int(value) -> int:
    """Round half-up to whole cents/units (away from zero at the midpoint)."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_2dp(value) -> float:
    """Round half-up to 2 decimal places (unit margins; PRD §2.8)."""
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def budgeted_unit_seigniorage_cents(face_value_cents, blank_budget_cost_cents, striking_cost_cents) -> float:
    """PRD §3.1: face - budgeted blank - striking."""
    return float(Decimal(str(face_value_cents)) - Decimal(str(blank_budget_cost_cents))
                 - Decimal(str(striking_cost_cents)))


def realized_unit_blank_cost_cents(lots) -> float:
    """PRD §3.1: sum(realized_cost_cents) / sum(blanks_produced) over DELIVERED
    lots, rounded half-up to 2dp. `lots` is an iterable of (realized_cost_cents,
    blanks_produced) pairs."""
    total_cost = sum(pair[0] for pair in lots)
    total_blanks = sum(pair[1] for pair in lots)
    return float((Decimal(total_cost) / Decimal(total_blanks)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP))


def realized_seigniorage_cents(quantity_ordered_pieces, face_value_cents,
                               realized_unit_blank_cost, striking_cost_cents) -> float:
    """PRD §3.1 (pinned order): unit margin = round2(face - unit blank - striking);
    THEN multiply by quantity."""
    unit_margin = Decimal(str(face_value_cents)) - Decimal(str(realized_unit_blank_cost)) - Decimal(str(striking_cost_cents))
    unit_margin = unit_margin.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(unit_margin * Decimal(quantity_ordered_pieces))


def subscriber_unit_net_cents(price_cents: int) -> int:
    """PRD §3.7 (pinned rounding): 10% subscriber discount applied and rounded
    half-up PER UNIT before any multiplication."""
    return round_half_up_int(Decimal(price_cents) * Decimal(str(1 - SUBSCRIBER_DISCOUNT_PCT)))


def shipping_cents_for_units(units_per_cycle: int) -> int:
    """PRD §3.7 shipping tiers: 495c at <= 3 units, 895c at 4..10, 0 at >= 11."""
    if units_per_cycle <= SHIPPING_TIER1_MAX_UNITS:
        return SHIPPING_TIER1_CENTS
    if units_per_cycle <= SHIPPING_TIER2_MAX_UNITS:
        return SHIPPING_TIER2_CENTS
    assert units_per_cycle >= FREE_SHIPPING_MIN_UNITS
    return 0


def subscription_invoice_amount_cents(price_cents: int, units_per_cycle: int) -> int:
    """PRD §3.7: per-unit net (rounded first) x units + shipping tier."""
    return subscriber_unit_net_cents(price_cents) * units_per_cycle + shipping_cents_for_units(units_per_cycle)


def program_net_proceeds_cents(gross_receipts_cents: int, direct_costs_cents: int) -> int:
    """PRD §3.5 (pinned order): base = gross - direct; fee = round_half_up(base x 5%);
    net = base - fee."""
    base = gross_receipts_cents - direct_costs_cents
    admin_fee = round_half_up_int(Decimal(base) * Decimal(str(ADMIN_FEE_PCT)))
    return base - admin_fee


def surcharge_disbursement_cents(surcharge_accrued_cents: int, beneficiary_cap_cents: int) -> int:
    """PRD §3.5: min(cap, accrued); equality pays the cap exactly."""
    return min(beneficiary_cap_cents, surcharge_accrued_cents)


def bullion_bracket_bps(total_oz) -> int:
    """PRD §3.8 size bracket: < 100 oz -> 200; 100..<500 -> 100; >= 500 -> 0."""
    oz = Decimal(str(total_oz))
    if oz < BRACKET_BOUNDARY_LOW_OZ:
        return BRACKET_BPS_UNDER_100OZ
    if oz < BRACKET_BOUNDARY_HIGH_OZ:
        return BRACKET_BPS_100_TO_499OZ
    return BRACKET_BPS_500OZ_PLUS


def bullion_premium_bps(tier: str, total_oz) -> int:
    """PRD §3.8: tier bps + size-bracket bps."""
    return TIER_BPS[tier] + bullion_bracket_bps(total_oz)


def bullion_total_price_cents(quantity_units: int, unit_weight_oz, spot_cents_per_oz: int, tier: str) -> int:
    """PRD §3.8: round_half_up(total_oz x spot x (1 + premium_bps/10000)) —
    a single round at the very end."""
    total_oz = Decimal(quantity_units) * Decimal(str(unit_weight_oz))
    premium = Decimal(bullion_premium_bps(tier, total_oz)) / Decimal(PREMIUM_BPS_DENOMINATOR)
    raw = total_oz * Decimal(spot_cents_per_oz) * (Decimal(1) + premium)
    return int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
