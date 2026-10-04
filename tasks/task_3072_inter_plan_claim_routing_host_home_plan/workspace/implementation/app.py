from flask import Flask, request, jsonify
from decimal import Decimal, ROUND_HALF_UP
import uuid, os
from datetime import datetime, timezone

app = Flask(__name__)

# ---------------- Logical clock ----------------
DEFAULT_CLOCK = "2026-09-01T00:00:00Z"
clock_state = {"current_utc": DEFAULT_CLOCK}

def _parse_iso(s):
    if isinstance(s, str) and s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)

def clock_now():
    return _parse_iso(clock_state["current_utc"])

def clock_date():
    return clock_now().date().isoformat()

def ts_now():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"

# ---------------- Store ----------------
DB = {
    "plans": {},
    "members": {},
    "accounts": {},
    "rate_schedules": {},
    "fee_schedules": {},
    "claims": {},
    "adjustments": {},
    "batches": {},
    "inquiries": {},
}

ROLES = {"AssociationAdmin", "HomePlanOperator", "HostPlanOperator"}

class ApiError(Exception):
    def __init__(self, error_id, message, http):
        self.error_id = error_id
        self.message = message
        self.http = http

def err(error_id, message, http):
    raise ApiError(error_id, message, http)

def meta():
    return {"api_request_id": "req_" + uuid.uuid4().hex[:22], "api_request_timestamp": ts_now()}

def ok(data, response_type="object", code=200, pagination=None):
    m = meta()
    if pagination:
        m.update(pagination)
    return jsonify({"meta": m, "response_type": response_type, "data": data}), code

@app.errorhandler(ApiError)
def handle_api(e):
    return jsonify({"meta": meta(), "response_type": "error",
                    "data": {"error_id": e.error_id, "message": e.message}}), e.http

@app.errorhandler(404)
def handle_404(e):
    return jsonify({"meta": meta(), "response_type": "error",
                    "data": {"error_id": "ERR_NOT_FOUND", "message": "Route not found"}}), 404

@app.errorhandler(405)
def handle_405(e):
    return jsonify({"meta": meta(), "response_type": "error",
                    "data": {"error_id": "ERR_NOT_FOUND", "message": "Route not found"}}), 405

@app.errorhandler(Exception)
def handle_exc(e):
    return jsonify({"meta": meta(), "response_type": "error",
                    "data": {"error_id": "ERR_VALIDATION_FAILED", "message": str(e)}}), 400

# ---------------- Auth ----------------
def auth():
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if not role or not uid or role not in ROLES:
        err("ERR_UNAUTHENTICATED", "Missing or invalid X-User-Role / X-User-ID headers", 401)
    return role, uid

def require_role(role, allowed):
    if role not in allowed:
        err("ERR_UNAUTHORIZED", "Role not permitted to invoke this endpoint", 403)

def require_plan_actor(role, uid, plan_id):
    """For plan-scoped roles, X-User-ID must equal the relevant plan id."""
    if role in ("HomePlanOperator", "HostPlanOperator") and uid != plan_id:
        err("ERR_UNAUTHORIZED", "Plan-scoped role acting on a plan other than its own", 403)

def body():
    if request.data:
        try:
            b = request.get_json(force=True, silent=False)
        except Exception:
            err("ERR_VALIDATION_FAILED", "Malformed JSON body", 400)
        if b is None:
            return {}
        if not isinstance(b, dict):
            err("ERR_VALIDATION_FAILED", "Request body must be a JSON object", 400)
        return b
    return {}

def req_fields(b, fields):
    for f in fields:
        if f not in b or b[f] is None:
            err("ERR_VALIDATION_FAILED", f"Missing required field: {f}", 400)

def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)

def is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)

def check_int(b, f):
    if f in b and b[f] is not None and not is_int(b[f]):
        err("ERR_VALIDATION_FAILED", f"Field {f} must be an integer", 400)

def check_num(b, f):
    if f in b and b[f] is not None and not is_num(b[f]):
        err("ERR_VALIDATION_FAILED", f"Field {f} must be a number", 400)

def check_str(b, f):
    if f in b and b[f] is not None and not isinstance(b[f], str):
        err("ERR_VALIDATION_FAILED", f"Field {f} must be a string", 400)

def check_str_list(b, f):
    if f in b and b[f] is not None:
        if not isinstance(b[f], list) or any(not isinstance(x, str) for x in b[f]):
            err("ERR_VALIDATION_FAILED", f"Field {f} must be a list of strings", 400)

def check_date(s, field):
    if not isinstance(s, str):
        err("ERR_VALIDATION_FAILED", f"Field {field} must be a date string", 400)
    try:
        datetime.strptime(s, "%Y-%m-%d")
    except Exception:
        err("ERR_VALIDATION_FAILED", f"Field {field} must be an ISO date (YYYY-MM-DD)", 400)

def check_enum(b, f, values):
    if f in b and b[f] is not None and b[f] not in values:
        err("ERR_VALIDATION_FAILED", f"Field {f} must be one of {sorted(values)}", 400)

def new_common():
    return {"id": str(uuid.uuid4()), "created_at": ts_now(), "updated_at": ts_now(), "version": 1}

def touch(r):
    r["updated_at"] = ts_now()
    r["version"] += 1

def get_or_404(coll, rid):
    r = DB[coll].get(rid)
    if not r:
        err("ERR_NOT_FOUND", "Referenced resource id does not exist", 404)
    return r

def round_half_up(x):
    return int(Decimal(str(x)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))

def pct_amount(cents, rate):
    return round_half_up(Decimal(cents) * Decimal(str(rate)))

