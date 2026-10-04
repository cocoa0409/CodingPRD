"""Grading and packing (PRD §3.9): OCC-guarded run creation consuming the
program's ungraded bucket, the computed size-class carton assortment, and
verification."""

from flask import Blueprint, request

from auth import authenticate, require_role
from calc import UNGRADED_FIELD, packing_distribution
from db import STORE, stamp_new, touch
from errors import (
    ApiError,
    ERR_COMPLEX_QUARANTINED,
    ERR_INSUFFICIENT_UNGRADED_INVENTORY,
    ERR_INVALID_STATE,
    ERR_STALE_COMPLEX_VERSION,
)
from helpers import get_complex, get_packing_run, list_response
from serialize import serialize_packing_run
from util import PROGRAMS, success_object
from validate import apply_values, get_body, validate_payload

bp = Blueprint("packing", __name__)


@bp.route("/api/complexes/<cid>/packing-runs", methods=["POST"])
def create_packing_run(cid):
    _uid, role = authenticate()
    require_role(role, {"PlantManager"})
    cx = get_complex(cid)
    values, raws = validate_payload(
        get_body(),
        {
            "program": {"kind": "enum", "required": True, "enum": PROGRAMS},
            "dozen_input": {"kind": "int", "required": True, "gt": 0},
            "run_date": {"kind": "datetime", "required": True},
            "expected_complex_version": {"kind": "int", "required": True},
        },
    )
    # Priority 8: optimistic concurrency on the complex version.
    if values["expected_complex_version"] != cx["version"]:
        raise ApiError(
            ERR_STALE_COMPLEX_VERSION,
            412,
            "expected_complex_version does not match the complex version",
        )
    # Priority 9: quarantine blocks packing outright.
    if cx["biosecurity_posture"] == "QUARANTINE":
        raise ApiError(
            ERR_COMPLEX_QUARANTINED, 409, "complex is under quarantine"
        )
    bucket = UNGRADED_FIELD[values["program"]]
    if cx[bucket] < values["dozen_input"]:
        raise ApiError(
            ERR_INSUFFICIENT_UNGRADED_INVENTORY,
            422,
            "the program's ungraded bucket holds fewer dozen than dozen_input",
        )
    # Raises ERR_NO_LAYING_FLOCK_FOR_PROGRAM when no LAYING flock qualifies.
    cases_by_size, total_cases = packing_distribution(
        cx["id"], values["program"], values["dozen_input"]
    )
    run = {
        "complex_id": cx["id"],
        "program": values["program"],
        "dozen_input": values["dozen_input"],
        "cases_by_size": cases_by_size,
        "total_cases": total_cases,
        "status": "PACKED",
    }
    apply_values(run, {"run_date": values["run_date"]},
                 {"run_date": raws["run_date"]})
    stamp_new(run)
    STORE.packing_runs[run["id"]] = run
    cx[bucket] -= values["dozen_input"]
    touch(cx)
    return success_object(serialize_packing_run(run), 201)


@bp.route("/api/complexes/<cid>/packing-runs", methods=["GET"])
def list_packing_runs(cid):
    authenticate()
    cx = get_complex(cid)
    items = [r for r in STORE.packing_runs.values() if r["complex_id"] == cx["id"]]
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    program = request.args.get("program")
    if program is not None:
        items = [r for r in items if r["program"] == program]
    return list_response(items, serialize_packing_run)


@bp.route("/api/packing-runs/<pid>/verify", methods=["POST"])
def verify_packing_run(pid):
    _uid, role = authenticate()
    require_role(role, {"PlantManager"})
    run = get_packing_run(pid)
    validate_payload(get_body(), {})
    if run["status"] != "PACKED":
        raise ApiError(ERR_INVALID_STATE, 409, "packing run is not PACKED")
    run["status"] = "VERIFIED"
    touch(run)
    return success_object(serialize_packing_run(run))
