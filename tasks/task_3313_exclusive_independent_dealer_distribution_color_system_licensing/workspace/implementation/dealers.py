"""Dealers and dealer applications."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

import db
import services
from errors import (
    err_not_found, err_invalid_request, err_invalid_state, err_stale_version,
    err_attestation_stale, err_territory_conflict, err_dealer_not_active,
)
from response import (
    body, get_auth, require_roles, require_dealer_principal, success_obj,
    paginate, req_string, req_number, req_bool, req_ts,
)

bp = Blueprint("dealers", __name__)

READ_ALL = ["PlatformAdmin", "RegionManager", "ChannelDirector", "ColorLabAdmin", "EquipmentTech", "DealerPrincipal"]
APP_READ = ["PlatformAdmin", "RegionManager", "ChannelDirector"]


def _serialize_dealer(d):
    return dict(d)


def _serialize_application(a):
    return dict(a)


def _validate_dealer_payload(data):
    region_id = req_string(data, "region_id")
    legal_name = req_string(data, "legal_name")
    latitude = req_number(data, "latitude")
    longitude = req_number(data, "longitude")
    attested_on = req_ts(data, "exclusivity_attested_on")
    branding = req_bool(data, "branding_compliant", False)
    rate = req_number(data, "coop_accrual_rate")
    if rate < 0 or rate > 0.10:
        raise err_invalid_request("coop_accrual_rate must be in [0, 0.10]")
    if region_id not in db.regions:
        raise err_not_found("region_id not found")
    return region_id, legal_name, latitude, longitude, attested_on, branding, rate


def _make_dealer(region_id, legal_name, latitude, longitude, attested_on, branding, rate):
    rec = db.new_common()
    rec.update({
        "region_id": region_id,
        "legal_name": legal_name,
        "latitude": latitude,
        "longitude": longitude,
        "status": "APPLIED",
        "channel_posture": "INDEPENDENT_ONLY",
        "bigbox_share_pct": 0,
        "exclusivity_attested_on": db.fmt_ts(attested_on),
        "branding_compliant": branding,
        "coop_accrual_rate": rate,
        "coop_balance_cents": 0,
        "coop_pending_cents": 0,
        "annual_net_purchase_cents": 0,
        "inventory_minimum_met": False,
    })
    db.dealers[rec["id"]] = rec
    return rec


# ---------------- dealers ----------------

@bp.post("/dealers")
def create_dealer():
    _, role = get_auth()
    require_roles(role, ["PlatformAdmin", "RegionManager"])
    data = body()
    args = _validate_dealer_payload(data)
    rec = _make_dealer(*args)
    return success_obj(_serialize_dealer(rec), 201)


@bp.get("/dealers")
def list_dealers():
    get_auth()
    items = list(db.dealers.values())
    region_id = request.args.get("region_id")
    status = request.args.get("status")
    if region_id is not None:
        items = [d for d in items if d["region_id"] == region_id]
    if status is not None:
        items = [d for d in items if d["status"] == status]
    return paginate([_serialize_dealer(d) for d in items])


@bp.get("/dealers/<did>")
def get_dealer(did):
    get_auth()
    d = db.dealers.get(did)
    if d is None:
        raise err_not_found("dealer not found")
    services.refresh_dealer_channel(d)
    return success_obj(_serialize_dealer(d))


@bp.post("/dealers/<did>/attest")
def attest_dealer(did):
    _, role = get_auth()
    require_roles(role, ["RegionManager"])
    d = db.dealers.get(did)
    if d is None:
        raise err_not_found("dealer not found")
    data = body()
    attested_on = req_ts(data, "exclusivity_attested_on")
    d["exclusivity_attested_on"] = db.fmt_ts(attested_on)
    db.touch(d)
    return success_obj(_serialize_dealer(d))


@bp.post("/dealers/<did>/begin-onboarding")
def begin_onboarding(did):
    _, role = get_auth()
    require_roles(role, ["RegionManager"])
    d = db.dealers.get(did)
    if d is None:
        raise err_not_found("dealer not found")
    if d["status"] != "APPLIED":
        raise err_invalid_state("dealer is not APPLIED")
    d["status"] = "ONBOARDING"
    db.touch(d)
    return success_obj(_serialize_dealer(d))


@bp.post("/dealers/<did>/activate")
def activate_dealer(did):
    _, role = get_auth()
    require_roles(role, ["RegionManager"])
    d = db.dealers.get(did)
    if d is None:
        raise err_not_found("dealer not found")
    if d["status"] != "ONBOARDING":
        raise err_invalid_state("dealer is not ONBOARDING")
    # gates
    services.sweep_equipment([u for u in db.equipment.values() if u["dealer_id"] == did])
    has_calibrated = any(
        u["dealer_id"] == did and u["status"] == "CALIBRATED"
        for u in db.equipment.values()
    )
    if not has_calibrated:
        raise err_dealer_not_active("no CALIBRATED equipment unit")
    services.sweep_licenses([l for l in db.licenses.values() if l["dealer_id"] == did])
    has_active_license = any(
        l["dealer_id"] == did and l["status"] == "ACTIVE"
        for l in db.licenses.values()
    )
    if not has_active_license:
        raise err_dealer_not_active("no ACTIVE license")
    if not d["inventory_minimum_met"]:
        raise err_dealer_not_active("inventory minimum not met")
    d["status"] = "ACTIVE"
    db.touch(d)
    region = db.regions.get(d["region_id"])
    if region is not None:
        region["active_dealer_count"] = region.get("active_dealer_count", 0) + 1
        db.touch(region)
    return success_obj(_serialize_dealer(d))


def _attestation_stale(d):
    att = db.parse_ts(d["exclusivity_attested_on"])
    if att is None:
        return True
    return (db.now() - att) > timedelta(days=db.ATTESTATION_FRESH_DAYS)


@bp.post("/dealers/<did>/suspend")
def suspend_dealer(did):
    _, role = get_auth()
    require_roles(role, ["ChannelDirector"])
    d = db.dealers.get(did)
    if d is None:
        raise err_not_found("dealer not found")
    if d["status"] != "ACTIVE":
        raise err_invalid_state("dealer is not ACTIVE")
    services.refresh_dealer_channel(d)
    services.sweep_equipment([u for u in db.equipment.values() if u["dealer_id"] == did])
    has_overdue = any(
        u["dealer_id"] == did and u["status"] == "CALIBRATION_OVERDUE"
        for u in db.equipment.values()
    )
    cause = (
        d["channel_posture"] == "BLOCKED"
        or has_overdue
        or _attestation_stale(d)
    )
    if not cause:
        raise err_invalid_state("no suspension cause holds")
    d["status"] = "SUSPENDED"
    db.touch(d)
    return success_obj(_serialize_dealer(d))


@bp.post("/dealers/<did>/reinstate")
def reinstate_dealer(did):
    _, role = get_auth()
    require_roles(role, ["ChannelDirector"])
    d = db.dealers.get(did)
    if d is None:
        raise err_not_found("dealer not found")
    if d["status"] != "SUSPENDED":
        raise err_invalid_state("dealer is not SUSPENDED")
    services.refresh_dealer_channel(d)
    services.sweep_equipment([u for u in db.equipment.values() if u["dealer_id"] == did])
    has_overdue = any(
        u["dealer_id"] == did and u["status"] == "CALIBRATION_OVERDUE"
        for u in db.equipment.values()
    )
    if d["channel_posture"] == "BLOCKED":
        raise err_invalid_state("channel posture still BLOCKED")
    if has_overdue:
        raise err_invalid_state("equipment calibration still overdue")
    if _attestation_stale(d):
        raise err_invalid_state("exclusivity attestation stale")
    d["status"] = "ACTIVE"
    db.touch(d)
    return success_obj(_serialize_dealer(d))


@bp.post("/dealers/<did>/terminate")
def terminate_dealer(did):
    _, role = get_auth()
    require_roles(role, ["ChannelDirector"])
    d = db.dealers.get(did)
    if d is None:
        raise err_not_found("dealer not found")
    if d["status"] not in ("ACTIVE", "SUSPENDED"):
        raise err_invalid_state("dealer is not ACTIVE or SUSPENDED")
    services.terminate_dealer_cascade(d)
    d["status"] = "TERMINATED"
    db.touch(d)
    return success_obj(_serialize_dealer(d))


# ---------------- applications ----------------

@bp.post("/applications")
def create_application():
    _, role = get_auth()
    require_roles(role, ["RegionManager"])
    data = body()
    args = _validate_dealer_payload(data)
    region_id, legal_name, latitude, longitude, attested_on, branding, rate = args
    dealer = _make_dealer(*args)
    rec = db.new_common()
    rec.update({
        "region_id": region_id,
        "dealer_id": dealer["id"],
        "latitude": latitude,
        "longitude": longitude,
        "legal_name": legal_name,
        "distance_to_nearest_miles": None,
        "territory_conflict": False,
        "nearest_dealer_id": None,
        "nearest_dealer_notified": False,
        "status": "DRAFT",
    })
    db.applications[rec["id"]] = rec
    return success_obj(_serialize_application(rec), 201)


@bp.get("/applications")
def list_applications():
    _, role = get_auth()
    require_roles(role, APP_READ)
    items = list(db.applications.values())
    region_id = request.args.get("region_id")
    status = request.args.get("status")
    dealer_id = request.args.get("dealer_id")
    nearest = request.args.get("nearest_dealer_id")
    if region_id is not None:
        items = [a for a in items if a["region_id"] == region_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    if dealer_id is not None:
        items = [a for a in items if a["dealer_id"] == dealer_id]
    if nearest is not None:
        items = [a for a in items if a["nearest_dealer_id"] == nearest]
    return paginate([_serialize_application(a) for a in items])


@bp.get("/applications/<aid>")
def get_application(aid):
    _, role = get_auth()
    require_roles(role, APP_READ)
    a = db.applications.get(aid)
    if a is None:
        raise err_not_found("application not found")
    return success_obj(_serialize_application(a))


def _get_application_or_404(aid):
    a = db.applications.get(aid)
    if a is None:
        raise err_not_found("application not found")
    return a


@bp.post("/applications/<aid>/submit")
def submit_application(aid):
    _, role = get_auth()
    require_roles(role, ["RegionManager"])
    a = _get_application_or_404(aid)
    if a["status"] != "DRAFT":
        raise err_invalid_state("application is not DRAFT")
    region = db.regions.get(a["region_id"])
    if region is None:
        raise err_not_found("region not found")
    # territory distance
    candidates = [
        d for d in db.dealers.values()
        if d["region_id"] == a["region_id"]
        and d["status"] in ("ONBOARDING", "ACTIVE", "SUSPENDED")
    ]
    best = None
    best_dist = None
    for d in candidates:
        dist = services.haversine_miles(a["latitude"], a["longitude"], d["latitude"], d["longitude"])
        dist = services.round_half_up_2dp(dist)
        if best is None:
            best, best_dist = d, dist
        else:
            if dist < best_dist or (dist == best_dist and d["created_at"] < best["created_at"]):
                best, best_dist = d, dist
    a["distance_to_nearest_miles"] = best_dist
    a["nearest_dealer_id"] = best["id"] if best else None
    if best_dist is None:
        a["territory_conflict"] = False
    else:
        a["territory_conflict"] = Decimal(str(best_dist)) < Decimal(str(region["territory_radius_miles"]))
    a["status"] = "SUBMITTED"
    db.touch(a)
    region["pending_application_count"] = region.get("pending_application_count", 0) + 1
    db.touch(region)
    return success_obj(_serialize_application(a))


@bp.post("/applications/<aid>/notify-neighbor")
def notify_neighbor(aid):
    _, role = get_auth()
    require_roles(role, ["RegionManager"])
    a = _get_application_or_404(aid)
    if a["status"] != "SUBMITTED":
        raise err_invalid_state("application is not SUBMITTED")
    a["nearest_dealer_notified"] = True
    db.touch(a)
    return success_obj(_serialize_application(a))


@bp.post("/applications/<aid>/approve")
def approve_application(aid):
    _, role = get_auth()
    require_roles(role, ["RegionManager", "ChannelDirector"])
    a = _get_application_or_404(aid)
    data = body()
    # OCC check evaluated BEFORE state preconditions
    if "expected_application_version" in data and data["expected_application_version"] is not None:
        expected = data["expected_application_version"]
        if isinstance(expected, bool) or not isinstance(expected, int):
            raise err_invalid_request("expected_application_version must be an integer")
        if expected != a["version"]:
            raise err_stale_version()
    if a["status"] != "SUBMITTED":
        raise err_invalid_state("application is not SUBMITTED")
    # territory guard (priority 18) before attestation (13)? PRD pins the
    # validation priority table; §3.2 lists attestation first. Priority
    # order in scaffold validations table is normative: attestation (13)
    # fires before territory (18).
    dealer = db.dealers.get(a["dealer_id"])
    if dealer is None:
        raise err_not_found("applicant dealer not found")
    att = db.parse_ts(dealer["exclusivity_attested_on"])
    if att is None or (db.now() - att) > timedelta(days=db.ATTESTATION_FRESH_DAYS):
        raise err_attestation_stale()
    if a["territory_conflict"]:
        if role != "ChannelDirector" or not a["nearest_dealer_notified"]:
            raise err_territory_conflict()
    a["status"] = "APPROVED"
    db.touch(a)
    if dealer["status"] == "APPLIED":
        dealer["status"] = "ONBOARDING"
        db.touch(dealer)
    region = db.regions.get(a["region_id"])
    if region is not None:
        region["pending_application_count"] = max(0, region.get("pending_application_count", 0) - 1)
        db.touch(region)
    return success_obj(_serialize_application(a))


@bp.post("/applications/<aid>/reject")
def reject_application(aid):
    _, role = get_auth()
    require_roles(role, ["RegionManager"])
    a = _get_application_or_404(aid)
    if a["status"] != "SUBMITTED":
        raise err_invalid_state("application is not SUBMITTED")
    a["status"] = "REJECTED"
    db.touch(a)
    dealer = db.dealers.get(a["dealer_id"])
    if dealer is not None and dealer["status"] == "APPLIED":
        dealer["status"] = "TERMINATED"
        db.touch(dealer)
    region = db.regions.get(a["region_id"])
    if region is not None:
        region["pending_application_count"] = max(0, region.get("pending_application_count", 0) - 1)
        db.touch(region)
    return success_obj(_serialize_application(a))


@bp.post("/applications/<aid>/withdraw")
def withdraw_application(aid):
    _, role = get_auth()
    require_roles(role, ["RegionManager"])
    a = _get_application_or_404(aid)
    if a["status"] != "DRAFT":
        raise err_invalid_state("application is not DRAFT")
    a["status"] = "WITHDRAWN"
    db.touch(a)
    return success_obj(_serialize_application(a))
