"""Business services: derivations, calculations, cascades, clock transitions."""

import datetime
import uuid
from decimal import Decimal, ROUND_HALF_UP

import db
from errors import raise_err

# ---- Constants (from scaffold / PRD) ----
TITLE_FAIR_OVERLAP_LIMIT = 2
CENTS_PER_POINT = 100
SHIPPING_FLAT_CENTS = 750
FREE_SHIP_MIN_CENTS = 2500
CLUB_PRICE_FACTOR_NUM = 70
CLUB_PRICE_FACTOR_DEN = 100
ROYALTY_PER_UNIT_CENTS = 90
POINTS_EXPIRY_MONTHS = 12
SUPPLY_UNIT_POINTS_COST = 200

GRADE_BANDS = {"K_2", "G3_5", "G6_8"}
TITLE_FORMATS = {"HARDCOVER", "PAPERBACK", "CLUB_PAPERBACK"}


# ---- Generic helpers ----

def new_id():
    return str(uuid.uuid4())


def new_record(extra=None):
    now = db.now_iso_ms()
    rec = {"id": new_id(), "created_at": now, "updated_at": now, "version": 1}
    if extra:
        rec.update(extra)
    return rec


def touch(rec):
    rec["updated_at"] = db.now_iso_ms()
    rec["version"] = rec.get("version", 1) + 1


def parse_date(value, field="date"):
    if not isinstance(value, str):
        raise_err("ERR_INVALID_REQUEST", "%s must be a YYYY-MM-DD string" % field)
    try:
        return datetime.datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise_err("ERR_INVALID_REQUEST", "%s must parse as YYYY-MM-DD" % field)


def parse_month(value):
    if not isinstance(value, str):
        raise_err("ERR_INVALID_REQUEST", "month must be a YYYY-MM string")
    try:
        datetime.datetime.strptime(value, "%Y-%m")
    except ValueError:
        raise_err("ERR_INVALID_REQUEST", "month must parse as YYYY-MM")
    return value


def month_bounds(month_key):
    y, m = int(month_key[:4]), int(month_key[5:7])
    start = datetime.date(y, m, 1)
    end = datetime.date(y + 1, 1, 1) if m == 12 else datetime.date(y, m + 1, 1)
    return start, end


def windows_intersect(a_start, a_end, b_start, b_end):
    """Half-open [start, end) intersection; adjacency is allowed."""
    return a_start < b_end and b_start < a_end


def months_plus(d, months):
    y = d.year + (d.month - 1 + months) // 12
    m = (d.month - 1 + months) % 12 + 1
    dim = [31, 29 if (y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)) else 28,
           31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]
    return datetime.date(y, m, min(d.day, dim))


# ---- School derivations ----

def school_posture(school_id):
    active = [e for e in db.enrollments.values()
              if e["school_id"] == school_id and e["status"] == "ACTIVE"]
    if active:
        return "NORMAL"
    any_enr = [e for e in db.enrollments.values() if e["school_id"] == school_id]
    return "RESTRICTED" if any_enr else "NORMAL"


def school_active_fair_id(school_id):
    today = db.clock.date
    active = [f for f in db.book_fairs.values()
              if f["school_id"] == school_id and f["status"] == "ACTIVE"
              and f["_start"] <= today < f["_end"]]
    if not active:
        return None
    active.sort(key=lambda f: (f["created_at"], f["id"]))
    return active[0]["id"]


