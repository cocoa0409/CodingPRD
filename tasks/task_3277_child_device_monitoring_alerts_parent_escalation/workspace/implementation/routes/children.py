"""Child profile routes: create, get, patch (tuning/archive), child-scoped collections."""
from flask import Blueprint, request
from db import store, clock
from errors import fail
from response import success_object, success_list, parse_pagination
from middleware import (authenticate, require_role, require_parent_scope,
                        require_school_scope_child)
import services as svc
import calculations as calc

bp = Blueprint("children", __name__)

SENSITIVITIES = {"LENIENT", "STANDARD", "STRICT"}
SERVICE_TYPES = {"MESSAGING", "SOCIAL", "EMAIL"}
RULE_KINDS = {"CATEGORY_BLOCK", "DOMAIN_BLOCK", "DOMAIN_ALLOW"}
PLATFORMS = {"ANDROID", "IOS", "CHROMEBOOK"}


def _get_child(child_id):
    c = store.children.get(child_id)
    if not c:
        fail("ERR_NOT_FOUND", "Child not found")
    return c


def _validate_birth_year(birth_year):
    if not isinstance(birth_year, int) or isinstance(birth_year, bool):
        fail("ERR_INVALID_REQUEST", "birth_year must be an integer")
    _band, age = calc.age_band_for(birth_year, clock.now())
    if age < 0 or age > 17:
        fail("ERR_INVALID_REQUEST", "age must be between 0 and 17")


@bp.post("/api/children")
def create_child():
    role, uid = authenticate()
    require_role(role, {"Parent"})
    body = request.get_json(silent=True) or {}
    family_id = body.get("family_account_id")
    if not isinstance(family_id, str) or not family_id:
        fail("ERR_INVALID_REQUEST", "family_account_id is required")
    family = store.families.get(family_id)
    if not family:
        fail("ERR_NOT_FOUND", "Family not found")
    require_parent_scope(uid, family["id"])
    display_name = body.get("display_name")
    if not isinstance(display_name, str) or not display_name:
        fail("ERR_INVALID_REQUEST", "display_name is required")
    birth_year = body.get("birth_year")
    _validate_birth_year(birth_year)
    sensitivity = body.get("monitoring_sensitivity", "STANDARD")
    if sensitivity not in SENSITIVITIES:
        fail("ERR_INVALID_REQUEST", "invalid monitoring_sensitivity")
    band, _age = calc.age_band_for(birth_year, clock.now())
    with store.lock:
        c = svc.new_entity()
        c.update({
            "family_account_id": family["id"],
            "display_name": display_name,
            "birth_year": birth_year,
            "age_band": band,
            "monitoring_sensitivity": sensitivity,
            "profile_status": "ACTIVE",
            "open_alert_count": 0,
        })
        store.children[c["id"]] = c
    return success_object(svc.ser_child(c), status=201)


@bp.get("/api/children/<child_id>")
def get_child(child_id):
    role, uid = authenticate()
    require_role(role, {"Parent", "SchoolAdmin", "PlatformAdmin"})
    c = _get_child(child_id)
    if role == "Parent":
        require_parent_scope(uid, c["family_account_id"])
    elif role == "SchoolAdmin":
        require_school_scope_child(uid, c["id"])
    return success_object(svc.ser_child(c))


