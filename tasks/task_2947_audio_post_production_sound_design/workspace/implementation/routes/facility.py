"""Logical clock and facility configuration: platform specs, mix stages, mixers,
voice talent and the sound library (PRD §2.4, §3.1)."""

from flask import Blueprint

import clock
import derive
import middleware
import response
import serialize
import validation as V
from db import db, new_record, newest_first, touch
from errors import ApiError

bp = Blueprint("facility", __name__)


# ------------------------------------------------------------- logical clock
@bp.post("/_clock/set_current_utc")
def set_clock():
    """PRD §2.1: the two clock endpoints are exempt from both header checks."""
    payload = V.body()
    current = V.v_instant(payload, "current_utc", required=True)
    clock.set_now(current)
    return response.object_response({"current_utc": clock.fmt(clock.now())})


@bp.get("/_clock")
def read_clock():
    return response.object_response({"current_utc": clock.fmt(clock.now())})


# ------------------------------------------------------------ platform specs
@bp.post("/platform-specs")
def create_platform_spec():
    middleware.actor("FacilityAdmin")
    payload = V.body()
    record = new_record(versioned=False)
    record.update({
        "platform": V.v_enum(payload, "platform", V.PLATFORMS),
        "spec_label": V.v_string(payload, "spec_label", minlen=1, maxlen=120),
        "target_lufs": V.v_decimal(payload, "target_lufs", minv="-40.00", maxv="0.00"),
        "tolerance_lu": V.v_decimal(payload, "tolerance_lu", minv="0"),
        "true_peak_max_dbtp": V.v_decimal(payload, "true_peak_max_dbtp",
                                          minv="-20.00", maxv="0.00"),
        "channel_layout": V.v_enum(payload, "channel_layout", V.CHANNEL_LAYOUTS),
        "requires_me_stems": V.v_bool(payload, "requires_me_stems",
                                      required=False, default=False),
        "max_remediation_rounds": V.v_int(payload, "max_remediation_rounds",
                                          required=False, minv=0, default=2),
        "qc_turnaround_hours": V.v_int(payload, "qc_turnaround_hours",
                                       required=False, minv=1, default=24),
    })
    db.platform_specs[record["id"]] = record
    return response.object_response(serialize.platform_spec(record), 201)


@bp.get("/platform-specs/<spec_id>")
def read_platform_spec(spec_id):
    middleware.actor("FacilityAdmin", "PostSupervisor", "SoundEditor", "Mixer", "QcOperator")
    record = middleware.path_generic(db.platform_specs, spec_id)
    return response.object_response(serialize.platform_spec(record))


# ---------------------------------------------------------------- mix stages
@bp.post("/mix-stages")
def create_mix_stage():
    middleware.actor("FacilityAdmin")
    payload = V.body()
    room_code = V.v_string(payload, "room_code", minlen=1, maxlen=32)
    if any(s["room_code"] == room_code for s in db.mix_stages.values()):
        V.bad_request("room_code must be unique across all stages.")
    record = new_record()
    record.update({
        "room_code": room_code,
        "display_name": V.v_string(payload, "display_name", minlen=1, maxlen=120),
        "hourly_rate_cents": V.v_int(payload, "hourly_rate_cents", minv=1),
        "supports_remote_review": V.v_bool(payload, "supports_remote_review",
                                           required=False, default=False),
        "changeover_minutes": V.v_int(payload, "changeover_minutes",
                                      required=False, minv=0, default=45),
    })
    db.mix_stages[record["id"]] = record
    return response.object_response(serialize.mix_stage(record), 201)


@bp.get("/mix-stages/<stage_id>")
def read_mix_stage(stage_id):
    middleware.actor("FacilityAdmin", "PostSupervisor", "SoundEditor", "Mixer", "QcOperator")
    record = middleware.path_generic(db.mix_stages, stage_id)
    return response.object_response(serialize.mix_stage(record))


# -------------------------------------------------------------------- mixers
@bp.post("/mixers")
def create_mixer():
    middleware.actor("FacilityAdmin")
    payload = V.body()
    record = new_record()
    record.update({
        "full_name": V.v_string(payload, "full_name", minlen=1, maxlen=120),
        "certified_platforms": V.v_str_array(payload, "certified_platforms",
                                             V.PLATFORMS, min_items=1),
        "max_daily_hours": V.v_decimal(payload, "max_daily_hours", required=False,
                                       minv="0.01", default=None),
    })
    if record["max_daily_hours"] is None:
        record["max_daily_hours"] = V.Decimal("10.00")
    db.mixers[record["id"]] = record
    return response.object_response(serialize.mixer(record), 201)


@bp.get("/mixers/<mixer_id>")
def read_mixer(mixer_id):
    middleware.actor("FacilityAdmin", "PostSupervisor", "SoundEditor", "Mixer", "QcOperator")
    record = middleware.path_generic(db.mixers, mixer_id)
    return response.object_response(serialize.mixer(record))


