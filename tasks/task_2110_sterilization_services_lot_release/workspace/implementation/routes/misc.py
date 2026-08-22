"""Residual testing, adverse-event disposition and the logical clock."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

import clock
import response
import validation as V
from db import db
from errors import ApiError
from middleware import authenticate
from routes.common import fetch
from services import calc
from services.domain import (by_seq, new_record, recompute_open_lot_count, touch)

bp = Blueprint("misc", __name__)


# =====================================================================
# Residual test (PRD 3.8)
# =====================================================================
@bp.post("/sterilization/aeration-records/<record_id>/residual-test")
def record_residual_test(record_id):
    authenticate("DosimetryAnalyst")
    body = V.body()
    eto_ppm = V.req_number(body, "eto_residual_ppm", ge=0)
    ech_ppm = V.req_number(body, "ech_residual_ppm", ge=0)

    record = fetch("aeration_records", record_id)

    # priority 45 - a settled record accepts no further samples
    if record["status"] in ("PASSED", "EXHAUSTED"):
        raise ApiError("ERR_RETEST_LIMIT_EXHAUSTED")

    # priority 80 - the laboratory may not sample early
    if clock.now() < record["target_end_at"]:
        raise ApiError("ERR_AERATION_INCOMPLETE",
                       "The aeration target end has not been reached.")

    lot = db.lots.get(record["lot_id"])
    product = db.products.get(lot["product_id"]) if lot else None

    record["last_eto_ppm"] = eto_ppm
    record["last_ech_ppm"] = ech_ppm

    passed = (product is not None
              and eto_ppm <= calc.dec(product["eto_residual_limit_ppm"])
              and ech_ppm <= calc.dec(product["ech_residual_limit_ppm"]))

    if passed:
        record["status"] = "PASSED"
        touch(record)
        if lot is not None:
            lot["residual_status"] = "RESIDUAL_PASS"
            touch(lot)
        return response.object_response(record)

    new_count = record["retest_count"] + 1
    record["retest_count"] = new_count
    if new_count <= calc.MAX_RESIDUAL_RETESTS:
        failed_at = clock.now()
        record["last_failed_sample_at"] = failed_at
        record["variant_applied"] = "EXTENDED_RETEST"
        record["required_hours"] = calc.required_hours_extended(
            record["base_hours"], record["density_factor"], new_count)
        record["target_end_at"] = failed_at + timedelta(hours=record["required_hours"])
        record["status"] = "RETEST_REQUIRED"
        touch(record)
        return response.object_response(record)

    record["status"] = "EXHAUSTED"
    touch(record)
    if lot is not None:
        lot["residual_status"] = "RESIDUAL_FAIL"
        if lot["status"] == "QUARANTINE":
            lot["status"] = "REJECTED"
            lot["quarantine_reason"] = "RESIDUAL_FAIL"
        touch(lot)
        recompute_open_lot_count(lot["customer_id"])
    return response.object_response(record)


# =====================================================================
# Adverse-event disposition (PRD 3.9)
# =====================================================================
@bp.post("/sterilization/adverse-events/<event_id>/disposition")
def disposition_adverse_event(event_id):
    authenticate("QualityReleaseOfficer")
    body = V.body()
    disposition = V.req_enum(body, "disposition", ("RESTERILIZE", "SCRAP", "DISMISS"))

    event = fetch("adverse_events", event_id)
    lot = db.lots.get(event["lot_id"])

    # priority 45 - the event and the subject lot must both admit the transition
    if event["status"] != "REPORTED":
        raise ApiError("ERR_INVALID_STATE", "This event has already been dispositioned.")
    if lot is None:
        raise ApiError("ERR_INVALID_STATE", "The subject lot no longer exists.")
    if disposition == "RESTERILIZE" and lot["status"] != "RELEASED":
        raise ApiError("ERR_INVALID_STATE",
                       "RESTERILIZE is only available for a RELEASED lot.")
    if disposition == "SCRAP" and lot["status"] not in ("RELEASED", "QUARANTINE"):
        raise ApiError("ERR_INVALID_STATE",
                       "SCRAP is only available for a RELEASED or QUARANTINE lot.")

    event["disposition"] = disposition

    if disposition == "DISMISS":
        event["status"] = "DISMISSED"
        touch(event)
        if lot["status"] == "QUARANTINE" and lot["quarantine_reason"] == "ADVERSE_EVENT":
            lot["quarantine_reason"] = "ROUTINE"
            touch(lot)
        return response.object_response(event)

    if disposition == "SCRAP":
        event["status"] = "SCRAP_APPROVED"
        touch(event)
        lot["status"] = "SCRAPPED"
        lot["schedulable"] = False
        touch(lot)
        recompute_open_lot_count(lot["customer_id"])
        return response.object_response(event)

    # ---- RESTERILIZE: CASCADE B ----
    event["status"] = "RESTERILIZE_APPROVED"
    touch(event)

    # hop two
    successor = new_record({
        "customer_id": lot["customer_id"],
        "product_id": lot["product_id"],
        "parent_lot_id": lot["id"],
        "lot_code": "%s-R%d" % (lot["lot_code"], lot["resterilization_count"] + 1),
        "total_pallet_count": lot["total_pallet_count"],
        "staged_pallet_count": 0,
        "available_pallet_count": lot["total_pallet_count"],
        "status": "RECEIVED",
        "residual_status": "NOT_APPLICABLE",
        "quarantine_reason": "NONE",
        "cumulative_dose_kgy": lot["cumulative_dose_kgy"],
        "resterilization_count": lot["resterilization_count"] + 1,
        "schedulable": True,
        "release_mode": "NONE",
        "released_at": None,
        "released_by_user_id": None,
        "release_dose_kgy": None,
    })
    db.lots[successor["id"]] = successor

    lot["status"] = "RECALLED"
    lot["quarantine_reason"] = "ADVERSE_EVENT"
    touch(lot)

    # hop three - the successor arrives carrying a dose burden
    product = db.products.get(successor["product_id"])
    blocked = False
    for qualification in by_seq([q for q in db.qualifications.values()
                                if q["product_id"] == successor["product_id"]]):
        if qualification["status"] not in ("QUALIFIED", "CONDITIONAL"):
            continue
        recipe = db.recipes.get(qualification["recipe_id"])
        if recipe is None or product is None:
            continue
        projected = calc.round_dose(calc.dec(successor["cumulative_dose_kgy"])
                                    + calc.dec(recipe["target_dose_kgy"]))
        if projected > calc.dec(product["max_cumulative_dose_kgy"]):
            qualification["status"] = "SUSPENDED"
            qualification["next_audit_due_at"] = None
            touch(qualification)
            blocked = True
    if blocked:
        successor["schedulable"] = False
        touch(successor)

    recompute_open_lot_count(lot["customer_id"])
    return response.object_response(event)


# =====================================================================
# Logical clock (PRD 2.4)
# =====================================================================
@bp.post("/sterilization/_clock/set_current_utc")
def set_clock():
    authenticate("RegulatoryAdmin")
    body = V.body()
    instant = V.req_datetime(body, "to_iso8601")
    clock.set_now(instant)
    return response.empty_response()
