"""Blending trials: projection, revision rounds, execution and unwind."""

from decimal import Decimal

from flask import Blueprint

import calc
import domain
from auth import ALL_ROLES, CLIENT_REP, FACILITY_ADMIN, guard, scope
from envelope import respond
from errors import (
    ApiError,
    ERR_APPELLATION_INELIGIBLE,
    ERR_BLEND_ALREADY_CONSUMED,
    ERR_CONTRACT_NOT_ACTIVE,
    ERR_CROSS_CONTRACT_REFERENCE,
    ERR_INSUFFICIENT_LOT_VOLUME,
    ERR_INVALID_STATE,
    ERR_STALE_CONTRACT_VERSION,
)
from helpers import declared, run_list
from store import db, iso, new_entity, rhu, touch
from validation import v_components, v_enum, v_int, v_number, v_string

D = Decimal
bp = Blueprint("blends", __name__)

TRIAL_ACTIONS = {
    "SUBMIT": [CLIENT_REP],
    "REQUEST_REVISION": [FACILITY_ADMIN],
    "APPROVE": [FACILITY_ADMIN],
    "REJECT": [FACILITY_ADMIN],
    "UNWIND": [FACILITY_ADMIN],
}

COMPONENT_ELIGIBLE_STATUSES = ("PRESSED", "AGING")


def _apply_projection(trial, components, declared_loss_pct):
    lots_by_id = {c["source_lot_id"]: db.lots.get(c["source_lot_id"])
                  for c in components}
    lots_by_id = {k: v for k, v in lots_by_id.items() if v is not None}
    projection = calc.blend_projection(components, declared_loss_pct, lots_by_id)
    trial["total_component_gallons"] = projection["total_component_gallons"]
    trial["projected_loss_gallons"] = projection["projected_loss_gallons"]
    trial["projected_blend_gallons"] = projection["projected_blend_gallons"]
    trial["projected_alcohol_pct"] = projection["projected_alcohol_pct"]
    trial["projected_varietal_label"] = projection["projected_varietal_label"]
    trial["projected_appellation_label"] = projection["projected_appellation_label"]
    trial["_projected_varietal"] = projection["varietal"]
    trial["_projected_appellation"] = projection["appellation"]
    return trial


def _check_components(contract_id, components):
    """Rungs 60, the PRESSED/AGING gate, and rung 78 -- in that order."""
    lots = [domain.get_lot(c["source_lot_id"]) for c in components]
    for lot in lots:
        if lot["contract_id"] != contract_id:
            raise ApiError(ERR_CROSS_CONTRACT_REFERENCE,
                           "A source lot belongs to a different contract.")
    for lot in lots:
        if lot["production_status"] not in COMPONENT_ELIGIBLE_STATUSES:
            raise ApiError(ERR_INVALID_STATE,
                           "A source lot is not PRESSED or AGING.")
    for component, lot in zip(components, lots):
        if D(lot["volume_gallons"]) < D(component["volume_gallons"]):
            raise ApiError(ERR_INSUFFICIENT_LOT_VOLUME,
                           "A source lot no longer holds its component volume.")
    return lots


@bp.route("/blend-trials", methods=["POST"])
def create_trial():
    ctx = guard([CLIENT_REP])
    body = ctx.body
    contract_id = v_string(body, "contract_id")
    trial_name = v_string(body, "trial_name")
    target_lot_code = v_string(body, "target_lot_code")
    declared_loss_pct = v_number(body, "declared_loss_pct", ge=0, le=5, max_dp=2)
    components = v_components(body)

    contract = domain.get_contract(contract_id)
    for component in components:
        domain.get_lot(component["source_lot_id"])

    scope(ctx, contract["client_id"])
    _check_components(contract_id, components)

    trial = new_entity({
        "contract_id": contract_id,
        "result_lot_id": None,
        "trial_name": trial_name,
        "target_lot_code": target_lot_code,
        "declared_loss_pct": declared_loss_pct,
        "components": components,
        "round_number": 1,
        "status": "DRAFT",
        "submitted_by_user_id": None,
        "approved_by_user_id": None,
        "revision_note": None,
        "total_component_gallons": D(0),
        "projected_loss_gallons": D(0),
        "projected_blend_gallons": D(0),
        "projected_alcohol_pct": None,
        "projected_varietal_label": None,
        "projected_appellation_label": None,
        "_projected_varietal": None,
        "_projected_appellation": None,
        "_executed_dt": None,
    })
    _apply_projection(trial, components, declared_loss_pct)
    db.trials[trial["id"]] = trial
    return respond(domain.serialize(trial), 201)


@bp.route("/blend-trials/<trial_id>", methods=["GET"])
def read_trial(trial_id):
    ctx = guard(ALL_ROLES, read_body=False)
    trial = domain.get_trial(trial_id)
    scope(ctx, domain.trial_client_id(trial))
    return respond(domain.serialize(trial))


