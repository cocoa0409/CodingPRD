"""Titles, licensing windows and manual takedown (PRD 3.1, 3.6)."""

from decimal import Decimal

from flask import Blueprint

from db import db, dec, new_row, now, q2, rows, sort_rows, touch
from errors import ApiError
from middleware import endpoint
from response import created, ok, read_page_params
from routes.common import (
    AVAILABILITY_STATES, CONTENT_TYPES, LICENSE_TIERS, PACKAGING_STATES,
    QC_STATES, REGION_PATTERN, WINDOW_STATES, apply_filters, get_title,
    get_window, send_list,
)
from services import calc
from services.domain import committed_total, derive_packaging, recompute_readiness
from validation import S, parse_body, parse_query

bp = Blueprint("titles", __name__)

BUDGET_DEFAULT = Decimal("5000.00")

TITLE_CREATE = [
    S("external_ref", "string", min_len=1, max_len=40, pattern=r"^[A-Z0-9\-]{1,40}$"),
    S("title_name", "string", min_len=1, max_len=200),
    S("content_type", "enum", values=CONTENT_TYPES),
    S("studio_code", "string", pattern=r"^[A-Z0-9]{2,10}$"),
    S("encode_budget_usd", "number", required=False, minimum=0, scale=2),
]

TITLE_PATCH = [
    S("title_name", "string", required=False, min_len=1, max_len=200),
    S("studio_code", "string", required=False, pattern=r"^[A-Z0-9]{2,10}$"),
    S("encode_budget_usd", "number", required=False, minimum=0, scale=2),
]

WINDOW_CREATE = [
    S("region_code", "string", pattern=REGION_PATTERN),
    S("window_start_at", "instant"),
    S("window_end_at", "instant"),
    S("license_tier", "enum", values=LICENSE_TIERS),
]


@bp.post("/titles")
@endpoint(["ContentOps"])
def create_title():
    payload = parse_body(TITLE_CREATE)
    for existing in rows(db.titles):
        if existing["external_ref"] == payload["external_ref"]:
            raise ApiError("ERR_DUPLICATE_EXTERNAL_REF")
    budget = q2(payload.get("encode_budget_usd", BUDGET_DEFAULT))
    title = new_row()
    title["external_ref"] = payload["external_ref"]
    title["title_name"] = payload["title_name"]
    title["content_type"] = payload["content_type"]
    title["studio_code"] = payload["studio_code"]
    title["availability_state"] = "DRAFT"
    title["packaging_state"] = "UNPACKAGED"
    title["takedown_reason"] = "NONE"
    title["encode_budget_usd"] = budget
    title["encode_budget_remaining_usd"] = budget
    title["readiness_score_provisional"] = q2(0)
    title["readiness_score_certified"] = q2(0)
    title["locked_ladder_count"] = 0
    title["last_sweep_at"] = None
    db.titles[title["id"]] = title
    return created(title)


@bp.get("/titles/<title_id>")
@endpoint(["ContentOps", "QcAnalyst", "EncodingEngineer", "DrmOperator",
           "DeliveryEngineer", "PlatformAdmin"])
def read_title(title_id):
    parse_query([], allow_paging=False)
    return ok(get_title(title_id))


@bp.get("/titles")
@endpoint(["ContentOps", "EncodingEngineer", "DrmOperator", "DeliveryEngineer",
           "PlatformAdmin"])
def list_titles():
    filters = parse_query([
        S("content_type", "enum", values=CONTENT_TYPES),
        S("availability_state", "enum", values=AVAILABILITY_STATES),
        S("packaging_state", "enum", values=PACKAGING_STATES),
        S("external_ref", "string"),
    ])
    page, page_size = read_page_params()
    items = apply_filters(rows(db.titles), filters, {})
    return send_list(sort_rows(items, [(lambda r: r["created_at"], False)]), page, page_size)


@bp.patch("/titles/<title_id>")
@endpoint(["ContentOps"])
def update_title(title_id):
    payload = parse_body(TITLE_PATCH)
    title = get_title(title_id)
    if "encode_budget_usd" in payload:
        proposed = q2(payload["encode_budget_usd"])
        if proposed < committed_total(title["id"]):
            raise ApiError("ERR_ENCODE_BUDGET_EXCEEDED")
        title["encode_budget_usd"] = proposed
    if "title_name" in payload:
        title["title_name"] = payload["title_name"]
    if "studio_code" in payload:
        title["studio_code"] = payload["studio_code"]
    title["encode_budget_remaining_usd"] = q2(
        dec(title["encode_budget_usd"]) - committed_total(title["id"])
    )
    touch(title)
    return ok(title)


