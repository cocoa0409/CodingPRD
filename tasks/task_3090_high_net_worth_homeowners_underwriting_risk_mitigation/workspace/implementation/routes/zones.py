"""Risk-zone and agency reference configuration (PRD §3.4)."""

from flask import Blueprint

import db
import reqs
from clock import fmt_dt, parse_dt
from errors import err
from middleware import authorize
from response import array, ok, paginate
from serialize import render, render_list
from services import core

bp = Blueprint("zones", __name__)

WUI_BANDS = ("WITHIN_WUI", "ADJACENT_WUI", "OUTSIDE_WUI")
EXPOSURE_BANDS = ("STANDARD", "ELEVATED", "EXTREME")
STATE_EVENTS = ("NONE", "WATCH", "ACTIVE")
CONCENTRATION_BANDS = ("NORMAL", "ELEVATED", "CRITICAL")
SERVICING_TIERS = ("PREMIER", "SELECT", "STANDARD")

ZONE_READERS = ("Underwriter", "AgencyProducer", "ClaimsAdjuster", "RiskConsultant",
                "PlatformAdmin", "ComplianceReporter")
ZONE_WRITERS = ("Underwriter",)
AGENCY_READERS = ("Underwriter", "AgencyProducer", "PlatformAdmin", "ComplianceReporter")


def common_fields():
    now = fmt_dt(db.now())
    return {
        "id": db.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }


# --------------------------------------------------------------------------
# risk zones
# --------------------------------------------------------------------------
@bp.route("/hnw/risk-zones", methods=["POST"])
def create_zone():
    authorize(("PlatformAdmin",))
    data = reqs.body()
    zone_code = reqs.string(data, "zone_code", required=True)
    if any(z["zone_code"] == zone_code for z in db.ZONES.values()):
        raise err("ERR_INVALID_REQUEST", "zone_code must be unique across RiskZone.")
    record = common_fields()
    record.update({
        "zone_code": zone_code,
        "state_code": reqs.string(data, "state_code", required=True),
        "wildland_urban_interface_band": reqs.enum(data, "wildland_urban_interface_band", WUI_BANDS),
        "sustained_wind_mph": reqs.integer(data, "sustained_wind_mph", required=True, minimum=0),
        "mitigation_band_multiplier": reqs.number(data, "mitigation_band_multiplier",
                                                  required=True, minimum=0, strict_min=True),
        "mitigated_loss_multiplier": reqs.number(data, "mitigated_loss_multiplier", default=1.0),
        "exposure_band": reqs.enum(data, "exposure_band", EXPOSURE_BANDS),
        "state_event": reqs.enum(data, "state_event", STATE_EVENTS, default="NONE", required=False),
        "concentration_ratio_pct": 0.0,
        "concentration_band": "NORMAL",
        "freeze_active": False,
    })
    db.ZONES[record["id"]] = record
    return ok(render(record), status=201)


@bp.route("/hnw/risk-zones", methods=["GET"])
def list_zones():
    authorize(ZONE_READERS)
    limit, offset = reqs.pagination()
    rows = list(db.ZONES.values())
    zone_code = reqs.query("zone_code")
    state_code = reqs.query("state_code")
    band = reqs.query("concentration_band")
    if zone_code:
        rows = [z for z in rows if z["zone_code"] == zone_code]
    if state_code:
        rows = [z for z in rows if z["state_code"] == state_code]
    if band:
        rows = [z for z in rows if z["concentration_band"] == band]
    rows = reqs.sorted_by_created(rows)
    page, pagination = db_paginate(rows, limit, offset)
    return array(render_list(page), pagination)


@bp.route("/hnw/risk-zones/<zone_id>", methods=["GET"])
def read_zone(zone_id):
    authorize(ZONE_READERS)
    zone = core.get(db.ZONES, zone_id, "RiskZone")
    return ok(render(zone))


@bp.route("/hnw/risk-zones/<zone_id>/check_concentration", methods=["POST"])
def check_concentration(zone_id):
    authorize(("Underwriter",))
    core.get(db.ZONES, zone_id, "RiskZone")
    core.recompute_concentration()
    return ok(render(db.ZONES[zone_id]))


@bp.route("/hnw/risk-zones/<zone_id>/set-event", methods=["POST"])
def set_event(zone_id):
    authorize(("Underwriter",))
    zone = core.get(db.ZONES, zone_id, "RiskZone")
    data = reqs.body()
    zone["state_event"] = reqs.enum(data, "state_event", STATE_EVENTS)
    core.touch(zone)
    core.apply_zone_event(zone)
    return ok(render(zone))


# --------------------------------------------------------------------------
# agencies
# --------------------------------------------------------------------------
@bp.route("/hnw/agencies", methods=["POST"])
def create_agency():
    authorize(("PlatformAdmin",))
    data = reqs.body()
    agency_code = reqs.string(data, "agency_code", required=True)
    if any(a["agency_code"] == agency_code for a in db.AGENCIES.values()):
        raise err("ERR_INVALID_REQUEST", "agency_code must be unique across Agency.")
    record = common_fields()
    record.update({
        "agency_code": agency_code,
        "legal_name": reqs.string(data, "legal_name", required=True),
        "state_code": reqs.string(data, "state_code", required=True),
        "servicing_tier": reqs.enum(data, "servicing_tier", SERVICING_TIERS,
                                    default="STANDARD", required=False),
        "delegated_authority_limit_cents": reqs.integer(
            data, "delegated_authority_limit_cents", required=True, minimum=0),
        "active": reqs.boolean(data, "active", default=True),
        "concentration_ratio_pct": 0.0,
        "concentration_band": "NORMAL",
    })
    db.AGENCIES[record["id"]] = record
    return ok(render(record), status=201)


@bp.route("/hnw/agencies", methods=["GET"])
def list_agencies():
    authorize(AGENCY_READERS)
    limit, offset = reqs.pagination()
    rows = list(db.AGENCIES.values())
    state_code = reqs.query("state_code")
    tier = reqs.query("servicing_tier")
    band = reqs.query("concentration_band")
    if state_code:
        rows = [a for a in rows if a["state_code"] == state_code]
    if tier:
        rows = [a for a in rows if a["servicing_tier"] == tier]
    if band:
        rows = [a for a in rows if a["concentration_band"] == band]
    rows = reqs.sorted_by_created(rows)
    page, pagination = db_paginate(rows, limit, offset)
    return array(render_list(page), pagination)


@bp.route("/hnw/agencies/<agency_id>", methods=["GET"])
def read_agency(agency_id):
    authorize(AGENCY_READERS)
    agency = core.get(db.AGENCIES, agency_id, "Agency")
    return ok(render(agency))


@bp.route("/hnw/agencies/<agency_id>/set-active", methods=["POST"])
def set_active(agency_id):
    authorize(("PlatformAdmin",))
    agency = core.get(db.AGENCIES, agency_id, "Agency")
    data = reqs.body()
    agency["active"] = reqs.boolean(data, "active", required=True)
    core.touch(agency)
    return ok(render(agency))


def db_paginate(rows, limit, offset):
    from response import paginate
    return paginate(rows, limit, offset)