"""The §1.4 / §2.11 validation ladders: clinical safety, fiscal, temporal."""

from datetime import timedelta

from core import (
    db, fail, parse_iso, get_clock, local_minute_of_day,
    COURIER_CUTOFF_BEFORE_DISPATCH_MINUTES, COURIER_MAX_SPECIMENS_PER_RUN,
    DRAW_HOLD_MINUTES_DEFAULT,
)
from domain import (
    credentialed_for, resolving_staff, fasting_deadline_for,
    specimen_stability_deadline,
)


# ---------------------------------------------------------------------------
# Priority 5 — clinical safety (sub-order 5a..5f)
# ---------------------------------------------------------------------------
def safety_pediatric_center_capable(order, center):
    if order["collection_mode"] == "PEDIATRIC" and not center.get("pediatric_capable"):
        fail("ERR_PEDIATRIC_CENTER_NOT_CAPABLE")


def safety_pediatric_draw_floor(order, center):
    if not order.get("patient_is_pediatric"):
        return
    for s in db.specimens.values():
        if s["test_order_id"] != order["id"]:
            continue
        row = _req_for(order, s["tube_code"])
        if row is None:
            continue
        if float(s["volume_ml"]) < float(row["min_volume_ml"]):
            fail("ERR_PEDIATRIC_DRAW_FLOOR_VIOLATION")


def safety_order_of_draw(order):
    rows = [s for s in db.specimens.values() if s["test_order_id"] == order["id"]]
    # created_at ascending is the only tie-break; id is never consulted.
    rows.sort(key=lambda s: s["created_at"])
    prev = None
    for s in rows:
        if prev is not None and s["order_of_draw"] < prev:
            fail("ERR_ORDER_OF_DRAW_VIOLATION")
        prev = s["order_of_draw"]


def safety_staff_credential(order, center):
    if not resolving_staff(center["id"], order["collection_mode"]):
        fail("ERR_STAFF_CREDENTIAL_INSUFFICIENT")


def safety_collection_mode(requested, order):
    if requested is not None and requested != order["collection_mode"]:
        fail("ERR_COLLECTION_MODE_MISMATCH")


def safety_fasting_window(order, served_at):
    if not order.get("is_fasting_required"):
        return
    dl = fasting_deadline_for(order)
    if dl is not None and served_at > dl:
        fail("ERR_FASTING_WINDOW_VIOLATED")


def safety_ladder(order, center, served_at, mode=None):
    safety_pediatric_center_capable(order, center)
    safety_pediatric_draw_floor(order, center)
    safety_order_of_draw(order)
    safety_staff_credential(order, center)
    safety_collection_mode(mode, order)
    safety_fasting_window(order, served_at)


# ---------------------------------------------------------------------------
# Priority 6 — fiscal (sub-order 6a..6g)
# ---------------------------------------------------------------------------
def fiscal_necessity(order):
    if order.get("necessity_status") == "FAIL":
        fail("ERR_MEDICAL_NECESSITY_FAILED")
    if order.get("necessity_status") == "PENDING":
        fail("ERR_MEDICAL_NECESSITY_PENDING")


def fiscal_insurance(order):
    status = order.get("insurance_status")
    if status == "UNVERIFIED":
        fail("ERR_INSURANCE_UNVERIFIED")
    if status == "INELIGIBLE":
        fail("ERR_INSURANCE_INELIGIBLE")
    if status == "EXPIRED":
        fail("ERR_INSURANCE_EXPIRED")


def fiscal_panel_covered(order):
    plan = db.insurance_plans.get(order.get("insurance_plan_id"))
    if plan is not None and plan.get("status") == "TERMINATED" \
            and order.get("insurance_status") not in ("ELIGIBLE",):
        return
    # A panel is NOT_COVERED only when the plan explicitly excludes it.
    if status_not_covered(order, plan):
        fail("ERR_NOT_COVERED_PANEL")


def status_not_covered(order, plan):
    if plan is None:
        return False
    covered = order.get("_covered_panels")
    if covered is None:
        return False
    return order["test_panel"] not in covered


def fiscal_prepay(order):
    if order.get("prepay_collected_cents", 0) < order.get("prepay_required_cents", 0):
        fail("ERR_PREPAY_REQUIRED")


def fiscal_ladder(order, include_prepay=True):
    fiscal_necessity(order)
    fiscal_insurance(order)
    fiscal_panel_covered(order)
    if include_prepay:
        fiscal_prepay(order)


# ---------------------------------------------------------------------------
# Priority 7 — temporal (sub-order 7a..7f)
# ---------------------------------------------------------------------------
def operating_hours_check(center, interval_start, interval_end):
    start_local = local_minute_of_day(interval_start, center)
    end_local = local_minute_of_day(interval_end, center)
    if start_local < center["open_local_minutes"] or end_local > center["close_local_minutes"]:
        fail("ERR_OUTSIDE_OPERATING_HOURS")