# ------------------------------------------------------------- voice talents
@bp.post("/voice-talents")
def create_voice_talent():
    middleware.actor("FacilityAdmin")
    payload = V.body()
    record = new_record()
    record.update({
        "full_name": V.v_string(payload, "full_name", minlen=1, maxlen=120),
        "union_status": V.v_enum(payload, "union_status", V.UNION_STATUSES),
        "daily_cap_minutes": V.v_int(payload, "daily_cap_minutes", required=False,
                                     minv=1, default=240),
        "min_call_minutes": V.v_int(payload, "min_call_minutes", required=False,
                                    minv=1, default=60),
    })
    db.voice_talents[record["id"]] = record
    return response.object_response(serialize.voice_talent(record), 201)


@bp.get("/voice-talents/<talent_id>")
def read_voice_talent(talent_id):
    middleware.actor("FacilityAdmin", "PostSupervisor", "SoundEditor", "QcOperator")
    record = middleware.path_generic(db.voice_talents, talent_id)
    return response.object_response(serialize.voice_talent(record))


# ------------------------------------------------------------ library assets
@bp.post("/library-assets")
def create_library_asset():
    middleware.actor("FacilityAdmin")
    payload = V.body()
    asset_code = V.v_string(payload, "asset_code", minlen=1, maxlen=64)
    if any(a["asset_code"] == asset_code for a in db.library_assets.values()):
        V.bad_request("asset_code must be unique across the library.")
    record = new_record()
    record.update({
        "asset_code": asset_code,
        "kind": V.v_enum(payload, "kind", V.ASSET_KINDS),
        "license_type": V.v_enum(payload, "license_type", V.LICENSE_TYPES),
        "territory_scope": V.v_enum(payload, "territory_scope", V.TERRITORIES),
        "fee_cents": V.v_int(payload, "fee_cents", minv=0),
        "expires_at_utc": V.v_instant(payload, "expires_at_utc", required=False,
                                      default=None),
        "status": "ACTIVE",
        "revocation_reason": None,
    })
    db.library_assets[record["id"]] = record
    return response.object_response(serialize.library_asset(record), 201)


@bp.get("/library-assets/<asset_id>")
def read_library_asset(asset_id):
    middleware.actor("FacilityAdmin", "PostSupervisor", "SoundEditor", "QcOperator")
    record = middleware.path_library_asset(asset_id)
    return response.object_response(serialize.library_asset(record))


@bp.get("/library-assets")
def list_library_assets():
    middleware.actor("FacilityAdmin", "PostSupervisor", "SoundEditor", "QcOperator")
    limit, offset = V.pagination()
    status = V.query_filter("status")
    license_type = V.query_filter("license_type")
    records = list(db.library_assets.values())
    if status is not None:
        records = [r for r in records if r["status"] == status]
    if license_type is not None:
        records = [r for r in records if r["license_type"] == license_type]
    records = newest_first(records)
    window, total = response.paginate(records, limit, offset)
    return response.list_response([serialize.library_asset(r) for r in window],
                                  limit, offset, total)


@bp.post("/library-assets/<asset_id>/revoke")
def revoke_library_asset(asset_id):
    """PRD §3.4 revocation cascade: usages lose their clearance, conformed packages
    go stale, and R-STALE hops B and C follow."""
    middleware.actor("FacilityAdmin")
    asset = middleware.path_library_asset(asset_id)
    payload = V.body()
    reason = V.v_string(payload, "revocation_reason", minlen=1)
    if asset["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE")

    asset["status"] = "REVOKED"
    asset["revocation_reason"] = reason
    touch(asset)

    affected = set()
    stale_candidates = []
    for usage in sorted(db.asset_usages.values(), key=lambda r: (r["created_at"], r["_seq"])):
        if usage["library_asset_id"] != asset["id"]:
            continue
        if usage["clearance_status"] != "CLEARED":
            continue
        usage["clearance_status"] = "UNLICENSED"
        usage["accrued_fee_cents"] = 0
        usage["unlicensed_reason"] = "ASSET_REVOKED"
        usage["cleared_at_utc"] = None
        touch(usage)
        package = db.stem_packages.get(usage["stem_package_id"])
        if package is not None:
            affected.add(package["project_id"])
            if package["status"] == "CONFORMED" and package["id"] not in stale_candidates:
                stale_candidates.append(package["id"])

    for package_id in stale_candidates:
        derive.mark_stem_package_stale(db.stem_packages[package_id],
                                      "LICENSE_REVOKED", affected)

    for project_id in affected:
        project = db.projects.get(project_id)
        if project is None:
            continue
        derive.recompute_project(project)
        derive.recompute_license_scores(project)
        derive.recompute_project(project)
        derive.touch_project(project)

    return response.object_response(serialize.library_asset(asset))
