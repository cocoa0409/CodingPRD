"""Program, ProgramLine and disposition-action endpoints (PRD 3.1, 3.7)."""
from decimal import Decimal

from flask import Blueprint, request

from auth import get_body, require_roles
from db import bump, new_entity, store
from envelope import ok, paginate
from errors import api_error
from services import (OPEN_ORDER_STATUSES, PROGRAM_DISCOUNT_CAP, get_active_line,
                      maybe_retire_line, supersede_cascade)
from util import iso3, parse_dt, parse_week

bp = Blueprint("programs", __name__)

ALL_ROLES = ("PlatformAdmin", "ProgramManager", "RetailDesigner", "DealerRep",
             "PlantScheduler", "LogisticsCoordinator", "ClaimsAdjuster", "FieldServiceRep")
DISPOSITION_TYPES = ("RTV", "LIQUIDATE", "TRANSFER", "DESTROY")


def serialize_program(program):
    data = dict(program)
    count = 0
    for order in store.orders.values():
        if order["program_id"] == program["id"] and order["status"] in OPEN_ORDER_STATUSES:
            count += 1
    data["open_order_count"] = count
    return data


def serialize_line(line):
    return dict(line)


@bp.route("/cabinet/programs", methods=["POST"])
def create_program():
    require_roles("ProgramManager")
    body = get_body()
    account_id = body.get("account_id")
    if account_id is None:
        raise api_error("ERR_INVALID_REQUEST", "account_id is required")
    account = store.accounts.get(account_id)
    if account is None:
        raise api_error("ERR_NOT_FOUND", "account not found")
    name = body.get("name")
    if not isinstance(name, str) or not name:
        raise api_error("ERR_INVALID_REQUEST", "name is required")
    discount = body.get("program_discount_pct")
    if isinstance(discount, bool) or not isinstance(discount, (int, float)):
        raise api_error("ERR_INVALID_REQUEST", "program_discount_pct is required")
    if Decimal(str(discount)) < 0 or Decimal(str(discount)) > PROGRAM_DISCOUNT_CAP:
        raise api_error("ERR_INVALID_REQUEST",
                        "program_discount_pct must be between 0 and 0.5 inclusive")
    program = new_entity()
    program.update({
        "account_id": account_id,
        "name": name,
        "program_discount_pct": discount,
        "status": "DRAFT",
        "transition_started_at": None,
        "display_reset_deadline": None,
        "disposition_deadline": None,
    })
    store.programs[program["id"]] = program
    return ok(serialize_program(program), 201)


@bp.route("/cabinet/programs/<program_id>", methods=["GET"])
def get_program(program_id):
    require_roles(*ALL_ROLES)
    program = store.programs.get(program_id)
    if program is None:
        raise api_error("ERR_NOT_FOUND", "program not found")
    return ok(serialize_program(program))


@bp.route("/cabinet/programs", methods=["GET"])
def list_programs():
    require_roles(*ALL_ROLES)
    account_id = request.args.get("account_id")
    status = request.args.get("status")
    items = [p for p in store.programs.values()
             if (account_id is None or p["account_id"] == account_id)
             and (status is None or p["status"] == status)]
    items = sorted(items, key=lambda p: p["created_at"])
    page, meta = paginate([serialize_program(p) for p in items])
    return ok(page, 200, meta)


@bp.route("/cabinet/programs/<program_id>/activate", methods=["POST"])
def activate_program(program_id):
    require_roles("ProgramManager")
    program = store.programs.get(program_id)
    if program is None:
        raise api_error("ERR_NOT_FOUND", "program not found")
    if program["status"] == "TRANSITIONING":
        raise api_error("ERR_PROGRAM_TRANSITIONING",
                        "activation is not permitted while the program is TRANSITIONING")
    if program["status"] != "DRAFT":
        raise api_error("ERR_INVALID_STATE", "only a DRAFT program can be activated")
    account = store.accounts.get(program["account_id"])
    if account is None or account["status"] != "ACTIVE":
        raise api_error("ERR_ACCOUNT_NOT_ACTIVE", "the program's account is not ACTIVE")
    active_lines = [l for l in store.lines.values()
                    if l["program_id"] == program_id and l["status"] == "ACTIVE"]
    if len(active_lines) != 1:
        raise api_error("ERR_NO_ACTIVE_LINE",
                        "program must have exactly one ACTIVE line to activate")
    program["status"] = "ACTIVE"
    bump(program)
    return ok(serialize_program(program))


