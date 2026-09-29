"""UnitDeployment endpoints: reservation, listing and relocation."""
from flask import Blueprint, g

from auth import ALL_ROLES, endpoint
import calculations as calc
import clock
import constants as C
from db import db, insert, ordered, serialize, touch
from errors import fail
from responses import created, ok
from routes.common import list_response, resolve
import services
import validation as V

bp = Blueprint("deployments", __name__)


@bp.post("/unit-deployments")
@endpoint(["DispatchPlanner"])
def create_deployment():
    body = V.body()
    contract_id = V.str_field(body, "contract_id", 1)
    asset_unit_id = V.str_field(body, "asset_unit_id", 1)
    deploy_from = V.date_field(body, "deploy_from")
    deploy_to = V.date_field(body, "deploy_to")
    V.ordering(deploy_from, deploy_to, "deploy_from", "deploy_to")

    contract = resolve("rental_contracts", contract_id)
    unit = resolve("asset_units", asset_unit_id)
    site = db.service_sites.get(contract["site_id"])

    if site is not None and site["site_posture"] == "BLOCKED":
        fail("ERR_SITE_POSTURE_BLOCKED")
    if site is not None and site["site_posture"] == "RESTRICTED":
        fail("ERR_SITE_POSTURE_RESTRICTED")
    if site is not None and unit["tare_length_ft"] > site["max_truck_length_ft"]:
        fail("ERR_SITE_ACCESS_INFEASIBLE")
    for candidate in services.deployments_of_unit(unit["id"]):
        if candidate["state"] not in ("RESERVED", "DEPLOYED"):
            continue
        if (deploy_from <= candidate["deploy_to"]
                and candidate["deploy_from"] <= deploy_to):
            fail("ERR_UNIT_DOUBLE_BOOKED")

    row = insert("unit_deployments", {
        "contract_id": contract["id"],
        "asset_unit_id": unit["id"],
        "site_id": contract["site_id"],
        "deploy_from": deploy_from,
        "deploy_to": deploy_to,
        "state": "RESERVED",
        "relocation_count": 0,
    })
    return created(serialize(row))


@bp.get("/unit-deployments/<deployment_id>")
@endpoint(ALL_ROLES)
def read_deployment(deployment_id):
    return ok(serialize(resolve("unit_deployments", deployment_id)))


@bp.get("/unit-deployments")
@endpoint(ALL_ROLES)
def list_deployments():
    limit, offset = V.pagination()
    contract_id = V.q_str("contract_id")
    asset_unit_id = V.q_str("asset_unit_id")
    site_id = V.q_str("site_id")
    state = V.q_enum("state", C.DEPLOYMENT_STATES)
    rows = ordered(db.unit_deployments.values())
    if contract_id is not None:
        rows = [r for r in rows if r["contract_id"] == contract_id]
    if asset_unit_id is not None:
        rows = [r for r in rows if r["asset_unit_id"] == asset_unit_id]
    if site_id is not None:
        rows = [r for r in rows if r["site_id"] == site_id]
    if state is not None:
        rows = [r for r in rows if r["state"] == state]
    return list_response(rows, limit, offset)


@bp.post("/unit-deployments/<deployment_id>/relocate")
@endpoint(["DispatchPlanner"])
def relocate_deployment(deployment_id):
    body = V.body()
    destination_site_id = V.str_field(body, "destination_site_id", 1)
    effective_date = V.date_field(body, "effective_date")
    V.str_field(body, "relocation_reason", 1, None, required=False)

    deployment = resolve("unit_deployments", deployment_id)
    destination = resolve("service_sites", destination_site_id)
    contract = db.rental_contracts.get(deployment["contract_id"])
    unit = db.asset_units.get(deployment["asset_unit_id"])

    if deployment["state"] != "DEPLOYED":
        fail("ERR_INVALID_STATE_TRANSITION")
    if contract is None or destination["account_id"] != contract["account_id"]:
        fail("ERR_INVALID_STATE_TRANSITION",
             "The destination site belongs to a different account.")
    if destination["site_posture"] == "BLOCKED":
        fail("ERR_SITE_POSTURE_BLOCKED")
    if unit is not None and unit["tare_length_ft"] > destination["max_truck_length_ft"]:
        fail("ERR_SITE_ACCESS_INFEASIBLE")

    origin_site_id = deployment["site_id"]
    deployment["site_id"] = destination["id"]
    deployment["relocation_count"] += 1
    touch(deployment)

    same_day = effective_date == clock.today()
    amount_cents = calc.relocation_cents(destination["access_class"], same_day)
    insert("charge_events", {
        "contract_id": contract["id"],
        "asset_unit_id": deployment["asset_unit_id"],
        "source_visit_id": None,
        "charge_kind": "RELOCATION",
        "severity": None,
        "amount_cents": amount_cents,
        "state": "ASSESSED",
        "assessed_by_user_id": g.user_id,
        "resolved_by_user_id": None,
        "assessed_at": clock.now_iso(),
        "dispute_reason": None,
        "resolution_note": None,
    })
    services.recompute_contract_ledger(contract)
    services.flag_rebill_required(contract)
    services.recompute_deployed_unit_count(origin_site_id)
    if destination["id"] != origin_site_id:
        services.recompute_deployed_unit_count(destination["id"])
    return ok(serialize(deployment))
