"""Catalyst charges: installation, the poisoning write and regeneration (PRD 3.1, 3.2)."""
from flask import Blueprint, request

import calc
import cascade
import serialize
import validate as v
from auth import ALL_ROLES, PROCESS_ENGINEER, actor
from envelope import list_response, object_response, paging
from guards import duplicate, filtered, load, state
from mutate import touch
from store import db, stamp_new
from util import D

bp = Blueprint("charges", __name__)
PREFIX = "/nitrogen-ops/catalyst-charges"
CHARGE_STATUSES = ("ACTIVE", "SPENT", "RETIRED")


def _running_campaign(train_id):
    return any(r["train_id"] == train_id and r["status"] == "RUNNING"
               for r in db.runs.values())


@bp.post(PREFIX)
def create_charge():
    actor([PROCESS_ENGINEER])
    body = v.get_body()
    train_id = v.s_id(body, "train_id")
    charge_code = v.s_code(body, "charge_code", 2, 16)
    design_life = v.s_num(body, "design_life_hours", 1, gt=0)
    baseline = v.s_num(body, "baseline_operating_hours", 1, required=False,
                       default=D("0.0"), ge=0)
    poisoning = v.s_num(body, "poisoning_index", 2, required=False,
                        default=D("0.00"), ge=0, le=1)
    train = load("trains", train_id)
    duplicate("charges", "charge_code", charge_code, scope=("train_id", train_id))
    row = {
        "train_id": train_id,
        "charge_code": charge_code,
        "design_life_hours": design_life,
        "baseline_operating_hours": baseline,
        "poisoning_index": poisoning,
        "regeneration_count": 0,
        "installed_at": db.clock,
        "status": "ACTIVE",
    }
    incumbent = calc.active_charge(train_id)
    if incumbent is not None:
        incumbent["status"] = "RETIRED"
        touch(incumbent)
        touch(train)
    stamp_new(row)
    db.charges[row["id"]] = row
    return object_response(serialize.charge_json(row), 201)


@bp.get(PREFIX + "/<id>")
def get_charge(id):
    actor(ALL_ROLES)
    return object_response(serialize.charge_json(load("charges", id)))


@bp.get(PREFIX)
def list_charges():
    actor(ALL_ROLES)
    limit, offset = paging(request.args)
    rows = filtered("charges", [
        ("train_id", v.query_str("train_id")),
        ("status", v.query_enum("status", CHARGE_STATUSES)),
    ])
    return list_response(serialize.dump("charges", rows), limit, offset)


@bp.patch(PREFIX + "/<id>")
def revise_poisoning(id):
    """A laboratory figure that can drive the whole derate cascade."""
    actor([PROCESS_ENGINEER])
    body = v.get_body()
    poisoning = v.s_num(body, "poisoning_index", 2, ge=0, le=1)
    charge = load("charges", id)
    charge["poisoning_index"] = poisoning
    touch(charge)
    cascade.derate_if_spent(charge)
    return object_response(serialize.charge_json(charge))


@bp.post(PREFIX + "/<id>/regenerate")
def regenerate(id):
    actor([PROCESS_ENGINEER])
    v.get_body()
    charge = load("charges", id)
    state(charge["status"] in ("ACTIVE", "SPENT"))
    if charge["status"] == "ACTIVE":
        state(charge["regeneration_count"] < calc.MAX_REGENERATIONS)
        charge["regeneration_count"] += 1
        touch(charge)
        return object_response(serialize.charge_json(charge))
    # The recovery arm: the increment is only kept if it buys the charge back.
    charge["regeneration_count"] += 1
    if calc.charge_activity_pct(charge) < calc.CATALYST_MIN_ACTIVITY_PCT:
        charge["regeneration_count"] -= 1
        state(False)
    if calc.active_charge(charge["train_id"]) is not None:
        charge["regeneration_count"] -= 1
        state(False)
    charge["status"] = "ACTIVE"
    touch(charge)
    train = db.trains.get(charge["train_id"])
    if train is not None:
        if train["status"] == "DERATED":
            train["status"] = "RUNNING" if _running_campaign(train["id"]) else "IDLE"
        touch(train)
    return object_response(serialize.charge_json(charge))
