"""Product catalog items and score tier thresholds."""

from flask import Blueprint, request

import store
import models
import helpers
import analytics
from auth import require
from envelope import ok, ok_list, limited
from errors import fail

bp = Blueprint("catalog", __name__)

READ_ROLES = ["Consumer", "LenderOps", "Referee", "ComplianceOfficer", "PlatformAdmin"]
PRODUCT_KINDS = ("CARD", "LOAN", "INSURANCE")
TIER_CODES = ("EXCEPTIONAL", "VERY_GOOD", "GOOD", "FAIR", "POOR")

NEGATIVE_FACTORS = ("too_many", "high", "recent", "short", "insufficient",
                    "late", "past", "missed", "derogatory", "inquiry",
                    "delinquen", "collection", "balance", "few", "no_")


def factor_descriptor(code):
    """Derive a stable (direction, impact_points) pair from a factor code."""
    lowered = code.lower()
    negative = any(token in lowered for token in NEGATIVE_FACTORS)
    magnitude = (sum(ord(ch) for ch in lowered) % 26) + 5
    if negative:
        return "DOWN", -magnitude
    return "UP", magnitude


def register_factor_catalog(codes):
    for code in codes or []:
        store.FACTOR_TABLE[code] = factor_descriptor(code)


@bp.route("/catalog/items", methods=["POST"])
def create_item():
    require(["PlatformAdmin"])
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST", "A JSON object body is required.")
    kind = data.get("product_kind")
    if kind not in PRODUCT_KINDS:
        fail("ERR_INVALID_REQUEST", "product_kind must be CARD, LOAN or INSURANCE.")
    try:
        min_score = int(data["min_score"])
        max_score = int(data["max_score"])
        max_dti = float(data["max_dti_pct"])
    except (KeyError, TypeError, ValueError):
        fail("ERR_INVALID_REQUEST", "min_score, max_score and max_dti_pct are required.")
    row = store.make_row({
        "product_kind": kind,
        "product_name": str(data.get("product_name") or ""),
        "min_score": min_score,
        "max_score": max_score,
        "max_dti_pct": max_dti,
        "status": "DRAFT",
    })
    store.product_catalog_items[row["id"]] = row
    return ok(models.catalog_item(row), store.now(), 201)


@bp.route("/catalog/items", methods=["GET"])
def list_items():
    require(READ_ROLES)
    rows = list(store.product_catalog_items.values())
    kind = request.args.get("product_kind")
    if kind:
        rows = [r for r in rows if r["product_kind"] == kind]
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    window, pagination = limited(rows, request.args)
    return ok_list([models.catalog_item(r) for r in window], store.now(), pagination)


def _derived_view(item, card_balance_cents):
    face, revenue = analytics.face_value_vs_revenue(item["id"])
    prog = analytics.first_program_of_item(item["id"])
    months, variant = analytics.fee_breakeven_months(prog, card_balance_cents)
    payload = models.catalog_item(item)
    payload.update({
        "face_value_cents": face,
        "platform_revenue_cents": revenue,
        "fee_breakeven_months": months,
        "breakeven_variant": variant,
    })
    payload.update(analytics.calibration_index(item["id"], "including_provisional"))
    return payload


@bp.route("/catalog/items/<iid>", methods=["GET"])
def get_item(iid):
    require(READ_ROLES)
    row = helpers.catalog_item(iid)
    raw_balance = request.args.get("card_balance_cents")
    balance = None
    if raw_balance not in (None, ""):
        try:
            balance = int(raw_balance)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "card_balance_cents must be an integer.")
    return ok(_derived_view(row, balance), store.now())


@bp.route("/catalog/items/<iid>/settled-index", methods=["GET"])
def settled_index(iid):
    require(["ComplianceOfficer", "PlatformAdmin"])
    row = helpers.catalog_item(iid)
    payload = {"id": row["id"], "product_kind": row["product_kind"]}
    payload.update(analytics.calibration_index(row["id"], "settled_only"))
    return ok(payload, store.now())


