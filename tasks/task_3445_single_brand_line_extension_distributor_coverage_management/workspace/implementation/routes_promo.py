"""Promotions and redemptions (PRD §3.8)."""
from datetime import datetime, timezone
from decimal import Decimal

from flask import Blueprint, request

from core import (
    STORE, err, ok, stamp_new, touch, new_id, now, parse_datetime, pct_of, today,
)
from derived import resolve_price_list, secs
from validate import (
    CHANNELS,
    as_date, as_discount_pct, as_enum, as_int, as_str, authenticate, authorize,
    body, filter_eq, get_or_404, need, paginate,
)

bp = Blueprint("promo", __name__)

PROMO_FIELDS = [
    "id", "product_line_id", "channel", "discount_pct", "starts_on", "ends_on",
    "funding_budget_cents", "accrued_funding_cents", "redemptions_count",
    "unit_funding_provisional_cents", "status", "created_by_user_id",
    "approved_by_user_id", "created_at", "updated_at", "version",
]

DEPTH_CAPS = {"NORMAL": Decimal("25.00"), "ELEVATED": Decimal("15.00"), "CRITICAL": Decimal("5.00")}
PEER_STATUSES = ("APPROVED", "LIVE", "SUSPENDED", "ENDED")


def promo_json(p):
    return {k: p.get(k) for k in PROMO_FIELDS}


def _midnight(date_str):
    return parse_datetime(date_str + "T00:00:00Z")


def _covering_lists(pack_id, channel, at):
    out = []
    at_s = secs(at)
    for pl in STORE["price_lists"].values():
        if pl["pack_format_id"] != pack_id or pl["channel"] != channel:
            continue
        if pl["status"] == "SUPERSEDED":
            continue
        ef = secs(parse_datetime(pl["effective_from"]))
        et = secs(parse_datetime(pl["effective_to"]))
        if ef <= at_s < et:
            out.append(pl)
    return out


# ---------------------------------------------------------------------------
# Promotions
# ---------------------------------------------------------------------------
@bp.post("/brand-ops/promotions")
def create_promotion():
    user_id, role = authenticate()
    authorize(role, ["PricingAnalyst"])
    b = body()
    product_line_id = as_str(need(b, "product_line_id"), "product_line_id")
    channel = as_enum(need(b, "channel"), "channel", CHANNELS)
    discount = as_discount_pct(need(b, "discount_pct"))
    starts_on = as_date(need(b, "starts_on"), "starts_on")
    ends_on = as_date(need(b, "ends_on"), "ends_on")
    budget = as_int(need(b, "funding_budget_cents"), "funding_budget_cents", minimum=1)
    # 5: body reference
    line = STORE["product_lines"].get(product_line_id)
    if line is None:
        err("ERR_INVALID_REFERENCE", "product_line_id does not exist")
    # 10: window well-ordered and not entirely past
    if ends_on < starts_on:
        err("ERR_WINDOW_INVALID", "ends_on must not precede starts_on")
    if ends_on < today():
        err("ERR_WINDOW_INVALID", "The promotion window is entirely past")
    # 11: line stage
    if line["status"] not in ("PILOT", "LAUNCHED"):
        err("ERR_LINE_STAGE_TOO_EARLY", "Line must be PILOT or LAUNCHED")
    # 12: channel inside line scope
    if channel not in line["target_channels"]:
        err("ERR_CHANNEL_OUTSIDE_LINE_SCOPE", "Channel is outside the line's target channels")
    promo = stamp_new({
        "product_line_id": product_line_id,
        "channel": channel,
        "discount_pct": discount,
        "starts_on": b["starts_on"],
        "ends_on": b["ends_on"],
        "funding_budget_cents": budget,
        "accrued_funding_cents": 0,
        "redemptions_count": 0,
        "unit_funding_provisional_cents": None,
        "status": "DRAFT",
        "created_by_user_id": user_id,
        "approved_by_user_id": None,
    })
    STORE["promotions"][promo["id"]] = promo
    return ok(promo_json(promo), code=201)