def paginate(items):
    q = request.args
    try:
        limit = int(q.get("limit", 10))
        offset = int(q.get("offset", 0))
    except Exception:
        err("ERR_VALIDATION_FAILED", "limit and offset must be integers", 400)
    if limit < 1 or limit > 100 or offset < 0:
        err("ERR_VALIDATION_FAILED", "limit must be in [1,100], offset >= 0", 400)
    # Stable sort: ties on created_at keep insertion (creation) order
    items.sort(key=lambda r: r["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return ok(page, "array", 200, {"limit": limit, "offset": offset,
                                   "total_count": total, "has_more": offset + limit < total})

NON_TERMINAL_CLAIM = {"RECEIVED", "PRICED", "ROUTED", "BENEFIT_DETERMINED", "ADJUSTMENT_PENDING"}

# ---------------- Plans ----------------
@app.post("/v1/plans")
def create_plan():
    role, uid = auth()
    require_role(role, ["AssociationAdmin"])
    b = body()
    req_fields(b, ["plan_code", "legal_name", "service_area_states"])
    check_str(b, "plan_code"); check_str(b, "legal_name"); check_str_list(b, "service_area_states")
    if not b["service_area_states"]:
        err("ERR_VALIDATION_FAILED", "service_area_states must be non-empty", 400)
    if any(p["plan_code"] == b["plan_code"] for p in DB["plans"].values()):
        err("ERR_DUPLICATE_PLAN_CODE", "plan_code already registered", 409)
    r = new_common()
    r.update({"plan_code": b["plan_code"], "legal_name": b["legal_name"],
              "service_area_states": list(b["service_area_states"]),
              "brand_license_status": "PENDING",
              "claims_paid_balance_cents": 0, "fees_receivable_balance_cents": 0})
    DB["plans"][r["id"]] = r
    return ok(r, code=201)

@app.get("/v1/plans/<pid>")
def get_plan(pid):
    role, uid = auth()
    return ok(get_or_404("plans", pid))

@app.get("/v1/plans")
def list_plans():
    role, uid = auth()
    items = list(DB["plans"].values())
    f = request.args.get("brand_license_status")
    if f:
        items = [p for p in items if p["brand_license_status"] == f]
    return paginate(items)

def plan_transition(pid, from_states, to_state):
    role, uid = auth()
    require_role(role, ["AssociationAdmin"])
    p = get_or_404("plans", pid)
    if p["brand_license_status"] not in from_states:
        err("ERR_INVALID_STATE", "Requested transition is not defined from the resource's current state", 409)
    return p

@app.post("/v1/plans/<pid>/activate-license")
def activate_plan(pid):
    p = plan_transition(pid, {"PENDING"}, "LICENSED")
    p["brand_license_status"] = "LICENSED"; touch(p)
    return ok(p)

@app.post("/v1/plans/<pid>/suspend-license")
def suspend_plan(pid):
    p = plan_transition(pid, {"LICENSED"}, "SUSPENDED")
    p["brand_license_status"] = "SUSPENDED"; touch(p)
    return ok(p)

@app.post("/v1/plans/<pid>/reinstate-license")
def reinstate_plan(pid):
    p = plan_transition(pid, {"SUSPENDED"}, "LICENSED")
    p["brand_license_status"] = "LICENSED"; touch(p)
    return ok(p)

@app.post("/v1/plans/<pid>/revoke-license")
def revoke_plan(pid):
    p = plan_transition(pid, {"LICENSED"}, "REVOKED")
    for c in DB["claims"].values():
        if (c["host_plan_id"] == pid or c["home_plan_id"] == pid) and c["status"] in NON_TERMINAL_CLAIM:
            err("ERR_INVALID_STATE", "Plan has claims in a non-terminal state", 409)
    p["brand_license_status"] = "REVOKED"; touch(p)
    for a in DB["accounts"].values():
        if a["controlling_plan_id"] == pid and a["status"] in ("ACTIVE", "SUSPENDED"):
            a["status"] = "TERMINATED"; touch(a)
    return ok(p)

# ---------------- Members ----------------
@app.post("/v1/members")
def create_member():
    role, uid = auth()
    require_role(role, ["HomePlanOperator", "AssociationAdmin"])
    b = body()
    req_fields(b, ["home_plan_id", "member_number", "full_name"])
    check_str(b, "home_plan_id"); check_str(b, "member_number"); check_str(b, "full_name")
    check_str(b, "national_account_id")
    get_or_404("plans", b["home_plan_id"])
    if role == "HomePlanOperator":
        require_plan_actor(role, uid, b["home_plan_id"])
    naid = b.get("national_account_id")
    if naid is not None:
        get_or_404("accounts", naid)
    if any(m["home_plan_id"] == b["home_plan_id"] and m["member_number"] == b["member_number"]
           for m in DB["members"].values()):
        err("ERR_DUPLICATE_MEMBER_NUMBER", "member_number already exists under the same home_plan_id", 409)
    r = new_common()
    r.update({"home_plan_id": b["home_plan_id"], "national_account_id": naid,
              "member_number": b["member_number"], "full_name": b["full_name"],
              "eligibility_status": "ACTIVE"})
    DB["members"][r["id"]] = r
    return ok(r, code=201)

@app.get("/v1/members/<mid>")
def get_member(mid):
    role, uid = auth()
    return ok(get_or_404("members", mid))

@app.get("/v1/members")
def list_members():
    role, uid = auth()
    items = list(DB["members"].values())
    for f in ("home_plan_id", "member_number", "national_account_id"):
        v = request.args.get(f)
        if v is not None:
            items = [m for m in items if m.get(f) == v]
    return paginate(items)

