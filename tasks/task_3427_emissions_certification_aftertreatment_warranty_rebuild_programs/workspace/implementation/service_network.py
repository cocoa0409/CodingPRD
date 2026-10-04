"""Service network: centers, technicians, diagnostic tools (PRD §3.6)."""
from flask import Blueprint

import cascade
import clock
import store
from errors import ApiError
from rbac import auth, ANY
from validators import (
    body, f_str, f_int, f_bool, f_enum, get_or_404, page_args, slice_page,
    envelope_ok, new_entity, touch, ser,
)

bp = Blueprint("service_network", __name__)

AUTH_TIERS = ("BASIC", "CERTIFIED", "MASTER")
CERT_LEVELS = ("LEVEL_1", "LEVEL_2", "LEVEL_3")
TECH_CERT_VALIDITY_DAYS = 730
TOOL_CALIBRATION_VALIDITY_DAYS = 365


# ---------------------------------------------------------------------------
# Service centers
# ---------------------------------------------------------------------------

@bp.post("/emissions/service-centers")
def create_center():
    auth(("PlatformAdmin",))
    b = body()
    name = f_str(b, "name")
    region = f_str(b, "region")
    capacity = f_int(b, "bay_capacity_per_day", min_v=1)
    ent = new_entity()
    ent.update({
        "name": name,
        "region": region,
        "authorization_tier": "BASIC",
        "auth_status": "APPLIED",
        "bay_capacity_per_day": capacity,
        "core_credit_balance_cents": 0,
        "core_reversal_count": 0,
    })
    store.centers[ent["id"]] = ent
    return envelope_ok(ser(ent), 201)


@bp.get("/emissions/service-centers/<cid>")
def get_center(cid):
    auth(ANY)
    ent = get_or_404(store.centers, cid, "ServiceCenter")
    return envelope_ok(ser(ent), 200)


@bp.post("/emissions/service-centers/<cid>/audit")
def audit_center(cid):
    auth(("PlatformAdmin",))
    center = get_or_404(store.centers, cid, "ServiceCenter")
    if center["auth_status"] != "APPLIED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409, "audit requires APPLIED")
    center["auth_status"] = "AUDITED"
    touch(center)
    return envelope_ok(ser(center), 200)


@bp.post("/emissions/service-centers/<cid>/authorize")
def authorize_center(cid):
    auth(("PlatformAdmin",))
    b = body()
    tier = f_enum(b, "authorization_tier", AUTH_TIERS)
    center = get_or_404(store.centers, cid, "ServiceCenter")
    if center["auth_status"] != "AUDITED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409, "authorize requires AUDITED")
    # qualification (priority 9): >= 1 CERT_ACTIVE emissions-endorsed technician
    qualified = False
    for t in store.technicians.values():
        if t["service_center_id"] != cid:
            continue
        cascade.materialize_technician(t)  # lazy EXPIRED on use (§2.4)
        if t["cert_status"] == "CERT_ACTIVE" and t["emissions_endorsed"]:
            qualified = True
    if not qualified:
        raise ApiError("ERR_NO_QUALIFIED_TECHNICIAN", 409,
                       "Authorization requires a CERT_ACTIVE emissions-endorsed technician")
    center["authorization_tier"] = tier
    center["auth_status"] = "AUTHORIZED"
    touch(center)
    return envelope_ok(ser(center), 200)


@bp.post("/emissions/service-centers/<cid>/suspend")
def suspend_center(cid):
    auth(("PlatformAdmin",))
    center = get_or_404(store.centers, cid, "ServiceCenter")
    if center["auth_status"] != "AUTHORIZED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409, "suspend requires AUTHORIZED")
    center["auth_status"] = "SUSPENDED"
    touch(center)
    return envelope_ok(ser(center), 200)