@bp.patch("/api/children/<child_id>")
def update_child(child_id):
    role, uid = authenticate()
    require_role(role, {"Parent"})
    c = _get_child(child_id)
    require_parent_scope(uid, c["family_account_id"])
    body = request.get_json(silent=True) or {}
    # OCC first (priority 5)
    expected = body.get("expected_child_version")
    if expected is None or not isinstance(expected, int) or isinstance(expected, bool):
        fail("ERR_INVALID_REQUEST", "expected_child_version is required")
    if expected != c["version"]:
        fail("ERR_STALE_VERSION", "Child version mismatch")

    if c["profile_status"] == "ARCHIVED":
        fail("ERR_ALREADY_TERMINAL", "Child is ARCHIVED")

    new_sensitivity = body.get("monitoring_sensitivity")
    if new_sensitivity is not None and new_sensitivity not in SENSITIVITIES:
        fail("ERR_INVALID_REQUEST", "invalid monitoring_sensitivity")
    new_birth_year = body.get("birth_year")
    if new_birth_year is not None:
        _validate_birth_year(new_birth_year)
    new_status = body.get("profile_status")
    archiving = False
    if new_status is not None:
        if new_status != "ARCHIVED":
            fail("ERR_INVALID_STATE", "profile_status may only transition to ARCHIVED")
        archiving = True

    if archiving:
        for case in store.escalation_cases.values():
            if case.get("child_profile_id") == c["id"] and case.get("case_status") != "CLOSED":
                fail("ERR_ESCALATION_OPEN", "Open escalation case blocks archival")

    with store.lock:
        if new_sensitivity is not None:
            c["monitoring_sensitivity"] = new_sensitivity
        if new_birth_year is not None:
            c["birth_year"] = new_birth_year
            band, _age = calc.age_band_for(new_birth_year, clock.now())
            c["age_band"] = band
        if archiving:
            c["profile_status"] = "ARCHIVED"
            for conn in store.connections.values():
                if (conn.get("child_profile_id") == c["id"]
                        and conn.get("consent_status") in ("AWAITING_CONSENT", "ACTIVE", "PAUSED")):
                    conn["consent_status"] = "REVOKED"
                    svc.touch(conn)
        svc.touch(c)
    return success_object(svc.ser_child(c))


@bp.get("/api/children/<child_id>/connections")
def list_connections(child_id):
    role, uid = authenticate()
    require_role(role, {"Parent", "PlatformAdmin"})
    c = _get_child(child_id)
    if role == "Parent":
        require_parent_scope(uid, c["family_account_id"])
    limit, offset = parse_pagination(request.args)
    items = [x for x in store.connections.values()
             if x.get("child_profile_id") == c["id"]]
    page, total = svc.paginate(items, limit, offset)
    return success_list([svc.ser_connection(x) for x in page], limit, offset, total)


@bp.post("/api/children/<child_id>/connections")
def create_connection(child_id):
    role, uid = authenticate()
    require_role(role, {"Parent"})
    c = _get_child(child_id)
    require_parent_scope(uid, c["family_account_id"])
    if c["profile_status"] != "ACTIVE":
        fail("ERR_CHILD_ARCHIVED", "Child is archived")
    body = request.get_json(silent=True) or {}
    service_type = body.get("service_type")
    handle = body.get("external_handle")
    token = body.get("credential_token")
    if service_type not in SERVICE_TYPES:
        fail("ERR_INVALID_REQUEST", "invalid service_type")
    if not isinstance(handle, str) or not handle:
        fail("ERR_INVALID_REQUEST", "external_handle is required")
    if not isinstance(token, str) or not token:
        fail("ERR_INVALID_REQUEST", "credential_token is required")
    for x in store.connections.values():
        if (x.get("child_profile_id") == c["id"]
                and x.get("service_type") == service_type
                and x.get("external_handle") == handle
                and x.get("consent_status") != "REVOKED"):
            fail("ERR_DUPLICATE_CONNECTION",
                 "A non-REVOKED connection already exists for this handle")
    with store.lock:
        conn = svc.new_entity()
        conn.update({
            "child_profile_id": c["id"],
            "service_type": service_type,
            "external_handle": handle,
            "credential_token": token,
            "consent_status": "AWAITING_CONSENT",
        })
        store.connections[conn["id"]] = conn
    return success_object(svc.ser_connection(conn), status=201)


@bp.get("/api/children/<child_id>/filter-rules")
def list_filter_rules(child_id):
    role, uid = authenticate()
    require_role(role, {"Parent", "PlatformAdmin"})
    c = _get_child(child_id)
    if role == "Parent":
        require_parent_scope(uid, c["family_account_id"])
    limit, offset = parse_pagination(request.args)
    items = [r for r in store.filter_rules.values()
             if r.get("child_profile_id") == c["id"]]
    page, total = svc.paginate(items, limit, offset)
    return success_list([svc.ser_filter_rule(r) for r in page], limit, offset, total)


