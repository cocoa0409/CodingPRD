"""Markets and market registrations (PRD §3.4)."""
from flask import Blueprint, request

from core import (
    STORE, err, ok, stamp_new, touch, now, now_iso, parse_datetime, cmp_sec, fmt_dt,
)
from validate import (
    CHANNELS, VOC_REGIMES,
    as_datetime, as_enum, as_enum_list, as_bool, as_str, authenticate, authorize,
    body, filter_eq, get_or_404, need, paginate,
)

bp = Blueprint("markets", __name__)

MARKET_FIELDS = [
    "id", "country_code", "name", "registration_required", "voc_regime",
    "allowed_channels", "status", "created_at", "updated_at", "version",
]
REG_FIELDS = [
    "id", "market_id", "product_line_id", "formulation_id", "registration_number",
    "status", "expires_on", "revise_count", "submitted_at", "approved_at",
    "created_at", "updated_at", "version",
]

REG_NONTERMINAL = ("DRAFT", "SUBMITTED", "REJECTED", "ACTIVE", "RENEWAL_DUE")


def market_json(m):
    return {k: m.get(k) for k in MARKET_FIELDS}


def reg_json(r):
    return {k: r.get(k) for k in REG_FIELDS}


# ---------------------------------------------------------------------------
# Markets
# ---------------------------------------------------------------------------
@bp.post("/brand-ops/markets")
def create_market():
    _, role = authenticate()
    authorize(role, ["RegulatoryAffairs"])
    b = body()
    country = as_str(need(b, "country_code"), "country_code")
    name = as_str(need(b, "name"), "name")
    reg_required = as_bool(need(b, "registration_required"), "registration_required")
    voc = as_enum(need(b, "voc_regime"), "voc_regime", VOC_REGIMES)
    channels = as_enum_list(need(b, "allowed_channels"), "allowed_channels", CHANNELS)
    for other in STORE["markets"].values():
        if other["country_code"] == country:
            err("ERR_MARKET_CODE_EXISTS", "country_code already registered")
    market = stamp_new({
        "country_code": country,
        "name": name,
        "registration_required": reg_required,
        "voc_regime": voc,
        "allowed_channels": channels,
        "status": "OPEN",
    })
    STORE["markets"][market["id"]] = market
    return ok(market_json(market), code=201)


@bp.get("/brand-ops/markets/<mid>")
def get_market(mid):
    authenticate()
    return ok(market_json(get_or_404("markets", mid, "market")))


@bp.post("/brand-ops/markets/<mid>/close")
def close_market(mid):
    _, role = authenticate()
    authorize(role, ["RegulatoryAffairs"])
    market = get_or_404("markets", mid, "market")
    body()
    if market["status"] != "OPEN":
        err("ERR_INVALID_STATE_TRANSITION", "Market is not OPEN")
    for a in STORE["assignments"].values():
        if a["market_id"] == mid and a["status"] in ("PROPOSED", "ACTIVE", "SUSPENDED"):
            err("ERR_MARKET_IN_USE", "Market is referenced by a live coverage assignment")
    for r in STORE["registrations"].values():
        if r["market_id"] == mid and r["status"] in ("DRAFT", "SUBMITTED", "ACTIVE", "RENEWAL_DUE"):
            err("ERR_MARKET_IN_USE", "Market is referenced by a non-terminal registration")
    market["status"] = "CLOSED"
    touch(market)
    return ok(market_json(market))