@bp.post("/emissions/service-centers/<cid>/reinstate")
def reinstate_center(cid):
    auth(("PlatformAdmin",))
    center = get_or_404(store.centers, cid, "ServiceCenter")
    if center["auth_status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409, "reinstate requires SUSPENDED")
    center["auth_status"] = "AUTHORIZED"
    center["core_reversal_count"] = 0
    touch(center)
    return envelope_ok(ser(center), 200)


@bp.post("/emissions/service-centers/<cid>/revoke")
def revoke_center(cid):
    auth(("PlatformAdmin",))
    center = get_or_404(store.centers, cid, "ServiceCenter")
    if center["auth_status"] not in ("AUTHORIZED", "SUSPENDED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "revoke requires AUTHORIZED or SUSPENDED")
    center["auth_status"] = "REVOKED"
    touch(center)
    return envelope_ok(ser(center), 200)


# ---------------------------------------------------------------------------
# Technicians
# ---------------------------------------------------------------------------

@bp.post("/emissions/service-centers/<cid>/technicians")
def create_technician(cid):
    auth(("PlatformAdmin",))
    b = body()
    full_name = f_str(b, "full_name")
    badge_id = f_str(b, "badge_id")
    level = f_enum(b, "certification_level", CERT_LEVELS)
    endorsed = f_bool(b, "emissions_endorsed")
    center = get_or_404(store.centers, cid, "ServiceCenter")
    if center["auth_status"] == "REVOKED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "A technician cannot be certified into a REVOKED center")
    for t in store.technicians.values():
        if t["service_center_id"] == cid and t["badge_id"] == badge_id:
            raise ApiError("ERR_DUPLICATE_BADGE_ID", 409,
                           "badge_id already exists within the center")
    now = clock.now_dt()
    ent = new_entity()
    ent.update({
        "service_center_id": cid,
        "full_name": full_name,
        "badge_id": badge_id,
        "certification_level": level,
        "emissions_endorsed": endorsed,
        "certified_at": now,
        "certification_expires_at": clock.add_days(now, TECH_CERT_VALIDITY_DAYS),
        "cert_status": "CERT_ACTIVE",
    })
    store.technicians[ent["id"]] = ent
    return envelope_ok(ser(ent), 201)


@bp.get("/emissions/service-centers/<cid>/technicians")
def list_technicians(cid):
    auth(ANY)
    limit, offset = page_args()
    get_or_404(store.centers, cid, "ServiceCenter")
    items = [t for t in store.technicians.values() if t["service_center_id"] == cid]
    for t in items:
        cascade.materialize_technician(t)  # lazy EXPIRED on read (§2.4)
    page, meta = slice_page(items, limit, offset)
    return envelope_ok(page, 200, meta)


@bp.post("/emissions/technicians/<tid>/recertify")
def recertify_technician(tid):
    auth(("PlatformAdmin",))
    b = body()
    new_level = f_enum(b, "new_level", CERT_LEVELS, required=False, default=None)
    tech = get_or_404(store.technicians, tid, "Technician")
    cascade.materialize_technician(tech)  # recertify is a use: lazy EXPIRED first
    now = clock.now_dt()
    tech["certified_at"] = now
    tech["certification_expires_at"] = clock.add_days(now, TECH_CERT_VALIDITY_DAYS)
    if new_level is not None:
        tech["certification_level"] = new_level
    tech["cert_status"] = "CERT_ACTIVE"
    touch(tech)
    return envelope_ok(ser(tech), 200)


# ---------------------------------------------------------------------------
# Diagnostic tools
# ---------------------------------------------------------------------------

@bp.post("/emissions/service-centers/<cid>/diagnostic-tools")
def create_tool(cid):
    auth(("PlatformAdmin",))
    b = body()
    serial = f_str(b, "tool_serial")
    software = f_str(b, "software_version")
    get_or_404(store.centers, cid, "ServiceCenter")
    for t in store.tools.values():
        if t["tool_serial"] == serial:
            raise ApiError("ERR_DUPLICATE_TOOL_SERIAL", 409,
                           "tool_serial already exists program-wide")
    now = clock.now_dt()
    ent = new_entity()
    ent.update({
        "service_center_id": cid,
        "tool_serial": serial,
        "software_version": software,
        "issued_at": now,
        "calibration_valid_until": clock.add_days(now, TOOL_CALIBRATION_VALIDITY_DAYS),
        "tool_status": "CALIBRATED_ACTIVE",
    })
    store.tools[ent["id"]] = ent
    return envelope_ok(ser(ent), 201)


@bp.get("/emissions/service-centers/<cid>/diagnostic-tools")
def list_tools(cid):
    auth(ANY)
    limit, offset = page_args()
    get_or_404(store.centers, cid, "ServiceCenter")
    items = [t for t in store.tools.values() if t["service_center_id"] == cid]
    for t in items:
        cascade.materialize_tool(t)  # lazy RECAL_DUE on read (§2.4)
    page, meta = slice_page(items, limit, offset)
    return envelope_ok(page, 200, meta)


@bp.post("/emissions/diagnostic-tools/<tid>/recalibrate")
def recalibrate_tool(tid):
    auth(("PlatformAdmin",))
    tool = get_or_404(store.tools, tid, "DiagnosticTool")
    cascade.materialize_tool(tool)  # recalibrate is a use: lazy RECAL_DUE first
    if tool["tool_status"] != "RECAL_DUE":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "recalibrate requires RECAL_DUE")
    tool["calibration_valid_until"] = clock.add_days(
        clock.now_dt(), TOOL_CALIBRATION_VALIDITY_DAYS)
    tool["tool_status"] = "CALIBRATED_ACTIVE"
    touch(tool)
    return envelope_ok(ser(tool), 200)