def serialize_school(s):
    return {
        "id": s["id"],
        "name": s["name"],
        "address": s["address"],
        "low_income_program": s["low_income_program"],
        "posture": school_posture(s["id"]),
        "active_fair_id": school_active_fair_id(s["id"]),
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


# ---- Teacher ----

def serialize_teacher(t):
    return {
        "id": t["id"],
        "school_id": t["school_id"],
        "full_name": t["full_name"],
        "email": t["email"],
        "grade_band": t["grade_band"],
        "points_balance": t["points_balance"],
        "points_earned_total": t["points_earned_total"],
        "points_redeemed_total": t["points_redeemed_total"],
        "points_expired_total": t["points_expired_total"],
        "donated_books_received": t["donated_books_received"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def append_ledger(teacher_id, entry_type, points, ref_type, ref_id, note=""):
    entry = new_record({
        "teacher_id": teacher_id,
        "entry_type": entry_type,
        "points": points,
        "ref_type": ref_type,
        "ref_id": ref_id,
        "note": note,
    })
    db.ledger[entry["id"]] = entry
    return entry


# ---- Title ----

def title_license_status(t):
    return "SUSPENDED" if t["royalty_accrued_cents"] > t["royalty_cap_cents"] else "ACTIVE"


def serialize_title(t):
    return {
        "id": t["id"],
        "isbn": t["isbn"],
        "name": t["name"],
        "format": t["format"],
        "grade_band": t["grade_band"],
        "base_price_cents": t["base_price_cents"],
        "points_cost": t["points_cost"],
        "rights_holder": t["rights_holder"],
        "royalty_cap_cents": t["royalty_cap_cents"],
        "license_status": title_license_status(t),
        "royalty_accrued_cents": t["royalty_accrued_cents"],
        "fair_count_used": title_fair_count_used(t["id"]),
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def title_fair_count_used(title_id):
    """Count of this title's FlyerOffering rows with fair_overlap == true
    across all PUBLISHED FlyerCycles."""
    n = 0
    for o in db.offerings.values():
        if o["title_id"] != title_id:
            continue
        cyc = db.flyer_cycles.get(o["cycle_id"])
        if cyc is not None and cyc["status"] == "PUBLISHED" and offering_fair_overlap(o):
            n += 1
    return n


def accrue_royalty(title, units):
    """Accrue ROYALTY_PER_UNIT_CENTS per unit; flips license SUSPENDED when the
    running total crosses strictly above the cap. Non-blocking: whole event
    completes, flip is recomputed afterwards. Returns True if status flipped."""
    if units <= 0:
        return False
    before = title_license_status(title)
    title["royalty_accrued_cents"] += ROYALTY_PER_UNIT_CENTS * units
    after = title_license_status(title)
    if before != after:
        touch(title)
        return True
    return False


def reverse_royalty(title, units):
    if units <= 0:
        return False
    before = title_license_status(title)
    title["royalty_accrued_cents"] -= ROYALTY_PER_UNIT_CENTS * units
    after = title_license_status(title)
    if before != after:
        touch(title)
        return True
    return False


# ---- Promotion ----

def promotion_status(p):
    return "EXPIRED" if db.clock.date >= p["_ends"] else "ACTIVE"


def serialize_promotion(p):
    return {
        "id": p["id"],
        "name": p["name"],
        "kind": p["kind"],
        "grade_band": p["grade_band"],
        "title_id": p["title_id"],
        "multiplier_bp": p["multiplier_bp"],
        "bonus_points_per_unit": p["bonus_points_per_unit"],
        "starts_on": p["starts_on"],
        "ends_on": p["ends_on"],
        "status": promotion_status(p),
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def active_promotions(grade_band=None):
    """ACTIVE promos whose [starts_on, ends_on) window contains the clock date
    and whose grade_band is null or matches."""
    today = db.clock.date
    out = []
    for p in db.promotions.values():
        if promotion_status(p) != "ACTIVE":
            continue
        if not (p["_starts"] <= today < p["_ends"]):
            continue
        if grade_band is not None and p["grade_band"] is not None and p["grade_band"] != grade_band:
            continue
        out.append(p)
    return out


# ---- FlyerCycle / FlyerOffering ----

def cycle_offering_count(cycle_id):
    return sum(1 for o in db.offerings.values() if o["cycle_id"] == cycle_id)


def serialize_cycle(c):
    return {
        "id": c["id"],
        "school_id": c["school_id"],
        "month": c["month"],
        "grade_band": c["grade_band"],
        "status": c["status"],
        "offering_count": cycle_offering_count(c["id"]),
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def offering_fair_overlap(o):
    """True iff the school has a BookFair in SCHEDULED or ACTIVE whose window
    intersects the offering's cycle month AND the fair's title list includes
    the offering's title."""
    cyc = db.flyer_cycles.get(o["cycle_id"])
    if cyc is None:
        return False
    m_start, m_end = month_bounds(cyc["month"])
    for f in db.book_fairs.values():
        if f["school_id"] != cyc["school_id"]:
            continue
        if f["status"] not in ("SCHEDULED", "ACTIVE"):
            continue
        if not windows_intersect(f["_start"], f["_end"], m_start, m_end):
            continue
        for ft in db.fair_titles.values():
            if ft["fair_id"] == f["id"] and ft["title_id"] == o["title_id"]:
                return True
    return False


def serialize_offering(o):
    return {
        "id": o["id"],
        "cycle_id": o["cycle_id"],
        "title_id": o["title_id"],
        "flyer_price_cents": o["flyer_price_cents"],
        "fair_overlap": offering_fair_overlap(o),
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


def recompute_fair_overlap_for_school(school_id):
    """Touch offerings of PUBLISHED cycles at the school whose live
    fair_overlap flag changed (fair_overlap is derived; no stored field)."""
    for o in db.offerings.values():
        cyc = db.flyer_cycles.get(o["cycle_id"])
        if cyc is None or cyc["school_id"] != school_id or cyc["status"] != "PUBLISHED":
            continue
        live = offering_fair_overlap(o)
        if o.get("_fair_overlap_cache") != live:
            o["_fair_overlap_cache"] = live
            touch(o)


# ---- Order economics ----

TIER_TABLE = [(0, 0), (5000, 500), (15000, 1000), (40000, 1500)]


def tier_discount_bp(subtotal):
    applicable = 0
    for min_sub, bp in TIER_TABLE:
        if subtotal >= min_sub:
            applicable = bp
    return applicable


def order_lines_of(order_id, include_cancelled=False):
    lines = [l for l in db.order_lines.values() if l["class_order_id"] == order_id]
    if not include_cancelled:
        lines = [l for l in lines if l["status"] != "CANCELLED"]
    lines.sort(key=lambda l: (l["created_at"], l["id"]))
    return lines


def order_aggregates(order):
    lines = order_lines_of(order["id"])
    subtotal = sum(l["qty"] * l["unit_price_cents"] for l in lines)
    rewardable = sum(l["qty"] * l["unit_price_cents"] for l in lines
                     if not l["fair_overlap"] and not l["donation_funded"])
    bp = tier_discount_bp(subtotal)
    discount = int((Decimal(subtotal) * Decimal(bp) / Decimal(10000)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP))
    net = subtotal - discount
    school = db.schools.get(order_school_id(order))
    if school is not None and school["low_income_program"]:
        shipping = 0
    elif rewardable >= FREE_SHIP_MIN_CENTS:
        shipping = 0
    else:
        shipping = SHIPPING_FLAT_CENTS
    base, bonus = award_points(order, lines, rewardable)
    return {
        "subtotal_cents": subtotal,
        "rewardable_subtotal_cents": rewardable,
        "discount_cents": discount,
        "net_total_cents": net,
        "shipping_fee_cents": shipping,
        "awarded_base_points": base,
        "awarded_bonus_points": bonus,
        "awarded_total_points": base + bonus,
    }


def award_points(order, lines, rewardable):
    """Pinned three-step reward calculation. Returns (base, bonus)."""
    base = rewardable // CENTS_PER_POINT
    teacher = db.teachers.get(order["teacher_id"])
    band = teacher["grade_band"] if teacher else None
    promos = active_promotions(band)
    # Best BONUS_POINTS multiplier: highest multiplier_bp, ties by created_at ASC, name ASC.
    bonus_promos = [p for p in promos if p["kind"] == "BONUS_POINTS"]
    multiplier_bonus = 0
    if bonus_promos:
        best = sorted(bonus_promos,
                      key=lambda p: (-p["multiplier_bp"], p["created_at"], p["name"]))[0]
        multiplier_bonus = (base * (best["multiplier_bp"] - 100)) // 100
    # TITLE_INCENTIVE: stack additively per qualifying line of that title.
    incentive_points = 0
    incentives = [p for p in promos if p["kind"] == "TITLE_INCENTIVE"]
    if incentives:
        qty_by_title = {}
        for l in lines:
            if l["fair_overlap"] or l["donation_funded"]:
                continue
            offering = db.offerings.get(l["offering_id"])
            if offering is None:
                continue
            qty_by_title[offering["title_id"]] = qty_by_title.get(offering["title_id"], 0) + l["qty"]
        for p in incentives:
            incentive_points += qty_by_title.get(p["title_id"], 0) * p["bonus_points_per_unit"]
    return base, multiplier_bonus + incentive_points


def line_points_attribution(order, lines, base):
    """Floor per qualifying line, order-level remainder to the earliest-created
    qualifying line (created_at ASC, tie-break student_name ASC)."""
    qualifying = [l for l in lines if not l["fair_overlap"] and not l["donation_funded"]]
    for l in lines:
        if l["fair_overlap"] or l["donation_funded"]:
            l["points_earned"] = 0
        else:
            l["points_earned"] = (l["qty"] * l["unit_price_cents"]) // CENTS_PER_POINT
    if not qualifying:
        return
    remainder = base - sum(l["points_earned"] for l in qualifying)
    if remainder > 0:
        first = sorted(qualifying, key=lambda l: (l["created_at"], l["student_name"]))[0]
        first["points_earned"] += remainder


def order_school_id(order):
    cyc = db.flyer_cycles.get(order["cycle_id"])
    return cyc["school_id"] if cyc else None


def recompute_order(order):
    aggs = order_aggregates(order)
    order.update(aggs)
    lines = order_lines_of(order["id"])
    line_points_attribution(order, lines, aggs["awarded_base_points"])


def serialize_order(o):
    return {
        "id": o["id"],
        "cycle_id": o["cycle_id"],
        "teacher_id": o["teacher_id"],
        "status": o["status"],
        "ship_status": o["ship_status"],
        "points_status": o["points_status"],
        "subtotal_cents": o["subtotal_cents"],
        "rewardable_subtotal_cents": o["rewardable_subtotal_cents"],
        "discount_cents": o["discount_cents"],
        "net_total_cents": o["net_total_cents"],
        "shipping_fee_cents": o["shipping_fee_cents"],
        "awarded_base_points": o["awarded_base_points"],
        "awarded_bonus_points": o["awarded_bonus_points"],
        "awarded_total_points": o["awarded_total_points"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


def serialize_line(l):
    return {
        "id": l["id"],
        "class_order_id": l["class_order_id"],
        "offering_id": l["offering_id"],
        "student_name": l["student_name"],
        "submitted_by": l["submitted_by"],
        "qty": l["qty"],
        "unit_price_cents": l["unit_price_cents"],
        "fair_overlap": l["fair_overlap"],
        "donation_funded": l["donation_funded"],
        "status": l["status"],
        "points_earned": l["points_earned"],
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
        "version": l["version"],
    }


# ---- BookFair / FairTitle ----

def serialize_fair(f):
    return {
        "id": f["id"],
        "school_id": f["school_id"],
        "start_date": f["start_date"],
        "end_date": f["end_date"],
        "status": f["status"],
        "created_at": f["created_at"],
        "updated_at": f["updated_at"],
        "version": f["version"],
    }


def serialize_fair_title(ft):
    return {
        "id": ft["id"],
        "fair_id": ft["fair_id"],
        "title_id": ft["title_id"],
        "created_at": ft["created_at"],
        "updated_at": ft["updated_at"],
        "version": ft["version"],
    }


def fair_title_count(fair_id):
    return sum(1 for ft in db.fair_titles.values() if ft["fair_id"] == fair_id)


# ---- DonationRequest ----

def serialize_donation(d):
    return {
        "id": d["id"],
        "school_id": d["school_id"],
        "teacher_id": d["teacher_id"],
        "title_id": d["title_id"],
        "qty_requested": d["qty_requested"],
        "qty_matched": d["qty_matched"],
        "status": d["status"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


# ---- Redemption ----

def serialize_redemption(r):
    return {
        "id": r["id"],
        "teacher_id": r["teacher_id"],
        "kind": r["kind"],
        "title_id": r["title_id"],
        "qty": r["qty"],
        "points_cost": r["points_cost"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


# ---- ProgramEnrollment ----

def serialize_enrollment(e):
    return {
        "id": e["id"],
        "school_id": e["school_id"],
        "status": e["status"],
        "enrolled_on": e["enrolled_on"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


# ---- PointsLedger ----

def serialize_ledger(e):
    return {
        "id": e["id"],
        "teacher_id": e["teacher_id"],
        "entry_type": e["entry_type"],
        "points": e["points"],
        "ref_type": e["ref_type"],
        "ref_id": e["ref_id"],
        "note": e["note"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


# ---- Suspension cascade ----

def cancel_order_lines(order):
    for l in order_lines_of(order["id"]):
        if l["status"] != "CANCELLED":
            l["status"] = "CANCELLED"
            touch(l)


def cascade_suspend_school(school_id):
    """Cancel every OPEN ClassOrder belonging to a teacher of this school."""
    teacher_ids = {t["id"] for t in db.teachers.values() if t["school_id"] == school_id}
    for o in db.class_orders.values():
        if o["teacher_id"] in teacher_ids and o["status"] == "OPEN":
            cancel_order_lines(o)
            o["status"] = "CANCELLED"
            touch(o)
            recompute_order(o)


# ---- Clock transitions ----

def fire_clock_transitions():
    """On clock advance: fair ACTIVATE/COMPLETE, promotion EXPIRE (derived),
    active_fair_id recompute (derived). Fairs are stored-status so they get
    explicit transitions here."""
    today = db.clock.date
    affected_schools = set()
    for f in sorted(db.book_fairs.values(), key=lambda f: (f["created_at"], f["id"])):
        if f["status"] == "SCHEDULED" and today >= f["_end"]:
            # The clock jumped past the whole window: SCHEDULED -> ACTIVE -> COMPLETED.
            f["status"] = "COMPLETED"
            touch(f)
            affected_schools.add(f["school_id"])
        elif f["status"] == "SCHEDULED" and f["_start"] <= today < f["_end"]:
            f["status"] = "ACTIVE"
            touch(f)
            affected_schools.add(f["school_id"])
        elif f["status"] == "ACTIVE" and today >= f["_end"]:
            f["status"] = "COMPLETED"
            touch(f)
            affected_schools.add(f["school_id"])
    for school_id in affected_schools:
        recompute_fair_overlap_for_school(school_id)
    # Promotions and school posture/active_fair_id are derived on read.


# ---- Points expiry sweep ----

def run_points_expiry():
    """FIFO expiry of EARN points older than POINTS_EXPIRY_MONTHS before the
    logical clock date. Returns (expired_total_points, teachers_affected)."""
    clock_date = db.clock.date
    expired_total = 0
    teachers_affected = 0
    ops_run_id = new_id()
    for teacher in sorted(db.teachers.values(), key=lambda t: (t["created_at"], t["id"])):
        entries = [e for e in db.ledger.values() if e["teacher_id"] == teacher["id"]]
        entries.sort(key=lambda e: (e["created_at"], e["note"]))
        earns = []
        consumed = []  # (consumed points, entry date)
        for e in entries:
            if e["entry_type"] == "EARN":
                earns.append(e)
            elif e["entry_type"] in ("REDEEM", "EXPIRE", "CLAWBACK"):
                consumed.append(e)
        # FIFO consumption matching against chronological EARN order.
        remaining = []
        ci = 0
        cleft = -consumed[0]["points"] if consumed else 0
        for earn in earns:
            left = earn["points"]
            while ci < len(consumed) and left > 0:
                if cleft <= 0:
                    ci += 1
                    cleft = -consumed[ci]["points"] if ci < len(consumed) else 0
                    continue
                take = min(left, cleft)
                left -= take
                cleft -= take
            remaining.append((earn, left))
        # Expire unconsumed points from entries older than the threshold.
        expired = 0
        for earn, left in remaining:
            if left <= 0:
                continue
            earn_date = datetime.datetime.strptime(
                earn["created_at"], "%Y-%m-%dT%H:%M:%S.%fZ").date()
            if months_plus(earn_date, POINTS_EXPIRY_MONTHS) <= clock_date:
                expired += left
        if expired > 0:
            append_ledger(teacher["id"], "EXPIRE", -expired, "OPS_RUN", ops_run_id)
            teacher["points_expired_total"] += expired
            teacher["points_balance"] -= expired
            touch(teacher)
            expired_total += expired
            teachers_affected += 1
    return expired_total, teachers_affected


# ---- Shipping sweep ----

def run_shipping():
    """Ship BACKORDERED lines with ACTIVE-license titles on SUBMITTED orders;
    re-derive ship_status. Returns (shipped_line_count, orders_touched)."""
    shipped_lines = 0
    orders_touched = 0
    for order in sorted(db.class_orders.values(), key=lambda o: (o["created_at"], o["id"])):
        if order["status"] != "SUBMITTED":
            continue
        if order["ship_status"] not in ("PENDING", "PARTIAL"):
            continue
        lines = order_lines_of(order["id"])
        shipped_this = 0
        for l in lines:
            if l["status"] != "BACKORDERED":
                continue
            offering = db.offerings.get(l["offering_id"])
            title = db.titles.get(offering["title_id"]) if offering else None
            if title is not None and title_license_status(title) == "ACTIVE":
                l["status"] = "ACTIVE"
                touch(l)
                shipped_this += 1
        backordered_left = sum(1 for l in order_lines_of(order["id"])
                               if l["status"] == "BACKORDERED")
        if shipped_this > 0:
            shipped_lines += shipped_this
            if backordered_left == 0:
                order["ship_status"] = "SHIPPED"
            elif order["ship_status"] == "PENDING":
                order["ship_status"] = "PARTIAL"
            orders_touched += 1
            touch(order)
    return shipped_lines, orders_touched
