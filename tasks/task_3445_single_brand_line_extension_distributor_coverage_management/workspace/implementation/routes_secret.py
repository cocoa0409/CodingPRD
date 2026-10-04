"""Formulations, contract manufacturers, confidentiality grants (PRD §3.3)."""
from datetime import timedelta

from flask import Blueprint, request

from core import (
    STORE, err, ok, stamp_new, touch, now, now_iso, parse_datetime, cmp_sec,
)
from derived import (
    recompute_disclosed_count, recompute_posture, reeval_formulation_coverage, secs,
)
from validate import (
    CAPABILITIES, GRANT_REASONS, VOC_CLASSES,
    as_bool, as_datetime, as_enum, as_enum_list, as_str, as_str_list, authenticate,
    authorize, body, filter_eq, get_or_404, need, paginate,
)

bp = Blueprint("secret", __name__)

FORM_FIELDS = [
    "id", "product_line_id", "version_label", "master_formulation_id",
    "component_codes", "voc_class", "status", "sealed_at",
    "created_at", "updated_at", "version",
]
MFR_FIELDS = [
    "id", "legal_name", "site_country", "capabilities", "sponsoring_officer_id",
    "status", "suspended_at", "disclosed_component_count",
    "created_at", "updated_at", "version",
]
GRANT_FIELDS = [
    "id", "manufacturer_id", "formulation_id", "component_scope", "grant_reason",
    "expires_on", "status", "granted_by_user_id", "revoked_for_cause", "revoked_at",
    "created_at", "updated_at", "version",
]


def form_json(f):
    return {k: f.get(k) for k in FORM_FIELDS}


def mfr_json(m):
    return {k: m.get(k) for k in MFR_FIELDS}


def grant_json(g):
    return {k: g.get(k) for k in GRANT_FIELDS}


# ---------------------------------------------------------------------------
# Formulations
# ---------------------------------------------------------------------------
@bp.post("/brand-ops/product-lines/<lineId>/formulations")
def create_formulation(lineId):
    _, role = authenticate()
    authorize(role, ["TradeSecretOfficer"])
    line = get_or_404("product_lines", lineId, "product line")
    b = body()
    version_label = as_str(need(b, "version_label"), "version_label")
    components = as_str_list(need(b, "component_codes"), "component_codes")
    voc = as_enum(need(b, "voc_class"), "voc_class", VOC_CLASSES)
    master = b.get("master_formulation_id")
    if master is not None:
        as_str(master, "master_formulation_id")
        if master not in STORE["formulations"]:
            err("ERR_INVALID_REFERENCE", "master_formulation_id does not exist")
    if len(components) > 12:
        err("ERR_COMPONENT_LIMIT_EXCEEDED", "component_codes exceeds 12 entries")
    form = stamp_new({
        "product_line_id": line["id"],
        "version_label": version_label,
        "master_formulation_id": master,
        "component_codes": components,
        "voc_class": voc,
        "status": "DRAFT",
        "sealed_at": None,
    })
    STORE["formulations"][form["id"]] = form
    return ok(form_json(form), code=201)


@bp.get("/brand-ops/formulations")
def list_formulations():
    authenticate()
    items = list(STORE["formulations"].values())
    items = filter_eq(items, "product_line_id", request.args.get("product_line_id"))
    items = filter_eq(items, "master_formulation_id", request.args.get("master_formulation_id"))
    items = filter_eq(items, "status", request.args.get("status"))
    page, pagination = paginate(items)
    return ok([form_json(f) for f in page], response_type="array", pagination=pagination)


@bp.get("/brand-ops/formulations/<fid>")
def get_formulation(fid):
    authenticate()
    return ok(form_json(get_or_404("formulations", fid, "formulation")))


@bp.post("/brand-ops/formulations/<fid>/seal")
def seal_formulation(fid):
    _, role = authenticate()
    authorize(role, ["TradeSecretOfficer"])
    form = get_or_404("formulations", fid, "formulation")
    body()
    if form["status"] != "DRAFT":
        err("ERR_INVALID_STATE_TRANSITION", "Formulation is not DRAFT")
    if len(form["component_codes"]) < 3:
        err("ERR_INSUFFICIENT_COMPONENTS", "Sealing requires at least 3 component codes")
    form["status"] = "SEALED"
    form["sealed_at"] = now_iso()
    touch(form)
    return ok(form_json(form))


# ---------------------------------------------------------------------------
# Contract manufacturers
# ---------------------------------------------------------------------------
@bp.post("/brand-ops/contract-manufacturers")
def create_manufacturer():
    user_id, role = authenticate()
    authorize(role, ["TradeSecretOfficer"])
    b = body()
    legal = as_str(need(b, "legal_name"), "legal_name")
    country = as_str(need(b, "site_country"), "site_country")
    caps = as_enum_list(need(b, "capabilities"), "capabilities", CAPABILITIES)
    mfr = stamp_new({
        "legal_name": legal,
        "site_country": country,
        "capabilities": caps,
        "sponsoring_officer_id": user_id,
        "status": "VETTING",
        "suspended_at": None,
        "disclosed_component_count": 0,
    })
    STORE["manufacturers"][mfr["id"]] = mfr
    return ok(mfr_json(mfr), code=201)


