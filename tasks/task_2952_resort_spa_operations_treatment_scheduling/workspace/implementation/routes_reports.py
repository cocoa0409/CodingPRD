"""Compliance sweeps and management reporting (PRD §3.10)."""

from datetime import timedelta

from flask import Blueprint

import auth
import calc
import domain
import envelope
import errors
import store
import validation as v
from errors import ApiError
from store import db, touch

bp = Blueprint("reports", __name__)


# --------------------------------------------------------------------------
# the compliance sweep
# --------------------------------------------------------------------------

@bp.route("/compliance-sweeps", methods=["POST"])
def run_compliance_sweep():
    auth.authenticate(auth.COMPLIANCE_OFFICER, auth.SPA_DIRECTOR)
    v.json_body()

    swept_at = db.clock
    today = swept_at.date()

    # hop 1 — expire every VERIFIED licence whose expiry date has passed
    expired_license_ids = []
    touched_therapist_ids = []
    for license_row in store.by_created(list(db.licenses.values())):
        if license_row["verification_status"] != "VERIFIED":
            continue
        if license_row["expires_on"] >= today:
            continue
        license_row["verification_status"] = "EXPIRED"
        touch(license_row)
        expired_license_ids.append(license_row["id"])
        if license_row["therapist_id"] not in touched_therapist_ids:
            touched_therapist_ids.append(license_row["therapist_id"])

    # hop 2 — suspend therapists left without any VERIFIED unexpired licence
    suspended_therapist_ids = []
    for therapist_id in touched_therapist_ids:
        therapist = db.therapists.get(therapist_id)
        if therapist is None or therapist["status"] != "ACTIVE":
            continue
        verified = domain.verified_licenses(therapist)
        if any(domain.unexpired(row) for row in verified):
            continue
        therapist["status"] = "SUSPENDED"
        therapist["suspension_reason"] = "LICENSE_EXPIRED"
        touch(therapist)
        suspended_therapist_ids.append(therapist["id"])

    # hops 3 and 4 — block their non-terminal appointments, expire the upsells
    candidates = []
    for therapist_id in suspended_therapist_ids:
        candidates.extend(domain.appointments_of_therapist(therapist_id))
    blocked_appointment_ids, expired_attachment_ids = domain.run_block_cascade(
        candidates)

    # hop 5 — auto-cancel newly blocked confirmed work inside the horizon
    horizon = swept_at + timedelta(hours=calc.SWEEP_AUTO_CANCEL_HORIZON_HOURS)
    auto_cancelled_appointment_ids = []
    for appointment_id in blocked_appointment_ids:
        appointment = db.appointments.get(appointment_id)
        if appointment is None or appointment["schedule_status"] != "CONFIRMED":
            continue
        if appointment["start_at"] >= horizon:
            continue
        appointment["schedule_status"] = "CANCELLED"
        appointment["cancellation_charge_cents"] = 0
        touch(appointment)
        domain.release_capacity(appointment)
        auto_cancelled_appointment_ids.append(appointment["id"])

    return envelope.ok({
        "swept_at": swept_at,
        "expired_license_ids": expired_license_ids,
        "suspended_therapist_ids": suspended_therapist_ids,
        "blocked_appointment_ids": blocked_appointment_ids,
        "auto_cancelled_appointment_ids": auto_cancelled_appointment_ids,
        "expired_attachment_ids": expired_attachment_ids,
    })


# --------------------------------------------------------------------------
# report window (ladder rung 32)
# --------------------------------------------------------------------------

def report_window():
    from_at = v.query_instant("from_at", required=True)
    to_at = v.query_instant("to_at", required=True)
    if from_at >= to_at:
        raise ApiError(errors.ERR_INVALID_REPORT_WINDOW,
                       "'from_at' must be strictly earlier than 'to_at'.")
    if (to_at - from_at) > timedelta(days=calc.MAX_REPORT_WINDOW_DAYS):
        raise ApiError(errors.ERR_INVALID_REPORT_WINDOW,
                       "The report window may span at most %d days."
                       % calc.MAX_REPORT_WINDOW_DAYS)
    return from_at, to_at


