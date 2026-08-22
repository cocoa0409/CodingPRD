"""Property lifecycle (PRD 3.1) and the season clock (PRD 2.5)."""

from decimal import Decimal

from flask import Blueprint, request

import db
from db import store, new_row, touch
from errors import ApiError
from middleware import endpoint
from response import ok, created
from services.serialize import property_out
from util import body_of, fail, v_str, v_int, v_num, v_enum, v_dt

bp = Blueprint("properties", __name__)

SPORT_CODES = {"FOOTBALL", "BASKETBALL", "SOCCER", "HOCKEY", "BASEBALL"}
PROPERTY_STATUSES = ("PLANNING", "SELLING", "IN_SEASON", "CLOSED")
READ_ROLES = ["PropertyAdmin", "SponsorshipSeller", "ContractApprover",
              "ActivationManager", "PerformanceAuditor"]


def get_property_or_404(property_id):
    prop = store.properties.get(property_id)
    if prop is None:
        raise ApiError("ERR_PROPERTY_NOT_FOUND", 404)
    return prop


@bp.post("/properties")
@endpoint(["PropertyAdmin"])
def create_property():
    body = body_of(request)
    name = v_str(body, "name", min_len=1, max_len=120)
    sport_code = v_enum(body, "sport_code", SPORT_CODES)
    season_year = v_int(body, "season_year", min_v=2020, max_v=2100)
    season_start_raw, season_start = v_dt(body, "season_start")
    season_end_raw, season_end = v_dt(body, "season_end")
    target = v_int(body, "inventory_target_value_cents", min_v=0)
    seasonality = v_num(body, "seasonality_index", required=False,
                        default=Decimal("1.00"), min_v="0.50", max_v="2.00", max_dp=2)
    if season_end <= season_start:
        fail("season_end must be strictly after season_start.")

    row = new_row()
    row.update({
        "name": name,
        "sport_code": sport_code,
        "season_year": season_year,
        "season_start": season_start_raw,
        "_season_start_dt": season_start,
        "season_end": season_end_raw,
        "_season_end_dt": season_end,
        "status": "PLANNING",
        "seasonality_index": seasonality,
        "inventory_target_value_cents": target,
        "committed_gross_value_cents": 0,
        "delivered_media_value_cents": 0,
        "sellout_pct": Decimal("0.00"),
    })
    store.properties[row["id"]] = row
    return created(property_out(row))


@bp.get("/properties/<property_id>")
@endpoint(READ_ROLES)
def read_property(property_id):
    return ok(property_out(get_property_or_404(property_id)))


@bp.post("/properties/<property_id>/transition")
@endpoint(["PropertyAdmin"])
def transition_property(property_id):
    prop = get_property_or_404(property_id)
    body = body_of(request)
    to_status = v_enum(body, "to_status", set(PROPERTY_STATUSES))

    current = prop["status"]
    declared = {("PLANNING", "SELLING"), ("SELLING", "IN_SEASON"), ("IN_SEASON", "CLOSED")}
    if (current, to_status) not in declared:
        raise ApiError("ERR_INVALID_STATE", 409)

    if to_status == "SELLING":
        if not db.published_rate_cards(prop["id"]):
            raise ApiError("ERR_NO_PUBLISHED_RATE_CARD", 409)
    elif to_status == "CLOSED":
        open_contracts = [c for c in db.contracts_of_property(prop["id"])
                          if c["status"] in ("COUNTERSIGNED", "ACTIVE")]
        if open_contracts:
            raise ApiError("ERR_OPEN_CONTRACTS", 409)
    elif to_status == "IN_SEASON":
        if store.now() < prop["_season_start_dt"]:
            raise ApiError("ERR_SEASON_NOT_STARTED", 409)

    prop["status"] = to_status
    touch(prop)
    return ok(property_out(prop))


@bp.post("/_clock/set_current_utc")
@endpoint(["PropertyAdmin"])
def set_clock():
    body = body_of(request)
    raw, parsed = v_dt(body, "to_iso8601")
    store.set_clock(raw, parsed)
    return ok({"current_utc": store.now_raw()})
