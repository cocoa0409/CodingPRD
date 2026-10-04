"""ServiceTerritory endpoints plus the territory-scoped growth gates.

Mapping ticks, validation runs, weather-tier ticks and service-area expansion
requests all live here because they are all territory-scoped writes.
"""

from flask import Blueprint, request

from db import store
from errors import fail
from middleware import (
    ANY,
    MAPPING_ENGINEER,
    SAFETY_REVIEWER,
    TERRITORY_PLANNER,
    authenticate,
    authorize,
    body_object,
    get_or_404,
    optional_enum,
    optional_int,
    require_instant,
    require_enum,
    require_int,
    require_str,
)
from response import paginate, success_array, success_object
from services import calculations as calc

bp = Blueprint("territories", __name__)

ROAD_TYPE_RISKS = ("LOW", "MEDIUM", "HIGH")


def _resolve(allowed):
    caller = authenticate(request.headers)
    authorize(caller, allowed)
    return caller


# ─── ServiceTerritory ─────────────────────────────────────────────────────


@bp.post("/fleet/territories")
def create_territory():
    _resolve((TERRITORY_PLANNER,))
    body = body_object(request.get_json(silent=True))
    name = require_str(body, "name")
    region_code = require_str(body, "region_code")
    mapped_pct = optional_int(body, "mapped_pct", 0, minimum=0)
    validation_hours = optional_int(body, "validation_hours", 0, minimum=0)
    road_type_risk = optional_enum(body, "road_type_risk", ROAD_TYPE_RISKS, "MEDIUM")

    territory = {
        "id": store.new_id(),
        "name": name,
        "region_code": region_code,
        "posture": "PENDING",
        "mapped_pct": min(100, mapped_pct),
        "validation_hours": validation_hours,
        "road_type_risk": road_type_risk,
        "active_zone_count": 0,
        "total_credit_cents": 0,
        "total_severe_incidents": 0,
        "version": 1,
    }
    store.stamp_create(territory)
    territory["posture"] = calc.compute_territory_posture(territory)
    store.territories[territory["id"]] = territory
    return success_object(territory, 201)


@bp.get("/fleet/territories")
def list_territories():
    _resolve((ANY,))
    params = request.args
    rows = sorted(store.territories.values(), key=lambda row: (row["created_at"], row["id"]))
    for param, field in (("posture", "posture"), ("region_code", "region_code")):
        raw = params.get(param)
        if raw:
            rows = [row for row in rows if row[field] == raw]
    page, limit, offset, total = paginate(rows, params)
    return success_array(page, limit, offset, total)


@bp.get("/fleet/territories/<territory_id>")
def get_territory(territory_id):
    _resolve((ANY,))
    return success_object(get_or_404(store.territories, territory_id))


# ─── onboarding gates ─────────────────────────────────────────────────────


@bp.post("/fleet/territories/<territory_id>/mapping-ticks")
def mapping_tick(territory_id):
    _resolve((MAPPING_ENGINEER,))
    territory = get_or_404(store.territories, territory_id)
    body = body_object(request.get_json(silent=True))
    delta = require_int(body, "mapped_pct_delta")
    if territory["posture"] != "PENDING":
        raise fail("ERR_INVALID_STATE")
    territory["mapped_pct"] = min(100, territory["mapped_pct"] + delta)
    territory["posture"] = calc.compute_territory_posture(territory)
    store.touch(territory)
    return success_object(territory)


@bp.post("/fleet/territories/<territory_id>/validation-runs")
def validation_run(territory_id):
    _resolve((MAPPING_ENGINEER, SAFETY_REVIEWER))
    territory = get_or_404(store.territories, territory_id)
    body = body_object(request.get_json(silent=True))
    hours = require_int(body, "hours")
    if territory["posture"] not in ("MAPPING", "VALIDATING"):
        raise fail("ERR_INVALID_STATE")
    territory["validation_hours"] = territory["validation_hours"] + hours
    territory["posture"] = calc.compute_territory_posture(territory)
    store.touch(territory)
    return success_object(territory)


@bp.post("/fleet/territories/<territory_id>/weather-tier-ticks")
def weather_tier_tick(territory_id):
    _resolve((SAFETY_REVIEWER,))
    territory = get_or_404(store.territories, territory_id)
    body = body_object(request.get_json(silent=True))
    window_code = require_enum(body, "window_code", calc.WINDOW_CODES)
    tier = require_int(body, "tier", minimum=0)
    store.weather_tiers[(territory_id, window_code)] = tier
    store.touch(territory)
    return success_object(territory)


# ─── ServiceAreaExpansionRequest ──────────────────────────────────────────


