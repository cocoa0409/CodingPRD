"""The logical clock and the four time sweeps (PRD section 2.6).

This is the one endpoint mounted outside /land-origination. The sweeps run in
the pinned order S1, S2, S3, S4, and each iterates its candidate set in
created_at ascending order.
"""

from flask import Blueprint

import cascades
import validation as v
from auth import OPERATOR_ROLES, require
from envelope import ok
from store import db, ordered, touch
from util import fmt_dt

bp = Blueprint("clock", __name__)


def _sweep_options(clock):
    """S1: option expiry. Never a refund event."""
    count = 0
    for agreement in ordered(db.options.values()):
        expiry = agreement["option_expiry_at"]
        if agreement["status"] != "EXECUTED" or expiry is None or expiry > clock:
            continue
        agreement["status"] = "EXPIRED"
        touch(agreement)
        parcel = db.parcels.get(agreement["parcel_id"])
        if parcel is not None and parcel["status"] == "OPTIONED":
            parcel["status"] = "QUALIFIED"
            touch(parcel)
        cascades.sync_landowner_posture(
            db.landowners.get(agreement["landowner_id"]))
        count += 1
    return count


def _sweep_consents(clock):
    """S2: consent expiry. No acreage recompute: nothing had been released."""
    count = 0
    for consent in ordered(db.consents.values()):
        expiry = consent["consent_expiry_at"]
        if consent["status"] != "REQUESTED" or expiry is None or expiry > clock:
            continue
        consent["status"] = "EXPIRED"
        touch(consent)
        count += 1
    return count


def _sweep_bookings(clock):
    """S3: booking completion."""
    count = 0
    for booking in ordered(db.bookings.values()):
        if booking["status"] != "BOOKED" or booking["window_end"] > clock:
            continue
        booking["status"] = "COMPLETED"
        touch(booking)
        count += 1
    return count


def _sweep_leases(clock):
    """S4: lease delinquency."""
    count = 0
    for lease in ordered(db.leases.values()):
        if lease["rent_status"] not in ("PENDING_FIRST_RENT", "CURRENT"):
            continue
        overdue = False
        for invoice in cascades.lease_invoices(lease["id"]):
            if invoice["status"] == "ISSUED" and invoice["due_at"] is not None \
                    and invoice["due_at"] <= clock:
                overdue = True
                break
        if not overdue:
            continue
        lease["rent_status"] = "DELINQUENT"
        touch(lease)
        count += 1
    return count


@bp.post("/_clock/set_current_utc")
@require(*OPERATOR_ROLES)
def set_current_utc():
    body = v.json_body()
    clock = v.req_dt(body, "current_utc")
    db.clock = clock

    expired_options = _sweep_options(clock)
    expired_consents = _sweep_consents(clock)
    completed_bookings = _sweep_bookings(clock)
    delinquent_leases = _sweep_leases(clock)

    return ok({
        "current_utc": fmt_dt(clock),
        "expired_option_count": expired_options,
        "expired_consent_count": expired_consents,
        "completed_booking_count": completed_bookings,
        "delinquent_lease_count": delinquent_leases,
    })
