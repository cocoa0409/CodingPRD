from decimal import Decimal

from flask import Blueprint

import calc
import db
import services
from core import (actor, auth, body, fail, fmt_date, get_date, get_enum, get_str, now_date, ok,
                  pagination, paginate, q_enum, q_str, sorted_rows)

bp = Blueprint("introductions", __name__)

LEVELS = ("CALM", "MINOR_AGGRESSION", "SEVERE_AGGRESSION")
STAGES = ("HOWDY", "PARTIAL_CONTACT", "FULL_CONTACT", "INTEGRATED", "ABORTED")
LADDER = ["HOWDY", "PARTIAL_CONTACT", "FULL_CONTACT", "INTEGRATED"]


def _reset_stage(protocol):
    protocol["sessions_at_stage"] = 0
    protocol["_stage_points"] = 0
    protocol["_stage_levels"] = []


@bp.post("/introduction-protocols")
@auth("Registrar")
def create_protocol():
    b = body()
    agreement_id = get_str(b, "transfer_agreement_id", required=True)
    animal_id = get_str(b, "animal_id", required=True)
    institution_id = get_str(b, "institution_id", required=True)
    group_code = get_str(b, "resident_group_code", required=True)

    agreement = db.get_agreement(agreement_id)
    animal = db.get_animal(animal_id)
    db.get_institution(institution_id)

    if actor() != institution_id:
        fail("ERR_ACTOR_SCOPE_VIOLATION")

    if not any(o for o in services.occupancies_of(agreement_id) if o["phase"] == "CLEARED"):
        fail("ERR_QUARANTINE_NOT_CLEARED")
    if animal["location_status"] != "AWAITING_INTRODUCTION":
        fail("ERR_ANIMAL_LOCATION_CONFLICT")

    protocol = db.insert(db.protocols, {
        "transfer_agreement_id": agreement_id,
        "animal_id": animal_id,
        "institution_id": institution_id,
        "resident_group_code": group_code,
        "stage": "HOWDY",
        "sessions_at_stage": 0,
        "aggression_score_total": Decimal("0.00"),
        "regression_count": 0,
        "observation_count": 0,
        "started_on": fmt_date(now_date()),
        "_stage_points": 0,
        "_stage_levels": [],
    })
    animal["location_status"] = "INTRODUCING"
    db.touch(animal)
    return ok(services.protocol_out(protocol), 201)


def _abort(protocol):
    protocol["stage"] = "ABORTED"
    _reset_stage(protocol)
    animal = db.animals.get(protocol["animal_id"])
    if animal is not None:
        if animal["location_status"] == "INTRODUCING":
            animal["location_status"] = "HELD"
        animal["genetic_designation"] = "HOLD_NO_BREED"
        db.touch(animal)
        services.decline_breed_recommendations(animal)


def _integrate(protocol):
    animal = db.animals.get(protocol["animal_id"])
    if animal is not None and animal["location_status"] == "INTRODUCING":
        animal["location_status"] = "HELD"
        db.touch(animal)
    agreement = db.agreements.get(protocol["transfer_agreement_id"])
    if agreement is not None and agreement["status"] == "EXECUTED":
        agreement["status"] = "COMPLETED"
        db.touch(agreement)


@bp.post("/introduction-protocols/<protocol_id>/observations")
@auth("Registrar")
def record_observation(protocol_id):
    b = body()
    level = get_enum(b, "aggression_level", LEVELS, required=True)
    observer_name = get_str(b, "observer_name", required=True)
    observed_on, observed_raw = get_date(b, "observed_on", required=True)

    protocol = db.get_protocol(protocol_id)
    if protocol["stage"] in ("INTEGRATED", "ABORTED"):
        fail("ERR_PROTOCOL_STAGE_INVALID")

    points = calc.AGGRESSION_POINTS[level]
    db.observations.append({
        "protocol_id": protocol["id"],
        "aggression_level": level,
        "observer_name": observer_name,
        "observed_on": observed_raw,
    })

    protocol["observation_count"] += 1
    protocol["aggression_score_total"] = protocol["aggression_score_total"] + Decimal(points)
    protocol["sessions_at_stage"] += 1
    protocol["_stage_points"] += points
    protocol["_stage_levels"].append(level)

    stage = protocol["stage"]
    if protocol["_stage_points"] >= calc.AGGRESSION_REGRESSION_THRESHOLD:
        # regression is evaluated before advancement
        if stage == "HOWDY":
            _abort(protocol)
        elif protocol["regression_count"] + 1 > calc.MAX_REGRESSIONS:
            _abort(protocol)
        else:
            protocol["regression_count"] += 1
            protocol["stage"] = LADDER[LADDER.index(stage) - 1]
            _reset_stage(protocol)
    else:
        levels = protocol["_stage_levels"]
        recent_calm = len(levels) >= 2 and levels[-1] == "CALM" and levels[-2] == "CALM"
        if protocol["sessions_at_stage"] >= calc.MIN_SESSIONS_PER_STAGE and recent_calm:
            protocol["stage"] = LADDER[LADDER.index(stage) + 1]
            _reset_stage(protocol)
            if protocol["stage"] == "INTEGRATED":
                _integrate(protocol)

    db.touch(protocol)
    return ok(services.protocol_out(protocol), 201)


@bp.get("/introduction-protocols/<protocol_id>")
@auth()
def read_protocol(protocol_id):
    return ok(services.protocol_out(db.get_protocol(protocol_id)))


@bp.get("/introduction-protocols")
@auth()
def list_protocols():
    limit, offset = pagination()
    filters = {
        "transfer_agreement_id": q_str("transfer_agreement_id"),
        "animal_id": q_str("animal_id"),
        "institution_id": q_str("institution_id"),
        "resident_group_code": q_str("resident_group_code"),
        "stage": q_enum("stage", STAGES),
    }
    rows = list(db.protocols.values())
    for field, value in filters.items():
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    return paginate(sorted_rows(rows), limit, offset, services.protocol_out)
