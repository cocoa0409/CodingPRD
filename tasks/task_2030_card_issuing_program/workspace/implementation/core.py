"""Core infrastructure: in-memory store, logical clock, envelope, auth, lazy transitions."""
import random
import re
import string
import uuid
from datetime import datetime, timezone, timedelta
from functools import wraps

from flask import request, jsonify

# ---------------------------------------------------------------------------
# Logical clock & in-memory store (starts empty on every boot — no seeding)
# ---------------------------------------------------------------------------

def _default_clock():
    return datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def _fresh_store():
    return {
        "clock": _default_clock(),
        "seq": 0,
        "programs": {},
        "bin_ranges": {},
        "vendors": {},
        "batches": {},
        "accounts": {},
        "cards": {},
        "tokens": {},
        "rules": {},
        "mandates": {},
        "acks": {},
        "events": {},
        "settlements": {},
        "campaigns": {},
        "jobs": {},
    }


STORE = _fresh_store()


def now():
    return STORE["clock"]


def next_seq():
    STORE["seq"] += 1
    return STORE["seq"]


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

def fmt_dt(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(dt.microsecond // 1000)


def parse_dt(value):
    if not isinstance(value, str):
        raise ValueError("not an ISO8601 string")
    s = value.strip()
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def parse_date(value):
    if not isinstance(value, str) or not DATE_RE.match(value):
        raise ValueError("not a YYYY-MM-DD date")
    return datetime.strptime(value, "%Y-%m-%d").date()


def add_months(dt, months):
    total = dt.year * 12 + (dt.month - 1) + months
    return total // 12, total % 12 + 1


# ---------------------------------------------------------------------------
# Errors & response envelope
# ---------------------------------------------------------------------------

class ApiError(Exception):
    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message


def _meta():
    rid = "req_" + "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
    return {"api_request_id": rid, "api_request_timestamp": fmt_dt(now())}


def ok(data, code=200):
    apply_lazy()
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), code


def ok_list(items):
    apply_lazy()
    page, pag = paginate(items)
    return jsonify({"meta": {**_meta(), **pag}, "response_type": "array", "data": page}), 200


def error_response(err):
    return jsonify({
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }), err.status


def paginate(items):
    raw_limit = request.args.get("limit", "10")
    raw_offset = request.args.get("offset", "0")
    try:
        limit = int(raw_limit)
        offset = int(raw_offset)
    except (TypeError, ValueError):
        raise ApiError("ERR_VALIDATION", 400, "limit/offset must be integers")
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    total = len(items)
    page = items[offset:offset + limit]
    return page, {"limit": limit, "offset": offset, "total_count": total,
                  "has_more": (offset + len(page)) < total}


# ---------------------------------------------------------------------------
# Auth (X-User-Role / X-User-ID headers)
# ---------------------------------------------------------------------------

ROLES = {"PlatformAdmin", "ProgramManager", "ComplianceOfficer",
         "OperationsAnalyst", "FinanceController", "CardholderOps"}


def current_role():
    return request.headers.get("X-User-Role")


def current_user_id():
    return request.headers.get("X-User-ID", "")


def require_roles(*allowed):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            role = current_role()
            if role not in ROLES:
                raise ApiError("ERR_UNAUTHENTICATED", 401,
                               "X-User-Role header missing or not a declared role")
            if role not in allowed:
                raise ApiError("ERR_UNAUTHORIZED", 403,
                               "role %s is not permitted for this endpoint" % role)
            return fn(*args, **kwargs)
        return wrapper
    return deco


# ---------------------------------------------------------------------------
# Request body helpers
# ---------------------------------------------------------------------------

def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_VALIDATION", 400, "request body must be a JSON object")
    return data


def req_field(data, name):
    if name not in data or data[name] is None:
        raise ApiError("ERR_VALIDATION", 400, "missing required field: %s" % name)
    return data[name]


def req_int(data, name, min_value=None):
    v = req_field(data, name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_VALIDATION", 400, "%s must be an integer" % name)
    if min_value is not None and v < min_value:
        raise ApiError("ERR_VALIDATION", 400, "%s must be >= %d" % (name, min_value))
    return v


def opt_int(data, name, default=None, min_value=None):
    if name not in data or data[name] is None:
        return default
    v = data[name]
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_VALIDATION", 400, "%s must be an integer" % name)
    if min_value is not None and v < min_value:
        raise ApiError("ERR_VALIDATION", 400, "%s must be >= %d" % (name, min_value))
    return v


def req_enum(data, name, allowed):
    v = req_field(data, name)
    if v not in allowed:
        raise ApiError("ERR_VALIDATION", 400, "%s must be one of %s" % (name, sorted(allowed)))
    return v


# ---------------------------------------------------------------------------
# Entity plumbing
# ---------------------------------------------------------------------------

def new_entity():
    ts = fmt_dt(now())
    return {"id": str(uuid.uuid4()), "created_at": ts, "updated_at": ts,
            "version": 1, "_seq": next_seq()}


def new_append_only():
    return {"id": str(uuid.uuid4()), "created_at": fmt_dt(now()), "_seq": next_seq()}


def touch(e):
    e["version"] = e.get("version", 0) + 1
    e["updated_at"] = fmt_dt(now())


def pub(e):
    return {k: v for k, v in e.items() if not k.startswith("_")}


def sort_created(items):
    return sorted(items, key=lambda e: (e["created_at"], e["_seq"]))


def get_or_404(coll, rid, label="resource"):
    e = STORE[coll].get(rid)
    if e is None:
        raise ApiError("ERR_NOT_FOUND", 404, "%s %s not found" % (label, rid))
    return e


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

NETWORKS = ("VISA", "MASTERCARD", "STAR", "PULSE")
PRODUCT_CLASSES = ("CONSUMER_PREPAID", "CORPORATE_FLEET", "DEBIT_CONSUMER", "COMMERCIAL_CREDIT")
TERMINATION_REASONS = ("VOLUNTARY", "NETWORK_DIRECTIVE", "PORTFOLIO_CONVERSION")
ACCOUNT_CLASSES = ("INDIVIDUAL", "BUSINESS", "FLEET_POOL")
FORM_FACTORS = ("PHYSICAL", "VIRTUAL")
CAPABILITY_FLAGS = ("EMV_CHIP", "CONTACTLESS", "MAGSTRIPE", "VIRTUAL", "DUAL_INTERFACE")
RULE_KINDS = ("VELOCITY", "MCC_ALLOW", "MCC_BLOCK", "GEO_BLOCK")
SEVERITIES = ("ADVISORY", "REQUIRED", "EMERGENCY")
CAMPAIGN_KINDS = ("EXPIRY_SWEEP", "COMPROMISE_BLAST", "NETWORK_MANDATE_REISSUE")

BASE_RATE_BP = {
    "VISA": {"QUALIFIED": 145, "MID_QUALIFIED": 185, "NON_QUALIFIED": 230},
    "MASTERCARD": {"QUALIFIED": 148, "MID_QUALIFIED": 188, "NON_QUALIFIED": 235},
    "STAR": {"QUALIFIED": 90, "MID_QUALIFIED": 130, "NON_QUALIFIED": 175},
    "PULSE": {"QUALIFIED": 85, "MID_QUALIFIED": 125, "NON_QUALIFIED": 170},
}
PER_ITEM_CENTS = {"VISA": 10, "MASTERCARD": 11, "STAR": 5, "PULSE": 5}
COMMERCIAL_UPLIFT_BP = 65
COMMERCIAL_CLASSES = ("COMMERCIAL_CREDIT", "CORPORATE_FLEET")
BLOCKED_MCC = {
    "VISA": ["7995", "6012"],
    "MASTERCARD": ["7995"],
    "STAR": [],
    "PULSE": [],
}
T1_SECONDS = 86400
T2_SECONDS = 172800

PIN_RE = re.compile(r"^[0-9]{4,12}$")
MCC_RE = re.compile(r"^[0-9]{4}$")
COUNTRY_RE = re.compile(r"^[A-Za-z]{2}$")
BIN_PREFIX_RE = re.compile(r"^([0-9]{6}|[0-9]{8})$")


# ---------------------------------------------------------------------------
# Derived fields
# ---------------------------------------------------------------------------

def account_of(card):
    return STORE["accounts"].get(card["account_id"])


def program_of_account(account):
    return STORE["programs"].get(account["program_id"])


def card_program(card):
    acct = account_of(card)
    return program_of_account(acct) if acct else None


def open_card_count(program_id):
    n = 0
    for card in STORE["cards"].values():
        acct = account_of(card)
        if acct and acct["program_id"] == program_id and \
                card["lifecycle_status"] in ("ISSUED", "ACTIVE", "SUSPENDED"):
            n += 1
    return n


def emv_capable(card):
    return card["form_factor"] == "PHYSICAL"


def expiry_threshold(card):
    y, m = add_months(datetime(card["expiry_year"], card["expiry_month"], 1), 1)
    return datetime(y, m, 1, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------

def qualification_tier(network, mcc, authorized_at, settled_at, chip):
    if mcc in BLOCKED_MCC.get(network, []):
        return "NON_QUALIFIED"
    gap = (settled_at - authorized_at).total_seconds()
    if gap > T2_SECONDS:
        return "NON_QUALIFIED"
    if not chip:
        return "NON_QUALIFIED"
    if gap <= T1_SECONDS and chip:
        return "QUALIFIED"
    return "MID_QUALIFIED"


def interchange_cents(amount_cents, network, tier, product_class):
    rate_bp = BASE_RATE_BP[network][tier]
    if product_class in COMMERCIAL_CLASSES:
        rate_bp += COMMERCIAL_UPLIFT_BP
    return (amount_cents * rate_bp) // 10000 + PER_ITEM_CENTS[network]


def matching_rules(card, kinds):
    acct = account_of(card)
    prog = program_of_account(acct) if acct else None
    out = []
    for r in STORE["rules"].values():
        if r["status"] != "ACTIVE" or r["rule_kind"] not in kinds:
            continue
        if r["subject_kind"] == "ACCOUNT" and acct and r["subject_ref"] == acct["id"]:
            out.append(r)
        elif r["subject_kind"] == "PROGRAM" and prog and r["subject_ref"] == prog["id"]:
            out.append(r)
    out.sort(key=lambda r: (r["priority_rank"], r["created_at"], r["_seq"]))
    return out


def approved_events_in_window(account_id, window_start, window_end):
    out = []
    for e in STORE["events"].values():
        if e["account_id"] != account_id or e["decision"] != "APPROVED":
            continue
        at = e["_authorized_at"]
        if window_start <= at <= window_end:
            out.append(e)
    return out


def select_campaign_cards(c):
    prog_id = c["program_id"]
    f = c.get("selection_filter") or {}
    lifecycle = f.get("lifecycle_in") or ["ACTIVE", "SUSPENDED", "ISSUED"]
    form = f.get("form_factor_in") or ["PHYSICAL", "VIRTUAL"]
    expiry_before = f.get("expiry_before")
    threshold = None
    if expiry_before:
        m = re.match(r"^(\d{4})-(\d{2})-\d{2}$", str(expiry_before))
        if m:
            threshold = int(m.group(1)) * 100 + int(m.group(2))
    out = []
    for card in STORE["cards"].values():
        acct = account_of(card)
        if not acct or acct["program_id"] != prog_id:
            continue
        if card["lifecycle_status"] not in lifecycle:
            continue
        if card["form_factor"] not in form:
            continue
        if threshold is not None and \
                card["expiry_year"] * 100 + card["expiry_month"] >= threshold:
            continue
        out.append(card)
    out.sort(key=lambda x: (x["expiry_year"], x["expiry_month"], x["created_at"], x["_seq"]))
    return out


# ---------------------------------------------------------------------------
# Card minting (shared by issuance and reissue campaigns)
# ---------------------------------------------------------------------------

def create_card(account, bin_range, expiry_month, expiry_year, form_factor,
                replaced_from=None, campaign_id=None):
    card = new_entity()
    pan_token = "".join(random.choices(string.digits, k=16))
    card.update({
        "account_id": account["id"],
        "bin_range_id": bin_range["id"],
        "pan_token": pan_token,
        "last4": pan_token[-4:],
        "expiry_month": expiry_month,
        "expiry_year": expiry_year,
        "form_factor": form_factor,
        "lifecycle_status": "ISSUED",
        "pin_status": "UNSET",
        "replaced_by_card_id": None,
        "replaced_from_card_id": replaced_from,
        "reissue_campaign_id": campaign_id,
        "_pin": None,
        "_compromised_at": None,
    })
    STORE["cards"][card["id"]] = card
    bin_range["pans_allocated"] += 1
    if bin_range["pans_allocated"] >= bin_range["range_size"] and \
            bin_range["status"] == "ACTIVE":
        bin_range["status"] = "DEPLETED"
    touch(bin_range)
    mint_activation_token(card)
    return card


def mint_activation_token(card):
    tok = new_entity()
    issued = now()
    expires = issued + timedelta(hours=72)
    tok.update({
        "card_id": card["id"],
        "token_value": "act_" + uuid.uuid4().hex,
        "issued_at": fmt_dt(issued),
        "expires_at": fmt_dt(expires),
        "consumed_at": None,
        "status": "PENDING",
        "_expires_at": expires,
    })
    STORE["tokens"][tok["id"]] = tok
    return tok


# ---------------------------------------------------------------------------
# Lazy (clock-driven) transitions
# ---------------------------------------------------------------------------

def execute_campaign(c):
    c["status"] = "EXECUTING"
    touch(c)
    selected = [x for x in select_campaign_cards(c)
                if x["lifecycle_status"] in ("ISSUED", "ACTIVE", "SUSPENDED")]
    if not selected:
        c["status"] = "FAILED"
        c["empty_execution_reason"] = "NO_MATCHING_CARDS"
        touch(c)
        return
    yy, mm = add_months(now(), 36)
    for src in selected:
        acct = STORE["accounts"].get(src["account_id"])
        br = STORE["bin_ranges"].get(src["bin_range_id"])
        if acct is None or br is None:
            continue
        succ = create_card(acct, br, mm, yy, src["form_factor"],
                           replaced_from=src["id"], campaign_id=c["id"])
        src["lifecycle_status"] = "REPLACED"
        src["replaced_by_card_id"] = succ["id"]
        touch(src)
    n = len(selected)
    if c["campaign_kind"] == "COMPROMISE_BLAST":
        fee = int(c.get("targeted_unit_fee_cents") or 0) * n
    elif c["campaign_kind"] == "EXPIRY_SWEEP":
        gross = int(c.get("blanket_unit_fee_cents") or 0) * n
        fee = gross - (gross * 4) // 100
    else:
        fee = 0
    c["_booked_fee_cents"] = fee
    c["_completed_at"] = now()
    c["status"] = "COMPLETED"
    touch(c)


def execute_job(j):
    j["status"] = "EXECUTING"
    touch(j)
    src = STORE["programs"].get(j["source_program_id"])
    tgt = STORE["programs"].get(j["target_program_id"])
    movable = [a for a in STORE["accounts"].values()
               if src and a["program_id"] == src["id"]
               and a["lifecycle_status"] in ("OPEN", "SUSPENDED")]
    if not src or src["posture"] != "SUNSETTING" or not tgt or \
            tgt["posture"] != "LIVE" or len(movable) == 0:
        j["status"] = "FAILED"
        touch(j)
        return
    for a in movable:
        a["program_id"] = tgt["id"]
        touch(a)
        j["accounts_converted"] += 1
    j["status"] = "COMPLETED"
    touch(j)


def apply_lazy():
    ts = now()
    for br in STORE["bin_ranges"].values():
        if br["status"] == "PENDING_ACTIVATION":
            prog = STORE["programs"].get(br["program_id"])
            if prog and ts >= br["_effective_from"] and \
                    prog["posture"] in ("DRAFT", "LIVE"):
                br["status"] = "ACTIVE"
                touch(br)
    for m in STORE["mandates"].values():
        if m["status"] == "ANNOUNCED" and ts >= m["_effective_at"]:
            m["status"] = "EFFECTIVE"
            touch(m)
            for ack in STORE["acks"].values():
                if ack["mandate_id"] == m["id"] and ack["status"] == "DRAFT":
                    note = "AUTO-RETURNED: mandate went effective"
                    prev = ack.get("implementation_notes") or ""
                    ack["implementation_notes"] = (prev + " " + note) if prev else note
                    ack["status"] = "RETURNED"
                    touch(ack)
    for c in STORE["campaigns"].values():
        if c["status"] == "SCHEDULED" and ts >= c["_scheduled_for"]:
            execute_campaign(c)
    for j in STORE["jobs"].values():
        if j["status"] == "SCHEDULED" and ts >= j["_execution_at"]:
            execute_job(j)
    for card in STORE["cards"].values():
        if card["lifecycle_status"] == "ACTIVE" and ts >= expiry_threshold(card):
            card["lifecycle_status"] = "EXPIRED"
            touch(card)
            br = STORE["bin_ranges"].get(card["bin_range_id"])
            if br is not None:
                br["pans_allocated"] = max(0, br["pans_allocated"] - 1)
                touch(br)
    for tok in STORE["tokens"].values():
        if tok["status"] == "PENDING" and ts > tok["_expires_at"]:
            tok["status"] = "EXPIRED"
            touch(tok)


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def ser_program(p):
    d = pub(p)
    d["open_card_count"] = open_card_count(p["id"])
    return d


def ser_bin_range(br):
    d = pub(br)
    d["pans_available"] = br["range_size"] - br["pans_allocated"]
    return d


def ser_generic(e):
    return pub(e)