@bp.post("/api/children/<child_id>/filter-rules")
def create_filter_rule(child_id):
    role, uid = authenticate()
    require_role(role, {"Parent"})
    c = _get_child(child_id)
    require_parent_scope(uid, c["family_account_id"])
    if c["profile_status"] != "ACTIVE":
        fail("ERR_CHILD_ARCHIVED", "Child is archived")
    body = request.get_json(silent=True) or {}
    rule_kind = body.get("rule_kind")
    target = body.get("target")
    if rule_kind not in RULE_KINDS:
        fail("ERR_INVALID_REQUEST", "invalid rule_kind")
    if not isinstance(target, str) or not target:
        fail("ERR_INVALID_REQUEST", "target is required")
    with store.lock:
        r = svc.new_entity()
        r.update({
            "child_profile_id": c["id"],
            "rule_kind": rule_kind,
            "target": target,
            "rule_status": "ACTIVE",
        })
        store.filter_rules[r["id"]] = r
    return success_object(svc.ser_filter_rule(r), status=201)


@bp.get("/api/children/<child_id>/district-links")
def list_child_district_links(child_id):
    role, uid = authenticate()
    require_role(role, {"Parent", "SchoolAdmin", "PlatformAdmin"})
    c = _get_child(child_id)
    if role == "Parent":
        require_parent_scope(uid, c["family_account_id"])
    elif role == "SchoolAdmin":
        require_school_scope_child(uid, c["id"])
    limit, offset = parse_pagination(request.args)
    items = [l for l in store.district_links.values()
             if l.get("child_profile_id") == c["id"]]
    page, total = svc.paginate(items, limit, offset)
    return success_list([svc.ser_district_link(l) for l in page], limit, offset, total)


@bp.get("/api/children/<child_id>/devices")
def list_child_devices(child_id):
    role, uid = authenticate()
    require_role(role, {"Parent", "PlatformAdmin"})
    c = _get_child(child_id)
    if role == "Parent":
        require_parent_scope(uid, c["family_account_id"])
    limit, offset = parse_pagination(request.args)
    items = [d for d in store.devices.values()
             if d.get("child_profile_id") == c["id"]]
    page, total = svc.paginate(items, limit, offset)
    return success_list([svc.ser_device(d) for d in page], limit, offset, total)


@bp.post("/api/children/<child_id>/devices/pair")
def pair_device(child_id):
    role, uid = authenticate()
    require_role(role, {"Parent"})
    c = _get_child(child_id)
    require_parent_scope(uid, c["family_account_id"])
    if c["profile_status"] != "ACTIVE":
        fail("ERR_CHILD_ARCHIVED", "Child is archived")
    family = store.families.get(c["family_account_id"])
    if family["account_status"] != "ACTIVE":
        fail("ERR_FAMILY_SUSPENDED", "Family is suspended")
    body = request.get_json(silent=True) or {}
    platform = body.get("platform")
    nickname = body.get("nickname")
    if platform not in PLATFORMS:
        fail("ERR_INVALID_REQUEST", "invalid platform")
    if not isinstance(nickname, str) or not nickname:
        fail("ERR_INVALID_REQUEST", "nickname is required")
    if family["device_count"] >= family["device_limit"]:
        fail("ERR_DEVICE_LIMIT_EXCEEDED", "Device limit reached for tier")
    with store.lock:
        d = svc.new_entity()
        d.update({
            "child_profile_id": c["id"],
            "platform": platform,
            "nickname": nickname,
            "pairing_status": "PAIRED",
            "device_posture": "NORMAL",
            "bypass_strike_count": 0,
        })
        store.devices[d["id"]] = d
        svc.recompute_device_count(family)
    return success_object(svc.ser_device(d), status=201)
