"""Derived fields, serialisers, slot recomputation and the conserving cascades."""

import datetime
from decimal import Decimal

import calc
from calc import RANK_NAMES, RANKS, dec
from errors import ApiError
from store import db, fmt_date, fmt_instant

LIVE_SEAT_STATUSES = ("CONFIRMED", "CHECKED_IN")
LIVE_BOOKING_STATUSES = ("HELD", "CONFIRMED", "CHECKED_IN")
BED_NIGHT_STATUSES = ("CONFIRMED", "CHECKED_IN", "CHECKED_OUT")
LIVE_SLOT_STATUSES = ("DRAFT", "OPEN", "HOLD", "RUNNING")
OPENABLE_SLOT_STATUSES = ("DRAFT", "OPEN", "HOLD")
TERMINAL_EMPLOYMENT = ("COMPLETED_SEASON", "DEPARTED_EARLY")


# --------------------------------------------------------------- collections
def rows_of(collection, **filters):
    out = []
    for row in db.rows(collection):
        ok = True
        for key, value in filters.items():
            if value is None:
                continue
            if row.get(key) != value:
                ok = False
                break
        if ok:
            out.append(row)
    return out


def seats_of_slot(slot_id):
    return rows_of("activity_reservations", slot_id=slot_id)


def seats_of_guest(guest_id):
    return rows_of("activity_reservations", guest_id=guest_id)


def assignments_of_slot(slot_id):
    return rows_of("guide_assignments", slot_id=slot_id)


def assessments_of_guest(guest_id):
    return rows_of("rider_assessments", guest_id=guest_id)


# ------------------------------------------------------------- guest derivations
def guest_age(guest):
    return calc.age_years(guest.get("birth_date"), db.clock_date())


def waiver_status(guest):
    """PRD 3.3: first matching clause of the ordered test."""
    if guest.get("waiver_signed_on") is None:
        return "NONE"
    if guest.get("waiver_revoked_at") is not None:
        return "REVOKED"
    expires = guest.get("waiver_expires_on")
    if expires is not None and db.clock_date() > expires:
        return "EXPIRED"
    return "SIGNED"


def guest_ranks(guest):
    """Returns (current_ability_rank, effective_ability_rank)."""
    rows = assessments_of_guest(guest["id"])
    evaluated = [
        a
        for a in rows
        if a["assessment_status"] == "EVALUATED" and a.get("evaluated_at") is not None
    ]
    base = "UNASSESSED"
    if evaluated:
        newest = max(a["evaluated_at"] for a in evaluated)
        tied = [a for a in evaluated if a["evaluated_at"] == newest]
        tied.sort(key=lambda a: (a["created_at"], a["_seq"]))
        base = tied[0].get("assessed_ability") or "UNASSESSED"
    current = base
    rank = RANKS[base]
    if any(a["assessment_status"] == "RE_EVALUATION_REQUESTED" for a in rows):
        rank = min(rank, RANKS["NOVICE"])
    if guest.get("guest_standing") == "RESTRICTED":
        rank = min(rank, RANKS["BEGINNER"])
    if guest.get("guest_standing") == "SUSPENDED":
        rank = RANKS["UNASSESSED"]
    return current, RANK_NAMES[rank]


def effective_rank(guest):
    return guest_ranks(guest)[1]


# ------------------------------------------------------------- horse derivations
def scheduled_load_hours(horse):
    total = Decimal(0)
    for seat in db.activity_reservations.values():
        if seat.get("assigned_horse_id") != horse["id"]:
            continue
        if seat.get("mount_status") != "ASSIGNED":
            continue
        slot = db.activity_slots.get(seat["slot_id"])
        if slot is not None:
            total += dec(slot["duration_hours"])
    return calc.hours(total, 1)


def realized_load_hours(horse):
    total = Decimal(0)
    for seat in db.activity_reservations.values():
        if seat.get("assigned_horse_id") != horse["id"]:
            continue
        if seat.get("mount_status") != "COMPLETED":
            continue
        slot = db.activity_slots.get(seat["slot_id"])
        if slot is not None and slot.get("actual_duration_hours") is not None:
            total += dec(slot["actual_duration_hours"])
    return calc.hours(total, 1)


def daily_scheduled_hours(horse_id, on_date, skip_seat_id=None):
    total = Decimal(0)
    for seat in db.activity_reservations.values():
        if seat["id"] == skip_seat_id:
            continue
        if seat.get("assigned_horse_id") != horse_id:
            continue
        if seat.get("mount_status") != "ASSIGNED":
            continue
        slot = db.activity_slots.get(seat["slot_id"])
        if slot is not None and slot["starts_at"].date() == on_date:
            total += dec(slot["duration_hours"])
    return total