@bp.route("/blend-trials", methods=["GET"])
def list_trials():
    ctx = guard(ALL_ROLES, read_body=False)
    return run_list(db.trials.values(), ctx, domain.serialize,
                    owner_fn=domain.trial_client_id,
                    filters=(("contract_id", "contract_id"),
                             ("result_lot_id", "result_lot_id"),
                             ("status", "status")))


@bp.route("/blend-trials/<trial_id>/revise", methods=["POST"])
def revise_trial(trial_id):
    ctx = guard([CLIENT_REP])
    body = ctx.body
    components = v_components(body)
    declared_loss_pct = v_number(body, "declared_loss_pct", required=False,
                                 default=None, ge=0, le=5, max_dp=2)

    trial = domain.get_trial(trial_id)
    for component in components:
        domain.get_lot(component["source_lot_id"])

    scope(ctx, domain.trial_client_id(trial))
    declared(trial["status"] == "REVISION_REQUESTED")

    contract = db.contracts.get(trial["contract_id"])
    if contract is None or contract["status"] != "ACTIVE":
        raise ApiError(ERR_CONTRACT_NOT_ACTIVE, "The governing contract is not ACTIVE.")

    _check_components(trial["contract_id"], components)

    trial["components"] = components
    if declared_loss_pct is not None:
        trial["declared_loss_pct"] = declared_loss_pct
    trial["round_number"] = trial["round_number"] + 1
    trial["revision_note"] = None
    trial["submitted_by_user_id"] = ctx.user_id
    trial["status"] = "SUBMITTED"
    _apply_projection(trial, trial["components"], trial["declared_loss_pct"])
    touch(trial)
    return respond(domain.serialize(trial))


@bp.route("/blend-trials/<trial_id>/transitions", methods=["POST"])
def trial_transitions(trial_id):
    ctx = guard([CLIENT_REP, FACILITY_ADMIN], TRIAL_ACTIONS)
    body = ctx.body
    action = v_enum(body, "action", set(TRIAL_ACTIONS))
    revision_note = None
    if action == "REQUEST_REVISION":
        revision_note = v_string(body, "revision_note", required=False, nullable=True)

    trial = domain.get_trial(trial_id)
    scope(ctx, domain.trial_client_id(trial))

    if action == "SUBMIT":
        declared(trial["status"] == "DRAFT")
        contract = db.contracts.get(trial["contract_id"])
        if contract is None or contract["status"] != "ACTIVE":
            raise ApiError(ERR_CONTRACT_NOT_ACTIVE,
                           "The governing contract is not ACTIVE.")
        _check_components(trial["contract_id"], trial["components"])
        trial["status"] = "SUBMITTED"
        trial["submitted_by_user_id"] = ctx.user_id
        _apply_projection(trial, trial["components"], trial["declared_loss_pct"])
        touch(trial)
    elif action == "REQUEST_REVISION":
        declared(trial["status"] == "SUBMITTED")
        trial["status"] = "REVISION_REQUESTED"
        trial["revision_note"] = revision_note
        touch(trial)
    elif action == "APPROVE":
        declared(trial["status"] == "SUBMITTED")
        if not D(trial["projected_blend_gallons"]) > 0:
            raise ApiError(ERR_INVALID_STATE,
                           "The projected blend volume must be greater than zero.")
        # Rung 90 -- the facility only executes AVA-eligible blends.
        if trial["projected_appellation_label"] == calc.GENERIC_APPELLATION_LABEL:
            raise ApiError(ERR_APPELLATION_INELIGIBLE,
                           "No dominant AVA reaches the 85.00 percent share.")
        trial["status"] = "APPROVED"
        trial["approved_by_user_id"] = ctx.user_id
        touch(trial)
    elif action == "REJECT":
        declared(trial["status"] in ("SUBMITTED", "REVISION_REQUESTED"))
        trial["status"] = "REJECTED"
        touch(trial)
    else:  # UNWIND
        declared(trial["status"] == "EXECUTED")
        _unwind(trial)

    return respond(domain.serialize(trial))


def _unwind(trial):
    result_lot = db.lots.get(trial["result_lot_id"])
    # Rung 90 -- only while the result lot is untouched.
    if (result_lot is None
            or D(result_lot["volume_gallons"]) != D(trial["projected_blend_gallons"])
            or D(result_lot["loss_gallons"]) != D(trial["projected_loss_gallons"])):
        raise ApiError(ERR_BLEND_ALREADY_CONSUMED,
                       "The blend lot has already been drawn down.")

    for component in trial["components"]:
        source = db.lots.get(component["source_lot_id"])
        if source is None:
            continue
        source["volume_gallons"] = rhu(
            D(source["volume_gallons"]) + D(component["volume_gallons"]), 2)
        source["parent_lot_id"] = None
        if source["production_status"] == "CONSUMED":
            source["production_status"] = "AGING"
        touch(source)

    result_lot["volume_gallons"] = D(0)
    result_lot["loss_gallons"] = D(0)
    result_lot["production_status"] = "CONSUMED"
    result_lot["component_manifest"] = []
    touch(result_lot)

    client_id = domain.trial_client_id(trial)
    domain.book_loss(client_id, -D(trial["projected_loss_gallons"]))

    trial["status"] = "UNWOUND"
    trial["result_lot_id"] = None
    touch(trial)

    client = db.clients.get(client_id)
    if client is not None:
        touch(client)


