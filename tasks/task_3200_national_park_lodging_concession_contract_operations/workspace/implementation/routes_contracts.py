"""Contract routes + transition lifecycle."""
from flask import Blueprint, request

from db import store
from errors import err, not_found
from helpers import (new_entity, serialize, paginate, require_fields, req_int,
                     req_enum, parse_dt, add_months, touch, new_id, ts_now)
from middleware import require_role, require_read_role
from response import ok
import engine

bp = Blueprint("contracts", __name__)

FOUR_LINES = {"LODGING", "FOOD", "RETAIL", "TOURS"}


def get_contract(cid):
    c = store.contracts.get(cid)
    if not c:
        raise not_found("contract")
    return c


def require_operational(c, allow_transition_pending=False):
    if c["status"] == "ACTIVE":
        return
    if allow_transition_pending and c["status"] == "TRANSITION_PENDING":
        return
    raise err("ERR_CONTRACT_NOT_OPERATIONAL", 409, "Contract not in a state permitting the operation")


@bp.post("/contracts")
def create_contract():
    require_role("AgencyContractingOfficer")
    body = request.get_json(silent=True)
    require_fields(body, ["park_code", "contract_number", "term_months", "start_date",
                          "franchise_fee_rate", "employee_housing_capacity",
                          "lsi_annual_schedule_type", "environmental_plan_due_day_of_year"])
    if not isinstance(body["park_code"], str) or not body["park_code"]:
        raise err("ERR_INVALID_REQUEST", 400, "park_code required")
    if not isinstance(body["contract_number"], str) or not body["contract_number"]:
        raise err("ERR_INVALID_REQUEST", 400, "contract_number required")
    for c in store.contracts.values():
        if c["contract_number"] == body["contract_number"]:
            raise err("ERR_INVALID_REQUEST", 400, "contract_number must be unique")
    term = req_int(body, "term_months", minimum=1)
    if term % 12 != 0:
        raise err("ERR_INVALID_REQUEST", 400, "term_months must be a positive multiple of 12")
    rate = body["franchise_fee_rate"]
    if isinstance(rate, bool) or not isinstance(rate, (int, float)) or rate <= 0 or rate > 0.20:
        raise err("ERR_INVALID_REQUEST", 400, "franchise_fee_rate must be > 0 and <= 0.20")
    req_int(body, "employee_housing_capacity", minimum=1)
    lsi = req_enum(body, "lsi_annual_schedule_type", {"LINEAR", "DECLINING_BALANCE"})
    req_int(body, "environmental_plan_due_day_of_year", minimum=1, maximum=365)
    start = parse_dt(body["start_date"], "start_date")
    end = add_months(start, term)
    c = new_entity({
        "park_code": body["park_code"],
        "contract_number": body["contract_number"],
        "term_months": term,
        "start_date": body["start_date"],
        "end_date": end.strftime("%Y-%m-%dT%H:%M:%S.") + f"{end.microsecond // 1000:03d}Z",
        "franchise_fee_rate": rate,
        "employee_housing_capacity": body["employee_housing_capacity"],
        "lsi_annual_schedule_type": lsi,
        "environmental_plan_due_day_of_year": body["environmental_plan_due_day_of_year"],
        "status": "DRAFT",
        "successor_contract_id": None,
    })
    store.contracts[c["id"]] = c
    return ok(serialize(c), 201)


@bp.get("/contracts")
def list_contracts():
    require_read_role()
    items = list(store.contracts.values())
    st = request.args.get("status")
    if st:
        items = [c for c in items if c["status"] == st]
    succ = request.args.get("successor_contract_id")
    if succ:
        items = [c for c in items if c.get("successor_contract_id") == succ]
    page, limit, offset, total = paginate(items)
    return ok(page, 200, True, limit, offset, total)


@bp.get("/contracts/<cid>")
def get_contract_route(cid):
    require_read_role()
    return ok(serialize(get_contract(cid)))


@bp.post("/contracts/<cid>/activate")
def activate(cid):
    require_role("ConcessionerOpsManager")
    c = get_contract(cid)
    if c["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", 409, "Contract must be DRAFT to activate")
    seasons = [s for s in store.seasons.values() if s["contract_id"] == cid]
    lines = {sl["line_type"] for sl in store.service_lines.values() if sl["contract_id"] == cid}
    if len(seasons) < 1 or lines != FOUR_LINES:
        raise err("ERR_CONTRACT_NOT_ACTIVATABLE", 409, "Activation requires >= 1 season and all four service lines")
    c["status"] = "ACTIVE"
    touch(c)
    return ok(serialize(c))


