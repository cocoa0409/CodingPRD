"""Census tracts: immutable configuration with a computed distress profile (PRD 3.2)."""
from flask import Blueprint

import clock
import validators as v
from db import db, new_id
from errors import fail
from middleware import ALL_ROLES, by_created_desc, endpoint, filter_str
from services import calc

bp = Blueprint("tracts", __name__)


def load_tract(tract_id):
    tract = db.tracts.get(tract_id)
    if tract is None:
        fail("ERR_CENSUS_TRACT_NOT_FOUND")
    return tract


@bp.route("/nmtc/census-tracts", methods=["POST"])
@endpoint(["CertifyingAgency"], mutating=True, status=201)
def create_tract():
    data = v.body()
    tract_code = v.req_str(data, "tract_code", 11, 11, v.ELEVEN_DIGITS)
    state_code = v.req_str(data, "state_code", 2, 2, v.TWO_UPPER)
    poverty = v.req_pct(data, "poverty_rate_pct")
    mfi = v.req_pct(data, "mfi_ratio_pct", "0.00", "300.00")
    unemployment = v.req_pct(data, "unemployment_ratio", "0.00", "10.00")
    contiguous_id = v.opt_str(data, "contiguous_lic_tract_id")

    neighbour = None
    if contiguous_id is not None:
        neighbour = db.tracts.get(contiguous_id)
        if neighbour is None:
            fail("ERR_CENSUS_TRACT_NOT_FOUND")

    for existing in db.tracts.values():
        if existing["tract_code"] == tract_code:
            fail("ERR_DUPLICATE_TRACT_CODE")

    if neighbour is not None and not neighbour["is_low_income_community"]:
        fail("ERR_TRACT_NOT_LIC_ELIGIBLE")

    profile = calc.tract_profile(poverty, mfi, unemployment, contiguous_id)
    row = {
        "id": new_id(),
        "created_at": clock.now(),
        "tract_code": tract_code,
        "state_code": state_code,
        "poverty_rate_pct": poverty,
        "mfi_ratio_pct": mfi,
        "unemployment_ratio": unemployment,
        "contiguous_lic_tract_id": contiguous_id,
        "is_low_income_community": profile["is_low_income_community"],
        "qualifies_by_contiguity": profile["qualifies_by_contiguity"],
        "eligible_for_qlici": profile["eligible_for_qlici"],
        "severe_criteria_met_count": profile["severe_criteria_met_count"],
        "distress_score": profile["distress_score"],
        "distress_tier": profile["distress_tier"],
        "_seq": db.next_seq(),
    }
    db.tracts[row["id"]] = row
    return row, 201


@bp.route("/nmtc/census-tracts", methods=["GET"])
@endpoint(ALL_ROLES)
def list_tracts():
    rows = list(db.tracts.values())
    rows = filter_str(rows, "state_code")
    rows = filter_str(rows, "distress_tier")
    rows = filter_str(rows, "contiguous_lic_tract_id")
    return by_created_desc(rows)


@bp.route("/nmtc/census-tracts/<tract_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def read_tract(tract_id):
    return load_tract(tract_id)