@bp.get("/brand-ops/promotions")
def list_promotions():
    authenticate()
    items = list(STORE["promotions"].values())
    items = filter_eq(items, "product_line_id", request.args.get("product_line_id"))
    items = filter_eq(items, "channel", request.args.get("channel"))
    items = filter_eq(items, "status", request.args.get("status"))
    page, pagination = paginate(items)
    return ok([promo_json(p) for p in page], response_type="array", pagination=pagination)


@bp.get("/brand-ops/promotions/<pid>")
def get_promotion(pid):
    authenticate()
    return ok(promo_json(get_or_404("promotions", pid, "promotion")))


@bp.post("/brand-ops/promotions/<pid>/submit")
def submit_promotion(pid):
    _, role = authenticate()
    authorize(role, ["PricingAnalyst"])
    promo = get_or_404("promotions", pid, "promotion")
    body()
    if promo["status"] != "DRAFT":
        err("ERR_INVALID_STATE_TRANSITION", "Promotion is not DRAFT")
    promo["status"] = "PENDING_APPROVAL"
    touch(promo)
    return ok(promo_json(promo))


@bp.post("/brand-ops/promotions/<pid>/approve")
def approve_promotion(pid):
    user_id, role = authenticate()
    authorize(role, ["MarketingManager"])
    promo = get_or_404("promotions", pid, "promotion")
    body()
    if promo["status"] != "PENDING_APPROVAL":
        err("ERR_INVALID_STATE_TRANSITION", "Promotion is not PENDING_APPROVAL")
    # 9: segregation of duties
    if user_id == promo["created_by_user_id"]:
        err("ERR_SEGREGATION_OF_DUTIES", "Approver must differ from the creator")
    line = STORE["product_lines"].get(promo["product_line_id"])
    brand = STORE["brands"].get(line["brand_id"]) if line else None
    pct = Decimal(str(promo["discount_pct"]))
    # 13 (fiscal, in order): depth cap -> price support -> MAP floor -> frequency -> gap
    posture = brand["protection_posture"] if brand else "NORMAL"
    if pct > DEPTH_CAPS[posture]:
        err("ERR_PROMO_DEPTH_EXCEEDS_CAP", "discount_pct exceeds the posture depth cap")
    starts_midnight = _midnight(promo["starts_on"])
    packs = [p for p in STORE["packs"].values() if p["product_line_id"] == promo["product_line_id"]]
    covering = []  # (pack, price list) pairs covering starts_on
    for pack in packs:
        for pl in _covering_lists(pack["id"], promo["channel"], starts_midnight):
            covering.append((pack, pl))
    if not covering:
        err("ERR_NO_PRICE_LIST", "No price list covers the promotion channel at starts_on")
    for _, pl in covering:
        unit_discount = pct_of(pl["list_price_cents"], promo["discount_pct"])
        if pl["list_price_cents"] - unit_discount < pl["map_price_cents"]:
            err("ERR_BELOW_MAP_PRICE", "Promotional price would undercut the MAP floor")
    peers = [
        p for p in STORE["promotions"].values()
        if p["id"] != promo["id"]
        and p["product_line_id"] == promo["product_line_id"]
        and p["channel"] == promo["channel"]
        and p["status"] in PEER_STATUSES
    ]
    cand_start = datetime.strptime(promo["starts_on"], "%Y-%m-%d").date()
    near = 0
    for peer in peers:
        peer_start = datetime.strptime(peer["starts_on"], "%Y-%m-%d").date()
        if abs((peer_start - cand_start).days) <= 90:
            near += 1
    if near >= 2:
        err("ERR_PROMO_TOO_FREQUENT", "Too many peer promotions within +/- 90 days")
    for peer in peers:
        peer_start = datetime.strptime(peer["starts_on"], "%Y-%m-%d").date()
        if abs((peer_start - cand_start).days) < 14:
            err("ERR_PROMO_GAP_VIOLATION", "A peer promotion starts less than 14 days away")
    # Provisional unit funding: smallest pack with a covering list, earliest created
    ref_pack = sorted(
        {pack["id"]: pack for pack, _ in covering}.values(),
        key=lambda p: (p["size_ml"], p["created_at"], p["_seq"]),
    )[0]
    ref_list = resolve_price_list(ref_pack["id"], promo["channel"], starts_midnight)
    promo["unit_funding_provisional_cents"] = pct_of(
        ref_list["list_price_cents"], promo["discount_pct"])
    promo["approved_by_user_id"] = user_id
    cur = today()
    if _d(promo["starts_on"]) <= cur <= _d(promo["ends_on"]):
        promo["status"] = "LIVE"
    else:
        promo["status"] = "APPROVED"
    touch(promo)
    return ok(promo_json(promo))


