"""Household Verification & Extra Member Administration API.

Flask implementation of the PRD at workspace/PRD.md. In-memory store,
logical clock, envelope per PRD section 2.
"""

import os
import re
import uuid
import random
from datetime import datetime, timedelta, timezone

from flask import Flask, request, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

_EPOCH = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


class Clock:
    now_dt = _EPOCH


def now():
    return Clock.now_dt


def iso(dt):
    """ISO 8601 UTC with three fractional digits, Z suffix."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(s):
    if not isinstance(s, str):
        raise ValueError("not a string")
    m = re.match(
        r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$",
        s,
    )
    if not m:
        raise ValueError("bad iso8601")
    y, mo, d, h, mi, se = (int(m.group(i)) for i in range(1, 7))
    frac = m.group(7)
    micro = 0
    if frac:
        digits = frac[1:]
        micro = int((digits + "000000")[:6])
    tzs = m.group(8)
    tz = timezone.utc
    if tzs and tzs != "Z":
        sign = 1 if tzs[0] == "+" else -1
        parts = tzs[1:].replace(":", "")
        th, tm = int(parts[:2]), int(parts[2:4])
        tz = timezone(sign * timedelta(hours=th, minutes=tm))
    return datetime(y, mo, d, h, mi, se, micro, tzinfo=tz).astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class DB:
    accounts = {}
    households = {}
    members = {}
    devices = {}
    slots = {}
    challenges = {}
    passes = {}
    transfers = {}
    sessions = {}
    downloads = {}
    policies = {}
    metrics = {}


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ApiError(Exception):
    def __init__(self, error_id, http, message):
        super().__init__(message)
        self.error_id = error_id
        self.http = http
        self.message = message


def err(error_id, http, message):
    raise ApiError(error_id, http, message)


NOT_FOUND = {
    "account": ("ERR_ACCOUNT_NOT_FOUND", "No account with the given id"),
    "household": ("ERR_HOUSEHOLD_NOT_FOUND", "No household with the given id"),
    "member": ("ERR_MEMBER_NOT_FOUND", "No member with the given id"),
    "device": ("ERR_DEVICE_NOT_FOUND", "No device with the given id"),
    "slot": ("ERR_SLOT_NOT_FOUND", "No extra member slot with the given id"),
    "challenge": ("ERR_CHALLENGE_NOT_FOUND", "No verification challenge with the given id"),
    "pass": ("ERR_TRAVEL_PASS_NOT_FOUND", "No travel pass with the given id"),
    "transfer": ("ERR_TRANSFER_NOT_FOUND", "No profile transfer with the given id"),
    "session": ("ERR_SESSION_NOT_FOUND", "No playback session with the given id"),
    "download": ("ERR_DOWNLOAD_NOT_FOUND", "No download with the given id"),
    "policy": ("ERR_POLICY_NOT_FOUND", "No enforcement policy with the given id"),
}


def get_or_404(kind, store, rid):
    obj = store.get(rid)
    if obj is None:
        eid, msg = NOT_FOUND[kind]
        err(eid, 404, msg)
    return obj


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------


def req_id():
    return "req_" + uuid.uuid4().hex[:24]


def meta():
    return {"api_request_id": req_id(), "api_request_timestamp": iso(now())}


def ok_obj(data, status=200):
    body = {"meta": meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(items, limit, offset, total):
    m = meta()
    m["limit"] = limit
    m["offset"] = offset
    m["total_count"] = total
    m["has_more"] = (offset + len(items)) < total
    body = {"meta": m, "response_type": "array", "data": items}
    return jsonify(body), 200


@app.errorhandler(ApiError)
def handle_api_error(e):
    body = {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http


@app.errorhandler(404)
def handle_404(e):
    body = {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_VALIDATION", "message": "Route not found"},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(e):
    body = {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_VALIDATION", "message": "Method not allowed"},
    }
    return jsonify(body), 405


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


def pagination():
    try:
        limit = int(request.args.get("limit", "10"))
    except (TypeError, ValueError):
        err("ERR_VALIDATION", 400, "limit must be an integer")
    try:
        offset = int(request.args.get("offset", "0"))
    except (TypeError, ValueError):
        err("ERR_VALIDATION", 400, "offset must be an integer")
    if limit < 1 or limit > 100:
        err("ERR_VALIDATION", 400, "limit must be between 1 and 100")
    if offset < 0:
        err("ERR_VALIDATION", 400, "offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list(page, limit, offset, total)


def sorted_by_created(items):
    return sorted(items, key=lambda x: (x["created_at"], x["id"]))


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

ROLES = {"PlatformAdmin", "SupportAgent", "AccountOwner", "HouseholdMember", "ExtraMember"}
MEMBER_ROLES = {"AccountOwner": "OWNER", "HouseholdMember": "HOUSEHOLD", "ExtraMember": "EXTRA"}


class Actor:
    def __init__(self, role, uid, member):
        self.role = role
        self.uid = uid
        self.member = member  # Member dict or None

    @property
    def account_id(self):
        return self.member["account_id"] if self.member else None


def authenticate():
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if not role or not uid:
        err("ERR_UNAUTHENTICATED", 401, "Missing X-User-Role or X-User-ID header")
    if role not in ROLES:
        err("ERR_UNAUTHENTICATED", 401, "Unknown role")
    member = None
    if role in MEMBER_ROLES:
        member = DB.members.get(uid)
        if member is None:
            err("ERR_UNAUTHENTICATED", 401, "X-User-ID does not resolve to an existing Member")
        if member["member_role"] != MEMBER_ROLES[role]:
            err("ERR_UNAUTHENTICATED", 401, "Member role does not match X-User-Role")
    return Actor(role, uid, member)


def authorize(actor, allowed, account_id=None):
    """Role list check plus member-ownership check."""
    if actor.role not in allowed:
        err("ERR_FORBIDDEN", 403, "Role not permitted for this endpoint")
    if actor.role in MEMBER_ROLES and account_id is not None:
        if actor.member["account_id"] != account_id:
            err("ERR_FORBIDDEN", 403, "Member does not belong to the target account")


# ---------------------------------------------------------------------------
# Request body validation helpers
# ---------------------------------------------------------------------------


def body():
    if not request.data:
        return {}
    try:
        b = request.get_json(force=True, silent=False)
    except Exception:
        err("ERR_VALIDATION", 400, "Request body must be valid JSON")
    if b is None:
        return {}
    if not isinstance(b, dict):
        err("ERR_VALIDATION", 400, "Request body must be a JSON object")
    return b


def req_str(b, field):
    v = b.get(field)
    if v is None:
        err("ERR_VALIDATION", 400, f"Missing required field: {field}")
    if not isinstance(v, str) or v == "":
        err("ERR_VALIDATION", 400, f"Field {field} must be a non-empty string")
    return v


def req_enum(b, field, values):
    v = req_str(b, field)
    if v not in values:
        err("ERR_VALIDATION", 400, f"Field {field} must be one of {sorted(values)}")
    return v


def req_int(b, field, minimum=None):
    v = b.get(field)
    if v is None:
        err("ERR_VALIDATION", 400, f"Missing required field: {field}")
    if not isinstance(v, int) or isinstance(v, bool):
        err("ERR_VALIDATION", 400, f"Field {field} must be an integer")
    if minimum is not None and v < minimum:
        err("ERR_VALIDATION", 400, f"Field {field} must be >= {minimum}")
    return v


def req_bool(b, field):
    v = b.get(field)
    if v is None:
        err("ERR_VALIDATION", 400, f"Missing required field: {field}")
    if not isinstance(v, bool):
        err("ERR_VALIDATION", 400, f"Field {field} must be a boolean")
    return v


def req_dt(b, field):
    v = req_str(b, field)
    try:
        return parse_iso(v)
    except ValueError:
        err("ERR_VALIDATION", 400, f"Field {field} must be ISO 8601")


# ---------------------------------------------------------------------------
# Entity construction / serialization
# ---------------------------------------------------------------------------


def new_common():
    t = iso(now())
    return {"id": str(uuid.uuid4()), "created_at": t, "updated_at": t, "version": 1}


def touch(obj):
    obj["updated_at"] = iso(now())
    obj["version"] += 1


def light_common():
    return {"id": str(uuid.uuid4()), "created_at": iso(now())}


def ser_account(a):
    return {
        "id": a["id"],
        "email": a["email"],
        "region_code": a["region_code"],
        "plan_tier": a["plan_tier"],
        "status": a["status"],
        "verification_posture": a["verification_posture"],
        "billing_anchor_day": a["billing_anchor_day"],
        "owner_member_id": a["owner_member_id"],
        "extra_member_billed_cents": a["extra_member_billed_cents"],
        "extra_member_credit_cents": a["extra_member_credit_cents"],
        "extra_member_net_revenue_cents": a["extra_member_billed_cents"] - a["extra_member_credit_cents"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def ser_household(h):
    trusted = sum(
        1 for d in DB.devices.values()
        if d["household_id"] == h["id"] and d["trust_status"] == "TRUSTED"
    )
    return {
        "id": h["id"],
        "account_id": h["account_id"],
        "label": h["label"],
        "primary_location": h["primary_location"],
        "network_fingerprint": h["network_fingerprint"],
        "geo_cell": h["geo_cell"],
        "status": h["status"],
        "trusted_device_count": trusted,
        "last_verified_at": h["last_verified_at"],
        "created_at": h["created_at"],
        "updated_at": h["updated_at"],
        "version": h["version"],
    }


def member_current_streams(m):
    return sum(
        1 for s in DB.sessions.values()
        if s["member_id"] == m["id"] and s["status"] == "ACTIVE"
    )


def member_downloads_used(m):
    month = now().strftime("%Y-%m")
    return sum(
        1 for d in DB.downloads.values()
        if d["member_id"] == m["id"]
        and d["status"] == "ACTIVE"
        and d["billing_month"] == month
    )


def ser_member(m):
    return {
        "id": m["id"],
        "account_id": m["account_id"],
        "display_name": m["display_name"],
        "member_role": m["member_role"],
        "status": m["status"],
        "viewing_history": list(m["viewing_history"]),
        "recommendation_seed": m["recommendation_seed"],
        "current_streams": member_current_streams(m),
        "downloads_used_this_month": member_downloads_used(m),
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


def device_travel_pass_active(d):
    apply_pass_lazy_all()
    return any(
        p["device_id"] == d["id"] and p["status"] == "ACTIVE"
        for p in DB.passes.values()
    )


def ser_device(d):
    return {
        "id": d["id"],
        "household_id": d["household_id"],
        "device_label": d["device_label"],
        "device_type": d["device_type"],
        "network_fingerprint": d["network_fingerprint"],
        "geo_cell": d["geo_cell"],
        "trust_status": d["trust_status"],
        "last_signal_at": d["last_signal_at"],
        "travel_pass_active": device_travel_pass_active(d),
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


def ser_slot(s):
    return {
        "id": s["id"],
        "account_id": s["account_id"],
        "member_id": s["member_id"],
        "payer_member_id": s["payer_member_id"],
        "transfer_rights": s["transfer_rights"],
        "status": s["status"],
        "slot_index": s["slot_index"],
        "price_cents_snapshot": s["price_cents_snapshot"],
        "credit_cents": s["credit_cents"],
        "purchased_day": s["purchased_day"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def ser_challenge(c):
    apply_challenge_lazy(c)
    return {
        "id": c["id"],
        "account_id": c["account_id"],
        "channel": c["channel"],
        "challenge_reason": c["challenge_reason"],
        "code": c["code"],
        "status": c["status"],
        "attempts_used": c["attempts_used"],
        "expires_at": c["expires_at"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def ser_pass(p):
    apply_pass_lazy(p)
    return {
        "id": p["id"],
        "device_id": p["device_id"],
        "grant_type": p["grant_type"],
        "starts_at": p["starts_at"],
        "ends_at": p["ends_at"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def ser_transfer(t):
    apply_transfer_lazy(t)
    return {
        "id": t["id"],
        "source_account_id": t["source_account_id"],
        "member_id": t["member_id"],
        "target_email": t["target_email"],
        "status": t["status"],
        "expires_at": t["expires_at"],
        "history_snapshot": list(t["history_snapshot"]),
        "recommendation_snapshot": t["recommendation_snapshot"],
        "target_account_id": t["target_account_id"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def ser_session(s):
    return {
        "id": s["id"],
        "member_id": s["member_id"],
        "device_id": s["device_id"],
        "requested_resolution": s["requested_resolution"],
        "resolution_granted": s["resolution_granted"],
        "status": s["status"],
        "started_at": s["started_at"],
        "ended_at": s["ended_at"],
        "created_at": s["created_at"],
    }


def ser_download(d):
    apply_download_lazy(d)
    return {
        "id": d["id"],
        "member_id": d["member_id"],
        "device_id": d["device_id"],
        "title_id": d["title_id"],
        "status": d["status"],
        "billing_month": d["billing_month"],
        "created_at": d["created_at"],
    }


def ser_policy(p):
    return {
        "id": p["id"],
        "region_code": p["region_code"],
        "enforcement_enabled": p["enforcement_enabled"],
        "grace_days": p["grace_days"],
        "messaging_variant": p["messaging_variant"],
        "effective_from": p["effective_from"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def ser_metric(m):
    return {
        "id": m["id"],
        "account_id": m["account_id"],
        "metric_type": m["metric_type"],
        "notes": m["notes"],
        "recorded_at": m["recorded_at"],
        "created_at": m["created_at"],
    }


# ---------------------------------------------------------------------------
# Lazy state materialization
# ---------------------------------------------------------------------------


def apply_challenge_lazy(c):
    if c["status"] == "PENDING" and now() >= parse_iso(c["expires_at"]):
        c["status"] = "EXPIRED"
        touch(c)


def apply_pass_lazy(p):
    if p["status"] == "ACTIVE" and now() >= parse_iso(p["ends_at"]):
        p["status"] = "EXPIRED"
        touch(p)


def apply_pass_lazy_all():
    for p in DB.passes.values():
        apply_pass_lazy(p)


def apply_transfer_lazy(t):
    if t["status"] == "AWAITING_ACCEPTANCE" and now() >= parse_iso(t["expires_at"]):
        t["status"] = "EXPIRED"
        touch(t)


def apply_download_lazy(d):
    if d["status"] == "ACTIVE":
        created = parse_iso(d["created_at"])
        if now() >= created + timedelta(days=30):
            d["status"] = "EXPIRED"


# ---------------------------------------------------------------------------
# Business helpers
# ---------------------------------------------------------------------------

REGIONS = {"NA", "LATAM", "EMEA", "APAC"}
TIERS = {"BASIC", "STANDARD", "PREMIUM"}
REGION_BASE = {"NA": 799, "LATAM": 299, "EMEA": 499, "APAC": 349}
TIER_MULT = {"BASIC": 1.0, "STANDARD": 1.0, "PREMIUM": 0.75}
TIER_MAX_STREAMS = {"BASIC": 1, "STANDARD": 2, "PREMIUM": 4}
TIER_MAX_RES = {"BASIC": 0, "STANDARD": 1, "PREMIUM": 2}  # SD=0 HD=1 UHD=2
RES_ORDER = {"SD": 0, "HD": 1, "UHD": 2}
TIER_MONTHLY_DL = {"BASIC": 5, "STANDARD": 25, "PREMIUM": 100}
TIER_MAX_SLOTS = {"BASIC": 0, "STANDARD": 1, "PREMIUM": 2}
SLOT_SURCHARGE = 200
CYCLE_DAYS = 30
FULL_CREDIT_WINDOW = 7
ATTEMPT_CAP = {"EMAIL": 3, "SMS": 3, "VOICE_CALL": 5}
CHALLENGE_TTL = {"EMAIL": 900, "SMS": 900, "VOICE_CALL": 1800}

from decimal import Decimal, ROUND_HALF_UP


def round_half_up(value):
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round4(value):
    return float(Decimal(str(value)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def household_of(account_id):
    """The account's non-DISSOLVED household, if any."""
    for h in DB.households.values():
        if h["account_id"] == account_id and h["status"] != "DISSOLVED":
            return h
    return None


