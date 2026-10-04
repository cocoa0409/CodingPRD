"""/survey/benchmark-runs: create and apply (PRD 3.7)."""
from flask import Blueprint

from authz import get_auth, require_role
from bp_programs import find_program_by_code
from calc_apply import apply_benchmark
from envelope import ok
from errors import (
    raise_err, ERR_VALIDATION, ERR_PROGRAM_NOT_FOUND, ERR_BENCHMARK_NOT_FOUND,
    ERR_INVALID_STATE,
)
from store import DB, new_entity, INDUSTRIES, SIZE_CLASSES
from validate import get_body, req_str, parse_month_field, month_str

bp = Blueprint("benchmarks", __name__)


def _validate_admin_cells(data):
    entries = data.get("admin_cell_counts")
    if not isinstance(entries, list) or not entries:
        raise_err(ERR_VALIDATION, "admin_cell_counts must be a non-empty array")
    seen = set()
    out = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise_err(ERR_VALIDATION, "each admin cell entry must be an object")
        ind = entry.get("industry_code")
        size = entry.get("size_class")
        if ind not in INDUSTRIES:
            raise_err(ERR_VALIDATION, "admin cell industry_code is invalid")
        if size not in SIZE_CLASSES:
            raise_err(ERR_VALIDATION, "admin cell size_class is invalid")
        emp = entry.get("admin_employment")
        if not isinstance(emp, int) or isinstance(emp, bool) or emp < 0:
            raise_err(ERR_VALIDATION, "admin_employment must be an integer >= 0")
        if (ind, size) in seen:
            raise_err(ERR_VALIDATION,
                      "at most one admin entry per (industry_code, size_class)")
        seen.add((ind, size))
        out.append({"industry_code": ind, "size_class": size, "admin_employment": emp})
    return out


@bp.post("/benchmark-runs")
def create_benchmark():
    _user, role = get_auth()
    require_role(role, {"SurveyMethodologist"})
    data = get_body()

    program = None
    if data.get("program_code") is not None:
        program = find_program_by_code(data["program_code"])
        if program is None:
            raise_err(ERR_PROGRAM_NOT_FOUND, "program_code does not resolve")

    req_str(data, "program_code")
    mref = parse_month_field(data, "benchmark_month")
    admin_cells = _validate_admin_cells(data)

    run = new_entity("benchmarks", {
        "program_code": program["code"],
        "benchmark_month": month_str(mref),
        "admin_cell_counts": admin_cells,
        "run_status": "DRAFT",
        "applied_at": None,
    })
    return ok(run, status=201)


@bp.post("/benchmark-runs/<bid>/apply")
def apply_benchmark_endpoint(bid):
    _user, role = get_auth()
    require_role(role, {"SurveyMethodologist"})
    run = DB["benchmarks"].get(bid)
    if run is None:
        raise_err(ERR_BENCHMARK_NOT_FOUND, "benchmark run not found")
    if run["run_status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE, "only a DRAFT benchmark run can be applied")
    apply_benchmark(run)
    return ok(run)
