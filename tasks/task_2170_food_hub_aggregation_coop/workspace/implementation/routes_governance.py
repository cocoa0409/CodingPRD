"""Member equity governance: patronage proposal, ratification and distribution,
plus the logical-clock administration endpoint."""

from flask import Blueprint

import cascade
import fetch
import governance
import serializers
from constants import (CYCLE_DECISIONS, FISCAL_YEAR_MAX, FISCAL_YEAR_MIN,
                       ROLE_BOARD, ROLE_HUB_ADMIN, ROLE_PRODUCER)
from envelope import ok
from errors import ApiError
from store import base_record, db, touch
from validators import actor, body, endpoint, req_datetime, req_enum, req_int

bp = Blueprint("governance", __name__)


@bp.post("/patronage-cycles")
@endpoint([ROLE_HUB_ADMIN])
def propose_cycle():
    payload = body()
    fiscal_year = req_int(payload, "fiscal_year", minimum=FISCAL_YEAR_MIN,
                          maximum=FISCAL_YEAR_MAX)                       # rung 6
    pool = req_int(payload, "distributable_pool_cents", minimum=1)
    user_id, _role = actor()

    # rung 27 — fiscal-year uniqueness
    for cycle in db.cycles.values():
        if cycle["fiscal_year"] == fiscal_year:
            raise ApiError("ERR_DUPLICATE_FISCAL_YEAR")

    cycle = base_record({
        "fiscal_year": fiscal_year,
        "distributable_pool_cents": pool,
        "status": "PROPOSED",
        "proposed_by_user_id": user_id,
        "ratified_by_user_id": None,
        "basis_snapshot_total_cents": 0,
        "eligible_producer_count": 0,
        "distributed_total_cents": 0,
        "remainder_cents": 0,
        "_snapshot": [],
    })
    db.cycles[cycle["id"]] = cycle
    return ok(serializers.cycle_out(cycle), 201)


@bp.get("/patronage-cycles/<cycle_id>")
@endpoint([ROLE_HUB_ADMIN, ROLE_BOARD, ROLE_PRODUCER])
def read_cycle(cycle_id):
    cycle = fetch.get("cycle", cycle_id)
    return ok(serializers.cycle_out(cycle))


@bp.post("/patronage-cycles/<cycle_id>/ratification")
@endpoint([ROLE_BOARD])
def ratify_cycle(cycle_id):
    cycle = fetch.get("cycle", cycle_id)                                 # rung 4
    payload = body()
    decision = req_enum(payload, "decision", CYCLE_DECISIONS)            # rung 6
    user_id, _role = actor()

    # rung 10
    if cycle["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_CYCLE_STATE")

    # rung 12 — a director may not ratify a cycle they proposed
    if user_id == cycle["proposed_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    if decision == "REJECT":
        cycle["status"] = "CANCELLED"
        cycle["ratified_by_user_id"] = user_id
        touch(cycle)
        return ok(serializers.cycle_out(cycle))

    members, total = governance.build_snapshot()
    # rung 28 — patronage basis positivity
    if total <= 0:
        raise ApiError("ERR_NO_PATRONAGE_BASIS")

    cycle["status"] = "RATIFIED"
    cycle["ratified_by_user_id"] = user_id
    cycle["basis_snapshot_total_cents"] = total
    cycle["eligible_producer_count"] = len(members)
    cycle["_snapshot"] = members
    touch(cycle)
    return ok(serializers.cycle_out(cycle))


@bp.post("/patronage-cycles/<cycle_id>/distribution")
@endpoint([ROLE_HUB_ADMIN])
def distribute_cycle(cycle_id):
    cycle = fetch.get("cycle", cycle_id)                                 # rung 4
    # rung 10
    if cycle["status"] != "RATIFIED":
        raise ApiError("ERR_INVALID_CYCLE_STATE")

    governance.distribute(cycle)
    cycle["status"] = "DISTRIBUTED"
    touch(cycle)
    return ok(serializers.cycle_out(cycle))


@bp.post("/_clock/set_current_utc")
@endpoint([ROLE_HUB_ADMIN])
def set_clock():
    payload = body()
    instant = req_datetime(payload, "to_iso8601")                        # rung 6
    cascade.set_clock_and_sweep(instant)
    return ok({})
