"""Land application site endpoints (PRD 3.5)."""

from decimal import Decimal

from flask import Blueprint

import store
from auth import roles
from derive import (active_limits, annual_loading, cumulative_loading,
                    defer_pre_field_events, derive_site_odor, events_of_site,
                    recompute_site_loading)
from envelope import object_response
from errors import fail
from listing import emit_list
from store import D, now, now_iso, public, r2, touch
from validate import (get_body, qenum, qint, qstr, resolve_fks, venum, vint, vmonths,
                      vnum, vstr)

bp = Blueprint("sites", __name__, url_prefix="/api/v1/land-application-sites")

CROP_TYPES = ("CORN", "SOYBEAN", "HAY", "SMALL_GRAIN", "PASTURE")
SITE_STATUSES = ("DRAFT", "UNDER_REVIEW", "PERMITTED", "RESTRICTED", "CLOSED")
SITE_READ_ROLES = ("Agronomist", "ComplianceOfficer", "FacilityOperator",
                   "PublicLiaison", "Farmer")
OPEN_EVENT_STATUSES = ("SCHEDULED", "WEATHER_HOLD", "DEFERRED", "IN_PROGRESS")


def get_site(site_id):
    site = store.sites.get(site_id)
    if site is None:
        fail("ERR_SITE_NOT_FOUND", "Site %s does not exist." % site_id)
    return site


@bp.post("")
@roles("Agronomist")
def create_site():
    body = get_body()
    fks = resolve_fks(body, ("facility_id",))
    facility_id = body.get("facility_id")
    if not isinstance(facility_id, str) or not facility_id.strip():
        fail("ERR_INVALID_REQUEST", "Field 'facility_id' is required.")
    facility = fks["facility_id"]
    site_code = vstr(body, "site_code", required=True, min_len=1)
    acres = vnum(body, "acres", required=True, gt=0)
    crop_type = venum(body, "crop_type", CROP_TYPES, required=True)
    crop_n = vnum(body, "crop_n_demand_lb_per_acre", required=True, gt=0)
    crop_p = vnum(body, "crop_p_removal_lb_per_acre", required=True, gt=0)
    soil_p_index = vnum(body, "soil_p_index", required=True, ge=0)
    setback_well = vnum(body, "setback_to_well_ft", required=True, ge=0)
    setback_water = vnum(body, "setback_to_surface_water_ft", required=True, ge=0)
    months = vmonths(body, "allowed_application_months", required=True)
    soil_ph = vnum(body, "soil_ph", required=False, default=Decimal("6.5"), ge=0)
    depth = vnum(body, "depth_to_groundwater_ft", required=False,
                 default=Decimal("10.0"), ge=0)
    slope = vnum(body, "slope_pct", required=False, default=Decimal("3.0"), ge=0)
    residence = vnum(body, "nearest_residence_ft", required=False,
                     default=Decimal("3000"), ge=0)
    reapplication = vint(body, "reapplication_interval_days", required=False, default=30,
                         ge=0)

    for existing in store.sites.values():
        if existing["facility_id"] == facility["id"] and existing["site_code"] == site_code:
            fail("ERR_DUPLICATE_RESOURCE",
                 "site_code %s already exists for this facility." % site_code)

    site = store.new_record({
        "facility_id": facility["id"],
        "site_code": site_code,
        "acres": r2(acres),
        "crop_type": crop_type,
        "crop_n_demand_lb_per_acre": crop_n,
        "crop_p_removal_lb_per_acre": crop_p,
        "soil_p_index": soil_p_index,
        "setback_to_well_ft": setback_well,
        "setback_to_surface_water_ft": setback_water,
        "allowed_application_months": months,
        "soil_ph": soil_ph,
        "depth_to_groundwater_ft": depth,
        "slope_pct": slope,
        "nearest_residence_ft": residence,
        "reapplication_interval_days": reapplication,
        "status": "DRAFT",
        "permit_number": None,
        "permitted_at": None,
        "restriction_reason": None,
        "cumulative_loading_kg_per_hectare": {},
        "annual_loading_kg_per_hectare": {},
        "odor_risk_score_historical": r2(0),
        "odor_risk_score_precautionary": r2(0),
        "gating_risk_score": r2(0),
        "pfas_advisory_flag": False,
        "latest_rainfall_in_24h": None,
        "latest_forecast_rainfall_in_48h": None,
        "latest_frozen_ground": None,
        "latest_weather_observed_at": None,
        "weather_clearance_ok": False,
        "updated_at": now_iso(),
        "version": 1,
    })
    store.sites[site["id"]] = site
    return object_response(public(site), 201)


@bp.get("/<site_id>")
@roles(*SITE_READ_ROLES)
def read_site(site_id):
    return object_response(public(get_site(site_id)))


@bp.get("")
@roles(*SITE_READ_ROLES)
def list_sites():
    facility_id = qstr("facility_id")
    status = qenum("status", SITE_STATUSES)
    crop_type = qenum("crop_type", CROP_TYPES)
    rows = [s for s in store.sites.values()
            if (facility_id is None or s["facility_id"] == facility_id)
            and (status is None or s["status"] == status)
            and (crop_type is None or s["crop_type"] == crop_type)]
    return emit_list(rows, ("created_at",))


@bp.post("/<site_id>/submit-permit")
@roles("Agronomist")
def submit_permit(site_id):
    site = get_site(site_id)
    get_body()
    if site["status"] != "DRAFT":
        fail("ERR_SITE_INVALID_STATE", "Only a DRAFT site may be submitted for review.")
    if (D(site["soil_ph"]) < Decimal("6.0")
            or D(site["depth_to_groundwater_ft"]) < Decimal("3.0")
            or D(site["setback_to_well_ft"]) < Decimal(100)
            or D(site["setback_to_surface_water_ft"]) < Decimal(33)
            or not site["allowed_application_months"]):
        fail("ERR_SETBACK_VIOLATION", "The baseline siting screen failed.")
    site["status"] = "UNDER_REVIEW"
    touch(site)
    return object_response(public(site))


