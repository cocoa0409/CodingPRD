"""/survey/seasonal-factor-sets: create, list, finalize (PRD 3.6)."""
from datetime import datetime, timezone
from decimal import Decimal
from flask import Blueprint, request

from authz import get_auth, require_role
from bp_programs import find_program_by_code
from envelope import ok, ok_list, paginate
from errors import (
    raise_err, ERR_VALIDATION, ERR_PROGRAM_NOT_FOUND, ERR_FACTOR_SET_NOT_FOUND,
    ERR_INVALID_STATE, ERR_FACTOR_SET_FINALIZE_TOO_EARLY, ERR_FACTOR_SET_INVALID,
)
from store import (
    DB, new_entity, sorted_entities, touch, now, round0,
    FACTOR_COUNT, FACTOR_MIN, FACTOR_MAX, FACTOR_MEAN_TOLERANCE,
)
from validate import get_body, req_str, req_int, req_industry, req_size, is_number

bp = Blueprint("seasonal", __name__)


def _validate_factors(data):
    factors = data.get("factors")
    if not isinstance(factors, list):
        raise_err(ERR_VALIDATION, "factors must be an array of 12 numbers")
    if len(factors) != FACTOR_COUNT:
        raise_err(ERR_FACTOR_SET_INVALID, "factors must have exactly 12 entries")
    values = []
    for f in factors:
        if not is_number(f):
            raise_err(ERR_FACTOR_SET_INVALID, "each factor must be a number")
        d = Decimal(str(f))
        if d < FACTOR_MIN or d > FACTOR_MAX:
            raise_err(ERR_FACTOR_SET_INVALID,
                      "each factor must lie within [0.2, 5.0]")
        values.append(d)
    mean = sum(values) / Decimal(FACTOR_COUNT)
    if abs(mean - Decimal("1.0")) > FACTOR_MEAN_TOLERANCE:
        raise_err(ERR_FACTOR_SET_INVALID,
                  "factor mean must lie within 1.0 +/- 0.0005 inclusive")
    return factors


@bp.post("/seasonal-factor-sets")
def create_factor_set():
    _user, role = get_auth()
    require_role(role, {"SurveyMethodologist"})
    data = get_body()

    program = None
    if data.get("program_code") is not None:
        program = find_program_by_code(data["program_code"])
        if program is None:
            raise_err(ERR_PROGRAM_NOT_FOUND, "program_code does not resolve")

    req_str(data, "program_code")
    industry = req_industry(data)
    size = req_size(data)
    year = req_int(data, "year")
    factors = _validate_factors(data)

    # A new set supersedes any existing set for the same series+year.
    for fs in DB["factor_sets"].values():
        if (fs["program_code"] == program["code"]
                and fs["industry_code"] == industry
                and fs["size_class"] == size
                and fs["year"] == year
                and fs["set_status"] != "SUPERSEDED"):
            fs["set_status"] = "SUPERSEDED"
            touch(fs)

    factor_set = new_entity("factor_sets", {
        "program_code": program["code"],
        "industry_code": industry,
        "size_class": size,
        "year": year,
        "factors": factors,
        "set_status": "PROVISIONAL",
        "finalized_at": None,
    })
    return ok(factor_set, status=201)


@bp.get("/seasonal-factor-sets")
def list_factor_sets():
    get_auth()
    items = sorted_entities("factor_sets")
    for param in ("program_code", "industry_code", "size_class", "set_status"):
        value = request.args.get(param)
        if value is not None:
            items = [f for f in items if f[param] == value]
    year = request.args.get("year")
    if year is not None:
        try:
            year_int = int(year)
        except ValueError:
            raise_err(ERR_VALIDATION, "year filter must be an integer")
        items = [f for f in items if f["year"] == year_int]
    page, pagination = paginate(items)
    return ok_list(page, pagination)


@bp.post("/seasonal-factor-sets/<fid>/finalize")
def finalize_factor_set(fid):
    _user, role = get_auth()
    require_role(role, {"SurveyMethodologist"})
    fs = DB["factor_sets"].get(fid)
    if fs is None:
        raise_err(ERR_FACTOR_SET_NOT_FOUND, "seasonal factor set not found")
    if fs["set_status"] != "PROVISIONAL":
        raise_err(ERR_INVALID_STATE, "only a PROVISIONAL factor set can be finalized")
    earliest = datetime(fs["year"] + 1, 1, 1, tzinfo=timezone.utc)
    if now() < earliest:
        raise_err(ERR_FACTOR_SET_FINALIZE_TOO_EARLY,
                  "factor sets finalize no earlier than January 1 of year + 1")

    fs["set_status"] = "FINAL"
    fs["finalized_at"] = now()
    touch(fs)

    # Recompute seasonally_adjusted_revised on every cell of this program and
    # series whose cycle reference_month falls within the factor year.
    for cell in DB["cells"].values():
        if cell["program_code"] != fs["program_code"]:
            continue
        if (cell["industry_code"], cell["size_class"]) != (fs["industry_code"], fs["size_class"]):
            continue
        cycle = DB["cycles"].get(cell["cycle_id"])
        if cycle is None:
            continue
        cy, cm = int(cycle["reference_month"][:4]), int(cycle["reference_month"][5:7])
        if cy != fs["year"]:
            continue
        cell["seasonally_adjusted_revised"] = round0(
            Decimal(cell["employment_estimate"]) / Decimal(str(fs["factors"][cm - 1])))
        touch(cell)
    return ok(fs)
