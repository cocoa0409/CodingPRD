"""Printer setup, material batch, and weather observation routes."""
from flask import Blueprint, request

from db import store, now, fmt_dt, stamp_created, touch, parse_dt
from errors import (
    raise_err,
    ERR_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_INVALID_REQUEST,
    ERR_STALE_VERSION,
    ERR_LEVELING_OUT_OF_TOLERANCE,
    ERR_FOUNDATION_NOT_CURED,
    ERR_BATCH_NOT_PUMPABLE,
)
from middleware import require_roles, parse_pagination
from validate import body_dict, req_enum, req_int, req_num, req_dt
from response import success_object, success_list
import services

bp = Blueprint("equipment", __name__)

GANTRY_MODELS = {"VULCAN_II", "VULCAN_III", "PHOENIX"}
MIX_CODES = {"LAVACRETE_A", "LAVACRETE_B", "LAVACRETE_C"}


def _site_or_404(site_id):
    site = store.sites.get(site_id)
    if site is None:
        raise_err(ERR_NOT_FOUND, "site not found")
    services.lazy_eval_site(site)
    return site


def _check_site_version(site, body):
    expected = body.get("expected_site_version")
    if expected is None:
        raise_err(ERR_INVALID_REQUEST, "expected_site_version is required")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise_err(ERR_INVALID_REQUEST, "expected_site_version must be an integer")
    if expected != site["version"]:
        raise_err(ERR_STALE_VERSION, "expected_site_version does not match site version")


# --- Printer setups ---

@bp.post("/construction/sites/<site_id>/printer-setups")
def create_printer_setup(site_id):
    require_roles("PrintOperator")
    site = _site_or_404(site_id)
    body = body_dict(request.get_json(silent=True))
    _check_site_version(site, body)
    setup = stamp_created({
        "site_id": site_id,
        "gantry_model": req_enum(body, "gantry_model", GANTRY_MODELS),
        "rail_span_mm": req_int(body, "rail_span_mm", minimum=5000),
        "leveling_tolerance_mm": req_num(body, "leveling_tolerance_mm", gt=0),
        "measured_level_deviation_mm": req_num(body, "measured_level_deviation_mm"),
        "is_within_tolerance": False,
        "status": "ASSEMBLED",
    })
    setup["is_within_tolerance"] = (
        setup["measured_level_deviation_mm"] <= setup["leveling_tolerance_mm"]
    )
    store.printer_setups[setup["id"]] = setup
    touch(site)
    return success_object(setup, status=201)


@bp.get("/construction/sites/<site_id>/printer-setups")
def list_printer_setups(site_id):
    require_roles("PlatformAdmin", "SiteManager", "PrintOperator")
    _site_or_404(site_id)
    limit, offset = parse_pagination()
    setups = [s for s in store.printer_setups.values() if s["site_id"] == site_id]
    status_filter = request.args.get("status")
    if status_filter:
        setups = [s for s in setups if s["status"] == status_filter]
    setups.sort(key=lambda s: s["created_at"])
    total = len(setups)
    return success_list(setups[offset:offset + limit], limit, offset, total)


@bp.post("/construction/sites/<site_id>/printer-setups/<setup_id>/advance")
def advance_setup(site_id, setup_id):
    require_roles("PrintOperator")
    site = _site_or_404(site_id)
    setup = store.printer_setups.get(setup_id)
    if setup is None or setup["site_id"] != site_id:
        raise_err(ERR_NOT_FOUND, "printer setup not found")
    body = body_dict(request.get_json(silent=True))
    to_state = body.get("to_state")
    if to_state == "LEVELED":
        if setup["status"] != "ASSEMBLED":
            raise_err(ERR_INVALID_STATE, "setup must be ASSEMBLED to advance to LEVELED")
        if site["status"] not in ("FOUNDATION_POURED", "FOUNDATION_CURED", "SITE_READY"):
            raise_err(ERR_INVALID_STATE, "site status does not allow leveling")
        setup["is_within_tolerance"] = (
            setup["measured_level_deviation_mm"] <= setup["leveling_tolerance_mm"]
        )
        setup["status"] = "LEVELED"
        touch(setup)
        touch(site)
        return success_object(setup)
    if to_state == "QUALIFIED":
        if setup["status"] != "LEVELED":
            raise_err(ERR_INVALID_STATE, "setup must be LEVELED to advance to QUALIFIED")
        if not setup["is_within_tolerance"]:
            raise_err(ERR_LEVELING_OUT_OF_TOLERANCE, "measured deviation exceeds tolerance")
        if site["status"] not in ("FOUNDATION_CURED", "SITE_READY"):
            raise_err(ERR_FOUNDATION_NOT_CURED, "foundation cure not confirmed")
        setup["status"] = "QUALIFIED"
        touch(setup)
        if site["status"] == "FOUNDATION_CURED":
            site["status"] = "SITE_READY"
        touch(site)
        services.recompute_posture(site_id)
        return success_object(setup)
    raise_err(ERR_INVALID_REQUEST, "to_state must be LEVELED or QUALIFIED")


@bp.post("/construction/sites/<site_id>/printer-setups/<setup_id>/demobilize")
def demobilize_setup(site_id, setup_id):
    require_roles("PrintOperator")
    _site_or_404(site_id)
    setup = store.printer_setups.get(setup_id)
    if setup is None or setup["site_id"] != site_id:
        raise_err(ERR_NOT_FOUND, "printer setup not found")
    if setup["status"] not in ("ASSEMBLED", "LEVELED", "QUALIFIED"):
        raise_err(ERR_INVALID_STATE, "setup cannot be demobilized from %s" % setup["status"])
    if setup["status"] == "QUALIFIED":
        for j in store.print_jobs.values():
            if j["printer_setup_id"] == setup_id and j["status"] in (
                "SCHEDULED", "READY_TO_PRINT", "PRINTING", "PAUSED"
            ):
                raise_err(ERR_INVALID_STATE, "setup referenced by an active print job")
    setup["status"] = "DEMOBILIZED"
    touch(setup)
    return success_object(setup)