@bp.route("/cabinet/programs/<program_id>/lines", methods=["POST"])
def create_line(program_id):
    require_roles("ProgramManager")
    program = store.programs.get(program_id)
    if program is None:
        raise api_error("ERR_NOT_FOUND", "program not found")
    body = get_body()
    if "expected_program_version" not in body:
        raise api_error("ERR_INVALID_REQUEST", "expected_program_version is required")
    # PRD 2.7 OCC: the only version-guarded write in the API.
    if body.get("expected_program_version") != program["version"]:
        raise api_error("ERR_STALE_VERSION",
                        "expected_program_version does not match the program's current version")
    if program["status"] == "TRANSITIONING":
        raise api_error("ERR_PROGRAM_TRANSITIONING",
                        "line creation is not permitted while the program is TRANSITIONING")
    active_line = get_active_line(program_id)
    if program["status"] == "DRAFT" and active_line is not None:
        raise api_error("ERR_INVALID_STATE",
                        "a DRAFT program already has an ACTIVE line")
    line_code = body.get("line_code")
    if not isinstance(line_code, str) or not line_code:
        raise api_error("ERR_INVALID_REQUEST", "line_code is required")
    for other in store.lines.values():
        if other["program_id"] == program_id and other["line_code"] == line_code:
            raise api_error("ERR_INVALID_REQUEST",
                            "line_code must be unique within the program")
    effective_start_week = body.get("effective_start_week")
    if parse_week(effective_start_week) is None:
        raise api_error("ERR_INVALID_REQUEST",
                        "effective_start_week must be an ISO week 'YYYY-Www'")
    families = body.get("families")
    if not isinstance(families, list) or not families:
        raise api_error("ERR_INVALID_REQUEST", "families must be a non-empty array")
    seen = set()
    clean_families = []
    for fam in families:
        if not isinstance(fam, dict):
            raise api_error("ERR_INVALID_REQUEST", "each family must be an object")
        fc = fam.get("family_code")
        price = fam.get("standard_price_cents")
        lead = fam.get("base_lead_weeks")
        complexity = fam.get("complexity_units_per_cabinet")
        if not isinstance(fc, str) or not fc:
            raise api_error("ERR_INVALID_REQUEST", "family_code is required on every family")
        if fc in seen:
            raise api_error("ERR_INVALID_REQUEST",
                            "family_code must be unique within the line")
        seen.add(fc)
        if isinstance(price, bool) or not isinstance(price, int) or price < 0:
            raise api_error("ERR_INVALID_REQUEST",
                            "standard_price_cents must be a non-negative integer")
        if isinstance(lead, bool) or not isinstance(lead, int) or lead <= 0:
            raise api_error("ERR_INVALID_REQUEST",
                            "base_lead_weeks must be a positive integer")
        if isinstance(complexity, bool) or not isinstance(complexity, int) or complexity <= 0:
            raise api_error("ERR_INVALID_REQUEST",
                            "complexity_units_per_cabinet must be a positive integer")
        clean_families.append({
            "family_code": fc,
            "standard_price_cents": price,
            "base_lead_weeks": lead,
            "complexity_units_per_cabinet": complexity,
        })
    qty = body.get("old_line_disposition_qty", 0)
    if isinstance(qty, bool) or not isinstance(qty, int) or qty < 0:
        raise api_error("ERR_INVALID_REQUEST",
                        "old_line_disposition_qty must be a non-negative integer")
    superseding = program["status"] == "ACTIVE" and active_line is not None
    line = new_entity()
    line.update({
        "program_id": program_id,
        "line_code": line_code,
        "status": "ACTIVE",
        "effective_start_week": effective_start_week,
        "families": clean_families,
        "supersedes_line_id": active_line["id"] if superseding else None,
        "original_disposition_qty": qty,
        "remaining_disposition_qty": 0,
        "disposition_actions": [],
    })
    store.lines[line["id"]] = line
    if superseding:
        supersede_cascade(program, active_line, line, qty)
    # PRD 3.1: every line creation advances the program's version by one.
    bump(program)
    return ok(serialize_line(line), 201)


@bp.route("/cabinet/lines/<line_id>", methods=["GET"])
def get_line(line_id):
    require_roles(*ALL_ROLES)
    line = store.lines.get(line_id)
    if line is None:
        raise api_error("ERR_NOT_FOUND", "program line not found")
    return ok(serialize_line(line))


@bp.route("/cabinet/lines", methods=["GET"])
def list_lines():
    require_roles(*ALL_ROLES)
    program_id = request.args.get("program_id")
    supersedes_line_id = request.args.get("supersedes_line_id")
    status = request.args.get("status")
    items = [l for l in store.lines.values()
             if (program_id is None or l["program_id"] == program_id)
             and (supersedes_line_id is None or l["supersedes_line_id"] == supersedes_line_id)
             and (status is None or l["status"] == status)]
    items = sorted(items, key=lambda l: l["created_at"])
    page, meta = paginate([serialize_line(l) for l in items])
    return ok(page, 200, meta)


@bp.route("/cabinet/lines/<line_id>/disposition-actions", methods=["POST"])
def add_disposition_action(line_id):
    require_roles("ProgramManager")
    line = store.lines.get(line_id)
    if line is None:
        raise api_error("ERR_NOT_FOUND", "program line not found")
    if line["status"] != "SUNSETTING":
        raise api_error("ERR_INVALID_STATE",
                        "disposition actions require a SUNSETTING line")
    body = get_body()
    action_type = body.get("action_type")
    if action_type not in DISPOSITION_TYPES:
        raise api_error("ERR_INVALID_REQUEST",
                        "action_type must be RTV, LIQUIDATE, TRANSFER or DESTROY")
    qty = body.get("qty")
    if isinstance(qty, bool) or not isinstance(qty, int):
        raise api_error("ERR_INVALID_REQUEST", "qty must be an integer")
    program = store.programs[line["program_id"]]
    if action_type != "DESTROY":
        # DESTROY is exempt from the disposition deadline (PRD 3.7).
        deadline = program.get("disposition_deadline")
        if deadline is not None and store.clock > parse_dt(deadline):
            raise api_error("ERR_DISPOSITION_WINDOW_EXPIRED",
                            "the program's disposition deadline has passed")
    remaining = line["remaining_disposition_qty"]
    if qty <= 0 or qty > remaining:
        raise api_error("ERR_DISPOSITION_OVERAGE",
                        "qty must be > 0 and <= remaining_disposition_qty")
    line["disposition_actions"].append({
        "action_type": action_type,
        "qty": qty,
        "created_at": iso3(store.clock),
    })
    line["remaining_disposition_qty"] = remaining - qty
    bump(line)
    maybe_retire_line(line)
    return ok(serialize_line(line), 201)