@bp.post("/fleet/territories/<territory_id>/expansion-requests")
def create_expansion_request(territory_id):
    _resolve((TERRITORY_PLANNER,))
    territory = get_or_404(store.territories, territory_id)
    body = body_object(request.get_json(silent=True))
    target_region_code = require_str(body, "target_region_code")
    requires_validation = body.get("requires_road_type_validation", False)
    if not isinstance(requires_validation, bool):
        raise fail("ERR_INVALID_REQUEST")
    expected_version = require_int(body, "expected_territory_version")
    if expected_version != territory["version"]:
        raise fail("ERR_STALE_VERSION")

    expansion = {
        "id": store.new_id(),
        "territory_id": territory_id,
        "target_region_code": target_region_code,
        "mapped_pct_at_submit": territory["mapped_pct"],
        "rule_version_at_approval": None,
        "status": "SUBMITTED",
        "requires_road_type_validation": requires_validation,
        "version": 1,
    }
    store.stamp_create(expansion)
    store.expansion_requests[expansion["id"]] = expansion
    store.touch(territory)
    return success_object(expansion, 201)


@bp.get("/fleet/territories/<territory_id>/expansion-requests")
def list_territory_expansions(territory_id):
    _resolve((TERRITORY_PLANNER, SAFETY_REVIEWER, MAPPING_ENGINEER))
    get_or_404(store.territories, territory_id)
    rows = sorted(
        (row for row in store.expansion_requests.values() if row["territory_id"] == territory_id),
        key=lambda row: (row["created_at"], row["id"]),
    )
    status = request.args.get("status")
    if status:
        rows = [row for row in rows if row["status"] == status]
    page, limit, offset, total = paginate(rows, request.args)
    return success_array(page, limit, offset, total)


@bp.get("/fleet/expansion-requests")
def list_expansions():
    _resolve((ANY,))
    rows = sorted(store.expansion_requests.values(), key=lambda row: (row["created_at"], row["id"]))
    territory_id = request.args.get("territory_id")
    if territory_id:
        rows = [row for row in rows if row["territory_id"] == territory_id]
    status = request.args.get("status")
    if status:
        rows = [row for row in rows if row["status"] == status]
    page, limit, offset, total = paginate(rows, request.args)
    return success_array(page, limit, offset, total)


@bp.get("/fleet/expansion-requests/<expansion_id>")
def get_expansion(expansion_id):
    _resolve((TERRITORY_PLANNER, SAFETY_REVIEWER, MAPPING_ENGINEER))
    return success_object(get_or_404(store.expansion_requests, expansion_id))


@bp.post("/fleet/expansion-requests/<expansion_id>/mapping-complete")
def expansion_mapping_complete(expansion_id):
    _resolve((MAPPING_ENGINEER,))
    expansion = get_or_404(store.expansion_requests, expansion_id)
    territory = get_or_404(store.territories, expansion["territory_id"])
    body = body_object(request.get_json(silent=True))
    expected_version = require_int(body, "expected_territory_version")
    if expected_version != territory["version"]:
        raise fail("ERR_STALE_VERSION")
    expansion["status"] = (
        "MAPPING_COMPLETE" if territory["mapped_pct"] >= calc.MAPPED_PCT_GATE else "VALIDATION_FAILED"
    )
    store.touch(expansion)
    store.touch(territory)
    return success_object(expansion)


@bp.post("/fleet/expansion-requests/<expansion_id>/approve")
def approve_expansion(expansion_id):
    _resolve((SAFETY_REVIEWER,))
    expansion = get_or_404(store.expansion_requests, expansion_id)
    territory = get_or_404(store.territories, expansion["territory_id"])
    if expansion["requires_road_type_validation"] and territory["road_type_risk"] == "HIGH":
        expansion["status"] = "CONDITIONALLY_APPROVED"
    else:
        expansion["status"] = "APPROVED"
    versions = [
        rule["rule_version"]
        for rule in store.area_rules.values()
        if rule["territory_id"] == territory["id"] and rule["status"] == "APPROVED"
    ]
    expansion["rule_version_at_approval"] = max(versions) if versions else 0
    store.touch(expansion)
    return success_object(expansion)


@bp.post("/fleet/expansion-requests/<expansion_id>/reject")
def reject_expansion(expansion_id):
    _resolve((SAFETY_REVIEWER,))
    expansion = get_or_404(store.expansion_requests, expansion_id)
    body = body_object(request.get_json(silent=True))
    require_str(body, "reason")
    expansion["status"] = "REJECTED"
    store.touch(expansion)
    return success_object(expansion)