@bp.get("/brand-ops/contract-manufacturers/<mid>")
def get_manufacturer(mid):
    authenticate()
    return ok(mfr_json(get_or_404("manufacturers", mid, "manufacturer")))


@bp.post("/brand-ops/contract-manufacturers/<mid>/qualify")
def qualify_manufacturer(mid):
    _, role = authenticate()
    authorize(role, ["TradeSecretOfficer"])
    mfr = get_or_404("manufacturers", mid, "manufacturer")
    body()
    if mfr["status"] not in ("VETTING", "SUSPENDED"):
        err("ERR_INVALID_STATE_TRANSITION", "Manufacturer cannot be qualified from %s" % mfr["status"])
    if mfr["status"] == "SUSPENDED":
        cutoff = secs(now() - timedelta(days=90))
        for g in STORE["grants"].values():
            if g["manufacturer_id"] == mid and g["revoked_for_cause"] and g["revoked_at"]:
                if secs(parse_datetime(g["revoked_at"])) >= cutoff:
                    err("ERR_RECENT_BREACH",
                        "A for-cause revocation is within the trailing 90 days")
    mfr["status"] = "QUALIFIED"
    mfr["suspended_at"] = None
    touch(mfr)
    return ok(mfr_json(mfr))


# ---------------------------------------------------------------------------
# Confidentiality grants
# ---------------------------------------------------------------------------
@bp.post("/brand-ops/confidentiality-grants")
def create_grant():
    _, role = authenticate()
    authorize(role, ["TradeSecretOfficer"])
    b = body()
    manufacturer_id = as_str(need(b, "manufacturer_id"), "manufacturer_id")
    formulation_id = as_str(need(b, "formulation_id"), "formulation_id")
    scope = as_str_list(need(b, "component_scope"), "component_scope")
    reason = as_enum(need(b, "grant_reason"), "grant_reason", GRANT_REASONS)
    expires_on = as_datetime(need(b, "expires_on"), "expires_on")
    # 5: body references
    mfr = STORE["manufacturers"].get(manufacturer_id)
    if mfr is None:
        err("ERR_INVALID_REFERENCE", "manufacturer_id does not exist")
    form = STORE["formulations"].get(formulation_id)
    if form is None:
        err("ERR_INVALID_REFERENCE", "formulation_id does not exist")
    # 9: qualification gate
    if mfr["status"] != "QUALIFIED":
        err("ERR_MANUFACTURER_NOT_QUALIFIED", "Manufacturer is not QUALIFIED")
    # 10: expiry must lie strictly in the future (second precision)
    if cmp_sec(expires_on, now()) <= 0:
        err("ERR_WINDOW_INVALID", "expires_on must be strictly after the current time")
    # 11: formulation state
    if form["status"] not in ("SEALED", "COMPARTMENTALIZED"):
        err("ERR_FORMULATION_NOT_SEALED", "Formulation is not SEALED or COMPARTMENTALIZED")
    # 12: scope subset
    if not set(scope) <= set(form["component_codes"]):
        err("ERR_SCOPE_NOT_SUBSET", "component_scope is not a subset of the formulation's codes")
    from core import fmt_dt
    grant = stamp_new({
        "manufacturer_id": manufacturer_id,
        "formulation_id": formulation_id,
        "component_scope": scope,
        "grant_reason": reason,
        "expires_on": fmt_dt(expires_on),
        "status": "REQUESTED",
        "granted_by_user_id": None,
        "revoked_for_cause": False,
        "revoked_at": None,
    })
    STORE["grants"][grant["id"]] = grant
    return ok(grant_json(grant), code=201)


@bp.get("/brand-ops/confidentiality-grants")
def list_grants():
    authenticate()
    items = list(STORE["grants"].values())
    items = filter_eq(items, "manufacturer_id", request.args.get("manufacturer_id"))
    items = filter_eq(items, "formulation_id", request.args.get("formulation_id"))
    items = filter_eq(items, "status", request.args.get("status"))
    page, pagination = paginate(items)
    return ok([grant_json(g) for g in page], response_type="array", pagination=pagination)


@bp.get("/brand-ops/confidentiality-grants/<gid>")
def get_grant(gid):
    authenticate()
    return ok(grant_json(get_or_404("grants", gid, "grant")))


