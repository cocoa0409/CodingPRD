"""Multi-hop side effects (PRD 2.10). Every resource touched at any hop takes
its own updated_at refresh and version increment."""

from db import db, now, touch
from derive import (
    active_affidavit,
    recompute_district_ledger,
    recompute_seat_pressure,
    recompute_window_breach,
    registrations_of_session,
    window_of_report,
)

INVALIDATABLE_SCORE_STATUSES = ("NOT_SCORED", "SCORED", "RELEASED", "UNDER_APPEAL", "CORRECTED")


def withdraw_pending_registrations(session):
    for registration in registrations_of_session(session["id"]):
        if registration["attendance_status"] == "PENDING":
            registration["attendance_status"] = "WITHDRAWN"
            touch(registration)


def cancel_session(session):
    """DRAFT/SCHEDULED -> CANCELLED, however it is triggered."""
    session["status"] = "CANCELLED"
    touch(session)
    withdraw_pending_registrations(session)
    recompute_seat_pressure(session)


def invalidate_session(session):
    """CLOSED -> INVALIDATED plus the score flip on every registration."""
    session["status"] = "INVALIDATED"
    touch(session)
    for registration in registrations_of_session(session["id"]):
        if registration["score_status"] in INVALIDATABLE_SCORE_STATUSES:
            registration["score_status"] = "INVALIDATED"
            touch(registration)


def revoke_proctor_for_breach(session):
    """Hops 2 to 5 of the BREACH_CONFIRMED cascade (PRD 3.7)."""
    proctor = db.proctors.get(session["proctor_id"])
    affidavit = active_affidavit(session["proctor_id"], session["window_id"])
    if affidavit is not None:
        affidavit["status"] = "REVOKED"
        affidavit["revoked_reason"] = "BREACH_CONFIRMED"
        touch(affidavit)
    if proctor is not None:
        proctor["revoked_at"] = now()
        proctor["strike_count"] = proctor.get("strike_count", 0) + 1
        touch(proctor)
        for scheduled in list(db.sessions.values()):
            if scheduled["proctor_id"] == proctor["id"] and scheduled["status"] == "SCHEDULED":
                cancel_session(scheduled)


def reverse_lot_charge(report):
    """DISMISSED adjudication of a system report drops the lot out of the ledger."""
    lot = db.lots.get(report.get("material_lot_id"))
    if lot is None:
        return
    if not lot["charge_reversed"]:
        lot["charge_reversed"] = True
        touch(lot)
    recompute_district_ledger(db.districts.get(lot["district_id"]))


def refresh_report_window(report):
    recompute_window_breach(window_of_report(report))
