"""Transition (trade-in) program endpoints."""

from flask import Blueprint, request

from auth import require_ownership, require_roles
from calc import tradein_final_cents, tradein_provisional_cents
from cascades import decommission_instrument
from envelope import ok, ok_list, sort_items
from errors import ApiError, invalid_state, not_found
from serializers import transition_json
from store import DB, new_id, now, stamp_new, touch
from validate import f_dt, f_enum, f_str, get_body, resolve_ref

bp = Blueprint("transitions", __name__)

CONDITION_FLAGS = ["COSMETIC_DAMAGE", "FUNCTIONAL_DEFECT", "MISSING_ACCESSORIES"]


@bp.post("/genomics/transition-programs")
def create_transition():
    uid, _role = require_roles("AccountManager")
    body = get_body()
    resolve_ref(body, "old_instrument_id", "instruments")
    resolve_ref(body, "new_model_id", "models")
    account_id = f_str(body, "account_id")
    old_instrument_id = f_str(body, "old_instrument_id")
    new_model_id = f_str(body, "new_model_id")
    enrollment_window_end = f_dt(body, "enrollment_window_end")
    old_instrument = DB["instruments"][old_instrument_id]
    new_model = DB["models"][new_model_id]
    old_model = DB["models"][old_instrument["model_id"]]
    t = now()
    if t > enrollment_window_end:
        raise ApiError(
            "ERR_ENROLLMENT_WINDOW_CLOSED", 422, "The enrollment window has closed"
        )
    if new_model["generation"] - old_model["generation"] < 1:
        raise ApiError(
            "ERR_ENROLLMENT_WINDOW_CLOSED",
            422,
            "The new model must be a genuine generational move (gap >= 1)",
        )
    program = {
        "id": new_id(),
        "account_id": account_id,
        "old_instrument_id": old_instrument_id,
        "new_model_id": new_model_id,
        "enrollment_window_end": enrollment_window_end,
        "program_state": "ENROLLED",
        "provisional_credit_cents": tradein_provisional_cents(old_model, new_model),
        "condition_flags": [],
        "final_credit_cents": None,
        "created_by_user_id": uid,
        "appraised_by_user_id": None,
        "appraised_at": None,
    }
    stamp_new(program)
    DB["transitions"][program["id"]] = program
    return ok(transition_json(program), 201)


@bp.get("/genomics/transition-programs/<program_id>")
def get_transition(program_id):
    uid, role = require_roles("AccountManager", "FinanceAdmin", "LabOperator")
    program = DB["transitions"].get(program_id)
    if program is None:
        raise not_found("TransitionProgram not found")
    if role == "LabOperator":
        require_ownership(program["account_id"] == uid)
    return ok(transition_json(program))


@bp.get("/genomics/transition-programs")
def list_transitions():
    require_roles("AccountManager", "FinanceAdmin")
    items = list(DB["transitions"].values())
    account_id = request.args.get("account_id")
    program_state = request.args.get("program_state")
    old_instrument_id = request.args.get("old_instrument_id")
    new_model_id = request.args.get("new_model_id")
    if account_id is not None:
        items = [p for p in items if p["account_id"] == account_id]
    if program_state is not None:
        items = [p for p in items if p["program_state"] == program_state]
    if old_instrument_id is not None:
        items = [p for p in items if p["old_instrument_id"] == old_instrument_id]
    if new_model_id is not None:
        items = [p for p in items if p["new_model_id"] == new_model_id]
    return ok_list([transition_json(p) for p in sort_items(items)])


@bp.post("/genomics/transition-programs/<program_id>/advance")
def advance_transition(program_id):
    uid, _role = require_roles("FinanceAdmin")
    program = DB["transitions"].get(program_id)
    if program is None:
        raise not_found("TransitionProgram not found")
    body = get_body()
    action = f_enum(body, "action", ["APPRAISE", "COMPLETE"])
    if action == "APPRAISE":
        flags_raw = body.get("condition_flags")
        flags = []
        if flags_raw is not None:
            if not isinstance(flags_raw, list) or any(
                not isinstance(f, str) or f not in CONDITION_FLAGS for f in flags_raw
            ):
                raise ApiError(
                    "ERR_INVALID_REQUEST",
                    400,
                    "condition_flags members must be one of %s" % "|".join(CONDITION_FLAGS),
                )
            flags = list(dict.fromkeys(flags_raw))
        if program["program_state"] != "ENROLLED":
            raise invalid_state("APPRAISE requires program_state ENROLLED")
        if uid == program["created_by_user_id"]:
            raise ApiError(
                "ERR_SEGREGATION_OF_DUTIES",
                409,
                "Appraiser must differ from the program creator",
            )
        old_instrument = DB["instruments"].get(program["old_instrument_id"])
        old_model = (
            DB["models"].get(old_instrument["model_id"]) if old_instrument is not None else None
        )
        appraisal_at = now()
        program["final_credit_cents"] = tradein_final_cents(
            old_model,
            program["provisional_credit_cents"],
            flags,
            old_instrument["installed_at"] if old_instrument is not None else None,
            appraisal_at,
        )
        program["condition_flags"] = flags
        program["appraised_by_user_id"] = uid
        program["appraised_at"] = appraisal_at
        program["program_state"] = "APPRAISED"
    else:  # COMPLETE
        if program["program_state"] != "APPRAISED":
            raise invalid_state("COMPLETE requires program_state APPRAISED")
        old_instrument = DB["instruments"].get(program["old_instrument_id"])
        if old_instrument is None or old_instrument["install_state"] not in (
            "OPERATIONAL",
            "DOWN_FOR_SERVICE",
        ):
            raise invalid_state(
                "The traded-in instrument must be OPERATIONAL or DOWN_FOR_SERVICE"
            )
        # Cascade: decommission the old instrument (terminating its contracts
        # with final uptime credits), then credit the account the trade-in.
        decommission_instrument(old_instrument)
        account = DB["accounts"].get(program["account_id"])
        if account is not None:
            account["credit_balance_cents"] += program["final_credit_cents"] or 0
            touch(account)
        program["program_state"] = "COMPLETED"
    touch(program)
    return ok(transition_json(program))