def staff_listing_check(phlebotomist_id, start, end):
    if phlebotomist_id is None:
        return
    for p in db.phlebotomists.values():
        if p["id"] == phlebotomist_id:
            continue
        if p.get("_listing_start") is None:
            continue
        if start < p["_listing_end"] and p["_listing_start"] < end:
            fail("ERR_STAFFING_BUSY")


def station_hold_check(center, station_index):
    for a in db.appointments.values():
        if a["service_center_id"] != center["id"]:
            continue
        if a["draw_state"] != "STAFF_PENDING":
            continue
        if a.get("station_index", -1) != station_index:
            continue
        expires = a.get("draw_hold_expires_utc")
        if expires is None:
            continue
        if get_clock() <= parse_iso(expires):
            fail("ERR_DRAW_HOLD_CONFLICT")


def appointment_slot_check(center, interval_start, interval_end, ignore_id=None):
    for a in db.appointments.values():
        if a["service_center_id"] != center["id"] or a["id"] == ignore_id:
            continue
        if a["draw_state"] in ("RESCHEDULED", "NO_SHOW"):
            continue
        other_start = parse_iso(a["scheduled_start_utc"])
        span = int(a.get("slot_span") or 1) * int(center["slot_minutes"])
        other_end = other_start + timedelta(minutes=span)
        if other_start == interval_start and other_end == interval_end:
            fail("ERR_SLOT_ALREADY_TAKEN")


def courier_dispatch_check(center, dispatch):
    for r in db.courier_runs.values():
        if r["service_center_id"] != center["id"]:
            continue
        if r["status"] == "CANCELLED":
            continue
        if parse_iso(r["dispatch_utc"]) == dispatch:
            fail("ERR_SLOT_ALREADY_TAKEN")


def capacity_check(center, interval_minutes, ignore_id=None):
    """7f: booked station-minutes from the clock forward must fit station_count*slot_minutes."""
    clock = get_clock()
    used = 0
    for a in db.appointments.values():
        if a["service_center_id"] != center["id"] or a["id"] == ignore_id:
            continue
        if a["draw_state"] in ("RESCHEDULED", "NO_SHOW"):
            continue
        start = parse_iso(a["scheduled_start_utc"])
        if start < clock:
            continue
        used += int(a.get("slot_span") or 1) * int(center["slot_minutes"])
    limit = int(center["station_count"]) * int(center["slot_minutes"])
    if used + interval_minutes > limit:
        fail("ERR_STATION_CAPACITY_EXCEEDED")


def temporal_ladder_for_appointment(center, interval_start, interval_end,
                                    slot_minutes, ignore_id=None):
    operating_hours_check(center, interval_start, interval_end)
    appointment_slot_check(center, interval_start, interval_end, ignore_id)
    capacity_check(center, slot_minutes, ignore_id)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _req_for(order, tube_code):
    from domain import resolve_tubes
    for r in resolve_tubes(order):
        if r["tube_code"] == tube_code:
            return r
    return None


def assignability(order, run):
    """Shared assign-courier / recollection courier gate. Returns deadline."""
    appt = _active_appointment(order)
    if appt is None or not appt.get("checkin_utc"):
        fail("ERR_NO_ELIGIBLE_COURIER_RUN")
    checkin = parse_iso(appt["checkin_utc"])
    start = parse_iso(appt["scheduled_start_utc"])
    if not (checkin - timedelta(minutes=30) <= start <= checkin):
        fail("ERR_NO_ELIGIBLE_COURIER_RUN")
    return appt


def _active_appointment(order):
    from domain import appointment_for_order
    return appointment_for_order(order["id"], active_only=True)


def courier_capacity_guard(run):
    """Write-time guard: reads the Post-decrement count (the read-time band reads
    the Pre-decrement count), so a put-back at exactly capacity frees one slot."""
    if run["committed_specimen_count"] >= COURIER_MAX_SPECIMENS_PER_RUN:
        fail("ERR_INVALID_STATE", "The courier run is at capacity.")


def assign_capacity_guard(run):
    if run["committed_specimen_count"] + 1 > COURIER_MAX_SPECIMENS_PER_RUN:
        fail("ERR_INVALID_STATE", "The courier run is at capacity.")


def load_posture(count):
    if count <= 24:
        return "LOW"
    if count <= 39:
        return "MEDIUM"
    return "FULL"


def draw_hold_expires(center, staff_pending_at):
    minutes = int(center.get("draw_hold_minutes", DRAW_HOLD_MINUTES_DEFAULT))
    return staff_pending_at + timedelta(minutes=minutes)


def credential_label(mode):
    allowed = credentialed_for(mode)
    return "any" if allowed is None else ",".join(sorted(allowed))