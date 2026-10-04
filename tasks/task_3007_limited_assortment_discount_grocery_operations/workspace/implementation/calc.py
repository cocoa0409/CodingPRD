"""Calculation rules (scaffold Table 3) and domain enumerations."""
from datetime import timedelta
from decimal import Decimal

from core import D, iso_week_monday, rhu, rhu_int  # noqa: F401

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------
CATEGORY_STATUSES = ("OPEN", "LOCKED")
SUPPLIER_STATUSES = ("ACTIVE", "SUSPENDED")
PRODUCT_KINDS = ("CORE", "FINDS")
PRODUCT_STATUSES = ("PROPOSED", "ACTIVE", "DISCONTINUED")
TENDER_STATUSES = ("DRAFT", "OPEN", "CLOSED", "EVALUATING", "AWARDED", "CANCELLED")
BID_STATUSES = (
    "SUBMITTED",
    "ELIGIBLE",
    "DISQUALIFIED",
    "AWARDED_PRIMARY",
    "AWARDED_SECONDARY",
    "NOT_SELECTED",
)
PANEL_STATUSES = ("SCHEDULED", "SCORED", "LOCKED")
STORE_TIERS = ("STANDARD", "HIGH_VOLUME")
STORE_STATUSES = ("ACTIVE", "CLOSED")
EMPLOYEE_ROLES = ("CASHIER", "STOCKER", "SHIFT_LEAD")
EMPLOYEE_STATUSES = ("ACTIVE", "INACTIVE")
FINDS_BUY_STATUSES = ("PLANNED", "ALLOCATED", "ON_SALE", "SOLD_OUT", "CLOSED")
ALLOCATION_STATUSES = ("RESERVED", "ON_SALE", "SOLD_OUT", "CLEARANCE", "CLOSED")
COIN_EVENT_TYPES = ("INSERT", "RETURN", "CORRAL_COLLECT", "AUDIT_ADJUST")
SHIFT_STATUSES = ("OPEN", "CLOSED")
SHIFT_COMPLIANCE = ("COMPLIANT", "BELOW_STANDARD")
LABOR_WINDOW_STATUSES = ("PLANNED", "CONFIRMED", "CANCELLED")
CLAIM_REASONS = ("QUALITY_DEFECT", "DAMAGED", "OTHER")
CLAIM_STATUSES = (
    "FILED",
    "UNDER_REVIEW",
    "DISPUTED",
    "APPROVED",
    "PAID",
    "REJECTED",
    "RESCINDED",
)

# ---------------------------------------------------------------------------
# Constants (scaffold calculations[].constants)
# ---------------------------------------------------------------------------
W_PANEL = Decimal("0.5")
W_PRICE = Decimal("0.3")
W_QUALITY = Decimal("0.2")
PANEL_MIN_SCORE = 60

TIER_SHARE = {
    "HIGH_VOLUME": Decimal("0.6"),
    "STANDARD": Decimal("0.4"),
}
TIER_PRIORITY = ["HIGH_VOLUME", "STANDARD"]

SCAN_TARGET = Decimal("1000")
VOID_PENALTY = 2

GUARANTEE_MULTIPLIER = Decimal("2.0")
STANDARD_MULTIPLIER = Decimal("1.0")

COIN_VALUE_CENTS = 25

ROLE_RATE_CENTS_PER_HOUR = {
    "CASHIER": 1700,
    "STOCKER": 1800,
    "SHIFT_LEAD": 2400,
}
LABOR_WEEKLY_WINDOW_LIMIT = 6

CLAIM_WINDOW_DAYS = 45
MIN_SOURCES_FIXED = 2


# ---------------------------------------------------------------------------
# tender_award_score
# ---------------------------------------------------------------------------
def award_score(tender, bid, panel, supplier):
    """Return (status, score): DISQUALIFIED/-1.0 marker or ELIGIBLE/blended score."""
    if panel["score"] < PANEL_MIN_SCORE or bid["unit_cost_cents"] > tender["bid_ceiling_cents"]:
        return "DISQUALIFIED", Decimal("-1.0")
    ceiling = D(tender["bid_ceiling_cents"])
    price_score = Decimal("100") * (ceiling - D(bid["unit_cost_cents"])) / ceiling
    blended = (
        W_PANEL * D(panel["score"])
        + W_PRICE * price_score
        + W_QUALITY * D(supplier["quality_score"])
    )
    return "ELIGIBLE", rhu(blended, 2)


