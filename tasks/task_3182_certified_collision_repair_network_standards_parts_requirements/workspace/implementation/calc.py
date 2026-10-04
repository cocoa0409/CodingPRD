"""Domain calculations: compliance score, grading, OE ratios, technician
currency, referral ranking, warranty reserve accrual, ZIP centroids."""
import math
from datetime import datetime, timezone

from db import db
from util import bump, parse_dt

# ---------------------------------------------------------------------------
# Constants (SCAFFOLD 1.3)
# ---------------------------------------------------------------------------
CATEGORY_WEIGHT = {"EQUIPMENT": 30, "STRUCTURAL": 30, "TOOLING": 15, "TRAINING": 25}
SEVERITY_POINTS = {"MINOR": 1, "MAJOR": 5, "CRITICAL": 25}
ESCALATION_PENALTY_EACH = 3
GRADE_B_MAX = 5
GRADE_C_MAX = 24
LOCATOR_RADIUS_MILES = 25.0
W_DISTANCE, W_COMPLIANCE, W_LOAD = 0.6, 0.3, 0.1
LOAD_CAP = 20
TIER1_CAP_CENTS = 100000
TIER1_RATE = 0.03
TIER2_CAP_CENTS = 500000
TIER2_RATE = 0.02
TIER3_RATE = 0.01
ADAS_MULTIPLIER = 1.5
REWORK_PENALTY_CENTS = 500
ADAS_MODEL_YEAR_THRESHOLD = 2018
CORRECTIVE_ACTION_DAYS = {"MINOR": 60, "MAJOR": 30, "CRITICAL": 10}
DELIVERY_GRACE_HOURS = 24
WARRANTY_MONTHS = 12
REFERRAL_TTL_HOURS = 72
DECERTIFY_GRACE_DAYS = 90
ESCALATION_THRESHOLD_CENTS = 500000
CLAIM_CLOSE_DAYS = 30
MAX_REWORK = 3


def round_half_up(value, places):
    q = 10 ** places
    n = value * q
    fl = math.floor(n)
    if n - fl >= 0.5 - 1e-12:
        fl += 1
    return fl / q


def add_months(dt, months):
    """Calendar-month addition, clamping the day to the target month's length."""
    y = dt.year + (dt.month - 1 + months) // 12
    m = (dt.month - 1 + months) % 12 + 1
    days_in_month = [31, 29 if y % 4 == 0 and (y % 100 != 0 or y % 400 == 0) else 28,
                     31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]
    d = min(dt.day, days_in_month)
    return dt.replace(year=y, month=m, day=d)


# ---------------------------------------------------------------------------
# ZIP centroids: consumer ZIP locations come from known shop ZIP codes only.
# A consumer ZIP with no shop at that ZIP has no known location -> no
# candidates within any finite radius (empty pool / empty locator page).
# ---------------------------------------------------------------------------
def zip_centroid(zip_code):
    matches = [s for s in db.shops.values() if s.get("zip_code") == zip_code]
    if not matches:
        return None
    lat = sum(float(s["latitude"]) for s in matches) / len(matches)
    lng = sum(float(s["longitude"]) for s in matches) / len(matches)
    return (lat, lng)


def haversine_miles(lat1, lng1, lat2, lng2):
    r = 3958.7613
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


# ---------------------------------------------------------------------------
# shop_compliance_score (SCAFFOLD 1.3)
# ---------------------------------------------------------------------------
def compute_compliance_score(shop):
    now = db.clock
    score = 0.0
    for cat, weight in CATEGORY_WEIGHT.items():
        reqs = [r for r in db.requirements.values()
                if r["category"] == cat and r["status"] == "PUBLISHED"
                and parse_dt(r["effective_from"], "effective_from") <= now]
        total = len(reqs)
        if total == 0:
            cat_score = 100.0
        else:
            satisfied = 0
            for r in reqs:
                if any(a["shop_id"] == shop["id"]
                       and a["requirement_id"] == r["id"]
                       and a["status"] == "ACTIVE"
                       for a in db.attestations.values()):
                    satisfied += 1
            cat_score = 100.0 * satisfied / total
        if cat == "TRAINING":
            roles = {t["tech_role"] for t in db.technicians.values()
                     if t["shop_id"] == shop["id"] and t["status"] != "INACTIVE"}
            for role in roles:
                if not any(t["shop_id"] == shop["id"] and t["tech_role"] == role
                           and t["status"] == "CURRENT"
                           for t in db.technicians.values()):
                    cat_score = cat_score * 0.5
                    break
        score += weight * cat_score
    return round_half_up(score / 100.0, 2)


def recompute_shop_score(shop):
    val = compute_compliance_score(shop)
    if shop.get("live_compliance_score") != val:
        shop["live_compliance_score"] = val
        bump(shop)


# ---------------------------------------------------------------------------
# certification_grade_from_findings
# ---------------------------------------------------------------------------
def grade_for_audit(audit):
    severity_points = sum(
        SEVERITY_POINTS[a["finding_severity"]]
        for a in db.corrective_actions.values() if a["audit_id"] == audit["id"])
    cycle = db.cycles.get(audit["cycle_id"])
    shop_id = cycle["shop_id"] if cycle else None
    escalations = 0
    for claim in db.warranty_claims.values():
        if claim["status"] != "ESCALATED":
            continue
        order = db.repair_orders.get(claim["repair_order_id"])
        if order and order["shop_id"] == shop_id:
            escalations += 1
    effective = severity_points + ESCALATION_PENALTY_EACH * escalations
    if effective == 0:
        return "A", severity_points, effective
    if effective <= GRADE_B_MAX:
        return "B", severity_points, effective
    if effective <= GRADE_C_MAX:
        return "C", severity_points, effective
    return "F", severity_points, effective