@app.post("/v1/members/<mid>/terminate")
def terminate_member(mid):
    role, uid = auth()
    require_role(role, ["HomePlanOperator"])
    m = get_or_404("members", mid)
    require_plan_actor(role, uid, m["home_plan_id"])
    if m["eligibility_status"] != "ACTIVE":
        err("ERR_INVALID_STATE", "Member is not ACTIVE", 409)
    m["eligibility_status"] = "TERMINATED"; touch(m)
    return ok(m)

# ---------------- National Accounts ----------------
def windows_overlap_closed(s1, e1, s2, e2):
    return s1 <= e2 and s2 <= e1

@app.post("/v1/national-accounts")
def create_account():
    role, uid = auth()
    require_role(role, ["AssociationAdmin"])
    b = body()
    req_fields(b, ["controlling_plan_id", "account_name", "employer_group_id",
                   "territory_states", "effective_start", "effective_end"])
    check_str(b, "controlling_plan_id"); check_str(b, "account_name")
    check_str(b, "employer_group_id"); check_str_list(b, "territory_states")
    check_date(b["effective_start"], "effective_start"); check_date(b["effective_end"], "effective_end")
    get_or_404("plans", b["controlling_plan_id"])
    if not b["territory_states"]:
        err("ERR_VALIDATION_FAILED", "territory_states must be non-empty", 400)
    if b["effective_end"] < b["effective_start"]:
        err("ERR_ACCOUNT_WINDOW_OVERLAP", "effective_end must be >= effective_start", 422)
    for a in DB["accounts"].values():
        if (a["controlling_plan_id"] == b["controlling_plan_id"]
                and a["employer_group_id"] == b["employer_group_id"]
                and windows_overlap_closed(a["effective_start"], a["effective_end"],
                                           b["effective_start"], b["effective_end"])):
            err("ERR_ACCOUNT_WINDOW_OVERLAP", "NationalAccount window overlaps an existing window", 422)
    r = new_common()
    r.update({"controlling_plan_id": b["controlling_plan_id"], "account_name": b["account_name"],
              "employer_group_id": b["employer_group_id"],
              "territory_states": list(b["territory_states"]),
              "effective_start": b["effective_start"], "effective_end": b["effective_end"],
              "status": "PROPOSED"})
    DB["accounts"][r["id"]] = r
    return ok(r, code=201)

@app.get("/v1/national-accounts/<aid>")
def get_account(aid):
    role, uid = auth()
    return ok(get_or_404("accounts", aid))

@app.get("/v1/national-accounts")
def list_accounts():
    role, uid = auth()
    items = list(DB["accounts"].values())
    for f in ("controlling_plan_id", "status"):
        v = request.args.get(f)
        if v is not None:
            items = [a for a in items if a.get(f) == v]
    return paginate(items)

def account_transition(aid, from_states, to_state, check_license=False):
    role, uid = auth()
    require_role(role, ["AssociationAdmin"])
    a = get_or_404("accounts", aid)
    if a["status"] not in from_states:
        err("ERR_INVALID_STATE", "Requested transition is not defined from the resource's current state", 409)
    if check_license:
        p = DB["plans"].get(a["controlling_plan_id"])
        if not p or p["brand_license_status"] != "LICENSED":
            err("ERR_INVALID_STATE", "Controlling plan is not LICENSED", 409)
    a["status"] = to_state; touch(a)
    return a

@app.post("/v1/national-accounts/<aid>/activate")
def activate_account(aid):
    return ok(account_transition(aid, {"PROPOSED"}, "ACTIVE", True))

@app.post("/v1/national-accounts/<aid>/suspend")
def suspend_account(aid):
    return ok(account_transition(aid, {"ACTIVE"}, "SUSPENDED"))

@app.post("/v1/national-accounts/<aid>/reactivate")
def reactivate_account(aid):
    return ok(account_transition(aid, {"SUSPENDED"}, "ACTIVE", True))

@app.post("/v1/national-accounts/<aid>/terminate")
def terminate_account(aid):
    return ok(account_transition(aid, {"ACTIVE"}, "TERMINATED"))

# ---------------- Rate Schedules ----------------
@app.post("/v1/rate-schedules")
def create_rate_schedule():
    role, uid = auth()
    require_role(role, ["HostPlanOperator", "AssociationAdmin"])
    b = body()
    req_fields(b, ["plan_id", "provider_npi", "procedure_code",
                   "negotiated_rate_cents", "effective_start", "effective_end"])
    check_str(b, "plan_id"); check_str(b, "provider_npi"); check_str(b, "procedure_code")
    check_int(b, "negotiated_rate_cents")
    check_date(b["effective_start"], "effective_start"); check_date(b["effective_end"], "effective_end")
    get_or_404("plans", b["plan_id"])
    if role == "HostPlanOperator":
        require_plan_actor(role, uid, b["plan_id"])
    if b["effective_end"] <= b["effective_start"]:
        err("ERR_RATE_WINDOW_OVERLAP", "effective_end must be > effective_start", 422)
    if not is_int(b["negotiated_rate_cents"]) or b["negotiated_rate_cents"] <= 0:
        err("ERR_INVALID_AMOUNT", "negotiated_rate_cents must be > 0", 422)
    for s in DB["rate_schedules"].values():
        if (s["plan_id"] == b["plan_id"] and s["provider_npi"] == b["provider_npi"]
                and s["procedure_code"] == b["procedure_code"]):
            # half-open overlap: start < existing_end and new_end > existing_start
            if b["effective_start"] < s["effective_end"] and b["effective_end"] > s["effective_start"]:
                err("ERR_RATE_WINDOW_OVERLAP", "RateSchedule half-open window overlaps an existing window", 422)
    r = new_common()
    r.update({"plan_id": b["plan_id"], "provider_npi": b["provider_npi"],
              "procedure_code": b["procedure_code"],
              "negotiated_rate_cents": b["negotiated_rate_cents"],
              "effective_start": b["effective_start"], "effective_end": b["effective_end"]})
    DB["rate_schedules"][r["id"]] = r
    return ok(r, code=201)

