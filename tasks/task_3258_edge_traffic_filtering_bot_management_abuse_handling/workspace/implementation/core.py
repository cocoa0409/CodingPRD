"""Core shared infrastructure: in-memory store, logical clock, errors,
response envelope, auth, common validators, serializers and clock sweep.

All structural names (headers, envelope fields, pagination params, error ids)
come from SCAFFOLD.yaml / PRD.md:
- headers: X-User-Role, X-User-ID
- envelope: meta{api_request_id, api_request_timestamp}, response_type, data
- error body: data{error_id, message}
- pagination: limit/offset/total_count/has_more; defaults limit=10, min=1,
  max=100, offset=0
"""
import random
import re
import string
import uuid
from datetime import datetime, timedelta, timezone

from flask import jsonify, request

# ---------------------------------------------------------------------------
# Constants (pinned platform values from SCAFFOLD.yaml calculations section)
# ---------------------------------------------------------------------------

SUPPORT_SLA_HOURS = {"FREE": 72, "PRO": 24, "BUSINESS": 8, "ENTERPRISE": 4}

PLAN_FEATURES = {
    "FREE": {
        "rate_limiting": False, "bot_classification": False,
        "managed_rulesets": False, "dos_sensitivity": False,
        "origin_shield": False, "cache_reserve": False,
    },
    "PRO": {
        "rate_limiting": True, "bot_classification": True,
        "managed_rulesets": True, "dos_sensitivity": True,
        "origin_shield": True, "cache_reserve": False,
    },
    "BUSINESS": {
        "rate_limiting": True, "bot_classification": True,
        "managed_rulesets": True, "dos_sensitivity": True,
        "origin_shield": True, "cache_reserve": True,
    },
    "ENTERPRISE": {
        "rate_limiting": True, "bot_classification": True,
        "managed_rulesets": True, "dos_sensitivity": True,
        "origin_shield": True, "cache_reserve": True,
    },
}

AUTO_THRESHOLD_MULTIPLIER = 20
SENSITIVITY_MULTIPLIER = {"HIGH": 0.5, "DEFAULT": 1.0, "LOW": 2.0}
AUTO_MITIGATION_TTL_HOURS = 4

HONEYPOT_LOOKBACK_SECONDS = 86400
HUMAN_SCORE = 30
VERIFIED_SCORE = 99
FIGHT_MODE_MIN_SCORE = 1
FIGHT_MODE_MAX_SCORE = 29

RATE_LIMIT_WINDOW_SECONDS = 60

SHIELD_PER_ENTRY_COMPLETION_SECONDS = 900
UNSHIELDED_PER_ENTRY_COMPLETION_SECONDS = 0

CATEGORY_BASE = {
    "CSAM": 1000, "PHISHING": 800, "MALWARE": 700,
    "COPYRIGHT": 500, "SPAM": 300, "OTHER": 100,
}

BLOCK_BASE_SECONDS = 3600
PROVISIONAL_WINDOW_SECONDS = 900
RELEASE_GRACE_FRACTION = 0.025

ROLES = {"PlatformAdmin", "ZoneAdmin", "TrustSafetyAnalyst",
         "NetworkPlanner", "Anonymous"}

PLAN_TIERS = {"FREE", "PRO", "BUSINESS", "ENTERPRISE"}
ONBOARDING_TYPES = {"FULL", "PARTIAL"}
DOS_SENSITIVITIES = {"DEFAULT", "LOW", "HIGH"}
RECORD_TYPES = {"A", "AAAA", "CNAME", "TXT"}
PROXYABLE_TYPES = {"A", "AAAA", "CNAME"}
CDN_SUFFIX = ".cdn.example.net"
RULE_KINDS = {"FIREWALL_FILTER", "RATE_LIMIT"}
RULE_ACTIONS = {"ALLOW", "BLOCK"}
RULE_STATUSES = {"ACTIVE", "DISABLED"}
SUB_SENSITIVITIES = {"LOW", "MEDIUM", "HIGH"}
SUB_STATUSES = {"ACTIVE", "UNSUBSCRIBED"}
OVERRIDE_ACTIONS = {"DISABLE", "CHALLENGE"}
OVERRIDE_STATUSES = {"ACTIVE", "REVERTED"}
BAND_ACTIONS = {"BLOCK", "CHALLENGE", "LOG"}
BAND_STATUSES = {"ACTIVE", "DISABLED"}
PURGE_TYPES = {"PURGE_ALL", "PURGE_URL"}
IP_VERSIONS = {"V4", "V6"}
ABUSE_CATEGORIES = {"PHISHING", "MALWARE", "CSAM", "SPAM", "COPYRIGHT", "OTHER"}
DISPOSITIONS = {"FORWARD", "TAKE_ACTION"}

