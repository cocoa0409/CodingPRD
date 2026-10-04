"""Counterfeit cases and consumer use cases (PRD §3.9)."""
from flask import Blueprint, request

from core import STORE, err, ok, stamp_new, touch
from derived import recompute_genericization, recompute_posture
from validate import (
    CHANNELS, USECASE_DECISIONS,
    as_bool, as_enum, as_int, as_str, authenticate, authorize, body,
    filter_eq, get_or_404, need, opt_int, paginate,
)

bp = Blueprint("defense", __name__)

CASE_FIELDS = [
    "id", "brand_id", "market_id", "channel", "severity", "units_seized",
    "status", "created_at", "updated_at", "version",
]
USECASE_FIELDS = [
    "id", "product_line_id", "submitter_ref", "title", "description",
    "generic_use_flag", "status", "created_at", "updated_at", "version",
]


def case_json(c):
    return {k: c.get(k) for k in CASE_FIELDS}


def usecase_json(u):
    return {k: u.get(k) for k in USECASE_FIELDS}


# ---------------------------------------------------------------------------
# Counterfeit cases
# ---------------------------------------------------------------------------
@bp.post("/brand-ops/brands/<brandId>/counterfeit-cases")
def create_case(brandId):
    _, role = authenticate()
    authorize(role, ["ComplianceAuditor"])
    brand = get_or_404("brands", brandId, "brand")
    b = body()
    market_id = as_str(need(b, "market_id"), "market_id")
    channel = as_enum(need(b, "channel"), "channel", CHANNELS)
    severity = as_int(need(b, "severity"), "severity", minimum=1, maximum=5)
    seized = opt_int(b, "units_seized", 0, minimum=0)
    if market_id not in STORE["markets"]:
        err("ERR_INVALID_REFERENCE", "market_id does not exist")
    case = stamp_new({
        "brand_id": brand["id"],
        "market_id": market_id,
        "channel": channel,
        "severity": severity,
        "units_seized": seized,
        "status": "REPORTED",
    })
    STORE["cases"][case["id"]] = case
    recompute_posture(brand)  # severity-5 creation already fires the promo cascade
    return ok(case_json(case), code=201)


@bp.get("/brand-ops/counterfeit-cases")
def list_cases():
    authenticate()
    items = list(STORE["cases"].values())
    items = filter_eq(items, "brand_id", request.args.get("brand_id"))
    items = filter_eq(items, "market_id", request.args.get("market_id"))
    items = filter_eq(items, "status", request.args.get("status"))
    page, pagination = paginate(items)
    return ok([case_json(c) for c in page], response_type="array", pagination=pagination)


@bp.get("/brand-ops/counterfeit-cases/<cid>")
def get_case(cid):
    authenticate()
    return ok(case_json(get_or_404("cases", cid, "counterfeit case")))


@bp.post("/brand-ops/counterfeit-cases/<cid>/take-action")
def take_action(cid):
    _, role = authenticate()
    authorize(role, ["ComplianceAuditor"])
    case = get_or_404("cases", cid, "counterfeit case")
    b = body()
    seized = as_int(need(b, "units_seized"), "units_seized", minimum=0)
    if case["status"] != "REPORTED":
        err("ERR_INVALID_STATE_TRANSITION", "Case is not REPORTED")
    case["status"] = "ACTION_TAKEN"
    case["units_seized"] = seized
    touch(case)
    brand = STORE["brands"].get(case["brand_id"])
    if brand is not None:
        recompute_posture(brand)
    return ok(case_json(case))


@bp.post("/brand-ops/counterfeit-cases/<cid>/close")
def close_case(cid):
    _, role = authenticate()
    authorize(role, ["ComplianceAuditor"])
    case = get_or_404("cases", cid, "counterfeit case")
    body()
    if case["status"] not in ("REPORTED", "ACTION_TAKEN"):
        err("ERR_INVALID_STATE_TRANSITION", "Case is not REPORTED or ACTION_TAKEN")
    case["status"] = "CLOSED"
    touch(case)
    brand = STORE["brands"].get(case["brand_id"])
    if brand is not None:
        recompute_posture(brand)  # never auto-resumes suspended promotions
    return ok(case_json(case))


