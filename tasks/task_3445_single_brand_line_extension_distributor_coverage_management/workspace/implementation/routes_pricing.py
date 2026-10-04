"""Pack formats, channel price lists, effective price (PRD §3.7)."""
from flask import Blueprint, request

from core import (
    STORE, err, ok, stamp_new, touch, now, parse_datetime, cmp_sec, fmt_dt,
)
from derived import resolve_price_list, secs
from validate import (
    CHANNELS, DELIVERY_SYSTEMS,
    as_datetime, as_enum, as_enum_list, as_int, authenticate, authorize, body,
    filter_eq, get_or_404, need, opt_int, paginate,
)

bp = Blueprint("pricing", __name__)

PACK_FIELDS = [
    "id", "product_line_id", "size_ml", "delivery_system", "channel_restrictions",
    "case_pack_qty", "status", "created_at", "updated_at", "version",
]
PRICE_FIELDS = [
    "id", "pack_format_id", "channel", "list_price_cents", "map_price_cents",
    "effective_from", "effective_to", "status", "created_at", "updated_at", "version",
]


def pack_json(p):
    return {k: p.get(k) for k in PACK_FIELDS}


def price_json(pl):
    return {k: pl.get(k) for k in PRICE_FIELDS}


# ---------------------------------------------------------------------------
# Pack formats
# ---------------------------------------------------------------------------
@bp.post("/brand-ops/product-lines/<lineId>/pack-formats")
def create_pack(lineId):
    _, role = authenticate()
    authorize(role, ["SupplyPlanner"])
    line = get_or_404("product_lines", lineId, "product line")
    b = body()
    size = as_int(need(b, "size_ml"), "size_ml", minimum=1)
    system = as_enum(need(b, "delivery_system"), "delivery_system", DELIVERY_SYSTEMS)
    restrictions = as_enum_list(
        need(b, "channel_restrictions"), "channel_restrictions", CHANNELS)
    case_qty = opt_int(b, "case_pack_qty", 1, minimum=1)
    if not set(restrictions) <= set(line["target_channels"]):
        err("ERR_CHANNEL_OUTSIDE_LINE_SCOPE",
            "channel_restrictions must be a subset of the line's target_channels")
    pack = stamp_new({
        "product_line_id": line["id"],
        "size_ml": size,
        "delivery_system": system,
        "channel_restrictions": restrictions,
        "case_pack_qty": case_qty,
        "status": "DESIGNED",
    })
    STORE["packs"][pack["id"]] = pack
    return ok(pack_json(pack), code=201)


@bp.get("/brand-ops/pack-formats")
def list_packs():
    authenticate()
    items = list(STORE["packs"].values())
    items = filter_eq(items, "product_line_id", request.args.get("product_line_id"))
    items = filter_eq(items, "status", request.args.get("status"))
    page, pagination = paginate(items)
    return ok([pack_json(p) for p in page], response_type="array", pagination=pagination)


@bp.get("/brand-ops/pack-formats/<pid>")
def get_pack(pid):
    authenticate()
    return ok(pack_json(get_or_404("packs", pid, "pack format")))


@bp.post("/brand-ops/pack-formats/<pid>/tool")
def tool_pack(pid):
    _, role = authenticate()
    authorize(role, ["SupplyPlanner"])
    pack = get_or_404("packs", pid, "pack format")
    body()
    if pack["status"] != "DESIGNED":
        err("ERR_INVALID_STATE_TRANSITION", "Pack is not DESIGNED")
    line = STORE["product_lines"].get(pack["product_line_id"])
    if line is None or line["status"] not in ("PILOT", "LAUNCHED"):
        err("ERR_LINE_STAGE_TOO_EARLY", "Line must be PILOT or LAUNCHED")
    pack["status"] = "TOOLED"
    touch(pack)
    return ok(pack_json(pack))


@bp.post("/brand-ops/pack-formats/<pid>/enter-production")
def enter_production(pid):
    _, role = authenticate()
    authorize(role, ["SupplyPlanner"])
    pack = get_or_404("packs", pid, "pack format")
    body()
    if pack["status"] != "TOOLED":
        err("ERR_INVALID_STATE_TRANSITION", "Pack is not TOOLED")
    compartmentalized = any(
        f["product_line_id"] == pack["product_line_id"] and f["status"] == "COMPARTMENTALIZED"
        for f in STORE["formulations"].values()
    )
    if not compartmentalized:
        err("ERR_FORMULATION_NOT_COMPARTMENTALIZED",
            "No COMPARTMENTALIZED formulation on the line")
    priced = any(
        pl["pack_format_id"] == pid and pl["status"] in ("SCHEDULED", "EFFECTIVE")
        for pl in STORE["price_lists"].values()
    )
    if not priced:
        err("ERR_NO_PRICE_LIST", "No SCHEDULED or EFFECTIVE price list for the pack")
    pack["status"] = "IN_PRODUCTION"
    touch(pack)
    return ok(pack_json(pack))


