"""Purchase option endpoints."""

from flask import Blueprint, request

import db
import services as svc
from db import stamp_created as DB_STAMP
from errors import (E_AGREEMENT_FROZEN, E_ESCROW_INCOMPLETE, E_INVALID_REQUEST, E_INVALID_STATE,
                    E_POSTURE_NOT_OPEN, E_PURCHASE_BLOCKED_BY_DELINQUENCY,
                    E_REFERENCED_ENTITY_NOT_FOUND, E_UNAUTHORIZED, raise_error)
from middleware import check_schema, is_int
from middleware import body as get_body
from response import ok, ok_list
from services import (all_of, by_created, check_agreement_version, get_agreement, get_option,
                      paginate, recompute_equity_credit, recompute_escrow_schedule, weeks_of)

bp = Blueprint("purchases", __name__)

OPTION_STATUSES = ("OFFERED", "ELECTED", "ESCROW_FUNDED", "COMPLETED", "WITHDRAWN")


@bp.post("/program/purchase-options")
def create_option():
    payload = get_body()
    check_schema(payload, "POST", "/program/purchase-options")
    agreement_id = payload["agreement_id"]
    driver_id = payload["driver_id"]
    if agreement_id not in db.AGREEMENTS:
        raise_error(E_REFERENCED_ENTITY_NOT_FOUND, "agreement_id does not name an agreement.")
    if driver_id not in db.DRIVERS:
        raise_error(E_REFERENCED_ENTITY_NOT_FOUND, "driver_id does not name a driver.")
    agreement = db.AGREEMENTS[agreement_id]
    price = payload["purchase_price_cents"]
    if not is_int(price) or price < 0:
        raise_error(E_INVALID_REQUEST, "purchase_price_cents must be a non-negative integer.")
    weeks_required = payload["escrow_weeks_required"]
    if not is_int(weeks_required) or weeks_required < 1:
        raise_error(E_INVALID_REQUEST, "escrow_weeks_required must be at least 1.")
    if agreement["compliance_posture"] != "OPEN":
        raise_error(E_POSTURE_NOT_OPEN,
                    "A purchase option may only be offered on an OPEN agreement.")

    row = {
        "id": db.new_id(),
        "agreement_id": agreement_id,
        "driver_id": driver_id,
        "option_status": "OFFERED",
        "purchase_price_cents": price,
        "equity_credit_cents": 0,
        "escrow_required_cents": 0,
        "escrow_balance_cents": 0,
        "escrow_weeks_required": weeks_required,
        "escrow_weeks_funded": 0,
        "elected_at": None,
        "operator_id": request.headers.get("X-User-ID"),
    }
    DB_STAMP(row)
    db.PURCHASE_OPTIONS[row["id"]] = row
    recompute_equity_credit(agreement)
    return ok(svc.option_out(row), 201)


@bp.get("/program/purchase-options")
def list_options():
    rows = by_created(db.PURCHASE_OPTIONS.values())
    for key in ("agreement_id", "driver_id", "option_status"):
        value = request.args.get(key)
        if value:
            rows = [r for r in rows if r[key] == value]
    page, limit, offset, total = paginate(rows)
    return ok_list([svc.option_out(r) for r in page], limit, offset, total)


@bp.get("/program/purchase-options/<option_id>")
def get_one_option(option_id):
    return ok(svc.option_out(get_option(option_id)))


def _own(option, role, actor):
    if role == "Driver" and str(actor) != str(option["driver_id"]):
        raise_error(E_UNAUTHORIZED, "The acting driver does not own this purchase option.")


