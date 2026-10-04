"""Shared business helpers: lookups, derived posture, demand projections, scoring."""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import db
import errors
from db import iso_z
from errors import ApiError

# --- constants --------------------------------------------------------------
PRE_SHOW_MIN_MINUTES = 10
PRE_SHOW_MAX_MINUTES = 40
CLUSTER_WINDOW_MINUTES = 120
CLUSTER_ANCHOR_LEAD_MINUTES = 60
ENTREE_DEADLINE_FRACTION = Decimal("0.75")
SERVICE_WINDOW_LEAD_MINUTES = 10
IN_KITCHEN_LEAD_MINUTES = 30
MINUTES_FROM_ENTREE_TO_START = 30
READY_LEAD_MINUTES = 30
DAILY_SECTION_CAP = 3
SERVO_BUFFER_MINUTES = 15
SERVER_QUALITY_WINDOW_DAYS = 30
AUTO_COMP_REFUND_PCT = Decimal("0.3")
THEME_DISCOUNT_PCT = Decimal("0.05")
ALLERGY_WEIGHT = 3
LARGE_PARTY_WEIGHT = 2
LARGE_PARTY_UNITS = 4
EJECTION_MULTIPLIER = Decimal("2.0")
REFUND_MULTIPLIER = Decimal("1.5")
CANCEL_MULTIPLIER = Decimal("0.5")
STRIKE_WINDOW_DAYS = 1
BASE_POINTS = {"A": 1, "B": 3, "C": 6}
UNRATED_POINTS = 2
GRADE_WEIGHT = {"A": Decimal("1.0"), "B": Decimal("0.8"), "C": Decimal("0.5")}
PENALTY_PCT_PER_LOW_ASSIGNMENT = Decimal("0.05")

ACTIVE_KITCHEN_TICKET_STATUSES = {"QUEUED", "PREPARING"}
DEMAND_SLIP_STATUSES = {"PLACED", "ACCEPTED", "PREPARING"}
CLUSTER_SHOWTIME_STATUSES = {"SCHEDULED", "DINING_OPEN", "SERVICE", "RUNNING"}
LIVE_SHOWTIME_STATUSES = {"DINING_OPEN", "SERVICE", "RUNNING"}
NON_TERMINAL_ASSIGNMENT_STATUSES = {"DRAFT", "ACTIVE", "REASSIGNMENT_PENDING"}
STAGE_ORDER = {"WARNING": 1, "FINAL_WARNING": 2, "EJECTION": 3}


