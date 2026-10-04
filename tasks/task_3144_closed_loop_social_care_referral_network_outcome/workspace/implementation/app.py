from decimal import Decimal, ROUND_HALF_UP
import re
import uuid
from datetime import datetime, timezone, timedelta

from flask import Flask, request, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# In-memory store (empty at every boot; nothing is seeded)
# ---------------------------------------------------------------------------
STORE = {
    "networks": {},
    "taxonomy": {},
    "orgs": {},
    "offerings": {},
    "clients": {},
    "agreements": {},
    "consents": {},
    "referrals": {},
    "notes": {},
    "outcomes": {},
    "rate_cards": {},
    "claims": {},
    "disbursements": {},
    "reports": {},
}

CLOCK = {"now": datetime(2026, 9, 1, tzinfo=timezone.utc)}

TERMINAL_REFERRAL_STATES = {"CANCELLED", "EXPIRED", "OUTCOME_RECORDED"}
ROLES = {"NetworkCoordinator", "CaseWorker", "OrgAdmin", "FunderAdmin"}
GENDERS = {"FEMALE", "MALE", "NONBINARY", "UNDISCLOSED"}
RACES = {"AMERICAN_INDIAN", "ASIAN", "BLACK", "PACIFIC_ISLANDER", "WHITE",
         "MULTIRACIAL", "UNDISCLOSED"}
ETHNICITIES = {"HISPANIC", "NON_HISPANIC", "UNDISCLOSED"}
ORG_TYPES = {"CBO", "CLINIC", "FUNDER"}
FUNDER_TYPES = {"HEALTH_PLAN", "PUBLIC_AGENCY", "NONE"}
OUTCOME_CODES = {"DELIVERED", "NOT_REACHED", "CLIENT_DECLINED",
                 "PARTIALLY_DELIVERED"}
K_ANON = 5
DAYS_PER_YEAR = Decimal("365.25")

_iso_z_re = re.compile(r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})"
                       r"(?:\.(\d+))?(?:Z|([+-])(\d{2}):?(\d{2}))?$")


class ApiError(Exception):
    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message


def err(error_id, status, message):
    raise ApiError(error_id, status, message)


def fmt_ts(dt):
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + (".%03dZ" % ms)


def clock_now():
    return CLOCK["now"]


def parse_dt(s):
    if not isinstance(s, str):
        return None
    s2 = s.strip()
    if s2.endswith("Z"):
        s2 = s2[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s2)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(s):
    if not isinstance(s, str):
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------
def envelope_ok(data, status=200, list_meta=None):
    meta = {
        "api_request_id": "req_" + uuid.uuid4().hex,
        "api_request_timestamp": fmt_ts(datetime.now(timezone.utc)),
    }
    if list_meta is not None:
        meta.update(list_meta)
    response_type = "array" if list_meta is not None else "object"
    body = {"meta": meta, "response_type": response_type, "data": data}
    resp = jsonify(body)
    resp.status_code = status
    return resp


def envelope_error(e):
    body = {
        "meta": {
            "api_request_id": "req_" + uuid.uuid4().hex,
            "api_request_timestamp": fmt_ts(datetime.now(timezone.utc)),
        },
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    resp = jsonify(body)
    resp.status_code = e.status
    return resp


@app.errorhandler(ApiError)
def handle_api_error(e):
    return envelope_error(e)


@app.errorhandler(404)
def handle_404(e):
    return envelope_error(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))


@app.errorhandler(405)
def handle_405(e):
    return envelope_error(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))


@app.errorhandler(Exception)
def handle_exception(e):
    return envelope_error(ApiError("ERR_INVALID_REQUEST", 400, str(e)))


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------
def caller_org_prefix():
    uid = request.headers.get("X-User-ID")
    if uid is None:
        return None
    return uid.split("#", 1)[0]


def require_auth():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not isinstance(uid, str) or uid.strip() == "":
        err("ERR_UNAUTHENTICATED", 401,
            "Missing or malformed X-User-ID / X-User-Role headers")
    if role not in ROLES:
        err("ERR_UNAUTHENTICATED", 401,
            "Missing or malformed X-User-ID / X-User-Role headers")
    return uid, role


def require_roles(*allowed):
    uid, role = require_auth()
    if role not in allowed:
        err("ERR_UNAUTHORIZED_ROLE", 403,
            "Role not permitted for this endpoint")
    return uid, role


def require_caller_org(expected_org_id):
    if caller_org_prefix() != expected_org_id:
        err("ERR_FORBIDDEN_ORG", 403,
            "Caller org does not own or is not the counterparty of the target "
            "resource")


# ---------------------------------------------------------------------------
# Body / field validation helpers
# ---------------------------------------------------------------------------
def get_body(allowed_fields=None):
    if not request.data:
        body = {}
    else:
        try:
            body = request.get_json(force=True, silent=False)
        except Exception:
            err("ERR_INVALID_REQUEST", 400, "Request body must be valid JSON")
    if body is None:
        body = {}
    if not isinstance(body, dict):
        err("ERR_INVALID_REQUEST", 400, "Request body must be a JSON object")
    if allowed_fields is not None:
        for k in body:
            if k not in allowed_fields:
                err("ERR_INVALID_REQUEST", 400, "Unknown field: %s" % k)
    return body


def req_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        err("ERR_INVALID_REQUEST", 400,
            "Missing or invalid required field: %s" % field)
    return v


def opt_str(body, field, default=None):
    if field not in body:
        return default
    v = body.get(field)
    if v is None:
        return default
    if not isinstance(v, str):
        err("ERR_INVALID_REQUEST", 400, "Invalid field: %s" % field)
    return v


def req_int(body, field):
    v = body.get(field)
    if not is_int(v):
        err("ERR_INVALID_REQUEST", 400,
            "Missing or invalid required field: %s" % field)
    return v


def opt_int(body, field, default=None):
    if field not in body:
        return default
    v = body.get(field)
    if v is None:
        return default
    if not is_int(v):
        err("ERR_INVALID_REQUEST", 400, "Invalid field: %s" % field)
    return v


def req_enum(body, field, allowed):
    v = body.get(field)
    if v not in allowed:
        err("ERR_INVALID_REQUEST", 400,
            "Missing or invalid enum value for field: %s" % field)
    return v


def opt_enum(body, field, allowed, default):
    if field not in body:
        return default
    v = body.get(field)
    if v is None:
        return default
    if v not in allowed:
        err("ERR_INVALID_REQUEST", 400, "Invalid enum value for field: %s"
            % field)
    return v


def opt_str_list(body, field, default):
    if field not in body:
        return list(default)
    v = body.get(field)
    if v is None:
        return list(default)
    if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
        err("ERR_INVALID_REQUEST", 400,
            "Invalid field: %s (must be array of strings)" % field)
    return list(v)


def req_occ(body, field, current):
    v = body.get(field)
    if not is_int(v):
        err("ERR_INVALID_REQUEST", 400,
            "Missing or invalid required field: %s" % field)
    if v != current:
        err("ERR_STALE_VERSION", 412,
            "Stale version: expected %s but current is %s" % (v, current))


# ---------------------------------------------------------------------------
# Lookups and pagination
# ---------------------------------------------------------------------------
def lookup(kind, entity_id):
    rec = STORE[kind].get(entity_id)
    if rec is None:
        err("ERR_NOT_FOUND", 404, "Resource not found: %s" % entity_id)
    return rec


def get_network():
    if not STORE["networks"]:
        return None
    return next(iter(STORE["networks"].values()))


def require_network():
    net = get_network()
    if net is None:
        err("ERR_NOT_FOUND", 404, "CareNetwork not found")
    return net


def parse_pagination():
    raw_limit = request.args.get("limit", "10")
    raw_offset = request.args.get("offset", "0")
    try:
        limit = int(raw_limit)
        offset = int(raw_offset)
    except (TypeError, ValueError):
        err("ERR_INVALID_REQUEST", 400, "Invalid pagination parameters")
    if limit < 1 or limit > 100 or offset < 0:
        err("ERR_INVALID_REQUEST", 400, "Invalid pagination parameters")
    return limit, offset