@bp.post("/program/purchase-options/<option_id>/elect")
def elect_option(option_id):
    option = get_option(option_id)
    payload = get_body()
    check_schema(payload, "POST", "/program/purchase-options/{id}/elect")
    _own(option, request.headers.get("X-User-Role"), request.headers.get("X-User-ID"))
    agreement = get_agreement(option["agreement_id"])
    if option["option_status"] != "OFFERED":
        raise_error(E_INVALID_STATE, "Only an OFFERED option may be elected.")
    # guard 8 (freeze) is evaluated before guard 9 (posture openness)
    if agreement["compliance_posture"] == "FROZEN":
        raise_error(E_AGREEMENT_FROZEN, "The agreement's compliance posture is FROZEN.")
    if agreement["compliance_posture"] != "OPEN":
        raise_error(E_POSTURE_NOT_OPEN, "The agreement's compliance posture is not OPEN.")
    if svc.outstanding_delinquent_weeks(agreement["id"]) > 0 or any(
            w["week_status"] == "DELINQUENT" for w in weeks_of(agreement["id"])):
        raise_error(E_PURCHASE_BLOCKED_BY_DELINQUENCY,
                    "A week of the agreement is delinquent.")
    # A live agreement is either ACTIVE or waiting on its open week
    # (RENEWAL_DUE); both are admissible, every other status is not.
    if agreement["agreement_status"] not in ("ACTIVE", "RENEWAL_DUE"):
        raise_error(E_INVALID_STATE, "The agreement may not enter the purchase stream.")
    check_agreement_version(agreement, payload.get("expected_agreement_version"))

    option["option_status"] = "ELECTED"
    option["elected_at"] = db.now()
    db.touch(option)

    for week in weeks_of(agreement["id"]):
        if week["week_status"] == "OPEN":
            week["week_status"] = "DEFERRED"
            db.touch(week)

    agreement["agreement_status"] = "PURCHASE_PENDING"
    db.touch(agreement)
    recompute_escrow_schedule(option)
    db.touch(option)
    return ok(svc.option_out(option))


@bp.post("/program/purchase-options/<option_id>/fund-escrow")
def fund_escrow(option_id):
    option = get_option(option_id)
    _own(option, request.headers.get("X-User-Role"), request.headers.get("X-User-ID"))
    if option["option_status"] not in ("ELECTED", "ESCROW_FUNDED"):
        raise_error(E_INVALID_STATE, "The option is not accepting escrow funding.")
    if option["escrow_weeks_funded"] >= option["escrow_weeks_required"]:
        raise_error(E_INVALID_STATE, "The required escrow weeks are already funded.")
    agreement = get_agreement(option["agreement_id"])

    option["escrow_balance_cents"] += option["escrow_required_cents"]
    option["escrow_weeks_funded"] += 1
    option["option_status"] = "ESCROW_FUNDED"
    db.touch(option)
    recompute_equity_credit(agreement)
    agreement["version"] += 1
    db.touch(agreement)
    return ok(svc.option_out(option))


@bp.post("/program/purchase-options/<option_id>/withdraw")
def withdraw_option(option_id):
    option = get_option(option_id)
    _own(option, request.headers.get("X-User-Role"), request.headers.get("X-User-ID"))
    if option["option_status"] not in ("OFFERED", "ELECTED", "ESCROW_FUNDED"):
        raise_error(E_INVALID_STATE, "This option may not be withdrawn.")
    agreement = get_agreement(option["agreement_id"])

    if option["option_status"] in ("ELECTED", "ESCROW_FUNDED"):
        for week in weeks_of(agreement["id"]):
            if week["week_status"] == "DEFERRED":
                week["week_status"] = "OPEN"
                week["payment_deadline"] = db.now() + db.days(7)
                week["grace_deadline"] = week["payment_deadline"] + db.hours(72)
                db.touch(week)
        if agreement["agreement_status"] == "PURCHASE_PENDING":
            agreement["agreement_status"] = "ACTIVE"
            db.touch(agreement)

    option["option_status"] = "WITHDRAWN"
    db.touch(option)
    return ok(svc.option_out(option))


@bp.post("/program/purchase-options/<option_id>/complete")
def complete_option(option_id):
    option = get_option(option_id)
    agreement = get_agreement(option["agreement_id"])
    if option["option_status"] not in ("ELECTED", "ESCROW_FUNDED"):
        raise_error(E_INVALID_STATE, "The option is not in a completable state.")
    if option["escrow_weeks_funded"] < option["escrow_weeks_required"]:
        raise_error(E_ESCROW_INCOMPLETE, "The required escrow weeks are not yet funded.")
    if option["escrow_balance_cents"] + option["equity_credit_cents"] < option["purchase_price_cents"]:
        raise_error(E_ESCROW_INCOMPLETE, "Escrow and equity do not cover the purchase price.")

    option["option_status"] = "COMPLETED"
    db.touch(option)
    vehicle = db.VEHICLES.get(agreement["vehicle_id"])
    if vehicle is not None:
        vehicle["vehicle_status"] = "RETIRED"
        vehicle["assigned_driver_id"] = None
        db.touch(vehicle)
    agreement["agreement_status"] = "PURCHASED"
    db.touch(agreement)
    return ok(svc.option_out(option))