"""WaterYears and HydrologyObservations (PRD section 3.2)."""
from flask import Blueprint, request

from auth import ALL_ROLES, authenticate
from calc import singleton_reservoir
from envelope import list_response, success
from errors import ApiError, not_found
from serial import observation_view, water_year_view
from store import DB, clock_now, new_id, new_record, next_seq, touch
from validate import as_datetime, as_enum, as_int, as_int_range, get_body, required

bp = Blueprint("water_years", __name__)

OBSERVATION_TYPES = ("SNOWPACK_INDEX", "RUNOFF_FORECAST_AF", "MEASURED_INFLOW_AF")


def year_or_404(water_year_id):
    year = DB["water_years"].get(water_year_id)
    if year is None:
        not_found("WaterYear")
    return year


@bp.post("/water/water-years")
def create_water_year():
    authenticate(["ReclamationOperator"])
    body = get_body()
    label = as_int(required(body, "label"), "label")
    season_start = as_datetime(required(body, "season_start"), "season_start")
    season_end = as_datetime(required(body, "season_end"), "season_end")
    if season_start >= season_end:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "season_start must be strictly before season_end")
    for y in DB["water_years"].values():
        if y["label"] == label:
            raise ApiError("ERR_DUPLICATE_WATER_YEAR", 409,
                           "water-year label already exists")
    rec = new_record()
    rec.update({
        "label": label,
        "season_start": season_start,
        "season_end": season_end,
        "status": "OPEN",
        "current_announcement_id": None,
    })
    DB["water_years"][rec["id"]] = rec
    return success(water_year_view(rec), 201)


@bp.get("/water/water-years/<string:water_year_id>")
def get_water_year(water_year_id):
    authenticate(ALL_ROLES)
    return success(water_year_view(year_or_404(water_year_id)))


@bp.post("/water/water-years/<string:water_year_id>/finalize")
def finalize_water_year(water_year_id):
    authenticate(["ReclamationOperator"])
    year = year_or_404(water_year_id)
    if year["current_announcement_id"] is None:
        raise ApiError("ERR_NO_PUBLISHED_ANNOUNCEMENT", 409,
                       "the water year has no PUBLISHED announcement")
    if year["status"] != "ANNOUNCED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "only an ANNOUNCED water year can be finalized")
    year["status"] = "CLOSED"
    touch(year)
    return success(water_year_view(year), 200)


@bp.post("/water/water-years/<string:water_year_id>/hydrology-observations")
def create_observation(water_year_id):
    authenticate(["HydrologyOfficer"])
    body = get_body()
    obs_type = as_enum(required(body, "observation_type"), "observation_type",
                       OBSERVATION_TYPES)
    value = as_int_range(required(body, "value"), "value", 0)
    observed_on = as_datetime(required(body, "observed_on"), "observed_on")
    # existence: path id, then the measured-inflow singleton reservoir rule
    year = year_or_404(water_year_id)
    reservoir = None
    if obs_type == "MEASURED_INFLOW_AF":
        reservoir = singleton_reservoir()
        if reservoir is None:
            not_found("Reservoir")
    # state gate: no observations into a CLOSED year
    if year["status"] == "CLOSED":
        raise ApiError("ERR_YEAR_CLOSED", 409,
                       "observations cannot be posted to a CLOSED water year")
    # HydrologyObservation carries only id + created_at (PRD section 2.5)
    rec = {
        "id": new_id(),
        "created_at": clock_now(),
        "_seq": next_seq(),
        "water_year_id": year["id"],
        "observation_type": obs_type,
        "value": value,
        "observed_on": observed_on,
    }
    DB["observations"][rec["id"]] = rec
    if obs_type == "MEASURED_INFLOW_AF":
        # measured inflow credits storage directly at creation
        reservoir["current_storage_af"] += value
        touch(reservoir)
    return success(observation_view(rec), 201)


@bp.get("/water/water-years/<string:water_year_id>/hydrology-observations")
def list_observations(water_year_id):
    authenticate(ALL_ROLES)
    year = year_or_404(water_year_id)
    filters = {"observation_type": request.args.get("observation_type")}
    records = [o for o in DB["observations"].values()
               if o["water_year_id"] == year["id"]]
    return list_response(records, observation_view, filters)
