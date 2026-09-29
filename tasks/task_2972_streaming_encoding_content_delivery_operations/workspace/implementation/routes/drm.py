"""DRM packages, entitlement rules and the playback entitlement check (PRD 3.5)."""

from flask import Blueprint

from db import db, new_row, now, rows, sort_rows, touch
from errors import ApiError
from middleware import endpoint
from response import created, ok, read_page_params
from routes.common import (
    DEVICE_CLASSES, DEVICE_SCOPES, DRM_SYSTEMS, HDCP_LEVELS, PACKAGE_STATES,
    REGION_OR_WILDCARD, REGION_PATTERN, SUBSCRIPTION_TIERS, apply_filters,
    get_ladder, get_package, get_title, send_list,
)
from services import calc
from services.domain import derive_packaging, recompute_readiness
from validation import S, parse_body, parse_query

bp = Blueprint("drm", __name__)

PACKAGE_CREATE = [
    S("title_id", "string"),
    S("ladder_id", "string"),
    S("drm_systems", "array", min_items=1, max_items=3, unique=True,
      item=S("drm_systems[]", "enum", values=DRM_SYSTEMS)),
    S("license_server_url", "string", min_len=8, max_len=300, prefix="https://"),
    S("key_rotation_hours", "integer", required=False, default=24, minimum=1, maximum=168),
    S("persistent_license_allowed", "boolean", required=False, default=False),
]

RULE_CREATE = [
    S("region_code", "string", pattern=REGION_OR_WILDCARD),
    S("subscription_tier", "enum", values=SUBSCRIPTION_TIERS),
    S("device_class_scope", "enum", required=False, default="ALL", values=DEVICE_SCOPES),
    S("max_concurrent_streams", "integer", minimum=1, maximum=10),
    S("max_playback_height_px", "integer", minimum=240, maximum=2160),
    S("hdcp_level", "enum", values=HDCP_LEVELS),
    S("offline_playback_allowed", "boolean", required=False, default=False),
    S("priority", "integer", minimum=1, maximum=100),
]

CHECK_INPUT = [
    S("title_id", "string"),
    S("region_code", "string", pattern=REGION_PATTERN),
    S("subscription_tier", "enum", values=SUBSCRIPTION_TIERS),
    S("device_class", "enum", values=DEVICE_CLASSES),
    S("requested_streams", "integer", minimum=1),
    S("offline_requested", "boolean", required=False, default=False),
]

BINDABLE_LADDER_STATES = ("DRAFT", "VALIDATED", "LOCKED")


def _hdcp_floor(ladder):
    """Derived from the bound ladder's peak height, never supplied."""
    peak = ladder["peak_height_px"]
    if peak >= 2160:
        return "TYPE_1"
    if peak >= 1080:
        return "TYPE_0"
    return "NONE"


def _covered_regions(title_id):
    return set(
        w["region_code"]
        for w in calc.title_windows(title_id)
        if w["state"] in ("SCHEDULED", "ACTIVE")
    )


def _master_quality_gate(title_id):
    masters = calc.title_assets(title_id)
    if not any(m["qc_state"] == "QC_PASSED" for m in masters):
        raise ApiError("ERR_NO_PASSED_ASSET")
    if any(m["qc_state"] == "REMEDIATION_REQUESTED" for m in masters):
        raise ApiError("ERR_ASSET_REMEDIATION_PENDING")


@bp.post("/drm-packages")
@endpoint(["DrmOperator"])
def create_package():
    payload = parse_body(PACKAGE_CREATE)
    title = get_title(payload["title_id"])
    ladder = get_ladder(payload["ladder_id"])
    if ladder["state"] not in BINDABLE_LADDER_STATES:
        raise ApiError("ERR_LADDER_NOT_BINDABLE")
    floor = _hdcp_floor(ladder)
    if floor == "TYPE_1" and "WIDEVINE" not in payload["drm_systems"]:
        raise ApiError("ERR_DRM_SYSTEM_UNSUPPORTED")
    if ladder["title_id"] != title["id"]:
        raise ApiError("ERR_LADDER_TITLE_MISMATCH")
    package = new_row()
    package["title_id"] = title["id"]
    package["ladder_id"] = ladder["id"]
    package["drm_systems"] = payload["drm_systems"]
    package["license_server_url"] = payload["license_server_url"]
    package["key_rotation_hours"] = payload["key_rotation_hours"]
    package["persistent_license_allowed"] = payload["persistent_license_allowed"]
    package["state"] = "PENDING"
    package["stale_reason"] = "NONE"
    package["entitlement_rule_count"] = 0
    package["packaged_at"] = None
    package["hdcp_floor"] = floor
    db.packages[package["id"]] = package
    derive_packaging(title)
    recompute_readiness(title)
    return created(package)