def round_half_up(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def ceil_div_minutes(points, rate):
    if rate <= 0:
        rate = 1
    return -((-int(points)) // int(rate))


def lookup(collection, row_id, error_id):
    row = getattr(db.db, collection).get(row_id)
    if row is None:
        raise ApiError(error_id)
    return row


def auditorium(row_id):
    return lookup("auditoriums", row_id, errors.ERR_AUDITORIUM_NOT_FOUND)


def showtime(row_id):
    return lookup("showtimes", row_id, errors.ERR_SHOWTIME_NOT_FOUND)


def menu_item(row_id):
    return lookup("menu_items", row_id, errors.ERR_MENU_ITEM_NOT_FOUND)


def programming_event(row_id):
    return lookup("programming_events", row_id, errors.ERR_PROGRAMMING_EVENT_NOT_FOUND)


def themed_menu_item(row_id):
    return lookup("themed_menu_items", row_id, errors.ERR_THEMED_MENU_ITEM_NOT_FOUND)


def server(row_id):
    return lookup("servers", row_id, errors.ERR_SERVER_NOT_FOUND)


def section_assignment(row_id):
    return lookup("section_assignments", row_id, errors.ERR_SECTION_ASSIGNMENT_NOT_FOUND)


def order_slip(row_id):
    return lookup("order_slips", row_id, errors.ERR_ORDER_SLIP_NOT_FOUND)


def check(row_id):
    return lookup("checks", row_id, errors.ERR_CHECK_NOT_FOUND)


def kitchen_ticket(row_id):
    return lookup("kitchen_tickets", row_id, errors.ERR_KITCHEN_TICKET_NOT_FOUND)


def disturbance(row_id):
    return lookup("disturbance_events", row_id, errors.ERR_DISTURBANCE_EVENT_NOT_FOUND)


def touch(row):
    row["updated_at"] = db.db.now


def bump_version(row):
    row["version"] = row.get("version", 1) + 1


# --- derived showtime axes --------------------------------------------------

def recompute_service_mode(st):
    now = db.db.now
    lead = st["start_at_utc"] - timedelta(minutes=SERVICE_WINDOW_LEAD_MINUTES)
    if now < lead:
        st["service_mode"] = "PRE_SHOW"
    elif now > st["entree_ready_deadline_utc"]:
        st["service_mode"] = "DARK_PERIOD"
    else:
        st["service_mode"] = "IN_KITCHEN"
    return st["service_mode"]


def members_of(aud_id):
    return [s for s in db.db.sorted_rows("showtimes") if s["auditorium_id"] == aud_id]


def derive_build_phase(members):
    now = db.db.now
    scheduled = [s for s in members if s["status"] == "SCHEDULED"]
    if not scheduled:
        return "EMPTY"
    if any(s["dining_open_at_utc"] <= now for s in scheduled):
        return "READY"
    if any(now <= s["dining_open_at_utc"] < now + timedelta(minutes=READY_LEAD_MINUTES)
           for s in scheduled):
        return "NEARLY_READY"
    return "SETUP"


def derive_auditorium_status(members):
    if any(s["mode"] == "DINING_OPEN" and s["status"] in LIVE_SHOWTIME_STATUSES
           for s in members):
        return "LIVE"
    if any(s["mode"] == "DINING_CLOSED" and s["status"] == "SCHEDULED" for s in members):
        return "TURNOVER"
    return "DARK"


def reconcile_auditorium(aud):
    """Re-derive the posture axes; returns True when the stored status changed."""
    members = members_of(aud["id"])
    new_status = derive_auditorium_status(members)
    changed = new_status != aud["status"]
    aud["status"] = new_status
    aud["service_posture"] = new_status
    aud["build_phase"] = derive_build_phase(members)
    openers = [s["start_at_utc"] for s in members if s["mode"] == "DINING_OPEN"]
    aud["last_showtime_cluster_start_utc"] = min(openers) if openers else None
    touch(aud)
    return changed


def note_cluster_opening(aud, st):
    """Record the instant the room's cluster opened, for §3.8's liability key."""
    if aud.get("refund_key_instant") is None:
        aud["refund_key_instant"] = st["start_at_utc"]


def reconcile_all_auditoriums():
    for aud in db.db.sorted_rows("auditoriums"):
        reconcile_auditorium(aud)


def recompute_all_service_modes():
    for st in db.db.sorted_rows("showtimes"):
        recompute_service_mode(st)


def next_scheduled_dining_open(aud_id):
    candidates = [s["dining_open_at_utc"] for s in members_of(aud_id)
                  if s["status"] == "SCHEDULED"]
    return min(candidates) if candidates else None


# --- kitchen demand projections --------------------------------------------

def entree_slips(st):
    return [sl for sl in db.db.sorted_rows("order_slips")
            if sl["showtime_id"] == st["id"] and sl["channel"] == "ENTREE"]


def point_cost(slip):
    total = 0
    for line in slip["resolved_lines"]:
        item = db.db.menu_items.get(line["menu_item_id"])
        prep = item["prep_minutes"] if item else 1
        total += line["quantity"] * prep
    return total


def cluster_members(st):
    anchor = st["start_at_utc"] - timedelta(minutes=CLUSTER_ANCHOR_LEAD_MINUTES)
    out = []
    for other in members_of(st["auditorium_id"]):
        if other["status"] not in CLUSTER_SHOWTIME_STATUSES:
            continue
        if abs((other["start_at_utc"] - anchor).total_seconds()) <= \
                CLUSTER_WINDOW_MINUTES * 60:
            out.append(other)
    return out


def kitchen_load_projection(st, variant=None):
    if variant is None:
        variant = "wave_projection" if st["status"] in ("SCHEDULED", "DINING_OPEN") \
            else "final_projection"
    members = cluster_members(st)
    if variant == "wave_projection":
        cohort = [x for x in members if x["start_at_utc"] <= st["start_at_utc"]]
        total = 0
        for x in cohort:
            for sl in entree_slips(x):
                if sl["status"] in DEMAND_SLIP_STATUSES:
                    total += point_cost(sl)
        return total
    total = 0
    for x in members:
        for sl in entree_slips(x):
            if sl["status"] in DEMAND_SLIP_STATUSES:
                total += 1
    return total


def kitchen_load_rollup(st):
    total = 0
    for sl in entree_slips(st):
        if sl["status"] in DEMAND_SLIP_STATUSES:
            total += point_cost(sl)
    return total


def beverage_load_points(st):
    """Summed point_cost of the showtime's OPEN hot_line kitchen tickets."""
    total = 0
    for ticket in db.db.sorted_rows("kitchen_tickets"):
        if ticket["showtime_id"] != st["id"]:
            continue
        if ticket["station"] != "hot_line":
            continue
        if ticket["status"] in ACTIVE_KITCHEN_TICKET_STATUSES:
            total += ticket["point_cost"]
    return total


def worse(a, b):
    rank = {"NORMAL": 0, "LATE": 1, "BLOCKED": 2}
    return a if rank.get(a, 0) >= rank.get(b, 0) else b


def entree_band(st):
    aud = auditorium(st["auditorium_id"])
    now = db.db.now
    deadline = st["entree_ready_deadline_utc"]
    rate = aud["kitchen_point_rate"] or 1
    members = cluster_members(st)
    if not members:
        # No cluster showtime stands in a countable state, so no cold-line work
        # is pending and there is nothing to fit before the deadline.
        return "NORMAL", deadline
    load = kitchen_load_projection(st, "wave_projection")
    latest = deadline - timedelta(minutes=ceil_div_minutes(load, rate))
    if now <= latest:
        return "NORMAL", latest
    if now <= deadline:
        return "LATE", latest
    return "BLOCKED", latest


def beverage_band(st):
    aud = auditorium(st["auditorium_id"])
    now = db.db.now
    deadline = st["entree_ready_deadline_utc"]
    alcove = aud["alcove_point_rate"] or 1
    load = beverage_load_points(st)
    latest = deadline - timedelta(minutes=ceil_div_minutes(load, alcove))
    if now <= latest:
        return "NORMAL", latest
    if now <= deadline:
        return "LATE", latest
    return "BLOCKED", latest


def utilization_band(st):
    aud = auditorium(st["auditorium_id"])
    now = db.db.now
    deadline = st["entree_ready_deadline_utc"]
    rate = aud["kitchen_point_rate"] or 1
    load = kitchen_load_projection(st, "wave_projection")
    whole_minutes = int((deadline - now).total_seconds() // 60)
    divisor = max(1, rate * whole_minutes)
    load_pct = (load * 100) // divisor
    if load_pct > 100:
        return "BLOCKED", load_pct
    if load_pct >= 90:
        return "LATE", load_pct
    return "NORMAL", load_pct


def capacity_snapshot(st):
    """The dining order capacity snapshot read model.

    PRD 3.4 names the verdict field `capacity_band` verbatim: "the showtime's
    `capacity_band` must be NORMAL for the order to be placed". The showtime's
    window/projection axis (`mode`) and the bound variant are reported
    separately.
    """
    e_band, e_latest = entree_band(st)
    b_band, b_latest = beverage_band(st)
    t_band, load_pct = utilization_band(st)
    entry_stage = len([sl for sl in db.db.sorted_rows("order_slips")
                       if sl["showtime_id"] == st["id"] and sl["status"] == "ACCEPTED"])

    # PRD §3.5: which variant runs "is a function of how far the showtime has
    # travelled". The base wave variant is the pre-show gate; the final variant is
    # "the one written into the projection snapshot once the showtime has left the
    # seating phases", measured over the whole cluster.
    if st["status"] not in ("SCHEDULED", "DINING_OPEN"):
        capacity_band = "BLOCKED"
        variant = "final_projection"
    else:
        capacity_band = worse(e_band, t_band)
        variant = "wave_projection"
    load = kitchen_load_projection(st, variant)

    return {
        "capacity_band": capacity_band,
        "entree_load_points": load,
        "entree_latest_accept_at_utc": iso_z(e_latest),
        "beverage_load_points": beverage_load_points(st),
        "beverage_latest_accept_at_utc": iso_z(b_latest),
        "entry_stage": entry_stage,
        "load_pct": load_pct,
        "projection_variant": variant,
    }


def band_for_slip(st, channel):
    """Steps 1-6 of dining_order_capacity_snapshot for a slip of this channel."""
    e_band, _ = entree_band(st)
    candidate = e_band
    if channel == "BEVERAGE":
        b_band, _ = beverage_band(st)
        candidate = worse(candidate, b_band)
    if st["status"] not in ("SCHEDULED", "DINING_OPEN"):
        return "BLOCKED"
    t_band, _ = utilization_band(st)
    return worse(candidate, t_band)


# --- cold-line sequencing ---------------------------------------------------

def ticket_priority_score(slip, ticket):
    allergy = 1 if ticket.get("allergen_substitution") else 0
    units = sum(line["quantity"] for line in slip["resolved_lines"])
    large = 1 if units >= LARGE_PARTY_UNITS else 0
    return (allergy * ALLERGY_WEIGHT) + (large * LARGE_PARTY_WEIGHT)


def cold_line_cohort(st):
    out = []
    for ticket in db.db.sorted_rows("kitchen_tickets"):
        if ticket["showtime_id"] != st["id"]:
            continue
        if ticket["station"] != "cold_line":
            continue
        if ticket["status"] not in ACTIVE_KITCHEN_TICKET_STATUSES:
            continue
        out.append(ticket)
    return out


def hot_line_cohort(st):
    out = []
    for ticket in db.db.sorted_rows("kitchen_tickets"):
        if ticket["showtime_id"] != st["id"]:
            continue
        if ticket["station"] != "hot_line":
            continue
        if ticket["status"] not in ACTIVE_KITCHEN_TICKET_STATUSES:
            continue
        out.append(ticket)
    return out


def resequence(st):
    """Re-derive sequence_position and fire_at_utc for both stations."""
    aud = auditorium(st["auditorium_id"])
    cold = cold_line_cohort(st)
    ordered = sorted(cold, key=lambda t: (
        -ticket_priority_score(db.db.order_slips[t["order_slip_id"]], t),
        db.db.order.get(t["id"], 0)))
    anchor = st["start_at_utc"] - timedelta(minutes=MINUTES_FROM_ENTREE_TO_START)
    cursor = anchor
    for index, ticket in enumerate(ordered):
        ticket["sequence_position"] = index + 1
        ticket["fire_at_utc"] = cursor
        ticket["projected_delivery_at_utc"] = cursor + timedelta(
            minutes=ceil_div_minutes(ticket["point_cost"], aud["kitchen_point_rate"]))
        touch(ticket)
        cursor = cursor + timedelta(
            minutes=ceil_div_minutes(ticket["point_cost"], aud["kitchen_point_rate"]))
    for ticket in db.db.sorted_rows("kitchen_tickets"):
        if ticket["showtime_id"] == st["id"] and ticket["station"] == "cold_line" \
                and ticket["status"] not in ACTIVE_KITCHEN_TICKET_STATUSES:
            ticket["sequence_position"] = 0
    # Hot-line tickets are never numbered: sequence_position is the cold-line
    # fire ordering only. Their elapsed time is still laid out from the anchor.
    for ticket in hot_line_cohort(st):
        ticket["sequence_position"] = 0
        ticket["projected_delivery_at_utc"] = ticket["fire_at_utc"] + timedelta(
            minutes=ceil_div_minutes(ticket["point_cost"], aud["alcove_point_rate"]))
        touch(ticket)
    return ordered


def refresh_ticket(ticket):
    st = db.db.showtimes.get(ticket["showtime_id"])
    if st is None:
        return
    aud = auditorium(st["auditorium_id"])
    if ticket["station"] == "cold_line":
        resequence(st)
    else:
        ticket["projected_delivery_at_utc"] = ticket["fire_at_utc"] + timedelta(
            minutes=ceil_div_minutes(ticket["point_cost"], aud["alcove_point_rate"]))
        touch(ticket)


# --- server side accounting -------------------------------------------------

def service_day(row):
    created = row.get("created_at")
    if created is None:
        return None
    return created.date()


def projected_load(srv):
    day = db.db.now.date()
    count = 0
    for a in db.db.sorted_rows("section_assignments"):
        if a["server_id"] != srv["id"]:
            continue
        if service_day(a) != day:
            continue
        if a["status"] == "CANCELLED":
            continue
        count += 1
    return count


def final_load(srv):
    day = db.db.now.date()
    count = 0
    for a in db.db.sorted_rows("section_assignments"):
        if a["server_id"] != srv["id"]:
            continue
        if service_day(a) != day:
            continue
        if a["status"] == "COMPLETED":
            count += 1
    return count


def rollup_provisional(srv):
    total = 0
    for a in db.db.sorted_rows("section_assignments"):
        if a["server_id"] != srv["id"]:
            continue
        for sl in db.db.sorted_rows("order_slips"):
            if sl["section_assignment_id"] != a["id"]:
                continue
            tab = db.db.checks.get(sl["id"])
            if tab is None:
                continue
            if is_ejected_slip(sl) or tab["status"] in ("OPEN", "PARTIALLY_REFUNDED"):
                total += tab["original_cents"]
    return total


def is_ejected_slip(slip):
    for ev in db.db.sorted_rows("disturbance_events"):
        if ev["order_slip_id"] == slip["id"] and ev["stage"] == "EJECTION" \
                and ev["ejected_occupant_id"] is not None:
            return True
    return False


def assignment_quality_window(srv):
    cutoff = db.db.now - timedelta(days=SERVER_QUALITY_WINDOW_DAYS)
    window = []
    for entry in srv["ratings"]:
        a = db.db.section_assignments.get(entry["assignment_id"])
        if a is None:
            continue
        if a["created_at"] >= cutoff:
            window.append(entry)
    return window


def server_quality_index(srv):
    window = assignment_quality_window(srv)
    raw = sum(GRADE_WEIGHT.get(e["rating_grade"], Decimal("0")) for e in window) / \
        Decimal(max(1, len(window)))
    cutoff = db.db.now - timedelta(days=SERVER_QUALITY_WINDOW_DAYS)
    low = 0
    for a in db.db.sorted_rows("section_assignments"):
        if a["server_id"] != srv["id"]:
            continue
        if a["assignment_points"] >= 5 and a["created_at"] >= cutoff:
            low += 1
    penalty = PENALTY_PCT_PER_LOW_ASSIGNMENT * low
    value = raw - Decimal(penalty)
    if value < 0:
        value = Decimal("0")
    return float(value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def refresh_server(srv):
    srv["shift_load_projected"] = projected_load(srv)
    srv["shift_load_final"] = final_load(srv)
    srv["rollup_provisional_cents"] = rollup_provisional(srv)
    touch(srv)
    return srv


def assignment_points(a, cancel=False):
    grade = a.get("rating_grade")
    base = Decimal(BASE_POINTS.get(grade, UNRATED_POINTS) if grade else UNRATED_POINTS)
    st = db.db.showtimes.get(a["showtime_id"])
    ejection_mult = EJECTION_MULTIPLIER if showtime_has_ejection_refund(st) else Decimal("1.0")
    refund_mult = REFUND_MULTIPLIER if assignment_has_compensation(a) else Decimal("1.0")
    points = base * ejection_mult * refund_mult
    if cancel:
        points = points * CANCEL_MULTIPLIER
    return round_half_up(points)


def showtime_has_ejection_refund(st):
    if st is None:
        return False
    for sl in db.db.sorted_rows("order_slips"):
        if sl["showtime_id"] != st["id"]:
            continue
        tab = db.db.checks.get(sl["id"])
        if tab is None:
            continue
        if tab["reason_code"] in ("EJECTION_NO_TALKING", "EJECTION_NO_TEXTING"):
            return True
    return False


def assignment_has_compensation(a):
    for sl in db.db.sorted_rows("order_slips"):
        if sl["section_assignment_id"] != a["id"]:
            continue
        if is_ejected_slip(sl):
            return True
        tab = db.db.checks.get(sl["id"])
        if tab is not None and tab["reason_code"] in ("SERVICE_DELAY", "SERVICE_COMP_FAILURE"):
            return True
    return False


def server_has_high_cancel(srv):
    for a in db.db.sorted_rows("section_assignments"):
        if a["server_id"] != srv["id"]:
            continue
        if a["status"] == "CANCELLED" and a["assignment_points"] >= 5:
            return True
    return False


def refresh_server_status(srv):
    """Recompute roster posture from the server's assignment record.

    PRD 3.7: a server whose cancelled assignment scores five or more points is
    taken out of rotation and placed in the penalised roster state until the
    penalty is cleared. Any other server is ACTIVE and in rotation.
    """
    if server_has_high_cancel(srv):
        srv["in_rotation"] = False
        srv["status"] = "PENALIZED"
    else:
        srv["in_rotation"] = True
        srv["status"] = "ACTIVE"
    touch(srv)


def refresh_all_servers():
    for srv in db.db.sorted_rows("servers"):
        refresh_server(srv)