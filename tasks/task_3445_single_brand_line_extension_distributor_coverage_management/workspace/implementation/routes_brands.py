"""Brands and product lines (PRD §3.1, §3.2)."""
from datetime import timedelta

from flask import Blueprint

from core import STORE, err, ok, stamp_new, touch, now_iso, parse_datetime
from derived import (
    brand_of_line,
    live_dilution_cost,
    line_dilution_repr,
    recompute_brand_equity,
    secs,
)
from validate import (
    ALL_ROLES, CHANNELS, LOCKDOWN_REASONS, REVIEW_DECISIONS,
    as_enum, as_enum_list, as_int, as_str, authenticate, authorize, body,
    filter_eq, get_or_404, need, opt_bool, opt_int, paginate,
)

bp = Blueprint("brands", __name__)

BRAND_FIELDS = [
    "id", "name", "legal_entity_name", "equity_budget_bps", "status",
    "lockdown_reason", "protection_posture", "dilution_consumed_bps",
    "core_identity_share_bps", "genericization_risk_bps",
    "created_at", "updated_at", "version",
]
LINE_FIELDS = [
    "id", "brand_id", "line_code", "name", "is_core", "target_channels",
    "status", "brand_review_attempts", "dilution_cost_bps", "launched_at",
    "created_at", "updated_at", "version",
]


def brand_json(b):
    return {k: b.get(k) for k in BRAND_FIELDS}


def line_json(l):
    out = {k: l.get(k) for k in LINE_FIELDS}
    out["dilution_cost_bps"] = line_dilution_repr(l)
    return out


# ---------------------------------------------------------------------------
# Brand endpoints
# ---------------------------------------------------------------------------
@bp.post("/brand-ops/brands")
def create_brand():
    _, role = authenticate()
    authorize(role, ["BrandManager"])
    b = body()
    name = as_str(need(b, "name"), "name")
    legal = as_str(need(b, "legal_entity_name"), "legal_entity_name")
    budget = opt_int(b, "equity_budget_bps", 10000, minimum=1)
    brand = stamp_new({
        "name": name,
        "legal_entity_name": legal,
        "equity_budget_bps": budget,
        "status": "OPERATING",
        "lockdown_reason": None,
        "protection_posture": "NORMAL",
        "dilution_consumed_bps": 0,
        "core_identity_share_bps": 10000,
        "genericization_risk_bps": 0,
    })
    STORE["brands"][brand["id"]] = brand
    return ok(brand_json(brand), code=201)


@bp.get("/brand-ops/brands")
def list_brands():
    authenticate()
    page, pagination = paginate(list(STORE["brands"].values()))
    return ok([brand_json(b) for b in page], response_type="array", pagination=pagination)


@bp.get("/brand-ops/brands/<bid>")
def get_brand(bid):
    authenticate()
    return ok(brand_json(get_or_404("brands", bid, "brand")))


@bp.post("/brand-ops/brands/<bid>/lockdown")
def lockdown_brand(bid):
    _, role = authenticate()
    authorize(role, ["ComplianceAuditor"])
    brand = get_or_404("brands", bid, "brand")
    b = body()
    reason = as_enum(need(b, "reason"), "reason", LOCKDOWN_REASONS)
    if brand["status"] != "OPERATING":
        err("ERR_INVALID_STATE_TRANSITION", "Brand is not OPERATING")
    brand["status"] = "PROTECTIVE_LOCKDOWN"
    brand["lockdown_reason"] = reason
    touch(brand)
    return ok(brand_json(brand))


@bp.post("/brand-ops/brands/<bid>/lift-lockdown")
def lift_lockdown(bid):
    _, role = authenticate()
    authorize(role, ["ComplianceAuditor"])
    brand = get_or_404("brands", bid, "brand")
    body()  # body tolerated, nothing required
    if brand["status"] != "PROTECTIVE_LOCKDOWN":
        err("ERR_INVALID_STATE_TRANSITION", "Brand is not PROTECTIVE_LOCKDOWN")
    for c in STORE["cases"].values():
        if (
            c["brand_id"] == bid
            and c["status"] in ("REPORTED", "ACTION_TAKEN")
            and c["severity"] == 5
        ):
            err("ERR_LOCKDOWN_CONDITIONS_UNMET", "A severity-5 counterfeit case is still open")
    line_ids = {l["id"] for l in STORE["product_lines"].values() if l["brand_id"] == bid}
    form_ids = {
        f["id"] for f in STORE["formulations"].values() if f["product_line_id"] in line_ids
    }
    from core import now
    cutoff = secs(now() - timedelta(days=90))
    for g in STORE["grants"].values():
        if g["formulation_id"] in form_ids and g["revoked_for_cause"] and g["revoked_at"]:
            if secs(parse_datetime(g["revoked_at"])) >= cutoff:
                err("ERR_LOCKDOWN_CONDITIONS_UNMET",
                    "A for-cause revocation is within the trailing 90 days")
    brand["status"] = "OPERATING"
    brand["lockdown_reason"] = None
    touch(brand)
    return ok(brand_json(brand))


