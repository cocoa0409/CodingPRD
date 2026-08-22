"""Derived fields and calculation rules (PRD 2.9, 2.10 and section 3).

Every derived value is rebuilt from the stored facts rather than incrementally
patched: custody buckets by replaying the whole chain, the district ledger from
the full set of its lots, a window's breach accounting from the full set of its
reports, and a proctor's certification standing from its training record and the
logical clock.
"""

from decimal import ROUND_HALF_UP, Decimal

from db import db, now, touch
from timeutil import plus_days

# --------------------------------------------------------------------------
# Global constants
# --------------------------------------------------------------------------
SESSION_START_GRACE_MINUTES = 30
ROOM_TURNOVER_BUFFER_MINUTES = 15
MAKEUP_EXTENSION_DAYS = 7
MAX_RETURN_CYCLES = 2

MIN_QUIZ_SCORE_PCT = Decimal("80.0")
TRAINING_VALID_DAYS = 365

SEPARATE_SETTING_SEAT_COST = 2
PROCTOR_SPAN_FREE = 2
PROCTOR_SPAN_DIVISOR = 3
PROCTOR_SPAN_SEAT_COST = 4

UNIT_REPLACEMENT_COST_CENTS = 1250
INTACT_SEAL_MULTIPLIER = Decimal("1.25")
BROKEN_SEAL_MULTIPLIER = Decimal("1.75")
WAIVER_TIER_1_MIN_CENTS = 5000
WAIVER_TIER_2_MIN_CENTS = 20000

ACCOMMODATION_CATALOG = {
    "EXTENDED_TIME": {"tier": "STANDARD", "separate_setting": False},
    "SMALL_GROUP": {"tier": "STANDARD", "separate_setting": True},
    "ASSISTIVE_TECH": {"tier": "STANDARD", "separate_setting": False},
    "SEPARATE_ROOM": {"tier": "SPECIALIZED", "separate_setting": True},
    "READ_ALOUD": {"tier": "SPECIALIZED", "separate_setting": False},
    "SCRIBE": {"tier": "SPECIALIZED", "separate_setting": False},
    "BRAILLE_FORM": {"tier": "SPECIALIZED", "separate_setting": True},
}

OPEN_BREACH_STATUSES = ("SUBMITTED", "UNDER_REVIEW", "RETURNED_FOR_INFO")


# --------------------------------------------------------------------------
# Rounding helpers (PRD 2.9)
# --------------------------------------------------------------------------
def round_half_up(value, places=0):
    exponent = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(exponent, rounding=ROUND_HALF_UP)


def round_cents(value):
    return int(round_half_up(value, 0))


def one_decimal(value):
    return float(round_half_up(value, 1))