@bp.post("/contracts/<cid>/initiate-transition")
def initiate_transition(cid):
    require_role("AgencyContractingOfficer")
    c = get_contract(cid)
    if c["status"] not in ("ACTIVE", "EXPIRED"):
        raise err("ERR_INVALID_STATE", 409, "Transition can only start from ACTIVE or EXPIRED")
    for i in store.incidents.values():
        if i["contract_id"] == cid and i["status"] in ("REPORTED", "UNDER_REVIEW", "CORRECTIVE_PLAN_REQUIRED"):
            raise err("ERR_OPEN_ENVIRONMENTAL_INCIDENT", 409, "Open environmental incidents block transition")
    for p in store.capital_projects.values():
        if p["contract_id"] == cid and p["status"] in ("PROPOSED", "AUTHORIZED", "COMPLETED"):
            raise err("ERR_OPEN_CAPITAL_PROJECT", 409, "Live capital projects block transition initiation")
    c["status"] = "TRANSITION_PENDING"
    touch(c)
    return ok(serialize(c))


@bp.post("/contracts/<cid>/designate-successor")
def designate_successor(cid):
    require_role("AgencyContractingOfficer")
    c = get_contract(cid)
    if c["status"] != "TRANSITION_PENDING":
        raise err("ERR_CONTRACT_NOT_OPERATIONAL", 409, "Successor designation requires TRANSITION_PENDING")
    body = request.get_json(silent=True)
    require_fields(body, ["successor_contract_id"])
    succ = store.contracts.get(body["successor_contract_id"])
    if not succ:
        raise not_found("contract")
    if succ["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", 409, "Successor contract must be DRAFT")
    c["successor_contract_id"] = succ["id"]
    touch(c)
    return ok(serialize(c))


@bp.post("/contracts/<cid>/finalize-transition")
def finalize_transition(cid):
    require_role("AgencyContractingOfficer")
    c = get_contract(cid)
    if c["status"] != "TRANSITION_PENDING":
        raise err("ERR_INVALID_STATE", 409, "Finalization requires TRANSITION_PENDING")
    if not c.get("successor_contract_id"):
        raise err("ERR_NO_SUCCESSOR_DESIGNATED", 409, "A DRAFT successor must be designated")
    succ = store.contracts.get(c["successor_contract_id"])
    if not succ:
        raise err("ERR_NO_SUCCESSOR_DESIGNATED", 409, "A DRAFT successor must be designated")
    for st in store.fee_statements.values():
        if st["contract_id"] == cid and st["status"] != "PAID":
            raise err("ERR_STATEMENT_NOT_PAID", 409, "Every statement must be PAID")
    for r in store.receipts_reports.values():
        if r["contract_id"] == cid and r["status"] != "ACCEPTED":
            raise err("ERR_INVALID_STATE", 409, "Every receipts report must be ACCEPTED")
    # Cascade: capital projects APPROVED -> EXPENDED, recreated on successor
    n = engine.current_offset(c)
    lsi_total = 0
    for p in list(store.capital_projects.values()):
        if p["contract_id"] == cid and p["status"] == "APPROVED":
            p["accrued_lsi_cents"] = engine.lsi_accrual(c, p, n)
            p["status"] = "EXPENDED"
            touch(p)
            lsi_total += p["accrued_lsi_cents"]
            np = new_entity({
                "contract_id": succ["id"],
                "title": p["title"],
                "asset_ref": p["asset_ref"],
                "authorized_cost_cents": p["authorized_cost_cents"],
                "actual_cost_cents": 0,
                "in_service_month_offset": None,
                "accrued_lsi_cents": 0,
                "status": "PROPOSED",
            })
            store.capital_projects[np["id"]] = np
    for sl in list(store.service_lines.values()):
        if sl["contract_id"] == cid:
            sl["status"] = "TERMINATED"
            touch(sl)
            nl = new_entity({
                "contract_id": succ["id"],
                "line_type": sl["line_type"],
                "authorized": sl.get("authorized", True),
                "separate_reporting_required": sl.get("separate_reporting_required", True),
                "status": "AUTHORIZED",
            })
            store.service_lines[nl["id"]] = nl
    for rc in list(store.room_classes.values()):
        if rc["contract_id"] == cid and rc["status"] == "ACTIVE":
            rc["status"] = "DECOMMISSIONED"
            touch(rc)
            nr = new_entity({
                "contract_id": succ["id"],
                "code": rc["code"],
                "total_rooms": rc["total_rooms"],
                "peak_season_months": list(rc["peak_season_months"]),
                "status": "ACTIVE",
            })
            store.room_classes[nr["id"]] = nr
    c["_lsi_payout_cents"] = lsi_total
    c["status"] = "CLOSED"
    touch(c)
    return ok(serialize(c))