START_CLOCK_UTC = "2026-09-01T00:00:00Z"

# ---------------------------------------------------------------------------
# In-memory store (empty at boot; no seeding)
# ---------------------------------------------------------------------------


def parse_dt(s):
    """Parse an ISO-8601 UTC timestamp; return None when unparseable."""
    if not isinstance(s, str):
        return None
    try:
        txt = s.strip()
        if txt.endswith("Z"):
            txt = txt[:-1] + "+00:00"
        d = datetime.fromisoformat(txt)
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc)
    except (ValueError, AttributeError):
        return None


class DB:
    def __init__(self):
        self.accounts = {}
        self.pops = {}
        self.zones = {}
        self.ddos_events = {}
        self.purge_requests = {}
        self.ip_blocks = {}
        self.abuse_reports = {}
        # internal logs keyed by zone id
        self.honeypot_logs = {}   # zone_id -> [{hit_at, client_ip}]
        self.rule_hit_logs = {}   # (zone_id, rule_name) -> [occurred_at]
        # logical clock (fixed startup default, never wall clock)
        self.clock_utc = parse_dt(START_CLOCK_UTC)


db = DB()

# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------


def fmt_ts(d):
    """ISO 8601 UTC with three fractional digits, trailing Z."""
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + f"{d.microsecond // 1000:03d}Z"


def now():
    return db.clock_utc


def now_str():
    return fmt_ts(db.clock_utc)


def round_half_up(x):
    """Round half up to the nearest integer (returned as int)."""
    import decimal
    return int(decimal.Decimal(repr(x)).quantize(
        decimal.Decimal("1"), rounding=decimal.ROUND_HALF_UP))

# ---------------------------------------------------------------------------
# Errors and envelope
# ---------------------------------------------------------------------------


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def _meta():
    rid = "req_" + "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
    return {"api_request_id": rid,
            "api_request_timestamp": fmt_ts(datetime.now(timezone.utc))}


def success(data, status=200, pagination=None):
    body = {"meta": _meta(),
            "response_type": "array" if isinstance(data, list) else "object",
            "data": data}
    if pagination:
        body["meta"].update(pagination)
    resp = jsonify(body)
    resp.status_code = status
    return resp


def error_response(err):
    body = {"meta": _meta(),
            "response_type": "error",
            "data": {"error_id": err.error_id, "message": err.message}}
    resp = jsonify(body)
    resp.status_code = err.http_status
    return resp


def err_unauthenticated(msg="Missing or malformed authentication headers"):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def err_unauthorized(msg="Role not permitted for this endpoint"):
    return ApiError("ERR_UNAUTHORIZED", 403, msg)


def err_not_found(msg="Referenced resource does not exist"):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def err_invalid(msg="Invalid request"):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def err_invalid_state(msg="Resource state does not permit this operation"):
    return ApiError("ERR_INVALID_STATE", 409, msg)


def err_terminal(msg="Resource is in a terminal state"):
    return ApiError("ERR_ALREADY_TERMINAL", 409, msg)


def err_stale(msg="expected_zone_version does not match the current version"):
    return ApiError("ERR_STALE_VERSION", 412, msg)


def err_duplicate(msg="Duplicate resource within scope"):
    return ApiError("ERR_DUPLICATE_RESOURCE", 409, msg)


def err_proxy(msg="proxied=true on a proxy-ineligible record type"):
    return ApiError("ERR_PROXY_STATUS_INVALID", 422, msg)


def err_verify(msg="Zone delegation preconditions are not met"):
    return ApiError("ERR_ZONE_VERIFICATION_FAILED", 422, msg)


def err_plan(msg="Plan tier does not include the gated feature"):
    return ApiError("ERR_PLAN_FEATURE_UNAVAILABLE", 402, msg)


def err_time_range(msg="end_utc must be strictly after start_utc"):
    return ApiError("ERR_INVALID_TIME_RANGE", 422, msg)


def err_window_overlap(msg="Maintenance window overlaps an existing window"):
    return ApiError("ERR_WINDOW_OVERLAP", 409, msg)


