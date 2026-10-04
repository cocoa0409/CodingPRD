"""Storage facility endpoints (create, get, record readings) and the
processing-line creation endpoint."""

import calcs
import domain
from db import store
from errors import ApiError
from flask import Blueprint
from middleware import ANY_ROLES, require_roles
from response import success_object
from util import body_json, req_dt, req_int, req_number, req_str
from constants import CUT_FAMILIES, MAX_RECENT_READINGS

bp = Blueprint("facilities", __name__)


@bp.route("/potato-ops/storage-facilities", methods=["POST"])
@require_roles("PlatformAdmin")
def create_facility():
    body = body_json()
    facility_code = req_str(body, "facility_code")
    capacity = req_int(body, "capacity_cwt")
    if capacity <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "Field 'capacity_cwt': must be > 0", 400)
    target_temp = req_number(body, "target_temp_f")
    target_co2 = req_number(body, "target_co2_pct")
    f = domain.new_entity()
    f.update({
        "facility_code": facility_code,
        "capacity_cwt": capacity,
        "target_temp_f": body["target_temp_f"],
        "target_co2_pct": body["target_co2_pct"],
        "posture": "NORMAL",
        "recent_readings": [],
    })
    store.facilities[f["id"]] = f
    return success_object(domain.facility_view(f), 201)


@bp.route("/potato-ops/storage-facilities/<fid>", methods=["GET"])
@require_roles(*ANY_ROLES)
def get_facility(fid):
    return success_object(domain.facility_view(domain.get_facility_or_404(fid)), 200)


@bp.route("/potato-ops/storage-facilities/<fid>/readings", methods=["POST"])
@require_roles("StorageOperator")
def record_reading(fid):
    body = body_json()
    recorded_at = req_dt(body, "recorded_at")
    req_number(body, "temperature_f")
    req_number(body, "humidity_pct")
    req_number(body, "co2_pct")
    req_number(body, "sprout_index")
    req_number(body, "disease_incidence_pct")
    facility = domain.get_facility_or_404(fid)
    reading = {
        "recorded_at": recorded_at,
        "temperature_f": body["temperature_f"],
        "humidity_pct": body["humidity_pct"],
        "co2_pct": body["co2_pct"],
        "sprout_index": body["sprout_index"],
        "disease_incidence_pct": body["disease_incidence_pct"],
    }
    facility["recent_readings"].append(reading)
    if len(facility["recent_readings"]) > MAX_RECENT_READINGS:
        facility["recent_readings"] = facility["recent_readings"][-MAX_RECENT_READINGS:]
    # Posture derives from the latest reading alone: greatest recorded_at,
    # ties broken in favor of the reading appended last.
    latest = max(
        enumerate(facility["recent_readings"]),
        key=lambda pair: (pair[1]["recorded_at"], pair[0]),
    )[1]
    facility["posture"] = calcs.posture_from_reading(latest)
    domain.touch(facility)
    # PRD section 4 lists "readings" among the modify-an-existing-resource
    # operations returning 200 (this overrides the scaffold table's 201).
    return success_object(domain.facility_view(facility), 200)


@bp.route("/potato-ops/processing-lines", methods=["POST"])
@require_roles("PlatformAdmin")
def create_line():
    body = body_json()
    line_code = req_str(body, "line_code")
    families = body.get("supported_cut_families")
    if (
        not isinstance(families, list)
        or not families
        or any(not isinstance(x, str) or x not in CUT_FAMILIES for x in families)
    ):
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "Field 'supported_cut_families': must be a non-empty array of "
            "STRAIGHT | CRINKLE | WEDGE | SHOESTRING",
            400,
        )
    throughput = req_int(body, "rated_throughput_cases_per_hour")
    if throughput <= 0:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "Field 'rated_throughput_cases_per_hour': must be > 0",
            400,
        )
    line = domain.new_entity()
    line.update({
        "line_code": line_code,
        "supported_cut_families": list(families),
        "rated_throughput_cases_per_hour": throughput,
    })
    store.lines[line["id"]] = line
    return success_object(domain.line_view(line), 201)
