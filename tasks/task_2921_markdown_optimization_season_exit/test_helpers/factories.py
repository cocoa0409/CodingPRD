"""Request-payload factories.

Each factory returns only the fields a client may send. Server-computed and
server-derived fields are never included. Every factory accepts ``**overrides``
so a test can bend exactly one field.
"""

from typing import Any, Dict, Optional

from .constants import DEFAULT_CLOCK_UTC

# --------------------------------------------------------------------------
# Canonical calendar of the base scenario, all date-only YYYY-MM-DD values.
# --------------------------------------------------------------------------
SEASON_START_DATE = "2026-08-15"
SEASON_END_DATE = "2027-01-31"
SEASON_EXIT_TARGET_DATE = "2027-01-15"
ITEM_FIRST_RECEIPT_DATE = "2026-08-20"
WORKING_CLOCK_UTC = "2026-10-10T00:00:00Z"


def _merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Apply overrides, and drop any key whose override value is ``None``.

    Dropping on ``None`` lets a test omit an optional field entirely, which is
    different from sending it as JSON null.
    """
    payload = dict(base)
    for key, value in overrides.items():
        if value is None and key in payload:
            payload.pop(key)
        else:
            payload[key] = value
    return payload


# ==========================================================================
# Logical clock
# ==========================================================================
def clock_payload(current_utc: str = DEFAULT_CLOCK_UTC, **overrides) -> Dict[str, Any]:
    return _merge({"current_utc": current_utc}, overrides)


# ==========================================================================
# Season
# ==========================================================================
def season_payload(**overrides) -> Dict[str, Any]:
    return _merge(
        {
            "code": "FW26-APPAREL",
            "category": "APPAREL",
            "season_start_date": SEASON_START_DATE,
            "season_end_date": SEASON_END_DATE,
            "exit_target_date": SEASON_EXIT_TARGET_DATE,
            "exit_units_target": 1000,
            "sell_through_target_pct": 82.00,
            "clearance_space_units": 900,
        },
        overrides,
    )


def season_transition_payload(to_status: str, **overrides) -> Dict[str, Any]:
    return _merge({"to_status": to_status}, overrides)


# ==========================================================================
# Price zone
# ==========================================================================
def chain_zone_payload(**overrides) -> Dict[str, Any]:
    return _merge(
        {"zone_code": "CHAIN-US", "zone_type": "CHAIN", "signage_lead_days": 10},
        overrides,
    )


def region_zone_payload(parent_zone_id: str, **overrides) -> Dict[str, Any]:
    return _merge(
        {
            "zone_code": "REGION-WEST",
            "zone_type": "REGION",
            "parent_zone_id": parent_zone_id,
            "region_code": "WEST",
            "signage_lead_days": 7,
        },
        overrides,
    )


def store_zone_payload(parent_zone_id: str, **overrides) -> Dict[str, Any]:
    return _merge(
        {
            "zone_code": "STORE-0101",
            "zone_type": "STORE",
            "parent_zone_id": parent_zone_id,
            "region_code": "WEST",
            "signage_lead_days": 3,
        },
        overrides,
    )


# ==========================================================================
# Store
# ==========================================================================
def store_payload(price_zone_id: str, **overrides) -> Dict[str, Any]:
    return _merge(
        {
            "store_number": "0101",
            "price_zone_id": price_zone_id,
            "region_code": "WEST",
            "clearance_bay_units": 300,
        },
        overrides,
    )


def store_patch_payload(**overrides) -> Dict[str, Any]:
    return _merge({}, overrides)


# ==========================================================================
# Item
# ==========================================================================
def item_payload(season_id: str, **overrides) -> Dict[str, Any]:
    return _merge(
        {
            "sku": "A-1001",
            "season_id": season_id,
            "category": "APPAREL",
            "cluster_code": "CL-W1",
            "vendor_code": "VN-100",
            "first_receipt_date": ITEM_FIRST_RECEIPT_DATE,
            "original_retail_cents": 4999,
            "unit_cost_cents": 2000,
            "units_received_total": 600,
        },
        overrides,
    )


# ==========================================================================
# Sales week
# ==========================================================================
def sales_week_payload(
    week_ending_date: str, units_sold: int, ticket_price_cents: int, **overrides
) -> Dict[str, Any]:
    return _merge(
        {
            "week_ending_date": week_ending_date,
            "units_sold": units_sold,
            "ticket_price_cents": ticket_price_cents,
        },
        overrides,
    )


# The four-week history that gives item A-1001 a two-point log-log slope of
# -1.9901 with HIGH confidence, 257 units sold and 343 units on hand.
BASE_SALES_HISTORY = [
    ("2026-09-05", 60, 4999),
    ("2026-09-12", 55, 4999),
    ("2026-09-19", 68, 4499),
    ("2026-09-26", 74, 4499),
]


# ==========================================================================
# Elasticity estimate
# ==========================================================================
def elasticity_estimate_payload(item_id: str, **overrides) -> Dict[str, Any]:
    return _merge({"item_id": item_id, "method": "AUTO"}, overrides)


def certify_payload(**overrides) -> Dict[str, Any]:
    return _merge({}, overrides)


# ==========================================================================
# Markdown plan
# ==========================================================================
def markdown_plan_payload(
    season_id: str,
    item_id: str,
    elasticity_estimate_id: str,
    expected_item_version: int,
    **overrides,
) -> Dict[str, Any]:
    return _merge(
        {
            "season_id": season_id,
            "item_id": item_id,
            "elasticity_estimate_id": elasticity_estimate_id,
            "plan_type": "PERMANENT",
            "exit_date_target": SEASON_EXIT_TARGET_DATE,
            "expected_item_version": expected_item_version,
        },
        overrides,
    )


def markdown_step_payload(
    step_index: int, effective_date: str, depth_pct: float, **overrides
) -> Dict[str, Any]:
    return _merge(
        {
            "step_index": step_index,
            "effective_date": effective_date,
            "depth_pct": depth_pct,
        },
        overrides,
    )


def submit_payload(**overrides) -> Dict[str, Any]:
    return _merge({}, overrides)


def request_revision_payload(
    revision_reason: str = "Ladder steps too shallow for the exit target.", **overrides
) -> Dict[str, Any]:
    return _merge({"revision_reason": revision_reason}, overrides)


def reopen_payload(clear_ladder: Optional[bool] = None, **overrides) -> Dict[str, Any]:
    base: Dict[str, Any] = {}
    if clear_ladder is not None:
        base["clear_ladder"] = clear_ladder
    return _merge(base, overrides)


def approve_payload(**overrides) -> Dict[str, Any]:
    return _merge({}, overrides)


# ==========================================================================
# Zone execution
# ==========================================================================
def zone_execution_payload(
    markdown_plan_id: str,
    markdown_step_id: str,
    price_zone_id: str,
    execution_scope: str,
    effective_date: str,
    units_in_scope: int,
    store_id: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "markdown_plan_id": markdown_plan_id,
        "markdown_step_id": markdown_step_id,
        "price_zone_id": price_zone_id,
        "execution_scope": execution_scope,
        "effective_date": effective_date,
        "units_in_scope": units_in_scope,
    }
    if store_id is not None:
        base["store_id"] = store_id
    return _merge(base, overrides)


def post_signage_payload(**overrides) -> Dict[str, Any]:
    return _merge({}, overrides)


def verify_signage_payload(**overrides) -> Dict[str, Any]:
    return _merge({}, overrides)


def apply_payload(**overrides) -> Dict[str, Any]:
    return _merge({}, overrides)


def roll_back_payload(
    rollback_reason: str = "Ticket moved on the wrong assortment.", **overrides
) -> Dict[str, Any]:
    return _merge({"rollback_reason": rollback_reason}, overrides)


# ==========================================================================
# Clearance allocation and reservations
# ==========================================================================
def clearance_allocation_payload(
    markdown_plan_id: str, total_units: int, expected_season_version: int, **overrides
) -> Dict[str, Any]:
    return _merge(
        {
            "markdown_plan_id": markdown_plan_id,
            "total_units": total_units,
            "expected_season_version": expected_season_version,
        },
        overrides,
    )


def release_payload(release_reason: Optional[str] = None, **overrides) -> Dict[str, Any]:
    base: Dict[str, Any] = {}
    if release_reason is not None:
        base["release_reason"] = release_reason
    return _merge(base, overrides)


# ==========================================================================
# Vendor allowance agreement
# ==========================================================================
def allowance_agreement_payload(season_id: str, **overrides) -> Dict[str, Any]:
    return _merge(
        {
            "season_id": season_id,
            "vendor_code": "VN-100",
            "item_category_scope": "APPAREL",
            "current_share_pct": 25.00,
            "current_cap_cents": 100000,
        },
        overrides,
    )


def counter_payload(share_pct: float, cap_cents: int, **overrides) -> Dict[str, Any]:
    return _merge({"share_pct": share_pct, "cap_cents": cap_cents}, overrides)


def accept_payload(**overrides) -> Dict[str, Any]:
    return _merge({}, overrides)


# ==========================================================================
# Vendor claim
# ==========================================================================
def vendor_claim_payload(
    allowance_agreement_id: str, markdown_plan_id: str, claimed_cents: int, **overrides
) -> Dict[str, Any]:
    return _merge(
        {
            "allowance_agreement_id": allowance_agreement_id,
            "markdown_plan_id": markdown_plan_id,
            "claimed_cents": claimed_cents,
        },
        overrides,
    )


def recognize_payload(**overrides) -> Dict[str, Any]:
    return _merge({}, overrides)


def reverse_payload(
    reversal_reason: str = "Vendor disputed the funded share.", **overrides
) -> Dict[str, Any]:
    return _merge({"reversal_reason": reversal_reason}, overrides)


# ==========================================================================
# Disposition order
# ==========================================================================
def salvage_order_payload(
    season_id: str, item_id: str, units: int, unit_recovery_cents: int, **overrides
) -> Dict[str, Any]:
    return _merge(
        {
            "season_id": season_id,
            "item_id": item_id,
            "channel": "SALVAGE",
            "units": units,
            "unit_recovery_cents": unit_recovery_cents,
        },
        overrides,
    )


def jobber_order_payload(
    season_id: str, item_id: str, units: int, unit_recovery_cents: int, **overrides
) -> Dict[str, Any]:
    return _merge(
        {
            "season_id": season_id,
            "item_id": item_id,
            "channel": "JOBBER",
            "units": units,
            "unit_recovery_cents": unit_recovery_cents,
        },
        overrides,
    )


def donation_order_payload(
    season_id: str, item_id: str, units: int, fmv_cents: int, **overrides
) -> Dict[str, Any]:
    return _merge(
        {
            "season_id": season_id,
            "item_id": item_id,
            "channel": "DONATION",
            "units": units,
            "fmv_cents": fmv_cents,
        },
        overrides,
    )


def approve_disposition_payload(**overrides) -> Dict[str, Any]:
    return _merge({}, overrides)


def settle_payload(settled_units: int, **overrides) -> Dict[str, Any]:
    return _merge({"settled_units": settled_units}, overrides)


def cancel_payload(cancel_reason: Optional[str] = None, **overrides) -> Dict[str, Any]:
    base: Dict[str, Any] = {}
    if cancel_reason is not None:
        base["cancel_reason"] = cancel_reason
    return _merge(base, overrides)


# ==========================================================================
# Season exit review
# ==========================================================================
def exit_review_payload(review_type: str, **overrides) -> Dict[str, Any]:
    return _merge({"review_type": review_type}, overrides)