# ---------------------------------------------------------------------------
# Market registrations
# ---------------------------------------------------------------------------
@bp.post("/brand-ops/market-registrations")
def create_registration():
    _, role = authenticate()
    authorize(role, ["RegulatoryAffairs"])
    b = body()
    market_id = as_str(need(b, "market_id"), "market_id")
    product_line_id = as_str(need(b, "product_line_id"), "product_line_id")
    formulation_id = as_str(need(b, "formulation_id"), "formulation_id")
    expires_on = as_datetime(need(b, "expires_on"), "expires_on")
    # 5: body references
    market = STORE["markets"].get(market_id)
    if market is None:
        err("ERR_INVALID_REFERENCE", "market_id does not exist")
    line = STORE["product_lines"].get(product_line_id)
    if line is None:
        err("ERR_INVALID_REFERENCE", "product_line_id does not exist")
    form = STORE["formulations"].get(formulation_id)
    if form is None:
        err("ERR_INVALID_REFERENCE", "formulation_id does not exist")
    # 9: VOC regime
    if market["voc_regime"] == "STRICT" and form["voc_class"] != "LOW_VOC":
        err("ERR_VOC_REGIME_MISMATCH", "STRICT markets accept only LOW_VOC formulations")
    # 10: expiry in the future
    if cmp_sec(expires_on, now()) <= 0:
        err("ERR_WINDOW_INVALID", "expires_on must be strictly after the current time")
    # 11: referential compatibility
    if market["status"] != "OPEN":
        err("ERR_MARKET_NOT_OPEN", "Market is not OPEN")
    if line["status"] not in ("PILOT", "LAUNCHED"):
        err("ERR_LINE_STAGE_TOO_EARLY", "Line must be PILOT or LAUNCHED")
    if form["product_line_id"] != product_line_id:
        err("ERR_FORMULATION_LINE_MISMATCH", "Formulation does not belong to the line")
    if form["status"] not in ("SEALED", "COMPARTMENTALIZED"):
        err("ERR_FORMULATION_NOT_SEALED", "Formulation is not SEALED or COMPARTMENTALIZED")
    # 12: one non-terminal registration per (market, line)
    for r in STORE["registrations"].values():
        if (
            r["market_id"] == market_id
            and r["product_line_id"] == product_line_id
            and r["status"] in REG_NONTERMINAL
        ):
            err("ERR_REGISTRATION_EXISTS", "A non-terminal registration already exists")
    reg = stamp_new({
        "market_id": market_id,
        "product_line_id": product_line_id,
        "formulation_id": formulation_id,
        "registration_number": None,
        "status": "DRAFT",
        "expires_on": fmt_dt(expires_on),
        "revise_count": 0,
        "submitted_at": None,
        "approved_at": None,
    })
    STORE["registrations"][reg["id"]] = reg
    return ok(reg_json(reg), code=201)


@bp.get("/brand-ops/market-registrations")
def list_registrations():
    authenticate()
    items = list(STORE["registrations"].values())
    items = filter_eq(items, "market_id", request.args.get("market_id"))
    items = filter_eq(items, "product_line_id", request.args.get("product_line_id"))
    items = filter_eq(items, "formulation_id", request.args.get("formulation_id"))
    items = filter_eq(items, "status", request.args.get("status"))
    page, pagination = paginate(items)
    return ok([reg_json(r) for r in page], response_type="array", pagination=pagination)


@bp.get("/brand-ops/market-registrations/<rid>")
def get_registration(rid):
    authenticate()
    return ok(reg_json(get_or_404("registrations", rid, "registration")))


def _owning_brand(reg):
    line = STORE["product_lines"].get(reg["product_line_id"])
    return STORE["brands"].get(line["brand_id"]) if line else None


@bp.post("/brand-ops/market-registrations/<rid>/submit")
def submit_registration(rid):
    _, role = authenticate()
    authorize(role, ["RegulatoryAffairs"])
    reg = get_or_404("registrations", rid, "registration")
    body()
    if reg["status"] != "DRAFT":
        err("ERR_INVALID_STATE_TRANSITION", "Registration is not DRAFT")
    brand = _owning_brand(reg)
    if brand is not None and brand["status"] != "OPERATING":
        err("ERR_BRAND_IN_LOCKDOWN", "Brand is in PROTECTIVE_LOCKDOWN")
    if brand is not None and brand["protection_posture"] == "CRITICAL":
        err("ERR_POSTURE_CRITICAL", "Brand protection posture is CRITICAL")
    reg["status"] = "SUBMITTED"
    reg["submitted_at"] = now_iso()
    touch(reg)
    return ok(reg_json(reg))


