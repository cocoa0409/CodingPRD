"""Cascade side effects (PRD 2.8, 3.7): flight cancellations, balloon grounding,
refund auto-creation. All effects are visible within the same request."""
from db import db
from services.core import new_record, touch
from services.calculations import refund_requested_amount, goodwill_credit


def create_refund(reservation, reason, requested_amount_cents):
    return new_record("refunds", {
        "reservation_id": reservation["id"],
        "reason": reason,
        "requested_amount_cents": requested_amount_cents,
        "approved_amount_cents": None,
        "status": "REQUESTED",
        "paid_via": None,
        "paid_at": None,
    })


def cancel_flight_cascade(flight, flight_cancel_reason, reservation_cancel_reason,
                          with_goodwill: bool):
    """Flight → CANCELLED; every reservation in {PENDING, CONFIRMED, CHECKED_IN}
    → CANCELLED with the cascade's reason; each PAID reservation gets a
    policy-computed Refund (REQUESTED). Operator-flavored cascades additionally
    set goodwill_credit_cents = round_half_up(paid_cents * 10%)."""
    flight["status"] = "CANCELLED"
    flight["cancel_reason"] = flight_cancel_reason
    touch(flight)
    for r in db["reservations"].values():
        if r["flight_id"] != flight["id"]:
            continue
        if r["booking_status"] not in ("PENDING", "CONFIRMED", "CHECKED_IN"):
            continue
        r["booking_status"] = "CANCELLED"
        r["cancel_reason"] = reservation_cancel_reason
        if r["payment_status"] == "PAID":
            amount = refund_requested_amount(
                flight["kind"], r["paid_cents"], r["party_size"],
                reservation_cancel_reason)
            if amount is not None:
                create_refund(r, reservation_cancel_reason, amount)
            if with_goodwill:
                r["goodwill_credit_cents"] = goodwill_credit(r["paid_cents"])
        touch(r)


def ground_balloon_cascade(balloon):
    """Balloon GROUND: every SCHEDULED flight on this balloon → CANCELLED
    (AIRCRAFT); their reservations cascade with OPERATOR_CANCEL + refunds +
    goodwill (PRD 3.7 aircraft cascade)."""
    for f in list(db["flights"].values()):
        if f["balloon_id"] == balloon["id"] and f["status"] == "SCHEDULED":
            cancel_flight_cascade(f, "AIRCRAFT", "OPERATOR_CANCEL", with_goodwill=True)