@bp.route("/catalog/items/<iid>/activate", methods=["POST"])
def activate_item(iid):
    require(["PlatformAdmin"])
    row = helpers.catalog_item(iid)
    if row["status"] != "DRAFT":
        fail("ERR_INVALID_STATE_TRANSITION", "Only a DRAFT item may be activated.")
    intersects = False
    for tier in store.score_tiers.values():
        if tier["status"] != "ACTIVE":
            continue
        if tier["min_score"] <= row["max_score"] and tier["max_score"] >= row["min_score"]:
            intersects = True
            break
    if not intersects:
        fail("ERR_ITEM_NO_SCORE_TIER")
    row["status"] = "ACTIVE"
    models.touch(row)
    return ok(models.catalog_item(row), store.now())


@bp.route("/catalog/items/<iid>/retire", methods=["POST"])
def retire_item(iid):
    require(["PlatformAdmin"])
    row = helpers.catalog_item(iid)
    if row["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE_TRANSITION", "Only an ACTIVE item may be retired.")
    for prog in store.lender_programs.values():
        if prog["product_catalog_item_id"] == iid and prog["status"] == "ACTIVE":
            fail("ERR_ITEM_HAS_ACTIVE_PROGRAM")
    row["status"] = "RETIRED"
    models.touch(row)
    return ok(models.catalog_item(row), store.now())


@bp.route("/catalog/items/<iid>/lender-programs", methods=["GET"])
def item_programs(iid):
    require(READ_ROLES)
    helpers.catalog_item(iid)
    rows = [p for p in store.lender_programs.values()
            if p["product_catalog_item_id"] == iid]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    window, pagination = limited(rows, request.args)
    return ok_list([models.program(r) for r in window], store.now(), pagination)


# ---------------------------------------------------------------------------
# Score tiers
# ---------------------------------------------------------------------------
@bp.route("/score-tiers", methods=["POST"])
def create_tier():
    require(["PlatformAdmin"])
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST", "A JSON object body is required.")
    code = data.get("tier_code")
    if code not in TIER_CODES:
        fail("ERR_INVALID_REQUEST", "tier_code is not a declared tier.")
    try:
        min_score = int(data["min_score"])
        max_score = int(data["max_score"])
    except (KeyError, TypeError, ValueError):
        fail("ERR_INVALID_REQUEST", "min_score and max_score are required.")
    catalog = data.get("factor_catalog")
    if not isinstance(catalog, list):
        fail("ERR_INVALID_REQUEST", "factor_catalog must be an array.")
    row = store.make_row({
        "tier_code": code,
        "min_score": min_score,
        "max_score": max_score,
        "factor_catalog": [str(c).lower() for c in catalog],
        "status": "DRAFT",
    })
    register_factor_catalog(row["factor_catalog"])
    store.score_tiers[row["id"]] = row
    return ok(models.tier(row), store.now(), 201)


@bp.route("/score-tiers", methods=["GET"])
def list_tiers():
    require(["Consumer", "Referee", "ComplianceOfficer", "PlatformAdmin"])
    rows = list(store.score_tiers.values())
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    window, pagination = limited(rows, request.args)
    return ok_list([models.tier(r) for r in window], store.now(), pagination)


@bp.route("/score-tiers/<tid>/activate", methods=["POST"])
def activate_tier(tid):
    require(["PlatformAdmin"])
    row = helpers.tier(tid)
    if row["status"] != "DRAFT":
        fail("ERR_INVALID_STATE_TRANSITION", "Only a DRAFT tier may be activated.")
    for other in store.score_tiers.values():
        if other["id"] == tid or other["status"] != "ACTIVE":
            continue
        if other["tier_code"] == row["tier_code"]:
            fail("ERR_TIER_CODE_DUPLICATE")
        if row["min_score"] <= other["max_score"] and row["max_score"] >= other["min_score"]:
            fail("ERR_TIER_BAND_OVERLAP")
    row["status"] = "ACTIVE"
    register_factor_catalog(row["factor_catalog"])
    models.touch(row)
    return ok(models.tier(row), store.now())


@bp.route("/score-tiers/<tid>/retire", methods=["POST"])
def retire_tier(tid):
    require(["PlatformAdmin"])
    row = helpers.tier(tid)
    if row["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE_TRANSITION", "Only an ACTIVE tier may be retired.")
    row["status"] = "RETIRED"
    models.touch(row)
    return ok(models.tier(row), store.now())