def _d(s):
    return datetime.strptime(s, "%Y-%m-%d").date()


@bp.post("/brand-ops/promotions/<pid>/resume")
def resume_promotion(pid):
    _, role = authenticate()
    authorize(role, ["MarketingManager"])
    promo = get_or_404("promotions", pid, "promotion")
    body()
    if promo["status"] != "SUSPENDED":
        err("ERR_INVALID_STATE_TRANSITION", "Promotion is not SUSPENDED")
    # 8: dedicated wrong-state window error; then 9: posture / lockdown
    if today() > _d(promo["ends_on"]):
        err("ERR_PROMO_WINDOW_CLOSED", "The promotion window has closed")
    line = STORE["product_lines"].get(promo["product_line_id"])
    brand = STORE["brands"].get(line["brand_id"]) if line else None
    if brand is not None and brand["protection_posture"] == "CRITICAL":
        err("ERR_POSTURE_CRITICAL", "Brand protection posture is CRITICAL")
    if brand is not None and brand["status"] != "OPERATING":
        err("ERR_BRAND_IN_LOCKDOWN", "Brand is in PROTECTIVE_LOCKDOWN")
    promo["status"] = "LIVE"
    touch(promo)
    return ok(promo_json(promo))


@bp.post("/brand-ops/promotions/<pid>/redemptions")
def redeem_promotion(pid):
    _, role = authenticate()
    authorize(role, ["ChannelManager"])
    promo = get_or_404("promotions", pid, "promotion")
    b = body()
    pack_format_id = as_str(need(b, "pack_format_id"), "pack_format_id")
    units = as_int(need(b, "units"), "units", minimum=1)
    # 5: body reference
    pack = STORE["packs"].get(pack_format_id)
    if pack is None:
        err("ERR_INVALID_REFERENCE", "pack_format_id does not exist")
    # 8: promotion must be LIVE
    if promo["status"] != "LIVE":
        err("ERR_INVALID_STATE_TRANSITION", "Promotion is not LIVE")
    # 11: pack belongs to the promotion's line; an EFFECTIVE list must resolve
    if pack["product_line_id"] != promo["product_line_id"]:
        err("ERR_PACK_LINE_MISMATCH", "Pack does not belong to the promotion's line")
    pl = resolve_price_list(pack["id"], promo["channel"], now())
    if pl is None:
        err("ERR_NO_EFFECTIVE_PRICE", "No EFFECTIVE price list for the pack and channel")
    # ACTUAL unit funding, rounded once at unit level before case multiplication
    unit_funding = pct_of(pl["list_price_cents"], promo["discount_pct"])
    promo_unit = pl["list_price_cents"] - unit_funding
    promo_case = promo_unit * pack["case_pack_qty"]
    total = unit_funding * units
    # 13: funding budget
    if promo["accrued_funding_cents"] + total > promo["funding_budget_cents"]:
        err("ERR_PROMO_BUDGET_EXCEEDED", "Redemption would exceed the funding budget")
    promo["accrued_funding_cents"] += total
    promo["redemptions_count"] += 1
    touch(promo)
    return ok({
        "redemption_id": new_id(),
        "unit_funding_cents": unit_funding,
        "promo_unit_price_cents": promo_unit,
        "promo_case_price_cents": promo_case,
        "total_funding_cents": total,
        "accrued_funding_cents": promo["accrued_funding_cents"],
        "remaining_budget_cents": promo["funding_budget_cents"] - promo["accrued_funding_cents"],
    })