def mount_interval_conflict(horse_id, slot, skip_seat_id=None):
    for seat in db.activity_reservations.values():
        if seat["id"] == skip_seat_id:
            continue
        if seat.get("assigned_horse_id") != horse_id:
            continue
        if seat.get("mount_status") != "ASSIGNED":
            continue
        other = db.activity_slots.get(seat["slot_id"])
        if other is None or other["id"] == slot["id"]:
            continue
        if calc.mount_buffer_conflict(
            slot["starts_at"], slot["ends_at"], other["starts_at"], other["ends_at"]
        ):
            return True
    return False


# ------------------------------------------------------------- staff derivations
def staff_scheduled_guide_hours(staff):
    total = Decimal(0)
    for assignment in db.guide_assignments.values():
        if assignment["staff_member_id"] != staff["id"]:
            continue
        if assignment["assignment_status"] != "SCHEDULED":
            continue
        slot = db.activity_slots.get(assignment["slot_id"])
        if slot is not None:
            total += dec(slot["duration_hours"])
    return calc.hours(total, 1)


def staff_days_worked(staff):
    if staff["employment_status"] in TERMINAL_EMPLOYMENT:
        return int(staff.get("days_worked_frozen") or 0)
    return calc.staff_days_worked(
        staff["hired_on"], staff["contract_days"], db.clock_date()
    )


def staff_projected_bonus(staff):
    if staff["employment_status"] == "DEPARTED_EARLY":
        return 0
    season = db.seasons.get(staff["season_id"])
    if season is None:
        return 0
    return calc.pro_rated_bonus(
        season["retention_bonus_cents"], staff_days_worked(staff), staff["contract_days"]
    )


# -------------------------------------------------------------- slot derivations
def slot_state(slot):
    seats = seats_of_slot(slot["id"])
    live = [s for s in seats if s["reservation_status"] in LIVE_SEAT_STATUSES]
    confirmed = len(live)
    minors = 0
    rank_counts = {}
    for seat in live:
        guest = db.guests.get(seat["guest_id"])
        if guest is not None and guest_age(guest) < calc.MINOR_RIDER_AGE_YEARS:
            minors += 1
        rank = seat.get("rider_ability_at_booking") or "UNASSESSED"
        rank_counts[rank] = rank_counts.get(rank, 0) + 1
    mounts = len([s for s in live if s.get("mount_status") == "ASSIGNED"])
    guides = len(
        [
            a
            for a in assignments_of_slot(slot["id"])
            if a["assignment_status"] == "SCHEDULED"
        ]
    )
    required = calc.guide_staffing_requirement(
        rank_counts, minors, slot["terrain_grade"], confirmed
    )
    season = db.seasons.get(slot["season_id"])
    if season is None or season["season_status"] not in ("OPEN", "IN_SEASON"):
        posture = "FROZEN"
    elif slot["mount_required"] and mounts < confirmed:
        posture = "MOUNT_SHORT"
    elif guides < required:
        posture = "UNDERSTAFFED"
    else:
        posture = "STAFFED_READY"
    return {
        "confirmed_rider_count": confirmed,
        "minor_rider_count": minors,
        "mount_assigned_count": mounts,
        "assigned_guide_count": guides,
        "required_guide_count": required,
        "seats_available": slot["capacity"] - confirmed,
        "readiness_posture": posture,
    }


def apply_hold(slot):
    """An OPEN slot whose recomputed posture degraded drops to HOLD in-request."""
    state = slot_state(slot)
    if slot["slot_status"] == "OPEN" and state["readiness_posture"] in (
        "UNDERSTAFFED",
        "MOUNT_SHORT",
    ):
        slot["slot_status"] = "HOLD"
        slot["hold_reason"] = (
            "UNDERSTAFFED"
            if state["assigned_guide_count"] < state["required_guide_count"]
            else "MOUNT_SHORT"
        )


# --------------------------------------------------------------------- cascades
class Touch(object):
    """Collects every row a request mutated so each is versioned exactly once."""

    def __init__(self):
        self._rows = []
        self._slots = []

    def add(self, row):
        if row is None:
            return
        for existing in self._rows:
            if existing is row:
                return
        self._rows.append(row)

    def slot(self, row):
        if row is None:
            return
        for existing in self._slots:
            if existing is row:
                return
        self._slots.append(row)

    def finalize(self):
        for slot in self._slots:
            apply_hold(slot)
        for row in self._rows:
            db.touch(row)
        for slot in self._slots:
            db.touch(slot)