# ---------------------------------------------------------------------------
# Product line endpoints
# ---------------------------------------------------------------------------
@bp.post("/brand-ops/brands/<brandId>/product-lines")
def create_line(brandId):
    _, role = authenticate()
    authorize(role, ["BrandManager"])
    brand = get_or_404("brands", brandId, "brand")
    b = body()
    line_code = as_str(need(b, "line_code"), "line_code")
    name = as_str(need(b, "name"), "name")
    is_core = opt_bool(b, "is_core", False)
    channels = as_enum_list(need(b, "target_channels"), "target_channels", CHANNELS)
    # 12: uniqueness / single-core constraints
    for other in STORE["product_lines"].values():
        if other["brand_id"] != brandId or other["status"] == "DISCONTINUED":
            continue
        if other["line_code"] == line_code:
            err("ERR_DUPLICATE_LINE_CODE", "line_code already used by a live line")
    if is_core:
        for other in STORE["product_lines"].values():
            if (
                other["brand_id"] == brandId
                and other["status"] != "DISCONTINUED"
                and other["is_core"]
            ):
                err("ERR_CORE_LINE_EXISTS", "A live core line already exists")
    line = stamp_new({
        "brand_id": brand["id"],
        "line_code": line_code,
        "name": name,
        "is_core": is_core,
        "target_channels": channels,
        "status": "FORMULATION",
        "brand_review_attempts": 0,
        "launched_at": None,
        "_frozen_cost_bps": None,
    })
    STORE["product_lines"][line["id"]] = line
    return ok(line_json(line), code=201)


@bp.get("/brand-ops/product-lines")
def list_lines():
    authenticate()
    from flask import request
    items = list(STORE["product_lines"].values())
    items = filter_eq(items, "brand_id", request.args.get("brand_id"))
    items = filter_eq(items, "status", request.args.get("status"))
    page, pagination = paginate(items)
    return ok([line_json(l) for l in page], response_type="array", pagination=pagination)


@bp.get("/brand-ops/product-lines/<lid>")
def get_line(lid):
    authenticate()
    return ok(line_json(get_or_404("product_lines", lid, "product line")))


@bp.post("/brand-ops/product-lines/<lid>/brand-review")
def brand_review(lid):
    _, role = authenticate()
    authorize(role, ["BrandManager"])
    line = get_or_404("product_lines", lid, "product line")
    b = body()
    decision = as_enum(need(b, "decision"), "decision", REVIEW_DECISIONS)
    if line["status"] != "FORMULATION":
        err("ERR_INVALID_STATE_TRANSITION", "Line is not in FORMULATION")
    brand = brand_of_line(line)
    if decision == "REJECT":
        if line["brand_review_attempts"] < 2:
            line["brand_review_attempts"] += 1
            touch(line)
        else:
            line["brand_review_attempts"] = 3
            line["status"] = "DISCONTINUED"
            touch(line)
            recompute_brand_equity(brand)
        return ok(line_json(line))
    # APPROVE: formulation gate (11) then fiscal gates (13) in order
    sealed = any(
        f["product_line_id"] == lid and f["status"] in ("SEALED", "COMPARTMENTALIZED")
        for f in STORE["formulations"].values()
    )
    if not sealed:
        err("ERR_FORMULATION_NOT_SEALED", "No SEALED or COMPARTMENTALIZED formulation")
    cost = live_dilution_cost(line)
    if brand["dilution_consumed_bps"] + cost > brand["equity_budget_bps"]:
        err("ERR_EQUITY_BUDGET_EXCEEDED", "Equity budget would be exceeded")
    if brand["core_identity_share_bps"] - cost < 7000:
        err("ERR_CORE_IDENTITY_DILUTION", "Core identity share would fall below 7000")
    line["_frozen_cost_bps"] = cost
    line["status"] = "PILOT"
    touch(line)
    recompute_brand_equity(brand)
    return ok(line_json(line))


@bp.post("/brand-ops/product-lines/<lid>/launch")
def launch_line(lid):
    _, role = authenticate()
    authorize(role, ["BrandManager"])
    line = get_or_404("product_lines", lid, "product line")
    body()
    if line["status"] != "PILOT":
        err("ERR_INVALID_STATE_TRANSITION", "Line is not PILOT")
    brand = brand_of_line(line)
    if brand["status"] != "OPERATING":
        err("ERR_BRAND_IN_LOCKDOWN", "Brand is in PROTECTIVE_LOCKDOWN")
    if brand["protection_posture"] == "CRITICAL":
        err("ERR_POSTURE_CRITICAL", "Brand protection posture is CRITICAL")
    producible = any(
        p["product_line_id"] == lid and p["status"] == "IN_PRODUCTION"
        for p in STORE["packs"].values()
    )
    if not producible:
        err("ERR_NO_PRODUCIBLE_PACK_FORMAT", "No IN_PRODUCTION pack format on the line")
    line["status"] = "LAUNCHED"
    line["launched_at"] = now_iso()
    touch(line)
    return ok(line_json(line))


@bp.post("/brand-ops/product-lines/<lid>/discontinue")
def discontinue_line(lid):
    _, role = authenticate()
    authorize(role, ["BrandManager"])
    line = get_or_404("product_lines", lid, "product line")
    body()
    if line["status"] not in ("PILOT", "LAUNCHED"):
        err("ERR_INVALID_STATE_TRANSITION", "Line is not PILOT or LAUNCHED")
    if line["is_core"]:
        err("ERR_CORE_LINE_IMMUTABLE", "The core line cannot be discontinued")
    line["status"] = "DISCONTINUED"
    touch(line)
    recompute_brand_equity(brand_of_line(line))
    return ok(line_json(line))
