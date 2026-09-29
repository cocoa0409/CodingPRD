"""Parcel intake, acreage derivation and screening (PRD section 3.2)."""

from flask import Blueprint

import access
import calc
import cascades
import serializers as ser
import validation as v
from auth import LAND_AGENT, OPERATOR_ROLES, require
from envelope import ok, ok_list
from errors import ERR_PARCEL_APN_DUPLICATE, ERR_PROHIBITED_ZONING, fail
from store import db, insert, ordered, touch
from util import D

bp = Blueprint("parcels", __name__, url_prefix="/land-origination")

GRADES = ("A", "B", "C", "D")
SCREEN_MODES = ("DESKTOP", "FIELD_VERIFIED")


def _blank_parcel():
    return {
        "screen_mode": "DESKTOP",
        "screening_score": None,
        "screening_tier": None,
        "slope_excluded_acres": D("0.00"),
        "raw_setback_acres": D("0.00"),
        "consent_released_acres": D("0.00"),
        "setback_encumbered_acres": D("0.00"),
        "buildable_acres": D("0.00"),
        "blocking_curative_open_count": 0,
        "waived_blocking_count": 0,
        "curative_cost_cents": 0,
        "status": "SCREENING",
    }


@bp.get("/parcels/<parcel_id>")
@require(*OPERATOR_ROLES)
def get_parcel(parcel_id):
    return ok(ser.parcel(access.parcel(parcel_id)))


@bp.get("/parcels")
@require(*OPERATOR_ROLES)
def list_parcels():
    limit, offset = v.pagination()
    rows = ordered(db.parcels.values())
    rows = v.apply_filters(rows, [
        ("landowner_id", v.query_str("landowner_id")),
        ("county_fips", v.query_str("county_fips")),
        ("screening_tier", v.query_str("screening_tier")),
        ("status", v.query_str("status")),
    ])
    page, total = v.paginate(rows, limit, offset)
    return ok_list(ser.many(ser.parcel, page), limit, offset, total)


@bp.post("/parcels")
@require(LAND_AGENT)
def create_parcel():
    body = v.json_body()
    # Rung 3: the body foreign key resolves before any shape rule.
    owner_id = v.lookup_fk(body, "landowner_id")
    owner = access.landowner(owner_id) if owner_id else None

    v.req_fk(body, "landowner_id")
    apn = v.req_str(body, "apn", min_len=1, max_len=40)
    county_fips = v.req_str(body, "county_fips", min_len=5, max_len=5,
                            pattern=r"^\d{5}$")
    gross_acres = v.req_num(body, "gross_acres", lo=0, lo_exclusive=True)
    distance = v.req_num(body, "interconnection_distance_km", lo=0)
    capacity = v.req_num(body, "resource_capacity_factor", lo=0, hi=1,
                         lo_exclusive=True)
    slope = v.req_num(body, "slope_pct", lo=0, hi=100)
    grade = v.req_enum(body, "title_condition_grade", GRADES)
    zoning = v.req_str(body, "zoning_code", min_len=1, max_len=12)

    for other in db.parcels.values():
        if other["apn"] == apn and other["county_fips"] == county_fips:
            fail(ERR_PARCEL_APN_DUPLICATE)
    if zoning in calc.PROHIBITED_ZONING_CODES:
        fail(ERR_PROHIBITED_ZONING)

    row = _blank_parcel()
    row.update({
        "apn": apn,
        "county_fips": county_fips,
        "landowner_id": owner["id"],
        "gross_acres": gross_acres,
        "interconnection_distance_km": distance,
        "resource_capacity_factor": capacity,
        "slope_pct": slope,
        "title_condition_grade": grade,
        "zoning_code": zoning,
    })
    insert("parcels", row)

    # A brand-new parcel is version 1: the intake chain does not bump it.
    cascades.recompute_parcel_acreage(row, bump=False)
    cascades.recompute_parcel_screening(row, bump=False)
    cascades.reevaluate_parcel_qualification(row, bump=False)
    if row["status"] == "SCREENING" and row["screening_tier"] == "REJECTED":
        row["status"] = "DISQUALIFIED"
    else:
        cascades.sync_landowner_posture(owner)
    return ok(ser.parcel(row), 201)


@bp.post("/parcels/<parcel_id>/rescreen")
@require(LAND_AGENT)
def rescreen_parcel(parcel_id):
    row = access.parcel(parcel_id)
    body = v.json_body()
    mode = v.req_enum(body, "screen_mode", SCREEN_MODES)

    row["screen_mode"] = mode
    cascades.recompute_parcel_acreage(row)
    cascades.recompute_parcel_screening(row)
    cascades.reevaluate_parcel_qualification(row)
    cascades.sync_landowner_posture(db.landowners.get(row["landowner_id"]))

    # The only operator-driven route into the terminal DISQUALIFIED status;
    # it deliberately fires no landowner cascade.
    if row["status"] == "SCREENING" and row["screening_tier"] == "REJECTED":
        row["status"] = "DISQUALIFIED"
        touch(row)
    return ok(ser.parcel(row))
