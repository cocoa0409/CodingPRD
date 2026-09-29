"""The device matrix, encoding ladders and the five-hop lock cascade (PRD 3.3, 3.4)."""

from flask import Blueprint

from db import db, new_row, q2, rows, sort_rows, touch
from errors import ApiError
from middleware import endpoint
from response import created, ok, read_page_params
from routes.common import (
    CODEC_FAMILIES, DEVICE_CLASSES, LADDER_STATES, PROFILE_STATES,
    REQUIRED_DRM_SYSTEMS, apply_filters, get_ladder, get_title, send_list,
)
from services import calc
from services.domain import (
    build_ladder, derive_packaging, recompute_locked_count, recompute_readiness,
    supersede_ladder,
)
from validation import S, parse_body, parse_query

bp = Blueprint("ladders", __name__)

PROFILE_CREATE = [
    S("device_class", "enum", values=DEVICE_CLASSES),
    S("max_height_px", "integer", minimum=240, maximum=2160),
    S("supported_codecs", "array", min_items=1, max_items=3, unique=True,
      item=S("supported_codecs[]", "enum", values=CODEC_FAMILIES)),
    S("min_bitrate_kbps", "integer", minimum=200, maximum=40000),
    S("max_bitrate_kbps", "integer", minimum=200, maximum=40000),
    S("hdcp_required", "boolean", required=False, default=False),
    S("required_drm_system", "enum", required=False, default="NONE",
      values=REQUIRED_DRM_SYSTEMS),
    S("market_share_pct", "number", minimum=0, maximum=100, scale=2),
    S("quality_normalization_factor", "number", minimum="0.50", maximum="1.00", scale=2),
    S("state", "enum", required=False, default="ACTIVE", values=PROFILE_STATES),
]

LADDER_CREATE = [
    S("title_id", "string"),
    S("codec_family", "enum", values=CODEC_FAMILIES),
    S("rungs", "rungs"),
    S("expected_title_version", "integer", minimum=1),
    S("derived_from_ladder_id", "string", required=False, default=None, nullable=True),
]


@bp.post("/device-profiles")
@endpoint(["PlatformAdmin"])
def create_profile():
    payload = parse_body(PROFILE_CREATE)
    if payload["max_bitrate_kbps"] < payload["min_bitrate_kbps"]:
        raise ApiError("ERR_INVALID_REQUEST", "max_bitrate_kbps must be at or above min_bitrate_kbps")
    for existing in rows(db.device_profiles):
        if existing["device_class"] == payload["device_class"]:
            raise ApiError("ERR_DUPLICATE_DEVICE_CLASS")
    profile = new_row()
    profile["device_class"] = payload["device_class"]
    profile["max_height_px"] = payload["max_height_px"]
    profile["supported_codecs"] = payload["supported_codecs"]
    profile["min_bitrate_kbps"] = payload["min_bitrate_kbps"]
    profile["max_bitrate_kbps"] = payload["max_bitrate_kbps"]
    profile["hdcp_required"] = payload["hdcp_required"]
    profile["required_drm_system"] = payload["required_drm_system"]
    profile["market_share_pct"] = q2(payload["market_share_pct"])
    profile["quality_normalization_factor"] = q2(payload["quality_normalization_factor"])
    profile["state"] = payload["state"]
    db.device_profiles[profile["id"]] = profile
    return created(profile)


@bp.get("/device-profiles")
@endpoint(["PlatformAdmin", "EncodingEngineer", "DrmOperator", "DeliveryEngineer"])
def list_profiles():
    filters = parse_query([
        S("state", "enum", values=PROFILE_STATES),
        S("device_class", "enum", values=DEVICE_CLASSES),
    ])
    page, page_size = read_page_params()
    items = apply_filters(rows(db.device_profiles), filters, {})
    return send_list(sort_rows(items, [(lambda r: r["created_at"], False)]), page, page_size)