@app.get("/v1/rate-schedules/<sid>")
def get_rate_schedule(sid):
    role, uid = auth()
    return ok(get_or_404("rate_schedules", sid))

@app.get("/v1/rate-schedules")
def list_rate_schedules():
    role, uid = auth()
    items = list(DB["rate_schedules"].values())
    for f in ("plan_id", "provider_npi", "procedure_code"):
        v = request.args.get(f)
        if v is not None:
            items = [s for s in items if s.get(f) == v]
    return paginate(items)

# ---------------- Access Fee Schedules ----------------
@app.post("/v1/access-fee-schedules")
def create_fee_schedule():
    role, uid = auth()
    require_role(role, ["AssociationAdmin"])
    b = body()
    req_fields(b, ["home_plan_id", "host_plan_id", "tier1_cap_cents", "tier1_fee_cents",
                   "tier2_rate", "effective_start", "effective_end"])
    check_str(b, "home_plan_id"); check_str(b, "host_plan_id")
    check_int(b, "tier1_cap_cents"); check_int(b, "tier1_fee_cents")
    check_num(b, "tier2_rate"); check_num(b, "national_account_discount_pct")
    check_date(b["effective_start"], "effective_start"); check_date(b["effective_end"], "effective_end")
    get_or_404("plans", b["home_plan_id"])
    get_or_404("plans", b["host_plan_id"])
    if b["effective_end"] < b["effective_start"]:
        err("ERR_FEE_WINDOW_OVERLAP", "effective_end must be >= effective_start", 422)
    cap = b["tier1_cap_cents"]; fee1 = b["tier1_fee_cents"]; t2 = b["tier2_rate"]
    disc = b.get("national_account_discount_pct", 0)
    if not is_int(cap) or cap <= 0 or not is_int(fee1) or fee1 < 0 \
            or not is_num(t2) or t2 < 0 or not is_num(disc) or disc < 0 or disc > 1:
        err("ERR_INVALID_AMOUNT", "Tier values must be non-negative, cap > 0, discount within [0,1]", 422)
    for s in DB["fee_schedules"].values():
        if (s["home_plan_id"] == b["home_plan_id"] and s["host_plan_id"] == b["host_plan_id"]
                and windows_overlap_closed(s["effective_start"], s["effective_end"],
                                           b["effective_start"], b["effective_end"])):
            err("ERR_FEE_WINDOW_OVERLAP", "AccessFeeSchedule closed window overlaps an existing window", 422)
    r = new_common()
    r.update({"home_plan_id": b["home_plan_id"], "host_plan_id": b["host_plan_id"],
              "tier1_cap_cents": cap, "tier1_fee_cents": fee1,
              "tier2_rate": t2, "national_account_discount_pct": disc,
              "effective_start": b["effective_start"], "effective_end": b["effective_end"]})
    DB["fee_schedules"][r["id"]] = r
    return ok(r, code=201)

@app.get("/v1/access-fee-schedules/<sid>")
def get_fee_schedule(sid):
    role, uid = auth()
    return ok(get_or_404("fee_schedules", sid))

@app.get("/v1/access-fee-schedules")
def list_fee_schedules():
    role, uid = auth()
    items = list(DB["fee_schedules"].values())
    for f in ("home_plan_id", "host_plan_id"):
        v = request.args.get(f)
        if v is not None:
            items = [s for s in items if s.get(f) == v]
    return paginate(items)

# ---------------- Claims ----------------
def find_rate(host_plan_id, npi, proc, date):
    for s in DB["rate_schedules"].values():
        if (s["plan_id"] == host_plan_id and s["provider_npi"] == npi
                and s["procedure_code"] == proc
                and s["effective_start"] <= date < s["effective_end"]):
            return s
    return None

def find_fee_schedule(home_plan_id, host_plan_id, date):
    for s in DB["fee_schedules"].values():
        if (s["home_plan_id"] == home_plan_id and s["host_plan_id"] == host_plan_id
                and s["effective_start"] <= date <= s["effective_end"]):
            return s
    return None

def check_plans_licensed(home_id, host_id):
    home = DB["plans"].get(home_id)
    host = DB["plans"].get(host_id)
    if (not home or home["brand_license_status"] != "LICENSED"
            or not host or host["brand_license_status"] != "LICENSED"):
        err("ERR_PLAN_LICENSE_SUSPENDED",
            "Home or host plan brand_license_status is not LICENSED", 409)

