"""Grower endpoints: onboard, suspend (cascade), exit (3-link cascade)."""
from flask import Blueprint

import store
from errors import (
    err,
    ERR_GROWER_HAS_LIVE_PLANTINGS,
    ERR_GROWER_HAS_UNSETTLED_STATEMENTS,
    ERR_GROWER_NOT_FOUND,
    ERR_INVALID_STATE,
)
from helpers import as_str, body, dump, opt_field, req_field, require_roles, success

bp = Blueprint("growers", __name__)


def get_grower_or_404(grower_id):
    g = store.db["growers"].get(grower_id)
    if g is None:
        raise err(ERR_GROWER_NOT_FOUND, "No grower with the given id")
    return g


def grower_agreements(grower_id):
    return [a for a in store.db["agreements"].values() if a["grower_id"] == grower_id]


@bp.route("/licensing/growers", methods=["POST"])
@require_roles("PlatformAdmin")
def create_grower():
    b = body()
    rec = store.init_record({
        "legal_name": as_str(req_field(b, "legal_name"), "legal_name"),
        "region_code": as_str(req_field(b, "region_code"), "region_code"),
        "status": "ACTIVE",
        "suspended_at": None,
        "exited_at": None,
    })
    store.db["growers"][rec["id"]] = rec
    return success(dump(rec), code=201)


@bp.route("/licensing/growers/<growerId>/suspend", methods=["POST"])
@require_roles("ComplianceOfficer")
def suspend_grower(growerId):
    g = get_grower_or_404(growerId)
    opt_field(body(), "reason", None)  # optional reason is accepted but not persisted
    if g["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Grower is not ACTIVE")
    # CASCADE link 1: ACTIVE agreements -> SUSPENDED (each bumps its own version)
    for a in grower_agreements(g["id"]):
        if a["status"] == "ACTIVE":
            a["status"] = "SUSPENDED"
            store.touch(a)
    g["status"] = "SUSPENDED"
    g["suspended_at"] = store.clock_now()
    store.touch(g)
    return success(dump(g))


@bp.route("/licensing/growers/<growerId>/exit", methods=["POST"])
@require_roles("ComplianceOfficer")
def exit_grower(growerId):
    g = get_grower_or_404(growerId)
    if g["status"] not in ("ACTIVE", "SUSPENDED"):
        raise err(ERR_INVALID_STATE, "Grower is not ACTIVE or SUSPENDED")
    agreements = grower_agreements(g["id"])
    agreement_ids = {a["id"] for a in agreements}
    # Blocker 1: no PLANTED or HARVESTING planting reachable via the grower's agreements
    for p in store.db["plantings"].values():
        if p["agreement_id"] in agreement_ids and p["status"] in ("PLANTED", "HARVESTING"):
            raise err(ERR_GROWER_HAS_LIVE_PLANTINGS, "Grower has live plantings")
    # Blocker 2: no statement with status != PAID
    for s in store.db["settlement_statements"].values():
        if s["grower_id"] == g["id"] and s["status"] != "PAID":
            raise err(ERR_GROWER_HAS_UNSETTLED_STATEMENTS, "Grower has unsettled statements")
    # CASCADE link 1: ACTIVE|SUSPENDED agreements -> TERMINATED
    terminated = [a for a in agreements if a["status"] in ("ACTIVE", "SUSPENDED")]
    for a in terminated:
        a["status"] = "TERMINATED"
        store.touch(a)
    # CASCADE link 2: PLANNED plantings of each terminated agreement -> CANCELLED
    terminated_ids = {a["id"] for a in terminated}
    for p in store.db["plantings"].values():
        if p["agreement_id"] in terminated_ids and p["status"] == "PLANNED":
            p["status"] = "CANCELLED"
            store.touch(p)
            # CASCADE link 3: release the reservation on the plant lot
            lot = store.db["plant_lots"].get(p["plant_lot_id"])
            if lot is not None:
                lot["plants_reserved"] -= p["planned_plants"]
                lot["plants_available"] = (
                    lot["quantity_plants"]
                    - lot["plants_reserved"]
                    - lot["plants_planted"]
                    - lot["plants_destroyed"]
                )
                store.touch(lot)
    g["status"] = "EXITED"
    g["exited_at"] = store.clock_now()
    store.touch(g)
    return success(dump(g))