@bp.post("/encoding-ladders")
@endpoint(["EncodingEngineer"])
def create_ladder():
    payload = parse_body(LADDER_CREATE)
    title = get_title(payload["title_id"])
    ancestor_id = payload.get("derived_from_ladder_id")
    if ancestor_id is not None:
        get_ladder(ancestor_id)
    if payload["expected_title_version"] != title["version"]:
        raise ApiError("ERR_STALE_TITLE_VERSION")
    rungs = payload["rungs"]
    if len(rungs) < 2 or len(rungs) > 8:
        raise ApiError("ERR_RUNG_SHAPE_INVALID")
    heights = [r["height_px"] for r in rungs]
    if any(heights[i] >= heights[i + 1] for i in range(len(heights) - 1)):
        raise ApiError("ERR_RUNG_SHAPE_INVALID")
    labels = [r["label"] for r in rungs]
    if len(set(labels)) != len(labels):
        raise ApiError("ERR_RUNG_SHAPE_INVALID")
    ladder = build_ladder(
        title["id"], payload["codec_family"], rungs, ancestor_id, "DRAFT", "NONE"
    )
    touch(title)
    derive_packaging(title)
    recompute_readiness(title)
    return created(ladder)


@bp.get("/encoding-ladders/<ladder_id>")
@endpoint(["EncodingEngineer", "ContentOps", "DrmOperator", "PlatformAdmin"])
def read_ladder(ladder_id):
    parse_query([], allow_paging=False)
    return ok(get_ladder(ladder_id))


@bp.get("/encoding-ladders")
@endpoint(["EncodingEngineer", "ContentOps", "DrmOperator", "PlatformAdmin"])
def list_ladders():
    filters = parse_query([
        S("title_id", "string"),
        S("codec_family", "enum", values=CODEC_FAMILIES),
        S("state", "enum", values=LADDER_STATES),
        S("derived_from_ladder_id", "string"),
        S("superseded_by_ladder_id", "string"),
    ])
    page, page_size = read_page_params()
    items = apply_filters(rows(db.ladders), filters, {})
    return send_list(sort_rows(items, [(lambda r: r["created_at"], False)]), page, page_size)


@bp.post("/encoding-ladders/<ladder_id>/validate")
@endpoint(["EncodingEngineer"])
def validate_ladder(ladder_id):
    parse_body([])
    ladder = get_ladder(ladder_id)
    if ladder["state"] != "DRAFT":
        raise ApiError("ERR_LADDER_STATE_INVALID")
    score, count = calc.compat_figures(ladder)
    flaw = calc.rung_geometry_flaw(ladder["rungs"])
    ladder["device_compat_score"] = score
    ladder["compatible_device_count"] = count
    if flaw is None and score > q2(0):
        ladder["state"] = "VALIDATED"
        ladder["validation_reason_code"] = "OK"
    else:
        ladder["state"] = "REJECTED"
        ladder["validation_reason_code"] = flaw or "NO_COMPATIBLE_DEVICE"
    touch(ladder)
    recompute_readiness(db.titles[ladder["title_id"]])
    return ok(ladder)


@bp.post("/encoding-ladders/<ladder_id>/lock")
@endpoint(["EncodingEngineer"])
def lock_ladder(ladder_id):
    parse_body([])
    ladder = get_ladder(ladder_id)
    if ladder["state"] != "VALIDATED":
        raise ApiError("ERR_LADDER_STATE_INVALID")
    title = db.titles[ladder["title_id"]]
    masters = calc.title_assets(title["id"])
    if not any(m["qc_state"] == "QC_PASSED" for m in masters):
        raise ApiError("ERR_NO_PASSED_ASSET")
    if any(m["qc_state"] == "REMEDIATION_REQUESTED" for m in masters):
        raise ApiError("ERR_ASSET_REMEDIATION_PENDING")

    # Hop 1: the ladder locks and the title's locked count is recomputed.
    ladder["state"] = "LOCKED"
    touch(ladder)
    recompute_locked_count(title)
    touch(title)
    # Hop 2: any other LOCKED ladder of the same title and codec family is superseded,
    # which itself drives hops 3 and 4.
    for other in calc.title_ladders(title["id"]):
        if other["id"] == ladder["id"]:
            continue
        if other["state"] == "LOCKED" and other["codec_family"] == ladder["codec_family"]:
            supersede_ladder(other, ladder["id"], title)
    # Hops 4 and 5: the packaging dimension is re-derived and may take the title down.
    derive_packaging(title)
    recompute_readiness(title)
    return ok(ladder)
