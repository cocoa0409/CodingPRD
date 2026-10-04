"""Placement program endpoints: create, read, review cycle, amendment cycle,
period close."""

from flask import Blueprint, request

from auth import require_action_role, require_ownership, require_roles
from calc import (
    accrual_expected_cents,
    final_shortfall_and_penalty,
    subsidy_cap_ok,
    subsidy_pool_cents,
)
from envelope import ok, ok_list, sort_items
from errors import ApiError, invalid_state, not_found
from serializers import program_json
from store import DB, new_id, stamp_new, touch
from validate import f_enum, f_int, f_list, f_num, f_str, get_body

bp = Blueprint("programs", __name__)

REVIEW_ACTIONS = {"SUBMIT": "AccountManager", "APPROVE": "FinanceAdmin", "REJECT": "FinanceAdmin"}
AMENDMENT_ACTIONS = {
    "CREATE": "AccountManager",
    "APPROVE": "FinanceAdmin",
    "REJECT": "FinanceAdmin",
}
TERM_MONTHS = (12, 24, 36)


def _validate_hardware_lines(body):
    lines = f_list(body, "hardware_lines")
    out = []
    for ln in lines:
        if not isinstance(ln, dict):
            raise ApiError("ERR_INVALID_REQUEST", 400, "hardware_lines entries must be objects")
        description = ln.get("description")
        quantity = ln.get("quantity")
        unit_price_cents = ln.get("unit_price_cents")
        if not isinstance(description, str) or description == "":
            raise ApiError("ERR_INVALID_REQUEST", 400, "hardware_lines.description must be a string")
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1:
            raise ApiError("ERR_INVALID_REQUEST", 400, "hardware_lines.quantity must be >= 1")
        if (
            isinstance(unit_price_cents, bool)
            or not isinstance(unit_price_cents, int)
            or unit_price_cents < 0
        ):
            raise ApiError("ERR_INVALID_REQUEST", 400, "hardware_lines.unit_price_cents must be >= 0")
        out.append(
            {
                "description": description,
                "quantity": quantity,
                "unit_price_cents": unit_price_cents,
            }
        )
    return out


def _validate_subsidy_pct(body, key="subsidy_pct", required=True):
    pct = f_num(body, key, required=required)
    if pct is not None and not (pct > 0 and pct <= 1):
        raise ApiError("ERR_INVALID_REQUEST", 400, "%s must be in (0, 1]" % key)
    return pct


@bp.post("/genomics/placement-programs")
def create_program():
    uid, _role = require_roles("AccountManager")
    body = get_body()
    account_id = f_str(body, "account_id")
    term_months = f_int(body, "term_months")
    if term_months not in TERM_MONTHS:
        raise ApiError("ERR_INVALID_REQUEST", 400, "term_months must be one of 12, 24, 36")
    committed = f_int(body, "committed_annual_reagent_cents", min_v=0)
    subsidy_pct = _validate_subsidy_pct(body)
    hardware_lines = _validate_hardware_lines(body)
    program = {
        "id": new_id(),
        "account_id": account_id,
        "term_months": term_months,
        "committed_annual_reagent_cents": committed,
        "subsidy_pct": subsidy_pct,
        "hardware_lines": hardware_lines,
        "program_state": "DRAFT",
        "subsidy_pool_cents": None,  # computed at review SUBMIT
        "pinned_kit_prices": None,  # snapshot at review APPROVE
        "delivered_spend_cents": 0,
        "pipeline_spend_cents": 0,
        "shortfall_flag": False,
        "penalty_cents": 0,
        "period_index": 1,
        "created_by_user_id": uid,
        "approved_by_user_id": None,
        "pending_amendment": None,
    }
    stamp_new(program)
    DB["programs"][program["id"]] = program
    return ok(program_json(program), 201)


@bp.get("/genomics/placement-programs/<program_id>")
def get_program(program_id):
    uid, role = require_roles("AccountManager", "FinanceAdmin", "LabOperator")
    program = DB["programs"].get(program_id)
    if program is None:
        raise not_found("PlacementProgram not found")
    if role == "LabOperator":
        require_ownership(program["account_id"] == uid)
    return ok(program_json(program))


@bp.get("/genomics/placement-programs")
def list_programs():
    require_roles("AccountManager", "FinanceAdmin")
    items = list(DB["programs"].values())
    account_id = request.args.get("account_id")
    program_state = request.args.get("program_state")
    if account_id is not None:
        items = [p for p in items if p["account_id"] == account_id]
    if program_state is not None:
        items = [p for p in items if p["program_state"] == program_state]
    return ok_list([program_json(p) for p in sort_items(items)])


