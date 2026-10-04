"""Calculation rules (PRD 3.x / scaffold 1.3), with pinned evaluation orders.

Rounding: ROUND_HALF_UP to whole cents, applied exactly where the PRD pins it.
All date/datetime inputs are compared against the logical clock in db.
"""

from decimal import Decimal, ROUND_HALF_UP

import constants
import db
import util


def round_cents(d):
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# --- member_status_calc ---
def member_status(member):
    """ACTIVE iff current logical date <= expires_on, else LAPSED."""
    expires = util.parse_date(member["expires_on"])
    return "ACTIVE" if db.today() <= expires else "LAPSED"


# --- member_unit_price_cents ---
def member_unit_price(fee_cents, is_active_member):
    if is_active_member:
        return round_cents(
            Decimal(fee_cents) * (Decimal(1) - Decimal(constants.MEMBER_DISCOUNT_PCT))
        )
    return fee_cents


# --- loan_premium_cents (FINAL variant; pinned rounding order) ---
def loan_premium_final(declared_value_cents, courier_required, coverage_type):
    if coverage_type == "INDEMNITY":
        return 0
    v = declared_value_cents
    tier1 = Decimal(min(v, constants.TIER1_CAP_CENTS)) * Decimal(constants.TIER1_RATE)
    tier2 = Decimal(min(max(0, v - constants.TIER1_CAP_CENTS), constants.TIER2_WIDTH_CENTS)) * Decimal(
        constants.TIER2_RATE
    )
    tier3 = Decimal(max(0, v - constants.TIER1_CAP_CENTS - constants.TIER2_WIDTH_CENTS)) * Decimal(
        constants.TIER3_RATE
    )
    # (2) round the tiered base exactly once, half up
    base_cents = round_cents(tier1 + tier2 + tier3)
    # (3) courier surcharge computed from the ROUNDED base, rounded half up
    surcharge = (
        round_cents(Decimal(base_cents) * Decimal(constants.COURIER_SURCHARGE_RATE))
        if courier_required
        else 0
    )
    # (4) sum of rounded parts
    return base_cents + surcharge


