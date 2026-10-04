"""Calculation rules from SCAFFOLD §1.3 and PRD §3.

Rounding discipline (PRD §2.9):
- money and composite scores: round half up
- point accrual: floor division
- supply-order pricing: per-line round, then sum
- royalty tiers: sum unrounded tier products, single round half up at the end
"""
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from db import db
import errors as E

# Constants
BPS_DENOMINATOR = 10000
PASS_EXAM_SCORE = 80
AUDIT_ANOMALY_PENALTY = 5
VOLUME_DISCOUNT_QTY = 100
VOLUME_DISCOUNT_BPS = 500
MAX_PAR_LEVEL = 1000
POINT_VALUE_CENTS = 100
REDEEM_CAP_PCT_LICENSED = 50
REDEEM_CAP_PCT_COMPANY = 75
INSPECTION_PASS_SCORE = 85
CORRECTIVE_DUE_DAYS = 14
CATEGORY_FAIL_SCORE = 70
EARN_DIVISOR_CENTS = 200
EARN_RATE_LICENSED = 1
EARN_RATE_COMPANY = 2
MIN_CERTIFIED_BARISTAS = 2
MAX_REOPENS = 2
BREACH_SUSPEND_THRESHOLD = 2
ORDER_BUDGET_MAX_CENTS = 20000000
CERT_VALIDITY_DAYS = 365

INSPECTION_CATEGORIES = ("BEVERAGE_QUALITY", "FOOD_SAFETY", "BRAND_PRESENTATION", "SERVICE_SPEED")
INSPECTION_WEIGHTS = {
    "BEVERAGE_QUALITY": 30,
    "FOOD_SAFETY": 40,
    "BRAND_PRESENTATION": 20,
    "SERVICE_SPEED": 10,
}