def account_of_household(h):
    return DB.accounts.get(h["account_id"])


def account_gate(account, writes=True):
    """Account-level state gate: cancelled -> ERR_ACCOUNT_CANCELLED,
    suspended -> ERR_ACCOUNT_SUSPENDED."""
    if account["status"] == "CANCELLED":
        err("ERR_ACCOUNT_CANCELLED", 409, "Account is cancelled")
    if writes and account["status"] == "SUSPENDED":
        err("ERR_ACCOUNT_SUSPENDED", 409, "Account is suspended")


def cycle_day_index(account):
    """0-based day index within the current 30-day cycle."""
    anchor = account["billing_anchor_day"]
    dom = now().day
    return (dom - anchor) % 30


def confidence(device):
    h = DB.households.get(device["household_id"])
    network_match = h is not None and device["network_fingerprint"] == h["network_fingerprint"]
    geo_match = h is not None and device["geo_cell"] == h["geo_cell"]
    network_score = 40 if network_match else 0
    geo_score = 30 if geo_match else 0
    age = now() - parse_iso(device["last_signal_at"])
    age_days = int(age.total_seconds() // 86400)
    if age_days <= 7:
        recency = 30
    elif age_days <= 30:
        recency = 10
    else:
        recency = 0
    raw = network_score + geo_score + recency
    strict = min(raw, 50) if network_score == 0 else raw
    return {
        "network_match": bool(network_match),
        "geo_match": bool(geo_match),
        "recency_score": recency,
        "strict_pct": strict,
        "lenient_pct": raw,
    }


def gen_code():
    while True:
        c = f"{random.randint(0, 999999):06d}"
        if c != "000000":
            return c


def end_sessions_for_member(member):
    for s in DB.sessions.values():
        if s["member_id"] == member["id"] and s["status"] == "ACTIVE":
            s["status"] = "ENDED"
            s["ended_at"] = iso(now())


def revoke_pass_cascade(p, account_id):
    """Revoke one ACTIVE pass with its CHURN_SIGNAL metric."""
    if p["status"] != "ACTIVE":
        return
    p["status"] = "REVOKED"
    touch(p)
    m = light_common()
    m.update({
        "account_id": account_id,
        "metric_type": "CHURN_SIGNAL",
        "notes": "",
        "recorded_at": iso(now()),
    })
    DB.metrics[m["id"]] = m


def untrust_device_cascade(device, account_id):
    """TRUSTED -> UNTRUSTED with pass revocation cascade."""
    if device["trust_status"] != "TRUSTED":
        return
    device["trust_status"] = "UNTRUSTED"
    touch(device)
    for p in DB.passes.values():
        if p["device_id"] == device["id"] and p["status"] == "ACTIVE":
            revoke_pass_cascade(p, account_id)


def suspend_account_cascade(account):
    for m in DB.members.values():
        if m["account_id"] == account["id"]:
            end_sessions_for_member(m)
    h = household_of(account["id"])
    if h:
        for d in DB.devices.values():
            if d["household_id"] == h["id"] and d["trust_status"] == "TRUSTED":
                untrust_device_cascade(d, account["id"])


def lapse_slot(slot):
    slot["status"] = "LAPSED"
    touch(slot)
    if slot["member_id"]:
        m = DB.members.get(slot["member_id"])
        if m and m["status"] == "ACTIVE":
            m["status"] = "REMOVED"
            touch(m)
            end_sessions_for_member(m)


# ---------------------------------------------------------------------------
# Clock & billing simulation
# ---------------------------------------------------------------------------


@app.post("/hv/_clock/set_current_utc")
def set_clock():
    b = body()
    to = req_dt(b, "to_iso8601")
    actor = authenticate()
    authorize(actor, ["PlatformAdmin"])
    Clock.now_dt = to
    return ok_obj({"current_utc": iso(Clock.now_dt)})


@app.post("/hv/_billing/simulate")
def billing_simulate():
    b = body()
    account_id = req_str(b, "account_id")
    outcome = req_enum(b, "outcome", {"SUCCEEDED", "FAILED"})
    actor = authenticate()
    authorize(actor, ["PlatformAdmin"])
    account = get_or_404("account", DB.accounts, account_id)
    if outcome == "FAILED" and account["status"] == "ACTIVE":
        suspend_account_cascade(account)
        account["status"] = "SUSPENDED"
        touch(account)
        for s in DB.slots.values():
            if s["account_id"] == account["id"] and s["status"] in ("OFFERED", "ACTIVE"):
                lapse_slot(s)
    return ok_obj(ser_account(account))


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------


def create_account_record(email, region, tier):
    a = new_common()
    anchor = min(max(now().day, 1), 28)
    a.update({
        "email": email,
        "region_code": region,
        "plan_tier": tier,
        "status": "ACTIVE",
        "verification_posture": "VERIFIED",
        "billing_anchor_day": anchor,
        "owner_member_id": None,
        "extra_member_billed_cents": 0,
        "extra_member_credit_cents": 0,
    })
    DB.accounts[a["id"]] = a
    owner = new_common()
    owner.update({
        "account_id": a["id"],
        "display_name": email,
        "member_role": "OWNER",
        "status": "ACTIVE",
        "viewing_history": [],
        "recommendation_seed": uuid.uuid4().hex,
    })
    DB.members[owner["id"]] = owner
    a["owner_member_id"] = owner["id"]
    return a


@app.post("/hv/accounts")
def create_account():
    b = body()
    email = req_str(b, "email")
    region = req_enum(b, "region_code", REGIONS)
    tier = req_enum(b, "plan_tier", TIERS)
    actor = authenticate()
    authorize(actor, ["PlatformAdmin"])
    a = create_account_record(email, region, tier)
    return ok_obj(ser_account(a), 201)


@app.get("/hv/accounts/<aid>")
def get_account(aid):
    actor = authenticate()
    account = get_or_404("account", DB.accounts, aid)
    authorize(actor, ["PlatformAdmin", "SupportAgent", "AccountOwner", "HouseholdMember", "ExtraMember"], account["id"])
    return ok_obj(ser_account(account))


@app.get("/hv/accounts")
def list_accounts():
    actor = authenticate()
    authorize(actor, ["PlatformAdmin", "SupportAgent"])
    limit, offset = pagination()
    items = list(DB.accounts.values())
    region = request.args.get("region_code")
    if region:
        items = [a for a in items if a["region_code"] == region]
    tier = request.args.get("plan_tier")
    if tier:
        items = [a for a in items if a["plan_tier"] == tier]
    items = [ser_account(a) for a in sorted_by_created(items)]
    return paginate(items, limit, offset)


@app.post("/hv/accounts/<aid>/suspend")
def suspend_account(aid):
    actor = authenticate()
    authorize(actor, ["PlatformAdmin"])
    account = get_or_404("account", DB.accounts, aid)
    if account["status"] == "CANCELLED":
        err("ERR_ACCOUNT_CANCELLED", 409, "Account is cancelled")
    if account["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", 409, "Account must be ACTIVE to suspend")
    suspend_account_cascade(account)
    account["status"] = "SUSPENDED"
    touch(account)
    return ok_obj(ser_account(account))


@app.post("/hv/accounts/<aid>/reactivate")
def reactivate_account(aid):
    actor = authenticate()
    authorize(actor, ["PlatformAdmin"])
    account = get_or_404("account", DB.accounts, aid)
    if account["status"] == "CANCELLED":
        err("ERR_ACCOUNT_CANCELLED", 409, "Account is cancelled")
    if account["status"] != "SUSPENDED":
        err("ERR_INVALID_STATE", 409, "Account must be SUSPENDED to reactivate")
    account["status"] = "ACTIVE"
    touch(account)
    return ok_obj(ser_account(account))


@app.post("/hv/accounts/<aid>/cancel")
def cancel_account(aid):
    actor = authenticate()
    account = get_or_404("account", DB.accounts, aid)
    authorize(actor, ["PlatformAdmin", "AccountOwner"], account["id"])
    if account["status"] == "CANCELLED":
        err("ERR_ACCOUNT_CANCELLED", 409, "Account is cancelled")
    if account["status"] not in ("ACTIVE", "SUSPENDED"):
        err("ERR_INVALID_STATE", 409, "Account cannot be cancelled")
    for m in DB.members.values():
        if m["account_id"] == account["id"] and m["status"] == "ACTIVE":
            m["status"] = "REMOVED"
            touch(m)
            end_sessions_for_member(m)
    for s in DB.slots.values():
        if s["account_id"] == account["id"] and s["status"] in ("OFFERED", "ACTIVE"):
            s["status"] = "REVOKED"
            s["credit_cents"] = 0
            touch(s)
    account["status"] = "CANCELLED"
    touch(account)
    return ok_obj(ser_account(account))


@app.patch("/hv/accounts/<aid>/plan")
def change_plan(aid):
    b = body()
    tier = req_enum(b, "plan_tier", TIERS)
    if "expected_account_version" not in b or not isinstance(b.get("expected_account_version"), int) or isinstance(b.get("expected_account_version"), bool):
        err("ERR_VALIDATION", 400, "expected_account_version is required and must be an integer")
    expected = b["expected_account_version"]
    actor = authenticate()
    account = get_or_404("account", DB.accounts, aid)
    authorize(actor, ["PlatformAdmin", "AccountOwner"], account["id"])
    if account["status"] == "CANCELLED":
        err("ERR_ACCOUNT_CANCELLED", 409, "Account is cancelled")
    if expected != account["version"]:
        err("ERR_STALE_ACCOUNT_VERSION", 412, "Stale account version")
    account["plan_tier"] = tier
    touch(account)
    return ok_obj(ser_account(account))


# ---------------------------------------------------------------------------
# Households
# ---------------------------------------------------------------------------


@app.post("/hv/accounts/<aid>/households")
def create_household(aid):
    b = body()
    label = req_str(b, "label")
    loc = req_str(b, "primary_location")
    nfp = req_str(b, "network_fingerprint")
    geo = req_str(b, "geo_cell")
    actor = authenticate()
    account = get_or_404("account", DB.accounts, aid)
    authorize(actor, ["AccountOwner"], account["id"])
    account_gate(account)
    if household_of(account["id"]) is not None:
        err("ERR_ACCOUNT_ALREADY_HAS_HOUSEHOLD", 409, "Account already has a non-dissolved household")
    h = new_common()
    h.update({
        "account_id": account["id"],
        "label": label,
        "primary_location": loc,
        "network_fingerprint": nfp,
        "geo_cell": geo,
        "status": "ESTABLISHED",
        "last_verified_at": None,
    })
    DB.households[h["id"]] = h
    return ok_obj(ser_household(h), 201)


@app.get("/hv/households/<hid>")
def get_household(hid):
    actor = authenticate()
    h = get_or_404("household", DB.households, hid)
    authorize(actor, ["PlatformAdmin", "SupportAgent", "AccountOwner", "HouseholdMember", "ExtraMember"], h["account_id"])
    return ok_obj(ser_household(h))


@app.get("/hv/accounts/<aid>/households")
def list_households(aid):
    actor = authenticate()
    account = get_or_404("account", DB.accounts, aid)
    authorize(actor, ["PlatformAdmin", "SupportAgent", "AccountOwner", "HouseholdMember", "ExtraMember"], account["id"])
    limit, offset = pagination()
    items = [h for h in DB.households.values() if h["account_id"] == aid]
    items = [ser_household(h) for h in sorted_by_created(items)]
    return paginate(items, limit, offset)


@app.post("/hv/households/<hid>/relocate")
def relocate_household(hid):
    b = body()
    loc = req_str(b, "primary_location")
    nfp = req_str(b, "network_fingerprint")
    geo = req_str(b, "geo_cell")
    actor = authenticate()
    h = get_or_404("household", DB.households, hid)
    authorize(actor, ["AccountOwner"], h["account_id"])
    account = account_of_household(h)
    account_gate(account)
    if h["status"] != "ESTABLISHED":
        err("ERR_INVALID_STATE", 409, "Household must be ESTABLISHED to relocate")
    h["primary_location"] = loc
    h["network_fingerprint"] = nfp
    h["geo_cell"] = geo
    h["status"] = "RELOCATING"
    touch(h)
    for d in DB.devices.values():
        if d["household_id"] == h["id"] and d["trust_status"] == "TRUSTED":
            untrust_device_cascade(d, h["account_id"])
    return ok_obj(ser_household(h))


@app.post("/hv/households/<hid>/dissolve")
def dissolve_household(hid):
    actor = authenticate()
    h = get_or_404("household", DB.households, hid)
    authorize(actor, ["AccountOwner"], h["account_id"])
    account = account_of_household(h)
    if account["status"] == "CANCELLED":
        err("ERR_ACCOUNT_CANCELLED", 409, "Account is cancelled")
    if h["status"] not in ("ESTABLISHED", "RELOCATING"):
        err("ERR_INVALID_STATE", 409, "Household cannot be dissolved")
    for d in DB.devices.values():
        if d["household_id"] == h["id"] and d["trust_status"] != "REMOVED":
            d["trust_status"] = "REMOVED"
            touch(d)
            for s in DB.sessions.values():
                if s["device_id"] == d["id"] and s["status"] == "ACTIVE":
                    s["status"] = "ENDED"
                    s["ended_at"] = iso(now())
            for p in DB.passes.values():
                if p["device_id"] == d["id"] and p["status"] == "ACTIVE":
                    revoke_pass_cascade(p, h["account_id"])
    h["status"] = "DISSOLVED"
    touch(h)
    return ok_obj(ser_household(h))


# ---------------------------------------------------------------------------
# Members
# ---------------------------------------------------------------------------


@app.post("/hv/accounts/<aid>/members")
def create_member(aid):
    b = body()
    name = req_str(b, "display_name")
    actor = authenticate()
    account = get_or_404("account", DB.accounts, aid)
    authorize(actor, ["AccountOwner"], account["id"])
    account_gate(account)
    m = new_common()
    m.update({
        "account_id": account["id"],
        "display_name": name,
        "member_role": "HOUSEHOLD",
        "status": "ACTIVE",
        "viewing_history": [],
        "recommendation_seed": uuid.uuid4().hex,
    })
    DB.members[m["id"]] = m
    return ok_obj(ser_member(m), 201)


@app.get("/hv/members/<mid>")
def get_member(mid):
    actor = authenticate()
    m = get_or_404("member", DB.members, mid)
    authorize(actor, ["PlatformAdmin", "SupportAgent", "AccountOwner", "HouseholdMember", "ExtraMember"], m["account_id"])
    return ok_obj(ser_member(m))


@app.get("/hv/accounts/<aid>/members")
def list_members(aid):
    actor = authenticate()
    account = get_or_404("account", DB.accounts, aid)
    authorize(actor, ["PlatformAdmin", "SupportAgent", "AccountOwner", "HouseholdMember", "ExtraMember"], account["id"])
    limit, offset = pagination()
    items = [m for m in DB.members.values() if m["account_id"] == aid]
    role = request.args.get("member_role")
    if role:
        items = [m for m in items if m["member_role"] == role]
    status = request.args.get("status")
    if status:
        items = [m for m in items if m["status"] == status]
    items = [ser_member(m) for m in sorted_by_created(items)]
    return paginate(items, limit, offset)


@app.post("/hv/members/<mid>/remove")
def remove_member(mid):
    actor = authenticate()
    m = get_or_404("member", DB.members, mid)
    authorize(actor, ["AccountOwner"], m["account_id"])
    account = DB.accounts.get(m["account_id"])
    account_gate(account)
    if m["member_role"] == "OWNER":
        err("ERR_INVALID_STATE", 409, "Owner member cannot be removed")
    if m["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", 409, "Member is not ACTIVE")
    m["status"] = "REMOVED"
    touch(m)
    end_sessions_for_member(m)
    return ok_obj(ser_member(m))


# ---------------------------------------------------------------------------
# Devices
# ---------------------------------------------------------------------------


@app.post("/hv/households/<hid>/devices")
def register_device(hid):
    b = body()
    label = req_str(b, "device_label")
    dtype = req_enum(b, "device_type", {"TV", "MOBILE", "WEB", "CONSOLE"})
    nfp = req_str(b, "network_fingerprint")
    geo = req_str(b, "geo_cell")
    actor = authenticate()
    h = get_or_404("household", DB.households, hid)
    authorize(actor, ["AccountOwner", "HouseholdMember", "ExtraMember"], h["account_id"])
    account = account_of_household(h)
    account_gate(account)
    if h["status"] == "DISSOLVED":
        err("ERR_INVALID_STATE", 409, "Household is dissolved")
    d = new_common()
    d.update({
        "household_id": h["id"],
        "device_label": label,
        "device_type": dtype,
        "network_fingerprint": nfp,
        "geo_cell": geo,
        "trust_status": "UNTRUSTED",
        "last_signal_at": iso(now()),
    })
    DB.devices[d["id"]] = d
    return ok_obj(ser_device(d), 201)


@app.get("/hv/devices/<did>")
def get_device(did):
    actor = authenticate()
    d = get_or_404("device", DB.devices, did)
    h = DB.households.get(d["household_id"])
    authorize(actor, ["PlatformAdmin", "SupportAgent", "AccountOwner", "HouseholdMember", "ExtraMember"], h["account_id"] if h else None)
    return ok_obj(ser_device(d))


@app.get("/hv/households/<hid>/devices")
def list_devices(hid):
    actor = authenticate()
    h = get_or_404("household", DB.households, hid)
    authorize(actor, ["PlatformAdmin", "SupportAgent", "AccountOwner", "HouseholdMember", "ExtraMember"], h["account_id"])
    limit, offset = pagination()
    items = [d for d in DB.devices.values() if d["household_id"] == hid]
    ts = request.args.get("trust_status")
    if ts:
        items = [d for d in items if d["trust_status"] == ts]
    items = [ser_device(d) for d in sorted_by_created(items)]
    return paginate(items, limit, offset)


@app.get("/hv/devices/<did>/confidence")
def device_confidence(did):
    actor = authenticate()
    d = get_or_404("device", DB.devices, did)
    h = DB.households.get(d["household_id"])
    authorize(actor, ["PlatformAdmin", "SupportAgent", "AccountOwner", "HouseholdMember", "ExtraMember"], h["account_id"] if h else None)
    return ok_obj(confidence(d))


@app.post("/hv/devices/<did>/signal")
def device_signal(did):
    b = body()
    nfp = req_str(b, "network_fingerprint")
    geo = req_str(b, "geo_cell")
    actor = authenticate()
    d = get_or_404("device", DB.devices, did)
    h = DB.households.get(d["household_id"])
    authorize(actor, ["AccountOwner", "HouseholdMember", "ExtraMember"], h["account_id"] if h else None)
    d["network_fingerprint"] = nfp
    d["geo_cell"] = geo
    d["last_signal_at"] = iso(now())
    touch(d)
    if h and h["status"] == "RELOCATING" and nfp == h["network_fingerprint"]:
        h["status"] = "ESTABLISHED"
        h["last_verified_at"] = iso(now())
        touch(h)
    return ok_obj(ser_device(d))


@app.post("/hv/devices/<did>/trust")
def trust_device(did):
    actor = authenticate()
    d = get_or_404("device", DB.devices, did)
    h = DB.households.get(d["household_id"])
    authorize(actor, ["AccountOwner"], h["account_id"] if h else None)
    account = account_of_household(h)
    account_gate(account)
    if d["trust_status"] != "UNTRUSTED":
        err("ERR_INVALID_STATE", 409, "Device must be UNTRUSTED to trust")
    if account["verification_posture"] != "VERIFIED":
        err("ERR_ACCOUNT_NOT_VERIFIED", 409, "Account verification posture is not VERIFIED")
    if confidence(d)["strict_pct"] < 70:
        err("ERR_DEVICE_NOT_TRUSTED", 403, "Strict household-match confidence below 70")
    d["trust_status"] = "TRUSTED"
    touch(d)
    return ok_obj(ser_device(d))


@app.post("/hv/devices/<did>/untrust")
def untrust_device(did):
    actor = authenticate()
    d = get_or_404("device", DB.devices, did)
    h = DB.households.get(d["household_id"])
    authorize(actor, ["AccountOwner"], h["account_id"] if h else None)
    account = account_of_household(h)
    if account["status"] == "CANCELLED":
        err("ERR_ACCOUNT_CANCELLED", 409, "Account is cancelled")
    if d["trust_status"] != "TRUSTED":
        err("ERR_INVALID_STATE", 409, "Device must be TRUSTED to untrust")
    untrust_device_cascade(d, h["account_id"])
    return ok_obj(ser_device(d))


@app.post("/hv/devices/<did>/remove")
def remove_device(did):
    actor = authenticate()
    d = get_or_404("device", DB.devices, did)
    h = DB.households.get(d["household_id"])
    authorize(actor, ["AccountOwner"], h["account_id"] if h else None)
    account = account_of_household(h)
    if account["status"] == "CANCELLED":
        err("ERR_ACCOUNT_CANCELLED", 409, "Account is cancelled")
    if d["trust_status"] not in ("TRUSTED", "UNTRUSTED"):
        err("ERR_INVALID_STATE", 409, "Device cannot be removed")
    d["trust_status"] = "REMOVED"
    touch(d)
    for s in DB.sessions.values():
        if s["device_id"] == d["id"] and s["status"] == "ACTIVE":
            s["status"] = "ENDED"
            s["ended_at"] = iso(now())
    for p in DB.passes.values():
        if p["device_id"] == d["id"] and p["status"] == "ACTIVE":
            revoke_pass_cascade(p, h["account_id"])
    return ok_obj(ser_device(d))


# ---------------------------------------------------------------------------
# Extra member slots
# ---------------------------------------------------------------------------


@app.post("/hv/accounts/<aid>/extra-member-slots")
def purchase_slot(aid):
    b = body()
    payer = req_str(b, "payer_member_id")
    rights = req_enum(b, "transfer_rights", {"TRANSFERABLE", "LOCKED"})
    if "expected_account_version" not in b or not isinstance(b.get("expected_account_version"), int) or isinstance(b.get("expected_account_version"), bool):
        err("ERR_VALIDATION", 400, "expected_account_version is required and must be an integer")
    expected = b["expected_account_version"]
    actor = authenticate()
    account = get_or_404("account", DB.accounts, aid)
    authorize(actor, ["AccountOwner"], account["id"])
    payer_member = DB.members.get(payer)
    if payer_member is None:
        err("ERR_MEMBER_NOT_FOUND", 404, "No member with the given id")
    if expected != account["version"]:
        err("ERR_STALE_ACCOUNT_VERSION", 412, "Stale account version")
    account_gate(account)
    open_slots = [s for s in DB.slots.values() if s["account_id"] == aid and s["status"] in ("OFFERED", "ACTIVE")]
    if len(open_slots) >= TIER_MAX_SLOTS[account["plan_tier"]]:
        err("ERR_SLOT_LIMIT_EXCEEDED", 422, "Extra member slot cap reached for plan tier")
    if payer_member["account_id"] != aid or payer_member["member_role"] != "OWNER":
        err("ERR_VALIDATION", 400, "payer_member_id must identify the account's OWNER member")
    slot_index = 1 + len(open_slots)
    base = REGION_BASE[account["region_code"]]
    fee_full = round_half_up(base * TIER_MULT[account["plan_tier"]]) + (slot_index - 1) * SLOT_SURCHARGE
    day_index = cycle_day_index(account)
    days_remaining = CYCLE_DAYS - day_index
    if day_index == 0:
        fee = fee_full
    else:
        fee = round_half_up(fee_full * days_remaining / CYCLE_DAYS)
    s = new_common()
    s.update({
        "account_id": aid,
        "member_id": None,
        "payer_member_id": payer,
        "transfer_rights": rights,
        "status": "OFFERED",
        "slot_index": slot_index,
        "price_cents_snapshot": fee,
        "credit_cents": 0,
        "purchased_day": day_index,
    })
    DB.slots[s["id"]] = s
    account["extra_member_billed_cents"] += fee
    touch(account)
    return ok_obj(ser_slot(s), 201)


@app.get("/hv/extra-member-slots/<sid>")
def get_slot(sid):
    actor = authenticate()
    s = get_or_404("slot", DB.slots, sid)
    authorize(actor, ["PlatformAdmin", "SupportAgent", "AccountOwner"], s["account_id"])
    return ok_obj(ser_slot(s))


@app.get("/hv/accounts/<aid>/extra-member-slots")
def list_account_slots(aid):
    actor = authenticate()
    account = get_or_404("account", DB.accounts, aid)
    authorize(actor, ["PlatformAdmin", "SupportAgent", "AccountOwner"], account["id"])
    limit, offset = pagination()
    items = [s for s in DB.slots.values() if s["account_id"] == aid]
    status = request.args.get("status")
    if status:
        items = [s for s in items if s["status"] == status]
    items = [ser_slot(s) for s in sorted_by_created(items)]
    return paginate(items, limit, offset)


@app.get("/hv/extra-member-slots")
def list_slots():
    actor = authenticate()
    authorize(actor, ["PlatformAdmin", "SupportAgent"])
    limit, offset = pagination()
    items = list(DB.slots.values())
    mid = request.args.get("member_id")
    if mid:
        items = [s for s in items if s["member_id"] == mid]
    pid = request.args.get("payer_member_id")
    if pid:
        items = [s for s in items if s["payer_member_id"] == pid]
    status = request.args.get("status")
    if status:
        items = [s for s in items if s["status"] == status]
    items = [ser_slot(s) for s in sorted_by_created(items)]
    return paginate(items, limit, offset)


@app.post("/hv/extra-member-slots/<sid>/assign")
def assign_slot(sid):
    b = body()
    email = req_str(b, "email")
    name = req_str(b, "display_name")
    member_region = req_enum(b, "member_region", REGIONS)
    actor = authenticate()
    s = get_or_404("slot", DB.slots, sid)
    authorize(actor, ["AccountOwner"], s["account_id"])
    account = DB.accounts.get(s["account_id"])
    account_gate(account)
    if s["status"] != "OFFERED":
        err("ERR_INVALID_STATE", 409, "Slot must be OFFERED to assign")
    if account["verification_posture"] != "VERIFIED":
        err("ERR_ACCOUNT_NOT_VERIFIED", 409, "Account verification posture is not VERIFIED")
    if member_region != account["region_code"]:
        err("ERR_REGION_MISMATCH", 422, "member_region differs from the account's region_code")
    m = new_common()
    m.update({
        "account_id": account["id"],
        "display_name": name,
        "member_role": "EXTRA",
        "status": "ACTIVE",
        "viewing_history": [],
        "recommendation_seed": uuid.uuid4().hex,
    })
    DB.members[m["id"]] = m
    s["member_id"] = m["id"]
    s["status"] = "ACTIVE"
    touch(s)
    return ok_obj(ser_slot(s))


@app.post("/hv/extra-member-slots/<sid>/revoke")
def revoke_slot(sid):
    actor = authenticate()
    s = get_or_404("slot", DB.slots, sid)
    authorize(actor, ["AccountOwner", "PlatformAdmin"], s["account_id"])
    account = DB.accounts.get(s["account_id"])
    if account["status"] == "CANCELLED":
        err("ERR_ACCOUNT_CANCELLED", 409, "Account is cancelled")
    if s["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", 409, "Slot must be ACTIVE to revoke")
    day_index = cycle_day_index(account)
    if (day_index - s["purchased_day"]) <= FULL_CREDIT_WINDOW:
        credit = s["price_cents_snapshot"]
    else:
        days_remaining = CYCLE_DAYS - day_index
        daily = round_half_up(s["price_cents_snapshot"] / CYCLE_DAYS)
        credit = days_remaining * daily
    s["credit_cents"] = credit
    s["status"] = "REVOKED"
    touch(s)
    account["extra_member_credit_cents"] += credit
    touch(account)
    if s["member_id"]:
        m = DB.members.get(s["member_id"])
        if m and m["status"] == "ACTIVE":
            m["status"] = "REMOVED"
            touch(m)
            end_sessions_for_member(m)
    return ok_obj(ser_slot(s))


@app.post("/hv/extra-member-slots/<sid>/reoffer")
def reoffer_slot(sid):
    actor = authenticate()
    s = get_or_404("slot", DB.slots, sid)
    authorize(actor, ["AccountOwner"], s["account_id"])
    account = DB.accounts.get(s["account_id"])
    account_gate(account)
    if s["status"] != "REVOKED":
        err("ERR_INVALID_STATE", 409, "Slot must be REVOKED to reoffer")
    s["member_id"] = None
    s["status"] = "OFFERED"
    touch(s)
    return ok_obj(ser_slot(s))


# ---------------------------------------------------------------------------
# Verification challenges
# ---------------------------------------------------------------------------


@app.post("/hv/accounts/<aid>/verification-challenges")
def issue_challenge(aid):
    b = body()
    channel = req_enum(b, "channel", {"EMAIL", "SMS", "VOICE_CALL"})
    reason = req_enum(b, "challenge_reason", {"NEW_DEVICE", "PERIODIC", "LOCATION_DRIFT"})
    actor = authenticate()
    account = get_or_404("account", DB.accounts, aid)
    authorize(actor, ["PlatformAdmin", "AccountOwner"], account["id"])
    account_gate(account)
    if reason == "PERIODIC":
        ok_policy = False
        for p in DB.policies.values():
            if (p["region_code"] == account["region_code"] and p["status"] == "ACTIVE"
                    and p["enforcement_enabled"]):
                eff = parse_iso(p["effective_from"]) + timedelta(days=p["grace_days"])
                if now() >= eff:
                    ok_policy = True
                    break
        if not ok_policy:
            err("ERR_ENFORCEMENT_GRACE_ACTIVE", 409, "No ACTIVE enabled policy past its grace period for this region")
    c = new_common()
    expires = now() + timedelta(seconds=CHALLENGE_TTL[channel])
    c.update({
        "account_id": aid,
        "channel": channel,
        "challenge_reason": reason,
        "code": gen_code(),
        "status": "PENDING",
        "attempts_used": 0,
        "expires_at": iso(expires),
    })
    DB.challenges[c["id"]] = c
    if account["verification_posture"] == "VERIFIED":
        account["verification_posture"] = "CHALLENGE_PENDING"
        touch(account)
    return ok_obj(ser_challenge(c), 201)


@app.get("/hv/verification-challenges/<cid>")
def get_challenge(cid):
    actor = authenticate()
    c = get_or_404("challenge", DB.challenges, cid)
    authorize(actor, ["PlatformAdmin", "SupportAgent", "AccountOwner"], c["account_id"])
    return ok_obj(ser_challenge(c))


@app.get("/hv/accounts/<aid>/verification-challenges")
def list_challenges(aid):
    actor = authenticate()
    account = get_or_404("account", DB.accounts, aid)
    authorize(actor, ["PlatformAdmin", "SupportAgent", "AccountOwner"], account["id"])
    limit, offset = pagination()
    items = [c for c in DB.challenges.values() if c["account_id"] == aid]
    for c in items:
        apply_challenge_lazy(c)
    status = request.args.get("status")
    if status:
        items = [c for c in items if c["status"] == status]
    items = [ser_challenge(c) for c in sorted_by_created(items)]
    return paginate(items, limit, offset)


@app.post("/hv/verification-challenges/<cid>/submit")
def submit_challenge(cid):
    b = body()
    code = req_str(b, "code")
    member_id = req_str(b, "member_id")
    actor = authenticate()
    c = get_or_404("challenge", DB.challenges, cid)
    authorize(actor, ["AccountOwner", "HouseholdMember", "ExtraMember"], c["account_id"])
    m = DB.members.get(member_id)
    if m is None:
        err("ERR_MEMBER_NOT_FOUND", 404, "No member with the given id")
    if c["status"] == "LOCKED_OUT":
        err("ERR_CHALLENGE_LOCKED", 409, "Challenge is locked out")
    if c["status"] == "VERIFIED":
        err("ERR_INVALID_STATE", 409, "Challenge already verified")
    if c["status"] == "PENDING" and now() >= parse_iso(c["expires_at"]):
        c["status"] = "EXPIRED"
        touch(c)
        err("ERR_CHALLENGE_EXPIRED", 409, "Challenge has expired")
    if c["status"] != "PENDING":
        err("ERR_INVALID_STATE", 409, "Challenge is not PENDING")
    if m["account_id"] != c["account_id"] or m["status"] != "ACTIVE":
        err("ERR_MEMBER_NOT_IN_ACCOUNT", 422, "member_id does not belong to the challenged account")
    account = DB.accounts.get(c["account_id"])
    if code != c["code"]:
        c["attempts_used"] += 1
        if c["attempts_used"] >= ATTEMPT_CAP[c["channel"]]:
            c["status"] = "LOCKED_OUT"
            account["verification_posture"] = "LOCKED"
            touch(account)
        touch(c)
        err("ERR_CHALLENGE_CODE_MISMATCH", 422, "Submitted code does not match")
    c["status"] = "VERIFIED"
    touch(c)
    account["verification_posture"] = "VERIFIED"
    touch(account)
    h = household_of(account["id"])
    if h:
        h["last_verified_at"] = iso(now())
        touch(h)
    return ok_obj(ser_challenge(c))


@app.post("/hv/verification-challenges/<cid>/reissue")
def reissue_challenge(cid):
    actor = authenticate()
    c = get_or_404("challenge", DB.challenges, cid)
    authorize(actor, ["AccountOwner", "PlatformAdmin"], c["account_id"])
    account = DB.accounts.get(c["account_id"])
    account_gate(account)
    apply_challenge_lazy(c)
    if c["status"] != "EXPIRED":
        err("ERR_INVALID_STATE", 409, "Challenge must be EXPIRED to reissue")
    if now() < parse_iso(c["expires_at"]) + timedelta(seconds=300):
        err("ERR_CHALLENGE_COOLDOWN", 409, "Reissue cooldown not yet elapsed")
    c["code"] = gen_code()
    c["attempts_used"] = 0
    c["expires_at"] = iso(now() + timedelta(seconds=CHALLENGE_TTL[c["channel"]]))
    c["status"] = "PENDING"
    touch(c)
    return ok_obj(ser_challenge(c))


# ---------------------------------------------------------------------------
# Travel passes
# ---------------------------------------------------------------------------


@app.post("/hv/devices/<did>/travel-passes")
def grant_pass(did):
    b = body()
    grant = req_enum(b, "grant_type", {"TEMPORARY_14D", "TEMPORARY_30D"})
    starts = req_dt(b, "starts_at")
    actor = authenticate()
    d = get_or_404("device", DB.devices, did)
    h = DB.households.get(d["household_id"])
    authorize(actor, ["AccountOwner", "HouseholdMember", "ExtraMember"], h["account_id"] if h else None)
    account = account_of_household(h)
    account_gate(account)
    days = 14 if grant == "TEMPORARY_14D" else 30
    ends = starts + timedelta(days=days)
    apply_pass_lazy_all()
    for p in DB.passes.values():
        if p["device_id"] == did and p["status"] == "ACTIVE":
            ps, pe = parse_iso(p["starts_at"]), parse_iso(p["ends_at"])
            if starts < pe and ps < ends:
                err("ERR_TRAVEL_PASS_OVERLAP", 409, "New pass window overlaps an existing ACTIVE pass")
    p = new_common()
    p.update({
        "device_id": did,
        "grant_type": grant,
        "starts_at": iso(starts),
        "ends_at": iso(ends),
        "status": "ACTIVE",
    })
    DB.passes[p["id"]] = p
    return ok_obj(ser_pass(p), 201)


@app.get("/hv/travel-passes/<pid>")
def get_pass(pid):
    actor = authenticate()
    p = get_or_404("pass", DB.passes, pid)
    d = DB.devices.get(p["device_id"])
    h = DB.households.get(d["household_id"]) if d else None
    authorize(actor, ["PlatformAdmin", "SupportAgent", "AccountOwner", "HouseholdMember", "ExtraMember"], h["account_id"] if h else None)
    return ok_obj(ser_pass(p))


@app.get("/hv/devices/<did>/travel-passes")
def list_passes(did):
    actor = authenticate()
    d = get_or_404("device", DB.devices, did)
    h = DB.households.get(d["household_id"])
    authorize(actor, ["PlatformAdmin", "SupportAgent", "AccountOwner", "HouseholdMember", "ExtraMember"], h["account_id"] if h else None)
    limit, offset = pagination()
    items = [p for p in DB.passes.values() if p["device_id"] == did]
    for p in items:
        apply_pass_lazy(p)
    status = request.args.get("status")
    if status:
        items = [p for p in items if p["status"] == status]
    items = [ser_pass(p) for p in sorted_by_created(items)]
    return paginate(items, limit, offset)


@app.post("/hv/travel-passes/<pid>/revoke")
def revoke_pass(pid):
    actor = authenticate()
    p = get_or_404("pass", DB.passes, pid)
    d = DB.devices.get(p["device_id"])
    h = DB.households.get(d["household_id"]) if d else None
    authorize(actor, ["AccountOwner"], h["account_id"] if h else None)
    account = account_of_household(h)
    if account["status"] == "CANCELLED":
        err("ERR_ACCOUNT_CANCELLED", 409, "Account is cancelled")
    apply_pass_lazy(p)
    if p["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", 409, "Pass must be ACTIVE to revoke")
    revoke_pass_cascade(p, h["account_id"])
    return ok_obj(ser_pass(p))


@app.post("/hv/travel-passes/<pid>/convert")
def convert_pass(pid):
    actor = authenticate()
    p = get_or_404("pass", DB.passes, pid)
    d = DB.devices.get(p["device_id"])
    h = DB.households.get(d["household_id"]) if d else None
    authorize(actor, ["AccountOwner", "PlatformAdmin"], h["account_id"] if h else None)
    account = account_of_household(h)
    account_gate(account)
    apply_pass_lazy(p)
    if p["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", 409, "Pass must be ACTIVE to convert")
    if d["network_fingerprint"] != h["network_fingerprint"]:
        err("ERR_DEVICE_NOT_TRUSTED", 403, "Device is not on the household network")
    p["status"] = "CONVERTED"
    touch(p)
    if d["trust_status"] == "UNTRUSTED":
        d["trust_status"] = "TRUSTED"
        touch(d)
    return ok_obj(ser_pass(p))


# ---------------------------------------------------------------------------
# Profile transfers
# ---------------------------------------------------------------------------


@app.post("/hv/accounts/<aid>/profile-transfers")
def create_transfer(aid):
    b = body()
    member_id = req_str(b, "member_id")
    target_email = req_str(b, "target_email")
    actor = authenticate()
    account = get_or_404("account", DB.accounts, aid)
    authorize(actor, ["AccountOwner"], account["id"])
    account_gate(account)
    m = DB.members.get(member_id)
    if m is None:
        err("ERR_MEMBER_NOT_FOUND", 404, "No member with the given id")
    if m["account_id"] != aid:
        err("ERR_MEMBER_NOT_IN_ACCOUNT", 422, "Member does not belong to the source account")
    if target_email == account["email"]:
        err("ERR_TRANSFER_TARGET_SELF", 422, "target_email equals the source account's email")
    t = new_common()
    t.update({
        "source_account_id": aid,
        "member_id": member_id,
        "target_email": target_email,
        "status": "AWAITING_ACCEPTANCE",
        "expires_at": iso(now() + timedelta(days=7)),
        "history_snapshot": list(m["viewing_history"]),
        "recommendation_snapshot": m["recommendation_seed"],
        "target_account_id": None,
    })
    DB.transfers[t["id"]] = t
    return ok_obj(ser_transfer(t), 201)


@app.get("/hv/profile-transfers/<tid>")
def get_transfer(tid):
    actor = authenticate()
    t = get_or_404("transfer", DB.transfers, tid)
    authorize(actor, ["PlatformAdmin", "SupportAgent", "AccountOwner"], t["source_account_id"])
    return ok_obj(ser_transfer(t))


@app.get("/hv/accounts/<aid>/profile-transfers")
def list_account_transfers(aid):
    actor = authenticate()
    account = get_or_404("account", DB.accounts, aid)
    authorize(actor, ["PlatformAdmin", "SupportAgent", "AccountOwner"], account["id"])
    limit, offset = pagination()
    items = [t for t in DB.transfers.values() if t["source_account_id"] == aid]
    for t in items:
        apply_transfer_lazy(t)
    status = request.args.get("status")
    if status:
        items = [t for t in items if t["status"] == status]
    items = [ser_transfer(t) for t in sorted_by_created(items)]
    return paginate(items, limit, offset)


@app.get("/hv/profile-transfers")
def list_transfers():
    actor = authenticate()
    authorize(actor, ["PlatformAdmin", "SupportAgent"])
    limit, offset = pagination()
    items = list(DB.transfers.values())
    for t in items:
        apply_transfer_lazy(t)
    mid = request.args.get("member_id")
    if mid:
        items = [t for t in items if t["member_id"] == mid]
    status = request.args.get("status")
    if status:
        items = [t for t in items if t["status"] == status]
    items = [ser_transfer(t) for t in sorted_by_created(items)]
    return paginate(items, limit, offset)


@app.post("/hv/profile-transfers/<tid>/accept")
def accept_transfer(tid):
    b = body()
    email = req_str(b, "new_account_email")
    region = req_enum(b, "new_account_region", REGIONS)
    tier = req_enum(b, "new_account_plan_tier", TIERS)
    if "expected_profile_transfer_version" not in b or not isinstance(b.get("expected_profile_transfer_version"), int) or isinstance(b.get("expected_profile_transfer_version"), bool):
        err("ERR_VALIDATION", 400, "expected_profile_transfer_version is required and must be an integer")
    expected = b["expected_profile_transfer_version"]
    actor = authenticate()
    authorize(actor, ["PlatformAdmin"])
    t = get_or_404("transfer", DB.transfers, tid)
    if expected != t["version"]:
        err("ERR_STALE_TRANSFER_VERSION", 412, "Stale transfer version")
    apply_transfer_lazy(t)
    if t["status"] != "AWAITING_ACCEPTANCE":
        err("ERR_INVALID_STATE", 409, "Transfer is not AWAITING_ACCEPTANCE")
    new_account = create_account_record(email, region, tier)
    # Remove the auto-created owner of the new account; the transferred member
    # becomes the owner instead.
    auto_owner = DB.members.get(new_account["owner_member_id"])
    m = DB.members.get(t["member_id"])
    m["account_id"] = new_account["id"]
    m["member_role"] = "OWNER"
    touch(m)
    if auto_owner is not None:
        auto_owner["status"] = "REMOVED"
        auto_owner["account_id"] = new_account["id"]
        touch(auto_owner)
    new_account["owner_member_id"] = m["id"]
    touch(new_account)
    for s in DB.slots.values():
        if s["member_id"] == m["id"] and s["status"] == "ACTIVE":
            s["status"] = "REVOKED"
            s["credit_cents"] = 0
            touch(s)
    t["target_account_id"] = new_account["id"]
    t["status"] = "COMPLETED"
    touch(t)
    return ok_obj(ser_transfer(t))


@app.post("/hv/profile-transfers/<tid>/cancel")
def cancel_transfer(tid):
    actor = authenticate()
    t = get_or_404("transfer", DB.transfers, tid)
    authorize(actor, ["AccountOwner"], t["source_account_id"])
    apply_transfer_lazy(t)
    if t["status"] != "AWAITING_ACCEPTANCE":
        err("ERR_INVALID_STATE", 409, "Transfer is not AWAITING_ACCEPTANCE")
    t["status"] = "CANCELLED"
    touch(t)
    return ok_obj(ser_transfer(t))


# ---------------------------------------------------------------------------
# Playback sessions
# ---------------------------------------------------------------------------


def check_playback_device(member, device_id):
    """Device must exist, belong to the account's household, and be TRUSTED or
    hold an ACTIVE travel pass."""
    d = DB.devices.get(device_id)
    if d is None:
        err("ERR_DEVICE_NOT_FOUND", 404, "No device with the given id")
    h = DB.households.get(d["household_id"])
    if h is None or h["account_id"] != member["account_id"] or h["status"] == "DISSOLVED":
        err("ERR_DEVICE_NOT_TRUSTED", 403, "Device does not belong to the account's household")
    apply_pass_lazy_all()
    has_pass = any(
        p["device_id"] == device_id and p["status"] == "ACTIVE"
        for p in DB.passes.values()
    )
    if d["trust_status"] != "TRUSTED" and not has_pass:
        err("ERR_DEVICE_NOT_TRUSTED", 403, "Device is neither TRUSTED nor holding an ACTIVE travel pass")
    return d


@app.post("/hv/members/<mid>/playback-sessions")
def start_session(mid):
    b = body()
    device_id = req_str(b, "device_id")
    resolution = req_enum(b, "requested_resolution", {"SD", "HD", "UHD"})
    actor = authenticate()
    m = get_or_404("member", DB.members, mid)
    authorize(actor, ["AccountOwner", "HouseholdMember", "ExtraMember"], m["account_id"])
    account = DB.accounts.get(m["account_id"])
    account_gate(account)
    if m["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", 409, "Member is not ACTIVE")
    d = check_playback_device(m, device_id)
    if RES_ORDER[resolution] > TIER_MAX_RES[account["plan_tier"]]:
        err("ERR_RESOLUTION_NOT_ENTITLED", 403, "Requested resolution exceeds plan tier maximum")
    active = sum(
        1 for s in DB.sessions.values()
        if s["status"] == "ACTIVE"
        and DB.members.get(s["member_id"], {}).get("account_id") == account["id"]
    )
    if active >= TIER_MAX_STREAMS[account["plan_tier"]]:
        err("ERR_STREAM_LIMIT_REACHED", 409, "Concurrent stream limit reached")
    s = light_common()
    s.update({
        "member_id": mid,
        "device_id": d["id"],
        "requested_resolution": resolution,
        "resolution_granted": resolution,
        "status": "ACTIVE",
        "started_at": iso(now()),
        "ended_at": None,
    })
    DB.sessions[s["id"]] = s
    return ok_obj(ser_session(s), 201)


@app.get("/hv/playback-sessions/<sid>")
def get_session(sid):
    actor = authenticate()
    s = get_or_404("session", DB.sessions, sid)
    m = DB.members.get(s["member_id"])
    authorize(actor, ["PlatformAdmin", "SupportAgent", "AccountOwner", "HouseholdMember", "ExtraMember"], m["account_id"] if m else None)
    return ok_obj(ser_session(s))


@app.get("/hv/members/<mid>/playback-sessions")
def list_member_sessions(mid):
    actor = authenticate()
    m = get_or_404("member", DB.members, mid)
    authorize(actor, ["PlatformAdmin", "SupportAgent", "AccountOwner", "HouseholdMember", "ExtraMember"], m["account_id"])
    limit, offset = pagination()
    items = [s for s in DB.sessions.values() if s["member_id"] == mid]
    status = request.args.get("status")
    if status:
        items = [s for s in items if s["status"] == status]
    items = [ser_session(s) for s in sorted_by_created(items)]
    return paginate(items, limit, offset)


@app.get("/hv/devices/<did>/playback-sessions")
def list_device_sessions(did):
    actor = authenticate()
    d = get_or_404("device", DB.devices, did)
    h = DB.households.get(d["household_id"])
    authorize(actor, ["PlatformAdmin", "SupportAgent", "AccountOwner", "HouseholdMember", "ExtraMember"], h["account_id"] if h else None)
    limit, offset = pagination()
    items = [s for s in DB.sessions.values() if s["device_id"] == did]
    status = request.args.get("status")
    if status:
        items = [s for s in items if s["status"] == status]
    items = [ser_session(s) for s in sorted_by_created(items)]
    return paginate(items, limit, offset)


@app.post("/hv/playback-sessions/<sid>/end")
def end_session(sid):
    actor = authenticate()
    s = get_or_404("session", DB.sessions, sid)
    m = DB.members.get(s["member_id"])
    authorize(actor, ["AccountOwner", "HouseholdMember", "ExtraMember"], m["account_id"] if m else None)
    if s["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", 409, "Session is not ACTIVE")
    s["status"] = "ENDED"
    s["ended_at"] = iso(now())
    return ok_obj(ser_session(s))


# ---------------------------------------------------------------------------
# Downloads
# ---------------------------------------------------------------------------


@app.post("/hv/members/<mid>/downloads")
def create_download(mid):
    b = body()
    device_id = req_str(b, "device_id")
    title_id = req_str(b, "title_id")
    actor = authenticate()
    m = get_or_404("member", DB.members, mid)
    authorize(actor, ["AccountOwner", "HouseholdMember", "ExtraMember"], m["account_id"])
    account = DB.accounts.get(m["account_id"])
    account_gate(account)
    if m["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", 409, "Member is not ACTIVE")
    d = check_playback_device(m, device_id)
    month = now().strftime("%Y-%m")
    for dl in DB.downloads.values():
        apply_download_lazy(dl)
    used = sum(
        1 for dl in DB.downloads.values()
        if dl["status"] == "ACTIVE"
        and dl["billing_month"] == month
        and DB.members.get(dl["member_id"], {}).get("account_id") == account["id"]
    )
    if used >= TIER_MONTHLY_DL[account["plan_tier"]]:
        err("ERR_DOWNLOAD_LIMIT_REACHED", 409, "Monthly download allowance reached")
    dl = light_common()
    dl.update({
        "member_id": mid,
        "device_id": d["id"],
        "title_id": title_id,
        "status": "ACTIVE",
        "billing_month": month,
    })
    DB.downloads[dl["id"]] = dl
    return ok_obj(ser_download(dl), 201)


@app.get("/hv/downloads/<did>")
def get_download(did):
    actor = authenticate()
    dl = get_or_404("download", DB.downloads, did)
    m = DB.members.get(dl["member_id"])
    authorize(actor, ["PlatformAdmin", "SupportAgent", "AccountOwner", "HouseholdMember", "ExtraMember"], m["account_id"] if m else None)
    return ok_obj(ser_download(dl))


@app.get("/hv/members/<mid>/downloads")
def list_member_downloads(mid):
    actor = authenticate()
    m = get_or_404("member", DB.members, mid)
    authorize(actor, ["PlatformAdmin", "SupportAgent", "AccountOwner", "HouseholdMember", "ExtraMember"], m["account_id"])
    limit, offset = pagination()
    items = [dl for dl in DB.downloads.values() if dl["member_id"] == mid]
    for dl in items:
        apply_download_lazy(dl)
    status = request.args.get("status")
    if status:
        items = [dl for dl in items if dl["status"] == status]
    bm = request.args.get("billing_month")
    if bm:
        items = [dl for dl in items if dl["billing_month"] == bm]
    items = [ser_download(dl) for dl in sorted_by_created(items)]
    return paginate(items, limit, offset)


@app.get("/hv/devices/<did>/downloads")
def list_device_downloads(did):
    actor = authenticate()
    d = get_or_404("device", DB.devices, did)
    h = DB.households.get(d["household_id"])
    authorize(actor, ["PlatformAdmin", "SupportAgent", "AccountOwner", "HouseholdMember", "ExtraMember"], h["account_id"] if h else None)
    limit, offset = pagination()
    items = [dl for dl in DB.downloads.values() if dl["device_id"] == did]
    for dl in items:
        apply_download_lazy(dl)
    status = request.args.get("status")
    if status:
        items = [dl for dl in items if dl["status"] == status]
    items = [ser_download(dl) for dl in sorted_by_created(items)]
    return paginate(items, limit, offset)


@app.delete("/hv/downloads/<did>")
def delete_download(did):
    actor = authenticate()
    dl = get_or_404("download", DB.downloads, did)
    m = DB.members.get(dl["member_id"])
    authorize(actor, ["AccountOwner", "HouseholdMember", "ExtraMember"], m["account_id"] if m else None)
    account = DB.accounts.get(m["account_id"]) if m else None
    if account is not None and account["status"] == "CANCELLED":
        err("ERR_ACCOUNT_CANCELLED", 409, "Account is cancelled")
    apply_download_lazy(dl)
    if dl["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", 409, "Download is not ACTIVE")
    dl["status"] = "DELETED"
    return ok_obj(ser_download(dl))


# ---------------------------------------------------------------------------
# Enforcement policies
# ---------------------------------------------------------------------------


@app.post("/hv/enforcement-policies")
def create_policy():
    b = body()
    region = req_enum(b, "region_code", REGIONS)
    enabled = req_bool(b, "enforcement_enabled")
    grace = req_int(b, "grace_days", minimum=0)
    variant = req_enum(b, "messaging_variant", {"SOFT", "HARD"})
    eff = req_dt(b, "effective_from")
    actor = authenticate()
    authorize(actor, ["PlatformAdmin"])
    p = new_common()
    p.update({
        "region_code": region,
        "enforcement_enabled": enabled,
        "grace_days": grace,
        "messaging_variant": variant,
        "effective_from": iso(eff),
        "status": "DRAFT",
    })
    DB.policies[p["id"]] = p
    return ok_obj(ser_policy(p), 201)


@app.get("/hv/enforcement-policies/<pid>")
def get_policy(pid):
    actor = authenticate()
    p = get_or_404("policy", DB.policies, pid)
    authorize(actor, ["PlatformAdmin", "SupportAgent"])
    return ok_obj(ser_policy(p))


@app.get("/hv/enforcement-policies")
def list_policies():
    actor = authenticate()
    authorize(actor, ["PlatformAdmin", "SupportAgent"])
    limit, offset = pagination()
    items = list(DB.policies.values())
    region = request.args.get("region_code")
    if region:
        items = [p for p in items if p["region_code"] == region]
    status = request.args.get("status")
    if status:
        items = [p for p in items if p["status"] == status]
    items = [ser_policy(p) for p in sorted_by_created(items)]
    return paginate(items, limit, offset)


@app.post("/hv/enforcement-policies/<pid>/activate")
def activate_policy(pid):
    actor = authenticate()
    authorize(actor, ["PlatformAdmin"])
    p = get_or_404("policy", DB.policies, pid)
    if p["status"] != "DRAFT":
        err("ERR_INVALID_STATE", 409, "Policy must be DRAFT to activate")
    for other in DB.policies.values():
        if other["id"] != p["id"] and other["region_code"] == p["region_code"] and other["status"] == "ACTIVE":
            other["status"] = "RETIRED"
            touch(other)
    p["status"] = "ACTIVE"
    touch(p)
    return ok_obj(ser_policy(p))


@app.post("/hv/enforcement-policies/<pid>/retire")
def retire_policy(pid):
    actor = authenticate()
    authorize(actor, ["PlatformAdmin"])
    p = get_or_404("policy", DB.policies, pid)
    if p["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", 409, "Policy must be ACTIVE to retire")
    p["status"] = "RETIRED"
    touch(p)
    return ok_obj(ser_policy(p))


# ---------------------------------------------------------------------------
# Enforcement metrics & churn summary
# ---------------------------------------------------------------------------


@app.post("/hv/accounts/<aid>/enforcement-metrics")
def record_metric(aid):
    b = body()
    mtype = req_enum(b, "metric_type", {"CHURN_SIGNAL", "COMPLAINT", "WINBACK"})
    notes = b.get("notes", "")
    if notes is None:
        notes = ""
    if not isinstance(notes, str):
        err("ERR_VALIDATION", 400, "notes must be a string")
    actor = authenticate()
    account = get_or_404("account", DB.accounts, aid)
    authorize(actor, ["PlatformAdmin", "SupportAgent"])
    m = light_common()
    m.update({
        "account_id": aid,
        "metric_type": mtype,
        "notes": notes,
        "recorded_at": iso(now()),
    })
    DB.metrics[m["id"]] = m
    return ok_obj(ser_metric(m), 201)


@app.get("/hv/accounts/<aid>/enforcement-metrics")
def list_metrics(aid):
    actor = authenticate()
    account = get_or_404("account", DB.accounts, aid)
    authorize(actor, ["PlatformAdmin", "SupportAgent"])
    limit, offset = pagination()
    items = [m for m in DB.metrics.values() if m["account_id"] == aid]
    mtype = request.args.get("metric_type")
    if mtype:
        items = [m for m in items if m["metric_type"] == mtype]
    items = [ser_metric(m) for m in sorted_by_created(items)]
    return paginate(items, limit, offset)


@app.get("/hv/accounts/<aid>/churn-summary")
def churn_summary(aid):
    actor = authenticate()
    account = get_or_404("account", DB.accounts, aid)
    authorize(actor, ["PlatformAdmin", "SupportAgent"])
    churn = sum(1 for m in DB.metrics.values() if m["account_id"] == aid and m["metric_type"] == "CHURN_SIGNAL")
    winbacks = sum(1 for m in DB.metrics.values() if m["account_id"] == aid and m["metric_type"] == "WINBACK")
    active_flag = 1 if account["status"] == "ACTIVE" else 0
    denom = churn + winbacks + active_flag
    gross = round4(churn / denom) if denom else 0.0
    net = round4(max(0, churn - winbacks) / denom) if denom else 0.0
    return ok_obj({
        "churn_signals": churn,
        "winbacks": winbacks,
        "active_flag": active_flag,
        "gross_churn_rate": gross,
        "net_churn_rate": net,
    })


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