def bid_rank_key(bid):
    """Deterministic award ranking: highest score, then lower cost, then earliest."""
    score = bid["award_score"] if bid["award_score"] is not None else Decimal("-1.0")
    return (-D(score), D(bid["unit_cost_cents"]), bid["created_at"], bid["_seq"])


# ---------------------------------------------------------------------------
# finds_allocation_waterfall
# ---------------------------------------------------------------------------
def waterfall(total_quantity, stores):
    """Return a list of (store, allocated_quantity) pairs.

    Shares renormalize over present tiers; per-store quotas floor; the leftover
    is distributed one unit at a time by (tier priority, store created_at ASC).
    """
    present = [t for t in TIER_PRIORITY if any(s["tier"] == t for s in stores)]
    shares = {}
    if len(present) == 1:
        shares[present[0]] = Decimal("1.0")
    else:
        for t in present:
            shares[t] = TIER_SHARE[t]

    quota = {}  # store id -> units
    for tier in present:
        members = [s for s in stores if s["tier"] == tier]
        pool = int(D(total_quantity) * shares[tier])  # floor of a nonneg product
        per_store = pool // len(members)
        for s in members:
            quota[s["id"]] = per_store

    allocated = sum(quota.values())
    leftover = int(total_quantity) - allocated
    ordered = sorted(stores, key=lambda s: (TIER_PRIORITY.index(s["tier"]),
                                            s["created_at"], s["_seq"]))
    i = 0
    while leftover > 0 and ordered:
        quota[ordered[i % len(ordered)]["id"]] += 1
        leftover -= 1
        i += 1
    return [(s, quota[s["id"]]) for s in ordered]


# ---------------------------------------------------------------------------
# clearance_markdown_value -- per-unit rounding FIRST, then multiply
# ---------------------------------------------------------------------------
def clearance_value(price_cents, markdown_pct, remaining_quantity):
    unit = rhu(D(price_cents) * (Decimal("1") - D(markdown_pct)), 0)
    return int(unit) * int(remaining_quantity)


# ---------------------------------------------------------------------------
# scan_rate -- provisional and final variants
# ---------------------------------------------------------------------------
def provisional_rate(items_scanned, started_at, at):
    elapsed = max(int((at - started_at).total_seconds()), 1)
    return rhu(D(items_scanned) * Decimal("3600") / D(elapsed), 2)


def final_rate(items_scanned, voids, started_at, closed_at):
    duration = max(int((closed_at - started_at).total_seconds()), 1)
    effective = D(items_scanned) - D(VOID_PENALTY * voids)
    return rhu(effective * Decimal("3600") / D(duration), 2)


def compliance_for(final):
    return "COMPLIANT" if D(final) >= SCAN_TARGET else "BELOW_STANDARD"


# ---------------------------------------------------------------------------
# double_refund
# ---------------------------------------------------------------------------
def refund_amount(reason, unit_price_cents, quantity):
    multiplier = GUARANTEE_MULTIPLIER if reason == "QUALITY_DEFECT" else STANDARD_MULTIPLIER
    return rhu_int(D(unit_price_cents) * D(quantity) * multiplier)


# ---------------------------------------------------------------------------
# labor_window_cost and ISO-week helpers
# ---------------------------------------------------------------------------
def window_cost(role, starts_at, ends_at):
    hours = rhu(D((ends_at - starts_at).total_seconds()) / Decimal("3600"), 2)
    return rhu_int(hours * D(ROLE_RATE_CENTS_PER_HOUR[role]))


def same_iso_week(a, b):
    return iso_week_monday(a) == iso_week_monday(b)


def windows_in_week(windows, store_id, reference_start):
    return [
        w for w in windows
        if w["store_id"] == store_id
        and w["status"] in ("PLANNED", "CONFIRMED")
        and same_iso_week(w["starts_at"], reference_start)
    ]


def weekly_spend(windows, store_id, reference_start):
    return sum(w["cost_cents"] for w in windows_in_week(windows, store_id, reference_start))