def release_mount(seat, touch):
    """ASSIGNED -> RELEASED, restoring the horse's scheduled load exactly."""
    if seat.get("mount_status") != "ASSIGNED":
        return
    horse = db.horses.get(seat.get("assigned_horse_id"))
    seat["mount_status"] = "RELEASED"
    seat["assigned_horse_id"] = None
    seat["mount_release_count"] = int(seat.get("mount_release_count") or 0) + 1
    if horse is not None:
        touch.add(horse)


def cancel_seat(seat, touch):
    """Conserving seat reversal: the seat returns exactly the surcharge it charged."""
    seat["reservation_status"] = "CANCELLED"
    seat["cancelled_at"] = db.clock_iso()
    seat["surcharge_reversed_cents"] = int(seat.get("surcharge_cents") or 0)
    booking = db.bookings.get(seat["booking_id"])
    if booking is not None:
        booking["activity_surcharge_total_cents"] = int(
            booking["activity_surcharge_total_cents"]
        ) - int(seat["surcharge_cents"] or 0)
        touch.add(booking)
    release_mount(seat, touch)
    touch.add(seat)
    touch.slot(db.activity_slots.get(seat["slot_id"]))


def slot_not_started(seat):
    slot = db.activity_slots.get(seat["slot_id"])
    if slot is None:
        return False
    return slot["starts_at"] > db.clock_instant()


def cancel_future_seats(guest_id, touch, statuses=LIVE_SEAT_STATUSES, min_rank_above=None):
    """Cancels the guest's future seats a safety change no longer supports."""
    for seat in seats_of_guest(guest_id):
        if seat["reservation_status"] not in statuses:
            continue
        if not slot_not_started(seat):
            continue
        if min_rank_above is not None:
            slot = db.activity_slots.get(seat["slot_id"])
            if slot is None:
                continue
            if RANKS[slot["min_ability_rank"]] <= RANKS[min_rank_above]:
                continue
        cancel_seat(seat, touch)


def apply_standing(guest, standing, touch):
    """Moves a guest's standing and runs the seat/mount/slot cascade it forces."""
    guest["guest_standing"] = standing
    if standing == "SUSPENDED":
        cancel_future_seats(guest["id"], touch)
    elif standing == "RESTRICTED":
        cancel_future_seats(guest["id"], touch, min_rank_above="BEGINNER")
    touch.add(guest)


# --------------------------------------------------------------- mount selection
def mount_is_eligible(horse, seat, slot, guest, rider_rank):
    if horse["horse_status"] != "IN_SERVICE":
        return False
    if RANKS[rider_rank] < RANKS[horse["min_rider_ability"]]:
        return False
    if RANKS[rider_rank] > RANKS[horse["max_rider_ability"]]:
        return False
    if dec(guest["weight_lb"]) > dec(horse["weight_limit_lb"]):
        return False
    if mount_interval_conflict(horse["id"], slot, skip_seat_id=seat["id"]):
        return False
    daily = daily_scheduled_hours(horse["id"], slot["starts_at"].date(), skip_seat_id=seat["id"])
    if daily + dec(slot["duration_hours"]) > calc.MAX_DAILY_MOUNT_HOURS:
        return False
    if int(horse["consecutive_duty_days"]) >= calc.MAX_CONSECUTIVE_DUTY_DAYS:
        return False
    return True


def select_mount(seat, slot, guest, rider_rank):
    eligible = [
        h
        for h in db.rows("horses")
        if mount_is_eligible(h, seat, slot, guest, rider_rank)
    ]
    if not eligible:
        raise ApiError("ERR_NO_ELIGIBLE_MOUNT", "No eligible mount is available.")
    eligible.sort(
        key=lambda h: (
            dec(scheduled_load_hours(h)),
            int(h["consecutive_duty_days"]),
            h["created_at"],
            h["_seq"],
        )
    )
    return eligible[0]


def attach_mount(seat, slot, horse, touch):
    seat["mount_status"] = "ASSIGNED"
    seat["assigned_horse_id"] = horse["id"]
    touch.add(seat)
    touch.add(horse)
    touch.slot(slot)


