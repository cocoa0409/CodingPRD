"""Weekly rental period endpoints and the logical-clock control."""

from flask import Blueprint, request

import db
import services as svc
from db import stamp_created as DB_STAMP
from errors import (E_AGREEMENT_FROZEN, E_GRACE_NOT_LAPSED, E_INVALID_REQUEST,
                    E_INVALID_STATE, E_PAYMENT_BELOW_AMOUNT_DUE,
                    E_REFERENCED_ENTITY_NOT_FOUND, E_WEEK_OUTSIDE_AGREEMENT_TERM,
                    E_WEEK_OVERLAP, raise_error)
from middleware import check_schema, is_int
from middleware import body as get_body
from response import ok, ok_list
from services import (all_of, by_created, check_agreement_version, compute_weekly_charge,
                      damage_settlement_split, get_agreement, get_week, outstanding_delinquent_weeks,
                      paginate, recompute_equity_credit, recompute_posture, refresh_open_week_charge,
                      weeks_of)

bp = Blueprint("weeks", __name__)

WEEK_STATUSES = ("SCHEDULED", "OPEN", "DUE", "PAID", "GRACE", "DELINQUENT", "DEFERRED",
                 "RECOVERED", "WAIVED")
PAYMENT_STATUSES = ("UNPAID", "PARTIAL", "SETTLED", "FAILED")


@bp.post("/program/weeks")
def open_week():
    payload = get_body()
    check_schema(payload, "POST", "/program/weeks")
    agreement_id = payload["agreement_id"]
    if agreement_id not in db.AGREEMENTS:
        raise_error(E_REFERENCED_ENTITY_NOT_FOUND, "agreement_id does not name an agreement.")
    agreement = db.AGREEMENTS[agreement_id]

    # guard 7 (the agreement must not be frozen) is evaluated before guard 8,
    # whose literal trigger on this path is an agreement in no admissible state
    if agreement["compliance_posture"] == "FROZEN":
        raise_error(E_AGREEMENT_FROZEN, "The agreement's compliance posture is FROZEN.")
    if agreement["agreement_status"] not in ("ACTIVE", "RENEWAL_DUE"):
        raise_error(E_INVALID_STATE, "The agreement is not ACTIVE or RENEWAL_DUE.")

    start = db.now()
    end = start + db.days(7)

    # guard 18 (week ordinal) is evaluated before guard 19 (term bound)
    number = agreement["current_week_number"] + 1
    for week in weeks_of(agreement["id"]):
        if week["week_number"] == number:
            raise_error(E_WEEK_OVERLAP, "Two weekly periods would share one week number.")

    term_end = db.parse_iso(agreement["period_end"])
    if term_end is not None and end > term_end:
        raise_error(E_WEEK_OUTSIDE_AGREEMENT_TERM,
                    "The weekly period would extend past the agreement's period_end.")

    expected = payload.get("expected_agreement_version")
    check_agreement_version(agreement, expected)

    row = {
        "id": db.new_id(),
        "agreement_id": agreement["id"],
        "vehicle_id": agreement["vehicle_id"],
        "week_number": number,
        "period_start": start,
        "period_end": end,
        "miles_driven": 0,
        "base_charge_cents": 0,
        "insurance_charge_cents": 0,
        "mileage_overage_cents": 0,
        "damage_charge_cents": 0,
        "platform_credit_cents": 0,
        "amount_due_cents": 0,
        "week_status": "SCHEDULED",
        "payment_status": "UNPAID",
        "payment_deadline": None,
        "grace_deadline": None,
        "_settled_cents": 0,
        "operator_id": request.headers.get("X-User-ID"),
    }
    DB_STAMP(row)
    db.WEEKS[row["id"]] = row

    # the auto-transition inside this request: SCHEDULED -> OPEN
    row["week_status"] = "OPEN"
    row["period_start"] = start
    row["period_end"] = end
    compute_weekly_charge(row, agreement, final=False)
    db.touch(row)

    agreement["current_week_number"] = number
    agreement["agreement_status"] = "RENEWAL_DUE"
    db.touch(agreement)
    return ok(svc.week_out(row), 201)