def err_rule_overlap(msg="Conflicting firewall filter with identical expression"):
    return ApiError("ERR_RULE_OVERLAP", 409, msg)


def err_band_overlap(msg="Bot action band intersects another ACTIVE band"):
    return ApiError("ERR_BAND_OVERLAP", 409, msg)


def err_routing(msg="TAKE_ACTION is permitted only on HOSTED-routing reports"):
    return ApiError("ERR_ABUSE_ROUTING_VIOLATION", 409, msg)


def err_mitigation(msg="Zone is under automatic DoS mitigation"):
    return ApiError("ERR_MITIGATION_ACTIVE", 409, msg)

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def get_auth():
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if not role or not uid or role not in ROLES:
        raise err_unauthenticated()
    return role, uid


def require_roles(*roles):
    role, uid = get_auth()
    if role not in roles:
        raise err_unauthorized()
    return role, uid


def check_ownership(zone, role, uid):
    """ZoneAdmin may only touch zones of their own account."""
    if role == "ZoneAdmin" and zone["account_id"] != uid:
        raise err_unauthorized()

# ---------------------------------------------------------------------------
# Common field helpers
# ---------------------------------------------------------------------------


def new_id():
    return str(uuid.uuid4())


def stamp_new(obj):
    obj["id"] = new_id()
    obj["created_at"] = now_str()
    obj["updated_at"] = now_str()
    obj["version"] = 1
    return obj


def touch(obj):
    obj["updated_at"] = now_str()
    obj["version"] += 1
    return obj

# ---------------------------------------------------------------------------
# Input helpers
# ---------------------------------------------------------------------------


def body():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise err_invalid("Request body must be a JSON object")
    return data


def req_str(data, field):
    v = data.get(field)
    if not isinstance(v, str) or v == "":
        raise err_invalid(f"Field '{field}' is required and must be a string")
    return v


def req_bool(data, field):
    v = data.get(field)
    if not isinstance(v, bool):
        raise err_invalid(f"Field '{field}' is required and must be a boolean")
    return v


def req_int(data, field, minimum=None, maximum=None):
    v = data.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err_invalid(f"Field '{field}' is required and must be an integer")
    if minimum is not None and v < minimum:
        raise err_invalid(f"Field '{field}' must be >= {minimum}")
    if maximum is not None and v > maximum:
        raise err_invalid(f"Field '{field}' must be <= {maximum}")
    return v


def req_enum(data, field, allowed):
    v = data.get(field)
    if v not in allowed:
        raise err_invalid(f"Field '{field}' must be one of {sorted(allowed)}")
    return v

# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


def paginate(items):
    args = request.args
    try:
        limit = int(args.get("limit")) if args.get("limit") is not None else 10
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(args.get("offset")) if args.get("offset") is not None else 0
    except (TypeError, ValueError):
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    total = len(items)
    page = items[offset:offset + limit]
    return page, {"limit": limit, "offset": offset,
                  "total_count": total, "has_more": offset + limit < total}

# ---------------------------------------------------------------------------
# Zone helper: delegation preconditions
# ---------------------------------------------------------------------------


def delegation_ok(zone):
    records = zone.get("dns_records", [])
    if zone["onboarding_type"] == "FULL":
        return sum(1 for r in records if r.get("proxied") is True) >= 1
    # PARTIAL
    proxied = [r for r in records if r.get("proxied") is True]
    if not any(r.get("record_type") in PROXYABLE_TYPES for r in proxied):
        return False
    for r in proxied:
        if r.get("record_type") == "CNAME":
            content = r.get("content")
            if not isinstance(content, str) or not content.endswith(CDN_SUFFIX):
                return False
    return True

# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------


def account_out(a):
    return dict(a)


def pop_out(p, as_of=None, reserved=None):
    out = {k: v for k, v in p.items()
           if k not in ("effective_capacity_gbps", "planned_utilization_pct")}
    if as_of is None:
        out["effective_capacity_gbps"] = None
        out["planned_utilization_pct"] = None
    else:
        windows = [w for w in p.get("maintenance_windows", [])
                   if parse_dt(w["start_utc"]) <= as_of < parse_dt(w["end_utc"])]
        if windows:
            min_headroom = min(w["headroom_pct"] for w in windows)
            eff = (p["capacity_baseline_gbps"] * min_headroom) // 100
        else:
            eff = p["capacity_baseline_gbps"]
        out["effective_capacity_gbps"] = eff
        if reserved is not None:
            if eff == 0:
                out["planned_utilization_pct"] = 0
            else:
                out["planned_utilization_pct"] = round_half_up(
                    100 * reserved / eff)
        else:
            out["planned_utilization_pct"] = None
    return out


