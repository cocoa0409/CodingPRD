"""Cattle lots, receiving and scale tickets."""
from datetime import timedelta

from flask import Blueprint, request

from common import (authenticate, body_of, day_of, parse_dt, req_dt_str,
                    req_enum, req_int, req_num, req_str, whole_days)
from derive import (contract_of_lot, pasture_of_contract, recompute_pasture,
                    shrunk_weight, sorted_records, treatments_of_lot)
from envelope import created, listing, ok, pagination, public, public_list
from errors import ApiError
from routes.contracts import get_contract
from store import db, new_record, touch

bp = Blueprint("lots", __name__)

ALL_ROLES = ("Grazier", "CattleOwner", "RangeConsultant", "PlatformAdmin")
POSTABLE_EVENT_TYPES = ("INTERIM", "OUT")
WITHDRAWAL_BLOCKING = ("RECORDED", "DISPUTED", "APPROVED")


def get_lot(lot_id):
    lot = db.lots.get(lot_id)
    if lot is None:
        raise ApiError("ERR_LOT_NOT_FOUND", "Lot does not exist.")
    return lot


@bp.post("/grazing/contracts/<contract_id>/lots")
def book_lot(contract_id):
    actor = authenticate(("Grazier",))
    contract = get_contract(contract_id)
    body = body_of()
    scheduled_head_count = req_int(body, "scheduled_head_count", gt=0)
    scheduled_delivery_date = req_dt_str(body, "scheduled_delivery_date")

    if contract["grazier_id"] != actor.user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Only the contract's grazier may book a delivery.")

    if contract["lifecycle_status"] != "ACTIVE":
        raise ApiError("ERR_CONTRACT_INVALID_STATE",
                       "A delivery may only be booked against an ACTIVE contract.")

    pasture = pasture_of_contract(contract)
    if pasture["grazing_posture"] != "OPEN":
        raise ApiError("ERR_PASTURE_POSTURE_BLOCKED",
                       "The pasture's grazing posture is %s." % pasture["grazing_posture"])

    rec = new_record()
    rec.update({
        "contract_id": contract["id"],
        "scheduled_head_count": scheduled_head_count,
        "scheduled_delivery_date": scheduled_delivery_date,
        "head_count_received": 0,
        "gross_weight_in_lbs": 0,
        "shrunk_weight_in_lbs": 0,
        "in_date": None,
        "head_count_out": 0,
        "gross_weight_out_lbs": 0,
        "shrunk_weight_out_lbs": 0,
        "out_date": None,
        "confirmed_death_head": 0,
        "days_on_feed": 0,
        "scheduled_removal_date": None,
        "status": "SCHEDULED",
    })
    db.lots[rec["id"]] = rec
    return created(public(rec))


@bp.get("/grazing/contracts/<contract_id>/lots")
def list_contract_lots(contract_id):
    authenticate(ALL_ROLES)
    contract = get_contract(contract_id)
    limit, offset = pagination()
    rows = [l for l in sorted_records(db.lots.values()) if l["contract_id"] == contract["id"]]
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return listing(public_list(rows), limit, offset)


@bp.get("/grazing/lots/<lot_id>")
def read_lot(lot_id):
    authenticate(ALL_ROLES)
    return ok(public(get_lot(lot_id)))


@bp.post("/grazing/lots/<lot_id>/receive")
def receive_lot(lot_id):
    actor = authenticate(("Grazier",))
    lot = get_lot(lot_id)
    body = body_of()
    head_count_received = req_int(body, "head_count_received", gt=0)
    gross_weight_lbs = req_num(body, "gross_weight_lbs", gt=0)
    scale_ticket_ref = req_str(body, "scale_ticket_ref")
    received_at = req_dt_str(body, "received_at")

    contract = contract_of_lot(lot)
    if contract["grazier_id"] != actor.user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Only the contract's grazier may receive this lot.")

    if lot["status"] != "SCHEDULED":
        raise ApiError("ERR_LOT_INVALID_STATE", "Receiving is only declared from SCHEDULED.")
    if contract["lifecycle_status"] != "ACTIVE":
        raise ApiError("ERR_CONTRACT_INVALID_STATE", "The contract is not ACTIVE.")

    pasture = pasture_of_contract(contract)
    if pasture["grazing_posture"] != "OPEN":
        raise ApiError("ERR_PASTURE_POSTURE_BLOCKED",
                       "The pasture's grazing posture is %s." % pasture["grazing_posture"])

    shrink_pct = contract["shrink_pct"]
    shrunk = shrunk_weight(gross_weight_lbs, shrink_pct)

    event = new_record(common_fields=False)
    event.update({
        "lot_id": lot["id"],
        "event_type": "IN",
        "gross_weight_lbs": gross_weight_lbs,
        "head_count": head_count_received,
        "scale_ticket_ref": scale_ticket_ref,
        "weighed_at": received_at,
        "shrink_pct_applied": shrink_pct,
        "shrunk_weight_lbs": shrunk,
    })
    db.weight_events[event["id"]] = event

    lot["head_count_received"] = head_count_received
    lot["gross_weight_in_lbs"] = gross_weight_lbs
    lot["shrunk_weight_in_lbs"] = shrunk
    lot["in_date"] = received_at
    lot["status"] = "ON_FEED"
    touch(lot)
    recompute_pasture(pasture)
    return ok(public(lot))