@bp.post("/brand-ops/pack-formats/<pid>/retire")
def retire_pack(pid):
    _, role = authenticate()
    authorize(role, ["SupplyPlanner"])
    pack = get_or_404("packs", pid, "pack format")
    body()
    if pack["status"] != "IN_PRODUCTION":
        err("ERR_INVALID_STATE_TRANSITION", "Pack is not IN_PRODUCTION")
    outstanding = any(
        pl["pack_format_id"] == pid and pl["status"] in ("SCHEDULED", "EFFECTIVE")
        for pl in STORE["price_lists"].values()
    )
    if outstanding:
        err("ERR_PRICE_LISTS_OUTSTANDING", "Pack has non-terminal price lists")
    pack["status"] = "RETIRED"
    touch(pack)
    return ok(pack_json(pack))


# ---------------------------------------------------------------------------
# Channel price lists
# ---------------------------------------------------------------------------
@bp.post("/brand-ops/pack-formats/<packFormatId>/price-lists")
def create_price_list(packFormatId):
    _, role = authenticate()
    authorize(role, ["PricingAnalyst"])
    pack = get_or_404("packs", packFormatId, "pack format")
    b = body()
    channel = as_enum(need(b, "channel"), "channel", CHANNELS)
    list_price = as_int(need(b, "list_price_cents"), "list_price_cents", minimum=1)
    map_price = as_int(need(b, "map_price_cents"), "map_price_cents", minimum=1)
    effective_from = as_datetime(need(b, "effective_from"), "effective_from")
    effective_to = as_datetime(need(b, "effective_to"), "effective_to")
    expected = as_int(need(b, "expected_pack_format_version"), "expected_pack_format_version")
    # 7: OCC on the parent pack format
    if expected != pack["version"]:
        err("ERR_STALE_VERSION", "Pack format version is stale")
    # 10: window well-ordered and not entirely past
    cur = now()
    if cmp_sec(effective_from, effective_to) >= 0:
        err("ERR_WINDOW_INVALID", "effective_from must be strictly before effective_to")
    if cmp_sec(effective_to, cur) <= 0:
        err("ERR_WINDOW_INVALID", "The window is entirely in the past")
    # 12: channel membership + map floor
    if channel not in pack["channel_restrictions"]:
        err("ERR_CHANNEL_NOT_ALLOWED", "Channel is outside the pack's channel_restrictions")
    if map_price > list_price:
        err("ERR_MAP_ABOVE_LIST", "map_price_cents exceeds list_price_cents")
    # Initial status from the current logical time
    status = (
        "EFFECTIVE"
        if cmp_sec(effective_from, cur) <= 0 and cmp_sec(cur, effective_to) < 0
        else "SCHEDULED"
    )
    new_ef, new_et = secs(effective_from), secs(effective_to)
    # Reconcile incumbents on the same (pack, channel): touch ok, overlap not
    for other in STORE["price_lists"].values():
        if other["pack_format_id"] != packFormatId or other["channel"] != channel:
            continue
        if other["status"] not in ("SCHEDULED", "EFFECTIVE"):
            continue
        old_ef = secs(parse_datetime(other["effective_from"]))
        old_et = secs(parse_datetime(other["effective_to"]))
        overlaps = new_ef < old_et and old_ef < new_et  # half-open intervals
        if not overlaps:
            continue
        if other["status"] == "SCHEDULED":
            other["status"] = "SUPERSEDED"
            touch(other)
        else:  # EFFECTIVE
            if new_ef <= old_ef:
                other["status"] = "SUPERSEDED"
                touch(other)
            else:
                other["effective_to"] = fmt_dt(effective_from)  # clip
                touch(other)
    pl = stamp_new({
        "pack_format_id": packFormatId,
        "channel": channel,
        "list_price_cents": list_price,
        "map_price_cents": map_price,
        "effective_from": fmt_dt(effective_from),
        "effective_to": fmt_dt(effective_to),
        "status": status,
    })
    STORE["price_lists"][pl["id"]] = pl
    touch(pack)  # OCC: successful create increments the pack format's version
    return ok(price_json(pl), code=201)


@bp.get("/brand-ops/price-lists")
def list_price_lists():
    authenticate()
    items = list(STORE["price_lists"].values())
    items = filter_eq(items, "pack_format_id", request.args.get("pack_format_id"))
    items = filter_eq(items, "channel", request.args.get("channel"))
    items = filter_eq(items, "status", request.args.get("status"))
    page, pagination = paginate(items)
    return ok([price_json(pl) for pl in page], response_type="array", pagination=pagination)


@bp.get("/brand-ops/price-lists/<pid>")
def get_price_list(pid):
    authenticate()
    return ok(price_json(get_or_404("price_lists", pid, "price list")))


@bp.get("/brand-ops/pack-formats/<pid>/effective-price")
def effective_price(pid):
    authenticate()
    pack = get_or_404("packs", pid, "pack format")
    raw_channel = request.args.get("channel")
    if raw_channel is None:
        err("ERR_INVALID_REQUEST", "channel query parameter is required")
    channel = as_enum(raw_channel, "channel", CHANNELS)
    raw_at = request.args.get("at")
    at = now()
    if raw_at is not None:
        at = as_datetime(raw_at, "at")
    winner = resolve_price_list(pack["id"], channel, at)
    if winner is None:
        err("ERR_NO_EFFECTIVE_PRICE", "No price list governs this pack and channel at the instant")
    return ok({
        "price_list_id": winner["id"],
        "channel": winner["channel"],
        "list_price_cents": winner["list_price_cents"],
        "map_price_cents": winner["map_price_cents"],
        "effective_from": winner["effective_from"],
        "effective_to": winner["effective_to"],
    })