@bp.route("/blend-trials/<trial_id>/execute", methods=["POST"])
def execute_trial(trial_id):
    ctx = guard([CLIENT_REP])
    expected = v_int(ctx.body, "expected_contract_version")

    trial = domain.get_trial(trial_id)
    scope(ctx, domain.trial_client_id(trial))

    # Rung 30 -- declared transition.
    declared(trial["status"] == "APPROVED")

    contract = db.contracts.get(trial["contract_id"])
    # Rung 35 -- stale-parent rejection.
    if contract is None or expected != contract["version"]:
        raise ApiError(ERR_STALE_CONTRACT_VERSION,
                       "The contract has moved since it was last read.")
    # Rung 40 -- cross-entity state gate.
    if contract["status"] != "ACTIVE":
        raise ApiError(ERR_CONTRACT_NOT_ACTIVE, "The governing contract is not ACTIVE.")

    components = trial["components"]
    # Rung 78 -- every source lot must STILL hold its component volume.
    for component in components:
        source = db.lots.get(component["source_lot_id"])
        if source is None or D(source["volume_gallons"]) < D(
                component["volume_gallons"]):
            raise ApiError(ERR_INSUFFICIENT_LOT_VOLUME,
                           "A source lot no longer holds its component volume.")

    now = db.now()
    total = D(trial["total_component_gallons"])
    manifest = []
    for component in components:
        pct = calc.share_pct(component["volume_gallons"], total)
        manifest.append({
            "source_lot_id": component["source_lot_id"],
            "volume_gallons": D(component["volume_gallons"]),
            "pct_of_blend": pct,
        })

    blend_lot = new_entity({
        "contract_id": trial["contract_id"],
        "current_vessel_id": None,
        "parent_lot_id": None,
        "lot_code": trial["target_lot_code"],
        "vintage_year": None,
        "varietal": trial.get("_projected_varietal"),
        "appellation": trial.get("_projected_appellation"),
        "varietal_label": trial["projected_varietal_label"],
        "appellation_label": trial["projected_appellation_label"],
        "volume_gallons": D(trial["projected_blend_gallons"]),
        "loss_gallons": D(trial["projected_loss_gallons"]),
        "brix_at_crush": None,
        "alcohol_pct": trial["projected_alcohol_pct"],
        "origin": "BLEND",
        "production_status": "AGING",
        "bond_status": "IN_BOND",
        "aging_start_at": iso(now),
        "aging_days": 0,
        "cases_bottled": 0,
        "source_intake_ids": [],
        "component_manifest": manifest,
        "_aging_dt": now,
        "_created_volume": D(trial["projected_blend_gallons"]),
    })
    db.lots[blend_lot["id"]] = blend_lot

    trial["status"] = "EXECUTED"
    trial["result_lot_id"] = blend_lot["id"]
    trial["_executed_dt"] = now
    touch(trial)

    # HOP 1 -- draw each source lot down.
    consumed = []
    for component in components:
        source = db.lots[component["source_lot_id"]]
        source["volume_gallons"] = rhu(
            D(source["volume_gallons"]) - D(component["volume_gallons"]), 2)
        if (D(source["volume_gallons"]) == 0
                and source["production_status"] == "AGING"):
            source["production_status"] = "CONSUMED"
            source["parent_lot_id"] = blend_lot["id"]
            # The lot leaves the vessel by itself; its housing is folded into
            # this same mutation so the lot advances its version exactly once.
            source["current_vessel_id"] = None
            consumed.append(source)
        touch(source)

    # HOPS 2 and 3 -- release the allocation, dirty the vessel.
    touched_contracts = []
    for source in consumed:
        allocation = domain.cascade_lot_left_vessel(source, recompute_contract=False)
        if allocation is not None and allocation["contract_id"] not in touched_contracts:
            touched_contracts.append(allocation["contract_id"])

    # HOP 4 -- each contract behind those vessels recomputes its counters.
    for contract_id in touched_contracts:
        owner = db.contracts.get(contract_id)
        if owner is not None:
            domain.recompute_contract_counters_and_touch(owner)

    client_id = domain.trial_client_id(trial)
    domain.book_loss(client_id, D(trial["projected_loss_gallons"]))
    client = db.clients.get(client_id)
    if client is not None:
        touch(client)

    return respond(domain.serialize(trial))
