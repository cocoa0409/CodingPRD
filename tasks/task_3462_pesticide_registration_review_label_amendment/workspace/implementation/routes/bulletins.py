"""Endangered-species bulletins (PRD 3.6): county-level use restrictions."""
from flask import Blueprint

import clock
import constants
from auth import require_auth, require_role
from db import new_row, store, touch
from envelope import ok
from errors import err
from services.calcs import bulletin_month_set
from validate import as_enum, as_int, as_num, as_str, parse_body, reject_unknown

bp = Blueprint("bulletins", __name__)


@bp.post("/endangered-species-bulletins")
def create_bulletin():
    caller = require_auth()
    require_role(caller, [constants.ROLE_REGISTRATION_REVIEWER])
    data = parse_body()
    reject_unknown(
        data,
        [
            "product_id",
            "county_fips",
            "restriction_code",
            "rate_cap_lbs_acre",
            "window_start_month",
            "window_end_month",
            "consultation_reference",
        ],
    )
    product_id = as_str(data, "product_id", required=True)
    county_fips = as_str(data, "county_fips", required=True)
    restriction_code = as_enum(
        data, "restriction_code", constants.RESTRICTION_CODES, required=True
    )
    rate_cap = as_num(
        data, "rate_cap_lbs_acre", required=False, minimum=0, exclusive_minimum=True
    )
    # rate_cap_lbs_acre exactly when restriction_code == RATE_CAP.
    if restriction_code == "RATE_CAP":
        if rate_cap is None:
            err(
                "ERR_INVALID_REQUEST",
                "rate_cap_lbs_acre is required for RATE_CAP bulletins.",
            )
    elif rate_cap is not None:
        err(
            "ERR_INVALID_REQUEST",
            "rate_cap_lbs_acre is forbidden unless restriction_code is RATE_CAP.",
        )
    window_start = as_int(data, "window_start_month", required=True)
    window_end = as_int(data, "window_end_month", required=True)
    consultation_reference = as_str(data, "consultation_reference", required=True)

    # Stage 4: existence.
    product = store["products"].get(product_id)
    if product is None:
        err("ERR_PRODUCT_NOT_FOUND", "Product %s does not exist." % product_id)

    # Stage 11: bulletin months in 1..12.
    if not (1 <= window_start <= 12) or not (1 <= window_end <= 12):
        err("ERR_INVALID_REQUEST", "Window months must be integers in 1..12.")

    # Stage 9: same product+county IN_EFFECT windows may not share a month.
    new_months = bulletin_month_set(window_start, window_end)
    for bulletin in store["bulletins"].values():
        if (
            bulletin["product_id"] == product_id
            and bulletin["county_fips"] == county_fips
            and bulletin["status"] == "IN_EFFECT"
        ):
            existing = bulletin_month_set(
                bulletin["window_start_month"], bulletin["window_end_month"]
            )
            if existing & new_months:
                err(
                    "ERR_BULLETIN_WINDOW_OVERLAP",
                    "An IN_EFFECT bulletin for this product and county shares a calendar month.",
                )

    row = new_row()
    row.update(
        {
            "product_id": product_id,
            "county_fips": county_fips,
            "restriction_code": restriction_code,
            "rate_cap_lbs_acre": rate_cap,
            "window_start_month": window_start,
            "window_end_month": window_end,
            "consultation_reference": consultation_reference,
            "status": "IN_EFFECT",
            "effective_at": clock.now(),
            "lifted_at": None,
        }
    )
    store["bulletins"][row["id"]] = row
    return ok(row, status=201)


@bp.post("/endangered-species-bulletins/<bulletin_id>/lift")
def lift_bulletin(bulletin_id):
    caller = require_auth()
    require_role(caller, [constants.ROLE_REGISTRATION_REVIEWER])
    data = parse_body()
    reject_unknown(data, ["lift_reason"])
    if "lift_reason" in data and data["lift_reason"] is not None:
        as_str(data, "lift_reason")

    bulletin = store["bulletins"].get(bulletin_id)
    if bulletin is None:
        err("ERR_NOT_FOUND", "Bulletin %s does not exist." % bulletin_id)
    if bulletin["status"] != "IN_EFFECT":
        err("ERR_BULLETIN_NOT_LIFTABLE", "The bulletin is not IN_EFFECT.")

    bulletin["status"] = "LIFTED"
    bulletin["lifted_at"] = clock.now()
    if data.get("lift_reason") is not None:
        bulletin["lift_reason"] = data["lift_reason"]
    touch(bulletin)
    return ok(bulletin)