@app.post("/v1/claims")
def create_claim():
    role, uid = auth()
    require_role(role, ["HostPlanOperator"])
    b = body()
    req_fields(b, ["member_id", "host_plan_id", "provider_npi", "procedure_code",
                   "service_date", "service_state", "billed_amount_cents"])
    check_str(b, "member_id"); check_str(b, "host_plan_id"); check_str(b, "provider_npi")
    check_str(b, "procedure_code"); check_str(b, "service_state")
    check_date(b["service_date"], "service_date")
    check_int(b, "billed_amount_cents")
    m = get_or_404("members", b["member_id"])
    host = get_or_404("plans", b["host_plan_id"])
    require_plan_actor(role, uid, b["host_plan_id"])
    home = get_or_404("plans", m["home_plan_id"])
    if b["host_plan_id"] == m["home_plan_id"]:
        err("ERR_SAME_PLAN_CLAIM", "host_plan_id equals the member's home plan", 422)
    if b["service_state"] not in host["service_area_states"]:
        err("ERR_OUT_OF_SERVICE_AREA", "service_state is not in the host plan's service_area_states", 422)
    check_plans_licensed(m["home_plan_id"], b["host_plan_id"])
    if not is_int(b["billed_amount_cents"]) or b["billed_amount_cents"] <= 0:
        err("ERR_INVALID_AMOUNT", "billed_amount_cents must be > 0", 422)
    # provisional pricing, keyed on service_date, fallback to billed
    rate = find_rate(b["host_plan_id"], b["provider_npi"], b["procedure_code"], b["service_date"])
    if rate is None:
        provisional = b["billed_amount_cents"]
    else:
        provisional = min(b["billed_amount_cents"], rate["negotiated_rate_cents"])
    r = new_common()
    r.update({"member_id": b["member_id"], "host_plan_id": b["host_plan_id"],
              "home_plan_id": m["home_plan_id"], "national_account_id": m.get("national_account_id"),
              "provider_npi": b["provider_npi"], "procedure_code": b["procedure_code"],
              "service_date": b["service_date"], "service_state": b["service_state"],
              "billed_amount_cents": b["billed_amount_cents"],
              "provisional_allowed_cents": provisional,
              "priced_allowed_cents": None, "access_fee_cents": None,
              "admin_charge_cents": None, "provider_payment_cents": None,
              "current_allowed_cents": None, "status": "RECEIVED"})
    DB["claims"][r["id"]] = r
    return ok(r, code=201)

@app.get("/v1/claims/<cid>")
def get_claim(cid):
    role, uid = auth()
    return ok(get_or_404("claims", cid))

@app.get("/v1/claims")
def list_claims():
    role, uid = auth()
    items = list(DB["claims"].values())
    for f in ("home_plan_id", "host_plan_id", "member_id", "national_account_id", "status"):
        v = request.args.get(f)
        if v is not None:
            items = [c for c in items if c.get(f) == v]
    return paginate(items)

def claim_host_action(cid, from_states):
    role, uid = auth()
    require_role(role, ["HostPlanOperator"])
    c = get_or_404("claims", cid)
    require_plan_actor(role, uid, c["host_plan_id"])
    if c["status"] not in from_states:
        err("ERR_INVALID_STATE", "Requested transition is not defined from the resource's current state", 409)
    return c

def claim_home_action(cid, from_states):
    role, uid = auth()
    require_role(role, ["HomePlanOperator"])
    c = get_or_404("claims", cid)
    require_plan_actor(role, uid, c["home_plan_id"])
    if c["status"] not in from_states:
        err("ERR_INVALID_STATE", "Requested transition is not defined from the resource's current state", 409)
    return c

@app.post("/v1/claims/<cid>/price")
def price_claim(cid):
    c = claim_host_action(cid, {"RECEIVED"})
    rate = find_rate(c["host_plan_id"], c["provider_npi"], c["procedure_code"], clock_date())
    if rate is None:
        err("ERR_RATE_SCHEDULE_MISSING", "No RateSchedule window covers the pricing date", 422)
    c["priced_allowed_cents"] = min(c["billed_amount_cents"], rate["negotiated_rate_cents"])
    c["current_allowed_cents"] = c["priced_allowed_cents"]
    c["status"] = "PRICED"; touch(c)
    return ok(c)

@app.post("/v1/claims/<cid>/route")
def route_claim(cid):
    c = claim_host_action(cid, {"PRICED"})
    check_plans_licensed(c["home_plan_id"], c["host_plan_id"])
    sched = find_fee_schedule(c["home_plan_id"], c["host_plan_id"], c["service_date"])
    if sched is None:
        err("ERR_FEE_SCHEDULE_MISSING", "No AccessFeeSchedule covers service_date for the (home, host) pair", 422)
    allowed = c["current_allowed_cents"]
    if allowed <= sched["tier1_cap_cents"]:
        base_fee = sched["tier1_fee_cents"]
    else:
        base_fee = pct_amount(allowed, sched["tier2_rate"])
    fee = base_fee
    naid = c.get("national_account_id")
    if naid:
        acct = DB["accounts"].get(naid)
        if (acct and acct["controlling_plan_id"] == c["home_plan_id"]
                and acct["status"] == "ACTIVE"
                and acct["effective_start"] <= c["service_date"] <= acct["effective_end"]):
            fee = round_half_up(Decimal(base_fee) * (Decimal(1) - Decimal(str(sched["national_account_discount_pct"]))))
    c["access_fee_cents"] = fee
    # admin charge: cumulative marginal brackets, round each slice then sum
    admin = 0
    admin += pct_amount(min(allowed, 10000), "0.05")
    if allowed > 10000:
        admin += pct_amount(min(allowed, 100000) - 10000, "0.03")
    if allowed > 100000:
        admin += pct_amount(allowed - 100000, "0.01")
    c["admin_charge_cents"] = admin
    c["status"] = "ROUTED"; touch(c)
    return ok(c)

@app.post("/v1/claims/<cid>/determine-benefit")
def determine_benefit(cid):
    c = claim_home_action(cid, {"ROUTED"})
    m = DB["members"].get(c["member_id"])
    if not m or m["eligibility_status"] != "ACTIVE":
        err("ERR_MEMBER_INELIGIBLE", "Member eligibility_status is TERMINATED at benefit determination", 422)
    c["status"] = "BENEFIT_DETERMINED"; touch(c)
    return ok(c)

@app.post("/v1/claims/<cid>/deny")
def deny_claim(cid):
    c = claim_home_action(cid, {"ROUTED"})
    c["status"] = "DENIED"; touch(c)
    return ok(c)