# ---------------------------------------------------------------------------
# oe_parts_ratio
# ---------------------------------------------------------------------------
def recompute_oe_ratios(order):
    lines = [l for l in db.part_lines.values()
             if l["repair_order_id"] == order["id"] and l["line_status"] == "ACTIVE"]
    if not lines:
        by_count = by_cost = 1.0
    else:
        oe = [l for l in lines if l["part_class"] in ("OE", "OE_SURPLUS")]
        by_count = round_half_up(len(oe) / len(lines), 4)
        cost_all = sum(l["unit_cost_cents"] * l["quantity"] for l in lines)
        cost_oe = sum(l["unit_cost_cents"] * l["quantity"] for l in oe)
        by_cost = round_half_up(cost_oe / cost_all, 4) if cost_all else 1.0
    changed = (order.get("oe_parts_ratio_by_count") != by_count
               or order.get("oe_parts_ratio_by_cost") != by_cost)
    order["oe_parts_ratio_by_count"] = by_count
    order["oe_parts_ratio_by_cost"] = by_cost
    if changed:
        bump(order)


# ---------------------------------------------------------------------------
# technician_currency
# ---------------------------------------------------------------------------
def compute_progress(tech):
    required = [c for c in db.courses.values()
                if c.get("active") and tech["tech_role"] in (c.get("required_for_roles") or [])]
    if not required:
        return 100.0
    satisfied = 0
    for course in required:
        if any(cc["technician_id"] == tech["id"] and cc["course_id"] == course["id"]
               and cc["status"] == "CURRENT" for cc in db.completions.values()):
            satisfied += 1
    return round_half_up(100.0 * satisfied / len(required), 2)


def recompute_technician(tech, touch_shop=True):
    if tech["status"] == "INACTIVE":
        return
    progress = compute_progress(tech)
    changed = False
    if tech.get("curriculum_progress_pct") != progress:
        tech["curriculum_progress_pct"] = progress
        changed = True
    old_status = tech["status"]
    if progress == 100.0:
        new_status = "CURRENT"
    elif old_status == "CURRENT":
        new_status = "LAPSED"
    else:
        new_status = old_status
    if new_status != old_status:
        tech["status"] = new_status
        changed = True
    if changed:
        bump(tech)
        if touch_shop:
            shop = db.shops.get(tech["shop_id"])
            if shop:
                recompute_shop_score(shop)


def recompute_all_technicians():
    for tech in db.technicians.values():
        recompute_technician(tech)


# ---------------------------------------------------------------------------
# warranty_reserve_accrual (pinned evaluation order)
# ---------------------------------------------------------------------------
def compute_reserve_accrual(order):
    base = order["estimate_total_cents"]
    t1 = min(base, TIER1_CAP_CENTS) * TIER1_RATE
    t2 = min(max(base - TIER1_CAP_CENTS, 0), TIER2_CAP_CENTS - TIER1_CAP_CENTS) * TIER2_RATE
    t3 = max(base - TIER2_CAP_CENTS, 0) * TIER3_RATE
    base_rate_amount = t1 + t2 + t3
    mult = ADAS_MULTIPLIER if is_adas_equipped(order) else 1.0
    rounded = round_half_up(base_rate_amount * mult, 0)
    return int(rounded) + REWORK_PENALTY_CENTS * order["rework_count"]


def is_adas_equipped(order):
    if order.get("adas_equipped") is not None:
        return bool(order["adas_equipped"])
    return order["vehicle_model_year"] >= ADAS_MODEL_YEAR_THRESHOLD


# ---------------------------------------------------------------------------
# referral_ranking
# ---------------------------------------------------------------------------
def _insurer_gate(shop, referral_insurer_code):
    return any(r["shop_id"] == shop["id"]
               and r["insurer_code"] == referral_insurer_code
               and r["status"] == "ACTIVE"
               and r["steering_enabled"]
               for r in db.insurer_relations.values())


def rank_candidates(consumer_zip, source_type=None, insurer_code=None,
                    radius_miles=LOCATOR_RADIUS_MILES):
    centroid = zip_centroid(consumer_zip)
    if centroid is None:
        return []
    clat, clng = centroid
    pool = []
    for shop in db.shops.values():
        if shop["certification_status"] not in ("CERTIFIED", "PROBATION"):
            continue
        if shop["locator_hidden"]:
            continue
        dist = haversine_miles(float(shop["latitude"]), float(shop["longitude"]),
                               clat, clng)
        if dist > radius_miles:
            continue
        if source_type == "INSURER" and not _insurer_gate(shop, insurer_code):
            continue
        score = (W_DISTANCE * (1 - dist / LOCATOR_RADIUS_MILES)
                 + W_COMPLIANCE * (shop["live_compliance_score"] / 100.0)
                 + W_LOAD * (1 - min(shop["pending_referral_count"], LOAD_CAP) / LOAD_CAP))
        pool.append((round_half_up(score, 6), shop))
    pool.sort(key=lambda t: (-t[0], -t[1]["live_compliance_score"],
                             t[1]["created_at"], t[1]["_seq"]))
    return [shop for _, shop in pool]
