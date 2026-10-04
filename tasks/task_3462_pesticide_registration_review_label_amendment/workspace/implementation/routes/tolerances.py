"""Tolerances (PRD 3.4): registrant-proposed residue ceilings."""
from flask import Blueprint

import constants
from auth import require_auth, require_role
from db import new_row, store
from envelope import ok
from errors import err
from validate import as_num, as_str, parse_body, reject_unknown

bp = Blueprint("tolerances", __name__)


@bp.post("/tolerances")
def create_tolerance():
    caller = require_auth()
    require_role(caller, [constants.ROLE_REGISTRANT_REPRESENTATIVE])
    data = parse_body()
    reject_unknown(data, ["product_id", "commodity_code", "tolerance_ppm"])
    product_id = as_str(data, "product_id", required=True)
    commodity_code = as_str(data, "commodity_code", required=True)
    tolerance_ppm = as_num(
        data, "tolerance_ppm", required=True, minimum=0, exclusive_minimum=True
    )

    product = store["products"].get(product_id)
    if product is None:
        err("ERR_PRODUCT_NOT_FOUND", "Product %s does not exist." % product_id)
    if product["registrant_ref"] != caller["user_id"]:
        err("ERR_NOT_RESOURCE_OWNER", "The product belongs to another registrant.")
    if product["status"] == "CANCELLED":
        err("ERR_PRODUCT_TERMINAL", "The product is CANCELLED.")

    # Stage 9: one PROPOSED/ESTABLISHED tolerance per (product, commodity).
    for tol in store["tolerances"].values():
        if (
            tol["product_id"] == product_id
            and tol["commodity_code"] == commodity_code
            and tol["status"] in ("PROPOSED", "ESTABLISHED")
        ):
            err(
                "ERR_DUPLICATE_TOLERANCE",
                "A live tolerance already exists for this product and commodity.",
            )

    # Stage 10: commodity known to the dietary model.
    if commodity_code not in constants.CONSUMPTION_G_DAY:
        err("ERR_UNKNOWN_COMMODITY", "Unknown commodity_code %s." % commodity_code)

    row = new_row()
    row.update(
        {
            "product_id": product_id,
            "origin": "INITIAL_APPLICATION",
            "commodity_code": commodity_code,
            "tolerance_ppm": tolerance_ppm,
            "status": "PROPOSED",
            "established_at": None,
            "revoked_at": None,
            "pre_revocation_status": None,
        }
    )
    store["tolerances"][row["id"]] = row
    return ok(row, status=201)
