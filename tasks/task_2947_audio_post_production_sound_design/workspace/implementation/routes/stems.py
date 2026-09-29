"""Stem packages, music cues, conform and asset usages (PRD §3.3, §3.4)."""

from decimal import Decimal

from flask import Blueprint

import calc
import clock
import derive
import middleware
import response
import serialize
import validation as V
from db import db, new_record, newest_first, oldest_first, touch
from errors import ApiError

bp = Blueprint("stems", __name__)


# ------------------------------------------------------------- stem packages
@bp.post("/stem-packages")
def create_stem_package():
    middleware.actor("SoundEditor", "PostSupervisor")
    payload = V.body()
    project = middleware.body_ref(payload, "project_id", db.projects)
    V.v_string(payload, "project_id", minlen=1)
    reel_label = V.v_string(payload, "reel_label", minlen=1, maxlen=32)
    stem_layout = V.v_enum(payload, "stem_layout", V.STEM_LAYOUTS)
    includes_me_stems = V.v_bool(payload, "includes_me_stems", required=False,
                                 default=False)
    if any(p["project_id"] == project["id"] and p["reel_label"] == reel_label
           for p in db.stem_packages.values()):
        V.bad_request("reel_label must be unique within the project.")
    middleware.gate_archived(project)

    record = new_record()
    record.update({
        "project_id": project["id"],
        "reel_label": reel_label,
        "stem_layout": stem_layout,
        "includes_me_stems": includes_me_stems,
        "status": "DRAFT",
        "conform_round": 0,
        "cue_count": 0,
        "total_stem_minutes": Decimal("0.00"),
        "conform_fee_cents": 0,
        "conformed_at_utc": None,
        "stale_reason": None,
    })
    db.stem_packages[record["id"]] = record
    return response.object_response(serialize.stem_package(record), 201)


@bp.get("/stem-packages/<package_id>")
def read_stem_package(package_id):
    middleware.actor("FacilityAdmin", "PostSupervisor", "SoundEditor", "Mixer", "QcOperator")
    record = middleware.path_stem_package(package_id)
    return response.object_response(serialize.stem_package(record))


