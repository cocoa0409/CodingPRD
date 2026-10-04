"""Active ingredients: reference chemistry (PRD 3.1)."""
from flask import Blueprint

import constants
from auth import require_auth, require_role
from db import new_row, store
from envelope import ok, ok_list
from errors import err
from validate import as_enum, as_num, as_str, paginate, parse_body, reject_unknown

bp = Blueprint("active_ingredients", __name__)


@bp.post("/active-ingredients")
def create_active_ingredient():
    caller = require_auth()
    require_role(caller, [constants.ROLE_SYSTEM_ADMINISTRATOR])
    data = parse_body()
    reject_unknown(
        data,
        ["common_name", "cas_number", "tox_category", "reference_dose_mg_kg_day", "aquatic_lc50_ppm"],
    )
    common_name = as_str(data, "common_name", required=True)
    cas_number = as_str(data, "cas_number", required=True)
    tox_category = as_enum(data, "tox_category", constants.TOX_CATEGORIES, required=True)
    reference_dose = as_num(
        data, "reference_dose_mg_kg_day", required=True, minimum=0, exclusive_minimum=True
    )
    aquatic_lc50 = as_num(
        data, "aquatic_lc50_ppm", required=True, minimum=0, exclusive_minimum=True
    )

    if any(a["cas_number"] == cas_number for a in store["active_ingredients"].values()):
        err("ERR_INVALID_REQUEST", "cas_number must be unique across active ingredients.")

    row = new_row()
    row.update(
        {
            "common_name": common_name,
            "cas_number": cas_number,
            "tox_category": tox_category,
            "reference_dose_mg_kg_day": reference_dose,
            "aquatic_lc50_ppm": aquatic_lc50,
        }
    )
    store["active_ingredients"][row["id"]] = row
    return ok(row, status=201)


@bp.get("/active-ingredients")
def list_active_ingredients():
    require_auth()
    rows = list(store["active_ingredients"].values())
    page, limit, offset, total = paginate(rows)
    return ok_list(page, limit, offset, total)