@bp.get("/program/weeks")
def list_weeks():
    rows = by_created(db.WEEKS.values())
    for key in ("agreement_id", "vehicle_id", "week_status", "payment_status"):
        value = request.args.get(key)
        if value:
            rows = [r for r in rows if r[key] == value]
    page, limit, offset, total = paginate(rows)
    return ok_list([svc.week_out(r) for r in page], limit, offset, total)


@bp.get("/program/weeks/<week_id>")
def get_one_week(week_id):
    return ok(svc.week_out(get_week(week_id)))


@bp.post("/program/weeks/<week_id>/mileage")
def record_mileage(week_id):
    week = get_week(week_id)
    payload = get_body()
    check_schema(payload, "POST", "/program/weeks/{id}/mileage")
    miles = payload["miles_driven"]
    if not is_int(miles) or miles < 0:
        raise_error(E_INVALID_REQUEST, "miles_driven must be a non-negative integer.")
    week["miles_driven"] = miles
    agreement = db.AGREEMENTS[week["agreement_id"]]
    if week["week_status"] == "OPEN":
        compute_weekly_charge(week, agreement, final=False)
    db.touch(week)
    return ok(svc.week_out(week))


@bp.post("/program/weeks/<week_id>/settle")
def settle_week(week_id):
    week = get_week(week_id)
    agreement = db.AGREEMENTS[week["agreement_id"]]
    if agreement["compliance_posture"] == "FROZEN":
        raise_error(E_AGREEMENT_FROZEN, "The agreement's compliance posture is FROZEN.")
    if week["week_status"] != "OPEN":
        raise_error(E_INVALID_STATE, "Only an OPEN week may be settled.")

    compute_weekly_charge(week, agreement, final=True)
    damage_settlement_split(agreement)
    week["amount_due_cents"] = (week["base_charge_cents"] + week["insurance_charge_cents"]
                                + week["mileage_overage_cents"] + week["damage_charge_cents"]
                                - week["platform_credit_cents"])
    week["payment_deadline"] = week["period_end"]
    week["grace_deadline"] = week["period_end"] + db.hours(72)
    week["week_status"] = "DUE"
    db.touch(week)
    # settlement moves the lifecycle past the open period; the EUR receivable
    # it creates is then worked through the payment dimension (PRD 3.6)
    svc.refresh_agreement_status(agreement)
    return ok(svc.week_out(week))


def _record_payment(week, agreement, amount, outcome, retry):
    row = {
        "id": db.new_id(),
        "agreement_id": agreement["id"],
        "week_id": week["id"],
        "amount_cents": amount,
        "coverage_cents": 0,
        "platform_credit_cents": 0,
        "payment_outcome": outcome,
        "collected_at": db.now(),
        "operator_id": request.headers.get("X-User-ID"),
    }
    DB_STAMP(row)
    db.PAYMENTS[row["id"]] = row
    return row


