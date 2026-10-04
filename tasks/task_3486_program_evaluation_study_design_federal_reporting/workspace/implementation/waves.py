"""DataCollectionWave endpoints: create, list (per-study and cross-study),
get, open, close, link."""
import uuid

from flask import Blueprint, request

import store
from clock import now_dt, parse_iso
from errors import raise_err
from serialize import wave_out
from services import (records_of_wave, require_irb_coverage,
                      visit_window_conflict, waves_of_study)
from util import new_entity, ok_list, ok_obj, paginate, sort_created, touch
from validation import (ROLE_DATA_MANAGER, STAFF_ROLES, authenticate,
                        authorize, check_schema, get_json_body)

bp = Blueprint("waves", __name__)


def get_wave_or_404(wave_id):
    wave = store.waves.get(wave_id)
    if wave is None:
        raise_err("ERR_NOT_FOUND", "Wave not found")
    return wave


@bp.post("/evaluation/studies/<study_id>/waves")
def create_wave(study_id):
    _uid, role = authenticate()
    authorize(role, [ROLE_DATA_MANAGER])
    study = store.studies.get(study_id)
    if study is None:
        raise_err("ERR_NOT_FOUND", "Study not found")
    body = get_json_body()
    check_schema(body, {
        "wave_type": ("enum:SURVEY|ADMIN_RECORDS|SITE_VISIT", True),
        "open_at": ("dt", True),
        "close_at": ("dt", True),
        "site_id": ("str", False),
    })
    open_dt = parse_iso(body["open_at"])
    close_dt = parse_iso(body["close_at"])
    if not close_dt > open_dt:
        raise_err("ERR_INVALID_REQUEST", "close_at must be after open_at")
    site_id = body.get("site_id")
    if body["wave_type"] == "SITE_VISIT":
        if site_id is None:
            raise_err("ERR_INVALID_REQUEST",
                      "site_id is required for SITE_VISIT waves")
        site = store.sites.get(site_id)
        if site is None or site["study_id"] != study_id:
            raise_err("ERR_NOT_FOUND", "Site not found within this study")
    elif site_id is not None:
        raise_err("ERR_INVALID_REQUEST",
                  "site_id is forbidden for non-SITE_VISIT waves")
    if study["status"] not in ("RECRUITMENT", "DATA_COLLECTION"):
        raise_err("ERR_STUDY_INVALID_STATE",
                  "Waves may only be planned while the study is in "
                  "RECRUITMENT or DATA_COLLECTION")
    if body["wave_type"] == "SITE_VISIT" and visit_window_conflict(
            study_id, site_id, open_dt, close_dt):
        raise_err("ERR_VISIT_WINDOW_CONFLICT",
                  "SITE_VISIT window overlaps or sits too close to another "
                  "visit at the same site")
    wave = new_entity({
        "study_id": study_id,
        "wave_type": body["wave_type"],
        "site_id": site_id,
        "open_at": open_dt,
        "close_at": close_dt,
        "status": "PLANNED",
    })
    store.waves[wave["id"]] = wave
    return ok_obj(wave_out(wave), 201)


@bp.get("/evaluation/studies/<study_id>/waves")
def list_waves_of_study(study_id):
    _uid, role = authenticate()
    authorize(role, STAFF_ROLES)
    if study_id not in store.studies:
        raise_err("ERR_NOT_FOUND", "Study not found")
    items = sort_created(waves_of_study(study_id))
    page, limit, offset, total = paginate(items)
    return ok_list([wave_out(w) for w in page], limit, offset, total)


@bp.get("/evaluation/waves")
def list_waves_cross_study():
    _uid, role = authenticate()
    authorize(role, STAFF_ROLES)
    items = list(store.waves.values())
    site_id = request.args.get("site_id")
    study_id = request.args.get("study_id")
    wave_type = request.args.get("wave_type")
    status = request.args.get("status")
    if site_id is not None:
        items = [w for w in items if w["site_id"] == site_id]
    if study_id is not None:
        items = [w for w in items if w["study_id"] == study_id]
    if wave_type is not None:
        items = [w for w in items if w["wave_type"] == wave_type]
    if status is not None:
        items = [w for w in items if w["status"] == status]
    items = sort_created(items)
    page, limit, offset, total = paginate(items)
    return ok_list([wave_out(w) for w in page], limit, offset, total)


@bp.get("/evaluation/waves/<wave_id>")
def get_wave(wave_id):
    _uid, role = authenticate()
    authorize(role, STAFF_ROLES)
    return ok_obj(wave_out(get_wave_or_404(wave_id)))


@bp.post("/evaluation/waves/<wave_id>/open")
def open_wave(wave_id):
    _uid, role = authenticate()
    authorize(role, [ROLE_DATA_MANAGER])
    wave = get_wave_or_404(wave_id)
    body = get_json_body()
    check_schema(body, {})
    if wave["status"] not in ("PLANNED", "SUSPENDED"):
        raise_err("ERR_WAVE_INVALID_STATE",
                  "Only a PLANNED or SUSPENDED wave can be opened")
    require_irb_coverage(wave["study_id"])
    now = now_dt()
    if not (wave["open_at"] <= now < wave["close_at"]):
        raise_err("ERR_WAVE_WINDOW_NOT_STARTED",
                  "Current logical time is outside the wave's "
                  "[open_at, close_at) window")
    wave["status"] = "OPEN"
    touch(wave)
    study = store.studies.get(wave["study_id"])
    if study["status"] == "RECRUITMENT":
        study["status"] = "DATA_COLLECTION"
        touch(study)
    return ok_obj(wave_out(wave))


@bp.post("/evaluation/waves/<wave_id>/close")
def close_wave(wave_id):
    _uid, role = authenticate()
    authorize(role, [ROLE_DATA_MANAGER])
    wave = get_wave_or_404(wave_id)
    body = get_json_body()
    check_schema(body, {})
    if wave["status"] != "OPEN":
        raise_err("ERR_WAVE_INVALID_STATE",
                  "Only an OPEN wave can be closed")
    wave["status"] = "CLOSED"
    touch(wave)
    for r in records_of_wave(wave_id):
        if r["status"] == "RECEIVED":
            r["status"] = "VALIDATED"
            touch(r)
    study = store.studies.get(wave["study_id"])
    if study["status"] == "DATA_COLLECTION" and not any(
            w["status"] in ("PLANNED", "OPEN", "SUSPENDED")
            for w in waves_of_study(study["id"])):
        study["status"] = "ANALYSIS"
        touch(study)
    return ok_obj(wave_out(wave))


@bp.post("/evaluation/waves/<wave_id>/link")
def link_wave(wave_id):
    _uid, role = authenticate()
    authorize(role, [ROLE_DATA_MANAGER])
    wave = get_wave_or_404(wave_id)
    body = get_json_body()
    check_schema(body, {})
    if wave["status"] != "CLOSED":
        raise_err("ERR_WAVE_INVALID_STATE",
                  "Only a CLOSED wave can be linked")
    for r in records_of_wave(wave_id):
        if r["status"] == "RECEIVED":
            raise_err("ERR_RECORDS_UNRESOLVED",
                      "A record of this wave is still RECEIVED")
    wave["status"] = "LINKED"
    touch(wave)
    for r in records_of_wave(wave_id):
        if r["status"] == "VALIDATED":
            r["status"] = "LINKED"
            r["linkage_key"] = str(uuid.uuid4())
            touch(r)
    return ok_obj(wave_out(wave))
