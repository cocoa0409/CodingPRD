"""Movement reporting, arrival, dispute, correction and voiding (PRD 3.5)."""
from flask import Blueprint

import calc
import derive
import shape
from authz import (PRODUCER, PROGRAM_ADMIN, STATE_OFFICIAL, TRACE_ANALYST,
                   require_owner, require_roles)
from db import base_record, store, touch
from errors import conflict, invalid_state, unprocessable
from respond import success
from routes._common import (animal_or_404, movement_or_404, page, premises_or_404)
from serialize import public
from timeutil import hours_between

bp = Blueprint("movements", __name__)


def _recompute_timeliness(movement):
    lag, on_time = calc.reporting_lag(hours_between(movement["reported_at"],
                                                    movement["departed_at"]))
    movement["reporting_lag_hours"] = lag
    movement["on_time"] = on_time


def _movement_sighting(movement_id, sighting_type, only_live=True):
    for s in store.sightings.values():
        if s["source_movement_id"] != movement_id or s["sighting_type"] != sighting_type:
            continue
        if only_live and s["reversed"]:
            continue
        return s
    return None


@bp.post("/movement-events")
def report_movement():
    uid, role = require_roles(PRODUCER)
    body = shape.body()
    animal_id = shape.s_str(body, "animal_id")
    origin_id = shape.s_str(body, "origin_premises_id")
    destination_id = shape.s_str(body, "destination_premises_id")
    departed_at = shape.s_instant(body, "departed_at")
    icvi_number = shape.s_str(body, "icvi_number", required=False)
    animal = animal_or_404(animal_id)
    origin = premises_or_404(origin_id)
    destination = premises_or_404(destination_id)
    # Band 6 - the departure end belongs to the acting producer.
    require_owner(origin["producer_id"] == uid)
    # Band 10 - own-state gate on the animal.
    if animal["lifecycle_status"] != "ACTIVE":
        raise invalid_state("The animal is not ACTIVE")
    # Band 11 - cross-entity state gates on the origin.
    if origin["registration_status"] != "ACTIVE":
        raise conflict("ERR_PREMISES_NOT_ACTIVE", "The origin premises registration is not ACTIVE")
    if origin["health_status"] == "QUARANTINED":
        raise conflict("ERR_PREMISES_UNDER_HOLD", "The origin premises is under quarantine")
    # Band 12 - regulatory interval safety.
    interstate = origin["state_code"] != destination["state_code"]
    if interstate and not icvi_number:
        raise conflict("ERR_ICVI_REQUIRED", "An interstate movement requires an icvi_number")
    # Band 13 - cross-field temporal checks.
    now = store.now()
    if departed_at > now:
        raise unprocessable("ERR_FUTURE_TIMESTAMP", "departed_at is later than the logical clock")
    latest = derive.latest_observed_at(animal["id"])
    if latest is not None and departed_at < latest:
        raise unprocessable("ERR_BACKDATED_EVENT",
                            "departed_at precedes the animal's latest observation")
    # Band 14 - referential coherence.
    if origin["id"] == destination["id"]:
        raise unprocessable("ERR_SAME_PREMISES_MOVE",
                            "The origin and destination premises must differ")
    if animal["current_premises_id"] != origin["id"]:
        raise unprocessable("ERR_ANIMAL_NOT_AT_PREMISES",
                            "The animal does not currently stand at the origin premises")

    rec = base_record()
    rec.update({
        "animal_id": animal["id"],
        "origin_premises_id": origin["id"],
        "destination_premises_id": destination["id"],
        "departed_at": departed_at,
        "arrived_at": None,
        "reported_at": now,
        "icvi_number": icvi_number,
        "interstate": interstate,
        "status": "REPORTED",
        "reporting_lag_hours": None,
        "on_time": None,
        "correction_count": 0,
    })
    _recompute_timeliness(rec)
    store.movements[rec["id"]] = rec

    derive.append_sighting(animal, origin["id"], "DEPARTURE", departed_at,
                           source_movement_id=rec["id"])
    derive.reproject_animal(animal)
    derive.recompute_premises_animal_count([origin["id"]])
    derive.mark_producer(origin["producer_id"], on_time=True)
    return success(public(rec), status=201)


@bp.get("/movement-events/<movement_id>")
def read_movement(movement_id):
    require_roles(PRODUCER, PROGRAM_ADMIN, STATE_OFFICIAL, TRACE_ANALYST)
    return success(public(movement_or_404(movement_id)))


