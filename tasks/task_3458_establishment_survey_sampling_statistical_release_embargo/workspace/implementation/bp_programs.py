"""POST/GET /survey/programs (PRD 3.1)."""
from flask import Blueprint

from authz import get_auth, require_role
from envelope import ok, ok_list, paginate
from errors import raise_err, ERR_VALIDATION
from store import (
    DB, new_entity, sorted_entities,
    DEFAULT_EMBARGO_WINDOW_MINUTES, EMBARGO_WINDOW_MIN, EMBARGO_WINDOW_MAX,
    DEFAULT_BURDEN_BUDGET_MINUTES, MIN_BURDEN_BUDGET_MINUTES,
)
from validate import (
    get_body, req_str, req_int, opt_int, PROGRAM_CODE_RE,
)

bp = Blueprint("programs", __name__)


@bp.post("/programs")
def create_program():
    _user, role = get_auth()
    require_role(role, {"ProgramAdmin"})
    data = get_body()

    code = req_str(data, "code")
    if not PROGRAM_CODE_RE.match(code):
        raise_err(ERR_VALIDATION, "program code must be uppercase letters/digits")
    name = req_str(data, "name")
    sample_budget = req_int(data, "sample_budget", minimum=2)
    embargo_window = opt_int(
        data, "embargo_window_minutes",
        default=DEFAULT_EMBARGO_WINDOW_MINUTES,
        minimum=EMBARGO_WINDOW_MIN, maximum=EMBARGO_WINDOW_MAX,
    )
    burden_budget = opt_int(
        data, "annual_burden_budget_minutes",
        default=DEFAULT_BURDEN_BUDGET_MINUTES,
        minimum=MIN_BURDEN_BUDGET_MINUTES,
    )

    if any(p["code"] == code for p in DB["programs"].values()):
        raise_err(ERR_VALIDATION, f"program code '{code}' already exists")

    program = new_entity("programs", {
        "code": code,
        "name": name,
        "sample_budget": sample_budget,
        "embargo_window_minutes": embargo_window,
        "annual_burden_budget_minutes": burden_budget,
    })
    return ok(program, status=201)


@bp.get("/programs")
def list_programs():
    get_auth()
    items = sorted_entities("programs")
    page, pagination = paginate(items)
    return ok_list(page, pagination)


def find_program_by_code(code):
    return next((p for p in DB["programs"].values() if p["code"] == code), None)