def zone_out(z):
    active_rules = sum(1 for r in z.get("traffic_rules", [])
                       if r.get("status") == "ACTIVE")
    disabled_managed = 0
    for sub in z.get("ruleset_subscriptions", []):
        if sub.get("status") != "ACTIVE":
            continue
        for ov in sub.get("overrides", []):
            if ov.get("override_action") == "DISABLE" and ov.get("status") == "ACTIVE":
                disabled_managed += 1
    denom = disabled_managed + active_rules
    fpr = 0 if denom == 0 else round_half_up(100 * disabled_managed / denom)
    out = dict(z)
    out["active_rules_count"] = active_rules
    out["disabled_managed_rules_count"] = disabled_managed
    out["false_positive_rate_pct"] = fpr
    return out


def ddos_out(e):
    return dict(e)


def purge_out(p):
    return dict(p)


def ipblock_out(b):
    out = dict(b)
    if b["status"] == "CONFIRMED":
        now_utc = now()
        expires = parse_dt(b["expires_at"])
        effective = min(now_utc, expires)
        elapsed = (effective - parse_dt(b["confirmed_at"])).total_seconds()
        out["blocked_seconds_total"] = round_half_up(
            elapsed * (1 - RELEASE_GRACE_FRACTION))
    else:
        out["blocked_seconds_total"] = None
    return out


def abuse_out(r):
    return dict(r)

# ---------------------------------------------------------------------------
# Clock sweep: DDoS auto-expiry, IpBlock expiry, purge progression, then the
# delegation re-check for ACTIVE zones.
# ---------------------------------------------------------------------------


def _recompute_dos_active(zone_id):
    z = db.zones.get(zone_id)
    if z is None:
        return
    z["dos_mitigation_active"] = any(
        e["zone_id"] == zone_id and e["status"] == "ACTIVATED"
        for e in db.ddos_events.values())


def sweep_clock(new_time):
    # 1. DDoS events: ACTIVATED -> ENDED when expires_at reached
    for e in db.ddos_events.values():
        if e["status"] == "ACTIVATED" and parse_dt(e["expires_at"]) <= new_time:
            e["status"] = "ENDED"
            touch(e)
            _recompute_dos_active(e["zone_id"])
    # 2. IpBlocks: PROVISIONAL/CONFIRMED -> EXPIRED when expires_at reached
    for b in db.ip_blocks.values():
        if b["status"] in ("PROVISIONAL", "CONFIRMED") and \
                parse_dt(b["expires_at"]) <= new_time:
            b["status"] = "EXPIRED"
            touch(b)
    # 3. PurgeRequests: QUEUED -> IN_PROGRESS -> COMPLETED, in order
    for p in db.purge_requests.values():
        if p["status"] == "COMPLETED":
            continue
        requested = parse_dt(p["requested_at"])
        latency = SHIELD_PER_ENTRY_COMPLETION_SECONDS if p.get(
            "origin_shield_degraded") else UNSHIELDED_PER_ENTRY_COMPLETION_SECONDS
        if p["status"] == "QUEUED" and new_time > requested:
            p["status"] = "IN_PROGRESS"
            touch(p)
        if p["status"] == "IN_PROGRESS" and \
                new_time >= requested + timedelta(seconds=latency):
            p["status"] = "COMPLETED"
            touch(p)
            z = db.zones.get(p["zone_id"])
            if p["purge_type"] == "PURGE_ALL" and z is not None:
                z["last_purged_at"] = now_str()
    # 4. Delegation re-check: ACTIVE zones failing delegation -> MOVED + cascade
    for z in db.zones.values():
        if z["status"] != "ACTIVE":
            continue
        if delegation_ok(z):
            continue
        z["status"] = "MOVED"
        touch(z)
        for r in z.get("traffic_rules", []):
            if r.get("status") == "ACTIVE":
                r["status"] = "DISABLED"
        for band in z.get("bot_action_bands", []):
            if band.get("status") == "ACTIVE":
                band["status"] = "DISABLED"
        for e in db.ddos_events.values():
            if e["zone_id"] == z["id"] and e["status"] == "ACTIVATED":
                e["status"] = "ENDED"
                touch(e)
        _recompute_dos_active(z["id"])