def ceil_div(numerator, divisor):
    """Ceiling of an exact rational quotient, computed in integers."""
    return -((-numerator) // divisor)


# --------------------------------------------------------------------------
# Collection helpers
# --------------------------------------------------------------------------
def sessions_of_window(window_id):
    return [s for s in db.sessions.values() if s["window_id"] == window_id]


def registrations_of_session(session_id):
    return [r for r in db.registrations.values() if r["session_id"] == session_id]


def registrations_of_window(window_id):
    session_ids = {s["id"] for s in db.sessions.values() if s["window_id"] == window_id}
    return [r for r in db.registrations.values() if r["session_id"] in session_ids]


def lots_of_window(window_id):
    return [lot for lot in db.lots.values() if lot["window_id"] == window_id]


def custody_events_of_lot(lot_id):
    events = [e for e in db.custody_events.values() if e["material_lot_id"] == lot_id]
    events.sort(key=lambda e: e["sequence_no"])
    return events


def session_of_registration(registration):
    return db.sessions.get(registration["session_id"])


def window_of_session(session):
    return db.windows.get(session["window_id"])


def window_of_registration(registration):
    session = session_of_registration(registration)
    return window_of_session(session) if session else None


def window_of_report(report):
    """A report is scoped to a window through its session or its material lot."""
    if report.get("session_id"):
        session = db.sessions.get(report["session_id"])
        if session:
            return db.windows.get(session["window_id"])
    if report.get("material_lot_id"):
        lot = db.lots.get(report["material_lot_id"])
        if lot:
            return db.windows.get(lot["window_id"])
    return None


def active_affidavit(proctor_id, window_id):
    for affidavit in db.affidavits.values():
        if (
            affidavit["proctor_id"] == proctor_id
            and affidavit["window_id"] == window_id
            and affidavit["status"] == "ACTIVE"
        ):
            return affidavit
    return None


# --------------------------------------------------------------------------
# Proctor certification standing (PRD 3.1)
# --------------------------------------------------------------------------
def certification_status(proctor):
    if proctor.get("revoked_at") is not None:
        return "REVOKED"
    if proctor.get("training_status") != "PASSED":
        return "NOT_CERTIFIED"
    completed = proctor.get("training_completed_at")
    if completed is None:
        return "NOT_CERTIFIED"
    if now() >= plus_days(completed, TRAINING_VALID_DAYS):
        return "EXPIRED"
    return "CERTIFIED"


def quiz_passes(score_pct):
    return round_half_up(Decimal(str(score_pct)), 1) >= MIN_QUIZ_SCORE_PCT


# --------------------------------------------------------------------------
# Seat pressure (PRD 3.4)
# --------------------------------------------------------------------------
def needs_separate_setting(codes):
    return any(ACCOMMODATION_CATALOG[code]["separate_setting"] for code in codes if code in ACCOMMODATION_CATALOG)


def seats_required_for(codes):
    return 1 + (SEPARATE_SETTING_SEAT_COST if needs_separate_setting(codes) else 0)


def _supply(session, separate_setting_count):
    school = db.schools.get(session["school_id"])
    ceiling = session["seat_capacity"]
    if school is not None:
        ceiling = min(ceiling, school["max_concurrent_seats"])
    span = max(0, ceil_div(separate_setting_count - PROCTOR_SPAN_FREE, PROCTOR_SPAN_DIVISOR))
    penalty = span * PROCTOR_SPAN_SEAT_COST
    return max(0, ceiling - penalty)


def seat_pressure_for(session, live_registrations):
    """Demand and supply over an explicit roster (used for prospective checks)."""
    separate_setting_count = sum(
        1 for reg in live_registrations if needs_separate_setting(reg["accommodation_codes"])
    )
    seats_consumed = sum(reg["seats_required"] for reg in live_registrations)
    return {
        "separate_setting_count": separate_setting_count,
        "seats_consumed": seats_consumed,
        "effective_seat_capacity": _supply(session, separate_setting_count),
    }


def live_registrations(session_id):
    return [
        reg
        for reg in registrations_of_session(session_id)
        if reg["attendance_status"] != "WITHDRAWN"
    ]


def recompute_seat_pressure(session):
    pressure = seat_pressure_for(session, live_registrations(session["id"]))
    changed = any(session.get(field) != value for field, value in pressure.items())
    session.update(pressure)
    if changed:
        touch(session)
    return pressure


# --------------------------------------------------------------------------
# Accommodation review routing (PRD 3.4)
# --------------------------------------------------------------------------
def review_routing(codes):
    if not codes:
        return "NONE"
    if any(ACCOMMODATION_CATALOG[code]["tier"] == "SPECIALIZED" for code in codes):
        return "REQUESTED"
    return "APPROVED"


# --------------------------------------------------------------------------
# Chain of custody replay (PRD 3.5)
# --------------------------------------------------------------------------
_BUCKET_MOVES = {
    "RECEIPT": (None, "at_district"),
    "TRANSFER_TO_SCHOOL": ("at_district", "at_school"),
    "SESSION_CHECKOUT": ("at_school", "in_sessions"),
    "SESSION_CHECKIN": ("in_sessions", "at_school"),
    "RETURN_TO_DISTRICT": ("at_school", "at_district"),
    "DESTRUCTION": ("at_district", "destroyed"),
}


def replay_chain(lot):
    buckets = {"at_district": 0, "at_school": 0, "in_sessions": 0, "destroyed": 0}
    for event in custody_events_of_lot(lot["id"]):
        source, target = _BUCKET_MOVES[event["event_type"]]
        if source is not None:
            buckets[source] -= event["quantity"]
        buckets[target] += event["quantity"]
        event["chain_balance_after"] = sum(buckets.values())
    lot["quantity_at_district"] = buckets["at_district"]
    lot["quantity_at_school"] = buckets["at_school"]
    lot["quantity_in_sessions"] = buckets["in_sessions"]
    lot["quantity_destroyed"] = buckets["destroyed"]
    lot["chain_accounted_count"] = buckets["at_district"] + buckets["destroyed"]
    return buckets


def recompute_session_materials(session):
    checked_out = 0
    checked_in = 0
    for event in db.custody_events.values():
        if event.get("session_id") != session["id"]:
            continue
        if event["event_type"] == "SESSION_CHECKOUT":
            checked_out += event["quantity"]
        elif event["event_type"] == "SESSION_CHECKIN":
            checked_in += event["quantity"]
    changed = (
        session["materials_checked_out"] != checked_out
        or session["materials_checked_in"] != checked_in
    )
    session["materials_checked_out"] = checked_out
    session["materials_checked_in"] = checked_in
    if changed:
        touch(session)


def outstanding_booklets(session):
    return session["materials_checked_out"] - session["materials_checked_in"]


# --------------------------------------------------------------------------
# Replacement charges and the district ledger (PRD 3.5)
# --------------------------------------------------------------------------
def lot_replacement_charge(lot):
    multiplier = BROKEN_SEAL_MULTIPLIER if lot["seal_broken_count"] > 0 else INTACT_SEAL_MULTIPLIER
    gross = Decimal(lot["missing_count"]) * Decimal(UNIT_REPLACEMENT_COST_CENTS) * multiplier
    return round_cents(gross)


def waiver_pct_for(gross):
    if gross < WAIVER_TIER_1_MIN_CENTS:
        return Decimal("0.00")
    if gross < WAIVER_TIER_2_MIN_CENTS:
        return Decimal("0.10")
    return Decimal("0.20")


def recompute_district_ledger(district):
    """Round per lot first, then sum the already-rounded amounts."""
    if district is None:
        return
    charged = [
        lot
        for lot in db.lots.values()
        if lot["district_id"] == district["id"]
        and lot["status"] == "DISCREPANT"
        and not lot["charge_reversed"]
    ]
    total = sum(lot["replacement_charge_cents"] for lot in charged)
    waiver = round_cents(Decimal(total) * waiver_pct_for(total))
    assessment = total - waiver
    changed = (
        district["replacement_charge_total_cents"] != total
        or district["security_assessment_cents"] != assessment
        or district["open_discrepancy_count"] != len(charged)
    )
    district["replacement_charge_total_cents"] = total
    district["security_assessment_cents"] = assessment
    district["open_discrepancy_count"] = len(charged)
    if changed:
        touch(district)


# --------------------------------------------------------------------------
# Window breach accounting (PRD 3.7)
# --------------------------------------------------------------------------
def recompute_window_breach(window):
    if window is None:
        return
    count = 0
    for report in db.reports.values():
        if report["category"] != "SECURITY_BREACH":
            continue
        if report["status"] not in OPEN_BREACH_STATUSES:
            continue
        scoped = window_of_report(report)
        if scoped is not None and scoped["id"] == window["id"]:
            count += 1
    hold = count > 0
    changed = window["open_breach_count"] != count or window["security_hold"] != hold
    window["open_breach_count"] = count
    window["security_hold"] = hold
    if changed:
        touch(window)


# --------------------------------------------------------------------------
# Participation (PRD 3.8, 3.9)
# --------------------------------------------------------------------------
PROVISIONAL_SESSION_STATUSES = ("SCHEDULED", "ACTIVE", "CLOSED")
PROVISIONAL_ATTENDANCE = ("PENDING", "PRESENT", "ABSENT", "EXCUSED")
FINAL_SESSION_STATUSES = ("SCHEDULED", "ACTIVE", "CLOSED", "CANCELLED", "INVALIDATED")
FINAL_ATTENDANCE = ("PENDING", "PRESENT", "ABSENT", "EXCUSED", "WITHDRAWN")


def _participation(window, session_statuses, attendance_statuses, numerator_test):
    denominator_ids = set()
    numerator_ids = set()
    for registration in registrations_of_window(window["id"]):
        session = session_of_registration(registration)
        if session is None or session["status"] not in session_statuses:
            continue
        if registration["attendance_status"] not in attendance_statuses:
            continue
        denominator_ids.add(registration["student_state_id"])
        if numerator_test(registration):
            numerator_ids.add(registration["student_state_id"])
    denominator = len(denominator_ids)
    numerator = len(numerator_ids)
    if denominator == 0:
        rate = 0.0
    else:
        rate = one_decimal(Decimal(numerator) * Decimal(100) / Decimal(denominator))
    return rate, denominator, numerator


def participation_provisional(window):
    return _participation(
        window,
        PROVISIONAL_SESSION_STATUSES,
        PROVISIONAL_ATTENDANCE,
        lambda reg: reg["attendance_status"] == "PRESENT",
    )


def participation_final(window):
    return _participation(
        window,
        FINAL_SESSION_STATUSES,
        FINAL_ATTENDANCE,
        lambda reg: reg["score_status"] == "FINAL",
    )