@bp.post("/brand-ops/confidentiality-grants/<gid>/grant")
def grant_grant(gid):
    user_id, role = authenticate()
    authorize(role, ["TradeSecretOfficer"])
    g = get_or_404("grants", gid, "grant")
    body()
    if g["status"] != "REQUESTED":
        err("ERR_INVALID_STATE_TRANSITION", "Grant is not REQUESTED")
    form = STORE["formulations"].get(g["formulation_id"])
    # 9: compartmentalization scope cap (category 9 fires before temporal, §2.6)
    union = set(g["component_scope"])
    for other in STORE["grants"].values():
        if (
            other["manufacturer_id"] == g["manufacturer_id"]
            and other["formulation_id"] == g["formulation_id"]
            and other["status"] in ("GRANTED", "ACTIVE")
        ):
            union.update(other["component_scope"])
    if len(union) * 2 > len(form["component_codes"]):
        err("ERR_COMPARTMENT_SCOPE_EXCEEDED",
            "Scope would exceed half of the formulation's components")
    # 10: expiry re-verified
    if cmp_sec(parse_datetime(g["expires_on"]), now()) <= 0:
        err("ERR_GRANT_EXPIRED", "Grant expiry is not in the future")
    g["status"] = "GRANTED"
    g["granted_by_user_id"] = user_id
    touch(g)
    mfr = STORE["manufacturers"].get(g["manufacturer_id"])
    if mfr is not None:
        recompute_disclosed_count(mfr)
    return ok(grant_json(g))


@bp.post("/brand-ops/confidentiality-grants/<gid>/activate")
def activate_grant(gid):
    _, role = authenticate()
    authorize(role, ["TradeSecretOfficer"])
    g = get_or_404("grants", gid, "grant")
    body()
    if g["status"] != "GRANTED":
        err("ERR_INVALID_STATE_TRANSITION", "Grant is not GRANTED")
    mfr = STORE["manufacturers"].get(g["manufacturer_id"])
    if mfr is None or mfr["status"] != "QUALIFIED":
        err("ERR_MANUFACTURER_NOT_QUALIFIED", "Manufacturer is not QUALIFIED")
    if cmp_sec(parse_datetime(g["expires_on"]), now()) <= 0:
        err("ERR_GRANT_EXPIRED", "Grant expiry is not in the future")
    g["status"] = "ACTIVE"
    touch(g)
    recompute_disclosed_count(mfr)
    form = STORE["formulations"].get(g["formulation_id"])
    if form is not None:
        reeval_formulation_coverage(form)
    return ok(grant_json(g))


@bp.post("/brand-ops/confidentiality-grants/<gid>/revoke")
def revoke_grant(gid):
    user_id, role = authenticate()
    authorize(role, ["ComplianceAuditor"])
    g = get_or_404("grants", gid, "grant")
    b = body()
    for_cause = as_bool(need(b, "for_cause"), "for_cause")
    if g["status"] not in ("REQUESTED", "GRANTED", "ACTIVE"):
        err("ERR_INVALID_STATE_TRANSITION", "Grant is already terminal")
    if for_cause and g["granted_by_user_id"] and user_id == g["granted_by_user_id"]:
        err("ERR_AUDITOR_CONFLICT", "Revoker matches granted_by_user_id")
    was_active = g["status"] == "ACTIVE"
    was_live = g["status"] in ("GRANTED", "ACTIVE")
    ts = now_iso()
    g["status"] = "REVOKED"
    g["revoked_for_cause"] = for_cause
    g["revoked_at"] = ts
    touch(g)
    mfr = STORE["manufacturers"].get(g["manufacturer_id"])
    touched_forms = {g["formulation_id"]}
    # For-cause cascade: only when the manufacturer is QUALIFIED
    if for_cause and mfr is not None and mfr["status"] == "QUALIFIED":
        mfr["status"] = "SUSPENDED"
        mfr["suspended_at"] = ts
        touch(mfr)
        for other in STORE["grants"].values():
            if (
                other["id"] != g["id"]
                and other["manufacturer_id"] == mfr["id"]
                and other["status"] in ("REQUESTED", "GRANTED", "ACTIVE")
            ):
                other["status"] = "REVOKED"
                other["revoked_for_cause"] = True
                other["revoked_at"] = ts
                touch(other)
                touched_forms.add(other["formulation_id"])
    if was_live or (for_cause and mfr is not None):
        if mfr is not None:
            recompute_disclosed_count(mfr)
    for fid in touched_forms:
        form = STORE["formulations"].get(fid)
        if form is not None:
            reeval_formulation_coverage(form)
    # Posture recompute on every brand owning a touched formulation's line
    brand_ids = set()
    for fid in touched_forms:
        form = STORE["formulations"].get(fid)
        if form is None:
            continue
        line = STORE["product_lines"].get(form["product_line_id"])
        if line is not None:
            brand_ids.add(line["brand_id"])
    for bid in brand_ids:
        brand = STORE["brands"].get(bid)
        if brand is not None:
            recompute_posture(brand)
    return ok(grant_json(g))