# ------------------------------------------------------------------ serialisers
def season_json(row):
    return {
        "id": row["id"],
        "name": row["name"],
        "arrival_weekday": row["arrival_weekday"],
        "season_start_date": fmt_date(row["season_start_date"]),
        "season_end_date": fmt_date(row["season_end_date"]),
        "min_stay_nights": row["min_stay_nights"],
        "max_stay_nights": row["max_stay_nights"],
        "deposit_pct": row["deposit_pct"],
        "buyout_premium_pct": row["buyout_premium_pct"],
        "no_show_penalty_cents": row["no_show_penalty_cents"],
        "retention_bonus_cents": row["retention_bonus_cents"],
        "dining_seat_capacity": row["dining_seat_capacity"],
        "package_tiers": row["package_tiers"],
        "season_status": row["season_status"],
        "gross_package_revenue_cents": row["gross_package_revenue_cents"],
        "retention_bonus_liability_cents": row["retention_bonus_liability_cents"],
        "net_surplus_cents": row["net_surplus_cents"],
        "capital_reserve_cents": row["capital_reserve_cents"],
        "capital_committed_cents": row["capital_committed_cents"],
        "bed_nights_sold": row["bed_nights_sold"],
        "in_house_guest_count": row["in_house_guest_count"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def cabin_json(row):
    return {
        "id": row["id"],
        "name": row["name"],
        "bed_capacity": row["bed_capacity"],
        "cabin_status": row["cabin_status"],
        "maintenance_project_code": row["maintenance_project_code"],
        "maintenance_capital_cost_cents": row["maintenance_capital_cost_cents"],
        "last_turnover_completed_at": row["last_turnover_completed_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def guest_json(row):
    current, effective = guest_ranks(row)
    return {
        "id": row["id"],
        "full_name": row["full_name"],
        "birth_date": fmt_date(row["birth_date"]),
        "weight_lb": row["weight_lb"],
        "age_years": guest_age(row),
        "guest_standing": row["guest_standing"],
        "waiver_signed_on": fmt_date(row.get("waiver_signed_on")),
        "waiver_expires_on": fmt_date(row.get("waiver_expires_on")),
        "waiver_revoked_at": row.get("waiver_revoked_at"),
        "equine_statute_ack": row["equine_statute_ack"],
        "waiver_signed_by_guardian_guest_id": row.get("waiver_signed_by_guardian_guest_id"),
        "waiver_status": waiver_status(row),
        "current_ability_rank": current,
        "effective_ability_rank": effective,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def assessment_json(row):
    return {
        "id": row["id"],
        "guest_id": row["guest_id"],
        "requested_ability": row["requested_ability"],
        "assessed_ability": row.get("assessed_ability"),
        "assessed_by_note": row.get("assessed_by_note"),
        "evaluated_at": fmt_instant(row.get("evaluated_at")),
        "assessment_status": row["assessment_status"],
        "re_evaluation_reason": row.get("re_evaluation_reason"),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def booking_json(row):
    return {
        "id": row["id"],
        "season_id": row["season_id"],
        "cabin_id": row["cabin_id"],
        "lead_guest_id": row["lead_guest_id"],
        "package_tier_code": row["package_tier_code"],
        "arrival_date": fmt_date(row["arrival_date"]),
        "departure_date": fmt_date(row["departure_date"]),
        "nights": row["nights"],
        "is_buyout": row["is_buyout"],
        "party_members": row["party_members"],
        "party_size": row["party_size"],
        "adult_count": row["adult_count"],
        "child_count": row["child_count"],
        "dietary_briefing_ack": row["dietary_briefing_ack"],
        "booking_status": row["booking_status"],
        "payment_status": row["payment_status"],
        "provisional_package_total_cents": row["provisional_package_total_cents"],
        "deposit_required_cents": row["deposit_required_cents"],
        "deposit_paid_cents": row["deposit_paid_cents"],
        "payments_applied_cents": row["payments_applied_cents"],
        "refunded_cents": row["refunded_cents"],
        "forfeited_cents": row["forfeited_cents"],
        "activity_surcharge_total_cents": row["activity_surcharge_total_cents"],
        "activity_credit_applied_cents": row["activity_credit_applied_cents"],
        "no_show_count": row["no_show_count"],
        "no_show_penalty_total_cents": row["no_show_penalty_total_cents"],
        "gratuity_cents": row["gratuity_cents"],
        "folio_adjustment_total_cents": row["folio_adjustment_total_cents"],
        "realized_nights": row["realized_nights"],
        "realized_subtotal_cents": row["realized_subtotal_cents"],
        "final_folio_total_cents": row["final_folio_total_cents"],
        "folio_balance_cents": row["folio_balance_cents"],
        "cancellation_refund_pct": row["cancellation_refund_pct"],
        "checked_in_at": row.get("checked_in_at"),
        "checked_out_at": row.get("checked_out_at"),
        "cancelled_at": row.get("cancelled_at"),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def horse_json(row):
    return {
        "id": row["id"],
        "name": row["name"],
        "min_rider_ability": row["min_rider_ability"],
        "max_rider_ability": row["max_rider_ability"],
        "weight_limit_lb": row["weight_limit_lb"],
        "horse_status": row["horse_status"],
        "scheduled_load_hours": scheduled_load_hours(row),
        "realized_load_hours": realized_load_hours(row),
        "consecutive_duty_days": row["consecutive_duty_days"],
        "last_duty_date": fmt_date(row.get("last_duty_date")),
        "last_rest_started_on": fmt_date(row.get("last_rest_started_on")),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def health_event_json(row):
    return {
        "id": row["id"],
        "horse_id": row["horse_id"],
        "event_type": row["event_type"],
        "observed_on": fmt_date(row["observed_on"]),
        "note": row.get("note"),
        "resulting_horse_status": row["resulting_horse_status"],
        "created_at": row["created_at"],
    }


def slot_json(row):
    payload = {
        "id": row["id"],
        "season_id": row["season_id"],
        "activity_type": row["activity_type"],
        "starts_at": fmt_instant(row["starts_at"]),
        "ends_at": fmt_instant(row["ends_at"]),
        "duration_hours": row["duration_hours"],
        "terrain_grade": row["terrain_grade"],
        "min_ability_rank": row["min_ability_rank"],
        "capacity": row["capacity"],
        "rider_surcharge_cents": row["rider_surcharge_cents"],
        "mount_required": row["mount_required"],
        "slot_status": row["slot_status"],
        "hold_reason": row.get("hold_reason"),
        "actual_started_at": fmt_instant(row.get("actual_started_at")),
        "actual_ended_at": fmt_instant(row.get("actual_ended_at")),
        "actual_duration_hours": row.get("actual_duration_hours"),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }
    payload.update(slot_state(row))
    return payload


def assignment_json(row):
    return {
        "id": row["id"],
        "slot_id": row["slot_id"],
        "staff_member_id": row["staff_member_id"],
        "guide_role": row["guide_role"],
        "assignment_status": row["assignment_status"],
        "credited_hours": row["credited_hours"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def reservation_json(row):
    return {
        "id": row["id"],
        "slot_id": row["slot_id"],
        "booking_id": row["booking_id"],
        "guest_id": row["guest_id"],
        "assigned_horse_id": row.get("assigned_horse_id"),
        "reservation_status": row["reservation_status"],
        "mount_status": row["mount_status"],
        "surcharge_cents": row["surcharge_cents"],
        "surcharge_reversed_cents": row["surcharge_reversed_cents"],
        "rider_ability_at_booking": row.get("rider_ability_at_booking"),
        "mount_release_count": row["mount_release_count"],
        "checked_in_at": row.get("checked_in_at"),
        "completed_at": row.get("completed_at"),
        "cancelled_at": row.get("cancelled_at"),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def staff_json(row):
    return {
        "id": row["id"],
        "season_id": row["season_id"],
        "full_name": row["full_name"],
        "role_type": row["role_type"],
        "certifications": row["certifications"],
        "hired_on": fmt_date(row["hired_on"]),
        "contract_end_date": fmt_date(row["contract_end_date"]),
        "housing_unit_code": row.get("housing_unit_code"),
        "housing_bunk_number": row.get("housing_bunk_number"),
        "employment_status": row["employment_status"],
        "separated_on": fmt_date(row.get("separated_on")),
        "contract_days": row["contract_days"],
        "days_worked": staff_days_worked(row),
        "retention_bonus_projected_cents": staff_projected_bonus(row),
        "retention_bonus_settled_cents": row["retention_bonus_settled_cents"],
        "scheduled_guide_hours": staff_scheduled_guide_hours(row),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def incident_json(row):
    return {
        "id": row["id"],
        "reservation_id": row["reservation_id"],
        "guest_id": row["guest_id"],
        "horse_id": row.get("horse_id"),
        "reported_by_staff_member_id": row["reported_by_staff_member_id"],
        "severity": row["severity"],
        "equine_activity_statute_notice_given": row["equine_activity_statute_notice_given"],
        "narrative": row["narrative"],
        "occurred_at": fmt_instant(row["occurred_at"]),
        "incident_status": row["incident_status"],
        "disposition_note": row.get("disposition_note"),
        "disposed_by_user_id": row.get("disposed_by_user_id"),
        "closed_by_user_id": row.get("closed_by_user_id"),
        "remediation_completed": row["remediation_completed"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }
