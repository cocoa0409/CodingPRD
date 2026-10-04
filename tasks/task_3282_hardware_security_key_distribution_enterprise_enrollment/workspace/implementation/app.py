import math
import os
import re
import uuid
import threading
from datetime import datetime, timedelta, timezone

from flask import Flask, request, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------
STORE_LOCK = threading.RLock()

db = {
    "organizations": {},
    "key_models": {},
    "devices": {},
    "employees": {},
    "identity_accounts": {},
    "purchase_orders": {},
    "security_keys": {},
    "enrollments": {},
    "temp_grants": {},
    "subscriptions": {},
    "help_desk_cases": {},
}

CLOCK = {"now": datetime(2026, 9, 1, tzinfo=timezone.utc)}

ENROLLMENT_VALIDITY_DAYS = 365
EXPIRING_WINDOW_DAYS = 30
CREDIT_UNIT_CENTS = 100
REFRESH_CREDIT_COST = 1

ROLES = {
    "PlatformAdmin",
    "SecurityAdmin",
    "ProcurementAdmin",
    "LogisticsCoordinator",
    "HelpDeskAgent",
    "Employee",
}

PROTOCOLS = {"FIDO2", "U2F", "OATH_HOTP", "PIV"}
CONNECTORS = {"USB_A", "USB_C", "LIGHTNING", "NFC", "BLE"}
FORM_FACTORS = {"KEYCHAIN", "NANO", "CARD", "BIOMETRIC"}
PLATFORMS = {"WINDOWS", "MACOS", "LINUX", "CHROMEOS", "ANDROID", "IOS"}
GRANT_METHODS = {"TOTP", "SMART_CARD", "SERVICE_DESK_TOKEN"}
HARDWARE_PROTOCOLS = {"FIDO2", "U2F", "PIV"}


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


# ---------------------------------------------------------------------------
# Time / envelope helpers
# ---------------------------------------------------------------------------

def now():
    return CLOCK["now"]


def iso(dt):
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def stamp_now_ms():
    # meta timestamp: ISO 8601 UTC with three fractional digits
    n = datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"


def success(payload, status=200, response_type="object", pagination=None):
    meta = {
        "api_request_id": "req_" + uuid.uuid4().hex[:20],
        "api_request_timestamp": stamp_now_ms(),
    }
    if pagination:
        meta.update(pagination)
    return jsonify({"meta": meta, "response_type": response_type, "data": payload}), status


def error_response(err):
    meta = {
        "api_request_id": "req_" + uuid.uuid4().hex[:20],
        "api_request_timestamp": stamp_now_ms(),
    }
    return jsonify({
        "meta": meta,
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }), err.http_status


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def handle_404(err):
    return error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))


@app.errorhandler(405)
def handle_405(err):
    return error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))


@app.errorhandler(400)
def handle_400(err):
    return error_response(ApiError("ERR_INVALID_REQUEST", 400, "Malformed request"))


@app.errorhandler(Exception)
def handle_exc(err):
    app.logger.exception(err)
    return error_response(ApiError("ERR_INVALID_REQUEST", 400, "Malformed request"))


def err_unauthenticated(msg="Missing or malformed authentication headers"):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def err_unauthorized(msg="Role not permitted for this endpoint"):
    return ApiError("ERR_UNAUTHORIZED", 403, msg)


def err_not_found(msg="Resource not found"):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def err_invalid_request(msg="Malformed request"):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def err_invalid_state(msg="Invalid state for this transition"):
    return ApiError("ERR_INVALID_STATE", 409, msg)


def err_stale(msg="Stale version"):
    return ApiError("ERR_STALE_VERSION", 412, msg)


# ---------------------------------------------------------------------------
# Request helpers
# ---------------------------------------------------------------------------

def get_body():
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise err_invalid_request("Request body must be valid JSON")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err_invalid_request("Request body must be a JSON object")
    return body


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise err_invalid_request(f"Missing required field: {f}")


def reject_unknown(body, allowed):
    for k in body:
        if k not in allowed:
            raise err_invalid_request(f"Unknown field: {k}")


def check_enum(value, allowed, field):
    if value not in allowed:
        raise err_invalid_request(f"Invalid value for {field}")
    return value


def check_str(value, field):
    if not isinstance(value, str) or value == "":
        raise err_invalid_request(f"Invalid value for {field}")
    return value


def check_int(value, field):
    if isinstance(value, bool) or not isinstance(value, int):
        raise err_invalid_request(f"Invalid value for {field}")
    return value


def check_nonempty_array(value, field, elem_allowed=None):
    if not isinstance(value, list) or len(value) == 0:
        raise err_invalid_request(f"{field} must be a non-empty array")
    for e in value:
        if not isinstance(e, str):
            raise err_invalid_request(f"Invalid element in {field}")
        if elem_allowed is not None and e not in elem_allowed:
            raise err_invalid_request(f"Invalid element in {field}")
    return value


def auth(*allowed_roles):
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise err_unauthenticated()
    if role not in allowed_roles:
        raise err_unauthorized()
    return uid, role


def new_id():
    return str(uuid.uuid4())


def touch(entity):
    entity["updated_at"] = now()
    entity["version"] += 1


def new_entity():
    return {"id": new_id(), "created_at": now(), "updated_at": now(), "version": 1}


def parse_limit_offset():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise err_invalid_request("Invalid limit")
        if limit < 1 or limit > 100:
            raise err_invalid_request("Invalid limit")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise err_invalid_request("Invalid offset")
        if offset < 0:
            raise err_invalid_request("Invalid offset")
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    page = items[offset:offset + limit]
    has_more = offset + limit < total
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": has_more,
    }


# ---------------------------------------------------------------------------
# Entity serialization (all datetimes -> iso strings)
# ---------------------------------------------------------------------------

def ser(entity):
    out = {}
    for k, v in entity.items():
        if isinstance(v, datetime):
            out[k] = iso(v)
        elif isinstance(v, list):
            out[k] = list(v)
        else:
            out[k] = v
    return out


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def get_org(org_id):
    org = db["organizations"].get(org_id)
    if org is None:
        raise err_not_found("Organization not found")
    return org


def get_org_child(table, org_id, child_id, label):
    org = get_org(org_id)
    child = db[table].get(child_id)
    if child is None or child.get("organization_id") != org["id"]:
        raise err_not_found(f"{label} not found")
    return org, child


def get_account(acc_id):
    acc = db["identity_accounts"].get(acc_id)
    if acc is None:
        raise err_not_found("Identity account not found")
    return acc


def active_subscription(org_id):
    for s in db["subscriptions"].values():
        if s["organization_id"] == org_id and s["status"] == "ACTIVE":
            return s
    return None


def recompute_account(acc):
    org = db["organizations"][acc["organization_id"]]
    count = 0
    for e in db["enrollments"].values():
        if e["identity_account_id"] == acc["id"] and e["status"] in ("ACTIVE", "EXPIRING"):
            count += 1
    acc["registered_key_count"] = count
    minimum = org["backup_key_minimum"]
    if org["authentication_policy"] == "PHISHING_RESISTANT":
        minimum += 1
    acc["backup_compliant"] = count >= minimum
    if acc["status"] == "ENROLLED" and count == 0:
        acc["status"] = "LOCKED"
    touch(acc)


def revoke_ceremony(cer):
    if cer["status"] in ("PENDING", "ACTIVE", "EXPIRING"):
        cer["status"] = "REVOKED"
        cer["revoked_at"] = now()
        touch(cer)


def revoke_key(key):
    """Revoke a key and cascade into ceremonies/accounts."""
    if key["hardware_status"] in ("PRE_REGISTERED", "ASSIGNED", "DISTRIBUTED"):
        key["hardware_status"] = "REVOKED"
        touch(key)
    affected_accounts = set()
    for cer in db["enrollments"].values():
        if cer["security_key_id"] == key["id"] and cer["status"] in ("PENDING", "ACTIVE", "EXPIRING"):
            counted = cer["status"] in ("ACTIVE", "EXPIRING")
            revoke_ceremony(cer)
            if counted:
                affected_accounts.add(cer["identity_account_id"])
    for aid in affected_accounts:
        recompute_account(db["identity_accounts"][aid])


def void_active_grants(account_id):
    for g in db["temp_grants"].values():
        if g["identity_account_id"] == account_id and g["status"] == "ACTIVE":
            g["status"] = "VOIDED"
            touch(g)


