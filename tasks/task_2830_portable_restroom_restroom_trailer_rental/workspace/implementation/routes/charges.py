"""ChargeEvent endpoints: assessment, dispute and officer resolution."""
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

bp = Blueprint("charges", __name__)


def _retire_unit(unit):
    """DAMAGE / TOTAL_LOSS: retire the iron and return every live deployment."""
    if unit["status"] == "DEPLOYED":
        unit["status"] = "RETIRED"
        touch(unit)
    affected_sites = []
    for deployment in services.deployments_of_unit(unit["id"]):
        if deployment["state"] not in ("RESERVED", "DEPLOYED"):
            continue
        deployment["state"] = "RETURNED"
        touch(deployment)
        if deployment["site_id"] not in affected_sites:
            affected_sites.append(deployment["site_id"])
    for site_id in affected_sites:
        services.recompute_deployed_unit_count(site_id)


def _send_to_repair(unit):
    if unit["status"] != "DEPLOYED":
        return
    unit["status"] = "IN_REPAIR"
    touch(unit)
    affected_sites = []
    for deployment in services.deployments_of_unit(unit["id"]):
        if deployment["state"] != "DEPLOYED":
            continue
        if deployment["site_id"] not in affected_sites:
            affected_sites.append(deployment["site_id"])
    for site_id in affected_sites:
        services.recompute_deployed_unit_count(site_id)


@bp.post("/charge-events")
@endpoint(["ComplianceOfficer"])
def create_charge():
    body = V.body()
    contract_id = V.str_field(body, "contract_id", 1)
    asset_unit_id = V.str_field(body, "asset_unit_id", 1)
    charge_kind = V.enum_field(body, "charge_kind", C.CLIENT_CHARGE_KINDS)
    severity = V.enum_field(body, "severity", C.SEVERITIES, required=False)
    if charge_kind == "DAMAGE" and severity is None:
        V.bad("Field 'severity' is required for a DAMAGE charge.")
    if charge_kind == "TIP_OVER" and severity is not None:
        V.bad("Field 'severity' must not be supplied for a TIP_OVER charge.")

    contract = resolve("rental_contracts", contract_id)
    unit = resolve("asset_units", asset_unit_id)

    prior_strikes = unit["damage_strikes"] + unit["tip_over_count"]
    amount_cents = calc.damage_tip_over_cents(
        unit["unit_class"], charge_kind, severity, prior_strikes)

    charge = insert("charge_events", {
        "contract_id": contract["id"],
        "asset_unit_id": unit["id"],
        "source_visit_id": None,
        "charge_kind": charge_kind,
        "severity": severity,
        "amount_cents": amount_cents,
        "state": "ASSESSED",
        "assessed_by_user_id": g.user_id,
        "resolved_by_user_id": None,
        "assessed_at": clock.now_iso(),
        "dispute_reason": None,
        "resolution_note": None,
    })

    services.recompute_asset_strikes(unit)
    if charge_kind == "DAMAGE" and severity == "TOTAL_LOSS":
        _retire_unit(unit)
    elif (unit["damage_strikes"] + unit["tip_over_count"]
            >= C.UNIT_REPAIR_STRIKE_THRESHOLD):
        _send_to_repair(unit)

    services.recompute_contract_ledger(contract)
    services.flag_rebill_required(contract)
    if charge_kind == "TIP_OVER":
        site = db.service_sites.get(contract["site_id"])
        if site is not None:
            services.recompute_site_posture(site)
    return created(serialize(charge))


@bp.get("/charge-events/<charge_id>")
@endpoint(ALL_ROLES)
def read_charge(charge_id):
    return ok(serialize(resolve("charge_events", charge_id)))


@bp.get("/charge-events")
@endpoint(ALL_ROLES)
def list_charges():
    limit, offset = V.pagination()
    contract_id = V.q_str("contract_id")
    asset_unit_id = V.q_str("asset_unit_id")
    source_visit_id = V.q_str("source_visit_id")
    charge_kind = V.q_enum("charge_kind", C.CHARGE_KINDS)
    state = V.q_enum("state", C.CHARGE_STATES)
    rows = ordered(db.charge_events.values())
    if contract_id is not None:
        rows = [r for r in rows if r["contract_id"] == contract_id]
    if asset_unit_id is not None:
        rows = [r for r in rows if r["asset_unit_id"] == asset_unit_id]
    if source_visit_id is not None:
        rows = [r for r in rows if r["source_visit_id"] == source_visit_id]
    if charge_kind is not None:
        rows = [r for r in rows if r["charge_kind"] == charge_kind]
    if state is not None:
        rows = [r for r in rows if r["state"] == state]
    return list_response(rows, limit, offset)


@bp.post("/charge-events/<charge_id>/dispute")
@endpoint(["CustomerContact"])
def dispute_charge(charge_id):
    body = V.body()
    dispute_reason = V.str_field(body, "dispute_reason", 1)
    charge = resolve("charge_events", charge_id)
    contract = db.rental_contracts.get(charge["contract_id"])

    if contract is None or contract["account_id"] != g.user_id:
        fail("ERR_ACCOUNT_SCOPE_VIOLATION")
    if charge["state"] != "ASSESSED":
        fail("ERR_INVALID_STATE_TRANSITION")
    assessed_at = clock.parse_instant(charge["assessed_at"])
    if assessed_at is not None:
        deadline = clock.plus_days(assessed_at, C.CHARGE_DISPUTE_WINDOW_DAYS)
        if clock.now() > deadline:
            fail("ERR_DISPUTE_WINDOW_CLOSED")

    charge["state"] = "DISPUTED"
    charge["dispute_reason"] = dispute_reason
    touch(charge)
    services.apply_charge_state_effects(charge)
    return ok(serialize(charge))


def _resolve_charge(charge_id, target, with_strikes):
    body = V.body()
    resolution_note = V.str_field(body, "resolution_note", 1, None, required=False)
    charge = resolve("charge_events", charge_id)

    if charge["assessed_by_user_id"] == g.user_id:
        fail("ERR_SEGREGATION_OF_DUTIES")
    if charge["state"] not in ("ASSESSED", "DISPUTED"):
        fail("ERR_INVALID_STATE_TRANSITION")

    charge["state"] = target
    charge["resolved_by_user_id"] = g.user_id
    if resolution_note is not None:
        charge["resolution_note"] = resolution_note
    touch(charge)
    services.apply_charge_state_effects(charge, with_strikes=with_strikes)
    return ok(serialize(charge))


@bp.post("/charge-events/<charge_id>/uphold")
@endpoint(["ComplianceOfficer"])
def uphold_charge(charge_id):
    return _resolve_charge(charge_id, "UPHELD", with_strikes=False)


@bp.post("/charge-events/<charge_id>/waive")
@endpoint(["ComplianceOfficer"])
def waive_charge(charge_id):
    return _resolve_charge(charge_id, "WAIVED", with_strikes=True)
