"""Incentive programs and accruals (PRD §3.12)."""
from flask import Blueprint, request

import errors as err
from db import get_store
from middleware import auth_context
from response import success_list, success_object
from services.core import compute_accrual
from util import (bump, new_entity, now_dt, parse_dt, req_enum, req_field,
                  req_str, req_ts)

bp = Blueprint("incentives", __name__)

ALLOC_ONLY = ["RegionalAllocator"]
READ = ["RegionalAllocator", "Dealer", "ProductionScheduler"]


def _body() -> dict:
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else {}


@bp.post("/wholesale/incentive-programs")
def create_program():
    auth_context(ALLOC_ONLY)
    body = _body()
    code = req_str(body, "code")
    model_line_id = req_str(body, "model_line_id")
    kind = req_enum(body, "kind", ("AGED_INVENTORY_CREDIT", "VOLUME_BONUS"))
    params = req_field(body, "params")
    if not isinstance(params, dict):
        raise err.validation("params must be an object")
    window_start = req_ts(body, "window_start")
    window_end = req_ts(body, "window_end")
    if model_line_id not in get_store("model_lines"):
        raise err.not_found("model line not found")
    if parse_dt(window_end) <= parse_dt(window_start):
        raise err.validation("window_end must be strictly after window_start")
    for p in get_store("incentive_programs").values():
        if p["code"] == code:
            raise err.duplicate("program code already exists")
    program = new_entity({
        "code": code,
        "model_line_id": model_line_id,
        "kind": kind,
        "params": params,
        "window_start": window_start,
        "window_end": window_end,
        "status": "ACTIVE",
        "_final_accruals": None,
    })
    get_store("incentive_programs")[program["id"]] = program
    return success_object(_program_view(program), 201)


def _program_view(program: dict) -> dict:
    view = dict(program)
    if program["status"] == "CLOSED":
        view["status"] = "CLOSED"
    else:
        start = parse_dt(program["window_start"])
        end = parse_dt(program["window_end"])
        now = now_dt()
        view["status"] = "ACTIVE" if start <= now < end else "CLOSED"
    view.pop("_final_accruals", None)
    return view


@bp.get("/wholesale/incentive-programs")
def list_programs():
    auth_context(READ)
    rows = [_program_view(p) for p in get_store("incentive_programs").values()]
    if request.args.get("model_line_id"):
        rows = [r for r in rows if r["model_line_id"] == request.args["model_line_id"]]
    if request.args.get("status"):
        rows = [r for r in rows if r["status"] == request.args["status"]]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    return success_list(rows)


@bp.get("/wholesale/incentive-programs/<pid>")
def get_program(pid):
    auth_context(READ)
    program = get_store("incentive_programs").get(pid)
    if program is None:
        raise err.not_found("program not found")
    return success_object(_program_view(program))


@bp.post("/wholesale/incentive-programs/<pid>/close")
def close_program(pid):
    auth_context(ALLOC_ONLY)
    program = get_store("incentive_programs").get(pid)
    if program is None:
        raise err.not_found("program not found")
    if program.get("_final_accruals") is not None or program["status"] == "CLOSED":
        raise err.program_closed()
    if _program_view(program)["status"] == "CLOSED":
        raise err.program_closed()
    # Final accrual per dealer, frozen as amount_cents (§3.12). One row per
    # dealer with any delivered history on the program's line.
    accruals = {}
    for dealer_id in _program_dealers(program):
        accruals[dealer_id] = compute_accrual(program, dealer_id)
    program["_final_accruals"] = accruals
    program["status"] = "CLOSED"
    bump(program)
    return success_object(_program_view(program))


def _program_dealers(program: dict):
    """Dealers tracked for this program: those with a DealerModelLine row on
    the program's line (materialized at run publish / first order)."""
    ids = [dml["dealer_id"] for dml in get_store("dealer_model_lines").values()
           if dml["model_line_id"] == program["model_line_id"]]
    return sorted(set(ids))


@bp.get("/wholesale/incentive-programs/<pid>/accruals")
def list_accruals(pid):
    auth_context(["RegionalAllocator", "Dealer"])
    program = get_store("incentive_programs").get(pid)
    if program is None:
        raise err.not_found("program not found")
    rows = []
    if program.get("_final_accruals") is not None:
        # Final variant: frozen ledger figures (§3.12).
        for dealer_id in _program_dealers(program):
            rows.append({
                "dealer_id": dealer_id,
                "amount_cents": program["_final_accruals"].get(dealer_id, 0),
                "variant": "final",
            })
    else:
        # Provisional variant: recomputed per delivery (§3.12).
        for dealer_id in _program_dealers(program):
            rows.append({
                "dealer_id": dealer_id,
                "amount_cents": compute_accrual(program, dealer_id),
                "variant": "provisional",
            })
    if request.args.get("dealer_id"):
        rows = [r for r in rows if r["dealer_id"] == request.args["dealer_id"]]
    return success_list(rows)