# --- Material batches ---

@bp.post("/construction/sites/<site_id>/material-batches")
def create_batch(site_id):
    require_roles("PrintOperator")
    _site_or_404(site_id)
    body = body_dict(request.get_json(silent=True))
    wc = req_num(body, "water_cement_ratio")
    if not (0.30 <= wc <= 0.60):
        raise_err(ERR_INVALID_REQUEST, "water_cement_ratio must be between 0.30 and 0.60")
    batch = stamp_created({
        "site_id": site_id,
        "mix_code": req_enum(body, "mix_code", MIX_CODES),
        "water_cement_ratio": wc,
        "target_slump_mm": req_int(body, "target_slump_mm", minimum=50),
        "measured_slump_mm": req_int(body, "measured_slump_mm"),
        "slump_within_band": False,
        "pump_consistency_kg_per_min": req_num(body, "pump_consistency_kg_per_min"),
        "pump_window_kg_per_min": [0, 0],
        "is_pumpable": False,
        "status": "PROPORTIONED",
    })
    services.batch_derived(batch)
    store.batches[batch["id"]] = batch
    return success_object(batch, status=201)


@bp.get("/construction/sites/<site_id>/material-batches")
def list_batches(site_id):
    require_roles("PlatformAdmin", "SiteManager", "PrintOperator")
    _site_or_404(site_id)
    limit, offset = parse_pagination()
    batches = [b for b in store.batches.values() if b["site_id"] == site_id]
    status_filter = request.args.get("status")
    if status_filter:
        batches = [b for b in batches if b["status"] == status_filter]
    batches.sort(key=lambda b: b["created_at"])
    total = len(batches)
    return success_list(batches[offset:offset + limit], limit, offset, total)


@bp.post("/construction/sites/<site_id>/material-batches/<batch_id>/qualify")
def qualify_batch(site_id, batch_id):
    require_roles("PrintOperator")
    site = _site_or_404(site_id)
    batch = store.batches.get(batch_id)
    if batch is None or batch["site_id"] != site_id:
        raise_err(ERR_NOT_FOUND, "material batch not found")
    if batch["status"] != "PROPORTIONED":
        raise_err(ERR_INVALID_STATE, "batch must be PROPORTIONED to qualify")
    if not batch["is_pumpable"]:
        raise_err(ERR_BATCH_NOT_PUMPABLE, "batch is not pumpable")
    if site["status"] not in ("FOUNDATION_CURED", "SITE_READY", "ACTIVE_PRINT"):
        raise_err(ERR_INVALID_STATE, "site status does not allow batch qualification")
    batch["status"] = "QUALIFIED"
    touch(batch)
    return success_object(batch)


@bp.post("/construction/sites/<site_id>/material-batches/<batch_id>/reject")
def reject_batch(site_id, batch_id):
    require_roles("PrintOperator")
    _site_or_404(site_id)
    batch = store.batches.get(batch_id)
    if batch is None or batch["site_id"] != site_id:
        raise_err(ERR_NOT_FOUND, "material batch not found")
    if batch["status"] not in ("PROPORTIONED", "QUALIFIED"):
        raise_err(ERR_INVALID_STATE, "batch cannot be rejected from %s" % batch["status"])
    if batch["status"] == "QUALIFIED":
        for j in store.print_jobs.values():
            if j["site_id"] == site_id and j["status"] in ("PRINTING", "PAUSED"):
                if j.get("consumed_batch_id") == batch_id:
                    raise_err(ERR_INVALID_STATE, "batch is being consumed by an active print job")
    batch["status"] = "REJECTED"
    touch(batch)
    return success_object(batch)


# --- Weather observations ---

@bp.post("/construction/sites/<site_id>/weather-observations")
def create_weather(site_id):
    require_roles("PrintOperator", "QualityInspector")
    _site_or_404(site_id)
    body = body_dict(request.get_json(silent=True))
    obs = stamp_created({
        "site_id": site_id,
        "observed_at": fmt_dt(req_dt(body, "observed_at")),
        "air_temp_c": req_num(body, "air_temp_c"),
        "relative_humidity_pct": req_num(body, "relative_humidity_pct"),
        "wind_speed_mps": req_num(body, "wind_speed_mps"),
        "precipitation_mm": req_num(body, "precipitation_mm", minimum=0),
        "is_print_permissible": False,
    })
    if not (0 <= obs["relative_humidity_pct"] <= 100):
        raise_err(ERR_INVALID_REQUEST, "relative_humidity_pct must be 0..100")
    services.weather_derived(obs)
    store.weather[obs["id"]] = obs
    services.recompute_posture(site_id)
    return success_object(obs, status=201)


@bp.get("/construction/sites/<site_id>/weather-observations")
def list_weather(site_id):
    require_roles("PlatformAdmin", "SiteManager", "PrintOperator", "QualityInspector")
    _site_or_404(site_id)
    limit, offset = parse_pagination()
    obs = [o for o in store.weather.values() if o["site_id"] == site_id]
    # newest first by observed_at
    obs.sort(key=lambda o: (-parse_dt(o["observed_at"]).timestamp(), o["created_at"]))
    total = len(obs)
    return success_list(obs[offset:offset + limit], limit, offset, total)