@app.post("/v1/claims/<cid>/pay")
def pay_claim(cid):
    c = claim_host_action(cid, {"BENEFIT_DETERMINED"})
    c["provider_payment_cents"] = c["current_allowed_cents"]
    host = DB["plans"][c["host_plan_id"]]
    host["claims_paid_balance_cents"] += c["provider_payment_cents"]
    host["fees_receivable_balance_cents"] += (c["access_fee_cents"] or 0) + (c["admin_charge_cents"] or 0)
    touch(host)
    c["status"] = "PAID"; touch(c)
    return ok(c)

# ---------------- Adjustments ----------------
@app.post("/v1/claims/<cid>/adjustments")
def create_adjustment(cid):
    role, uid = auth()
    require_role(role, ["HostPlanOperator"])
    b = body()
    c = get_or_404("claims", cid)
    require_plan_actor(role, uid, c["host_plan_id"])
    if c["status"] not in ("PAID", "ADJUSTMENT_PENDING"):
        err("ERR_INVALID_STATE", "Adjustment can only be created on a PAID or ADJUSTMENT_PENDING claim", 409)
    req_fields(b, ["reason", "delta_allowed_cents", "expected_claim_version"])
    check_str(b, "reason"); check_int(b, "delta_allowed_cents"); check_int(b, "expected_claim_version")
    if b["expected_claim_version"] != c["version"]:
        err("ERR_STALE_VERSION", "expected_claim_version does not equal the claim's current version", 412)
    if not is_int(b["delta_allowed_cents"]) or b["delta_allowed_cents"] == 0:
        err("ERR_INVALID_AMOUNT", "delta_allowed_cents must be non-zero", 422)
    supersedes = None
    for a in DB["adjustments"].values():
        if a["claim_id"] == cid and a["status"] == "INITIATED":
            a["status"] = "REJECTED"; touch(a)
            supersedes = a["id"]
    if c["status"] == "PAID":
        c["status"] = "ADJUSTMENT_PENDING"
    touch(c)
    r = new_common()
    r.update({"claim_id": cid, "supersedes_adjustment_id": supersedes,
              "reason": b["reason"], "delta_allowed_cents": b["delta_allowed_cents"],
              "recovery_amount_cents": 0, "status": "INITIATED"})
    DB["adjustments"][r["id"]] = r
    return ok(r, code=201)

@app.get("/v1/adjustments/<aid>")
def get_adjustment(aid):
    role, uid = auth()
    return ok(get_or_404("adjustments", aid))

@app.get("/v1/adjustments")
def list_adjustments():
    role, uid = auth()
    items = list(DB["adjustments"].values())
    for f in ("claim_id", "status", "supersedes_adjustment_id"):
        v = request.args.get(f)
        if v is not None:
            items = [a for a in items if a.get(f) == v]
    return paginate(items)

@app.post("/v1/adjustments/<aid>/validate")
def validate_adjustment(aid):
    role, uid = auth()
    require_role(role, ["HostPlanOperator"])
    a = get_or_404("adjustments", aid)
    c = get_or_404("claims", a["claim_id"])
    require_plan_actor(role, uid, c["host_plan_id"])
    if a["status"] != "INITIATED":
        err("ERR_INVALID_STATE", "Adjustment is not INITIATED", 409)
    if c["status"] != "ADJUSTMENT_PENDING":
        err("ERR_INVALID_STATE", "Parent claim is not ADJUSTMENT_PENDING", 409)
    a["status"] = "VALIDATED"; touch(a)
    return ok(a)

@app.post("/v1/adjustments/<aid>/propagate")
def propagate_adjustment(aid):
    role, uid = auth()
    require_role(role, ["HomePlanOperator"])
    a = get_or_404("adjustments", aid)
    c = get_or_404("claims", a["claim_id"])
    require_plan_actor(role, uid, c["home_plan_id"])
    if a["status"] != "VALIDATED":
        err("ERR_INVALID_STATE", "Adjustment is not VALIDATED", 409)
    a["status"] = "PROPAGATED"; touch(a)
    return ok(a)

@app.post("/v1/adjustments/<aid>/apply")
def apply_adjustment(aid):
    role, uid = auth()
    require_role(role, ["HostPlanOperator"])
    a = get_or_404("adjustments", aid)
    c = get_or_404("claims", a["claim_id"])
    require_plan_actor(role, uid, c["host_plan_id"])
    if a["status"] != "PROPAGATED":
        err("ERR_INVALID_STATE", "Adjustment is not PROPAGATED", 409)
    if c["current_allowed_cents"] + a["delta_allowed_cents"] < 0:
        err("ERR_NEGATIVE_ALLOWED", "Applying the adjustment would drive current_allowed_cents below 0", 422)
    recovery = max(0, -a["delta_allowed_cents"])
    c["current_allowed_cents"] = c["current_allowed_cents"] + a["delta_allowed_cents"]
    a["recovery_amount_cents"] = recovery
    host = DB["plans"][c["host_plan_id"]]
    host["claims_paid_balance_cents"] -= recovery
    touch(host)
    a["status"] = "APPLIED"; touch(a)
    c["status"] = "PAID"; touch(c)
    return ok(a)

@app.post("/v1/adjustments/<aid>/reject")
def reject_adjustment(aid):
    role, uid = auth()
    require_role(role, ["HomePlanOperator"])
    a = get_or_404("adjustments", aid)
    c = get_or_404("claims", a["claim_id"])
    require_plan_actor(role, uid, c["home_plan_id"])
    if a["status"] not in ("INITIATED", "VALIDATED"):
        err("ERR_INVALID_STATE", "Adjustment is not INITIATED or VALIDATED", 409)
    a["status"] = "REJECTED"; touch(a)
    if c["status"] == "ADJUSTMENT_PENDING":
        c["status"] = "PAID"; touch(c)
    return ok(a)

