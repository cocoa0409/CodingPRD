"""Business logic: calculations, cascades, window checks, clock-driven transitions."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import STORE
from response import parse_dt, fmt_dt, touch

SIZE_RANK = {"SMALL": 1, "MEDIUM": 2, "LARGE": 3}
UNION_MIN_CREW = {"SMALL": 4, "MEDIUM": 8, "LARGE": 14}
CREW_WEEKLY_RATE_CENTS = 120000
THEATRE_GROSS_PCT = Decimal("0.30")
POOL_SHARE_PCT = Decimal("0.65")

SIZE_CLASSES = ("SMALL", "MEDIUM", "LARGE")
BOOKING_STATUSES = ("REQUESTED", "APPROVED", "DECLINED", "WITHDRAWN", "ACTIVE",
                    "CLOSED", "EVICTED", "MAINTENANCE_HOLD", "DONE")
LICENSE_STATUSES = ("DRAFT", "SIGNED", "SUPERSEDED", "VOIDED")
REPORT_STATUSES = ("DRAFT", "SUBMITTED", "VERIFIED", "REJECTED")
SETTLEMENT_STATUSES = ("DRAFT", "FINALIZED")
NOTICE_STATUSES = ("OPEN", "DISCHARGED", "EXECUTED")
PROJECT_STATUSES = ("SCHEDULED", "COMPLETED", "CANCELLED")


def dec(value):
    """Exact Decimal from a JSON number (avoid float artifacts via str())."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def rhu_cents(value):
    """Round half-up to integer cents, returned as int."""
    return int(dec(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------- lookups

def get_production(pid):
    return STORE.productions.get(pid)


def get_theatre(tid):
    return STORE.theatres.get(tid)


def get_booking(bid):
    return STORE.bookings.get(bid)


def company_of_booking(booking):
    prod = STORE.productions.get(booking["production_id"])
    return prod["company_id"] if prod else None


def booking_dt(booking, field):
    return parse_dt(booking[field], field)


def loadout_done_dt(booking):
    """Instant at which load-out completes: run_end + required_loadout_hours."""
    prod = STORE.productions.get(booking["production_id"])
    hours = prod["required_loadout_hours"] if prod else 0
    return booking_dt(booking, "run_end") + timedelta(hours=hours)


def occupancy_window(booking):
    """Half-open occupancy window including load-out buffer."""
    return booking_dt(booking, "loadin_start"), loadout_done_dt(booking)


def windows_overlap(a_start, a_end, b_start, b_end):
    """Half-open overlap; touching boundaries allowed."""
    return a_start < b_end and b_start < a_end


def run_conflicts_project(booking, project):
    """Capital-project conflict: closed-interval contact on the performance run conflicts."""
    rs = booking_dt(booking, "loadin_start")
    re_ = booking_dt(booking, "run_end")
    ws = parse_dt(project["window_start"], "window_start")
    we = parse_dt(project["window_end"], "window_end")
    return ws <= re_ and rs <= we


def conflicting_bookings_for(booking):
    """APPROVED/ACTIVE bookings on the same theatre whose buffered windows overlap."""
    bs, be = occupancy_window(booking)
    out = []
    for other in STORE.bookings.values():
        if other["id"] == booking["id"]:
            continue
        if other["theatre_id"] != booking["theatre_id"]:
            continue
        if other["status"] not in ("APPROVED", "ACTIVE"):
            continue
        os_, oe = occupancy_window(other)
        if windows_overlap(bs, be, os_, oe):
            out.append(other)
    return out


def conflicting_projects_for(booking):
    out = []
    for p in STORE.capital_projects.values():
        if p["theatre_id"] != booking["theatre_id"]:
            continue
        if p["status"] != "SCHEDULED":
            continue
        if run_conflicts_project(booking, p):
            out.append(p)
    return out


def landmark_maintenance_satisfied(booking):
    """For landmark houses: at least one SCHEDULED project disjoint from the run,
    starting within the 365 days before loadin_start or the 365 days after run_end."""
    theatre = STORE.theatres.get(booking["theatre_id"])
    if not theatre or not theatre.get("is_landmark"):
        return True
    ls = booking_dt(booking, "loadin_start")
    re_ = booking_dt(booking, "run_end")
    before_lo = ls - timedelta(days=365)
    after_hi = re_ + timedelta(days=365)
    for p in STORE.capital_projects.values():
        if p["theatre_id"] != booking["theatre_id"] or p["status"] != "SCHEDULED":
            continue
        if run_conflicts_project(booking, p):
            continue
        ws = parse_dt(p["window_start"], "window_start")
        if before_lo <= ws < ls or re_ <= ws <= after_hi:
            return True
    return False


def live_agreement(booking_id):
    """Latest DRAFT/SIGNED agreement for the booking (by created_at, then id)."""
    cands = [a for a in STORE.license_agreements.values()
             if a["booking_id"] == booking_id and a["status"] in ("DRAFT", "SIGNED")]
    if not cands:
        return None
    return sorted(cands, key=lambda a: (a["created_at"], a["id"]))[-1]


def signed_agreement(booking_id):
    cands = [a for a in STORE.license_agreements.values()
             if a["booking_id"] == booking_id and a["status"] == "SIGNED"]
    if not cands:
        return None
    return sorted(cands, key=lambda a: (a["created_at"], a["id"]))[-1]


def open_notice(booking_id):
    for n in STORE.stop_notices.values():
        if n["booking_id"] == booking_id and n["status"] == "OPEN":
            return n
    return None


def latest_crew_assignment(booking_id):
    cands = [c for c in STORE.crew_assignments.values() if c["booking_id"] == booking_id]
    if not cands:
        return None
    # latest by engaged_at; tie-break created_at ASC
    return sorted(cands, key=lambda c: (c["engaged_at"], c["created_at"], c["id"]))[-1]


def qualifying_crew_exists(booking):
    theatre = STORE.theatres.get(booking["theatre_id"])
    if not theatre:
        return False
    minimum = UNION_MIN_CREW[theatre["size_class"]]
    a = latest_crew_assignment(booking["id"])
    return a is not None and a["crew_size"] >= minimum


# ---------------------------------------------------------------- calculations

def compute_order_gross(ticket_count, face_value_cents, dynamic_factor, percent_off):
    raw = (Decimal(ticket_count) * Decimal(face_value_cents)
           * dec(dynamic_factor) * (Decimal(1) - dec(percent_off) / Decimal(100)))
    return rhu_cents(raw)


def weekly_gross(booking_id, week_start_s, week_end_s):
    ws = parse_dt(week_start_s, "week_start")
    we = parse_dt(week_end_s, "week_end")
    total = 0
    for o in STORE.ticket_orders.values():
        if o["booking_id"] != booking_id or o["status"] != "SOLD":
            continue
        pd_ = parse_dt(o["performance_date"], "performance_date")
        if ws <= pd_ < we:
            total += o["computed_gross_cents"]
    return total


def recompute_report(report):
    """Provisional recompute; bumps report version/updated_at."""
    report["gross_cents"] = weekly_gross(report["booking_id"], report["week_start"], report["week_end"])
    touch(report)


def crew_cost_cents_for(booking):
    theatre = STORE.theatres.get(booking["theatre_id"])
    minimum = UNION_MIN_CREW[theatre["size_class"]]
    a = latest_crew_assignment(booking["id"])
    engaged = max(minimum, a["crew_size"]) if a else minimum
    return engaged * CREW_WEEKLY_RATE_CENTS


def royalty_participants_of(production_id):
    return [p for p in STORE.royalty_participants.values() if p["production_id"] == production_id]


def royalty_point_total(production_id):
    return sum(p["royalty_points"] for p in royalty_participants_of(production_id))

# ---------------------------------------------------------------- cascades

def cascade_decline_competitors(approved_booking):
    """Decline overlapping REQUESTED competitors on the same theatre."""
    bs, be = occupancy_window(approved_booking)
    for other in STORE.bookings.values():
        if other["id"] == approved_booking["id"]:
            continue
        if other["theatre_id"] != approved_booking["theatre_id"]:
            continue
        if other["status"] != "REQUESTED":
            continue
        os_, oe = occupancy_window(other)
        if windows_overlap(bs, be, os_, oe):
            other["status"] = "DECLINED"
            other["decline_notice_sent"] = True  # cascade depth 2 marker
            touch(other)


def void_agreements_for(booking_id):
    """Void live agreements; discharges OPEN stop notices (cascade depth 2)."""
    for a in STORE.license_agreements.values():
        if a["booking_id"] == booking_id and a["status"] in ("DRAFT", "SIGNED"):
            a["status"] = "VOIDED"
            touch(a)
    n = open_notice(booking_id)
    if n:
        n["status"] = "DISCHARGED"
        n["consecutive_under_floor_weeks"] = 0
        touch(n)


def _reports_to_recompute(booking_id):
    return [r for r in STORE.weekly_reports.values()
            if r["booking_id"] == booking_id and r["status"] in ("DRAFT", "SUBMITTED")]


def _covering_report(booking_id, performance_date_s):
    pd_ = parse_dt(performance_date_s, "performance_date")
    for r in _reports_to_recompute(booking_id):
        ws = parse_dt(r["week_start"], "week_start")
        we = parse_dt(r["week_end"], "week_end")
        if ws <= pd_ < we:
            yield r


def refund_order(order):
    order["status"] = "REFUNDED"
    order["refunded"] = True
    touch(order)
    for r in _covering_report(order["booking_id"], order["performance_date"]):
        recompute_report(r)


def apply_stop_clause(booking, gross_cents):
    """Apply the stop-clause counter on report verify (only with a live license)."""
    agreement = live_agreement(booking["id"])
    if not agreement:
        return
    floor = agreement["stop_clause_weekly_floor_cents"]
    if gross_cents < floor:
        n = open_notice(booking["id"])
        if not n:
            from response import new_common
            n = new_common()
            n.update({"booking_id": booking["id"],
                      "consecutive_under_floor_weeks": 0,
                      "status": "OPEN"})
            STORE.stop_notices[n["id"]] = n
        # The under-floor week increments the counter, including the week that
        # created the notice (scaffold default 0, then += 1).
        n["consecutive_under_floor_weeks"] += 1
        touch(n)
    else:
        n = open_notice(booking["id"])
        if n:
            n["status"] = "DISCHARGED"
            n["consecutive_under_floor_weeks"] = 0
            touch(n)


def execute_eviction(booking, notice):
    """Booking -> EVICTED; notice -> EXECUTED; future-dated SOLD orders refunded."""
    now = STORE.clock
    booking["status"] = "EVICTED"
    touch(booking)
    notice["status"] = "EXECUTED"
    touch(notice)
    now_dt = parse_dt(now, "clock")
    for o in STORE.ticket_orders.values():
        if o["booking_id"] != booking["id"] or o["status"] != "SOLD":
            continue
        if parse_dt(o["performance_date"], "performance_date") > now_dt:
            refund_order(o)


def release_held_bookings(project):
    """On project completion: held bookings whose load-out fell inside the window -> DONE."""
    ws = parse_dt(project["window_start"], "window_start")
    we = parse_dt(project["window_end"], "window_end")
    for b in STORE.bookings.values():
        if b["status"] != "MAINTENANCE_HOLD" or b["theatre_id"] != project["theatre_id"]:
            continue
        lo = loadout_done_dt(b)
        if ws <= lo < we:
            b["status"] = "DONE"
            touch(b)


def loadout_held_by(booking):
    """The SCHEDULED project window that holds this booking's load-out, or None."""
    theatre = STORE.theatres.get(booking["theatre_id"])
    if not theatre or not theatre.get("is_landmark"):
        return None
    lo = loadout_done_dt(booking)
    for p in STORE.capital_projects.values():
        if p["theatre_id"] != booking["theatre_id"] or p["status"] != "SCHEDULED":
            continue
        ws = parse_dt(p["window_start"], "window_start")
        we = parse_dt(p["window_end"], "window_end")
        if ws <= lo < we:
            return p
    return None


def evaluate_clock_transitions():
    """Evaluate time-driven transitions against the current logical clock."""
    now = parse_dt(STORE.clock, "clock")
    # APPROVED -> ACTIVE once loadin_start reached (only with qualifying crew).
    # Two passes: a single pass can starve a later-created booking when an
    # earlier competitor for the same house fails the crew gate and stays
    # APPROVED, since windows_overlap is a strict inequality.
    pending = [b for b in STORE.bookings.values() if b["status"] == "APPROVED"]
    pending.sort(key=lambda b: (b["created_at"], b["id"]))
    for b in pending:
        if booking_dt(b, "loadin_start") <= now and qualifying_crew_exists(b):
            b["status"] = "ACTIVE"
            touch(b)
    # CLOSED/EVICTED -> MAINTENANCE_HOLD / DONE once load-out completes
    for b in list(STORE.bookings.values()):
        if b["status"] not in ("CLOSED", "EVICTED"):
            continue
        if loadout_done_dt(b) > now:
            continue
        if loadout_held_by(b) is not None:
            b["status"] = "MAINTENANCE_HOLD"
        else:
            b["status"] = "DONE"
        touch(b)

# ---------------------------------------------------------------- settlement

def compute_settlement_amounts(report, booking, agreement, house_expenses_cents):
    """Waterfall: gross -> crew -> fixed -> share -> profit -> pool. Returns a dict."""
    gross = report["gross_cents"]
    crew_cost = crew_cost_cents_for(booking)
    prod_id = booking["production_id"]
    participants = royalty_participants_of(prod_id)
    fixed = sum(p.get("fixed_royalty_cents", 0) for p in participants if not p["pool_eligible"])
    pct_share = rhu_cents(THEATRE_GROSS_PCT * Decimal(gross))
    theatre_share = max(agreement["weekly_rent_cents"], pct_share)
    profit = gross - house_expenses_cents - crew_cost - theatre_share - fixed
    pool = rhu_cents(POOL_SHARE_PCT * Decimal(profit)) if profit > 0 else 0
    return {
        "crew_cost_cents": crew_cost,
        "theatre_share_cents": theatre_share,
        "weekly_operating_profit_cents": profit,
        "royalty_pool_cents": pool,
    }


def pool_payouts(production_id, royalty_pool_cents):
    """Per pool participant: floor(pool * points / total_pool_points); remainder cents
    allocated one at a time ranked by points DESC, tie-break created_at ASC."""
    participants = [p for p in royalty_participants_of(production_id) if p["pool_eligible"]]
    total_points = sum(p["royalty_points"] for p in participants)
    if royalty_pool_cents <= 0 or total_points <= 0 or not participants:
        return {}
    payouts = {}
    allocated = 0
    for p in participants:
        pay = (royalty_pool_cents * p["royalty_points"]) // total_points
        payouts[p["id"]] = pay
        allocated += pay
    remainder = royalty_pool_cents - allocated
    ranked = sorted(participants, key=lambda p: (-p["royalty_points"], p["created_at"], p["id"]))
    i = 0
    while remainder > 0:
        payouts[ranked[i % len(ranked)]["id"]] += 1
        remainder -= 1
        i += 1
    return payouts
