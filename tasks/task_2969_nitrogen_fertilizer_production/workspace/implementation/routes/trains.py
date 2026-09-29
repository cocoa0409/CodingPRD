"""Reformer trains (PRD 3.1). Status is never written directly by a client."""
from flask import Blueprint, request

import serialize
import validate as v
from auth import ALL_ROLES, PROCESS_ENGINEER, actor
from envelope import list_response, object_response, paging
from guards import duplicate, filtered, load
from store import db, stamp_new

bp = Blueprint("trains", __name__)
PREFIX = "/nitrogen-ops/reformer-trains"
TRAIN_STATUSES = ("IDLE", "RUNNING", "DERATED", "DOWN_FOR_TURNAROUND")


@bp.post(PREFIX)
def create_train():
    actor([PROCESS_ENGINEER])
    body = v.get_body()
    plant_id = v.s_id(body, "plant_id")
    train_code = v.s_code(body, "train_code", 2, 12)
    rated = v.s_num(body, "rated_ammonia_tpd", 2, gt=0)
    load("plants", plant_id)
    duplicate("trains", "train_code", train_code, scope=("plant_id", plant_id))
    row = {
        "plant_id": plant_id,
        "train_code": train_code,
        "rated_ammonia_tpd": rated,
        "status": "IDLE",
    }
    stamp_new(row)
    db.trains[row["id"]] = row
    return object_response(serialize.train_json(row), 201)


@bp.get(PREFIX + "/<id>")
def get_train(id):
    actor(ALL_ROLES)
    return object_response(serialize.train_json(load("trains", id)))


@bp.get(PREFIX)
def list_trains():
    actor(ALL_ROLES)
    limit, offset = paging(request.args)
    rows = filtered("trains", [
        ("plant_id", v.query_str("plant_id")),
        ("status", v.query_enum("status", TRAIN_STATUSES)),
    ])
    return list_response(serialize.dump("trains", rows), limit, offset)