@bp.get("/stem-packages")
def list_stem_packages():
    middleware.actor("FacilityAdmin", "PostSupervisor", "SoundEditor", "Mixer", "QcOperator")
    limit, offset = V.pagination()
    project_id = V.query_filter("project_id")
    status = V.query_filter("status")
    records = list(db.stem_packages.values())
    if project_id is not None:
        records = [r for r in records if r["project_id"] == project_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    records = newest_first(records)
    window, total = response.paginate(records, limit, offset)
    return response.list_response([serialize.stem_package(r) for r in window],
                                  limit, offset, total)


# ----------------------------------------------------------------- music cues
@bp.post("/stem-packages/<package_id>/music-cues")
def create_music_cue(package_id):
    """PRD §3.3.  Cue creation always bumps the package version by exactly one;
    a cue landing on a CONFORMED package invalidates the conform."""
    middleware.actor("SoundEditor")
    package = middleware.path_stem_package(package_id)
    payload = V.body()
    expected = V.v_int(payload, "expected_stem_package_version")
    cue_number = V.v_string(payload, "cue_number", minlen=1, maxlen=32)
    duration_seconds = V.v_int(payload, "duration_seconds", minv=1)
    source = V.v_enum(payload, "source", V.CUE_SOURCES)
    composer_delivery_ref = V.v_string(payload, "composer_delivery_ref",
                                       required=False, minlen=0, maxlen=200)
    if expected != package["version"]:
        raise ApiError("ERR_STALE_STEM_PACKAGE_VERSION")
    project = db.projects.get(package["project_id"])
    middleware.gate_posture(project, "music_cue_create")
    middleware.gate_archived(project)

    record = new_record()
    record.update({
        "stem_package_id": package["id"],
        "cue_number": cue_number,
        "duration_seconds": duration_seconds,
        "source": source,
        "composer_delivery_ref": composer_delivery_ref,
        "status": "ACTIVE",
    })
    db.music_cues[record["id"]] = record

    for existing in oldest_first(derive.cues_of(package["id"])):
        if existing["id"] == record["id"]:
            continue
        if existing["status"] == "ACTIVE" and existing["cue_number"] == cue_number:
            existing["status"] = "SUPERSEDED"
            touch(existing)

    went_stale = package["status"] == "CONFORMED"
    if went_stale:
        package["status"] = "STALE"
        package["stale_reason"] = "CUE_REVISED"
    touch(package)

    if went_stale:
        affected = set()
        derive.cascade_from_stale_package(package, affected)
        affected.discard(project["id"])
        for other_id in affected:
            other = db.projects.get(other_id)
            if other is not None:
                derive.recompute_project(other)
                derive.touch_project(other)
        derive.recompute_project(project)
        derive.touch_project(project)

    return response.object_response(serialize.music_cue(record), 201)


@bp.get("/stem-packages/<package_id>/music-cues")
def list_music_cues(package_id):
    middleware.actor("FacilityAdmin", "PostSupervisor", "SoundEditor", "Mixer", "QcOperator")
    package = middleware.path_stem_package(package_id)
    limit, offset = V.pagination()
    status = V.query_filter("status")
    records = derive.cues_of(package["id"])
    if status is not None:
        records = [r for r in records if r["status"] == status]
    # PRD §2.3: cues are ordered by cue_number ASC then created_at ASC.
    records = sorted(records, key=lambda r: (r["cue_number"], r["created_at"], r["_seq"]))
    window, total = response.paginate(records, limit, offset)
    return response.list_response([serialize.music_cue(r) for r in window],
                                  limit, offset, total)


# --------------------------------------------------------------------- conform
@bp.post("/stem-packages/<package_id>/conform")
def conform_stem_package(package_id):
    """PRD §3.3: DRAFT|STALE -> CONFORMED, pinning the conform totals."""
    middleware.actor("SoundEditor")
    package = middleware.path_stem_package(package_id)
    project = db.projects.get(package["project_id"])
    middleware.gate_posture(project, "conform")
    middleware.gate_archived(project)
    if package["status"] not in ("DRAFT", "STALE"):
        raise ApiError("ERR_INVALID_STATE")
    active = [c for c in derive.cues_of(package["id"]) if c["status"] == "ACTIVE"]
    if len(active) < 1:
        raise ApiError("ERR_EMPTY_STEM_SET")

    durations = [c["duration_seconds"] for c in oldest_first(active)]
    total_minutes, fee = calc.stem_conform_totals(durations)
    package["cue_count"] = len(active)
    package["total_stem_minutes"] = total_minutes
    package["conform_fee_cents"] = fee
    package["status"] = "CONFORMED"
    package["conform_round"] = package["conform_round"] + 1
    package["conformed_at_utc"] = clock.now()
    package["stale_reason"] = None
    touch(package)

    before = project["conformed_stem_count"]
    derive.recompute_project(project)
    if before == 0 and project["conformed_stem_count"] >= 1:
        derive.advance_pipeline(project, "EDITORIAL", "PREMIX")
    derive.recompute_project(project)
    derive.touch_project(project)
    return response.object_response(serialize.stem_package(package))


# ---------------------------------------------------------------- asset usages
@bp.post("/asset-usages")
def create_asset_usage():
    """PRD §3.4 clearance evaluation and licence accrual."""
    middleware.actor("SoundEditor")
    payload = V.body()
    asset = middleware.body_ref(payload, "library_asset_id", db.library_assets)
    package = middleware.body_ref(payload, "stem_package_id", db.stem_packages)
    V.v_string(payload, "library_asset_id", minlen=1)
    V.v_string(payload, "stem_package_id", minlen=1)
    usage_seconds = V.v_int(payload, "usage_seconds", minv=1)
    territory_declared = V.v_enum(payload, "territory_declared", V.TERRITORIES)
    project = db.projects.get(package["project_id"])
    middleware.gate_archived(project)

    now = clock.now()
    expires = asset["expires_at_utc"]
    territory_ok = (asset["territory_scope"] == "WORLDWIDE"
                    or asset["territory_scope"] == territory_declared)
    cleared = (asset["status"] == "ACTIVE"
               and (expires is None or expires > now)
               and territory_ok)

    record = new_record()
    record.update({
        "library_asset_id": asset["id"],
        "stem_package_id": package["id"],
        "usage_seconds": usage_seconds,
        "territory_declared": territory_declared,
    })
    if cleared:
        record.update({
            "clearance_status": "CLEARED",
            "cleared_at_utc": now,
            "unlicensed_reason": None,
            "accrued_fee_cents": calc.accrued_fee(asset["license_type"],
                                                  asset["fee_cents"], usage_seconds),
        })
    else:
        if asset["status"] == "REVOKED":
            reason = "ASSET_REVOKED"
        elif expires is not None and expires <= now:
            reason = "ASSET_EXPIRED"
        else:
            reason = "TERRITORY_OUT_OF_SCOPE"
        record.update({
            "clearance_status": "UNLICENSED",
            "cleared_at_utc": None,
            "unlicensed_reason": reason,
            "accrued_fee_cents": 0,
        })
    db.asset_usages[record["id"]] = record

    derive.recompute_project(project)
    derive.recompute_license_scores(project)
    derive.recompute_project(project)
    derive.touch_project(project)
    return response.object_response(serialize.asset_usage(record), 201)


@bp.get("/asset-usages/<usage_id>")
def read_asset_usage(usage_id):
    middleware.actor("FacilityAdmin", "PostSupervisor", "SoundEditor", "QcOperator")
    record = middleware.path_generic(db.asset_usages, usage_id)
    return response.object_response(serialize.asset_usage(record))


@bp.get("/asset-usages")
def list_asset_usages():
    middleware.actor("FacilityAdmin", "PostSupervisor", "SoundEditor", "QcOperator")
    limit, offset = V.pagination()
    library_asset_id = V.query_filter("library_asset_id")
    stem_package_id = V.query_filter("stem_package_id")
    clearance_status = V.query_filter("clearance_status")
    records = list(db.asset_usages.values())
    if library_asset_id is not None:
        records = [r for r in records if r["library_asset_id"] == library_asset_id]
    if stem_package_id is not None:
        records = [r for r in records if r["stem_package_id"] == stem_package_id]
    if clearance_status is not None:
        records = [r for r in records if r["clearance_status"] == clearance_status]
    records = newest_first(records)
    window, total = response.paginate(records, limit, offset)
    return response.list_response([serialize.asset_usage(r) for r in window],
                                  limit, offset, total)