@bp.get("/movement-events")
def list_movements():
    require_roles(PRODUCER, PROGRAM_ADMIN, STATE_OFFICIAL, TRACE_ANALYST)
    limit, offset = shape.pagination_params()
    rows = list(store.movements.values())
    for field in ("animal_id", "origin_premises_id", "destination_premises_id", "status"):
        value = shape.q(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    on_time = shape.q_bool("on_time")
    if on_time is not None:
        rows = [r for r in rows if bool(r["on_time"]) is on_time]
    return page(rows, limit, offset)


@bp.post("/movement-events/<movement_id>/receive")
def receive_movement(movement_id):
    uid, role = require_roles(PRODUCER)
    body = shape.body()
    arrived_at = shape.s_instant(body, "arrived_at")
    movement = movement_or_404(movement_id)
    destination = store.premises.get(movement["destination_premises_id"])
    # Band 6 - arrival is confirmed by the receiving producer.
    require_owner(destination is not None and destination["producer_id"] == uid)
    # Band 10 - own-state gate.
    if movement["status"] != "REPORTED":
        raise invalid_state("Only a REPORTED movement may be received")
    # Band 11 - cross-entity state gates on the destination.
    if destination["registration_status"] != "ACTIVE":
        raise conflict("ERR_PREMISES_NOT_ACTIVE",
                       "The destination premises registration is not ACTIVE")
    if destination["health_status"] == "QUARANTINED":
        raise conflict("ERR_PREMISES_UNDER_HOLD", "The destination premises is under quarantine")
    # Band 13 - cross-field temporal checks.
    if arrived_at < movement["departed_at"]:
        raise unprocessable("ERR_INVALID_WINDOW", "arrived_at may not precede departed_at")
    if arrived_at > store.now():
        raise unprocessable("ERR_FUTURE_TIMESTAMP", "arrived_at is later than the logical clock")
    # Band 16 - capacity, against pre-request state.
    if destination["animal_count"] + 1 > destination["capacity"]:
        raise conflict("ERR_PREMISES_AT_CAPACITY",
                       "Admitting one more animal would exceed the premises capacity")

    # CASCADE-A.
    movement["status"] = "RECEIVED"
    movement["arrived_at"] = arrived_at
    touch(movement)
    animal = store.animals.get(movement["animal_id"])
    if animal is not None:
        previous = animal["current_premises_id"]
        derive.append_sighting(animal, destination["id"], "ARRIVAL", arrived_at,
                               source_movement_id=movement["id"])
        derive.reproject_animal(animal)
        derive.recompute_premises_animal_count([previous, destination["id"]])
    return success(public(movement))


@bp.post("/movement-events/<movement_id>/dispute")
def dispute_movement(movement_id):
    require_roles(STATE_OFFICIAL)
    body = shape.body()
    shape.s_str(body, "reason", required=False)
    movement = movement_or_404(movement_id)
    if movement["status"] not in ("REPORTED", "RECEIVED"):
        raise invalid_state("Only a REPORTED or RECEIVED movement may be disputed")
    was_received = movement["status"] == "RECEIVED"
    movement["status"] = "DISPUTED"
    touch(movement)
    if was_received:
        # Conditional cascade: the arrival is retracted.
        arrival = _movement_sighting(movement["id"], "ARRIVAL")
        animal = store.animals.get(movement["animal_id"])
        if arrival is not None and animal is not None:
            arrival["reversed"] = True
            previous = animal["current_premises_id"]
            derive.reproject_animal(animal)
            derive.recompute_premises_animal_count([previous,
                                                    movement["destination_premises_id"]])
    return success(public(movement))


@bp.post("/movement-events/<movement_id>/correct")
def correct_movement(movement_id):
    uid, role = require_roles(PRODUCER)
    body = shape.body()
    departed_at = shape.s_instant(body, "departed_at")
    icvi_number = shape.s_str(body, "icvi_number", required=False)
    movement = movement_or_404(movement_id)
    origin = store.premises.get(movement["origin_premises_id"])
    # Band 6 - the origin end belongs to the acting producer.
    require_owner(origin is not None and origin["producer_id"] == uid)
    # Band 10 - own-state gate.
    if movement["status"] != "DISPUTED":
        raise invalid_state("Only a DISPUTED movement may be corrected")
    # Band 11 - the origin must not be under quarantine.
    if origin["health_status"] == "QUARANTINED":
        raise conflict("ERR_PREMISES_UNDER_HOLD", "The origin premises is under quarantine")
    # Band 12 - regulatory interval safety.
    if movement["interstate"] and not icvi_number:
        raise conflict("ERR_ICVI_REQUIRED", "An interstate movement requires an icvi_number")
    # Band 13 - cross-field temporal checks.
    if departed_at > store.now():
        raise unprocessable("ERR_FUTURE_TIMESTAMP", "departed_at is later than the logical clock")
    animal = store.animals.get(movement["animal_id"])
    latest = derive.latest_observed_at(movement["animal_id"]) if animal else None
    if latest is not None and departed_at < latest:
        raise unprocessable("ERR_BACKDATED_EVENT",
                            "departed_at precedes the animal's latest observation")
    # Band 15 - bounded repetition, then residency coherence.
    if movement["correction_count"] >= 3:
        raise conflict("ERR_CORRECTION_LIMIT_EXCEEDED",
                       "The movement has already been corrected three times")
    if movement["arrived_at"] is not None and departed_at > movement["arrived_at"]:
        raise conflict("ERR_RESIDENCY_OVERLAP",
                       "A corrected departed_at may not be later than the recorded arrived_at")

    movement["status"] = "REPORTED"
    movement["correction_count"] += 1
    movement["departed_at"] = departed_at
    movement["icvi_number"] = icvi_number
    _recompute_timeliness(movement)
    touch(movement)
    departure = _movement_sighting(movement["id"], "DEPARTURE")
    if departure is not None:
        departure["observed_at"] = departed_at
    derive.mark_producer(origin["producer_id"], on_time=True)
    return success(public(movement))


@bp.post("/movement-events/<movement_id>/void")
def void_movement(movement_id):
    require_roles(PROGRAM_ADMIN)
    movement = movement_or_404(movement_id)
    if movement["status"] != "DISPUTED":
        raise invalid_state("Only a DISPUTED movement may be voided")
    movement["status"] = "VOIDED"
    touch(movement)
    animal = store.animals.get(movement["animal_id"])
    for sighting in list(store.sightings.values()):
        if sighting["source_movement_id"] == movement["id"]:
            sighting["reversed"] = True
    if animal is not None:
        previous = animal["current_premises_id"]
        derive.reproject_animal(animal)
        derive.recompute_premises_animal_count([previous,
                                                movement["origin_premises_id"],
                                                movement["destination_premises_id"]])
    origin = store.premises.get(movement["origin_premises_id"])
    if origin is not None:
        derive.mark_producer(origin["producer_id"], on_time=True)
    return success(public(movement))