@bp.post("/brand-ops/market-registrations/<rid>/approve")
def approve_registration(rid):
    _, role = authenticate()
    authorize(role, ["RegulatoryAffairs"])
    reg = get_or_404("registrations", rid, "registration")
    b = body()
    reg_number = as_str(need(b, "registration_number"), "registration_number")
    if reg["status"] != "SUBMITTED":
        err("ERR_INVALID_STATE_TRANSITION", "Registration is not SUBMITTED")
    if cmp_sec(parse_datetime(reg["expires_on"]), now()) <= 0:
        err("ERR_WINDOW_INVALID", "expires_on is not strictly after the current time")
    reg["status"] = "ACTIVE"
    reg["registration_number"] = reg_number
    reg["approved_at"] = now_iso()
    touch(reg)
    return ok(reg_json(reg))


@bp.post("/brand-ops/market-registrations/<rid>/reject")
def reject_registration(rid):
    _, role = authenticate()
    authorize(role, ["RegulatoryAffairs"])
    reg = get_or_404("registrations", rid, "registration")
    b = body()
    as_str(need(b, "reason"), "reason")  # carried by the request; not stored
    if reg["status"] != "SUBMITTED":
        err("ERR_INVALID_STATE_TRANSITION", "Registration is not SUBMITTED")
    reg["status"] = "REJECTED"
    touch(reg)
    return ok(reg_json(reg))


@bp.post("/brand-ops/market-registrations/<rid>/revise")
def revise_registration(rid):
    _, role = authenticate()
    authorize(role, ["RegulatoryAffairs"])
    reg = get_or_404("registrations", rid, "registration")
    body()
    if reg["status"] != "REJECTED":
        err("ERR_INVALID_STATE_TRANSITION", "Registration is not REJECTED")
    reg["status"] = "DRAFT"
    reg["revise_count"] += 1
    touch(reg)
    return ok(reg_json(reg))


@bp.post("/brand-ops/market-registrations/<rid>/renew")
def renew_registration(rid):
    _, role = authenticate()
    authorize(role, ["RegulatoryAffairs"])
    reg = get_or_404("registrations", rid, "registration")
    b = body()
    new_expiry = as_datetime(need(b, "new_expires_on"), "new_expires_on")
    if reg["status"] == "ACTIVE":
        err("ERR_RENEWAL_WINDOW_NOT_OPEN", "Renewal window opens 90 days before expiry")
    if reg["status"] == "EXPIRED":
        err("ERR_REGISTRATION_EXPIRED", "Registration has expired")
    if reg["status"] != "RENEWAL_DUE":
        err("ERR_INVALID_STATE_TRANSITION", "Registration is not RENEWAL_DUE")
    if cmp_sec(new_expiry, parse_datetime(reg["expires_on"])) <= 0:
        err("ERR_WINDOW_INVALID", "new_expires_on must be strictly after expires_on")
    reg["expires_on"] = fmt_dt(new_expiry)
    reg["status"] = "ACTIVE"
    touch(reg)
    return ok(reg_json(reg))


@bp.post("/brand-ops/market-registrations/<rid>/revoke")
def revoke_registration(rid):
    _, role = authenticate()
    authorize(role, ["RegulatoryAffairs"])
    reg = get_or_404("registrations", rid, "registration")
    body()
    if reg["status"] not in ("ACTIVE", "RENEWAL_DUE"):
        err("ERR_INVALID_STATE_TRANSITION", "Registration is not ACTIVE or RENEWAL_DUE")
    reg["status"] = "REVOKED"
    touch(reg)
    for a in STORE["assignments"].values():
        if (
            a["market_id"] == reg["market_id"]
            and a["product_line_id"] == reg["product_line_id"]
            and a["status"] == "ACTIVE"
        ):
            a["status"] = "SUSPENDED"
            touch(a)
    return ok(reg_json(reg))