def completed_in_window(rows, from_at, to_at):
    return [r for r in rows
            if r["schedule_status"] == "COMPLETED"
            and from_at <= r["start_at"] < to_at]


# --------------------------------------------------------------------------
# room utilisation and margin
# --------------------------------------------------------------------------

@bp.route("/reports/room-utilization", methods=["GET"])
def room_utilization_report():
    auth.authenticate(auth.SPA_DIRECTOR, auth.SPA_COORDINATOR)
    from_at, to_at = report_window()
    room_id = v.query_str("room_id")

    window_minutes = int((to_at - from_at).total_seconds() // 60)

    rooms = store.by_created(list(db.rooms.values()))
    if room_id is not None:
        rooms = [r for r in rooms if r["id"] == room_id]

    elements = []
    for room in rooms:
        appointments = completed_in_window(domain.appointments_of_room(room["id"]),
                                          from_at, to_at)
        occupied_minutes = 0
        revenue_cents = 0
        labor_cost_cents = 0
        for appointment in appointments:
            occupied_minutes += ((appointment["actual_duration_minutes"] or 0)
                                 + room["turnover_buffer_minutes"])
            for row in domain.settlements_of(appointment["id"]):
                if row["status"] != "FINALIZED":
                    continue
                revenue_cents += (row["realized_price_cents"]
                                  + row["retail_revenue_cents"])
                labor_cost_cents += row["labor_cost_cents"]
        room_fixed_cost_cents = calc.apply_bp_per_hour(room["hourly_fixed_cost_cents"],
                                                      occupied_minutes)
        elements.append({
            "room_id": room["id"],
            "room_code": room["code"],
            "occupied_minutes": occupied_minutes,
            "utilization_pct": calc.pct2(occupied_minutes, window_minutes),
            "revenue_cents": revenue_cents,
            "labor_cost_cents": labor_cost_cents,
            "room_fixed_cost_cents": room_fixed_cost_cents,
            "net_margin_cents": revenue_cents - labor_cost_cents
            - room_fixed_cost_cents,
            "revenue_per_room_hour_cents": (
                calc.cents(calc.Decimal(revenue_cents) * calc.Decimal(60)
                           / calc.Decimal(window_minutes))
                if window_minutes else 0),
        })

    return envelope.ok({
        "from_at": from_at,
        "to_at": to_at,
        "window_minutes": window_minutes,
        "rooms": elements,
    })


# --------------------------------------------------------------------------
# retail attachment rate
# --------------------------------------------------------------------------

@bp.route("/reports/retail-attachment", methods=["GET"])
def retail_attachment_report():
    auth.authenticate(auth.SPA_DIRECTOR, auth.SPA_COORDINATOR)
    from_at, to_at = report_window()
    therapist_id = v.query_str("therapist_id")

    rows = store.by_created(list(db.appointments.values()))
    if therapist_id is not None:
        rows = [r for r in rows if r["therapist_id"] == therapist_id]
    eligible = completed_in_window(rows, from_at, to_at)

    purchased = []
    for appointment in eligible:
        purchased.extend(domain.purchased_attachments(appointment["id"]))

    purchased_amount_cents = sum(p["amount_cents"] for p in purchased)
    commission_cents = sum(calc.apply_bp(p["amount_cents"], calc.RETAIL_COMMISSION_BP)
                           for p in purchased)

    return envelope.ok({
        "from_at": from_at,
        "to_at": to_at,
        "eligible_appointment_count": len(eligible),
        "purchased_count": len(purchased),
        "attach_rate_pct": calc.pct2(len(purchased), len(eligible)),
        "purchased_amount_cents": purchased_amount_cents,
        "commission_cents": commission_cents,
    })