# ---------------- Settlement Batches ----------------
@app.post("/v1/settlement-batches")
def create_batch():
    role, uid = auth()
    require_role(role, ["HostPlanOperator"])
    b = body()
    req_fields(b, ["debtor_plan_id", "creditor_plan_id", "period_start", "period_end"])
    check_str(b, "debtor_plan_id"); check_str(b, "creditor_plan_id")
    check_date(b["period_start"], "period_start"); check_date(b["period_end"], "period_end")
    check_enum(b, "settlement_variant", {"NET", "GROSS"})
    get_or_404("plans", b["debtor_plan_id"])
    get_or_404("plans", b["creditor_plan_id"])
    require_plan_actor(role, uid, b["creditor_plan_id"])
    if b["debtor_plan_id"] == b["creditor_plan_id"]:
        err("ERR_VALIDATION_FAILED", "creditor_plan_id must differ from debtor_plan_id", 400)
    if b["period_end"] < b["period_start"]:
        err("ERR_VALIDATION_FAILED", "period_end must be >= period_start", 400)
    r = new_common()
    r.update({"debtor_plan_id": b["debtor_plan_id"], "creditor_plan_id": b["creditor_plan_id"],
              "period_start": b["period_start"], "period_end": b["period_end"],
              "gross_claims_total_cents": None, "fees_total_cents": None,
              "net_settlement_cents": None,
              "settlement_variant": b.get("settlement_variant", "NET"),
              "status": "OPEN"})
    r["_swept_claim_ids"] = []
    DB["batches"][r["id"]] = r
    return ok(r, code=201)

def batch_view(b):
    return {k: v for k, v in b.items() if not k.startswith("_")}

@app.get("/v1/settlement-batches/<bid>")
def get_batch(bid):
    role, uid = auth()
    return ok(batch_view(get_or_404("batches", bid)))

@app.get("/v1/settlement-batches")
def list_batches():
    role, uid = auth()
    items = list(DB["batches"].values())
    for f in ("debtor_plan_id", "creditor_plan_id", "status"):
        v = request.args.get(f)
        if v is not None:
            items = [x for x in items if x.get(f) == v]
    # Stable sort: ties on created_at keep insertion (creation) order
    items.sort(key=lambda r: r["created_at"])
    q = request.args
    try:
        limit = int(q.get("limit", 10)); offset = int(q.get("offset", 0))
    except Exception:
        err("ERR_VALIDATION_FAILED", "limit and offset must be integers", 400)
    if limit < 1 or limit > 100 or offset < 0:
        err("ERR_VALIDATION_FAILED", "limit must be in [1,100], offset >= 0", 400)
    total = len(items)
    page = [batch_view(x) for x in items[offset:offset + limit]]
    return ok(page, "array", 200, {"limit": limit, "offset": offset,
                                   "total_count": total, "has_more": offset + limit < total})

def run_sweep(btch):
    claims = [c for c in DB["claims"].values()
              if c["home_plan_id"] == btch["debtor_plan_id"]
              and c["host_plan_id"] == btch["creditor_plan_id"]
              and c["status"] == "PAID"
              and btch["period_start"] <= c["service_date"] <= btch["period_end"]]
    claims.sort(key=lambda c: (c["service_date"], c["created_at"]))
    return claims

def finalize_totals(btch, claims):
    gross = sum(c["provider_payment_cents"] for c in claims)
    swept_ids = {c["id"] for c in claims}
    recoveries = sum(a["recovery_amount_cents"] for a in DB["adjustments"].values()
                     if a["claim_id"] in swept_ids and a["status"] == "APPLIED")
    fees = sum((c["access_fee_cents"] or 0) + (c["admin_charge_cents"] or 0) for c in claims) - recoveries
    btch["gross_claims_total_cents"] = gross
    btch["fees_total_cents"] = fees
    if btch["settlement_variant"] == "NET":
        btch["net_settlement_cents"] = gross - fees
    else:
        btch["net_settlement_cents"] = gross
    btch["_swept_claim_ids"] = [c["id"] for c in claims]

@app.post("/v1/settlement-batches/<bid>/finalize")
def finalize_batch(bid):
    role, uid = auth()
    require_role(role, ["HostPlanOperator"])
    btch = get_or_404("batches", bid)
    require_plan_actor(role, uid, btch["creditor_plan_id"])
    if btch["status"] != "OPEN":
        err("ERR_INVALID_STATE", "Batch is not OPEN", 409)
    claims = run_sweep(btch)
    if not claims:
        err("ERR_EMPTY_BATCH", "Finalize requested on a batch whose sweep scope contains no PAID claims", 422)
    finalize_totals(btch, claims)
    btch["status"] = "FINALIZED"; touch(btch)
    return ok(batch_view(btch))

@app.post("/v1/settlement-batches/<bid>/acknowledge")
def acknowledge_batch(bid):
    role, uid = auth()
    require_role(role, ["HomePlanOperator"])
    btch = get_or_404("batches", bid)
    require_plan_actor(role, uid, btch["debtor_plan_id"])
    if btch["status"] != "FINALIZED":
        err("ERR_INVALID_STATE", "Batch is not FINALIZED", 409)
    btch["status"] = "ACKNOWLEDGED"; touch(btch)
    return ok(batch_view(btch))

@app.post("/v1/settlement-batches/<bid>/dispute")
def dispute_batch(bid):
    role, uid = auth()
    require_role(role, ["HomePlanOperator"])
    btch = get_or_404("batches", bid)
    require_plan_actor(role, uid, btch["debtor_plan_id"])
    if btch["status"] != "FINALIZED":
        err("ERR_INVALID_STATE", "Batch is not FINALIZED", 409)
    btch["status"] = "DISPUTED"; touch(btch)
    return ok(batch_view(btch))