def list_response(records, serialize):
    limit, offset = parse_pagination()
    ordered = sorted(records,
                     key=lambda r: (r["created_at"], r["id"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return envelope_ok([serialize(r) for r in page], 200, meta)


def touch(rec):
    rec["updated_at"] = fmt_ts(clock_now())
    rec["version"] += 1


def new_record(common=True):
    ts = fmt_ts(clock_now())
    rec = {"id": str(uuid.uuid4()), "created_at": ts}
    if common:
        rec["updated_at"] = ts
        rec["version"] = 1
    return rec


def client_age_years(client, as_of_dt):
    dob = parse_date(client["date_of_birth"])
    days = (as_of_dt.date() - dob).days
    return int(Decimal(days) / DAYS_PER_YEAR)


def has_active_agreement(org_x, org_y):
    for a in STORE["agreements"].values():
        if a["status"] != "ACTIVE":
            continue
        pair = {a["party_a_org_id"], a["party_b_org_id"]}
        if org_x in pair and org_y in pair:
            return True
    return False


def consent_covers(consent, sender, receiver):
    return (consent["sender_org_id"] == sender
            and consent["receiver_org_id"] == receiver)


def referral_aging_days(ref):
    if ref["status"] == "DRAFT":
        return 0
    if ref["status"] in TERMINAL_REFERRAL_STATES:
        end = parse_dt(ref["updated_at"]) or clock_now()
    else:
        end = clock_now()
    start = parse_dt(ref["created_at"]) or end
    days = int((end - start).total_seconds() // 86400)
    return max(days, 0)


def sync_report(report):
    funder_id = report["funder_org_id"]
    ps = parse_date(report["period_start"])
    pe = parse_date(report["period_end"])
    net = get_network()
    unresolved_aging_days = (net["unresolved_aging_days"] if net
                             else 30)
    period_refs = []
    for r in STORE["referrals"].values():
        cd = parse_dt(r["created_at"])
        if cd is None:
            continue
        d = cd.date()
        if not (ps <= d <= pe):
            continue
        if not has_active_agreement(funder_id, r["receiver_org_id"]):
            continue
        period_refs.append(r)
    total = len(period_refs)
    delivered = 0
    not_reached = 0
    unresolved = 0
    aging = 0
    for r in period_refs:
        o = STORE["outcomes"].get(r["id"])
        if o is not None:
            if o["outcome_code"] in ("DELIVERED", "PARTIALLY_DELIVERED"):
                delivered += 1
            else:
                not_reached += 1
        if r["status"] not in TERMINAL_REFERRAL_STATES:
            unresolved += 1
            if referral_aging_days(r) > unresolved_aging_days:
                aging += 1
    total_reimbursed = 0
    for c in STORE["claims"].values():
        if c["funder_org_id"] != funder_id:
            continue
        amt = c.get("approved_amount_cents")
        if amt is None:
            continue
        if c["status"] == "APPROVED":
            ad = (parse_dt(c["updated_at"]) or clock_now()).date()
            if ps <= ad <= pe:
                total_reimbursed += amt
        elif c["status"] == "VOIDED" and c.get("approved_at") is not None:
            ad = (parse_dt(c["approved_at"]) or clock_now()).date()
            if ps <= ad <= pe:
                total_reimbursed += amt - c.get("clawback_reserve_cents", 0)

    cells = {}
    for r in period_refs:
        client = STORE["clients"].get(r["client_id"])
        if client is None:
            continue
        key = "%s|%s|%s|%s|%s" % (
            client["gender"], client["race"], client["ethnicity"],
            str(client["veteran_status"]).lower(), client["language"])
        cells[key] = cells.get(key, 0) + 1
    breakdown = {}
    suppressed_total = 0
    for key, cnt in cells.items():
        if cnt >= K_ANON:
            breakdown[key] = cnt
        else:
            suppressed_total += cnt
    if suppressed_total >= K_ANON:
        breakdown["SUPPRESSED"] = suppressed_total

    if total == 0:
        closure = 0.0
        resolution = 0.0
    else:
        closure = float(
            (Decimal(delivered) * 100 / Decimal(total)).quantize(
                Decimal("0.1"), rounding=ROUND_HALF_UP))
        resolution = float(
            (Decimal(delivered + not_reached) * 100 / Decimal(total))
            .quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))

    report["total_referrals"] = total
    report["delivered_count"] = delivered
    report["not_reached_count"] = not_reached
    report["unresolved_count"] = unresolved
    report["aging_count"] = aging
    report["total_reimbursed_cents"] = total_reimbursed
    report["demographic_breakdown"] = breakdown
    report["closure_rate_percent"] = closure
    report["resolution_rate_percent"] = resolution


def run_aging_sweep():
    expired_ids = []
    for net in STORE["networks"].values():
        expiry = net["referral_expiry_days"]
        for ref in list(STORE["referrals"].values()):
            if ref["status"] != "ROUTED":
                continue
            routed_at = parse_dt(ref["updated_at"]) or clock_now()
            days = int((clock_now() - routed_at).total_seconds() // 86400)
            if days > expiry:
                off = STORE["offerings"].get(ref["service_offering_id"])
                if off is not None:
                    off["capacity_consumed"] -= 1
                    off["capacity_available"] = (off["capacity_total"]
                                                 - off["capacity_consumed"])
                    touch(off)
                ref["status"] = "EXPIRED"
                touch(ref)
                client = STORE["clients"].get(ref["client_id"])
                if client is not None:
                    client["open_referral_count"] -= 1
                    touch(client)
                expired_ids.append(ref["id"])
    return expired_ids


def void_claim(claim, use_approved, net):
    """Precondition: escrow sufficiency already checked. Mutates claim,
    provider balance, and escrow."""
    provider = STORE["orgs"].get(claim["provider_org_id"])
    if use_approved:
        amt = claim["approved_amount_cents"]
        balance = provider["payable_balance_cents"]
        shortfall = max(0, amt - balance)
        provider["payable_balance_cents"] = max(0, balance - amt)
        claim["clawback_reserve_cents"] = shortfall
        if shortfall:
            touch(provider)
    else:
        shortfall = claim["provisional_amount_cents"]
        claim["clawback_reserve_cents"] = shortfall
    net["network_escrow_cents"] -= shortfall
    net["network_escrow_reserved_cents"] += shortfall
    if shortfall:
        touch(net)
    claim["status"] = "VOIDED"
    touch(claim)


def cancel_referral_for_consent(ref):
    """Cascade C hop 1/2/3 (referral part)."""
    if ref["status"] in ("ROUTED",):
        off = STORE["offerings"].get(ref["service_offering_id"])
        if off is not None:
            off["capacity_consumed"] -= 1
            off["capacity_available"] = (off["capacity_total"]
                                         - off["capacity_consumed"])
            touch(off)
    ref["status"] = "CANCELLED"
    touch(ref)
    client = STORE["clients"].get(ref["client_id"])
    if client is not None:
        client["open_referral_count"] -= 1
        touch(client)


def revoke_consent(consent):
    """Full consent revocation with cascades. Assumes consent is ACTIVE."""
    # Pre-compute claims to void and the total reserve for atomicity.
    claims_to_void = []
    total_reserve = 0
    for c in STORE["claims"].values():
        if c["status"] not in ("SUBMITTED", "UNDER_REVIEW"):
            continue
        ref = STORE["referrals"].get(c["referral_id"])
        if ref is None or ref["consent_id"] != consent["id"]:
            continue
        reserve = (c["approved_amount_cents"]
                   if c.get("approved_amount_cents") is not None
                   else c["provisional_amount_cents"])
        claims_to_void.append(c)
        total_reserve += reserve
    net = get_network()
    if claims_to_void:
        if net is None:
            err("ERR_ESCROW_EXHAUSTED", 402,
                "Network escrow cannot fund the clawback reserve")
        if total_reserve > net["network_escrow_cents"]:
            err("ERR_ESCROW_EXHAUSTED", 402,
                "Network escrow cannot fund the clawback reserve")
    consent["status"] = "REVOKED"
    consent["revoked_at"] = fmt_ts(clock_now())
    touch(consent)
    for ref in list(STORE["referrals"].values()):
        if ref["consent_id"] != consent["id"]:
            continue
        if ref["status"] in ("DRAFT", "ROUTED", "DECLINED", "ESCALATED"):
            cancel_referral_for_consent(ref)
    for c in claims_to_void:
        void_claim(c, False, net)


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
def ser_network(n):
    return {
        "id": n["id"], "name": n["name"],
        "coordinator_org_name": n["coordinator_org_name"],
        "max_reassignment_count": n["max_reassignment_count"],
        "auto_accept_window_hours": n["auto_accept_window_hours"],
        "unresolved_aging_days": n["unresolved_aging_days"],
        "referral_expiry_days": n["referral_expiry_days"],
        "network_escrow_cents": n["network_escrow_cents"],
        "network_escrow_reserved_cents": n["network_escrow_reserved_cents"],
        "created_at": n["created_at"], "updated_at": n["updated_at"],
        "version": n["version"],
    }


def ser_taxonomy(t):
    return {
        "id": t["id"], "code": t["code"], "name": t["name"],
        "status": t["status"], "created_at": t["created_at"],
        "updated_at": t["updated_at"], "version": t["version"],
    }


def ser_org(o):
    return {
        "id": o["id"], "name": o["name"], "org_type": o["org_type"],
        "funder_type": o["funder_type"], "ein": o["ein"],
        "status": o["status"], "suspension_reason": o["suspension_reason"],
        "payable_balance_cents": o["payable_balance_cents"],
        "created_at": o["created_at"], "updated_at": o["updated_at"],
        "version": o["version"],
    }


def ser_offering(o):
    return {
        "id": o["id"], "organization_id": o["organization_id"],
        "category_code": o["category_code"],
        "description": o["description"],
        "min_client_age": o["min_client_age"],
        "max_client_age": o["max_client_age"],
        "eligible_zip_codes": o["eligible_zip_codes"],
        "eligible_genders": o["eligible_genders"],
        "income_cap_annual_cents": o["income_cap_annual_cents"],
        "capacity_total": o["capacity_total"],
        "capacity_consumed": o["capacity_consumed"],
        "capacity_available": o["capacity_available"],
        "status": o["status"], "created_at": o["created_at"],
        "updated_at": o["updated_at"], "version": o["version"],
    }


def ser_client(c):
    return {
        "id": c["id"], "full_name": c["full_name"],
        "date_of_birth": c["date_of_birth"], "zip_code": c["zip_code"],
        "gender": c["gender"],
        "annual_income_cents": c["annual_income_cents"],
        "race": c["race"], "ethnicity": c["ethnicity"],
        "language": c["language"], "veteran_status": c["veteran_status"],
        "open_referral_count": c["open_referral_count"],
        "created_at": c["created_at"], "updated_at": c["updated_at"],
        "version": c["version"],
    }


def ser_agreement(a):
    return {
        "id": a["id"], "party_a_org_id": a["party_a_org_id"],
        "party_b_org_id": a["party_b_org_id"],
        "effective_at": a["effective_at"], "status": a["status"],
        "created_at": a["created_at"], "updated_at": a["updated_at"],
        "version": a["version"],
    }


def ser_consent(c):
    return {
        "id": c["id"], "client_id": c["client_id"],
        "sender_org_id": c["sender_org_id"],
        "receiver_org_id": c["receiver_org_id"], "scope": c["scope"],
        "status": c["status"], "revoked_at": c["revoked_at"],
        "created_at": c["created_at"], "updated_at": c["updated_at"],
        "version": c["version"],
    }


def ser_referral(r):
    return {
        "id": r["id"], "client_id": r["client_id"],
        "sender_org_id": r["sender_org_id"],
        "receiver_org_id": r["receiver_org_id"],
        "service_offering_id": r["service_offering_id"],
        "consent_id": r["consent_id"], "category_code": r["category_code"],
        "urgency": r["urgency"], "status": r["status"],
        "service_started_at": r["service_started_at"],
        "reassignment_count": r["reassignment_count"],
        "aging_days": referral_aging_days(r),
        "reopen_count": r["reopen_count"],
        "outcome_code": r["outcome_code"],
        "delivered_units": r["delivered_units"],
        "created_at": r["created_at"], "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_note(n):
    return {
        "id": n["id"], "referral_id": n["referral_id"],
        "author_org_id": n["author_org_id"], "body": n["body"],
        "visibility": n["visibility"], "created_at": n["created_at"],
    }


def ser_outcome(o):
    return {
        "id": o["id"], "referral_id": o["referral_id"],
        "outcome_code": o["outcome_code"],
        "delivered_units": o["delivered_units"],
        "reported_by_org_id": o["reported_by_org_id"],
        "reported_at": o["reported_at"], "billable": o["billable"],
        "created_at": o["created_at"],
    }


def ser_rate_card(rc):
    return {
        "id": rc["id"], "funder_org_id": rc["funder_org_id"],
        "category_code": rc["category_code"],
        "rate_cents_per_unit": rc["rate_cents_per_unit"],
        "min_units": rc["min_units"],
        "tier2_rate_cents_per_unit": rc["tier2_rate_cents_per_unit"],
        "monthly_cap_cents": rc["monthly_cap_cents"],
        "status": rc["status"], "created_at": rc["created_at"],
        "updated_at": rc["updated_at"], "version": rc["version"],
    }


def ser_claim(c):
    return {
        "id": c["id"], "referral_id": c["referral_id"],
        "funder_org_id": c["funder_org_id"],
        "provider_org_id": c["provider_org_id"],
        "claimed_units": c["claimed_units"],
        "reviewed_by_user_id": c["reviewed_by_user_id"],
        "provisional_amount_cents": c["provisional_amount_cents"],
        "approved_amount_cents": c["approved_amount_cents"],
        "clawback_reserve_cents": c["clawback_reserve_cents"],
        "status": c["status"], "created_at": c["created_at"],
        "updated_at": c["updated_at"], "version": c["version"],
    }


def ser_disbursement(d):
    return {
        "id": d["id"], "provider_org_id": d["provider_org_id"],
        "funder_org_id": d["funder_org_id"], "claim_ids": d["claim_ids"],
        "total_amount_cents": d["total_amount_cents"],
        "status": d["status"], "failure_reason": d["failure_reason"],
        "created_at": d["created_at"], "updated_at": d["updated_at"],
        "version": d["version"],
    }


def ser_report(r):
    return {
        "id": r["id"], "funder_org_id": r["funder_org_id"],
        "period_start": r["period_start"], "period_end": r["period_end"],
        "baseline_snapshot_cents": r["baseline_snapshot_cents"],
        "total_referrals": r["total_referrals"],
        "delivered_count": r["delivered_count"],
        "not_reached_count": r["not_reached_count"],
        "unresolved_count": r["unresolved_count"],
        "aging_count": r["aging_count"],
        "total_reimbursed_cents": r["total_reimbursed_cents"],
        "demographic_breakdown": r["demographic_breakdown"],
        "closure_rate_percent": r["closure_rate_percent"],
        "resolution_rate_percent": r["resolution_rate_percent"],
        "status": r["status"], "created_at": r["created_at"],
        "updated_at": r["updated_at"], "version": r["version"],
    }


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------
@app.post("/care-network/_clock/set_current_utc")
def set_clock():
    require_roles("NetworkCoordinator")
    body = get_body({"to_iso8601"})
    raw = req_str(body, "to_iso8601")
    dt = parse_dt(raw)
    if dt is None:
        err("ERR_INVALID_REQUEST", 400, "Invalid to_iso8601")
    CLOCK["now"] = dt
    run_aging_sweep()
    return envelope_ok({"current_utc": fmt_ts(CLOCK["now"])}, 200)


# ---------------------------------------------------------------------------
# Networks
# ---------------------------------------------------------------------------
@app.post("/care-network/networks")
def create_network():
    require_roles("NetworkCoordinator")
    body = get_body({"name", "coordinator_org_name", "max_reassignment_count",
                     "auto_accept_window_hours", "unresolved_aging_days",
                     "referral_expiry_days", "network_escrow_cents"})
    name = req_str(body, "name")
    coord = req_str(body, "coordinator_org_name")
    mrc = opt_int(body, "max_reassignment_count", 3)
    aaw = opt_int(body, "auto_accept_window_hours", 72)
    uad = opt_int(body, "unresolved_aging_days", 30)
    red = opt_int(body, "referral_expiry_days", 60)
    escrow = opt_int(body, "network_escrow_cents", 0)
    for label, v in (("max_reassignment_count", mrc),
                     ("auto_accept_window_hours", aaw),
                     ("unresolved_aging_days", uad),
                     ("referral_expiry_days", red),
                     ("network_escrow_cents", escrow)):
        if not is_int(v) or v < 0:
            err("ERR_INVALID_REQUEST", 400, "Invalid field: %s" % label)
    rec = new_record()
    rec.update({
        "name": name, "coordinator_org_name": coord,
        "max_reassignment_count": mrc, "auto_accept_window_hours": aaw,
        "unresolved_aging_days": uad, "referral_expiry_days": red,
        "network_escrow_cents": escrow, "network_escrow_reserved_cents": 0,
    })
    STORE["networks"][rec["id"]] = rec
    return envelope_ok(ser_network(rec), 201)


@app.get("/care-network/networks/<nid>")
def get_network_ep(nid):
    require_roles("NetworkCoordinator", "FunderAdmin", "OrgAdmin",
                  "CaseWorker")
    return envelope_ok(ser_network(lookup("networks", nid)), 200)


# ---------------------------------------------------------------------------
# Taxonomy
# ---------------------------------------------------------------------------
@app.post("/care-network/taxonomy")
def create_taxonomy():
    require_roles("NetworkCoordinator")
    body = get_body({"code", "name"})
    code = req_str(body, "code")
    name = req_str(body, "name")
    for t in STORE["taxonomy"].values():
        if t["code"] == code:
            err("ERR_INVALID_REQUEST", 400, "Duplicate taxonomy code")
    rec = new_record()
    rec.update({"code": code, "name": name, "status": "ACTIVE"})
    STORE["taxonomy"][rec["id"]] = rec
    return envelope_ok(ser_taxonomy(rec), 201)


@app.get("/care-network/taxonomy")
def list_taxonomy():
    require_roles("NetworkCoordinator", "FunderAdmin", "OrgAdmin",
                  "CaseWorker")
    status = request.args.get("status")
    recs = list(STORE["taxonomy"].values())
    if status is not None:
        recs = [t for t in recs if t["status"] == status]
    return list_response(recs, ser_taxonomy)


@app.get("/care-network/taxonomy/<tid>")
def get_taxonomy(tid):
    require_roles("NetworkCoordinator", "FunderAdmin", "OrgAdmin",
                  "CaseWorker")
    return envelope_ok(ser_taxonomy(lookup("taxonomy", tid)), 200)


@app.post("/care-network/taxonomy/<tid>/retire")
def retire_taxonomy(tid):
    require_roles("NetworkCoordinator")
    rec = lookup("taxonomy", tid)
    if rec["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", 409, "Category is not ACTIVE")
    for o in STORE["offerings"].values():
        if o["category_code"] == rec["code"] and o["status"] == "ACTIVE":
            err("ERR_CATEGORY_IN_USE", 409,
                "Category retirement blocked by ACTIVE offerings")
    rec["status"] = "RETIRED"
    touch(rec)
    return envelope_ok(ser_taxonomy(rec), 200)


# ---------------------------------------------------------------------------
# Organizations
# ---------------------------------------------------------------------------
@app.post("/care-network/organizations")
def create_org():
    require_roles("NetworkCoordinator")
    body = get_body({"name", "org_type", "ein", "funder_type"})
    name = req_str(body, "name")
    org_type = req_enum(body, "org_type", ORG_TYPES)
    ein = req_str(body, "ein")
    funder_type = opt_enum(body, "funder_type", FUNDER_TYPES, "NONE")
    for o in STORE["orgs"].values():
        if o["ein"] == ein:
            err("ERR_INVALID_REQUEST", 400, "Duplicate ein")
    rec = new_record()
    rec.update({
        "name": name, "org_type": org_type, "funder_type": funder_type,
        "ein": ein, "status": "PENDING_REVIEW", "suspension_reason": None,
        "payable_balance_cents": 0,
    })
    STORE["orgs"][rec["id"]] = rec
    return envelope_ok(ser_org(rec), 201)


@app.get("/care-network/organizations")
def list_orgs():
    require_roles("NetworkCoordinator", "FunderAdmin", "OrgAdmin",
                  "CaseWorker")
    org_type = request.args.get("org_type")
    status = request.args.get("status")
    recs = list(STORE["orgs"].values())
    if org_type is not None:
        recs = [o for o in recs if o["org_type"] == org_type]
    if status is not None:
        recs = [o for o in recs if o["status"] == status]
    return list_response(recs, ser_org)


@app.get("/care-network/organizations/<oid>")
def get_org(oid):
    require_roles("NetworkCoordinator", "FunderAdmin", "OrgAdmin",
                  "CaseWorker")
    return envelope_ok(ser_org(lookup("orgs", oid)), 200)


@app.post("/care-network/organizations/<oid>/activate")
def activate_org(oid):
    require_roles("NetworkCoordinator")
    org = lookup("orgs", oid)
    if org["status"] not in ("PENDING_REVIEW", "SUSPENDED"):
        err("ERR_INVALID_STATE", 409,
            "Organization not in PENDING_REVIEW or SUSPENDED")
    if org["status"] == "SUSPENDED":
        org["suspension_reason"] = None
    org["status"] = "ACTIVE"
    touch(org)
    return envelope_ok(ser_org(org), 200)


@app.post("/care-network/organizations/<oid>/suspend")
def suspend_org(oid):
    require_roles("NetworkCoordinator")
    org = lookup("orgs", oid)
    body = get_body({"suspension_reason", "expected_org_version"})
    reason = req_str(body, "suspension_reason")
    req_occ(body, "expected_org_version", org["version"])
    if org["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", 409, "Organization not ACTIVE")
    for c in STORE["claims"].values():
        if c["status"] in ("SUBMITTED", "UNDER_REVIEW") and (
                c["provider_org_id"] == oid or c["funder_org_id"] == oid):
            err("ERR_OPEN_CLAIMS_BLOCK_TRANSITION", 409,
                "Org suspension blocked by open claims")
    net = require_network()
    org["status"] = "SUSPENDED"
    org["suspension_reason"] = reason
    touch(org)
    for off in STORE["offerings"].values():
        if off["organization_id"] == oid and off["status"] == "ACTIVE":
            off["status"] = "PAUSED"
            touch(off)
    # Cascade A: force-decline ROUTED referrals aimed at this org
    for ref in list(STORE["referrals"].values()):
        if ref["status"] == "ROUTED" and ref["receiver_org_id"] == oid:
            off = STORE["offerings"].get(ref["service_offering_id"])
            if off is not None:
                off["capacity_consumed"] -= 1
                off["capacity_available"] = (off["capacity_total"]
                                             - off["capacity_consumed"])
                touch(off)
            ref["status"] = "DECLINED"
            ref["reassignment_count"] += 1
            touch(ref)
            if ref["reassignment_count"] > net["max_reassignment_count"]:
                ref["status"] = "CANCELLED"
                touch(ref)
                client = STORE["clients"].get(ref["client_id"])
                if client is not None:
                    client["open_referral_count"] -= 1
                    touch(client)
    return envelope_ok(ser_org(org), 200)


@app.post("/care-network/organizations/<oid>/terminate")
def terminate_org(oid):
    require_roles("NetworkCoordinator")
    org = lookup("orgs", oid)
    if org["status"] not in ("ACTIVE", "SUSPENDED"):
        err("ERR_INVALID_STATE", 409,
            "Organization not in ACTIVE or SUSPENDED")
    for ref in STORE["referrals"].values():
        if ref["status"] not in TERMINAL_REFERRAL_STATES and (
                ref["sender_org_id"] == oid or ref["receiver_org_id"] == oid):
            err("ERR_OPEN_REFERRALS_BLOCK_TERMINATION", 409,
                "Termination blocked by non-terminal referrals")
    if org["payable_balance_cents"] != 0:
        err("ERR_UNSETTLED_BALANCE", 409,
            "Termination blocked: payable balance nonzero")
    org["status"] = "TERMINATED"
    touch(org)
    # Cascade: terminate ACTIVE agreements naming this org (Cascade B each)
    for a in list(STORE["agreements"].values()):
        if a["status"] == "ACTIVE" and oid in (a["party_a_org_id"],
                                               a["party_b_org_id"]):
            terminate_agreement_internal(a)
    for off in STORE["offerings"].values():
        if off["organization_id"] == oid and off["status"] == "ACTIVE":
            off["status"] = "PAUSED"
            touch(off)
    return envelope_ok(ser_org(org), 200)


# ---------------------------------------------------------------------------
# Service offerings
# ---------------------------------------------------------------------------
@app.post("/care-network/organizations/<oid>/offerings")
def create_offering(oid):
    require_roles("OrgAdmin", "NetworkCoordinator")
    org = lookup("orgs", oid)
    body = get_body({"category_code", "description", "capacity_total",
                     "min_client_age", "max_client_age", "eligible_zip_codes",
                     "eligible_genders", "income_cap_annual_cents"})
    category_code = req_str(body, "category_code")
    description = req_str(body, "description")
    capacity_total = req_int(body, "capacity_total")
    min_age = opt_int(body, "min_client_age", 0)
    max_age = opt_int(body, "max_client_age", 150)
    zips = opt_str_list(body, "eligible_zip_codes", [])
    genders = opt_str_list(body, "eligible_genders", ["ANY"])
    income_cap = opt_int(body, "income_cap_annual_cents", None)
    if capacity_total < 1:
        err("ERR_INVALID_REQUEST", 400, "capacity_total must be >= 1")
    if not is_int(min_age) or not is_int(max_age) or min_age < 0:
        err("ERR_INVALID_REQUEST", 400, "Invalid age bounds")
    cat = None
    for t in STORE["taxonomy"].values():
        if t["code"] == category_code:
            cat = t
            break
    if cat is None:
        err("ERR_INVALID_REQUEST", 400, "Unknown category_code")
    if org["status"] != "ACTIVE":
        err("ERR_ORG_NOT_ACTIVE", 409, "Organization is not ACTIVE")
    if cat["status"] != "ACTIVE":
        err("ERR_CATEGORY_RETIRED", 422, "Category is RETIRED")
    rec = new_record()
    rec.update({
        "organization_id": oid, "category_code": category_code,
        "description": description, "min_client_age": min_age,
        "max_client_age": max_age, "eligible_zip_codes": zips,
        "eligible_genders": genders,
        "income_cap_annual_cents": income_cap,
        "capacity_total": capacity_total, "capacity_consumed": 0,
        "capacity_available": capacity_total, "status": "ACTIVE",
    })
    STORE["offerings"][rec["id"]] = rec
    return envelope_ok(ser_offering(rec), 201)


@app.get("/care-network/organizations/<oid>/offerings")
def list_org_offerings(oid):
    require_roles("NetworkCoordinator", "FunderAdmin", "OrgAdmin",
                  "CaseWorker")
    lookup("orgs", oid)
    status = request.args.get("status")
    recs = [o for o in STORE["offerings"].values()
            if o["organization_id"] == oid]
    if status is not None:
        recs = [o for o in recs if o["status"] == status]
    return list_response(recs, ser_offering)


@app.get("/care-network/offerings/<oid>")
def get_offering(oid):
    require_roles("NetworkCoordinator", "FunderAdmin", "OrgAdmin",
                  "CaseWorker")
    return envelope_ok(ser_offering(lookup("offerings", oid)), 200)


@app.post("/care-network/offerings/<oid>/pause")
def pause_offering(oid):
    require_roles("OrgAdmin", "NetworkCoordinator")
    off = lookup("offerings", oid)
    if off["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", 409, "Offering not ACTIVE")
    off["status"] = "PAUSED"
    touch(off)
    return envelope_ok(ser_offering(off), 200)


@app.post("/care-network/offerings/<oid>/resume")
def resume_offering(oid):
    require_roles("OrgAdmin", "NetworkCoordinator")
    off = lookup("offerings", oid)
    if off["status"] != "PAUSED":
        err("ERR_INVALID_STATE", 409, "Offering not PAUSED")
    org = STORE["orgs"].get(off["organization_id"])
    if org is None or org["status"] != "ACTIVE":
        err("ERR_ORG_NOT_ACTIVE", 409, "Owning organization is not ACTIVE")
    off["status"] = "ACTIVE"
    touch(off)
    return envelope_ok(ser_offering(off), 200)


# ---------------------------------------------------------------------------
# Clients
# ---------------------------------------------------------------------------
@app.post("/care-network/clients")
def create_client():
    require_roles("CaseWorker", "NetworkCoordinator")
    body = get_body({"full_name", "date_of_birth", "zip_code", "gender",
                     "annual_income_cents", "race", "ethnicity", "language",
                     "veteran_status"})
    full_name = req_str(body, "full_name")
    dob = req_str(body, "date_of_birth")
    if parse_date(dob) is None:
        err("ERR_INVALID_REQUEST", 400,
            "date_of_birth must be ISO YYYY-MM-DD")
    zip_code = req_str(body, "zip_code")
    gender = req_enum(body, "gender", GENDERS)
    income = opt_int(body, "annual_income_cents", None)
    race = opt_enum(body, "race", RACES, "UNDISCLOSED")
    ethnicity = opt_enum(body, "ethnicity", ETHNICITIES, "UNDISCLOSED")
    language = opt_str(body, "language", "en")
    veteran = body.get("veteran_status", False)
    if not isinstance(veteran, bool):
        err("ERR_INVALID_REQUEST", 400, "Invalid veteran_status")
    rec = new_record()
    rec.update({
        "full_name": full_name, "date_of_birth": dob, "zip_code": zip_code,
        "gender": gender, "annual_income_cents": income, "race": race,
        "ethnicity": ethnicity, "language": language,
        "veteran_status": veteran, "open_referral_count": 0,
    })
    STORE["clients"][rec["id"]] = rec
    return envelope_ok(ser_client(rec), 201)


@app.get("/care-network/clients/<cid>")
def get_client(cid):
    require_roles("NetworkCoordinator", "CaseWorker")
    return envelope_ok(ser_client(lookup("clients", cid)), 200)


# ---------------------------------------------------------------------------
# Agreements
# ---------------------------------------------------------------------------
@app.post("/care-network/agreements")
def create_agreement():
    require_roles("NetworkCoordinator")
    body = get_body({"party_a_org_id", "party_b_org_id", "effective_at"})
    pa = req_str(body, "party_a_org_id")
    pb = req_str(body, "party_b_org_id")
    eff_raw = req_str(body, "effective_at")
    if pa == pb:
        err("ERR_INVALID_REQUEST", 400, "party_a and party_b must differ")
    if pa not in STORE["orgs"] or pb not in STORE["orgs"]:
        err("ERR_INVALID_REQUEST", 400, "Party org does not exist")
    eff = parse_dt(eff_raw)
    if eff is None:
        err("ERR_INVALID_REQUEST", 400, "Invalid effective_at")
    rec = new_record()
    rec.update({"party_a_org_id": pa, "party_b_org_id": pb,
                "effective_at": fmt_ts(eff), "status": "PENDING"})
    STORE["agreements"][rec["id"]] = rec
    return envelope_ok(ser_agreement(rec), 201)


@app.get("/care-network/agreements")
def list_agreements():
    require_roles("NetworkCoordinator", "FunderAdmin", "OrgAdmin",
                  "CaseWorker")
    pa = request.args.get("party_a_org_id")
    pb = request.args.get("party_b_org_id")
    status = request.args.get("status")
    recs = list(STORE["agreements"].values())
    if pa is not None:
        recs = [a for a in recs if a["party_a_org_id"] == pa]
    if pb is not None:
        recs = [a for a in recs if a["party_b_org_id"] == pb]
    if status is not None:
        recs = [a for a in recs if a["status"] == status]
    return list_response(recs, ser_agreement)


@app.get("/care-network/organizations/<oid>/agreements")
def list_org_agreements(oid):
    require_roles("NetworkCoordinator", "FunderAdmin", "OrgAdmin",
                  "CaseWorker")
    lookup("orgs", oid)
    recs = [a for a in STORE["agreements"].values()
            if oid in (a["party_a_org_id"], a["party_b_org_id"])]
    return list_response(recs, ser_agreement)


@app.post("/care-network/agreements/<aid>/approve")
def approve_agreement(aid):
    require_roles("NetworkCoordinator")
    a = lookup("agreements", aid)
    if a["status"] != "PENDING":
        err("ERR_INVALID_STATE", 409, "Agreement not PENDING")
    eff = parse_dt(a["effective_at"])
    if eff is not None and eff > clock_now():
        err("ERR_AGREEMENT_NOT_YET_EFFECTIVE", 409,
            "Agreement effective_at is after the server clock")
    for pid in (a["party_a_org_id"], a["party_b_org_id"]):
        org = STORE["orgs"].get(pid)
        if org is None or org["status"] != "ACTIVE":
            err("ERR_ORG_NOT_ACTIVE", 409, "Party organization not ACTIVE")
    a["status"] = "ACTIVE"
    touch(a)
    return envelope_ok(ser_agreement(a), 200)


@app.post("/care-network/agreements/<aid>/expire")
def expire_agreement(aid):
    require_roles("NetworkCoordinator")
    a = lookup("agreements", aid)
    if a["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", 409, "Agreement not ACTIVE")
    a["status"] = "EXPIRED"
    touch(a)
    return envelope_ok(ser_agreement(a), 200)


def terminate_agreement_internal(a):
    a["status"] = "TERMINATED"
    touch(a)
    pa, pb = a["party_a_org_id"], a["party_b_org_id"]
    for c in list(STORE["consents"].values()):
        if c["status"] != "ACTIVE":
            continue
        if ((c["sender_org_id"] == pa and c["receiver_org_id"] == pb)
                or (c["sender_org_id"] == pb and c["receiver_org_id"] == pa)):
            revoke_consent(c)


@app.post("/care-network/agreements/<aid>/terminate")
def terminate_agreement(aid):
    require_roles("NetworkCoordinator")
    a = lookup("agreements", aid)
    if a["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", 409, "Agreement not ACTIVE")
    terminate_agreement_internal(a)
    return envelope_ok(ser_agreement(a), 200)


# ---------------------------------------------------------------------------
# Consents
# ---------------------------------------------------------------------------
@app.post("/care-network/clients/<cid>/consents")
def create_consent(cid):
    require_roles("CaseWorker", "NetworkCoordinator")
    lookup("clients", cid)
    body = get_body({"sender_org_id", "receiver_org_id", "scope"})
    sender = req_str(body, "sender_org_id")
    receiver = req_str(body, "receiver_org_id")
    scope = req_enum(body, "scope", {"FULL", "MINIMUM_NECESSARY"})
    if sender not in STORE["orgs"] or receiver not in STORE["orgs"]:
        err("ERR_INVALID_REQUEST", 400, "Consent org does not exist")
    rec = new_record()
    rec.update({
        "client_id": cid, "sender_org_id": sender,
        "receiver_org_id": receiver, "scope": scope, "status": "ACTIVE",
        "revoked_at": None,
    })
    STORE["consents"][rec["id"]] = rec
    return envelope_ok(ser_consent(rec), 201)


@app.get("/care-network/consents")
def list_consents():
    require_roles("NetworkCoordinator", "CaseWorker", "OrgAdmin")
    sender = request.args.get("sender_org_id")
    receiver = request.args.get("receiver_org_id")
    status = request.args.get("status")
    recs = list(STORE["consents"].values())
    if sender is not None:
        recs = [c for c in recs if c["sender_org_id"] == sender]
    if receiver is not None:
        recs = [c for c in recs if c["receiver_org_id"] == receiver]
    if status is not None:
        recs = [c for c in recs if c["status"] == status]
    return list_response(recs, ser_consent)


@app.get("/care-network/clients/<cid>/consents")
def list_client_consents(cid):
    require_roles("NetworkCoordinator", "CaseWorker")
    lookup("clients", cid)
    status = request.args.get("status")
    recs = [c for c in STORE["consents"].values() if c["client_id"] == cid]
    if status is not None:
        recs = [c for c in recs if c["status"] == status]
    return list_response(recs, ser_consent)


@app.get("/care-network/consents/<cid>")
def get_consent(cid):
    require_roles("NetworkCoordinator", "CaseWorker", "OrgAdmin")
    return envelope_ok(ser_consent(lookup("consents", cid)), 200)


@app.post("/care-network/consents/<cid>/revoke")
def revoke_consent_ep(cid):
    require_roles("CaseWorker", "NetworkCoordinator")
    consent = lookup("consents", cid)
    if consent["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", 409, "Consent not ACTIVE")
    revoke_consent(consent)
    return envelope_ok(ser_consent(consent), 200)


# ---------------------------------------------------------------------------
# Referrals
# ---------------------------------------------------------------------------
@app.post("/care-network/referrals")
def create_referral():
    require_roles("CaseWorker")
    body = get_body({"client_id", "sender_org_id", "receiver_org_id",
                     "service_offering_id", "consent_id", "category_code",
                     "urgency"})
    client_id = req_str(body, "client_id")
    sender = req_str(body, "sender_org_id")
    receiver = req_str(body, "receiver_org_id")
    offering_id = req_str(body, "service_offering_id")
    consent_id = req_str(body, "consent_id")
    category_code = req_str(body, "category_code")
    urgency = opt_enum(body, "urgency", {"STANDARD", "URGENT"}, "STANDARD")
    for label, kind in (("client_id", "clients"),
                        ("sender_org_id", "orgs"),
                        ("receiver_org_id", "orgs"),
                        ("service_offering_id", "offerings"),
                        ("consent_id", "consents")):
        val = {"client_id": client_id, "sender_org_id": sender,
               "receiver_org_id": receiver, "service_offering_id": offering_id,
               "consent_id": consent_id}[label]
        if val not in STORE[kind]:
            err("ERR_INVALID_REQUEST", 400,
                "FK target does not exist: %s" % label)
    cat = None
    for t in STORE["taxonomy"].values():
        if t["code"] == category_code:
            cat = t
            break
    if cat is None:
        err("ERR_INVALID_REQUEST", 400, "Unknown category_code")
    # Eager consent validation: the named consent must be ACTIVE. The
    # sender-receiver pair match is enforced by the routing gate (§3.5).
    consent = STORE["consents"][consent_id]
    if consent["status"] != "ACTIVE":
        err("ERR_CONSENT_REQUIRED", 422,
            "No ACTIVE consent matches the referral pair")
    if cat["status"] != "ACTIVE":
        err("ERR_CATEGORY_RETIRED", 422, "Category is RETIRED")
    rec = new_record()
    rec.update({
        "client_id": client_id, "sender_org_id": sender,
        "receiver_org_id": receiver, "service_offering_id": offering_id,
        "consent_id": consent_id, "category_code": category_code,
        "urgency": urgency, "status": "DRAFT", "service_started_at": None,
        "reassignment_count": 0, "reopen_count": 0, "outcome_code": None,
        "delivered_units": 0,
    })
    STORE["referrals"][rec["id"]] = rec
    return envelope_ok(ser_referral(rec), 201)


@app.get("/care-network/referrals")
def list_referrals():
    require_roles("NetworkCoordinator", "CaseWorker", "OrgAdmin",
                  "FunderAdmin")
    recs = list(STORE["referrals"].values())
    for field in ("client_id", "sender_org_id", "receiver_org_id",
                  "service_offering_id", "consent_id", "status"):
        v = request.args.get(field)
        if v is not None:
            recs = [r for r in recs if r[field] == v]
    aging_only = request.args.get("aging_only")
    if aging_only is not None and aging_only.lower() in ("true", "1", "yes"):
        net = get_network()
        threshold = net["unresolved_aging_days"] if net else 30
        recs = [r for r in recs
                if r["status"] not in TERMINAL_REFERRAL_STATES
                and referral_aging_days(r) > threshold]
    return list_response(recs, ser_referral)


@app.get("/care-network/offerings/<oid>/referrals")
def list_offering_referrals(oid):
    require_roles("NetworkCoordinator", "CaseWorker", "OrgAdmin")
    lookup("offerings", oid)
    recs = [r for r in STORE["referrals"].values()
            if r["service_offering_id"] == oid
            and r["status"] in ("ROUTED", "ACCEPTED", "IN_SERVICE")]
    return list_response(recs, ser_referral)


@app.get("/care-network/clients/<cid>/referrals")
def list_client_referrals(cid):
    require_roles("NetworkCoordinator", "CaseWorker")
    lookup("clients", cid)
    recs = [r for r in STORE["referrals"].values() if r["client_id"] == cid]
    return list_response(recs, ser_referral)


@app.get("/care-network/referrals/<rid>")
def get_referral(rid):
    require_roles("NetworkCoordinator", "CaseWorker", "OrgAdmin",
                  "FunderAdmin")
    return envelope_ok(ser_referral(lookup("referrals", rid)), 200)


def routing_gate(ref, receiver_id, offering_id, consent_id=None):
    """Full routing preconditions for route and reassign (business-rule
    section, in validation priority order)."""
    net = require_network()
    sender = STORE["orgs"].get(ref["sender_org_id"])
    receiver = STORE["orgs"].get(receiver_id)
    offering = STORE["offerings"].get(offering_id)
    if receiver is None:
        err("ERR_INVALID_REQUEST", 400, "Receiver org does not exist")
    if offering is None:
        err("ERR_INVALID_REQUEST", 400, "Offering does not exist")
    # An ACTIVE consent of the referral's client must match the
    # sender-receiver pair (existential over the client's consents).
    matched = None
    if consent_id is not None:
        cand = STORE["consents"].get(consent_id)
        if (cand is not None and cand["status"] == "ACTIVE"
                and cand["client_id"] == ref["client_id"]
                and consent_covers(cand, ref["sender_org_id"], receiver_id)):
            matched = cand
    else:
        for cand in STORE["consents"].values():
            if (cand["client_id"] == ref["client_id"]
                    and cand["status"] == "ACTIVE"
                    and consent_covers(cand, ref["sender_org_id"],
                                       receiver_id)):
                matched = cand
                break
    if matched is None:
        err("ERR_CONSENT_REQUIRED", 422,
            "No ACTIVE consent matches the referral pair")
    if not has_active_agreement(ref["sender_org_id"], receiver_id):
        err("ERR_AGREEMENT_INACTIVE", 422,
            "No ACTIVE agreement covers the org pair")
    cat = None
    for t in STORE["taxonomy"].values():
        if t["code"] == ref["category_code"]:
            cat = t
            break
    if (offering["organization_id"] != receiver_id
            or offering["category_code"] != ref["category_code"]
            or offering["status"] != "ACTIVE"):
        err("ERR_OFFERING_MISMATCH", 422, "Offering mismatch")
    if cat is None or cat["status"] != "ACTIVE":
        err("ERR_CATEGORY_RETIRED", 422, "Category is RETIRED")
    client = STORE["clients"].get(ref["client_id"])
    if client is None:
        err("ERR_INVALID_REQUEST", 400, "Client does not exist")
    created = parse_dt(ref["created_at"]) or clock_now()
    age = client_age_years(client, created)
    eligible = (offering["min_client_age"] <= age <= offering["max_client_age"]
                and (not offering["eligible_zip_codes"]
                     or client["zip_code"] in offering["eligible_zip_codes"])
                and ("ANY" in offering["eligible_genders"]
                     or client["gender"] in offering["eligible_genders"])
                and (offering["income_cap_annual_cents"] is None
                     or (client["annual_income_cents"] is not None
                         and client["annual_income_cents"]
                         < offering["income_cap_annual_cents"])))
    if not eligible:
        err("ERR_ELIGIBILITY_FAILED", 422, "Client fails eligibility")
    if offering["capacity_available"] < 1:
        err("ERR_CAPACITY_EXHAUSTED", 409, "Offering capacity exhausted")
    if receiver["org_type"] != "CBO":
        err("ERR_RECEIVER_NOT_CBO", 422, "Receiver org_type is not CBO")
    if (sender is None or sender["status"] != "ACTIVE"
            or receiver["status"] != "ACTIVE"):
        err("ERR_ORG_NOT_ACTIVE", 409, "Sender or receiver org not ACTIVE")
    return offering


@app.post("/care-network/referrals/<rid>/route")
def route_referral(rid):
    require_roles("CaseWorker")
    ref = lookup("referrals", rid)
    if ref["status"] != "DRAFT":
        err("ERR_INVALID_STATE", 409, "Referral not in DRAFT")
    offering = routing_gate(ref, ref["receiver_org_id"],
                            ref["service_offering_id"])
    ref["status"] = "ROUTED"
    touch(ref)
    offering["capacity_consumed"] += 1
    offering["capacity_available"] = (offering["capacity_total"]
                                      - offering["capacity_consumed"])
    touch(offering)
    client = STORE["clients"].get(ref["client_id"])
    if client is not None:
        client["open_referral_count"] += 1
        touch(client)
    return envelope_ok(ser_referral(ref), 200)


@app.post("/care-network/referrals/<rid>/accept")
def accept_referral(rid):
    require_roles("OrgAdmin")
    ref = lookup("referrals", rid)
    require_caller_org(ref["receiver_org_id"])
    if ref["status"] != "ROUTED":
        err("ERR_INVALID_STATE", 409, "Referral not ROUTED")
    offering = STORE["offerings"].get(ref["service_offering_id"])
    if offering is None or offering["capacity_available"] < 1:
        err("ERR_CAPACITY_EXHAUSTED", 409, "Offering capacity exhausted")
    ref["status"] = "ACCEPTED"
    touch(ref)
    return envelope_ok(ser_referral(ref), 200)


@app.post("/care-network/referrals/<rid>/decline")
def decline_referral(rid):
    require_roles("OrgAdmin")
    ref = lookup("referrals", rid)
    require_caller_org(ref["receiver_org_id"])
    get_body({"reason"})
    if ref["status"] != "ROUTED":
        err("ERR_INVALID_STATE", 409, "Referral not ROUTED")
    net = require_network()
    offering = STORE["offerings"].get(ref["service_offering_id"])
    if offering is not None:
        offering["capacity_consumed"] -= 1
        offering["capacity_available"] = (offering["capacity_total"]
                                          - offering["capacity_consumed"])
        touch(offering)
    ref["status"] = "DECLINED"
    ref["reassignment_count"] += 1
    touch(ref)
    if ref["reassignment_count"] > net["max_reassignment_count"]:
        ref["status"] = "CANCELLED"
        touch(ref)
        client = STORE["clients"].get(ref["client_id"])
        if client is not None:
            client["open_referral_count"] -= 1
            touch(client)
    return envelope_ok(ser_referral(ref), 200)


@app.post("/care-network/referrals/<rid>/reassign")
def reassign_referral(rid):
    require_roles("CaseWorker", "NetworkCoordinator")
    ref = lookup("referrals", rid)
    body = get_body({"new_receiver_org_id", "new_service_offering_id",
                     "expected_referral_version", "new_consent_id"})
    new_receiver = req_str(body, "new_receiver_org_id")
    new_offering_id = req_str(body, "new_service_offering_id")
    new_consent_id = body.get("new_consent_id")
    if new_consent_id is not None and not isinstance(new_consent_id, str):
        err("ERR_INVALID_REQUEST", 400, "Invalid new_consent_id")
    if new_receiver not in STORE["orgs"]:
        err("ERR_INVALID_REQUEST", 400, "Receiver org does not exist")
    if new_offering_id not in STORE["offerings"]:
        err("ERR_INVALID_REQUEST", 400, "Offering does not exist")
    if (new_consent_id is not None
            and new_consent_id not in STORE["consents"]):
        err("ERR_INVALID_REQUEST", 400, "new_consent_id does not exist")
    req_occ(body, "expected_referral_version", ref["version"])
    if ref["status"] not in ("DECLINED", "ESCALATED"):
        err("ERR_INVALID_STATE", 409,
            "Referral not in DECLINED or ESCALATED")
    from_escalated = ref["status"] == "ESCALATED"
    if new_receiver == ref["receiver_org_id"]:
        err("ERR_REASSIGNMENT_LOOP", 409,
            "Reassignment targets the current receiver")
    new_offering = routing_gate(ref, new_receiver, new_offering_id,
                                consent_id=new_consent_id)
    if from_escalated:
        old_offering = STORE["offerings"].get(ref["service_offering_id"])
        if old_offering is not None:
            old_offering["capacity_consumed"] -= 1
            old_offering["capacity_available"] = (
                old_offering["capacity_total"]
                - old_offering["capacity_consumed"])
            touch(old_offering)
    ref["receiver_org_id"] = new_receiver
    ref["service_offering_id"] = new_offering_id
    if new_consent_id is not None:
        ref["consent_id"] = new_consent_id
    ref["status"] = "ROUTED"
    if from_escalated:
        ref["reopen_count"] += 1
        ref["reassignment_count"] += 1
    touch(ref)
    new_offering["capacity_consumed"] += 1
    new_offering["capacity_available"] = (new_offering["capacity_total"]
                                          - new_offering["capacity_consumed"])
    touch(new_offering)
    return envelope_ok(ser_referral(ref), 200)


@app.post("/care-network/referrals/<rid>/escalate")
def escalate_referral(rid):
    require_roles("NetworkCoordinator")
    ref = lookup("referrals", rid)
    if ref["status"] != "ROUTED":
        err("ERR_INVALID_STATE", 409, "Referral not ROUTED")
    net = require_network()
    window = net["auto_accept_window_hours"]
    if ref["urgency"] == "URGENT":
        window = window // 2
    routed_at = parse_dt(ref["updated_at"]) or clock_now()
    elapsed_hours = int((clock_now() - routed_at).total_seconds() // 3600)
    if not elapsed_hours > window:
        err("ERR_NOT_AGING", 409, "Referral has not exceeded the window")
    ref["status"] = "ESCALATED"
    touch(ref)
    return envelope_ok(ser_referral(ref), 200)


@app.post("/care-network/referrals/<rid>/start-service")
def start_service(rid):
    require_roles("OrgAdmin")
    ref = lookup("referrals", rid)
    require_caller_org(ref["receiver_org_id"])
    if ref["status"] != "ACCEPTED":
        err("ERR_INVALID_STATE", 409, "Referral not ACCEPTED")
    ref["status"] = "IN_SERVICE"
    ref["service_started_at"] = fmt_ts(clock_now())
    touch(ref)
    return envelope_ok(ser_referral(ref), 200)


@app.post("/care-network/referrals/<rid>/confirm-outcome")
def confirm_outcome(rid):
    require_roles("OrgAdmin")
    ref = lookup("referrals", rid)
    require_caller_org(ref["receiver_org_id"])
    body = get_body({"outcome_code", "delivered_units"})
    outcome_code = req_enum(body, "outcome_code", OUTCOME_CODES)
    units = req_int(body, "delivered_units")
    if ref["status"] != "IN_SERVICE":
        err("ERR_INVALID_STATE", 409, "Referral not IN_SERVICE")
    if outcome_code in ("DELIVERED", "PARTIALLY_DELIVERED"):
        if units < 1:
            err("ERR_OUTCOME_UNITS_MISMATCH", 422,
                "delivered_units must be >= 1 for this outcome")
    else:
        if units != 0:
            err("ERR_OUTCOME_UNITS_MISMATCH", 422,
                "delivered_units must be 0 for this outcome")
    ref["status"] = "OUTCOME_RECORDED"
    ref["outcome_code"] = outcome_code
    ref["delivered_units"] = units
    touch(ref)
    billable = (outcome_code in ("DELIVERED", "PARTIALLY_DELIVERED")
                and units >= 1)
    ts = fmt_ts(clock_now())
    rec = {"id": str(uuid.uuid4()), "created_at": ts, "referral_id": rid,
           "outcome_code": outcome_code, "delivered_units": units,
           "reported_by_org_id": ref["receiver_org_id"], "reported_at": ts,
           "billable": billable}
    STORE["outcomes"][rid] = rec
    offering = STORE["offerings"].get(ref["service_offering_id"])
    if offering is not None:
        offering["capacity_consumed"] -= 1
        offering["capacity_available"] = (offering["capacity_total"]
                                          - offering["capacity_consumed"])
        touch(offering)
    client = STORE["clients"].get(ref["client_id"])
    if client is not None:
        client["open_referral_count"] -= 1
        touch(client)
    return envelope_ok(ser_referral(ref), 200)


@app.post("/care-network/referrals/<rid>/cancel")
def cancel_referral(rid):
    require_roles("CaseWorker", "NetworkCoordinator")
    ref = lookup("referrals", rid)
    get_body({"reason"})
    if ref["status"] not in ("DRAFT", "ROUTED", "ACCEPTED", "DECLINED",
                             "ESCALATED"):
        err("ERR_INVALID_STATE", 409, "Referral not in a cancellable state")
    if ref["status"] in ("ROUTED", "ACCEPTED", "ESCALATED"):
        offering = STORE["offerings"].get(ref["service_offering_id"])
        if offering is not None:
            offering["capacity_consumed"] -= 1
            offering["capacity_available"] = (offering["capacity_total"]
                                              - offering["capacity_consumed"])
            touch(offering)
    ref["status"] = "CANCELLED"
    touch(ref)
    client = STORE["clients"].get(ref["client_id"])
    if client is not None:
        client["open_referral_count"] -= 1
        touch(client)
    return envelope_ok(ser_referral(ref), 200)


# ---------------------------------------------------------------------------
# Referral notes
# ---------------------------------------------------------------------------
@app.post("/care-network/referrals/<rid>/notes")
def create_note(rid):
    uid, role = require_roles("CaseWorker", "OrgAdmin", "NetworkCoordinator")
    lookup("referrals", rid)
    body = get_body({"body", "visibility"})
    text = req_str(body, "body")
    visibility = opt_enum(body, "visibility",
                          {"NETWORK", "SENDER_ONLY", "RECEIVER_ONLY"},
                          "NETWORK")
    author = uid if role == "NetworkCoordinator" else caller_org_prefix()
    rec = new_record(common=False)
    rec.update({"referral_id": rid, "author_org_id": author, "body": text,
                "visibility": visibility})
    STORE["notes"][rec["id"]] = rec
    return envelope_ok(ser_note(rec), 201)


@app.get("/care-network/referrals/<rid>/notes")
def list_notes(rid):
    require_roles("NetworkCoordinator", "CaseWorker", "OrgAdmin")
    lookup("referrals", rid)
    recs = [n for n in STORE["notes"].values() if n["referral_id"] == rid]
    return list_response(recs, ser_note)


@app.get("/care-network/organizations/<oid>/notes")
def list_org_notes(oid):
    require_roles("NetworkCoordinator", "CaseWorker", "OrgAdmin")
    lookup("orgs", oid)
    recs = [n for n in STORE["notes"].values() if n["author_org_id"] == oid]
    return list_response(recs, ser_note)


# ---------------------------------------------------------------------------
# Outcome records
# ---------------------------------------------------------------------------
@app.get("/care-network/referrals/<rid>/outcome")
def get_outcome(rid):
    require_roles("NetworkCoordinator", "CaseWorker", "OrgAdmin",
                  "FunderAdmin")
    lookup("referrals", rid)
    rec = STORE["outcomes"].get(rid)
    recs = [rec] if rec is not None else []
    return list_response(recs, ser_outcome)


@app.get("/care-network/organizations/<oid>/outcomes")
def list_org_outcomes(oid):
    require_roles("NetworkCoordinator", "FunderAdmin", "OrgAdmin")
    lookup("orgs", oid)
    recs = [o for o in STORE["outcomes"].values()
            if o["reported_by_org_id"] == oid]
    return list_response(recs, ser_outcome)


# ---------------------------------------------------------------------------
# Rate cards
# ---------------------------------------------------------------------------
@app.post("/care-network/organizations/<oid>/rate-cards")
def create_rate_card(oid):
    require_roles("FunderAdmin", "NetworkCoordinator")
    org = lookup("orgs", oid)
    body = get_body({"category_code", "rate_cents_per_unit", "min_units",
                     "tier2_rate_cents_per_unit", "monthly_cap_cents"})
    category_code = req_str(body, "category_code")
    rate = req_int(body, "rate_cents_per_unit")
    min_units = opt_int(body, "min_units", 1)
    tier2 = opt_int(body, "tier2_rate_cents_per_unit", None)
    cap = opt_int(body, "monthly_cap_cents", None)
    if rate < 1:
        err("ERR_INVALID_REQUEST", 400,
            "rate_cents_per_unit must be >= 1")
    if not is_int(min_units) or min_units < 1:
        err("ERR_INVALID_REQUEST", 400, "min_units must be >= 1")
    cat = None
    for t in STORE["taxonomy"].values():
        if t["code"] == category_code:
            cat = t
            break
    if cat is None:
        err("ERR_INVALID_REQUEST", 400, "Unknown category_code")
    if org["org_type"] != "FUNDER" or org["status"] != "ACTIVE":
        err("ERR_ORG_NOT_ACTIVE", 409,
            "Organization must be an ACTIVE FUNDER")
    rec = new_record()
    rec.update({
        "funder_org_id": oid, "category_code": category_code,
        "rate_cents_per_unit": rate, "min_units": min_units,
        "tier2_rate_cents_per_unit": tier2, "monthly_cap_cents": cap,
        "status": "ACTIVE",
    })
    STORE["rate_cards"][rec["id"]] = rec
    return envelope_ok(ser_rate_card(rec), 201)


@app.get("/care-network/organizations/<oid>/rate-cards")
def list_rate_cards(oid):
    require_roles("NetworkCoordinator", "FunderAdmin", "OrgAdmin")
    lookup("orgs", oid)
    status = request.args.get("status")
    recs = [rc for rc in STORE["rate_cards"].values()
            if rc["funder_org_id"] == oid]
    if status is not None:
        recs = [rc for rc in recs if rc["status"] == status]
    return list_response(recs, ser_rate_card)


@app.get("/care-network/rate-cards/<rid>")
def get_rate_card(rid):
    require_roles("NetworkCoordinator", "FunderAdmin", "OrgAdmin")
    return envelope_ok(ser_rate_card(lookup("rate_cards", rid)), 200)


def find_rate_card(funder_id, category_code):
    for rc in STORE["rate_cards"].values():
        if (rc["funder_org_id"] == funder_id
                and rc["category_code"] == category_code
                and rc["status"] == "ACTIVE"):
            return rc
    return None


def unit_rate(rate_card, units):
    if rate_card["tier2_rate_cents_per_unit"] is None:
        return rate_card["rate_cents_per_unit"]
    if units < rate_card["min_units"]:
        return rate_card["rate_cents_per_unit"]
    return rate_card["tier2_rate_cents_per_unit"]


# ---------------------------------------------------------------------------
# Claims
# ---------------------------------------------------------------------------
@app.post("/care-network/claims")
def create_claim():
    require_roles("OrgAdmin")
    body = get_body({"referral_id", "funder_org_id", "claimed_units"})
    referral_id = req_str(body, "referral_id")
    funder_id = req_str(body, "funder_org_id")
    units = req_int(body, "claimed_units")
    if referral_id not in STORE["referrals"]:
        err("ERR_INVALID_REQUEST", 400, "referral_id does not exist")
    if funder_id not in STORE["orgs"]:
        err("ERR_INVALID_REQUEST", 400, "funder_org_id does not exist")
    ref = STORE["referrals"][referral_id]
    provider_id = ref["receiver_org_id"]
    consent = STORE["consents"].get(ref["consent_id"])
    if consent is not None and consent["status"] == "REVOKED":
        err("ERR_CONSENT_REVOKED", 422,
            "Referral consent has been revoked")
    if not has_active_agreement(funder_id, provider_id):
        err("ERR_AGREEMENT_INACTIVE", 422,
            "No ACTIVE agreement between funder and provider")
    outcome = STORE["outcomes"].get(referral_id)
    if outcome is not None and units != outcome["delivered_units"]:
        err("ERR_OUTCOME_UNITS_MISMATCH", 422,
            "claimed_units must equal outcome delivered_units")
    for c in STORE["claims"].values():
        if c["referral_id"] == referral_id:
            err("ERR_DUPLICATE_CLAIM", 409,
                "A claim already exists for this referral")
    if ref["status"] != "OUTCOME_RECORDED" or outcome is None \
            or not outcome["billable"]:
        err("ERR_REFERRAL_NOT_BILLABLE", 422,
            "Referral not OUTCOME_RECORDED with a billable outcome")
    rate_card = find_rate_card(funder_id, ref["category_code"])
    if rate_card is None:
        err("ERR_INVALID_REQUEST", 400,
            "No ACTIVE rate card for this funder and category")
    rate = unit_rate(rate_card, units)
    provisional = units * rate
    rec = new_record()
    rec.update({
        "referral_id": referral_id, "funder_org_id": funder_id,
        "provider_org_id": provider_id, "claimed_units": units,
        "reviewed_by_user_id": None,
        "provisional_amount_cents": provisional,
        "approved_amount_cents": None, "clawback_reserve_cents": 0,
        "status": "SUBMITTED", "approved_at": None,
    })
    STORE["claims"][rec["id"]] = rec
    return envelope_ok(ser_claim(rec), 201)


@app.get("/care-network/claims")
def list_claims():
    require_roles("NetworkCoordinator", "FunderAdmin", "OrgAdmin")
    recs = list(STORE["claims"].values())
    for field in ("referral_id", "funder_org_id", "provider_org_id",
                  "status"):
        v = request.args.get(field)
        if v is not None:
            recs = [c for c in recs if c[field] == v]
    return list_response(recs, ser_claim)


@app.get("/care-network/claims/<cid>")
def get_claim(cid):
    require_roles("NetworkCoordinator", "FunderAdmin", "OrgAdmin")
    return envelope_ok(ser_claim(lookup("claims", cid)), 200)


@app.post("/care-network/claims/<cid>/review")
def review_claim(cid):
    uid, _ = require_roles("FunderAdmin")
    claim = lookup("claims", cid)
    require_caller_org(claim["funder_org_id"])
    if claim["status"] != "SUBMITTED":
        err("ERR_INVALID_STATE", 409, "Claim not SUBMITTED")
    claim["status"] = "UNDER_REVIEW"
    claim["reviewed_by_user_id"] = uid
    touch(claim)
    return envelope_ok(ser_claim(claim), 200)


@app.post("/care-network/claims/<cid>/approve")
def approve_claim(cid):
    uid, _ = require_roles("FunderAdmin")
    claim = lookup("claims", cid)
    require_caller_org(claim["funder_org_id"])
    body = get_body({"expected_claim_version"})
    req_occ(body, "expected_claim_version", claim["version"])
    if claim["status"] != "UNDER_REVIEW":
        err("ERR_INVALID_STATE", 409, "Claim not UNDER_REVIEW")
    ref = STORE["referrals"].get(claim["referral_id"])
    consent = STORE["consents"].get(ref["consent_id"]) if ref else None
    if consent is None or consent["status"] != "ACTIVE":
        err("ERR_CONSENT_REVOKED", 422, "Referral consent is not ACTIVE")
    if uid == claim["reviewed_by_user_id"]:
        err("ERR_SEGREGATION_OF_DUTIES", 403,
            "Approver must differ from reviewer")
    rate_card = find_rate_card(claim["funder_org_id"], ref["category_code"])
    if rate_card is None:
        err("ERR_INVALID_REQUEST", 400,
            "No ACTIVE rate card for this funder and category")
    rate = unit_rate(rate_card, claim["claimed_units"])
    gross = claim["claimed_units"] * rate
    now = clock_now()
    paid_this_month = 0
    for c in STORE["claims"].values():
        if c["id"] == claim["id"]:
            continue
        if c["funder_org_id"] != claim["funder_org_id"]:
            continue
        if c.get("approved_amount_cents") is None:
            continue
        approved_at = parse_dt(c.get("approved_at")) if c.get(
            "approved_at") else None
        if approved_at is None:
            continue
        if approved_at.year == now.year and approved_at.month == now.month:
            if c["status"] == "APPROVED":
                paid_this_month += c["approved_amount_cents"]
            elif c["status"] == "VOIDED":
                paid_this_month += (c["approved_amount_cents"]
                                    - c.get("clawback_reserve_cents", 0))
    cap = rate_card["monthly_cap_cents"]
    if cap is None:
        approved = gross
    else:
        approved = max(0, min(gross, cap - paid_this_month))
    claim["approved_amount_cents"] = approved
    claim["approved_at"] = fmt_ts(now)
    claim["status"] = "APPROVED"
    touch(claim)
    provider = STORE["orgs"].get(claim["provider_org_id"])
    if provider is not None:
        provider["payable_balance_cents"] += approved
        touch(provider)
    return envelope_ok(ser_claim(claim), 200)


@app.post("/care-network/claims/<cid>/deny")
def deny_claim(cid):
    uid, _ = require_roles("FunderAdmin")
    claim = lookup("claims", cid)
    require_caller_org(claim["funder_org_id"])
    get_body({"reason"})
    if claim["status"] != "UNDER_REVIEW":
        err("ERR_INVALID_STATE", 409, "Claim not UNDER_REVIEW")
    if uid == claim["reviewed_by_user_id"]:
        err("ERR_SEGREGATION_OF_DUTIES", 403,
            "Denier must differ from reviewer")
    claim["status"] = "DENIED"
    touch(claim)
    return envelope_ok(ser_claim(claim), 200)


@app.post("/care-network/claims/<cid>/void")
def void_claim_ep(cid):
    require_roles("FunderAdmin", "NetworkCoordinator")
    claim = lookup("claims", cid)
    get_body({"reason"})
    if claim["status"] == "PAID":
        err("ERR_CLAIM_ALREADY_PAID", 409, "Claim already paid")
    if claim["status"] not in ("SUBMITTED", "UNDER_REVIEW", "APPROVED"):
        err("ERR_INVALID_STATE", 409,
            "Claim not in SUBMITTED, UNDER_REVIEW, or APPROVED")
    net = require_network()
    provider = STORE["orgs"].get(claim["provider_org_id"])
    if claim["status"] == "APPROVED":
        balance = provider["payable_balance_cents"] if provider else 0
        shortfall = max(0, claim["approved_amount_cents"] - balance)
    else:
        shortfall = claim["provisional_amount_cents"]
    if shortfall > net["network_escrow_cents"]:
        err("ERR_ESCROW_EXHAUSTED", 402,
            "Network escrow cannot fund the clawback reserve")
    void_claim(claim, claim["status"] == "APPROVED", net)
    return envelope_ok(ser_claim(claim), 200)


# ---------------------------------------------------------------------------
# Disbursements
# ---------------------------------------------------------------------------
@app.post("/care-network/disbursements")
def create_disbursement():
    require_roles("FunderAdmin")
    body = get_body({"provider_org_id", "funder_org_id", "claim_ids"})
    provider_id = req_str(body, "provider_org_id")
    funder_id = req_str(body, "funder_org_id")
    claim_ids = body.get("claim_ids")
    if not isinstance(claim_ids, list) or not all(
            isinstance(x, str) for x in claim_ids):
        err("ERR_INVALID_REQUEST", 400,
            "claim_ids must be an array of strings")
    if provider_id not in STORE["orgs"]:
        err("ERR_INVALID_REQUEST", 400, "provider_org_id does not exist")
    if funder_id not in STORE["orgs"]:
        err("ERR_INVALID_REQUEST", 400, "funder_org_id does not exist")
    for cl_id in claim_ids:
        if cl_id not in STORE["claims"]:
            err("ERR_INVALID_REQUEST", 400,
                "claim id does not exist: %s" % cl_id)
    rec = new_record()
    rec.update({
        "provider_org_id": provider_id, "funder_org_id": funder_id,
        "claim_ids": list(claim_ids), "total_amount_cents": 0,
        "status": "SCHEDULED", "failure_reason": None,
    })
    STORE["disbursements"][rec["id"]] = rec
    return envelope_ok(ser_disbursement(rec), 201)


@app.get("/care-network/disbursements")
def list_disbursements():
    require_roles("NetworkCoordinator", "FunderAdmin", "OrgAdmin")
    recs = list(STORE["disbursements"].values())
    for field in ("provider_org_id", "funder_org_id", "status"):
        v = request.args.get(field)
        if v is not None:
            recs = [d for d in recs if d[field] == v]
    return list_response(recs, ser_disbursement)


@app.get("/care-network/disbursements/<did>")
def get_disbursement(did):
    require_roles("NetworkCoordinator", "FunderAdmin", "OrgAdmin")
    return envelope_ok(ser_disbursement(lookup("disbursements", did)), 200)


@app.post("/care-network/disbursements/<did>/run")
def run_disbursement(did):
    require_roles("FunderAdmin")
    d = lookup("disbursements", did)
    require_caller_org(d["funder_org_id"])
    body = get_body({"simulate_failure", "failure_reason"})
    simulate_failure = body.get("simulate_failure", False)
    if simulate_failure is not None and not isinstance(simulate_failure,
                                                       bool):
        err("ERR_INVALID_REQUEST", 400, "simulate_failure must be boolean")
    if d["status"] != "SCHEDULED":
        err("ERR_INVALID_STATE", 409, "Disbursement not SCHEDULED")
    if simulate_failure:
        d["status"] = "FAILED"
        d["failure_reason"] = opt_str(body, "failure_reason",
                                      "Simulated failure")
        touch(d)
        return envelope_ok(ser_disbursement(d), 200)
    for cl_id in d["claim_ids"]:
        c = STORE["claims"].get(cl_id)
        if (c is None or c["status"] != "APPROVED"
                or c["provider_org_id"] != d["provider_org_id"]):
            err("ERR_CLAIM_NOT_PAYABLE", 409,
                "Claim not APPROVED or belongs to another provider")
    provider = STORE["orgs"].get(d["provider_org_id"])
    if provider is None or provider["status"] != "ACTIVE":
        err("ERR_ORG_NOT_ACTIVE", 409, "Provider org not ACTIVE")
    total = 0
    for cl_id in d["claim_ids"]:
        c = STORE["claims"][cl_id]
        total += c["approved_amount_cents"]
        c["status"] = "PAID"
        touch(c)
        provider["payable_balance_cents"] -= c["approved_amount_cents"]
    d["total_amount_cents"] = total
    d["status"] = "PAID"
    touch(d)
    touch(provider)
    return envelope_ok(ser_disbursement(d), 200)


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------
@app.post("/care-network/organizations/<oid>/reports")
def create_report(oid):
    require_roles("FunderAdmin", "NetworkCoordinator")
    lookup("orgs", oid)
    body = get_body({"period_start", "period_end"})
    period_start = req_str(body, "period_start")
    period_end = req_str(body, "period_end")
    ps = parse_date(period_start)
    pe = parse_date(period_end)
    if ps is None or pe is None:
        err("ERR_INVALID_REQUEST", 400,
            "period_start/period_end must be ISO dates")
    if pe < ps:
        err("ERR_INVALID_REQUEST", 400,
            "period_end must be at or after period_start")
    rec = new_record()
    rec.update({
        "funder_org_id": oid, "period_start": period_start,
        "period_end": period_end, "baseline_snapshot_cents": 0,
        "total_referrals": 0, "delivered_count": 0, "not_reached_count": 0,
        "unresolved_count": 0, "aging_count": 0, "total_reimbursed_cents": 0,
        "demographic_breakdown": {}, "closure_rate_percent": 0.0,
        "resolution_rate_percent": 0.0, "status": "DRAFT",
    })
    sync_report(rec)
    STORE["reports"][rec["id"]] = rec
    return envelope_ok(ser_report(rec), 201)


@app.get("/care-network/reports/<rid>")
def get_report(rid):
    require_roles("NetworkCoordinator", "FunderAdmin")
    rec = lookup("reports", rid)
    if rec["status"] == "DRAFT":
        sync_report(rec)
    return envelope_ok(ser_report(rec), 200)


@app.get("/care-network/organizations/<oid>/reports")
def list_reports(oid):
    require_roles("NetworkCoordinator", "FunderAdmin")
    lookup("orgs", oid)
    status = request.args.get("status")
    recs = [r for r in STORE["reports"].values()
            if r["funder_org_id"] == oid]
    for r in recs:
        if r["status"] == "DRAFT":
            sync_report(r)
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    return list_response(recs, ser_report)


@app.post("/care-network/reports/<rid>/seal")
def seal_report(rid):
    require_roles("FunderAdmin")
    rec = lookup("reports", rid)
    require_caller_org(rec["funder_org_id"])
    if rec["status"] != "DRAFT":
        err("ERR_INVALID_STATE", 409, "Report not DRAFT")
    sync_report(rec)
    baseline = 0
    for c in STORE["claims"].values():
        if c.get("approved_amount_cents") is not None:
            baseline += c["approved_amount_cents"]
    rec["baseline_snapshot_cents"] = baseline
    rec["status"] = "SEALED"
    touch(rec)
    return envelope_ok(ser_report(rec), 200)


# ---------------------------------------------------------------------------
# Aging sweep
# ---------------------------------------------------------------------------
@app.post("/care-network/referrals/aging-sweep")
def aging_sweep_ep():
    require_roles("NetworkCoordinator")
    expired = run_aging_sweep()
    return envelope_ok({"expired_count": len(expired),
                        "expired_referral_ids": expired}, 200)


if __name__ == "__main__":
    import os
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