# ---------------------------------------------------------------------------
# Clock and ops endpoints
# ---------------------------------------------------------------------------

@app.route("/v1/_clock/set_current_utc", methods=["POST"])
def set_clock():
    body = get_body()
    reject_unknown(body, {"to_iso8601"})
    require_fields(body, ["to_iso8601"])
    auth("PlatformAdmin")
    val = body["to_iso8601"]
    if not isinstance(val, str):
        raise err_invalid_request("to_iso8601 must be a string")
    v = val.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(v)
    except ValueError:
        raise err_invalid_request("to_iso8601 is not a valid ISO 8601 timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc).replace(microsecond=0)
    with STORE_LOCK:
        CLOCK["now"] = dt
    return success({"now_iso8601": iso(CLOCK["now"])})


# ---------------------------------------------------------------------------
# Organizations
# ---------------------------------------------------------------------------

@app.route("/v1/organizations", methods=["POST"])
def create_org():
    body = get_body()
    allowed = {"legal_name", "assurance_tier", "authentication_policy", "idp_protocols",
               "approved_firmware_versions", "backup_key_minimum"}
    reject_unknown(body, allowed)
    require_fields(body, ["legal_name", "assurance_tier", "authentication_policy", "idp_protocols"])
    auth("PlatformAdmin")
    legal_name = check_str(body["legal_name"], "legal_name")
    tier = check_enum(body["assurance_tier"], {"STANDARD", "HIGH_ASSURANCE"}, "assurance_tier")
    policy = check_enum(body["authentication_policy"], {"STANDARD", "PHISHING_RESISTANT"}, "authentication_policy")
    idp = check_nonempty_array(body["idp_protocols"], "idp_protocols", PROTOCOLS)
    fw = body.get("approved_firmware_versions", [])
    if not isinstance(fw, list) or any(not isinstance(x, str) for x in fw):
        raise err_invalid_request("approved_firmware_versions must be an array of strings")
    bkm = body.get("backup_key_minimum", 2)
    check_int(bkm, "backup_key_minimum")
    if bkm < 1:
        raise err_invalid_request("backup_key_minimum must be >= 1")
    with STORE_LOCK:
        org = new_entity()
        org.update({
            "legal_name": legal_name,
            "assurance_tier": tier,
            "authentication_policy": policy,
            "idp_protocols": list(idp),
            "approved_firmware_versions": list(fw),
            "backup_key_minimum": bkm,
            "status": "ACTIVE",
        })
        db["organizations"][org["id"]] = org
        return success(ser(org), status=201)


# ---------------------------------------------------------------------------
# Key models
# ---------------------------------------------------------------------------

@app.route("/v1/key-models", methods=["POST"])
def create_key_model():
    body = get_body()
    allowed = {"model_code", "connectors", "protocols", "form_factor", "unit_price_cents"}
    reject_unknown(body, allowed)
    require_fields(body, ["model_code", "connectors", "protocols", "form_factor", "unit_price_cents"])
    auth("PlatformAdmin")
    model_code = check_str(body["model_code"], "model_code")
    connectors = check_nonempty_array(body["connectors"], "connectors", CONNECTORS)
    protocols = check_nonempty_array(body["protocols"], "protocols", PROTOCOLS)
    form_factor = check_enum(body["form_factor"], FORM_FACTORS, "form_factor")
    price = check_int(body["unit_price_cents"], "unit_price_cents")
    if price <= 0:
        raise err_invalid_request("unit_price_cents must be > 0")
    with STORE_LOCK:
        for m in db["key_models"].values():
            if m["model_code"] == model_code:
                raise ApiError("ERR_DUPLICATE", 409, "model_code already exists")
        m = new_entity()
        m.update({
            "model_code": model_code,
            "connectors": list(connectors),
            "protocols": list(protocols),
            "form_factor": form_factor,
            "unit_price_cents": price,
        })
        db["key_models"][m["id"]] = m
        return success(ser(m), status=201)


# ---------------------------------------------------------------------------
# Devices
# ---------------------------------------------------------------------------

@app.route("/v1/organizations/<org_id>/devices", methods=["POST"])
def create_device(org_id):
    body = get_body()
    allowed = {"asset_tag", "platform", "connectors", "protocol_capability", "lifecycle_status"}
    reject_unknown(body, allowed)
    require_fields(body, ["asset_tag", "platform", "connectors", "protocol_capability"])
    auth("SecurityAdmin")
    org = get_org(org_id)
    asset_tag = check_str(body["asset_tag"], "asset_tag")
    platform = check_enum(body["platform"], PLATFORMS, "platform")
    connectors = check_nonempty_array(body["connectors"], "connectors", CONNECTORS)
    proto = check_nonempty_array(body["protocol_capability"], "protocol_capability", PROTOCOLS)
    lifecycle = body.get("lifecycle_status", "ACTIVE")
    check_enum(lifecycle, {"ACTIVE", "RETIRED"}, "lifecycle_status")
    with STORE_LOCK:
        for d in db["devices"].values():
            if d["organization_id"] == org["id"] and d["asset_tag"] == asset_tag:
                raise ApiError("ERR_DUPLICATE", 409, "asset_tag already exists in organization")
        d = new_entity()
        d.update({
            "organization_id": org["id"],
            "asset_tag": asset_tag,
            "platform": platform,
            "connectors": list(connectors),
            "protocol_capability": list(proto),
            "lifecycle_status": lifecycle,
        })
        db["devices"][d["id"]] = d
        return success(ser(d), status=201)


@app.route("/v1/organizations/<org_id>/devices", methods=["GET"])
def list_devices(org_id):
    uid, role = auth("SecurityAdmin", "ProcurementAdmin")
    org = get_org(org_id)
    limit, offset = parse_limit_offset()
    items = [d for d in db["devices"].values() if d["organization_id"] == org["id"]]
    ls = request.args.get("lifecycle_status")
    if ls is not None:
        check_enum(ls, {"ACTIVE", "RETIRED"}, "lifecycle_status")
        items = [d for d in items if d["lifecycle_status"] == ls]
    pf = request.args.get("platform")
    if pf is not None:
        check_enum(pf, PLATFORMS, "platform")
        items = [d for d in items if d["platform"] == pf]
    items.sort(key=lambda d: (d["created_at"], d["id"]))
    page, pmeta = paginate([ser(d) for d in items], limit, offset)
    return success(page, response_type="array", pagination=pmeta)


@app.route("/v1/organizations/<org_id>/fleet-fit", methods=["GET"])
def fleet_fit(org_id):
    uid, role = auth("SecurityAdmin", "ProcurementAdmin")
    org = get_org(org_id)
    model_code = request.args.get("model_code")
    if model_code is None:
        raise err_invalid_request("model_code is required")
    model = None
    for m in db["key_models"].values():
        if m["model_code"] == model_code:
            model = m
            break
    if model is None:
        raise err_not_found("Key model not found")
    devices = [d for d in db["devices"].values()
               if d["organization_id"] == org["id"] and d["lifecycle_status"] == "ACTIVE"]
    if not devices:
        raise ApiError("ERR_EMPTY_FLEET", 422, "Organization has no ACTIVE devices")
    fit = 0
    uncovered = []
    for d in devices:
        c_ok = bool(set(d["connectors"]) & set(model["connectors"]))
        p_ok = bool(set(d["protocol_capability"]) & set(model["protocols"]))
        if c_ok and p_ok:
            fit += 1
        else:
            uncovered.append(d)
    uncovered.sort(key=lambda d: (d["created_at"], d["asset_tag"]))
    coverage = int(math.floor(100.0 * fit / len(devices) + 0.5))
    return success({
        "coverage_pct": coverage,
        "total_devices": len(devices),
        "uncovered_device_ids": [d["id"] for d in uncovered],
    })


# ---------------------------------------------------------------------------
# Employees and identity accounts
# ---------------------------------------------------------------------------

@app.route("/v1/organizations/<org_id>/employees", methods=["POST"])
def create_employee(org_id):
    body = get_body()
    allowed = {"employee_ref", "location", "directory_user_id"}
    reject_unknown(body, allowed)
    require_fields(body, ["employee_ref", "location", "directory_user_id"])
    auth("SecurityAdmin")
    org = get_org(org_id)
    employee_ref = check_str(body["employee_ref"], "employee_ref")
    location = check_str(body["location"], "location")
    duid = check_str(body["directory_user_id"], "directory_user_id")
    with STORE_LOCK:
        for e in db["employees"].values():
            if e["organization_id"] == org["id"]:
                if e["employee_ref"] == employee_ref:
                    raise ApiError("ERR_DUPLICATE", 409, "employee_ref already exists in organization")
                if e["directory_user_id"] == duid:
                    raise ApiError("ERR_DUPLICATE", 409, "directory_user_id already exists in organization")
        emp = new_entity()
        acc = new_entity()
        acc.update({
            "employee_id": emp["id"],
            "organization_id": org["id"],
            "directory_user_id": duid,
            "employee_ref": employee_ref,
            "registered_key_count": 0,
            "backup_compliant": False,
            "status": "UNENROLLED",
        })
        db["identity_accounts"][acc["id"]] = acc
        emp.update({
            "organization_id": org["id"],
            "employee_ref": employee_ref,
            "location": location,
            "directory_user_id": duid,
            "identity_account_id": acc["id"],
            "employment_status": "ACTIVE",
        })
        db["employees"][emp["id"]] = emp
        return success(ser(emp), status=201)


@app.route("/v1/organizations/<org_id>/employees/<eid>/terminate", methods=["POST"])
def terminate_employee(org_id, eid):
    body = get_body()
    reject_unknown(body, set())
    auth("SecurityAdmin")
    org, emp = get_org_child("employees", org_id, eid, "Employee")
    with STORE_LOCK:
        if emp["employment_status"] != "ACTIVE":
            raise err_invalid_state("Employee is not ACTIVE")
        emp["employment_status"] = "TERMINATED"
        acc = db["identity_accounts"][emp["identity_account_id"]]
        # revoke assigned/distributed keys of the account (cascade)
        for key in list(db["security_keys"].values()):
            if key.get("assigned_identity_account_id") == acc["id"] and \
                    key["hardware_status"] in ("ASSIGNED", "DISTRIBUTED"):
                revoke_key(key)
        # revoke remaining ceremonies of the account
        for cer in db["enrollments"].values():
            if cer["identity_account_id"] == acc["id"] and cer["status"] in ("PENDING", "ACTIVE", "EXPIRING"):
                revoke_ceremony(cer)
        # void active grants
        void_active_grants(acc["id"])
        # recompute + lock the account
        recompute_account(acc)
        acc["status"] = "LOCKED"
        touch(acc)
        touch(emp)
        return success(ser(emp))


@app.route("/v1/identity-accounts/<acc_id>", methods=["GET"])
def get_identity_account(acc_id):
    auth("SecurityAdmin", "HelpDeskAgent")
    acc = get_account(acc_id)
    return success(ser(acc))


@app.route("/v1/identity-accounts/<acc_id>/lock", methods=["POST"])
def lock_account(acc_id):
    body = get_body()
    reject_unknown(body, set())
    auth("SecurityAdmin")
    acc = get_account(acc_id)
    with STORE_LOCK:
        if acc["status"] not in ("ENROLLED", "UNENROLLED"):
            raise err_invalid_state("Account cannot be locked from its current state")
        acc["status"] = "LOCKED"
        void_active_grants(acc["id"])
        touch(acc)
        return success(ser(acc))


# ---------------------------------------------------------------------------
# Purchase orders
# ---------------------------------------------------------------------------

def order_to_dict(po):
    return ser(po)


def compute_base(po):
    total = 0
    lines_base = []
    for line in po["lines"]:
        model = None
        for m in db["key_models"].values():
            if m["model_code"] == line["model_code"]:
                model = m
                break
        lb = model["unit_price_cents"] * line["quantity"]
        lines_base.append(lb)
        total += lb
    return total, lines_base


@app.route("/v1/organizations/<org_id>/purchase-orders", methods=["POST"])
def create_purchase_order(org_id):
    body = get_body()
    allowed = {"lines", "shipping_location"}
    reject_unknown(body, allowed)
    require_fields(body, ["lines", "shipping_location"])
    uid, role = auth("ProcurementAdmin")
    org = get_org(org_id)
    lines = body["lines"]
    if not isinstance(lines, list) or len(lines) == 0:
        raise err_invalid_request("lines must be a non-empty array")
    seen = set()
    norm_lines = []
    for line in lines:
        if not isinstance(line, dict):
            raise err_invalid_request("Each line must be an object")
        for k in line:
            if k not in ("model_code", "quantity"):
                raise err_invalid_request("Unknown line field")
        if "model_code" not in line or "quantity" not in line:
            raise err_invalid_request("Line requires model_code and quantity")
        mc = line["model_code"]
        if not isinstance(mc, str):
            raise err_invalid_request("Invalid model_code")
        q = line["quantity"]
        check_int(q, "quantity")
        if q < 1:
            raise err_invalid_request("quantity must be >= 1")
        model = None
        for m in db["key_models"].values():
            if m["model_code"] == mc:
                model = m
                break
        if model is None:
            raise err_not_found(f"Key model {mc} not found")
        if mc in seen:
            raise ApiError("ERR_DUPLICATE", 409, "Duplicate model_code within one order")
        seen.add(mc)
        norm_lines.append({"model_code": mc, "quantity": q})
    shipping = check_str(body["shipping_location"], "shipping_location")
    with STORE_LOCK:
        po = new_entity()
        po.update({
            "organization_id": org["id"],
            "lines": norm_lines,
            "shipping_location": shipping,
            "supply_chain_cert_id": None,
            "created_by": uid,
            "line_count": sum(l["quantity"] for l in norm_lines),
            "quoted_total_cents": 0,
            "final_total_cents": None,
            "credit_applied_cents": 0,
            "quantity_discount_cents": 0,
            "status": "PENDING_APPROVAL",
        })
        base, _ = compute_base(po)
        po["quoted_total_cents"] = base
        db["purchase_orders"][po["id"]] = po
        return success(ser(po), status=201)


@app.route("/v1/organizations/<org_id>/purchase-orders", methods=["GET"])
def list_purchase_orders(org_id):
    auth("SecurityAdmin", "ProcurementAdmin", "LogisticsCoordinator")
    org = get_org(org_id)
    limit, offset = parse_limit_offset()
    items = [p for p in db["purchase_orders"].values() if p["organization_id"] == org["id"]]
    st = request.args.get("status")
    if st is not None:
        check_enum(st, {"PENDING_APPROVAL", "APPROVED", "IN_TRANSIT", "RECEIVED", "QUARANTINED"}, "status")
        items = [p for p in items if p["status"] == st]
    items.sort(key=lambda p: (p["created_at"], p["id"]))
    page, pmeta = paginate([ser(p) for p in items], limit, offset)
    return success(page, response_type="array", pagination=pmeta)


def get_po(org_id, po_id):
    return get_org_child("purchase_orders", org_id, po_id, "Purchase order")


def quarantine_order_cascade(org, po):
    """RECEIVED -> QUARANTINED with the full key/ceremony/account cascade."""
    po["status"] = "QUARANTINED"
    affected = set()
    for key in list(db["security_keys"].values()):
        if key["purchase_order_id"] == po["id"] and \
                key["hardware_status"] in ("PRE_REGISTERED", "ASSIGNED", "DISTRIBUTED"):
            key["hardware_status"] = "REVOKED"
            touch(key)
            for cer in db["enrollments"].values():
                if cer["security_key_id"] == key["id"] and cer["status"] in ("PENDING", "ACTIVE", "EXPIRING"):
                    counted = cer["status"] in ("ACTIVE", "EXPIRING")
                    revoke_ceremony(cer)
                    if counted:
                        affected.add(cer["identity_account_id"])
    for aid in affected:
        recompute_account(db["identity_accounts"][aid])
    touch(po)


@app.route("/v1/organizations/<org_id>/purchase-orders/<po_id>/approve", methods=["POST"])
def approve_purchase_order(org_id, po_id):
    body = get_body()
    reject_unknown(body, {"expected_purchase_order_version"})
    uid, role = auth("SecurityAdmin")
    org, po = get_po(org_id, po_id)
    with STORE_LOCK:
        # OCC: an expected version that no longer matches the order's current
        # version is stale (PRD §2.6), even if the order has since left
        # PENDING_APPROVAL.
        if "expected_purchase_order_version" in body and body["expected_purchase_order_version"] is not None:
            ev = body["expected_purchase_order_version"]
            check_int(ev, "expected_purchase_order_version")
            if ev != po["version"]:
                raise err_stale("Stale purchase order version")
        if po["status"] != "PENDING_APPROVAL":
            raise err_invalid_state("Order is not PENDING_APPROVAL")
        sub = active_subscription(org["id"])
        base, lines_base = compute_base(po)
        if sub is None:
            credit_applied = 0
        else:
            credit_applied = min(base, sub["coverage_cents_remaining"])
        credit_units = math.ceil(credit_applied / CREDIT_UNIT_CENTS) if credit_applied > 0 else 0
        # segregation of duties (priority 8) precedes fiscal capacity (priority 13)
        if uid == po["created_by"]:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES", 422, "Approver must differ from order creator")
        if sub is not None and credit_units > sub["credits_remaining"]:
            raise ApiError("ERR_INSUFFICIENT_CREDITS", 422, "Subscription credit pool too small")
        # final variant: base -> coverage -> per-line discount -> sum
        pool = credit_applied
        remainders = []
        for lb in lines_base:
            absorbed = min(lb, pool)
            pool -= absorbed
            remainders.append(lb - absorbed)
        remainder = base - credit_applied
        lc = po["line_count"]
        if lc >= 100:
            tier_pct = 10
        elif lc >= 50:
            tier_pct = 5
        else:
            tier_pct = 0
        sub_pct = sub["percent_discount"] if sub is not None else 0
        effective_pct = max(sub_pct, tier_pct)
        discount = 0
        for rl in remainders:
            discount += math.floor(rl * effective_pct / 100)
        final_total = remainder - discount
        po["status"] = "APPROVED"
        po["credit_applied_cents"] = credit_applied
        po["quantity_discount_cents"] = discount
        po["final_total_cents"] = final_total
        touch(po)
        if sub is not None and credit_applied > 0:
            sub["credits_used"] += credit_units
            sub["credits_remaining"] -= credit_units
            sub["coverage_cents_used"] += credit_applied
            sub["coverage_cents_remaining"] -= credit_applied
            if sub["credits_remaining"] == 0 and sub["status"] == "ACTIVE":
                sub["status"] = "EXHAUSTED"
            touch(sub)
        return success(ser(po))


@app.route("/v1/organizations/<org_id>/purchase-orders/<po_id>/ship", methods=["POST"])
def ship_purchase_order(org_id, po_id):
    body = get_body()
    reject_unknown(body, {"supply_chain_cert_id"})
    auth("LogisticsCoordinator")
    org, po = get_po(org_id, po_id)
    with STORE_LOCK:
        if po["status"] != "APPROVED":
            raise err_invalid_state("Order is not APPROVED")
        cert = body.get("supply_chain_cert_id")
        if cert is not None and not isinstance(cert, str):
            raise err_invalid_request("supply_chain_cert_id must be a string")
        if org["assurance_tier"] == "HIGH_ASSURANCE" and not cert:
            raise ApiError("ERR_PHISHABLE_PATH_FORBIDDEN", 422,
                           "HIGH_ASSURANCE organizations require a supply-chain certificate at ship time")
        po["status"] = "IN_TRANSIT"
        po["supply_chain_cert_id"] = cert if cert else None
        touch(po)
        return success(ser(po))


@app.route("/v1/organizations/<org_id>/purchase-orders/<po_id>/receive", methods=["POST"])
def receive_purchase_order(org_id, po_id):
    body = get_body()
    reject_unknown(body, set())
    auth("LogisticsCoordinator")
    org, po = get_po(org_id, po_id)
    with STORE_LOCK:
        if po["status"] != "IN_TRANSIT":
            raise err_invalid_state("Order is not IN_TRANSIT")
        po["status"] = "RECEIVED"
        touch(po)
        return success(ser(po))


@app.route("/v1/organizations/<org_id>/purchase-orders/<po_id>/quarantine", methods=["POST"])
def quarantine_purchase_order(org_id, po_id):
    body = get_body()
    reject_unknown(body, set())
    auth("SecurityAdmin")
    org, po = get_po(org_id, po_id)
    with STORE_LOCK:
        if po["status"] != "RECEIVED":
            raise err_invalid_state("Order is not RECEIVED")
        quarantine_order_cascade(org, po)
        return success(ser(po))


@app.route("/v1/organizations/<org_id>/purchase-orders/<po_id>/release", methods=["POST"])
def release_purchase_order(org_id, po_id):
    body = get_body()
    reject_unknown(body, set())
    auth("SecurityAdmin")
    org, po = get_po(org_id, po_id)
    with STORE_LOCK:
        if po["status"] != "QUARANTINED":
            raise err_invalid_state("Order is not QUARANTINED")
        if org["assurance_tier"] == "HIGH_ASSURANCE" and not po.get("supply_chain_cert_id"):
            raise ApiError("ERR_PHISHABLE_PATH_FORBIDDEN", 422,
                           "HIGH_ASSURANCE release requires a supply-chain certificate on the order")
        po["status"] = "RECEIVED"
        touch(po)
        return success(ser(po))


# ---------------------------------------------------------------------------
# Security keys
# ---------------------------------------------------------------------------

def get_key(org_id, kid):
    return get_org_child("security_keys", org_id, kid, "Security key")


def key_model_of(key):
    for m in db["key_models"].values():
        if m["model_code"] == key["model_code"]:
            return m
    return None


@app.route("/v1/organizations/<org_id>/purchase-orders/<po_id>/keys", methods=["POST"])
def preregister_keys(org_id, po_id):
    body = get_body()
    allowed = {"keys", "model_code"}
    reject_unknown(body, allowed)
    require_fields(body, ["keys"])
    auth("LogisticsCoordinator")
    org, po = get_po(org_id, po_id)
    keys_in = body["keys"]
    if not isinstance(keys_in, list) or len(keys_in) == 0:
        raise err_invalid_request("keys must be a non-empty array")
    top_model = body.get("model_code")
    if top_model is not None and not isinstance(top_model, str):
        raise err_invalid_request("model_code must be a string")
    order_models = [l["model_code"] for l in po["lines"]]
    normalized = []
    for k in keys_in:
        if not isinstance(k, dict):
            raise err_invalid_request("Each key must be an object")
        for field in k:
            if field not in ("serial_number", "firmware_version", "model_code"):
                raise err_invalid_request("Unknown key field")
        if "serial_number" not in k or "firmware_version" not in k:
            raise err_invalid_request("Key requires serial_number and firmware_version")
        sn = k["serial_number"]
        fv = k["firmware_version"]
        if not isinstance(sn, str) or not sn:
            raise err_invalid_request("Invalid serial_number")
        if not isinstance(fv, str) or not fv:
            raise err_invalid_request("Invalid firmware_version")
        mc = top_model if top_model is not None else k.get("model_code")
        if mc is None:
            if len(order_models) == 1:
                mc = order_models[0]
            else:
                raise err_invalid_request("model_code is required when the order has multiple line models")
        normalized.append({"serial_number": sn, "firmware_version": fv, "model_code": mc})
    with STORE_LOCK:
        if po["status"] != "APPROVED":
            raise ApiError("ERR_ORDER_STATE", 409, "Order is not APPROVED")
        for k in normalized:
            if k["model_code"] not in order_models:
                raise ApiError("ERR_ORDER_STATE", 409, "Key model_code does not appear in the order's lines")
        batch_serials = set()
        for k in normalized:
            if k["serial_number"] in batch_serials:
                raise ApiError("ERR_DUPLICATE", 409, "Duplicate serial_number in batch")
            batch_serials.add(k["serial_number"])
            for existing in db["security_keys"].values():
                if existing["serial_number"] == k["serial_number"]:
                    raise ApiError("ERR_DUPLICATE", 409, "serial_number already exists")
        created = []
        for k in normalized:
            key = new_entity()
            key.update({
                "purchase_order_id": po["id"],
                "organization_id": org["id"],
                "serial_number": k["serial_number"],
                "model_code": k["model_code"],
                "firmware_version": k["firmware_version"],
                "hardware_status": "PRE_REGISTERED",
                "attestation_status": "UNVERIFIED",
                "assigned_identity_account_id": None,
            })
            db["security_keys"][key["id"]] = key
            created.append(key)
        return success([ser(x) for x in created], status=201, response_type="array")


@app.route("/v1/organizations/<org_id>/security-keys", methods=["GET"])
def list_security_keys(org_id):
    auth("SecurityAdmin", "LogisticsCoordinator", "HelpDeskAgent")
    org = get_org(org_id)
    limit, offset = parse_limit_offset()
    items = [k for k in db["security_keys"].values() if k["organization_id"] == org["id"]]
    f_po = request.args.get("purchase_order_id")
    if f_po is not None:
        items = [k for k in items if k["purchase_order_id"] == f_po]
    f_hs = request.args.get("hardware_status")
    if f_hs is not None:
        check_enum(f_hs, {"PRE_REGISTERED", "ASSIGNED", "DISTRIBUTED", "REVOKED"}, "hardware_status")
        items = [k for k in items if k["hardware_status"] == f_hs]
    f_as = request.args.get("attestation_status")
    if f_as is not None:
        check_enum(f_as, {"UNVERIFIED", "VERIFIED", "FAILED"}, "attestation_status")
        items = [k for k in items if k["attestation_status"] == f_as]
    f_acc = request.args.get("assigned_identity_account_id")
    if f_acc is not None:
        items = [k for k in items if k.get("assigned_identity_account_id") == f_acc]
    f_mc = request.args.get("model_code")
    if f_mc is not None:
        items = [k for k in items if k["model_code"] == f_mc]
    items.sort(key=lambda k: (k["created_at"], k["id"]))
    page, pmeta = paginate([ser(k) for k in items], limit, offset)
    return success(page, response_type="array", pagination=pmeta)


@app.route("/v1/organizations/<org_id>/security-keys/<kid>/assign", methods=["POST"])
def assign_key(org_id, kid):
    body = get_body()
    reject_unknown(body, {"identity_account_id"})
    require_fields(body, ["identity_account_id"])
    auth("SecurityAdmin")
    org, key = get_key(org_id, kid)
    acc_id = body["identity_account_id"]
    if not isinstance(acc_id, str):
        raise err_invalid_request("identity_account_id must be a string")
    acc = db["identity_accounts"].get(acc_id)
    if acc is None or acc["organization_id"] != org["id"]:
        raise err_not_found("Identity account not found")
    with STORE_LOCK:
        if key["hardware_status"] != "PRE_REGISTERED":
            raise err_invalid_state("Key is not PRE_REGISTERED")
        po = db["purchase_orders"][key["purchase_order_id"]]
        if po["status"] != "RECEIVED":
            raise ApiError("ERR_ORDER_STATE", 409, "Order is not RECEIVED")
        emp = db["employees"][acc["employee_id"]]
        if emp["employment_status"] != "ACTIVE":
            raise err_invalid_state("Employee is not ACTIVE")
        model = key_model_of(key)
        if not (set(model["protocols"]) & set(org["idp_protocols"])):
            raise ApiError("ERR_PROTOCOL_MISMATCH", 422,
                           "Key model protocols do not intersect organization idp_protocols")
        key["hardware_status"] = "ASSIGNED"
        key["assigned_identity_account_id"] = acc["id"]
        touch(key)
        return success(ser(key))


@app.route("/v1/organizations/<org_id>/security-keys/<kid>/mark-distributed", methods=["POST"])
def mark_distributed(org_id, kid):
    body = get_body()
    reject_unknown(body, set())
    auth("LogisticsCoordinator")
    org, key = get_key(org_id, kid)
    with STORE_LOCK:
        if key["hardware_status"] != "ASSIGNED":
            raise err_invalid_state("Key is not ASSIGNED")
        po = db["purchase_orders"][key["purchase_order_id"]]
        if po["status"] != "RECEIVED":
            raise ApiError("ERR_ORDER_STATE", 409, "Order is not RECEIVED")
        key["hardware_status"] = "DISTRIBUTED"
        touch(key)
        return success(ser(key))


@app.route("/v1/organizations/<org_id>/security-keys/<kid>/return-to-stock", methods=["POST"])
def return_to_stock(org_id, kid):
    body = get_body()
    reject_unknown(body, set())
    auth("SecurityAdmin")
    org, key = get_key(org_id, kid)
    with STORE_LOCK:
        if key["hardware_status"] != "ASSIGNED":
            raise err_invalid_state("Key is not ASSIGNED")
        for cer in db["enrollments"].values():
            if cer["security_key_id"] == key["id"] and cer["status"] in ("PENDING", "ACTIVE", "EXPIRING"):
                raise err_invalid_state("A ceremony binds this key")
        key["hardware_status"] = "PRE_REGISTERED"
        key["assigned_identity_account_id"] = None
        touch(key)
        return success(ser(key))


@app.route("/v1/organizations/<org_id>/security-keys/<kid>/revoke", methods=["POST"])
def revoke_key_endpoint(org_id, kid):
    body = get_body()
    reject_unknown(body, set())
    auth("SecurityAdmin")
    org, key = get_key(org_id, kid)
    with STORE_LOCK:
        if key["hardware_status"] not in ("PRE_REGISTERED", "ASSIGNED", "DISTRIBUTED"):
            raise err_invalid_state("Key is already REVOKED")
        revoke_key(key)
        return success(ser(key))


@app.route("/v1/organizations/<org_id>/security-keys/<kid>/attest", methods=["POST"])
def attest_key(org_id, kid):
    body = get_body()
    reject_unknown(body, set())
    auth("SecurityAdmin")
    org, key = get_key(org_id, kid)
    with STORE_LOCK:
        if key["attestation_status"] != "UNVERIFIED":
            raise err_invalid_state("Key is not UNVERIFIED")
        if key["hardware_status"] == "REVOKED":
            raise err_invalid_state("Key is REVOKED")
        po = db["purchase_orders"][key["purchase_order_id"]]
        if org["assurance_tier"] == "HIGH_ASSURANCE" and not po.get("supply_chain_cert_id"):
            raise ApiError("ERR_PHISHABLE_PATH_FORBIDDEN", 422,
                           "HIGH_ASSURANCE attestation requires a supply-chain certificate on the order")
        approved = key["firmware_version"] in org["approved_firmware_versions"] or (
            org["assurance_tier"] == "STANDARD" and len(org["approved_firmware_versions"]) == 0)
        if approved:
            key["attestation_status"] = "VERIFIED"
            touch(key)
        else:
            key["attestation_status"] = "FAILED"
            touch(key)
            if org["assurance_tier"] == "HIGH_ASSURANCE" and po["status"] == "RECEIVED":
                quarantine_order_cascade(org, po)
        return success(ser(key))


# ---------------------------------------------------------------------------
# Enrollment ceremonies
# ---------------------------------------------------------------------------

def get_enrollment(acc_id, eid):
    acc = get_account(acc_id)
    cer = db["enrollments"].get(eid)
    if cer is None or cer["identity_account_id"] != acc["id"]:
        raise err_not_found("Enrollment not found")
    return acc, cer


@app.route("/v1/identity-accounts/<acc_id>/enrollments", methods=["POST"])
def create_enrollment(acc_id):
    body = get_body()
    reject_unknown(body, {"security_key_id"})
    require_fields(body, ["security_key_id"])
    auth("SecurityAdmin")
    acc = get_account(acc_id)
    skid = body["security_key_id"]
    if not isinstance(skid, str):
        raise err_invalid_request("security_key_id must be a string")
    key = db["security_keys"].get(skid)
    if key is None or key["organization_id"] != acc["organization_id"]:
        raise err_not_found("Security key not found")
    with STORE_LOCK:
        org = db["organizations"][acc["organization_id"]]
        model = key_model_of(key)
        if model is None or not (set(model["protocols"]) & set(org["idp_protocols"])):
            raise ApiError("ERR_PROTOCOL_MISMATCH", 422,
                           "Key model protocols do not intersect organization idp_protocols")
        cer = new_entity()
        cer.update({
            "identity_account_id": acc["id"],
            "security_key_id": key["id"],
            "status": "PENDING",
            "activated_at": None,
            "expires_at": None,
            "renewal_count": 0,
            "revoked_at": None,
        })
        db["enrollments"][cer["id"]] = cer
        return success(ser(cer), status=201)


@app.route("/v1/identity-accounts/<acc_id>/enrollments", methods=["GET"])
def list_enrollments(acc_id):
    auth("SecurityAdmin", "HelpDeskAgent")
    acc = get_account(acc_id)
    limit, offset = parse_limit_offset()
    items = [e for e in db["enrollments"].values() if e["identity_account_id"] == acc["id"]]
    st = request.args.get("status")
    if st is not None:
        check_enum(st, {"PENDING", "ACTIVE", "EXPIRING", "REVOKED", "SUPERSEDED"}, "status")
        items = [e for e in items if e["status"] == st]
    skid = request.args.get("security_key_id")
    if skid is not None:
        items = [e for e in items if e["security_key_id"] == skid]
    items.sort(key=lambda e: (e["created_at"], e["id"]))
    page, pmeta = paginate([ser(e) for e in items], limit, offset)
    return success(page, response_type="array", pagination=pmeta)


@app.route("/v1/identity-accounts/<acc_id>/enrollments/<eid>/activate", methods=["POST"])
def activate_enrollment(acc_id, eid):
    body = get_body()
    reject_unknown(body, {"expected_identity_account_version"})
    auth("SecurityAdmin")
    acc, cer = get_enrollment(acc_id, eid)
    with STORE_LOCK:
        if cer["status"] != "PENDING":
            raise err_invalid_state("Ceremony is not PENDING")
        if "expected_identity_account_version" in body and body["expected_identity_account_version"] is not None:
            ev = body["expected_identity_account_version"]
            check_int(ev, "expected_identity_account_version")
            if ev != acc["version"]:
                raise err_stale("Stale identity account version")
        key = db["security_keys"][cer["security_key_id"]]
        if key["hardware_status"] != "DISTRIBUTED" or key["attestation_status"] != "VERIFIED":
            raise err_invalid_state("Key is not DISTRIBUTED and VERIFIED")
        if key.get("assigned_identity_account_id") != acc["id"]:
            raise err_invalid_state("Key is not assigned to this account")
        if acc["status"] not in ("UNENROLLED", "ENROLLED", "LOCKED"):
            raise err_invalid_state("Account state does not permit activation")
        emp = db["employees"][acc["employee_id"]]
        if emp["employment_status"] != "ACTIVE":
            raise err_invalid_state("Employee is not ACTIVE")
        for other in db["enrollments"].values():
            if other["id"] != cer["id"] and other["security_key_id"] == key["id"] \
                    and other["status"] in ("ACTIVE", "EXPIRING"):
                raise err_invalid_state("Another ceremony already binds this key")
        n = now()
        cer["status"] = "ACTIVE"
        cer["activated_at"] = n
        cer["expires_at"] = n + timedelta(days=ENROLLMENT_VALIDITY_DAYS)
        cer["renewal_count"] = 0
        touch(cer)
        recompute_account(acc)
        if acc["status"] in ("UNENROLLED", "LOCKED"):
            acc["status"] = "ENROLLED"
        touch(acc)
        return success(ser(cer))


@app.route("/v1/identity-accounts/<acc_id>/enrollments/<eid>/renew", methods=["POST"])
def renew_enrollment(acc_id, eid):
    body = get_body()
    reject_unknown(body, set())
    auth("SecurityAdmin")
    acc, cer = get_enrollment(acc_id, eid)
    with STORE_LOCK:
        if cer["status"] != "EXPIRING" or cer["renewal_count"] != 0:
            raise err_invalid_state("Ceremony cannot be renewed from its current state")
        key = db["security_keys"][cer["security_key_id"]]
        if key["hardware_status"] != "DISTRIBUTED" or key["attestation_status"] != "VERIFIED":
            raise err_invalid_state("Key is not DISTRIBUTED and VERIFIED")
        n = now()
        cer["status"] = "ACTIVE"
        cer["expires_at"] = n + timedelta(days=ENROLLMENT_VALIDITY_DAYS)
        cer["renewal_count"] = 1
        touch(cer)
        return success(ser(cer))


@app.route("/v1/identity-accounts/<acc_id>/enrollments/<eid>/revoke", methods=["POST"])
def revoke_enrollment(acc_id, eid):
    body = get_body()
    reject_unknown(body, set())
    auth("SecurityAdmin", "HelpDeskAgent")
    acc, cer = get_enrollment(acc_id, eid)
    with STORE_LOCK:
        if cer["status"] not in ("PENDING", "ACTIVE", "EXPIRING"):
            raise err_invalid_state("Ceremony is already in a terminal state")
        counted = cer["status"] in ("ACTIVE", "EXPIRING")
        revoke_ceremony(cer)
        if counted:
            recompute_account(acc)
        return success(ser(cer))


# ---------------------------------------------------------------------------
# Temporary access grants
# ---------------------------------------------------------------------------

def derived_grant_status(g):
    if g["status"] == "ACTIVE" and now() >= g["expires_at"]:
        return "EXPIRED"
    return g["status"]


def ser_grant(g):
    out = ser(g)
    out["status"] = derived_grant_status(g)
    return out


def get_grant(acc_id, tid):
    acc = get_account(acc_id)
    g = db["temp_grants"].get(tid)
    if g is None or g["identity_account_id"] != acc["id"]:
        raise err_not_found("Temporary access grant not found")
    return acc, g


def validate_grant_request(org, acc, method, duration_hours):
    if method == "TOTP" and org["authentication_policy"] == "PHISHING_RESISTANT":
        raise ApiError("ERR_PHISHABLE_PATH_FORBIDDEN", 422,
                       "TOTP temporary access is forbidden under PHISHING_RESISTANT policy")
    if duration_hours < 1 or duration_hours > 72:
        raise ApiError("ERR_GRANT_WINDOW", 422, "duration_hours must be between 1 and 72")
    for g in db["temp_grants"].values():
        if g["identity_account_id"] == acc["id"] and derived_grant_status(g) == "ACTIVE":
            raise ApiError("ERR_GRANT_WINDOW", 422, "An ACTIVE grant already exists for the account")


def create_grant(acc, method, duration_hours):
    n = now()
    g = new_entity()
    g.update({
        "identity_account_id": acc["id"],
        "method": method,
        "starts_at": n,
        "duration_hours": duration_hours,
        "expires_at": n + timedelta(hours=duration_hours),
        "status": "ACTIVE",
    })
    db["temp_grants"][g["id"]] = g
    return g


@app.route("/v1/identity-accounts/<acc_id>/temporary-access", methods=["POST"])
def issue_grant(acc_id):
    body = get_body()
    reject_unknown(body, {"method", "duration_hours"})
    require_fields(body, ["method", "duration_hours"])
    auth("HelpDeskAgent")
    acc = get_account(acc_id)
    method = check_enum(body["method"], GRANT_METHODS, "method")
    duration = body["duration_hours"]
    check_int(duration, "duration_hours")
    with STORE_LOCK:
        org = db["organizations"][acc["organization_id"]]
        validate_grant_request(org, acc, method, duration)
        g = create_grant(acc, method, duration)
        return success(ser_grant(g), status=201)


@app.route("/v1/identity-accounts/<acc_id>/temporary-access", methods=["GET"])
def list_grants(acc_id):
    auth("SecurityAdmin", "HelpDeskAgent")
    acc = get_account(acc_id)
    limit, offset = parse_limit_offset()
    items = [g for g in db["temp_grants"].values() if g["identity_account_id"] == acc["id"]]
    st = request.args.get("status")
    if st is not None:
        check_enum(st, {"ACTIVE", "USED", "VOIDED", "EXPIRED"}, "status")
        items = [g for g in items if derived_grant_status(g) == st]
    items.sort(key=lambda g: (g["created_at"], g["id"]))
    page, pmeta = paginate([ser_grant(g) for g in items], limit, offset)
    return success(page, response_type="array", pagination=pmeta)


@app.route("/v1/identity-accounts/<acc_id>/temporary-access/<tid>/use", methods=["POST"])
def use_grant(acc_id, tid):
    body = get_body()
    reject_unknown(body, set())
    uid, role = auth("Employee")
    acc, g = get_grant(acc_id, tid)
    with STORE_LOCK:
        if g["status"] != "ACTIVE":
            raise err_invalid_state("Grant is not ACTIVE")
        emp = db["employees"].get(uid)
        if emp is None or emp["identity_account_id"] != acc["id"]:
            raise err_unauthorized("Grant does not belong to the acting employee")
        if now() >= g["expires_at"]:
            raise ApiError("ERR_GRANT_WINDOW", 422, "Grant has expired")
        g["status"] = "USED"
        touch(g)
        return success(ser_grant(g))


@app.route("/v1/identity-accounts/<acc_id>/temporary-access/<tid>/void", methods=["POST"])
def void_grant(acc_id, tid):
    body = get_body()
    reject_unknown(body, set())
    auth("SecurityAdmin", "HelpDeskAgent")
    acc, g = get_grant(acc_id, tid)
    with STORE_LOCK:
        if g["status"] != "ACTIVE":
            raise err_invalid_state("Grant is not ACTIVE")
        g["status"] = "VOIDED"
        touch(g)
        return success(ser_grant(g))


# ---------------------------------------------------------------------------
# Subscriptions
# ---------------------------------------------------------------------------

@app.route("/v1/organizations/<org_id>/subscriptions", methods=["POST"])
def create_subscription(org_id):
    body = get_body()
    allowed = {"tier", "refresh_interval_days", "replacement_credits_total",
               "coverage_cents_total", "percent_discount"}
    reject_unknown(body, allowed)
    require_fields(body, ["tier", "refresh_interval_days", "replacement_credits_total"])
    auth("ProcurementAdmin")
    org = get_org(org_id)
    tier = check_enum(body["tier"], {"BASIC", "ENTERPRISE"}, "tier")
    rid = check_int(body["refresh_interval_days"], "refresh_interval_days")
    if rid <= 0:
        raise err_invalid_request("refresh_interval_days must be > 0")
    rct = check_int(body["replacement_credits_total"], "replacement_credits_total")
    if rct <= 0:
        raise err_invalid_request("replacement_credits_total must be > 0")
    cct = body.get("coverage_cents_total", 0)
    check_int(cct, "coverage_cents_total")
    if cct < 0:
        raise err_invalid_request("coverage_cents_total must be >= 0")
    pd_ = body.get("percent_discount", 0)
    if isinstance(pd_, bool) or not isinstance(pd_, (int, float)):
        raise err_invalid_request("percent_discount must be a number")
    if pd_ < 0 or pd_ > 100:
        raise err_invalid_request("percent_discount must be between 0 and 100")
    with STORE_LOCK:
        if active_subscription(org["id"]) is not None:
            raise ApiError("ERR_DUPLICATE", 409, "Organization already has an ACTIVE subscription")
        n = now()
        sub = new_entity()
        sub.update({
            "organization_id": org["id"],
            "tier": tier,
            "refresh_interval_days": rid,
            "replacement_credits_total": rct,
            "credits_used": 0,
            "credits_remaining": rct,
            "coverage_cents_total": cct,
            "coverage_cents_used": 0,
            "coverage_cents_remaining": cct,
            "percent_discount": pd_,
            "status": "ACTIVE",
            "current_period_start": n,
            "current_period_end": n + timedelta(days=rid),
        })
        db["subscriptions"][sub["id"]] = sub
        return success(ser(sub), status=201)


@app.route("/v1/organizations/<org_id>/subscriptions", methods=["GET"])
def list_subscriptions(org_id):
    auth("SecurityAdmin", "ProcurementAdmin")
    org = get_org(org_id)
    limit, offset = parse_limit_offset()
    items = [s for s in db["subscriptions"].values() if s["organization_id"] == org["id"]]
    st = request.args.get("status")
    if st is not None:
        check_enum(st, {"ACTIVE", "EXHAUSTED", "EXPIRED"}, "status")
        items = [s for s in items if s["status"] == st]
    items.sort(key=lambda s: (s["created_at"], s["id"]))
    page, pmeta = paginate([ser(s) for s in items], limit, offset)
    return success(page, response_type="array", pagination=pmeta)


# ---------------------------------------------------------------------------
# Replacement key selector (shared by help desk and refresh runs)
# ---------------------------------------------------------------------------

def select_replacement_key(org):
    connectors_pool = set()
    for d in db["devices"].values():
        if d["organization_id"] == org["id"] and d["lifecycle_status"] == "ACTIVE":
            connectors_pool |= set(d["connectors"])
    candidates = []
    for key in db["security_keys"].values():
        if key["organization_id"] != org["id"]:
            continue
        if key["hardware_status"] != "PRE_REGISTERED":
            continue
        po = db["purchase_orders"][key["purchase_order_id"]]
        if po["status"] != "RECEIVED":
            continue
        model = key_model_of(key)
        if model is None:
            continue
        if not (set(model["protocols"]) & set(org["idp_protocols"])):
            continue
        if not (set(model["connectors"]) & connectors_pool):
            continue
        candidates.append((model["unit_price_cents"], key["created_at"], key))
    if not candidates:
        return None
    # Deterministic (PRD §3.9): cheapest first, ties by created_at ascending;
    # the logical clock makes created_at ties common, so the final tie-break
    # is registration order (dict insertion order), not the random UUID.
    candidates.sort(key=lambda t: (t[0], t[1]))
    return candidates[0][2]


# ---------------------------------------------------------------------------
# Help desk cases
# ---------------------------------------------------------------------------

CASE_CATEGORIES = {"LOST_KEY", "LOCKOUT", "OTHER"}
CASE_RESOLUTIONS = {"REVOKED_AND_REPLACED", "TEMP_ACCESS_ISSUED", "REJECTED"}


@app.route("/v1/help-desk-cases", methods=["POST"])
def create_case():
    body = get_body()
    allowed = {"identity_account_id", "category", "description"}
    reject_unknown(body, allowed)
    require_fields(body, ["identity_account_id", "category", "description"])
    uid, role = auth("HelpDeskAgent")
    acc_id = body["identity_account_id"]
    if not isinstance(acc_id, str):
        raise err_invalid_request("identity_account_id must be a string")
    acc = db["identity_accounts"].get(acc_id)
    if acc is None:
        raise err_not_found("Identity account not found")
    category = check_enum(body["category"], CASE_CATEGORIES, "category")
    description = check_str(body["description"], "description")
    with STORE_LOCK:
        case = new_entity()
        case.update({
            "identity_account_id": acc["id"],
            "category": category,
            "description": description,
            "opened_by_agent_id": uid,
            "resolution": None,
            "resolved_by_agent_id": None,
            "status": "OPEN",
        })
        db["help_desk_cases"][case["id"]] = case
        return success(ser(case), status=201)


@app.route("/v1/help-desk-cases", methods=["GET"])
def list_cases():
    auth("HelpDeskAgent", "SecurityAdmin")
    limit, offset = parse_limit_offset()
    items = list(db["help_desk_cases"].values())
    f_acc = request.args.get("identity_account_id")
    if f_acc is not None:
        items = [c for c in items if c["identity_account_id"] == f_acc]
    st = request.args.get("status")
    if st is not None:
        check_enum(st, {"OPEN", "PENDING_REVIEW", "RESOLVED", "REJECTED"}, "status")
        items = [c for c in items if c["status"] == st]
    cat = request.args.get("category")
    if cat is not None:
        check_enum(cat, CASE_CATEGORIES, "category")
        items = [c for c in items if c["category"] == cat]
    items.sort(key=lambda c: (c["created_at"], c["id"]))
    page, pmeta = paginate([ser(c) for c in items], limit, offset)
    return success(page, response_type="array", pagination=pmeta)


def get_case(case_id):
    case = db["help_desk_cases"].get(case_id)
    if case is None:
        raise err_not_found("Help desk case not found")
    return case


@app.route("/v1/help-desk-cases/<case_id>/submit-review", methods=["POST"])
def submit_review(case_id):
    body = get_body()
    reject_unknown(body, set())
    auth("HelpDeskAgent")
    case = get_case(case_id)
    with STORE_LOCK:
        if case["status"] != "OPEN":
            raise err_invalid_state("Case is not OPEN")
        if case["category"] not in ("LOST_KEY", "LOCKOUT"):
            raise err_invalid_state("Case category cannot be submitted for review")
        case["status"] = "PENDING_REVIEW"
        touch(case)
        return success(ser(case))


@app.route("/v1/help-desk-cases/<case_id>/resolve", methods=["POST"])
def resolve_case(case_id):
    body = get_body()
    allowed = {"resolution", "method", "duration_hours"}
    reject_unknown(body, allowed)
    require_fields(body, ["resolution"])
    uid, role = auth("HelpDeskAgent")
    case = get_case(case_id)
    resolution = check_enum(body["resolution"], CASE_RESOLUTIONS, "resolution")
    method = body.get("method")
    duration = body.get("duration_hours")
    if method is not None:
        check_enum(method, GRANT_METHODS, "method")
    if duration is not None:
        check_int(duration, "duration_hours")
    with STORE_LOCK:
        if case["status"] == "OPEN":
            if resolution != "REJECTED":
                raise err_invalid_state("An OPEN case may only be resolved with REJECTED")
        elif case["status"] != "PENDING_REVIEW":
            raise err_invalid_state("Case is already in a terminal state")
        if uid == case["opened_by_agent_id"]:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES", 422, "Resolver must differ from opener")
        acc = db["identity_accounts"][case["identity_account_id"]]
        org = db["organizations"][acc["organization_id"]]
        if resolution == "REVOKED_AND_REPLACED":
            if not (set(org["idp_protocols"]) & HARDWARE_PROTOCOLS):
                raise ApiError("ERR_PHISHABLE_PATH_FORBIDDEN", 422,
                               "Organization accepts no hardware protocol; recovery would be phishable-only")
            replacement = select_replacement_key(org)
            if replacement is None:
                raise ApiError("ERR_NO_ELIGIBLE_KEY", 422, "No eligible replacement key")
            # revoke every ACTIVE/EXPIRING ceremony and its key
            for cer in list(db["enrollments"].values()):
                if cer["identity_account_id"] == acc["id"] and cer["status"] in ("ACTIVE", "EXPIRING"):
                    revoke_ceremony(cer)
                    old_key = db["security_keys"][cer["security_key_id"]]
                    if old_key["hardware_status"] in ("PRE_REGISTERED", "ASSIGNED", "DISTRIBUTED"):
                        old_key["hardware_status"] = "REVOKED"
                        touch(old_key)
            # auto-assign replacement and create a new PENDING ceremony
            replacement["hardware_status"] = "ASSIGNED"
            replacement["assigned_identity_account_id"] = acc["id"]
            touch(replacement)
            cer = new_entity()
            cer.update({
                "identity_account_id": acc["id"],
                "security_key_id": replacement["id"],
                "status": "PENDING",
                "activated_at": None,
                "expires_at": None,
                "renewal_count": 0,
                "revoked_at": None,
            })
            db["enrollments"][cer["id"]] = cer
            recompute_account(acc)
        elif resolution == "TEMP_ACCESS_ISSUED":
            if method is None:
                raise err_invalid_request("method is required for TEMP_ACCESS_ISSUED")
            if duration is None:
                raise err_invalid_request("duration_hours is required for TEMP_ACCESS_ISSUED")
            validate_grant_request(org, acc, method, duration)
            create_grant(acc, method, duration)
        # REJECTED or resolved: finalize the case
        case["status"] = "REJECTED" if resolution == "REJECTED" else "RESOLVED"
        case["resolution"] = resolution
        case["resolved_by_agent_id"] = uid
        touch(case)
        return success(ser(case))


# ---------------------------------------------------------------------------
# Periodic run
# ---------------------------------------------------------------------------

@app.route("/v1/_ops/run_periodic", methods=["POST"])
def run_periodic():
    body = get_body()
    reject_unknown(body, {"organization_id", "expire"})
    auth("PlatformAdmin")
    scope_org = body.get("organization_id")
    if scope_org is not None and not isinstance(scope_org, str):
        raise err_invalid_request("organization_id must be a string")
    expire_flag = body.get("expire", False)
    if not isinstance(expire_flag, bool):
        raise err_invalid_request("expire must be a boolean")
    with STORE_LOCK:
        n = now()
        counts = {
            "enrollments_expiring": 0,
            "enrollments_expired": 0,
            "grants_expired": 0,
            "refreshed_accounts": 0,
            "subscriptions_exhausted": 0,
            "subscriptions_expired": 0,
        }

        # 1. Enrollment expiry sweep
        for cer in sorted(db["enrollments"].values(), key=lambda c: (c["created_at"], c["id"])):
            if scope_org is not None:
                acc = db["identity_accounts"][cer["identity_account_id"]]
                if acc["organization_id"] != scope_org:
                    continue
            if cer["status"] == "ACTIVE" and n >= cer["expires_at"] - timedelta(days=EXPIRING_WINDOW_DAYS) and n <= cer["expires_at"]:
                cer["status"] = "EXPIRING"
                cer["renewal_count"] = 0
                touch(cer)
                counts["enrollments_expiring"] += 1
        for cer in sorted(db["enrollments"].values(), key=lambda c: (c["created_at"], c["id"])):
            if scope_org is not None:
                acc = db["identity_accounts"][cer["identity_account_id"]]
                if acc["organization_id"] != scope_org:
                    continue
            if cer["status"] in ("ACTIVE", "EXPIRING") and n > cer["expires_at"]:
                revoke_ceremony(cer)
                recompute_account(db["identity_accounts"][cer["identity_account_id"]])
                counts["enrollments_expired"] += 1

        # 2. Temporary-access expiry sweep
        for g in db["temp_grants"].values():
            if scope_org is not None:
                acc = db["identity_accounts"][g["identity_account_id"]]
                if acc["organization_id"] != scope_org:
                    continue
            if g["status"] == "ACTIVE" and n >= g["expires_at"]:
                g["status"] = "EXPIRED"
                touch(g)
                counts["grants_expired"] += 1

        # 3. Refresh runs + subscription expiry
        subs = [s for s in db["subscriptions"].values()
                if (scope_org is None or s["organization_id"] == scope_org)
                and s["status"] in ("ACTIVE", "EXHAUSTED")
                and n >= s["current_period_end"]]
        subs.sort(key=lambda s: (s["created_at"], s["id"]))
        for sub in subs:
            org = db["organizations"][sub["organization_id"]]
            refreshed_any = False
            if sub["status"] == "ACTIVE":
                # eligible accounts: >= 1 ceremony in ACTIVE/EXPIRING
                eligible = []
                for acc in db["identity_accounts"].values():
                    if acc["organization_id"] != org["id"]:
                        continue
                    act = [c for c in db["enrollments"].values()
                           if c["identity_account_id"] == acc["id"] and c["status"] in ("ACTIVE", "EXPIRING")]
                    if not act:
                        continue
                    oldest = min(c["expires_at"] for c in act)
                    eligible.append((oldest, acc["created_at"], acc["id"], acc))
                eligible.sort(key=lambda t: (t[0], t[1], t[2]))
                for _, _, _, acc in eligible:
                    if sub["credits_remaining"] < REFRESH_CREDIT_COST:
                        break
                    key = select_replacement_key(org)
                    if key is None:
                        continue
                    # activate replacement without the distribution preconditions
                    key["hardware_status"] = "DISTRIBUTED"
                    key["assigned_identity_account_id"] = acc["id"]
                    touch(key)
                    cer = new_entity()
                    cer.update({
                        "identity_account_id": acc["id"],
                        "security_key_id": key["id"],
                        "status": "ACTIVE",
                        "activated_at": n,
                        "expires_at": n + timedelta(days=ENROLLMENT_VALIDITY_DAYS),
                        "renewal_count": 0,
                        "revoked_at": None,
                    })
                    db["enrollments"][cer["id"]] = cer
                    # supersede the old ceremony/ceremonies and revoke old keys
                    for old in db["enrollments"].values():
                        if old["identity_account_id"] == acc["id"] and old["id"] != cer["id"] \
                                and old["status"] in ("ACTIVE", "EXPIRING"):
                            old["status"] = "SUPERSEDED"
                            touch(old)
                            old_key = db["security_keys"][old["security_key_id"]]
                            if old_key["hardware_status"] in ("PRE_REGISTERED", "ASSIGNED", "DISTRIBUTED"):
                                old_key["hardware_status"] = "REVOKED"
                                touch(old_key)
                    recompute_account(acc)
                    sub["credits_used"] += REFRESH_CREDIT_COST
                    sub["credits_remaining"] -= REFRESH_CREDIT_COST
                    if sub["credits_remaining"] == 0:
                        sub["status"] = "EXHAUSTED"
                        counts["subscriptions_exhausted"] += 1
                    refreshed_any = True
                    counts["refreshed_accounts"] += 1
            if expire_flag:
                sub["status"] = "EXPIRED"
                touch(sub)
                counts["subscriptions_expired"] += 1
            elif sub["status"] == "ACTIVE":
                if not refreshed_any:
                    sub["status"] = "EXPIRED"
                    touch(sub)
                    counts["subscriptions_expired"] += 1
                else:
                    sub["current_period_start"] = sub["current_period_end"]
                    sub["current_period_end"] = sub["current_period_end"] + timedelta(days=sub["refresh_interval_days"])
                    touch(sub)
            elif sub["status"] == "EXHAUSTED" and refreshed_any:
                sub["current_period_start"] = sub["current_period_end"]
                sub["current_period_end"] = sub["current_period_end"] + timedelta(days=sub["refresh_interval_days"])
                touch(sub)
            else:
                touch(sub)
        return success(counts)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
