"""Statutory inspection-cycle endpoints (PRD section 3.2)."""
from flask import Blueprint

import clock
import services_cycles
import store
from constants import BUSINESS_READ_ROLES, ROLE_MSHA_ADMIN
from envelope import list_response, ok_object
from errors import ApiError, ERR_CYCLE_CLOSE_TOO_EARLY, ERR_CYCLE_OPEN_EXISTS, ERR_INVALID_STATE
from serialize import inspection_cycle as ser_cycle
from validate import ensure_empty_body, get_or_404, parse_body, require_roles

bp = Blueprint("cycles", __name__, url_prefix="/msha")


@bp.route("/mines/<mineId>/inspection-cycles", methods=["POST"])
def create_cycle(mineId):
    require_roles(ROLE_MSHA_ADMIN)
    body = parse_body({
        "period_start": ("date", True),
        "period_end": ("date", True),
    })
    mine = get_or_404(store.mines, mineId, "mine")
    # Tier 11 temporal rules: exclusivity check listed before geometry.
    if any(c["mine_id"] == mineId and c["status"] == "OPEN" for c in store.cycles.values()):
        raise ApiError(ERR_CYCLE_OPEN_EXISTS, "another cycle of this mine is still OPEN")
    services_cycles.validate_geometry(mine, body["period_start"], body["period_end"])
    cycle_index = 1 + sum(1 for c in store.cycles.values() if c["mine_id"] == mineId)
    required = 2 if mine["pov_status"] == "POV_FINAL" else 1
    entity = store.new_entity(store.cycles, {
        "mine_id": mineId,
        "cycle_index": cycle_index,
        "period_start": body["period_start"],
        "period_end": body["period_end"],
        "required_inspections": required,
        "completed_inspections": 0,
        "status": "OPEN",
    })
    return ok_object(ser_cycle(entity), 201)


@bp.route("/inspection-cycles/<cycleId>", methods=["GET"])
def get_cycle(cycleId):
    require_roles(*BUSINESS_READ_ROLES)
    return ok_object(ser_cycle(get_or_404(store.cycles, cycleId, "inspection cycle")))


@bp.route("/mines/<mineId>/inspection-cycles", methods=["GET"])
def list_cycles(mineId):
    require_roles(*BUSINESS_READ_ROLES)
    get_or_404(store.mines, mineId, "mine")
    items = [c for c in store.cycles.values() if c["mine_id"] == mineId]
    return list_response(items, ser_cycle)


@bp.route("/inspection-cycles/<cycleId>/close", methods=["POST"])
def close_cycle(cycleId):
    require_roles(ROLE_MSHA_ADMIN)
    ensure_empty_body()
    cycle = get_or_404(store.cycles, cycleId, "inspection cycle")
    if cycle["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE, "only an OPEN cycle can be closed")
    if cycle["completed_inspections"] >= cycle["required_inspections"]:
        # Requirement met: early close is permitted at any time.
        cycle["status"] = "COMPLIANT"
    elif clock.now().date() > cycle["period_end"]:
        # Unmet requirement closes as DELINQUENT only once the current logical
        # date is strictly later than period_end; never forgiven.
        cycle["status"] = "DELINQUENT"
    else:
        raise ApiError(
            ERR_CYCLE_CLOSE_TOO_EARLY,
            "an unmet cycle cannot be closed on or before its period_end",
        )
    store.touch(cycle)
    return ok_object(ser_cycle(cycle))