@bp.post("/grazing/lots/<lot_id>/weight-events")
def record_weight_event(lot_id):
    actor = authenticate(("Grazier",))
    lot = get_lot(lot_id)
    body = body_of()
    event_type = req_enum(body, "event_type", POSTABLE_EVENT_TYPES)
    gross_weight_lbs = req_num(body, "gross_weight_lbs", gt=0)
    head_count = req_int(body, "head_count", gt=0)
    scale_ticket_ref = req_str(body, "scale_ticket_ref")
    weighed_at = req_dt_str(body, "weighed_at")

    contract = contract_of_lot(lot)
    if contract["grazier_id"] != actor.user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Only the contract's grazier may weigh this lot.")

    if lot["status"] not in ("ON_FEED", "REMOVAL_SCHEDULED"):
        raise ApiError("ERR_LOT_INVALID_STATE",
                       "A scale ticket may only be posted against a lot on feed.")

    if event_type == "OUT":
        weigh_day = day_of(weighed_at)
        for treatment in treatments_of_lot(lot["id"]):
            if treatment["status"] not in WITHDRAWAL_BLOCKING:
                continue
            start = day_of(treatment["treatment_date"])
            if start is None:
                continue
            end = start + timedelta(days=treatment["withdrawal_days"])
            if start <= weigh_day <= end:
                raise ApiError("ERR_WITHDRAWAL_PERIOD_ACTIVE",
                               "The weigh-out falls inside a live drug withdrawal interval.")

        alive = (lot["head_count_received"] or 0) - (lot["confirmed_death_head"] or 0)
        if head_count > alive:
            raise ApiError("ERR_HEAD_COUNT_INCONSISTENT",
                           "The OUT head count exceeds the head still alive on the lot.")

    shrink_pct = contract["out_shrink_pct"]
    shrunk = shrunk_weight(gross_weight_lbs, shrink_pct)

    event = new_record(common_fields=False)
    event.update({
        "lot_id": lot["id"],
        "event_type": event_type,
        "gross_weight_lbs": gross_weight_lbs,
        "head_count": head_count,
        "scale_ticket_ref": scale_ticket_ref,
        "weighed_at": weighed_at,
        "shrink_pct_applied": shrink_pct,
        "shrunk_weight_lbs": shrunk,
    })
    db.weight_events[event["id"]] = event

    if event_type == "OUT":
        lot["head_count_out"] = head_count
        lot["gross_weight_out_lbs"] = gross_weight_lbs
        lot["shrunk_weight_out_lbs"] = shrunk
        lot["out_date"] = weighed_at
        lot["days_on_feed"] = whole_days(weighed_at, lot["in_date"]) if lot["in_date"] else 0
        lot["status"] = "WEIGHED_OUT"
        touch(lot)
        recompute_pasture(pasture_of_contract(contract))

    return created(public(event))


@bp.get("/grazing/lots/<lot_id>/weight-events")
def list_weight_events(lot_id):
    authenticate(ALL_ROLES)
    lot = get_lot(lot_id)
    limit, offset = pagination()
    rows = [w for w in db.weight_events.values() if w["lot_id"] == lot["id"]]
    rows.sort(key=lambda w: (parse_dt(w["weighed_at"]), w["_seq"]))
    event_type = request.args.get("event_type")
    if event_type is not None:
        rows = [r for r in rows if r["event_type"] == event_type]
    return listing(public_list(rows), limit, offset)