@bp.post("/titles/<title_id>/takedown")
@endpoint(["ContentOps"])
def takedown_title(title_id):
    # Only MANUAL_LEGAL may be asserted by an operator here.
    payload = parse_body([S("takedown_reason", "enum", values=("MANUAL_LEGAL",))])
    title = get_title(title_id)
    title["availability_state"] = "TAKEN_DOWN"
    title["takedown_reason"] = payload["takedown_reason"]
    for window in calc.title_windows(title["id"]):
        if window["state"] == "ACTIVE":
            window["state"] = "CLOSED"
            window["closed_at"] = now()
            touch(window)
    touch(title)
    return ok(title)


@bp.post("/titles/<title_id>/availability-windows")
@endpoint(["ContentOps"])
def schedule_window(title_id):
    payload = parse_body(WINDOW_CREATE)
    title = get_title(title_id)
    if title["availability_state"] == "TAKEN_DOWN" and title["takedown_reason"] == "MANUAL_LEGAL":
        raise ApiError("ERR_TITLE_LEGALLY_BLOCKED")
    start = payload["window_start_at"]
    end = payload["window_end_at"]
    if not start < end:
        raise ApiError("ERR_WINDOW_BOUNDS_INVALID")
    if start < now():
        raise ApiError("ERR_WINDOW_IN_PAST")
    for existing in calc.title_windows(title["id"]):
        if existing["region_code"] != payload["region_code"]:
            continue
        if existing["state"] not in ("SCHEDULED", "ACTIVE"):
            continue
        if calc.windows_conflict(existing, start, end):
            raise ApiError("ERR_WINDOW_OVERLAP")
    window = new_row()
    window["title_id"] = title["id"]
    window["region_code"] = payload["region_code"]
    window["window_start_at"] = start
    window["window_end_at"] = end
    window["license_tier"] = payload["license_tier"]
    window["state"] = "SCHEDULED"
    window["activated_at"] = None
    window["closed_at"] = None
    db.windows[window["id"]] = window
    if title["availability_state"] == "DRAFT":
        title["availability_state"] = "SCHEDULED"
    touch(title)
    return created(window)


@bp.get("/titles/<title_id>/availability-windows")
@endpoint(["ContentOps", "DeliveryEngineer", "PlatformAdmin"])
def list_windows(title_id):
    filters = parse_query([
        S("region_code", "string", pattern=REGION_PATTERN),
        S("state", "enum", values=WINDOW_STATES),
    ])
    page, page_size = read_page_params()
    title = get_title(title_id)
    items = apply_filters(calc.title_windows(title["id"]), filters, {})
    ordered = sort_rows(items, [
        (lambda r: r["window_start_at"], False),
        (lambda r: r["created_at"], False),
    ])
    return send_list(ordered, page, page_size)


@bp.get("/titles/<title_id>/mezzanine-assets")
@endpoint(["ContentOps", "QcAnalyst", "EncodingEngineer", "PlatformAdmin"])
def list_title_assets(title_id):
    filters = parse_query([S("qc_state", "enum", values=QC_STATES)])
    page, page_size = read_page_params()
    title = get_title(title_id)
    items = apply_filters(calc.title_assets(title["id"]), filters, {})
    ordered = sort_rows(items, [(lambda r: r["created_at"], False)])
    return send_list(ordered, page, page_size)


@bp.post("/availability-windows/<window_id>/cancel")
@endpoint(["ContentOps"])
def cancel_window(window_id):
    parse_body([])
    window = get_window(window_id)
    if window["state"] not in ("SCHEDULED", "ACTIVE"):
        raise ApiError("ERR_WINDOW_STATE_INVALID")
    was_active = window["state"] == "ACTIVE"
    window["state"] = "CANCELLED"
    window["closed_at"] = now()
    touch(window)
    title = db.titles.get(window["title_id"])
    if was_active and title is not None:
        remaining = [
            w for w in calc.title_windows(title["id"]) if w["state"] == "ACTIVE"
        ]
        if not remaining and title["availability_state"] == "PUBLISHED":
            title["availability_state"] = "TAKEN_DOWN"
            title["takedown_reason"] = "CONTRACT_END"
            from db import stamp_only
            stamp_only(title)
    return ok(window)