def round_half_up(numer, denom):
    """Integer round-half-up of numer/denom; numer/denom are ints (numer >= 0)."""
    return int((Decimal(int(numer)) / Decimal(int(denom))).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Royalty recognition (royalty_recognition)
# ---------------------------------------------------------------------------

def tiered_royalty_amount(tiers, recognized_sales_cents):
    """Marginal tiers; products summed unrounded; single round_half_up at end."""
    s = Decimal(int(recognized_sales_cents))
    total = Decimal(0)
    ordered = sorted(tiers, key=lambda t: t["threshold_cents"])
    for i, tier in enumerate(ordered):
        lo = Decimal(int(tier["threshold_cents"]))
        hi = Decimal(int(ordered[i + 1]["threshold_cents"])) if i + 1 < len(ordered) else None
        upper = s if hi is None else min(s, hi)
        portion = upper - lo
        if portion < 0:
            portion = Decimal(0)
        total += portion * Decimal(int(tier["rate_bps"])) / Decimal(BPS_DENOMINATOR)
    return int(total.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def validate_royalty_tiers(tiers):
    if not isinstance(tiers, list) or not tiers:
        raise E.err_invalid_request("royalty_tiers must be a non-empty array")
    prev = None
    for t in tiers:
        if not isinstance(t, dict):
            raise E.err_invalid_request("each royalty tier must be an object")
        th = t.get("threshold_cents")
        rate = t.get("rate_bps")
        if isinstance(th, bool) or not isinstance(th, int) or th < 0:
            raise E.err_invalid_request("tier threshold_cents must be a non-negative integer")
        if isinstance(rate, bool) or not isinstance(rate, int) or not (1 <= rate <= 10000):
            raise E.err_invalid_request("tier rate_bps must be an integer in 1..10000")
        if prev is not None and th <= prev:
            raise E.err_invalid_request("tier thresholds must be strictly increasing")
        prev = th
    if tiers[0]["threshold_cents"] != 0:
        raise E.err_invalid_request("the first royalty tier threshold must be 0")


def recognized_sales_for_statement(agreement, stmt_start, stmt_end, generation_clock):
    """Sum net_sales_cents over FINALIZED reports of the agreement's stores whose
    period is fully inside [stmt_start, stmt_end], filtered by basis variant."""
    store_ids = {
        s["id"] for s in db.stores.values() if s["agreement_id"] == agreement["id"]
    }
    total = 0
    if agreement["royalty_basis"] == "CASH":
        cutoff = datetime.combine(stmt_end, time(23, 59, 59, 999999), tzinfo=timezone.utc)
    else:
        cutoff = generation_clock
    for r in db.sales_reports.values():
        if r["store_id"] not in store_ids:
            continue
        if r["status"] != "FINALIZED":
            continue
        rs = date.fromisoformat(r["period_start_date"])
        re_ = date.fromisoformat(r["period_end_date"])
        if rs < stmt_start or re_ > stmt_end:
            continue
        finalized_at = r.get("finalized_at")
        if finalized_at is None:
            continue
        fa = _parse_dt(finalized_at)
        if fa > cutoff:
            continue
        total += r["net_sales_cents"]
    return total


def _parse_dt(s):
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Certification exam outcome (certification_exam_outcome)
# ---------------------------------------------------------------------------

def exam_passed(exam_score, proctor_anomaly):
    if proctor_anomaly:
        return (exam_score - AUDIT_ANOMALY_PENALTY) >= PASS_EXAM_SCORE
    return exam_score >= PASS_EXAM_SCORE


# ---------------------------------------------------------------------------
# Supply order pricing (supply_order_pricing) — round per line, then sum
# ---------------------------------------------------------------------------

def line_discount_bps(quantity_ordered):
    return VOLUME_DISCOUNT_BPS if quantity_ordered >= VOLUME_DISCOUNT_QTY else 0


def line_cost_cents(quantity, unit_cost_cents, discount_bps):
    return round_half_up(quantity * unit_cost_cents * (BPS_DENOMINATOR - discount_bps), BPS_DENOMINATOR)


# ---------------------------------------------------------------------------
# Par replenishment (par_replenishment_quantity)
# ---------------------------------------------------------------------------

def ceil_to_case_pack(shortfall, case_pack_units):
    return ((shortfall + case_pack_units - 1) // case_pack_units) * case_pack_units


# ---------------------------------------------------------------------------
# Promotion price preview (promotion_price_preview)
# ---------------------------------------------------------------------------

def price_preview(base_price_cents, discount_pct, floor_price_cents, points_balance):
    raw = round_half_up(base_price_cents * (100 - discount_pct), 100)
    clamped = max(raw, floor_price_cents)
    cap = (clamped * REDEEM_CAP_PCT_LICENSED) // 100  # floor
    redemption = min(points_balance * POINT_VALUE_CENTS, cap)
    effective = clamped - redemption
    return {
        "clamped_price_cents": clamped,
        "redemption_cents": redemption,
        "effective_price_cents": effective,
    }


# ---------------------------------------------------------------------------
# Inspection composite (inspection_composite_result)
# ---------------------------------------------------------------------------

def inspection_composite(category_scores):
    weighted = sum(int(category_scores[c]) * INSPECTION_WEIGHTS[c] for c in INSPECTION_CATEGORIES)
    return round_half_up(weighted, 100)


# ---------------------------------------------------------------------------
# Loyalty points engine (loyalty_points_engine)
# ---------------------------------------------------------------------------

def earn_points(purchase_cents, store_format):
    whole = purchase_cents // EARN_DIVISOR_CENTS
    rate = EARN_RATE_LICENSED if store_format == "LICENSED" else EARN_RATE_COMPANY
    return whole * rate


def redeem_cap_points(purchase_cents, store_format):
    cap_pct = REDEEM_CAP_PCT_LICENSED if store_format == "LICENSED" else REDEEM_CAP_PCT_COMPANY
    return (purchase_cents * cap_pct) // 100 // POINT_VALUE_CENTS


# ---------------------------------------------------------------------------
# Store posture recompute (store_posture_recompute)
# ---------------------------------------------------------------------------

def certified_active_baristas(licensee_id):
    """Count of CERTIFIED certifications whose employee belongs to licensee_id,
    is active, and has role_tag BARISTA."""
    n = 0
    for c in db.certifications.values():
        if c["status"] != "CERTIFIED":
            continue
        emp = db.employees.get(c["employee_id"])
        if emp is None:
            continue
        if emp["licensee_id"] != licensee_id:
            continue
        if not emp.get("active", True):
            continue
        if emp["role_tag"] != "BARISTA":
            continue
        n += 1
    return n


def open_correctives(store_id):
    n = 0
    for ca in db.corrective_actions.values():
        if ca["status"] not in ("OPEN", "SUBMITTED", "REOPENED"):
            continue
        insp = db.inspections.get(ca["inspection_id"])
        if insp is not None and insp["store_id"] == store_id:
            n += 1
    return n


def compute_posture(store):
    agreement = db.license_agreements[store["agreement_id"]]
    ca_count = open_correctives(store["id"])
    cert_count = certified_active_baristas(agreement["licensee_id"])
    if cert_count == 0 or ca_count >= 2:
        return "PROBATION"
    if cert_count < MIN_CERTIFIED_BARISTAS or ca_count == 1:
        return "WATCH"
    return "GOOD_STANDING"


def recompute_posture(store):
    """Recompute a store's posture; on transition INTO PROBATION cancel its PLANNED
    campaigns. Returns True if posture changed."""
    old = store["compliance_posture"]
    new = compute_posture(store)
    if new == old:
        return False
    store["compliance_posture"] = new
    import middleware as mw
    mw.touch(store)
    if new == "PROBATION":
        for c in db.promotion_campaigns.values():
            if c["store_id"] == store["id"] and c["status"] == "PLANNED":
                c["status"] = "CANCELLED"
                mw.touch(c)
    return True


def recompute_posture_for_licensee_stores(licensee_id):
    """Recompute posture of every non-DELICENSED store whose agreement belongs to
    this licensee (certification audit-verify / sweep-expiry triggers)."""
    for s in db.stores.values():
        if s["operating_status"] == "DELICENSED":
            continue
        ag = db.license_agreements[s["agreement_id"]]
        if ag["licensee_id"] == licensee_id:
            recompute_posture(s)


# ---------------------------------------------------------------------------
# Footprint utilization (footprint_utilization)
# ---------------------------------------------------------------------------

def venue_footprint_usage(venue_id, excluding_assortment_id=None):
    """Sum over the venue's stores (agreements in ACTIVE/SUSPENDED) of
    store.equipment_footprint_units + footprint_units of active assortment products."""
    usage = 0
    for s in db.stores.values():
        ag = db.license_agreements[s["agreement_id"]]
        if ag["venue_id"] != venue_id:
            continue
        if ag["status"] not in ("ACTIVE", "SUSPENDED"):
            continue
        usage += s["equipment_footprint_units"]
        for ai in db.assortment_items.values():
            if ai["store_id"] != s["id"] or not ai["active"]:
                continue
            if excluding_assortment_id is not None and ai["id"] == excluding_assortment_id:
                continue
            p = db.product_items.get(ai["product_item_id"])
            if p is not None:
                usage += p["footprint_units"]
    return usage