# ---------------------------------------------------------------------------
# Consumer use cases
# ---------------------------------------------------------------------------
@bp.post("/brand-ops/product-lines/<lineId>/use-cases")
def create_use_case(lineId):
    user_id, role = authenticate()
    authorize(role, ["Consumer"])
    line = get_or_404("product_lines", lineId, "product line")
    b = body()
    submitter = as_str(need(b, "submitter_ref"), "submitter_ref")
    title = as_str(need(b, "title"), "title")
    description = need(b, "description")
    if not isinstance(description, str):
        err("ERR_INVALID_REQUEST", "Field description must be a string")
    # 6: caller identity
    if submitter != user_id:
        err("ERR_SUBMITTER_MISMATCH", "submitter_ref must equal the caller X-User-ID")
    # 11: line launched
    if line["status"] != "LAUNCHED":
        err("ERR_LINE_NOT_LAUNCHED", "Line is not LAUNCHED")
    uc = stamp_new({
        "product_line_id": line["id"],
        "submitter_ref": submitter,
        "title": title,
        "description": description,
        "generic_use_flag": False,
        "status": "SUBMITTED",
    })
    STORE["use_cases"][uc["id"]] = uc
    return ok(usecase_json(uc), code=201)


@bp.get("/brand-ops/use-cases")
def list_use_cases():
    authenticate()
    items = list(STORE["use_cases"].values())
    items = filter_eq(items, "product_line_id", request.args.get("product_line_id"))
    items = filter_eq(items, "status", request.args.get("status"))
    items = filter_eq(items, "submitter_ref", request.args.get("submitter_ref"))
    page, pagination = paginate(items)
    return ok([usecase_json(u) for u in page], response_type="array", pagination=pagination)


@bp.get("/brand-ops/use-cases/<uid>")
def get_use_case(uid):
    authenticate()
    return ok(usecase_json(get_or_404("use_cases", uid, "use case")))


def _brand_of_use_case(uc):
    line = STORE["product_lines"].get(uc["product_line_id"])
    return STORE["brands"].get(line["brand_id"]) if line else None


@bp.post("/brand-ops/use-cases/<uid>/review")
def review_use_case(uid):
    _, role = authenticate()
    authorize(role, ["MarketingManager"])
    uc = get_or_404("use_cases", uid, "use case")
    b = body()
    decision = as_enum(need(b, "decision"), "decision", USECASE_DECISIONS)
    flag = as_bool(need(b, "generic_use_flag"), "generic_use_flag")
    if uc["status"] != "SUBMITTED":
        err("ERR_INVALID_STATE_TRANSITION", "Use case is not SUBMITTED")
    if decision == "VERIFY":
        uc["status"] = "VERIFIED"
        uc["generic_use_flag"] = flag
        touch(uc)
        brand = _brand_of_use_case(uc)
        if brand is not None:
            recompute_genericization(brand)
    else:
        uc["status"] = "REJECTED"
        touch(uc)
    return ok(usecase_json(uc))


@bp.post("/brand-ops/use-cases/<uid>/publish")
def publish_use_case(uid):
    _, role = authenticate()
    authorize(role, ["MarketingManager"])
    uc = get_or_404("use_cases", uid, "use case")
    body()
    if uc["status"] != "VERIFIED":
        err("ERR_INVALID_STATE_TRANSITION", "Use case is not VERIFIED")
    brand = _brand_of_use_case(uc)
    if uc["generic_use_flag"] and brand is not None and brand["genericization_risk_bps"] >= 500:
        err("ERR_GENERICIZATION_RISK", "Genericization risk has reached 500 bps")
    uc["status"] = "PUBLISHED"
    touch(uc)
    if brand is not None:
        recompute_genericization(brand)
    return ok(usecase_json(uc))


@bp.post("/brand-ops/use-cases/<uid>/retract")
def retract_use_case(uid):
    _, role = authenticate()
    authorize(role, ["MarketingManager"])
    uc = get_or_404("use_cases", uid, "use case")
    body()
    if uc["status"] != "PUBLISHED":
        err("ERR_INVALID_STATE_TRANSITION", "Use case is not PUBLISHED")
    uc["status"] = "RETRACTED"
    touch(uc)
    brand = _brand_of_use_case(uc)
    if brand is not None:
        recompute_genericization(brand)
    return ok(usecase_json(uc))
