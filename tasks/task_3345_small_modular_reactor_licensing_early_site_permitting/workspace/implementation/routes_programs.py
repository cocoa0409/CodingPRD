"""Adequacy test program and result routes."""
from flask import Blueprint, request

from calc import recompute_completed_tests
from errors import ApiError, ERR_DUPLICATE, ERR_INVALID_STATE, ERR_OUT_OF_ORDER_RESULT
from rbac import require_role
from store import (DB, apply_pagination, base_record, iso_ms, new_uuid,
                   now_iso_ms, paginate_args, parse_iso, serialize,
                   sort_by_created, success_list, success_object, touch)
from validation import (get_or_404, json_body, v_enum, v_int, v_iso, v_str)

bp = Blueprint("programs", __name__, url_prefix="/licensing")


def _invalid(msg):
    return ApiError(ERR_INVALID_STATE, 409, msg)


@bp.post("/dcas/<dca_id>/test-programs")
def create_program(dca_id):
    require_role("DcaApplicant")
    get_or_404("dca", dca_id)
    body = json_body()
    code = v_str(body, "program_code")
    required = v_int(body, "required_tests", minimum=0, exclusive_min=True)
    for p in DB["test_program"].values():
        if p["dca_id"] == dca_id and p["program_code"] == code:
            raise ApiError(ERR_DUPLICATE, 409, "program_code already exists for this application")
    prog = base_record("test_program", {
        "dca_id": dca_id,
        "program_code": code,
        "required_tests": required,
        "completed_tests": 0,
        "status": "PLANNED",
    })
    DB["test_program"][prog["id"]] = prog
    return success_object(serialize(prog), status=201)


@bp.get("/dcas/<dca_id>/test-programs")
def list_programs_of_dca(dca_id):
    require_role("DcaApplicant", "NrcReviewer", "SupplyChainManager")
    get_or_404("dca", dca_id)
    items = sort_by_created([p for p in DB["test_program"].values() if p["dca_id"] == dca_id])
    limit, offset = paginate_args(request.args)
    page, total = apply_pagination(items, limit, offset)
    return success_list([serialize(p) for p in page], total, limit, offset)


@bp.get("/test-programs")
def list_programs():
    require_role()
    items = list(DB["test_program"].values())
    dca_id = request.args.get("dca_id")
    if dca_id is not None:
        items = [p for p in items if p["dca_id"] == dca_id]
    items = sort_by_created(items)
    limit, offset = paginate_args(request.args)
    page, total = apply_pagination(items, limit, offset)
    return success_list([serialize(p) for p in page], total, limit, offset)


@bp.get("/test-programs/<id>")
def get_program(id):
    require_role()
    return success_object(serialize(get_or_404("test_program", id)))


@bp.post("/test-programs/<id>/start")
def start_program(id):
    require_role("DcaApplicant")
    prog = get_or_404("test_program", id)
    if prog["status"] != "PLANNED":
        raise _invalid("program is not PLANNED")
    prog["status"] = "IN_PROGRESS"
    touch(prog)
    return success_object(serialize(prog))


@bp.post("/test-programs/<id>/restart")
def restart_program(id):
    require_role("DcaApplicant")
    prog = get_or_404("test_program", id)
    if prog["status"] != "INSUFFICIENT":
        raise _invalid("program is not INSUFFICIENT")
    prog["status"] = "IN_PROGRESS"
    touch(prog)
    return success_object(serialize(prog))


@bp.post("/test-programs/<id>/results")
def record_result(id):
    require_role("DcaApplicant")
    prog = get_or_404("test_program", id)
    body = json_body()
    outcome = v_enum(body, "outcome", ("PASS", "FAIL"))
    run_at = v_iso(body, "run_at")
    notes = v_str(body, "notes", required=False)

    # chronological recording: run_at must not precede any earlier result
    for r in DB["test_result"].values():
        if r["program_id"] == id:
            prior = parse_iso(r["run_at"])
            if run_at < prior:
                raise ApiError(ERR_OUT_OF_ORDER_RESULT, 422,
                               "run_at precedes an earlier result of this program")

    result = {
        "id": new_uuid(),
        "created_at": now_iso_ms(),
        "program_id": id,
        "outcome": outcome,
        "run_at": iso_ms(run_at),
        "notes": notes,
    }
    DB["test_result"][result["id"]] = result

    passes = recompute_completed_tests(id)
    if outcome == "PASS":
        if prog["status"] == "IN_PROGRESS" and passes >= prog["required_tests"]:
            prog["status"] = "ADEQUATE"
            touch(prog)
    else:  # FAIL
        if prog["status"] == "ADEQUATE":
            prog["status"] = "INSUFFICIENT"
            touch(prog)
            # cascade: PROCURED lots against this program -> REJECTED
            for lot in DB["component_lot"].values():
                if lot["program_id"] == id and lot["status"] == "PROCURED":
                    lot["status"] = "REJECTED"
                    touch(lot)
        elif prog["status"] == "IN_PROGRESS" and passes > 0:
            prog["status"] = "INSUFFICIENT"
            touch(prog)
    return success_object(serialize(result), status=201)


@bp.get("/test-results")
def list_results():
    require_role()
    items = list(DB["test_result"].values())
    program_id = request.args.get("program_id")
    if program_id is not None:
        items = [r for r in items if r["program_id"] == program_id]
    items = sort_by_created(items)
    limit, offset = paginate_args(request.args)
    page, total = apply_pagination(items, limit, offset)
    return success_list([serialize(r) for r in page], total, limit, offset)


@bp.get("/test-results/<id>")
def get_result(id):
    require_role()
    return success_object(serialize(get_or_404("test_result", id)))
