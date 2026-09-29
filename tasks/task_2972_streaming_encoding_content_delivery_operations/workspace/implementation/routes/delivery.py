"""CDN vendors, traffic steering and playback telemetry (PRD 3.7)."""

from flask import Blueprint

from db import db, dec, new_row, q2, q4, rows, sort_rows, touch
from errors import ApiError
from middleware import endpoint
from response import created, ok, read_page_params
from routes.common import (
    POLICY_STATES, REGION_PATTERN, STEERING_MODES, apply_filters, get_metric,
    get_policy, get_profile, get_title, get_vendor, send_list,
)
from services import calc
from services.domain import refresh_vendor_health, resteer_policy
from validation import S, parse_body, parse_query

bp = Blueprint("delivery", __name__)

REGIONS_SPEC = S("regions", "array", min_items=1, max_items=20, unique=True,
                 item=S("regions[]", "string", pattern=REGION_PATTERN))

VENDOR_CREATE = [
    S("vendor_code", "string", pattern=r"^[A-Z0-9]{2,16}$"),
    REGIONS_SPEC,
    S("committed_gbps", "number", exclusive_minimum=0, scale=2),
    S("cost_per_gb_usd", "number", exclusive_minimum=0, scale=4),
]

VENDOR_PATCH = [
    S("committed_gbps", "number", required=False, exclusive_minimum=0, scale=2),
    S("cost_per_gb_usd", "number", required=False, exclusive_minimum=0, scale=4),
    S("regions", "array", required=False, min_items=1, max_items=20, unique=True,
      item=S("regions[]", "string", pattern=REGION_PATTERN)),
]

POLICY_CREATE = [
    S("title_id", "string"),
    S("region_code", "string", pattern=REGION_PATTERN),
    S("steering_mode", "enum", values=STEERING_MODES),
]

METRIC_CREATE = [
    S("title_id", "string"),
    S("device_profile_id", "string"),
    S("vendor_id", "string"),
    S("region_code", "string", pattern=REGION_PATTERN),
    S("window_start_at", "instant"),
    S("window_end_at", "instant"),
    S("play_attempts", "integer", minimum=1),
    S("rebuffer_events", "integer", minimum=0),
    S("startup_ms_p95", "integer", minimum=0, maximum=60000),
    S("error_count", "integer", minimum=0),
]


@bp.post("/cdn-vendors")
@endpoint(["PlatformAdmin"])
def create_vendor():
    payload = parse_body(VENDOR_CREATE)
    for existing in rows(db.vendors):
        if existing["vendor_code"] == payload["vendor_code"]:
            raise ApiError("ERR_DUPLICATE_VENDOR_CODE")
    vendor = new_row()
    vendor["vendor_code"] = payload["vendor_code"]
    vendor["regions"] = payload["regions"]
    vendor["committed_gbps"] = q2(payload["committed_gbps"])
    vendor["cost_per_gb_usd"] = q4(payload["cost_per_gb_usd"])
    vendor["state"] = "ACTIVE"
    vendor["reserved_gbps"] = q2(0)
    vendor["breach_window_count"] = 0
    # Both variants are seeded at the value the health calculation yields with
    # no measurement rows at all.
    vendor["health_score_rolling"] = q2(100)
    vendor["health_score_contract"] = q2(100)
    db.vendors[vendor["id"]] = vendor
    return created(vendor)


@bp.get("/cdn-vendors/<vendor_id>")
@endpoint(["PlatformAdmin", "DeliveryEngineer", "VendorOperator"], scope="vendor_path")
def read_vendor(vendor_id):
    parse_query([], allow_paging=False)
    return ok(get_vendor(vendor_id))


@bp.patch("/cdn-vendors/<vendor_id>")
@endpoint(["PlatformAdmin", "VendorOperator"], scope="vendor_path")
def update_vendor(vendor_id):
    payload = parse_body(VENDOR_PATCH)
    vendor = get_vendor(vendor_id)
    if "committed_gbps" in payload:
        proposed = q2(payload["committed_gbps"])
        if proposed < dec(vendor["reserved_gbps"]):
            raise ApiError("ERR_VENDOR_CAPACITY_EXCEEDED")
        vendor["committed_gbps"] = proposed
    if "cost_per_gb_usd" in payload:
        vendor["cost_per_gb_usd"] = q4(payload["cost_per_gb_usd"])
    if "regions" in payload:
        vendor["regions"] = payload["regions"]
    # Changing price or regions deliberately re-steers nothing.
    touch(vendor)
    return ok(vendor)