@bp.post("/genomics/placement-programs/<program_id>/review")
def review_program(program_id):
    uid, role = require_roles("AccountManager", "FinanceAdmin")
    body = get_body()
    require_action_role(role, body.get("action"), REVIEW_ACTIONS)
    program = DB["programs"].get(program_id)
    if program is None:
        raise not_found("PlacementProgram not found")
    action = f_enum(body, "action", list(REVIEW_ACTIONS.keys()))
    if action == "SUBMIT":
        if program["program_state"] != "DRAFT":
            raise invalid_state("SUBMIT requires program_state DRAFT")
        pool = subsidy_pool_cents(program["hardware_lines"], program["subsidy_pct"])
        if not subsidy_cap_ok(pool, program["committed_annual_reagent_cents"]):
            raise ApiError(
                "ERR_SUBSIDY_CAP_EXCEEDED",
                422,
                "Subsidy pool exceeds 40% of the committed annual reagent spend",
            )
        program["subsidy_pool_cents"] = pool
        program["program_state"] = "PENDING_APPROVAL"
    elif action == "APPROVE":
        if program["program_state"] != "PENDING_APPROVAL":
            raise invalid_state("APPROVE requires program_state PENDING_APPROVAL")
        if uid == program["created_by_user_id"]:
            raise ApiError(
                "ERR_SEGREGATION_OF_DUTIES", 409, "Approver must differ from the program creator"
            )
        program["pinned_kit_prices"] = {
            k["kit_code"]: k["price_cents"] for k in DB["kits"].values()
        }
        program["approved_by_user_id"] = uid
        program["program_state"] = "ACTIVE"
    else:  # REJECT
        if program["program_state"] != "PENDING_APPROVAL":
            raise invalid_state("REJECT requires program_state PENDING_APPROVAL")
        program["program_state"] = "DRAFT"
    touch(program)
    return ok(program_json(program))


@bp.post("/genomics/placement-programs/<program_id>/amendments")
def amend_program(program_id):
    uid, role = require_roles("AccountManager", "FinanceAdmin")
    body = get_body()
    require_action_role(role, body.get("action"), AMENDMENT_ACTIONS)
    program = DB["programs"].get(program_id)
    if program is None:
        raise not_found("PlacementProgram not found")
    action = f_enum(body, "action", list(AMENDMENT_ACTIONS.keys()))
    if action == "CREATE":
        # Shape (400) precedes the state gate (409) per PRD 2.9.
        new_annual = f_int(body, "new_committed_annual_reagent_cents", required=False, min_v=0)
        new_pct = _validate_subsidy_pct(body, key="new_subsidy_pct", required=False)
        expected_version = f_int(body, "expected_program_version", required=True)
        if new_annual is None and new_pct is None:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                400,
                "Provide new_committed_annual_reagent_cents and/or new_subsidy_pct",
            )
        if program["program_state"] != "ACTIVE":
            raise invalid_state("Amendment CREATE requires program_state ACTIVE")
        if expected_version is not None and expected_version != program["version"]:
            raise ApiError(
                "ERR_STALE_VERSION",
                412,
                "expected_program_version does not match the program's current version",
            )
        program["pending_amendment"] = {
            "new_committed_annual_reagent_cents": new_annual,
            "new_subsidy_pct": new_pct,
            "created_by_user_id": uid,
        }
        program["program_state"] = "UNDER_AMENDMENT"
    elif action == "APPROVE":
        if program["program_state"] != "UNDER_AMENDMENT":
            raise invalid_state("Amendment APPROVE requires program_state UNDER_AMENDMENT")
        pending = program["pending_amendment"]
        if pending is not None and uid == pending.get("created_by_user_id"):
            raise ApiError(
                "ERR_SEGREGATION_OF_DUTIES",
                409,
                "Approver must differ from the amendment creator",
            )
        if pending is not None:
            if pending.get("new_committed_annual_reagent_cents") is not None:
                program["committed_annual_reagent_cents"] = pending[
                    "new_committed_annual_reagent_cents"
                ]
            if pending.get("new_subsidy_pct") is not None:
                program["subsidy_pct"] = pending["new_subsidy_pct"]
        program["pending_amendment"] = None
        program["subsidy_pool_cents"] = subsidy_pool_cents(
            program["hardware_lines"], program["subsidy_pct"]
        )
        program["program_state"] = "ACTIVE"
    else:  # REJECT
        if program["program_state"] != "UNDER_AMENDMENT":
            raise invalid_state("Amendment REJECT requires program_state UNDER_AMENDMENT")
        program["pending_amendment"] = None
        program["program_state"] = "ACTIVE"
    touch(program)
    return ok(program_json(program))


@bp.post("/genomics/placement-programs/<program_id>/close-period")
def close_period(program_id):
    require_roles("FinanceAdmin")
    program = DB["programs"].get(program_id)
    if program is None:
        raise not_found("PlacementProgram not found")
    if program["program_state"] != "ACTIVE":
        raise invalid_state("close-period requires program_state ACTIVE")
    if program["period_index"] < program["term_months"]:
        # Interim close: accrual variant, sets shortfall_flag only.
        expected = accrual_expected_cents(program)
        program["shortfall_flag"] = program["delivered_spend_cents"] < expected
        program["period_index"] += 1
    else:
        # Final close: full-term reconciliation drives COMPLETED or BREACHED.
        shortfall, penalty = final_shortfall_and_penalty(program)
        if shortfall == 0:
            program["program_state"] = "COMPLETED"
        else:
            program["penalty_cents"] = penalty
            program["program_state"] = "BREACHED"  # account credit_hold derives from this
    touch(program)
    return ok(program_json(program))