@bp.get("/drm-packages/<package_id>")
@endpoint(["DrmOperator", "ContentOps", "DeliveryEngineer", "PlatformAdmin"])
def read_package(package_id):
    parse_query([], allow_paging=False)
    return ok(get_package(package_id))


@bp.get("/drm-packages")
@endpoint(["DrmOperator", "ContentOps", "DeliveryEngineer", "PlatformAdmin"])
def list_packages():
    filters = parse_query([
        S("title_id", "string"),
        S("ladder_id", "string"),
        S("state", "enum", values=PACKAGE_STATES),
    ])
    page, page_size = read_page_params()
    items = apply_filters(rows(db.packages), filters, {})
    return send_list(sort_rows(items, [(lambda r: r["created_at"], False)]), page, page_size)


@bp.post("/drm-packages/<package_id>/package")
@endpoint(["DrmOperator"])
def package_package(package_id):
    payload = parse_body([S("ladder_id", "string", required=False)])
    package = get_package(package_id)
    supplied = payload.get("ladder_id")
    rebound = get_ladder(supplied) if supplied is not None else None
    if package["state"] not in ("PENDING", "STALE"):
        raise ApiError("ERR_PACKAGE_STATE_INVALID")
    title = db.titles[package["title_id"]]
    if package["state"] == "PENDING":
        bound = db.ladders.get(package["ladder_id"])
        if bound is None or bound["state"] != "LOCKED":
            raise ApiError("ERR_LADDER_NOT_LOCKED")
        _master_quality_gate(title["id"])
        if package["entitlement_rule_count"] < 1:
            raise ApiError("ERR_PACKAGE_NOT_READY")
    else:
        # The repackage path must rebind onto a LOCKED ladder of the same title;
        # omitting ladder_id altogether is the same failure.
        if (
            rebound is None
            or rebound["state"] != "LOCKED"
            or rebound["title_id"] != title["id"]
        ):
            raise ApiError("ERR_LADDER_NOT_LOCKED")
        _master_quality_gate(title["id"])
        bound = rebound
        package["ladder_id"] = rebound["id"]
    package["state"] = "PACKAGED"
    package["packaged_at"] = now()
    package["stale_reason"] = "NONE"
    package["hdcp_floor"] = _hdcp_floor(bound)
    touch(package)
    derive_packaging(title)
    recompute_readiness(title)
    return ok(package)


@bp.post("/drm-packages/<package_id>/revoke")
@endpoint(["DrmOperator"])
def revoke_package(package_id):
    parse_body([])
    package = get_package(package_id)
    if package["state"] == "REVOKED":
        raise ApiError("ERR_PACKAGE_STATE_INVALID")
    package["state"] = "REVOKED"
    touch(package)
    title = db.titles[package["title_id"]]
    derive_packaging(title)
    recompute_readiness(title)
    return ok(package)


@bp.post("/drm-packages/<package_id>/entitlement-rules")
@endpoint(["DrmOperator"])
def create_rule(package_id):
    payload = parse_body(RULE_CREATE)
    package = get_package(package_id)
    if calc.HDCP_ORDER[payload["hdcp_level"]] < calc.HDCP_ORDER[package["hdcp_floor"]]:
        raise ApiError("ERR_HDCP_FLOOR_VIOLATION")
    if payload["offline_playback_allowed"] and not package["persistent_license_allowed"]:
        raise ApiError("ERR_OFFLINE_NOT_LICENSED")
    if payload["region_code"] != "*":
        if payload["region_code"] not in _covered_regions(package["title_id"]):
            raise ApiError("ERR_RULE_REGION_NOT_LICENSED")
    key = (
        payload["region_code"],
        payload["subscription_tier"],
        payload["device_class_scope"],
    )
    for existing in calc.package_rules(package["id"]):
        current = (
            existing["region_code"],
            existing["subscription_tier"],
            existing["device_class_scope"],
        )
        if current == key:
            raise ApiError("ERR_DUPLICATE_ENTITLEMENT_RULE")
    rule = new_row(versioned=False)
    rule["package_id"] = package["id"]
    rule["region_code"] = payload["region_code"]
    rule["subscription_tier"] = payload["subscription_tier"]
    rule["device_class_scope"] = payload["device_class_scope"]
    rule["max_concurrent_streams"] = payload["max_concurrent_streams"]
    rule["max_playback_height_px"] = payload["max_playback_height_px"]
    rule["hdcp_level"] = payload["hdcp_level"]
    rule["offline_playback_allowed"] = payload["offline_playback_allowed"]
    rule["priority"] = payload["priority"]
    db.entitlement_rules[rule["id"]] = rule
    package["entitlement_rule_count"] = package["entitlement_rule_count"] + 1
    touch(package)
    return created(rule)


@bp.get("/drm-packages/<package_id>/entitlement-rules")
@endpoint(["DrmOperator", "DeliveryEngineer", "PlatformAdmin"])
def list_rules(package_id):
    filters = parse_query([
        S("region_code", "string", pattern=REGION_OR_WILDCARD),
        S("subscription_tier", "enum", values=SUBSCRIPTION_TIERS),
        S("device_class_scope", "enum", values=DEVICE_SCOPES),
    ])
    page, page_size = read_page_params()
    package = get_package(package_id)
    items = apply_filters(calc.package_rules(package["id"]), filters, {})
    ordered = sort_rows(items, [
        (lambda r: r["priority"], True),
        (lambda r: r["created_at"], False),
    ])
    return send_list(ordered, page, page_size)


@bp.post("/playback-entitlement-checks")
@endpoint(["DeliveryEngineer", "DrmOperator"])
def entitlement_check():
    payload = parse_body(CHECK_INPUT)
    title = get_title(payload["title_id"])
    # Stage 1 -- package selection: the oldest PACKAGED package and no other.
    candidates = [p for p in calc.title_packages(title["id"]) if p["state"] == "PACKAGED"]
    if not candidates:
        raise ApiError("ERR_NO_PACKAGED_DRM")
    package = sort_rows(candidates, [(lambda r: r["created_at"], False)])[0]
    # Stage 2 -- the requesting device must be an ACTIVE profile of that class.
    profile = None
    for row in rows(db.device_profiles):
        if row["device_class"] == payload["device_class"] and row["state"] == "ACTIVE":
            profile = row
            break
    if profile is None:
        raise ApiError("ERR_DEVICE_PROFILE_NOT_FOUND")
    # Stages 3 and 4 -- eligibility then ranking.
    qualifying = [
        rule
        for rule in calc.package_rules(package["id"])
        if calc.rule_matches(
            rule, payload["region_code"], payload["subscription_tier"],
            payload["device_class"], profile,
        )
    ]
    ranked = calc.rank_rules(qualifying, payload["region_code"])
    if not ranked:
        raise ApiError("ERR_ENTITLEMENT_NO_RULE")
    rule = ranked[0]
    # Stage 5 -- the two post-match gates, in order.
    if payload["requested_streams"] > rule["max_concurrent_streams"]:
        raise ApiError("ERR_CONCURRENCY_LIMIT_EXCEEDED")
    offline_ok = rule["offline_playback_allowed"] and package["persistent_license_allowed"]
    if payload["offline_requested"] and not offline_ok:
        raise ApiError("ERR_OFFLINE_PLAYBACK_DENIED")
    ladder = db.ladders.get(package["ladder_id"])
    ceilings = [rule["max_playback_height_px"], profile["max_height_px"]]
    if ladder is not None:
        ceilings.append(ladder["peak_height_px"])
    return ok({
        "decision": "ALLOW",
        "reason_code": "MATCHED",
        "matched_rule_id": rule["id"],
        "package_id": package["id"],
        "max_concurrent_streams": rule["max_concurrent_streams"],
        "offline_granted": bool(payload["offline_requested"] and offline_ok),
        "effective_height_px": min(ceilings),
    })