# --- loan_window_overlap: half-open [start, end); adjacency is NOT overlap ---
def half_open_overlap(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


# --- research_visit_overlap: CLOSED visit intervals; shared boundary conflicts ---
def closed_overlap(a_start, a_end, b_start, b_end):
    return a_start <= b_end and b_start <= a_end


def visit_loan_conflict(v_start, v_end, l_start, l_end):
    """Closed visit interval vs half-open loan window."""
    return v_start < l_end and l_start <= v_end


# --- gallery_schedule_overlap ---
def gallery_conflict(museum_id, gallery_code, day_of_week, start_minute, end_minute, exclude_id=None):
    """Buffer-expanded conflict per PRD 3.3. The PRD pins that a gap of exactly
    SETUP_BUFFER_MINUTES (30) between sessions is allowed (expanded intervals
    'touch but do not overlap'), so the expansion is applied on the start side:
    occupied = [start - buffer, end). Only SCHEDULED programs participate."""
    for p in db.STORE["education_programs"].values():
        if exclude_id is not None and p["id"] == exclude_id:
            continue
        if p["status"] != "SCHEDULED":
            continue
        if (
            p["museum_id"] != museum_id
            or p["gallery_code"] != gallery_code
            or p["day_of_week"] != day_of_week
        ):
            continue
        if (start_minute - constants.SETUP_BUFFER_MINUTES) < p["end_minute"] and (
            p["start_minute"] - constants.SETUP_BUFFER_MINUTES
        ) < end_minute:
            return True
    return False


# --- fund_available_cents (SETTLED and COMMITTED variants) ---
def fund_receipts(fund_id):
    """TRUST-fund ticket receipts net of refunds (PRD 2.7/3.2). A purchase
    credits receipts by price_paid_cents and a refund debits them by the same
    price_paid_cents, so a REFUNDED ticket nets to zero (its earlier credit is
    cancelled by the refund debit) and contributes nothing here. FEDERAL funds
    are never named as a revenue fund, so this reads 0 for them."""
    total = 0
    for t in db.STORE["tickets"].values():
        ex = db.STORE["exhibitions"].get(t["exhibition_id"])
        if ex is None or ex["revenue_fund_id"] != fund_id:
            continue
        if t["status"] in ("PURCHASED", "REDEEMED"):
            total += t["price_paid_cents"]
    return total


def settled_available(fund):
    posted = sum(
        e["amount_cents"]
        for e in db.STORE["expenditures"].values()
        if e["fund_id"] == fund["id"] and e["status"] == "POSTED"
    )
    return fund["appropriation_cents"] + fund_receipts(fund["id"]) - posted


def committed_available(fund):
    committed = sum(
        r["estimated_cost_cents"]
        for r in db.STORE["collection_reviews"].values()
        if r["review_kind"] == "ACQUISITION"
        and r["status"] == "APPROVED"
        and r["fund_id"] == fund["id"]
    )
    return settled_available(fund) - committed


# --- fund_activity_permission ---
def activity_permitted(fund_type, activity_type):
    allowed = (
        constants.FEDERAL_PERMITTED_ACTIVITIES
        if fund_type == "FEDERAL"
        else constants.TRUST_PERMITTED_ACTIVITIES
    )
    return activity_type in allowed


# --- reservation_status_resolution / waitlist_promotion ---
def confirmed_headcount(program_id, visit_date):
    return sum(
        r["headcount"]
        for r in db.STORE["school_reservations"].values()
        if r["program_id"] == program_id
        and r["visit_date"] == visit_date
        and r["status"] == "CONFIRMED"
    )


def confirmed_docents(program_id, service_date):
    return sum(
        1
        for a in db.STORE["docent_assignments"].values()
        if a["program_id"] == program_id
        and a["service_date"] == service_date
        and a["status"] == "CONFIRMED"
    )


def docents_required(headcount, ratio):
    return -(-headcount // ratio)  # ceil division


def evaluate_reservation_status(program, headcount, visit_date, created_at, seq):
    """Steps (2)-(5) of reservation_status_resolution (hard validation has
    already run in the route): capacity, then docents, then queue position."""
    program_id = program["id"]
    capacity_fits = (
        confirmed_headcount(program_id, visit_date) + headcount
        <= program["student_capacity"]
    )
    docs_ok = confirmed_docents(program_id, visit_date) >= docents_required(
        headcount, program["docent_ratio"]
    )
    queue_blocked = any(
        r["status"] == "WAITLISTED"
        and r["program_id"] == program_id
        and r["visit_date"] == visit_date
        and (r["created_at"], r["_seq"]) < (created_at, seq)
        for r in db.STORE["school_reservations"].values()
    )
    if capacity_fits and docs_ok and not queue_blocked:
        return "CONFIRMED"
    return "WAITLISTED"


def promote_waitlist(program_id, visit_date):
    """Strict FIFO waterfall with head-of-line blocking: scan WAITLISTED rows
    in created_at ASC order; promote the head iff it fits capacity and docent
    requirements; stop at the first head that does not fit."""
    program = db.STORE["education_programs"].get(program_id)
    if program is None:
        return
    while True:
        waiting = [
            r
            for r in db.STORE["school_reservations"].values()
            if r["program_id"] == program_id
            and r["visit_date"] == visit_date
            and r["status"] == "WAITLISTED"
        ]
        if not waiting:
            return
        waiting.sort(key=lambda r: (r["created_at"], r["_seq"]))
        head = waiting[0]
        capacity_fits = (
            confirmed_headcount(program_id, visit_date) + head["headcount"]
            <= program["student_capacity"]
        )
        docs_ok = confirmed_docents(program_id, visit_date) >= docents_required(
            head["headcount"], program["docent_ratio"]
        )
        if capacity_fits and docs_ok:
            head["status"] = "CONFIRMED"
            db.touch(head)
        else:
            return


# --- screening_backlog_minutes (FORWARD variant; server-reported) ---
def screening_backlog_minutes(museum):
    slot = db.current_slot_index()
    today = db.today_str()
    pending = sum(
        1
        for p in db.STORE["timed_entry_passes"].values()
        if p["museum_id"] == museum["id"]
        and p["visit_date"] == today
        and p["status"] == "RESERVED"
        and p["entry_quarter_hour"] <= slot
    )
    return max(0, pending - museum["screening_rate_per_quarter_hour"]) * constants.SLOT_MINUTES