@bp.post("/program/weeks/<week_id>/payments")
def tender_payment(week_id):
    week = get_week(week_id)
    agreement = db.AGREEMENTS[week["agreement_id"]]
    payload = get_body()
    check_schema(payload, "POST", "/program/weeks/{id}/payments")
    amount = payload["amount_cents"]
    outcome = payload["payment_outcome"]
    if not is_int(amount) or amount < 0:
        raise_error(E_INVALID_REQUEST, "amount_cents must be a non-negative integer.")
    if outcome not in ("SUCCEEDED", "FAILED"):
        raise_error(E_INVALID_REQUEST, "payment_outcome must be SUCCEEDED or FAILED.")

    if outcome == "FAILED":
        if week["payment_status"] not in ("UNPAID", "PARTIAL"):
            raise_error(E_INVALID_STATE, "A failed tender is only recorded against an unpaid week.")
        _record_payment(week, agreement, amount, outcome, False)
        week["payment_status"] = "FAILED"
        db.touch(week)
        return ok(svc.week_out(week), 201)

    due = week["amount_due_cents"]
    # A tender below the outstanding balance is an explicit partial tender: it
    # reduces the balance and leaves the remainder owing. A week that has already
    # been part-tendered, or a retry, is not a fresh tender at all, so a short
    # one there is refused with ERR_PAYMENT_BELOW_AMOUNT_DUE (PRD 3.6).
    is_partial = 0 < amount < due and week["payment_status"] == "UNPAID"

    if week["week_status"] not in ("DUE", "GRACE", "DELINQUENT"):
        raise_error(E_INVALID_STATE, "The week is not in a collectable state.")

    if amount < due and not is_partial:
        raise_error(E_PAYMENT_BELOW_AMOUNT_DUE,
                    "The tendered amount is below the outstanding amount due.")

    was_frozen = agreement["compliance_posture"] == "FROZEN"
    payment = _record_payment(week, agreement, amount, outcome, False)

    if is_partial:
        week["payment_status"] = "PARTIAL"
        week["amount_due_cents"] = due - amount
        payment["coverage_cents"] = amount
        db.touch(payment)
        db.touch(week)
        return ok(svc.week_out(week), 201)

    settled_total = week["_settled_cents"] + due
    week["payment_status"] = "SETTLED"
    # the week keeps the amount it was settled for, so billing totals and the
    # equity credit read the settled figure rather than a cleared balance
    week["amount_due_cents"] = settled_total
    week["_settled_cents"] = settled_total
    payment["coverage_cents"] = due
    payment["platform_credit_cents"] = week["platform_credit_cents"]
    db.touch(payment)
    if week["week_status"] in ("DUE", "GRACE", "DELINQUENT"):
        week["week_status"] = "PAID"
    agreement["total_billed_cents"] += due
    db.touch(agreement)
    db.touch(week)

    recompute_posture(agreement)
    recompute_equity_credit(agreement)

    if agreement["agreement_status"] == "RECOVERY_PENDING":
        # a full cure pulls the agreement back out of recovery: with nothing
        # left outstanding the unit returns to the road and, once the posture
        # has left FROZEN, the driver's standing is restored with it (PRD 3.8)
        if outstanding_delinquent_weeks(agreement["id"]) == 0:
            vehicle = db.VEHICLES.get(agreement["vehicle_id"])
            if vehicle is not None and vehicle["vehicle_status"] == "RECOVERY":
                vehicle["vehicle_status"] = "ASSIGNED"
                vehicle["assigned_driver_id"] = agreement["driver_id"]
                db.touch(vehicle)
            agreement["agreement_status"] = "ACTIVE"
            db.touch(agreement)
            if agreement["compliance_posture"] != "FROZEN":
                svc.restore_driver_standing(agreement)
    svc.refresh_agreement_status(agreement)
    return ok(svc.week_out(week), 201)


@bp.post("/program/weeks/<week_id>/retry-payment")
def retry_payment(week_id):
    week = get_week(week_id)
    agreement = db.AGREEMENTS[week["agreement_id"]]
    payload = get_body()
    check_schema(payload, "POST", "/program/weeks/{id}/retry-payment")
    amount = payload["amount_cents"]
    outcome = payload["payment_outcome"]
    if not is_int(amount) or amount < 0:
        raise_error(E_INVALID_REQUEST, "amount_cents must be a non-negative integer.")
    if outcome not in ("SUCCEEDED", "FAILED"):
        raise_error(E_INVALID_REQUEST, "payment_outcome must be SUCCEEDED or FAILED.")
    if week["payment_status"] != "FAILED":
        raise_error(E_INVALID_STATE, "Only a FAILED week may be retried.")

    due = week["amount_due_cents"]
    if not is_int(amount) or amount < 0:
        raise_error(E_INVALID_REQUEST, "amount_cents must be a non-negative integer.")

    was_frozen = agreement["compliance_posture"] == "FROZEN"
    payment = _record_payment(week, agreement, amount, outcome, True)
    if outcome == "FAILED":
        db.touch(week)
        return ok(svc.week_out(week))

    if amount < due:
        week["payment_status"] = "UNPAID"
        payment["coverage_cents"] = amount
        db.touch(payment)
        db.touch(week)
        return ok(svc.week_out(week))

    settled_total = week["_settled_cents"] + due
    week["payment_status"] = "SETTLED"
    week["amount_due_cents"] = settled_total
    week["_settled_cents"] = settled_total
    payment["coverage_cents"] = due
    payment["platform_credit_cents"] = week["platform_credit_cents"]
    db.touch(payment)
    if week["week_status"] in ("DUE", "GRACE", "DELINQUENT"):
        week["week_status"] = "PAID"
    agreement["total_billed_cents"] += due
    db.touch(agreement)
    db.touch(week)
    recompute_posture(agreement)
    recompute_equity_credit(agreement)
    svc.refresh_agreement_status(agreement)
    return ok(svc.week_out(week))


@bp.post("/program/weeks/<week_id>/grace-lapse")
def grace_lapse(week_id):
    week = get_week(week_id)
    agreement = db.AGREEMENTS[week["agreement_id"]]
    if week["week_status"] != "GRACE":
        raise_error(E_INVALID_STATE, "Only a week in GRACE may be declared delinquent.")
    deadline = db.parse_iso(week["grace_deadline"])
    if deadline is None or db.now() < deadline:
        raise_error(E_GRACE_NOT_LAPSED, "The logical clock is before the grace deadline.")

    week["week_status"] = "DELINQUENT"
    week["payment_status"] = "FAILED"
    db.touch(week)
    was_frozen = agreement["compliance_posture"] == "FROZEN"
    agreement["agreement_status"] = "DELINQUENT"
    db.touch(agreement)
    recompute_posture(agreement)
    svc.refresh_agreement_status(agreement)
    return ok(svc.week_out(week))


@bp.post("/program/weeks/<week_id>/waive")
def waive_week(week_id):
    week = get_week(week_id)
    agreement = db.AGREEMENTS[week["agreement_id"]]
    if week["week_status"] not in ("DUE", "GRACE", "DELINQUENT"):
        raise_error(E_INVALID_STATE, "The week is not in a waivable state.")
    for option in all_of(db.PURCHASE_OPTIONS, lambda o: o["agreement_id"] == agreement["id"]):
        if option["option_status"] == "ELECTED":
            raise_error(E_INVALID_STATE, "A purchase option on the agreement is ELECTED.")

    was_frozen = agreement["compliance_posture"] == "FROZEN"
    week["week_status"] = "WAIVED"
    db.touch(week)
    agreement["total_waived_cents"] += week["amount_due_cents"]
    db.touch(agreement)
    recompute_posture(agreement)
    recompute_equity_credit(agreement)
    svc.refresh_agreement_status(agreement)
    return ok(svc.week_out(week))


@bp.post("/program/weeks/<week_id>/reopen")
def reopen_week(week_id):
    week = get_week(week_id)
    agreement = db.AGREEMENTS[week["agreement_id"]]
    driver = db.DRIVERS.get(agreement["driver_id"])
    if week["week_status"] != "DELINQUENT":
        raise_error(E_INVALID_STATE, "Only a DELINQUENT week may be reopened.")
    if agreement["compliance_posture"] != "RESTRICTED":
        raise_error(E_INVALID_STATE, "The agreement's posture is not RESTRICTED.")
    if driver is None or driver["eligibility_status"] != "ELIGIBLE":
        raise_error(E_INVALID_STATE, "The driver is not in ELIGIBLE standing.")

    week["week_status"] = "OPEN"
    week["payment_status"] = "UNPAID"
    week["payment_deadline"] = db.now() + db.days(7)
    week["grace_deadline"] = week["payment_deadline"] + db.hours(72)
    db.touch(week)
    recompute_posture(agreement)
    svc.refresh_agreement_status(agreement)
    return ok(svc.week_out(week))


# --- Logical clock ------------------------------------------------------------

@bp.post("/program/_clock/set_current_utc")
def set_clock():
    payload = get_body()
    check_schema(payload, "POST", "/program/_clock/set_current_utc")
    instant = db.parse_iso(payload["to_iso8601"])
    if instant is None:
        raise_error(E_INVALID_REQUEST, "to_iso8601 must be an ISO 8601 instant.")
    db.set_clock(instant)
    svc.advance_time_gates()
    return ok({"current_utc": db.now_iso()})