@bp.post("/<site_id>/permit-decision")
@roles("ComplianceOfficer")
def permit_decision(site_id):
    site = get_site(site_id)
    body = get_body()
    decision = venum(body, "decision", ("APPROVE", "REJECT"), required=True)
    permit_number = None
    if decision == "APPROVE":
        permit_number = vstr(body, "permit_number", required=True, min_len=1)
    if site["status"] != "UNDER_REVIEW":
        fail("ERR_SITE_INVALID_STATE", "Only a site UNDER_REVIEW may be decided.")
    if decision == "APPROVE":
        site["status"] = "PERMITTED"
        site["permit_number"] = permit_number
        site["permitted_at"] = now_iso()
    else:
        site["status"] = "DRAFT"
        site["permit_number"] = None
    touch(site)
    return object_response(public(site))


@bp.post("/<site_id>/restrict")
@roles("ComplianceOfficer")
def restrict(site_id):
    site = get_site(site_id)
    get_body()
    if site["status"] != "PERMITTED":
        fail("ERR_SITE_INVALID_STATE", "Only a PERMITTED site may be restricted.")
    site["status"] = "RESTRICTED"
    site["restriction_reason"] = "OFFICER_ORDER"
    touch(site)
    defer_pre_field_events(site["id"], "SITE_RESTRICTED")
    return object_response(public(site))


@bp.post("/<site_id>/reinstate")
@roles("ComplianceOfficer")
def reinstate(site_id):
    site = get_site(site_id)
    get_body()
    if site["status"] != "RESTRICTED":
        fail("ERR_SITE_INVALID_STATE", "Only a RESTRICTED site may be reinstated.")
    for analyte, limit in sorted(active_limits().items()):
        cplr = limit.get("cplr_kg_per_hectare")
        if cplr is None:
            continue
        if not cumulative_loading(site, analyte) < Decimal("0.90") * D(cplr):
            fail("ERR_CPLR_HEADROOM_EXCEEDED",
                 "Cumulative loading for %s leaves insufficient headroom." % analyte)
    if not D(site["gating_risk_score"]) < Decimal("60.00"):
        fail("ERR_ODOR_RISK_BLOCK", "gating_risk_score is at or above 60.00.")
    site["status"] = "PERMITTED"
    site["restriction_reason"] = None
    touch(site)
    return object_response(public(site))


@bp.post("/<site_id>/close")
@roles("Agronomist", "ComplianceOfficer")
def close_site(site_id):
    site = get_site(site_id)
    get_body()
    if site["status"] not in ("PERMITTED", "RESTRICTED"):
        fail("ERR_SITE_INVALID_STATE",
             "Only a PERMITTED or RESTRICTED site may be closed.")
    for event in events_of_site(site["id"]):
        if event["status"] in OPEN_EVENT_STATUSES:
            fail("ERR_OPEN_EVENTS_EXIST",
                 "The site still has application events that are not finished.")
    site["status"] = "CLOSED"
    touch(site)
    for agreement in store.agreements.values():
        if agreement["site_id"] != site["id"]:
            continue
        if agreement["status"] in ("DRAFT", "PROPOSED", "COUNTERED"):
            agreement["status"] = "WITHDRAWN"
            touch(agreement)
    return object_response(public(site))


@bp.get("/<site_id>/loading-summary")
@roles("Agronomist", "ComplianceOfficer", "FacilityOperator", "PublicLiaison")
def loading_summary(site_id):
    site = get_site(site_id)
    applied_year = qint("applied_year")
    limits = active_limits()
    cumulative = dict(site["cumulative_loading_kg_per_hectare"])
    annual = dict(site["annual_loading_kg_per_hectare"])
    if applied_year is not None:
        prefix = "%d:" % applied_year
        annual = {k: v for k, v in annual.items() if k.startswith(prefix)}
    year = applied_year if applied_year is not None else now().year

    cplr_headroom = {}
    aplr_headroom = {}
    for analyte in sorted(limits):
        limit = limits[analyte]
        cplr = limit.get("cplr_kg_per_hectare")
        if cplr is not None:
            cplr_headroom[analyte] = D(cplr) - cumulative_loading(site, analyte)
        aplr = limit.get("aplr_kg_per_hectare_yr")
        if aplr is not None:
            aplr_headroom[analyte] = D(aplr) - annual_loading(site, year, analyte)

    binding_analyte = None
    best_fraction = None
    any_loading = any(D(v) != 0 for v in cumulative.values())
    if any_loading:
        for analyte in sorted(limits):
            cplr = limits[analyte].get("cplr_kg_per_hectare")
            if cplr is None or D(cplr) == 0:
                continue
            fraction = (D(cplr) - cumulative_loading(site, analyte)) / D(cplr)
            if best_fraction is None or fraction < best_fraction:
                best_fraction = fraction
                binding_analyte = analyte

    return object_response({
        "site_id": site["id"],
        "cumulative_loading_kg_per_hectare": cumulative,
        "annual_loading_kg_per_hectare": annual,
        "cplr_headroom_kg_per_hectare": cplr_headroom,
        "aplr_headroom_kg_per_hectare": aplr_headroom,
        "binding_analyte": binding_analyte,
        "pfas_advisory_flag": site["pfas_advisory_flag"],
    })
