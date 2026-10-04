"""Error coin quarantine and certified destruction (PRD §3.4)."""
from flask import Blueprint, request

import serialize
import store
from helpers import (auth, body, envelope, err, list_response, need_int,
                     need_str, no_undeclared, not_found, opt_str)

bp = Blueprint("errorcoins", __name__)


@bp.route("/mint/error-coin-cases", methods=["POST"])
def create_case():
    uid, _ = auth("QualityInspector")
    b = body()
    # Body FK: the production run must resolve.
    run = None
    if isinstance(b.get("production_run_id"), str):
        run = store.db["runs"].get(b["production_run_id"])
        if run is None:
            not_found("Production run not found")
    no_undeclared(b, {"production_run_id", "error_pieces", "description"})
    if run is None:
        need_str(b, "production_run_id")  # raises the missing/invalid-type 400
        not_found("Production run not found")
    pieces = need_int(b, "error_pieces")
    if pieces <= 0:
        err("ERR_QUANTITY_INVALID", 400, "error_pieces must be greater than zero")
    if pieces > run["scrapped_pieces"]:
        err("ERR_ERRORCOIN_QUANTITY_EXCEEDS", 422,
            "error_pieces exceeds the run's scrapped_pieces")
    description = opt_str(b, "description")
    case = store.mint_entity({
        "production_run_id": run["id"],
        "error_pieces": pieces,
        "description": description,
        "reported_by_user_id": uid,
        "status": "QUARANTINED",
        "destroyed_by_user_ids": None,
    })
    store.db["error_cases"][case["id"]] = case
    return envelope(serialize.error_case(case), status=201)


@bp.route("/mint/production-runs/<rid>/error-coin-cases", methods=["GET"])
def list_cases(rid):
    auth("QualityInspector", "DestructionCertifier", "ProductionPlanner",
         "MintDirector", "PlatformAdmin")
    if rid not in store.db["runs"]:
        not_found("Production run not found")
    items = [c for c in store.db["error_cases"].values()
             if c["production_run_id"] == rid]
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    return list_response(items, serialize.error_case)


@bp.route("/mint/error-coin-cases/<cid>/destroy", methods=["POST"])
def destroy_case(cid):
    auth("DestructionCertifier")
    case = store.db["error_cases"].get(cid)
    if case is None:
        not_found("Error coin case not found")
    if case["status"] == "DESTROYED":
        err("ERR_CASE_ALREADY_DESTROYED", 422, "Case has already been destroyed")
    b = body()
    primary = b.get("primary_certifier_user_id")
    secondary = b.get("secondary_certifier_user_id")
    # Segregation of duties (rung 7): two distinct certifiers, neither the
    # reporting inspector.
    if isinstance(primary, str) and isinstance(secondary, str):
        if primary == secondary:
            err("ERR_SEGREGATION_OF_DUTIES", 422,
                "Certifier ids must differ from each other")
        if primary == case["reported_by_user_id"] or \
                secondary == case["reported_by_user_id"]:
            err("ERR_SEGREGATION_OF_DUTIES", 422,
                "Certifiers must differ from the reporting inspector")
    no_undeclared(b, {"primary_certifier_user_id", "secondary_certifier_user_id"})
    primary = need_str(b, "primary_certifier_user_id")
    secondary = need_str(b, "secondary_certifier_user_id")
    case["destroyed_by_user_ids"] = [primary, secondary]
    case["status"] = "DESTROYED"
    store.bump(case)
    return envelope(serialize.error_case(case))