@app.post("/v1/settlement-batches/<bid>/refinalize")
def refinalize_batch(bid):
    role, uid = auth()
    require_role(role, ["HostPlanOperator"])
    btch = get_or_404("batches", bid)
    require_plan_actor(role, uid, btch["creditor_plan_id"])
    if btch["status"] != "DISPUTED":
        err("ERR_INVALID_STATE", "Batch is not DISPUTED", 409)
    b = body()
    req_fields(b, ["expected_settlement_batch_version"])
    check_int(b, "expected_settlement_batch_version")
    if b["expected_settlement_batch_version"] != btch["version"]:
        err("ERR_STALE_VERSION", "expected_settlement_batch_version does not equal the batch's current version", 412)
    claims = run_sweep(btch)
    if not claims:
        err("ERR_EMPTY_BATCH", "Re-finalize sweep scope contains no PAID claims", 422)
    finalize_totals(btch, claims)
    btch["status"] = "FINALIZED"; touch(btch)
    return ok(batch_view(btch))

@app.post("/v1/settlement-batches/<bid>/disburse")
def disburse_batch(bid):
    role, uid = auth()
    require_role(role, ["AssociationAdmin"])
    btch = get_or_404("batches", bid)
    if btch["status"] != "ACKNOWLEDGED":
        err("ERR_INVALID_STATE", "Batch is not ACKNOWLEDGED", 409)
    if btch["settlement_variant"] == "NET":
        creditor = DB["plans"][btch["creditor_plan_id"]]
        creditor["fees_receivable_balance_cents"] -= btch["fees_total_cents"]
        touch(creditor)
    btch["status"] = "DISBURSED"; touch(btch)
    return ok(batch_view(btch))

@app.post("/v1/settlement-batches/<bid>/reconcile")
def reconcile_batch(bid):
    role, uid = auth()
    require_role(role, ["AssociationAdmin"])
    btch = get_or_404("batches", bid)
    if btch["status"] != "DISBURSED":
        err("ERR_INVALID_STATE", "Batch is not DISBURSED", 409)
    for cid in btch["_swept_claim_ids"]:
        c = DB["claims"].get(cid)
        if c and c["status"] == "PAID":
            c["status"] = "SETTLED"; touch(c)
    btch["status"] = "RECONCILED"; touch(btch)
    return ok(batch_view(btch))

# ---------------- Eligibility Inquiries ----------------
@app.post("/v1/eligibility-inquiries")
def create_inquiry():
    role, uid = auth()
    require_role(role, ["HostPlanOperator"])
    b = body()
    req_fields(b, ["inquiring_plan_id", "home_plan_id", "member_number"])
    check_str(b, "inquiring_plan_id"); check_str(b, "home_plan_id"); check_str(b, "member_number")
    get_or_404("plans", b["inquiring_plan_id"])
    get_or_404("plans", b["home_plan_id"])
    require_plan_actor(role, uid, b["inquiring_plan_id"])
    r = new_common()
    r.update({"inquiring_plan_id": b["inquiring_plan_id"], "home_plan_id": b["home_plan_id"],
              "member_number": b["member_number"], "answer_eligibility_status": None,
              "status": "ROUTED"})
    DB["inquiries"][r["id"]] = r
    return ok(r, code=201)

@app.get("/v1/eligibility-inquiries/<iid>")
def get_inquiry(iid):
    role, uid = auth()
    return ok(get_or_404("inquiries", iid))

@app.get("/v1/eligibility-inquiries")
def list_inquiries():
    role, uid = auth()
    items = list(DB["inquiries"].values())
    for f in ("inquiring_plan_id", "home_plan_id", "member_number", "status"):
        v = request.args.get(f)
        if v is not None:
            items = [i for i in items if i.get(f) == v]
    return paginate(items)

@app.post("/v1/eligibility-inquiries/<iid>/answer")
def answer_inquiry(iid):
    role, uid = auth()
    require_role(role, ["HomePlanOperator"])
    inq = get_or_404("inquiries", iid)
    require_plan_actor(role, uid, inq["home_plan_id"])
    if inq["status"] != "ROUTED":
        err("ERR_INVALID_STATE", "Inquiry is not ROUTED", 409)
    m = next((m for m in DB["members"].values()
              if m["home_plan_id"] == inq["home_plan_id"]
              and m["member_number"] == inq["member_number"]), None)
    if m is None:
        err("ERR_MEMBER_NOT_FOUND", "No Member with the inquired member_number exists under the home plan", 404)
    inq["answer_eligibility_status"] = m["eligibility_status"]
    inq["status"] = "ANSWERED"; touch(inq)
    return ok(inq)

@app.post("/v1/eligibility-inquiries/<iid>/reject")
def reject_inquiry(iid):
    role, uid = auth()
    require_role(role, ["HomePlanOperator"])
    inq = get_or_404("inquiries", iid)
    require_plan_actor(role, uid, inq["home_plan_id"])
    if inq["status"] != "ROUTED":
        err("ERR_INVALID_STATE", "Inquiry is not ROUTED", 409)
    inq["status"] = "REJECTED"; touch(inq)
    return ok(inq)

# ---------------- Logical clock ----------------
@app.post("/v1/_clock/set_current_utc")
def set_clock():
    role, uid = auth()
    require_role(role, ["AssociationAdmin"])
    b = body()
    req_fields(b, ["current_utc"])
    v = b["current_utc"]
    if not isinstance(v, str):
        err("ERR_VALIDATION_FAILED", "current_utc must be an ISO 8601 string", 400)
    try:
        parsed = _parse_iso(v)
    except Exception:
        err("ERR_VALIDATION_FAILED", "current_utc must be an ISO 8601 instant", 400)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    clock_state["current_utc"] = parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return ok({"current_utc": clock_state["current_utc"]})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