@bp.post("/routing-policies")
@endpoint(["DeliveryEngineer"])
def create_policy():
    payload = parse_body(POLICY_CREATE)
    title = get_title(payload["title_id"])
    for existing in rows(db.policies):
        if existing["title_id"] == title["id"] and existing["region_code"] == payload["region_code"]:
            raise ApiError("ERR_DUPLICATE_ROUTING_POLICY")
    primary, backup, state, reason, count = calc.select_vendors(
        payload["region_code"], [], payload["steering_mode"]
    )
    if count == 0:
        # Fatal at creation: nothing at all is persisted.
        raise ApiError("ERR_NO_ELIGIBLE_VENDOR")
    policy = new_row()
    policy["title_id"] = title["id"]
    policy["region_code"] = payload["region_code"]
    policy["steering_mode"] = payload["steering_mode"]
    policy["primary_vendor_id"] = primary
    policy["backup_vendor_id"] = backup
    policy["state"] = state
    policy["excluded_vendor_ids"] = []
    policy["resteer_count"] = 0
    policy["selection_reason_code"] = reason
    policy["projected_egress_cost_usd"] = q2(0)
    db.policies[policy["id"]] = policy
    policy["projected_egress_cost_usd"] = calc.egress_projection(policy)
    return created(policy)


@bp.get("/routing-policies/<policy_id>")
@endpoint(["DeliveryEngineer", "ContentOps", "PlatformAdmin"])
def read_policy(policy_id):
    parse_query([], allow_paging=False)
    return ok(get_policy(policy_id))


@bp.get("/routing-policies")
@endpoint(["DeliveryEngineer", "ContentOps", "PlatformAdmin", "VendorOperator"],
          scope="policies_list")
def list_policies():
    filters = parse_query([
        S("title_id", "string"),
        S("primary_vendor_id", "string"),
        S("backup_vendor_id", "string"),
        S("region_code", "string", pattern=REGION_PATTERN),
        S("state", "enum", values=POLICY_STATES),
    ])
    page, page_size = read_page_params()
    items = apply_filters(rows(db.policies), filters, {})
    return send_list(sort_rows(items, [(lambda r: r["created_at"], False)]), page, page_size)


@bp.post("/routing-policies/<policy_id>/resteer")
@endpoint(["DeliveryEngineer"])
def resteer(policy_id):
    parse_body([])
    policy = get_policy(policy_id)
    # Every policy state admits a re-steer, so rung 10 never fires here.
    resteer_policy(policy)
    return ok(policy)


@bp.post("/playback-metrics")
@endpoint(["DeliveryEngineer", "PlatformAdmin"])
def ingest_metric():
    payload = parse_body(METRIC_CREATE)
    title = get_title(payload["title_id"])
    profile = get_profile(payload["device_profile_id"])
    vendor = get_vendor(payload["vendor_id"])
    if payload["region_code"] not in vendor["regions"]:
        raise ApiError("ERR_VENDOR_REGION_NOT_SERVED")
    start = payload["window_start_at"]
    end = payload["window_end_at"]
    if not start < end:
        raise ApiError("ERR_WINDOW_BOUNDS_INVALID")
    from db import now

    if end > now():
        raise ApiError("ERR_METRIC_WINDOW_IN_FUTURE")
    figures = calc.quality_figures(
        payload["play_attempts"], payload["rebuffer_events"],
        payload["startup_ms_p95"], payload["error_count"], profile,
    )
    metric = new_row(versioned=False)
    metric["title_id"] = title["id"]
    metric["device_profile_id"] = profile["id"]
    metric["vendor_id"] = vendor["id"]
    metric["region_code"] = payload["region_code"]
    metric["window_start_at"] = start
    metric["window_end_at"] = end
    metric["play_attempts"] = payload["play_attempts"]
    metric["rebuffer_events"] = payload["rebuffer_events"]
    metric["startup_ms_p95"] = payload["startup_ms_p95"]
    metric["error_count"] = payload["error_count"]
    metric["rebuffer_ratio"] = figures["rebuffer_ratio"]
    metric["error_rate"] = figures["error_rate"]
    metric["quality_index"] = figures["quality_index"]
    metric["breach_flag"] = figures["breach_flag"]
    db.metrics[metric["id"]] = metric
    # The metric-ingest cascade: health, then vendor state, then dependent steering.
    refresh_vendor_health(vendor)
    return created(metric)


@bp.get("/playback-metrics/<metric_id>")
@endpoint(["DeliveryEngineer", "PlatformAdmin", "VendorOperator"])
def read_metric(metric_id):
    parse_query([], allow_paging=False)
    return ok(get_metric(metric_id))


@bp.get("/playback-metrics")
@endpoint(["DeliveryEngineer", "PlatformAdmin", "VendorOperator"], scope="metrics_list")
def list_metrics():
    filters = parse_query([
        S("title_id", "string"),
        S("device_profile_id", "string"),
        S("vendor_id", "string"),
        S("region_code", "string", pattern=REGION_PATTERN),
        S("breach_flag", "boolean"),
    ])
    page, page_size = read_page_params()
    items = apply_filters(rows(db.metrics), filters, {})
    ordered = sort_rows(items, [
        (lambda r: r["window_start_at"], True),
        (lambda r: r["created_at"], True),
    ])
    return send_list(ordered, page, page_size)
