"""Healthcare Claims Clearinghouse API — in-memory Flask implementation.

Contract: workspace/PRD.md + SCAFFOLD.yaml for
task_3102_healthcare_claims_clearinghouse_routing_payer_enrollment.

Storage is in-memory only (module-level dicts). The logical clock starts at
2026-09-01T00:00:00Z and is advanced only via POST /clearinghouse/_clock/set_current_utc.
"""

import math
import re
import uuid
from datetime import datetime, timedelta, timezone

from flask import Flask, jsonify, request

app = Flask(__name__)

# =============================================================================
# Logical clock
# =============================================================================

DEFAULT_CLOCK_STR = "2026-09-01T00:00:00Z"
_clock = {"now": datetime(2026, 9, 1, tzinfo=timezone.utc)}


def now():
    return _clock["now"]


def parse_instant(value):
    """Parse an ISO 8601 instant into an aware datetime (UTC)."""
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc)
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_instant(dt):
    """Render an aware UTC datetime as ISO 8601 with exactly 3 fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    return f"{base}.{dt.microsecond // 1000:03d}Z"


def business_day_add(instant, days):
    """Add N business days, skipping Saturdays and Sundays."""
    result = instant
    remaining = days
    while remaining > 0:
        result = result + timedelta(days=1)
        if result.weekday() < 5:  # Mon=0 .. Fri=4
            remaining -= 1
    return result


# =============================================================================
# In-memory store
# =============================================================================

db = {
    "providers": {},
    "credentials": {},
    "payers": {},
    "pricing_tiers": {},
    "edit_rules": {},
    "enrollments": {},
    "claims": {},
    "remittances": {},
    "posting_files": {},
    "inquiries": {},
    "outages": {},
    "notifications": {},
    "invoices": {},
}


def new_id():
    return str(uuid.uuid4())


_seq = {"n": 0}


def next_seq():
    _seq["n"] += 1
    return _seq["n"]


def stamp_new(record):
    ts = fmt_instant(now())
    record["id"] = new_id()
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    record["_seq"] = next_seq()
    return record


def touch(record):
    record["updated_at"] = fmt_instant(now())
    record["version"] = record.get("version", 1) + 1


# =============================================================================
# Errors and envelope
# =============================================================================

class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def _meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex[:24],
        "api_request_timestamp": fmt_instant(now()),
    }


def ok_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(items):
    args = request.args
    try:
        limit = int(args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    total = len(items)
    page = items[offset:offset + limit]
    meta = _meta()
    meta.update({
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    })
    return jsonify({"meta": meta, "response_type": "array", "data": page}), 200


@app.errorhandler(ApiError)
def handle_api_error(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


@app.errorhandler(404)
def handle_404(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "route not found"},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "method not allowed"},
    }
    return jsonify(body), 405


def err_missing_header(msg="missing or malformed user context header"):
    return ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400, msg)


def err_forbidden(msg="role not permitted for this endpoint"):
    return ApiError("ERR_INSUFFICIENT_PERMISSIONS", 403, msg)


def err_not_found(resource):
    return ApiError(f"ERR_{resource}_NOT_FOUND", 404, f"{resource.lower().replace('_', ' ')} not found")


def err_invalid_request(msg):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def err_invalid_state(msg):
    return ApiError("ERR_INVALID_STATE", 409, msg)


# =============================================================================
# Auth / RBAC
# =============================================================================

ROLES = {"ClearinghouseOps", "ProviderAdmin", "PayerOperator"}

# Each entry: (method, regex-ish route template) -> allowed roles.
# Matched against request.path via flask's url rule in dispatch; we instead
# key permissions per handler via a decorator argument.


def get_context(require_payer_code=False):
    """Validate X-User-ID / X-User-Role headers. Returns (role, user_id)."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or role not in ROLES:
        raise err_missing_header("X-User-Role header missing or malformed")
    if not user_id or not isinstance(user_id, str):
        raise err_missing_header("X-User-ID header missing or malformed")
    if role == "PayerOperator" and require_payer_code:
        code = request.headers.get("X-Payer-Code")
        if not code:
            raise err_missing_header("X-Payer-Code header required for PayerOperator")
    return role, user_id


def require_roles(*roles, payer_code_required=False):
    role, user_id = get_context(require_payer_code=payer_code_required)
    if role not in roles:
        raise err_forbidden()
    return role, user_id


def check_payer_code(payer):
    """PayerOperator actions on payer-owned surfaces: X-Payer-Code must match."""
    code = request.headers.get("X-Payer-Code")
    if not code:
        raise err_missing_header("X-Payer-Code header required for PayerOperator")
    if code != payer["payer_id_code"]:
        raise ApiError("ERR_PAYER_CODE_MISMATCH", 403, "X-Payer-Code does not match owning payer")


def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err_invalid_request("request body must be a JSON object")
    return data


# =============================================================================
# Serializers
# =============================================================================

def ser_provider(p):
    return {
        "id": p["id"],
        "legal_name": p["legal_name"],
        "tax_identification_number": p["tax_identification_number"],
        "national_provider_identifier": p["national_provider_identifier"],
        "billing_model": p["billing_model"],
        "volume_tier_code": p["volume_tier_code"],
        "status": p["status"],
        "activated_at": p.get("activated_at"),
        "trailing_billable_units_3m": p.get("trailing_billable_units_3m", 0),
        "account_balance_cents": p.get("account_balance_cents", 0),
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def ser_credential(c):
    return {
        "id": c["id"],
        "provider_id": c["provider_id"],
        "submitter_id": c["submitter_id"],
        "trading_partner_agreement_ref": c["trading_partner_agreement_ref"],
        "effective_at": c["effective_at"],
        "expires_at": c["expires_at"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def ser_payer(p):
    return {
        "id": p["id"],
        "payer_id_code": p["payer_id_code"],
        "display_name": p["display_name"],
        "claims_lead_time_days": p["claims_lead_time_days"],
        "remittance_lead_time_days": p["remittance_lead_time_days"],
        "eligibility_lead_time_seconds": p["eligibility_lead_time_seconds"],
        "pricing_model": p["pricing_model"],
        "shared_provider_pct": p.get("shared_provider_pct"),
        "connectivity_status": p["connectivity_status"],
        "monthly_minimum_cents": p.get("monthly_minimum_cents", 0),
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def ser_tier(t):
    return {
        "id": t["id"],
        "payer_id": t["payer_id"],
        "applies_to": t["applies_to"],
        "volume_floor": t["volume_floor"],
        "volume_ceiling": t.get("volume_ceiling"),
        "rate_cents": t["rate_cents"],
        "created_at": t["created_at"],
    }


def ser_rule(r):
    return {
        "id": r["id"],
        "payer_id": r["payer_id"],
        "rule_code": r["rule_code"],
        "applies_to": r["applies_to"],
        "severity": r["severity"],
        "expression": r["expression"],
        "effective_from": r["effective_from"],
        "effective_to": r.get("effective_to"),
        "created_at": r["created_at"],
    }


def ser_enrollment(e):
    return {
        "id": e["id"],
        "provider_id": e["provider_id"],
        "payer_id": e["payer_id"],
        "transaction_type": e["transaction_type"],
        "status": e["status"],
        "submitted_at": e.get("submitted_at"),
        "payer_decision_due_at": e.get("payer_decision_due_at"),
        "payer_decision_due_at_calendar": e.get("payer_decision_due_at_calendar"),
        "approved_at": e.get("approved_at"),
        "rejection_reason": e.get("rejection_reason"),
        "decision_round": e.get("decision_round", 0),
        "late_decision": e.get("late_decision", False),
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def ser_claim(c):
    return {
        "id": c["id"],
        "provider_id": c["provider_id"],
        "payer_id": c["payer_id"],
        "submitter_credential_id": c["submitter_credential_id"],
        "patient_control_number": c["patient_control_number"],
        "idempotency_key": c["idempotency_key"],
        "service_date": c["service_date"],
        "total_charge_cents": c["total_charge_cents"],
        "diagnosis_codes": c["diagnosis_codes"],
        "rendering_npi": c["rendering_npi"],
        "subscriber_id": c["subscriber_id"],
        "lines": c["lines"],
        "acceptance_status": c["acceptance_status"],
        "adjudication_status": c["adjudication_status"],
        "edit_failures": c.get("edit_failures", []),
        "forwarded_at": c.get("forwarded_at"),
        "payer_response_due_at": c.get("payer_response_due_at"),
        "payer_response_due_at_calendar": c.get("payer_response_due_at_calendar"),
        "rejection_payload": c.get("rejection_payload"),
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def ser_remittance(r):
    return {
        "id": r["id"],
        "claim_id": r["claim_id"],
        "payer_id": r["payer_id"],
        "check_number": r["check_number"],
        "paid_amount_cents": r["paid_amount_cents"],
        "adjustment_amount_cents": r["adjustment_amount_cents"],
        "patient_responsibility_cents": r["patient_responsibility_cents"],
        "denial_reason_codes": r["denial_reason_codes"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_posting_file(f):
    return {
        "id": f["id"],
        "remittance_advice_id": f["remittance_advice_id"],
        "generated_at": f["generated_at"],
        "line_count": f["line_count"],
        "total_posted_cents": f["total_posted_cents"],
        "status": f["status"],
        "created_at": f["created_at"],
    }


def ser_inquiry(i):
    return {
        "id": i["id"],
        "provider_id": i["provider_id"],
        "payer_id": i["payer_id"],
        "subscriber_id": i["subscriber_id"],
        "service_type_code": i["service_type_code"],
        "idempotency_key": i["idempotency_key"],
        "status": i["status"],
        "requested_at": i["requested_at"],
        "deadline_at": i.get("deadline_at"),
        "responded_at": i.get("responded_at"),
        "benefit_summary": i.get("benefit_summary"),
        "created_at": i["created_at"],
        "updated_at": i["updated_at"],
        "version": i["version"],
    }


def ser_outage(o):
    return {
        "id": o["id"],
        "payer_id": o["payer_id"],
        "started_at": o["started_at"],
        "ended_at": o.get("ended_at"),
        "severity": o["severity"],
        "affects_transaction_types": o["affects_transaction_types"],
        "status": o["status"],
        "notified_provider_ids": o.get("notified_provider_ids", []),
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


def ser_invoice(v):
    return {
        "id": v["id"],
        "provider_id": v["provider_id"],
        "period_yyyy_mm": v["period_yyyy_mm"],
        "claim_units": v["claim_units"],
        "eligibility_units": v["eligibility_units"],
        "remittance_units": v["remittance_units"],
        "billable_units": v["billable_units"],
        "gross_fee_cents": v["gross_fee_cents"],
        "monthly_minimum_applied_cents": v["monthly_minimum_applied_cents"],
        "amount_due_cents": v["amount_due_cents"],
        "status": v["status"],
        "created_at": v["created_at"],
        "updated_at": v["updated_at"],
        "version": v["version"],
    }


def ser_notification(n):
    return {
        "id": n["id"],
        "outage_id": n["outage_id"],
        "provider_id": n["provider_id"],
        "sent_at": n["sent_at"],
        "channel": n["channel"],
        "payload_summary": n["payload_summary"],
        "created_at": n["created_at"],
    }


# =============================================================================
# Lookups / shared helpers
# =============================================================================

def get_provider_or_404(provider_id):
    p = db["providers"].get(provider_id)
    if p is None:
        raise err_not_found("PROVIDER")
    return p


def get_payer_or_404(payer_id):
    p = db["payers"].get(payer_id)
    if p is None:
        raise err_not_found("PAYER")
    return p


def get_credential_or_404(credential_id):
    c = db["credentials"].get(credential_id)
    if c is None:
        raise err_not_found("CREDENTIAL")
    return c


def get_enrollment_or_404(enrollment_id):
    e = db["enrollments"].get(enrollment_id)
    if e is None:
        raise err_not_found("ENROLLMENT")
    return e


def get_claim_or_404(claim_id):
    c = db["claims"].get(claim_id)
    if c is None:
        raise err_not_found("CLAIM")
    return c


def get_remittance_or_404(remittance_id):
    r = db["remittances"].get(remittance_id)
    if r is None:
        raise err_not_found("REMITTANCE")
    return r


def get_posting_file_or_404(pf_id):
    f = db["posting_files"].get(pf_id)
    if f is None:
        raise err_not_found("POSTING_FILE")
    return f


def get_inquiry_or_404(inquiry_id):
    i = db["inquiries"].get(inquiry_id)
    if i is None:
        raise err_not_found("INQUIRY")
    return i


def get_outage_or_404(outage_id):
    o = db["outages"].get(outage_id)
    if o is None:
        raise err_not_found("OUTAGE")
    return o


def get_invoice_or_404(invoice_id):
    v = db["invoices"].get(invoice_id)
    if v is None:
        raise err_not_found("USAGE_INVOICE")
    return v


def get_notification_or_404(nid):
    n = db["notifications"].get(nid)
    if n is None:
        raise ApiError("ERR_NOTIFICATION_NOT_FOUND", 404, "notification not found")
    return n


TRANSACTION_TYPES = {"CLAIMS_837", "REMITTANCE_835", "ELIGIBILITY_270"}


def payer_posture_for(payer_id, transaction_type):
    """ONLINE | DEGRADED | OFFLINE for one (payer, transaction_type)."""
    worst = "ONLINE"
    for o in db["outages"].values():
        if o["payer_id"] != payer_id or o["status"] != "ACTIVE":
            continue
        if transaction_type not in o["affects_transaction_types"]:
            continue
        if o["severity"] == "FULL":
            return "OFFLINE"
        worst = "DEGRADED"
    return worst


def recompute_connectivity(payer):
    posture_order = {"OFFLINE": 2, "DEGRADED": 1, "ONLINE": 0}
    worst = "ONLINE"
    for tt in TRANSACTION_TYPES:
        posture = payer_posture_for(payer["id"], tt)
        if posture_order[posture] > posture_order[worst]:
            worst = posture
    if payer["connectivity_status"] != worst:
        payer["connectivity_status"] = worst
        touch(payer)


def lead_days_for(payer, transaction_type):
    if transaction_type == "CLAIMS_837":
        return payer["claims_lead_time_days"]
    if transaction_type == "REMITTANCE_835":
        return payer["remittance_lead_time_days"]
    # ELIGIBILITY_270: ceil seconds / 86400
    return math.ceil(payer["eligibility_lead_time_seconds"] / 86400)


def enrollment_due_dates(submitted_dt, payer, transaction_type):
    days = lead_days_for(payer, transaction_type)
    business = business_day_add(submitted_dt, days)
    calendar = submitted_dt + timedelta(days=days)
    return fmt_instant(business), fmt_instant(calendar)


def luhn_npi_valid(npi):
    """NPI Luhn check: prefix '80840' then standard Luhn mod-10."""
    if not isinstance(npi, str) or not re.fullmatch(r"[0-9]{10}", npi):
        return False
    s = "80840" + npi
    total = 0
    for i, ch in enumerate(reversed(s)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def find_approved_enrollment(provider_id, payer_id, transaction_type):
    for e in db["enrollments"].values():
        if (e["provider_id"] == provider_id and e["payer_id"] == payer_id
                and e["transaction_type"] == transaction_type and e["status"] == "APPROVED"):
            return e
    return None


def current_period(now_dt):
    return f"{now_dt.year:04d}-{now_dt.month:02d}"


def find_open_invoice(provider_id, period):
    for inv in db["invoices"].values():
        if (inv["provider_id"] == provider_id and inv["period_yyyy_mm"] == period
                and inv["status"] == "OPEN"):
            return inv
    return None


def record_meter_event(provider_id, kind, delta, payer):
    """Record a billable event (+1 or -1) in the global meter log.

    Invoice counters are derived from this log: an OPEN invoice for period P
    shows the net count of events whose period == P, so events that occurred
    before the invoice was opened are still counted, and voids unwind cleanly.
    """
    db.setdefault("_meter_events", []).append({
        "provider_id": provider_id,
        "payer_id": payer["id"],
        "kind": kind,
        "delta": delta,
        "period": current_period(now()),
    })


def _meter_counts(provider_id, period):
    """Net unit counts per kind for a provider in a period, from the meter log."""
    counts = {"claim": 0, "eligibility": 0, "remittance": 0}
    for ev in db.get("_meter_events", []):
        if ev["provider_id"] == provider_id and ev["period"] == period:
            counts[ev["kind"]] += ev["delta"]
    return counts


def _meter_events_for(provider_id, period):
    """Per-(kind, payer) net billable units (provider/shared payers only)."""
    per_kind_payer = {}
    for ev in db.get("_meter_events", []):
        if ev["provider_id"] != provider_id or ev["period"] != period:
            continue
        payer = db["payers"].get(ev["payer_id"])
        if payer is None or payer["pricing_model"] not in ("PROVIDER_FUNDED", "SHARED"):
            continue
        key = (ev["kind"], ev["payer_id"])
        per_kind_payer[key] = per_kind_payer.get(key, 0) + ev["delta"]
    return per_kind_payer


def sync_invoice_counters(inv):
    """For OPEN invoices, derive live counters from the meter log."""
    if inv["status"] != "OPEN":
        return
    counts = _meter_counts(inv["provider_id"], inv["period_yyyy_mm"])
    inv["claim_units"] = counts["claim"]
    inv["eligibility_units"] = counts["eligibility"]
    inv["remittance_units"] = counts["remittance"]
    billable = 0
    for (_kind, _pid), units in _meter_events_for(inv["provider_id"], inv["period_yyyy_mm"]).items():
        billable += units
    inv["billable_units"] = billable


def round_half_up(value):
    """Round a Decimal-like numeric to the nearest integer, halves away from zero."""
    from decimal import Decimal, ROUND_HALF_UP
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# =============================================================================
# Edit-rule expression evaluation
# =============================================================================

def eval_rule_expression(expression, claim):
    """Evaluate a declarative predicate over claim fields.

    Supported forms:
      - '<field>.nonempty'  -> field present and non-empty (list or string)
      - '<a> == <b>'        -> field equality; sides may be dotted claim fields
    Unknown expressions evaluate to True (pass).
    """
    expr = (expression or "").strip()
    if not expr:
        return True
    if expr.endswith(".nonempty"):
        field = expr[: -len(".nonempty")].strip()
        value = claim.get(field)
        if value is None:
            return False
        if isinstance(value, (list, str, dict)):
            return len(value) > 0
        return True
    if "==" in expr:
        left, right = [p.strip() for p in expr.split("==", 1)]
        return claim.get(left) == claim.get(right)
    if "!=" in expr:
        left, right = [p.strip() for p in expr.split("!=", 1)]
        return claim.get(left) != claim.get(right)
    return True


def run_edit_rules(claim, payer):
    """Populate claim.edit_failures from the payer's in-force rules."""
    failures = []
    current = now()
    rules = [r for r in db["edit_rules"].values() if r["payer_id"] == payer["id"]]
    applicable = []
    for r in rules:
        eff_from = parse_instant(r["effective_from"])
        eff_to = parse_instant(r["effective_to"]) if r.get("effective_to") else None
        if eff_from is not None and eff_from <= current and (eff_to is None or current < eff_to):
            applicable.append(r)
    for r in applicable:
        if not eval_rule_expression(r["expression"], claim):
            failures.append({
                "rule_code": r["rule_code"],
                "severity": r["severity"],
                "message": f"claim failed payer edit rule {r['rule_code']}",
                "_created_at": r["created_at"],
            })
    failures.sort(key=lambda f: (f["rule_code"], f["_created_at"]))
    for f in failures:
        f.pop("_created_at", None)
    return failures


# =============================================================================
# Time-driven transitions (triggered by clock advancement)
# =============================================================================

def apply_time_driven_transitions():
    current = now()
    # Credential activation at effective_at.
    for c in db["credentials"].values():
        if c["status"] == "PENDING_ACTIVATION":
            eff = parse_instant(c["effective_at"])
            if eff is not None and current >= eff:
                c["status"] = "ACTIVE"
                touch(c)
    # Eligibility timeouts.
    for i in db["inquiries"].values():
        if i["status"] == "PENDING" and i.get("deadline_at"):
            deadline = parse_instant(i["deadline_at"])
            if deadline is not None and current > deadline:
                i["status"] = "TIMED_OUT"
                touch(i)
    # Enrollment handoff SUBMITTED / RE_SUBMITTED -> PAYER_REVIEW when payer reachable.
    for e in db["enrollments"].values():
        if e["status"] in ("SUBMITTED", "RE_SUBMITTED"):
            payer = db["payers"].get(e["payer_id"])
            if payer and payer_posture_for(payer["id"], e["transaction_type"]) != "OFFLINE":
                e["status"] = "PAYER_REVIEW"
                touch(e)


# =============================================================================
# Test-driving endpoints
# =============================================================================

@app.post("/clearinghouse/_clock/set_current_utc")
def set_current_utc():
    require_roles("ClearinghouseOps")
    data = body()
    new_now = parse_instant(data.get("current_utc"))
    if new_now is None:
        raise err_invalid_request("current_utc must be an ISO 8601 instant")
    _clock["now"] = new_now
    apply_time_driven_transitions()
    return ok_object({})


@app.post("/clearinghouse/_enrollments/<enrollment_id>/advance-to-review")
def advance_enrollment_to_review(enrollment_id):
    require_roles("ClearinghouseOps")
    e = get_enrollment_or_404(enrollment_id)
    if e["status"] in ("SUBMITTED", "RE_SUBMITTED"):
        payer = get_payer_or_404(e["payer_id"])
        if payer_posture_for(payer["id"], e["transaction_type"]) == "OFFLINE":
            raise ApiError("ERR_PAYER_OFFLINE", 409, "payer is OFFLINE for this transaction type")
        e["status"] = "PAYER_REVIEW"
        touch(e)
    elif e["status"] != "PAYER_REVIEW":
        raise err_invalid_state("enrollment is not in a submittable state")
    return ok_object(ser_enrollment(e))


# =============================================================================
# Providers
# =============================================================================

TIN_RE = re.compile(r"^[0-9]{9}$")
PAYER_CODE_RE = re.compile(r"^[A-Z0-9]{5}$")
PERIOD_RE = re.compile(r"^[0-9]{4}-(0[1-9]|1[0-2])$")
BILLING_MODELS = {"PROVIDER_FUNDED", "PAYER_FUNDED", "HYBRID"}
PRICING_MODELS = {"PAYER_FUNDED", "PROVIDER_FUNDED", "SHARED"}


@app.post("/clearinghouse/providers")
def create_provider():
    require_roles("ClearinghouseOps")
    data = body()
    legal_name = data.get("legal_name")
    tin = data.get("tax_identification_number")
    npi = data.get("national_provider_identifier")
    billing_model = data.get("billing_model")
    if not isinstance(legal_name, str) or not legal_name:
        raise err_invalid_request("legal_name is required")
    if not isinstance(tin, str) or not TIN_RE.fullmatch(tin):
        raise err_invalid_request("tax_identification_number must be exactly 9 digits")
    if not isinstance(npi, str) or not re.fullmatch(r"[0-9]{10}", npi) or not luhn_npi_valid(npi):
        raise err_invalid_request("national_provider_identifier must be 10 digits and Luhn-valid")
    if billing_model not in BILLING_MODELS:
        raise err_invalid_request("billing_model must be PROVIDER_FUNDED, PAYER_FUNDED, or HYBRID")
    for p in db["providers"].values():
        if p["tax_identification_number"] == tin:
            raise err_invalid_request("tax_identification_number must be unique")
        if p["national_provider_identifier"] == npi:
            raise err_invalid_request("national_provider_identifier must be unique")
    p = stamp_new({
        "legal_name": legal_name,
        "tax_identification_number": tin,
        "national_provider_identifier": npi,
        "billing_model": billing_model,
        "volume_tier_code": "TIER_1",
        "status": "ONBOARDING",
        "activated_at": None,
        "trailing_billable_units_3m": 0,
        "account_balance_cents": 0,
    })
    db["providers"][p["id"]] = p
    return ok_object(ser_provider(p), status=201)


def _apply_filters(items, filters):
    out = items
    for key, value in filters.items():
        if value is not None:
            out = [it for it in out if str(it.get(key)) == value]
    return out


def _sorted_by_created(items):
    return sorted(items, key=lambda it: (it["created_at"], it.get("_seq", 0)))


@app.get("/clearinghouse/providers")
def list_providers():
    role, user_id = require_roles("ClearinghouseOps", "ProviderAdmin", "PayerOperator")
    items = list(db["providers"].values())
    if role == "ProviderAdmin":
        items = [p for p in items if p["id"] == user_id]
    items = _apply_filters(items, {
        "status": request.args.get("status"),
        "billing_model": request.args.get("billing_model"),
    })
    return ok_list([ser_provider(p) for p in _sorted_by_created(items)])


@app.get("/clearinghouse/providers/<provider_id>")
def get_provider(provider_id):
    require_roles("ClearinghouseOps", "ProviderAdmin", "PayerOperator")
    return ok_object(ser_provider(get_provider_or_404(provider_id)))


@app.post("/clearinghouse/providers/<provider_id>/activate")
def activate_provider(provider_id):
    require_roles("ClearinghouseOps")
    p = get_provider_or_404(provider_id)
    if p["status"] != "ONBOARDING":
        raise err_invalid_state("provider is not ONBOARDING")
    has_active_cred = any(
        c["provider_id"] == provider_id and c["status"] in ("ACTIVE", "PENDING_ACTIVATION")
        for c in db["credentials"].values()
    )
    if not has_active_cred:
        raise err_invalid_state("provider has no ACTIVE submitter credential")
    if not TIN_RE.fullmatch(p["tax_identification_number"]) or not luhn_npi_valid(p["national_provider_identifier"]):
        raise err_invalid_request("provider TIN/NPI no longer pass format checks")
    p["status"] = "ACTIVE"
    p["activated_at"] = fmt_instant(now())
    touch(p)
    return ok_object(ser_provider(p))


@app.post("/clearinghouse/providers/<provider_id>/suspend")
def suspend_provider(provider_id):
    require_roles("ClearinghouseOps")
    p = get_provider_or_404(provider_id)
    if p["status"] != "ACTIVE":
        raise err_invalid_state("provider is not ACTIVE")
    p["status"] = "SUSPENDED"
    touch(p)
    # Cascade: cancel in-flight enrollments.
    for e in db["enrollments"].values():
        if e["provider_id"] == provider_id and e["status"] in ("SUBMITTED", "PAYER_REVIEW"):
            e["status"] = "CANCELLED"
            e["rejection_reason"] = "PROVIDER_SUSPENDED"
            touch(e)
    # Cascade: time out pending eligibility inquiries.
    for i in db["inquiries"].values():
        if i["provider_id"] == provider_id and i["status"] == "PENDING":
            i["status"] = "TIMED_OUT"
            touch(i)
    return ok_object(ser_provider(p))


REINSTATE_THRESHOLD = 0


@app.post("/clearinghouse/providers/<provider_id>/reinstate")
def reinstate_provider(provider_id):
    require_roles("ClearinghouseOps")
    p = get_provider_or_404(provider_id)
    if p["status"] != "SUSPENDED":
        raise err_invalid_state("provider is not SUSPENDED")
    if p.get("account_balance_cents", 0) > REINSTATE_THRESHOLD:
        raise err_invalid_state("account balance exceeds reinstatement threshold")
    p["status"] = "ACTIVE"
    touch(p)
    return ok_object(ser_provider(p))


@app.post("/clearinghouse/providers/<provider_id>/terminate")
def terminate_provider(provider_id):
    require_roles("ClearinghouseOps")
    p = get_provider_or_404(provider_id)
    if p["status"] != "ACTIVE":
        raise err_invalid_state("provider is not ACTIVE")
    for inv in db["invoices"].values():
        if inv["provider_id"] == provider_id and inv["status"] in ("OPEN", "FINALIZED"):
            raise err_invalid_state("provider has OPEN or FINALIZED usage invoices")
    for c in db["claims"].values():
        if c["provider_id"] == provider_id and c["acceptance_status"] in (
                "RECEIVED", "VALIDATING", "ACCEPTED", "FORWARDED"):
            raise err_invalid_state("provider has in-flight claims")
    p["status"] = "TERMINATED"
    touch(p)
    for cred in db["credentials"].values():
        if cred["provider_id"] == provider_id and cred["status"] != "REVOKED":
            cred["status"] = "REVOKED"
            touch(cred)
    for e in db["enrollments"].values():
        if e["provider_id"] == provider_id and e["status"] == "APPROVED":
            e["status"] = "CANCELLED"
            touch(e)
    return ok_object(ser_provider(p))


# =============================================================================
# Submitter credentials
# =============================================================================

@app.post("/clearinghouse/providers/<provider_id>/credentials")
def create_credential(provider_id):
    require_roles("ProviderAdmin")
    get_provider_or_404(provider_id)
    data = body()
    submitter_id = data.get("submitter_id")
    agreement = data.get("trading_partner_agreement_ref", "")
    effective_at = data.get("effective_at")
    expires_at = data.get("expires_at")
    if not isinstance(submitter_id, str) or not submitter_id:
        raise err_invalid_request("submitter_id is required")
    eff = parse_instant(effective_at)
    exp = parse_instant(expires_at)
    if eff is None or exp is None:
        raise err_invalid_request("effective_at and expires_at must be ISO 8601 instants")
    for c in db["credentials"].values():
        if (c["provider_id"] == provider_id and c["submitter_id"] == submitter_id
                and c["status"] != "REVOKED"):
            raise err_invalid_request("submitter_id must be unique per provider among non-REVOKED credentials")
    c = stamp_new({
        "provider_id": provider_id,
        "submitter_id": submitter_id,
        "trading_partner_agreement_ref": agreement if isinstance(agreement, str) else "",
        "effective_at": fmt_instant(eff),
        "expires_at": fmt_instant(exp),
        "status": "DRAFT",
    })
    db["credentials"][c["id"]] = c
    return ok_object(ser_credential(c), status=201)


@app.get("/clearinghouse/providers/<provider_id>/credentials")
def list_credentials(provider_id):
    require_roles("ProviderAdmin", "ClearinghouseOps")
    get_provider_or_404(provider_id)
    items = [c for c in db["credentials"].values() if c["provider_id"] == provider_id]
    items = _apply_filters(items, {"status": request.args.get("status")})
    return ok_list([ser_credential(c) for c in _sorted_by_created(items)])


@app.get("/clearinghouse/providers/<provider_id>/credentials/<credential_id>")
def get_credential(provider_id, credential_id):
    require_roles("ProviderAdmin", "ClearinghouseOps")
    get_provider_or_404(provider_id)
    c = get_credential_or_404(credential_id)
    if c["provider_id"] != provider_id:
        raise err_not_found("CREDENTIAL")
    return ok_object(ser_credential(c))


@app.post("/clearinghouse/providers/<provider_id>/credentials/<credential_id>/submit")
def submit_credential(provider_id, credential_id):
    require_roles("ProviderAdmin")
    get_provider_or_404(provider_id)
    c = get_credential_or_404(credential_id)
    if c["provider_id"] != provider_id:
        raise err_not_found("CREDENTIAL")
    if c["status"] != "DRAFT":
        raise err_invalid_state("credential is not DRAFT")
    if not c["trading_partner_agreement_ref"]:
        raise err_invalid_request("trading_partner_agreement_ref must be non-empty")
    if parse_instant(c["effective_at"]) >= parse_instant(c["expires_at"]):
        raise err_invalid_request("effective_at must be strictly before expires_at")
    c["status"] = "PENDING_ACTIVATION"
    touch(c)
    # If the logical clock is already at/past effective_at, activate immediately.
    if now() >= parse_instant(c["effective_at"]):
        c["status"] = "ACTIVE"
        touch(c)
    return ok_object(ser_credential(c))


@app.post("/clearinghouse/providers/<provider_id>/credentials/<credential_id>/revoke")
def revoke_credential(provider_id, credential_id):
    require_roles("ProviderAdmin", "ClearinghouseOps")
    get_provider_or_404(provider_id)
    c = get_credential_or_404(credential_id)
    if c["provider_id"] != provider_id:
        raise err_not_found("CREDENTIAL")
    if c["status"] != "ACTIVE":
        raise err_invalid_state("credential is not ACTIVE")
    for claim in db["claims"].values():
        if (claim["submitter_credential_id"] == credential_id
                and claim["acceptance_status"] in ("RECEIVED", "VALIDATING", "ACCEPTED", "FORWARDED")):
            raise err_invalid_state("credential is referenced by an in-flight claim")
    c["status"] = "REVOKED"
    touch(c)
    return ok_object(ser_credential(c))


@app.get("/clearinghouse/credentials")
def list_all_credentials():
    require_roles("ClearinghouseOps", "ProviderAdmin")
    items = list(db["credentials"].values())
    items = _apply_filters(items, {
        "provider_id": request.args.get("provider_id"),
        "status": request.args.get("status"),
    })
    return ok_list([ser_credential(c) for c in _sorted_by_created(items)])


# =============================================================================
# Payers
# =============================================================================

@app.post("/clearinghouse/payers")
def create_payer():
    require_roles("ClearinghouseOps")
    data = body()
    code = data.get("payer_id_code")
    display_name = data.get("display_name")
    claims_lead = data.get("claims_lead_time_days")
    remit_lead = data.get("remittance_lead_time_days")
    elig_lead = data.get("eligibility_lead_time_seconds")
    pricing_model = data.get("pricing_model")
    shared_pct = data.get("shared_provider_pct")
    monthly_min = data.get("monthly_minimum_cents", 0)
    if not isinstance(code, str) or not PAYER_CODE_RE.fullmatch(code):
        raise err_invalid_request("payer_id_code must be 5 chars of [A-Z0-9]")
    for p in db["payers"].values():
        if p["payer_id_code"] == code:
            raise err_invalid_request("payer_id_code must be unique")
    if not isinstance(display_name, str) or not display_name:
        raise err_invalid_request("display_name is required")
    for name, val in (("claims_lead_time_days", claims_lead),
                      ("remittance_lead_time_days", remit_lead),
                      ("eligibility_lead_time_seconds", elig_lead),
                      ("monthly_minimum_cents", monthly_min)):
        if not isinstance(val, int) or isinstance(val, bool) or val < 0:
            raise err_invalid_request(f"{name} must be a non-negative integer")
    if pricing_model not in PRICING_MODELS:
        raise err_invalid_request("pricing_model must be PAYER_FUNDED, PROVIDER_FUNDED, or SHARED")
    if pricing_model == "SHARED":
        if shared_pct is None or not isinstance(shared_pct, (int, float)) or isinstance(shared_pct, bool) \
                or not (0 <= shared_pct <= 1):
            raise err_invalid_request("shared_provider_pct must be a fraction in [0,1] for SHARED payers")
    p = stamp_new({
        "payer_id_code": code,
        "display_name": display_name,
        "claims_lead_time_days": claims_lead,
        "remittance_lead_time_days": remit_lead,
        "eligibility_lead_time_seconds": elig_lead,
        "pricing_model": pricing_model,
        "shared_provider_pct": shared_pct if pricing_model == "SHARED" else shared_pct,
        "connectivity_status": "ONLINE",
        "monthly_minimum_cents": monthly_min,
    })
    db["payers"][p["id"]] = p
    return ok_object(ser_payer(p), status=201)


@app.get("/clearinghouse/payers")
def list_payers():
    role, user_id = require_roles("ClearinghouseOps", "ProviderAdmin", "PayerOperator")
    items = list(db["payers"].values())
    if role == "PayerOperator":
        items = [p for p in items if p["id"] == user_id]
    items = _apply_filters(items, {
        "connectivity_status": request.args.get("connectivity_status"),
        "pricing_model": request.args.get("pricing_model"),
    })
    return ok_list([ser_payer(p) for p in _sorted_by_created(items)])


@app.get("/clearinghouse/payers/<payer_id>")
def get_payer(payer_id):
    require_roles("ClearinghouseOps", "ProviderAdmin", "PayerOperator")
    return ok_object(ser_payer(get_payer_or_404(payer_id)))


# =============================================================================
# Pricing tiers
# =============================================================================

TIER_APPLIES_TO = {"CLAIM", "ELIGIBILITY", "REMITTANCE"}


@app.post("/clearinghouse/payers/<payer_id>/pricing-tiers")
def create_pricing_tier(payer_id):
    require_roles("ClearinghouseOps")
    get_payer_or_404(payer_id)
    data = body()
    applies_to = data.get("applies_to")
    floor = data.get("volume_floor")
    ceiling = data.get("volume_ceiling")
    rate = data.get("rate_cents")
    if applies_to not in TIER_APPLIES_TO:
        raise err_invalid_request("applies_to must be CLAIM, ELIGIBILITY, or REMITTANCE")
    if not isinstance(floor, int) or isinstance(floor, bool) or floor < 1:
        raise err_invalid_request("volume_floor must be a positive integer")
    if ceiling is not None and (not isinstance(ceiling, int) or isinstance(ceiling, bool) or ceiling < floor):
        raise err_invalid_request("volume_ceiling must be an integer >= volume_floor")
    if not isinstance(rate, int) or isinstance(rate, bool) or rate < 0:
        raise err_invalid_request("rate_cents must be a non-negative integer")
    t = {
        "id": new_id(),
        "payer_id": payer_id,
        "applies_to": applies_to,
        "volume_floor": floor,
        "volume_ceiling": ceiling,
        "rate_cents": rate,
        "created_at": fmt_instant(now()),
        "_seq": next_seq(),
    }
    db["pricing_tiers"][t["id"]] = t
    return ok_object(ser_tier(t), status=201)


@app.get("/clearinghouse/payers/<payer_id>/pricing-tiers")
def list_pricing_tiers(payer_id):
    require_roles("ClearinghouseOps", "ProviderAdmin")
    get_payer_or_404(payer_id)
    items = [t for t in db["pricing_tiers"].values() if t["payer_id"] == payer_id]
    items = _apply_filters(items, {"applies_to": request.args.get("applies_to")})
    return ok_list([ser_tier(t) for t in _sorted_by_created(items)])


@app.get("/clearinghouse/pricing-tiers")
def list_all_pricing_tiers():
    require_roles("ClearinghouseOps", "ProviderAdmin")
    items = list(db["pricing_tiers"].values())
    items = _apply_filters(items, {
        "payer_id": request.args.get("payer_id"),
        "applies_to": request.args.get("applies_to"),
    })
    return ok_list([ser_tier(t) for t in _sorted_by_created(items)])


# =============================================================================
# Edit rules
# =============================================================================

@app.post("/clearinghouse/payers/<payer_id>/edit-rules")
def create_edit_rule(payer_id):
    role, user_id = require_roles("ClearinghouseOps", "PayerOperator", payer_code_required=(request.headers.get("X-User-Role") == "PayerOperator"))
    payer = get_payer_or_404(payer_id)
    if role == "PayerOperator":
        check_payer_code(payer)
    data = body()
    rule_code = data.get("rule_code")
    applies_to = data.get("applies_to")
    severity = data.get("severity")
    expression = data.get("expression")
    effective_from = data.get("effective_from")
    effective_to = data.get("effective_to")
    if not isinstance(rule_code, str) or not rule_code:
        raise err_invalid_request("rule_code is required")
    if applies_to != "CLAIM_INTAKE":
        raise err_invalid_request("applies_to must be CLAIM_INTAKE")
    if severity not in ("ERROR", "WARNING"):
        raise err_invalid_request("severity must be ERROR or WARNING")
    if not isinstance(expression, str) or not expression:
        raise err_invalid_request("expression is required")
    eff_from = parse_instant(effective_from)
    if eff_from is None:
        raise err_invalid_request("effective_from must be an ISO 8601 instant")
    eff_to = parse_instant(effective_to) if effective_to is not None else None
    if effective_to is not None and eff_to is None:
        raise err_invalid_request("effective_to must be an ISO 8601 instant")
    if eff_to is not None and not (eff_from < eff_to):
        raise err_invalid_request("effective_from must be strictly before effective_to")
    if eff_to is None:
        for r in db["edit_rules"].values():
            if (r["payer_id"] == payer_id and r["rule_code"] == rule_code
                    and r.get("effective_to") is None):
                raise err_invalid_request("rule_code must be unique per payer among open-ended rules")
    r = {
        "id": new_id(),
        "payer_id": payer_id,
        "rule_code": rule_code,
        "applies_to": applies_to,
        "severity": severity,
        "expression": expression,
        "effective_from": fmt_instant(eff_from),
        "effective_to": fmt_instant(eff_to) if eff_to else None,
        "created_at": fmt_instant(now()),
        "_seq": next_seq(),
    }
    db["edit_rules"][r["id"]] = r
    return ok_object(ser_rule(r), status=201)


@app.get("/clearinghouse/payers/<payer_id>/edit-rules")
def list_edit_rules(payer_id):
    require_roles("ClearinghouseOps", "ProviderAdmin", "PayerOperator")
    get_payer_or_404(payer_id)
    items = [r for r in db["edit_rules"].values() if r["payer_id"] == payer_id]
    items = _apply_filters(items, {"severity": request.args.get("severity")})
    return ok_list([ser_rule(r) for r in _sorted_by_created(items)])


@app.get("/clearinghouse/edit-rules")
def list_all_edit_rules():
    require_roles("ClearinghouseOps", "ProviderAdmin", "PayerOperator")
    items = list(db["edit_rules"].values())
    items = _apply_filters(items, {
        "payer_id": request.args.get("payer_id"),
        "severity": request.args.get("severity"),
    })
    return ok_list([ser_rule(r) for r in _sorted_by_created(items)])


# =============================================================================
# Payer enrollments
# =============================================================================

ENROLLMENT_BLOCKING_STATES = {"DRAFT", "SUBMITTED", "PAYER_REVIEW", "RE_SUBMITTED", "APPROVED"}


@app.post("/clearinghouse/providers/<provider_id>/enrollments")
def create_enrollment(provider_id):
    require_roles("ProviderAdmin")
    get_provider_or_404(provider_id)
    data = body()
    payer_id = data.get("payer_id")
    transaction_type = data.get("transaction_type")
    get_payer_or_404(payer_id)
    if transaction_type not in TRANSACTION_TYPES:
        raise err_invalid_request("transaction_type must be CLAIMS_837, REMITTANCE_835, or ELIGIBILITY_270")
    e = stamp_new({
        "provider_id": provider_id,
        "payer_id": payer_id,
        "transaction_type": transaction_type,
        "status": "DRAFT",
        "submitted_at": None,
        "payer_decision_due_at": None,
        "payer_decision_due_at_calendar": None,
        "approved_at": None,
        "rejection_reason": None,
        "decision_round": 0,
        "late_decision": False,
    })
    db["enrollments"][e["id"]] = e
    return ok_object(ser_enrollment(e), status=201)


@app.get("/clearinghouse/providers/<provider_id>/enrollments")
def list_enrollments(provider_id):
    require_roles("ProviderAdmin", "ClearinghouseOps", "PayerOperator")
    get_provider_or_404(provider_id)
    items = [e for e in db["enrollments"].values() if e["provider_id"] == provider_id]
    items = _apply_filters(items, {
        "payer_id": request.args.get("payer_id"),
        "transaction_type": request.args.get("transaction_type"),
        "status": request.args.get("status"),
    })
    return ok_list([ser_enrollment(e) for e in _sorted_by_created(items)])


@app.get("/clearinghouse/providers/<provider_id>/enrollments/<enrollment_id>")
def get_enrollment(provider_id, enrollment_id):
    require_roles("ProviderAdmin", "ClearinghouseOps", "PayerOperator")
    get_provider_or_404(provider_id)
    e = get_enrollment_or_404(enrollment_id)
    if e["provider_id"] != provider_id:
        raise err_not_found("ENROLLMENT")
    return ok_object(ser_enrollment(e))


@app.get("/clearinghouse/enrollments/<enrollment_id>")
def get_enrollment_by_id(enrollment_id):
    require_roles("ClearinghouseOps", "ProviderAdmin", "PayerOperator")
    return ok_object(ser_enrollment(get_enrollment_or_404(enrollment_id)))


@app.get("/clearinghouse/enrollments")
def list_all_enrollments():
    require_roles("ClearinghouseOps", "ProviderAdmin", "PayerOperator")
    items = list(db["enrollments"].values())
    items = _apply_filters(items, {
        "provider_id": request.args.get("provider_id"),
        "payer_id": request.args.get("payer_id"),
        "transaction_type": request.args.get("transaction_type"),
        "status": request.args.get("status"),
    })
    return ok_list([ser_enrollment(e) for e in _sorted_by_created(items)])


def _do_submit_enrollment(e, provider, payer, resubmit=False):
    e["status"] = "RE_SUBMITTED" if resubmit else "SUBMITTED"
    submitted_dt = now()
    e["submitted_at"] = fmt_instant(submitted_dt)
    e["decision_round"] = (e.get("decision_round", 0) + 1) if resubmit else 1
    if resubmit:
        e["late_decision"] = False
    business, calendar = enrollment_due_dates(submitted_dt, payer, e["transaction_type"])
    e["payer_decision_due_at"] = business
    e["payer_decision_due_at_calendar"] = calendar
    touch(e)


@app.post("/clearinghouse/providers/<provider_id>/enrollments/<enrollment_id>/submit")
def submit_enrollment(provider_id, enrollment_id):
    require_roles("ProviderAdmin")
    provider = get_provider_or_404(provider_id)
    e = get_enrollment_or_404(enrollment_id)
    if e["provider_id"] != provider_id:
        raise err_not_found("ENROLLMENT")
    if e["status"] != "DRAFT":
        raise err_invalid_state("enrollment is not DRAFT")
    if provider["status"] != "ACTIVE":
        raise ApiError("ERR_PROVIDER_NOT_ACTIVE", 409, "provider is not ACTIVE")
    for other in db["enrollments"].values():
        if (other["id"] != e["id"] and other["provider_id"] == provider_id
                and other["payer_id"] == e["payer_id"]
                and other["transaction_type"] == e["transaction_type"]
                and other["status"] in ENROLLMENT_BLOCKING_STATES):
            raise ApiError("ERR_ENROLLMENT_DUPLICATE_ACTIVE", 409,
                           "a non-terminal enrollment already exists for this (provider, payer, transaction_type)")
    payer = get_payer_or_404(e["payer_id"])
    _do_submit_enrollment(e, provider, payer, resubmit=False)
    return ok_object(ser_enrollment(e))


@app.post("/clearinghouse/providers/<provider_id>/enrollments/<enrollment_id>/resubmit")
def resubmit_enrollment(provider_id, enrollment_id):
    require_roles("ProviderAdmin")
    provider = get_provider_or_404(provider_id)
    e = get_enrollment_or_404(enrollment_id)
    if e["provider_id"] != provider_id:
        raise err_not_found("ENROLLMENT")
    if e["status"] != "REJECTED":
        raise err_invalid_state("enrollment is not REJECTED")
    if provider["status"] != "ACTIVE":
        raise ApiError("ERR_PROVIDER_NOT_ACTIVE", 409, "provider is not ACTIVE")
    payer = get_payer_or_404(e["payer_id"])
    _do_submit_enrollment(e, provider, payer, resubmit=True)
    return ok_object(ser_enrollment(e))


@app.post("/clearinghouse/providers/<provider_id>/enrollments/<enrollment_id>/cancel")
def cancel_enrollment(provider_id, enrollment_id):
    require_roles("ProviderAdmin", "ClearinghouseOps")
    get_provider_or_404(provider_id)
    e = get_enrollment_or_404(enrollment_id)
    if e["provider_id"] != provider_id:
        raise err_not_found("ENROLLMENT")
    if e["status"] not in ("SUBMITTED", "PAYER_REVIEW", "APPROVED", "RE_SUBMITTED"):
        raise err_invalid_state("enrollment cannot be cancelled from its current state")
    if e["status"] == "APPROVED":
        if e["transaction_type"] == "CLAIMS_837":
            for c in db["claims"].values():
                if (c["provider_id"] == provider_id and c["payer_id"] == e["payer_id"]
                        and c["acceptance_status"] in ("RECEIVED", "VALIDATING", "ACCEPTED", "FORWARDED")):
                    raise err_invalid_state("in-flight claims exist on this (provider, payer)")
        elif e["transaction_type"] == "ELIGIBILITY_270":
            for i in db["inquiries"].values():
                if (i["provider_id"] == provider_id and i["payer_id"] == e["payer_id"]
                        and i["status"] in ("PENDING", "QUEUED_OUTAGE")):
                    raise err_invalid_state("in-flight eligibility inquiries exist on this (provider, payer)")
    e["status"] = "CANCELLED"
    touch(e)
    return ok_object(ser_enrollment(e))


@app.post("/clearinghouse/enrollments/<enrollment_id>/payer-decision")
def payer_decision(enrollment_id):
    role, user_id = require_roles("PayerOperator", payer_code_required=True)
    e = get_enrollment_or_404(enrollment_id)
    payer = get_payer_or_404(e["payer_id"])
    check_payer_code(payer)
    data = body()
    decision = data.get("decision")
    expected_version = data.get("expected_enrollment_version")
    rejection_reason = data.get("rejection_reason")
    if decision not in ("APPROVE", "REJECT"):
        raise err_invalid_request("decision must be APPROVE or REJECT")
    if e["status"] != "PAYER_REVIEW":
        raise err_invalid_state("enrollment is not in PAYER_REVIEW")
    if decision == "APPROVE":
        provider = db["providers"].get(e["provider_id"])
        if provider is None or provider["status"] != "ACTIVE":
            raise err_invalid_state("provider is not ACTIVE")
    if decision == "REJECT" and (not isinstance(rejection_reason, str) or not rejection_reason):
        raise err_invalid_request("rejection_reason is required when decision is REJECT")
    # OCC
    if expected_version is None or not isinstance(expected_version, int) \
            or expected_version != e["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "expected_enrollment_version does not match current version")
    # Late decision warning flag.
    if e.get("payer_decision_due_at"):
        due = parse_instant(e["payer_decision_due_at"])
        if due is not None and now() > due:
            e["late_decision"] = True
    if decision == "APPROVE":
        e["status"] = "APPROVED"
        e["approved_at"] = fmt_instant(now())
    else:
        e["status"] = "REJECTED"
        e["rejection_reason"] = rejection_reason
    touch(e)
    return ok_object(ser_enrollment(e))


# =============================================================================
# Claims
# =============================================================================

def _claim_payload_fingerprint(data):
    keys = ["payer_id", "submitter_credential_id", "patient_control_number",
            "service_date", "total_charge_cents", "diagnosis_codes",
            "rendering_npi", "subscriber_id", "lines"]
    import json
    return json.dumps({k: data.get(k) for k in keys}, sort_keys=True, default=str)


@app.post("/clearinghouse/providers/<provider_id>/claims")
def create_claim(provider_id):
    require_roles("ProviderAdmin")
    provider = get_provider_or_404(provider_id)
    data = body()
    payer_id = data.get("payer_id")
    credential_id = data.get("submitter_credential_id")
    payer = get_payer_or_404(payer_id)
    credential = get_credential_or_404(credential_id)
    # Parent aggregate state.
    if provider["status"] != "ACTIVE":
        raise ApiError("ERR_PROVIDER_NOT_ACTIVE", 409, "provider is not ACTIVE")
    # Idempotency (before credential binding per priority ladder ordering 8 < 9).
    idem_key = data.get("idempotency_key")
    if not isinstance(idem_key, str) or not idem_key:
        raise err_invalid_request("idempotency_key is required")
    fingerprint = _claim_payload_fingerprint(data)
    for existing in db["claims"].values():
        if existing["provider_id"] == provider_id and existing["idempotency_key"] == idem_key:
            if existing.get("_payload_fingerprint") == fingerprint:
                return ok_object(ser_claim(existing), status=201)
            raise ApiError("ERR_IDEMPOTENCY_CONFLICT", 409,
                           "idempotency_key replayed with a different payload")
    # Credential binding + validity window.
    if credential["provider_id"] != provider_id:
        raise ApiError("ERR_CREDENTIAL_NOT_ACTIVE", 409,
                       "submitter credential does not belong to this provider")
    if credential["status"] != "ACTIVE":
        raise ApiError("ERR_CREDENTIAL_NOT_ACTIVE", 409, "submitter credential is not ACTIVE")
    eff = parse_instant(credential["effective_at"])
    exp = parse_instant(credential["expires_at"])
    current = now()
    if not (eff <= current < exp):
        raise ApiError("ERR_CREDENTIAL_NOT_ACTIVE", 409,
                       "submitter credential is outside its validity window")
    # Claims enrollment gate.
    if find_approved_enrollment(provider_id, payer_id, "CLAIMS_837") is None:
        raise ApiError("ERR_ENROLLMENT_NOT_APPROVED", 409,
                       "no APPROVED CLAIMS_837 enrollment for this (provider, payer)")
    # Patient control number uniqueness among non-REJECTED_CLEARINGHOUSE claims.
    pcn = data.get("patient_control_number")
    if not isinstance(pcn, str) or not pcn:
        raise err_invalid_request("patient_control_number is required")
    for existing in db["claims"].values():
        if (existing["provider_id"] == provider_id and existing["payer_id"] == payer_id
                and existing["patient_control_number"] == pcn
                and existing["acceptance_status"] != "REJECTED_CLEARINGHOUSE"):
            raise ApiError("ERR_DUPLICATE_PATIENT_CONTROL_NUMBER", 409,
                           "patient_control_number collides with a non-rejected claim")
    # Total consistency.
    total = data.get("total_charge_cents")
    lines = data.get("lines") or []
    if not isinstance(total, int) or isinstance(total, bool):
        raise err_invalid_request("total_charge_cents must be an integer")
    if not isinstance(lines, list):
        raise err_invalid_request("lines must be an array")
    computed = 0
    for line in lines:
        if not isinstance(line, dict):
            raise err_invalid_request("each line must be an object")
        units = line.get("units", 0)
        unit_charge = line.get("unit_charge_cents", 0)
        if not isinstance(units, int) or not isinstance(unit_charge, int):
            raise err_invalid_request("line units and unit_charge_cents must be integers")
        computed += units * unit_charge
    if total != computed:
        raise ApiError("ERR_CLAIM_TOTAL_MISMATCH", 422,
                       "total_charge_cents does not equal the sum of line charges")
    service_date = parse_instant(data.get("service_date"))
    diagnosis_codes = data.get("diagnosis_codes") or []
    claim = stamp_new({
        "provider_id": provider_id,
        "payer_id": payer_id,
        "submitter_credential_id": credential_id,
        "patient_control_number": pcn,
        "idempotency_key": idem_key,
        "service_date": fmt_instant(service_date) if service_date else data.get("service_date"),
        "total_charge_cents": total,
        "diagnosis_codes": diagnosis_codes,
        "rendering_npi": data.get("rendering_npi"),
        "subscriber_id": data.get("subscriber_id"),
        "lines": lines,
        "acceptance_status": "RECEIVED",
        "adjudication_status": "NONE",
        "edit_failures": [],
        "forwarded_at": None,
        "payer_response_due_at": None,
        "payer_response_due_at_calendar": None,
        "rejection_payload": None,
        "_payload_fingerprint": fingerprint,
    })
    db["claims"][claim["id"]] = claim
    # RECEIVED -> VALIDATING, evaluate edits.
    claim["acceptance_status"] = "VALIDATING"
    failures = run_edit_rules(claim, payer)
    claim["edit_failures"] = failures
    if any(f["severity"] == "ERROR" for f in failures):
        claim["acceptance_status"] = "REJECTED_CLEARINGHOUSE"
        claim["rejection_payload"] = {
            "origin": "CLEARINGHOUSE",
            "rule_codes": [f["rule_code"] for f in failures if f["severity"] == "ERROR"],
            "message": "claim failed clearinghouse edits: "
                       + ", ".join(f["rule_code"] for f in failures if f["severity"] == "ERROR"),
        }
    else:
        claim["acceptance_status"] = "ACCEPTED"
    touch(claim)
    return ok_object(ser_claim(claim), status=201)


def _forward_claim(claim, payer):
    """Shared ACCEPTED -> FORWARDED transition with all side effects."""
    forwarded_dt = now()
    claim["acceptance_status"] = "FORWARDED"
    claim["forwarded_at"] = fmt_instant(forwarded_dt)
    business = business_day_add(forwarded_dt, payer["claims_lead_time_days"])
    calendar = forwarded_dt + timedelta(days=payer["claims_lead_time_days"])
    claim["payer_response_due_at"] = fmt_instant(business)
    claim["payer_response_due_at_calendar"] = fmt_instant(calendar)
    claim["adjudication_status"] = "PENDING"
    touch(claim)
    record_meter_event(claim["provider_id"], "claim", 1, payer)


@app.get("/clearinghouse/providers/<provider_id>/claims")
def list_claims(provider_id):
    require_roles("ProviderAdmin", "ClearinghouseOps", "PayerOperator")
    get_provider_or_404(provider_id)
    items = [c for c in db["claims"].values() if c["provider_id"] == provider_id]
    items = _apply_filters(items, {
        "payer_id": request.args.get("payer_id"),
        "acceptance_status": request.args.get("acceptance_status"),
        "adjudication_status": request.args.get("adjudication_status"),
    })
    return ok_list([ser_claim(c) for c in _sorted_by_created(items)])


@app.get("/clearinghouse/claims/<claim_id>")
def get_claim(claim_id):
    require_roles("ProviderAdmin", "ClearinghouseOps", "PayerOperator")
    return ok_object(ser_claim(get_claim_or_404(claim_id)))


@app.get("/clearinghouse/claims")
def list_all_claims():
    require_roles("ClearinghouseOps", "ProviderAdmin", "PayerOperator")
    items = list(db["claims"].values())
    items = _apply_filters(items, {
        "provider_id": request.args.get("provider_id"),
        "payer_id": request.args.get("payer_id"),
        "submitter_credential_id": request.args.get("submitter_credential_id"),
        "acceptance_status": request.args.get("acceptance_status"),
        "adjudication_status": request.args.get("adjudication_status"),
    })
    return ok_list([ser_claim(c) for c in _sorted_by_created(items)])


@app.post("/clearinghouse/claims/<claim_id>/forward")
def forward_claim(claim_id):
    require_roles("ClearinghouseOps")
    claim = get_claim_or_404(claim_id)
    data = body()
    expected_version = data.get("expected_claim_version")
    if claim["acceptance_status"] != "ACCEPTED":
        raise err_invalid_state("claim is not ACCEPTED")
    payer = get_payer_or_404(claim["payer_id"])
    if payer_posture_for(payer["id"], "CLAIMS_837") == "OFFLINE":
        raise ApiError("ERR_PAYER_OFFLINE", 409, "payer is OFFLINE for CLAIMS_837")
    if expected_version is None or not isinstance(expected_version, int) \
            or expected_version != claim["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "expected_claim_version does not match current version")
    _forward_claim(claim, payer)
    resp = ok_object(ser_claim(claim))
    if payer_posture_for(payer["id"], "CLAIMS_837") == "DEGRADED":
        resp[0].headers["X-Connectivity-Warning"] = "DEGRADED"
    return resp


@app.post("/clearinghouse/claims/<claim_id>/payer-ack")
def payer_ack_claim(claim_id):
    require_roles("PayerOperator", payer_code_required=True)
    claim = get_claim_or_404(claim_id)
    payer = get_payer_or_404(claim["payer_id"])
    check_payer_code(payer)
    if claim["acceptance_status"] != "FORWARDED":
        raise err_invalid_state("claim is not FORWARDED")
    claim["acceptance_status"] = "ACKNOWLEDGED_BY_PAYER"
    touch(claim)
    return ok_object(ser_claim(claim))


@app.post("/clearinghouse/claims/<claim_id>/payer-reject")
def payer_reject_claim(claim_id):
    require_roles("PayerOperator", payer_code_required=True)
    claim = get_claim_or_404(claim_id)
    payer = get_payer_or_404(claim["payer_id"])
    check_payer_code(payer)
    data = body()
    rule_codes = data.get("rule_codes")
    message = data.get("message", "")
    if claim["acceptance_status"] != "FORWARDED":
        raise err_invalid_state("claim is not FORWARDED")
    if not isinstance(rule_codes, list) or not rule_codes:
        raise err_invalid_request("rule_codes must be a non-empty list")
    claim["acceptance_status"] = "REJECTED_BY_PAYER"
    claim["adjudication_status"] = "DENIED"
    claim["rejection_payload"] = {
        "origin": "PAYER",
        "rule_codes": rule_codes,
        "message": message if isinstance(message, str) else "",
    }
    touch(claim)
    return ok_object(ser_claim(claim))


# =============================================================================
# Remittance advices & posting files
# =============================================================================

@app.post("/clearinghouse/claims/<claim_id>/remittances")
def create_remittance(claim_id):
    require_roles("PayerOperator", payer_code_required=True)
    claim = get_claim_or_404(claim_id)
    payer = get_payer_or_404(claim["payer_id"])
    check_payer_code(payer)
    data = body()
    check_number = data.get("check_number")
    paid = data.get("paid_amount_cents")
    adjustment = data.get("adjustment_amount_cents")
    patient_resp = data.get("patient_responsibility_cents")
    denial_codes = data.get("denial_reason_codes") or []
    for name, val in (("paid_amount_cents", paid), ("adjustment_amount_cents", adjustment),
                      ("patient_responsibility_cents", patient_resp)):
        if not isinstance(val, int) or isinstance(val, bool) or val < 0:
            raise err_invalid_request(f"{name} must be a non-negative integer")
    if not isinstance(denial_codes, list):
        raise err_invalid_request("denial_reason_codes must be a list")
    r = stamp_new({
        "claim_id": claim_id,
        "payer_id": claim["payer_id"],
        "check_number": check_number if isinstance(check_number, str) else "",
        "paid_amount_cents": paid,
        "adjustment_amount_cents": adjustment,
        "patient_responsibility_cents": patient_resp,
        "denial_reason_codes": denial_codes,
        "status": "RECEIVED",
    })
    db["remittances"][r["id"]] = r
    return ok_object(ser_remittance(r), status=201)


@app.get("/clearinghouse/claims/<claim_id>/remittances")
def list_remittances_for_claim(claim_id):
    require_roles("ProviderAdmin", "ClearinghouseOps", "PayerOperator")
    get_claim_or_404(claim_id)
    items = [r for r in db["remittances"].values() if r["claim_id"] == claim_id]
    items = _apply_filters(items, {"status": request.args.get("status")})
    return ok_list([ser_remittance(r) for r in _sorted_by_created(items)])


@app.get("/clearinghouse/remittances/<remittance_id>")
def get_remittance(remittance_id):
    require_roles("ProviderAdmin", "ClearinghouseOps", "PayerOperator")
    return ok_object(ser_remittance(get_remittance_or_404(remittance_id)))


@app.get("/clearinghouse/remittances")
def list_all_remittances():
    require_roles("ClearinghouseOps", "ProviderAdmin", "PayerOperator")
    items = list(db["remittances"].values())
    items = _apply_filters(items, {
        "claim_id": request.args.get("claim_id"),
        "payer_id": request.args.get("payer_id"),
        "status": request.args.get("status"),
    })
    return ok_list([ser_remittance(r) for r in _sorted_by_created(items)])


def _classify_remittance_outcome(remittance, claim):
    if remittance["denial_reason_codes"] and remittance["paid_amount_cents"] == 0:
        return "DENIED"
    if (remittance["paid_amount_cents"] == claim["total_charge_cents"]
            and remittance["adjustment_amount_cents"] == 0
            and remittance["patient_responsibility_cents"] == 0):
        return "PAID"
    return "PARTIAL"


@app.post("/clearinghouse/remittances/<remittance_id>/post")
def post_remittance(remittance_id):
    require_roles("ClearinghouseOps")
    r = get_remittance_or_404(remittance_id)
    if r["status"] in ("POSTED", "VOIDED"):
        raise ApiError("ERR_REMITTANCE_NOT_POSTABLE", 409,
                       "remittance is already POSTED or VOIDED")
    claim = get_claim_or_404(r["claim_id"])
    if claim["acceptance_status"] != "ACKNOWLEDGED_BY_PAYER":
        raise err_invalid_state("claim is not ACKNOWLEDGED_BY_PAYER")
    if claim["adjudication_status"] != "PENDING":
        raise err_invalid_state("claim adjudication is not PENDING")
    if find_approved_enrollment(claim["provider_id"], claim["payer_id"], "REMITTANCE_835") is None:
        raise ApiError("ERR_ENROLLMENT_NOT_APPROVED", 409,
                       "no APPROVED REMITTANCE_835 enrollment for this (provider, payer)")
    if (r["paid_amount_cents"] + r["adjustment_amount_cents"] + r["patient_responsibility_cents"]
            != claim["total_charge_cents"]):
        raise ApiError("ERR_REMITTANCE_IMBALANCE", 422,
                       "paid + adjustment + patient_responsibility must equal claim total")
    if r["paid_amount_cents"] == 0 and not r["denial_reason_codes"]:
        raise ApiError("ERR_REMITTANCE_IMBALANCE", 422,
                       "paid_amount_cents of 0 requires non-empty denial_reason_codes")
    # Post: classify outcome, update claim, spawn posting file, meter.
    r["status"] = "POSTED"
    touch(r)
    outcome = _classify_remittance_outcome(r, claim)
    claim["adjudication_status"] = outcome
    touch(claim)
    payer = get_payer_or_404(r["payer_id"])
    posting_file = {
        "id": new_id(),
        "remittance_advice_id": r["id"],
        "generated_at": fmt_instant(now()),
        "line_count": len(claim.get("lines") or []),
        "total_posted_cents": r["paid_amount_cents"],
        "status": "READY",  # GENERATING resolves to READY on render completion (immediate).
        "created_at": fmt_instant(now()),
        "_seq": next_seq(),
    }
    db["posting_files"][posting_file["id"]] = posting_file
    record_meter_event(claim["provider_id"], "remittance", 1, payer)
    return ok_object(ser_remittance(r))


@app.post("/clearinghouse/remittances/<remittance_id>/void")
def void_remittance(remittance_id):
    require_roles("ClearinghouseOps")
    r = get_remittance_or_404(remittance_id)
    if r["status"] != "POSTED":
        raise err_invalid_state("remittance is not POSTED")
    for f in db["posting_files"].values():
        if f["remittance_advice_id"] == remittance_id and f["status"] == "DELIVERED":
            raise err_invalid_state("a DELIVERED posting file exists for this remittance")
    r["status"] = "VOIDED"
    touch(r)
    for f in db["posting_files"].values():
        if f["remittance_advice_id"] == remittance_id and f["status"] == "READY":
            f["status"] = "FAILED"
    claim = get_claim_or_404(r["claim_id"])
    claim["adjudication_status"] = "PENDING"
    touch(claim)
    payer = get_payer_or_404(r["payer_id"])
    record_meter_event(claim["provider_id"], "remittance", -1, payer)
    return ok_object(ser_remittance(r))


@app.get("/clearinghouse/remittances/<remittance_id>/posting-files")
def list_posting_files(remittance_id):
    require_roles("ProviderAdmin", "ClearinghouseOps")
    get_remittance_or_404(remittance_id)
    items = [f for f in db["posting_files"].values() if f["remittance_advice_id"] == remittance_id]
    items = _apply_filters(items, {"status": request.args.get("status")})
    return ok_list([ser_posting_file(f) for f in _sorted_by_created(items)])


@app.get("/clearinghouse/posting-files/<posting_file_id>")
def get_posting_file(posting_file_id):
    require_roles("ProviderAdmin", "ClearinghouseOps")
    return ok_object(ser_posting_file(get_posting_file_or_404(posting_file_id)))


@app.get("/clearinghouse/posting-files")
def list_all_posting_files():
    require_roles("ClearinghouseOps", "ProviderAdmin")
    items = list(db["posting_files"].values())
    items = _apply_filters(items, {
        "remittance_advice_id": request.args.get("remittance_advice_id"),
        "status": request.args.get("status"),
    })
    return ok_list([ser_posting_file(f) for f in _sorted_by_created(items)])


@app.post("/clearinghouse/posting-files/<posting_file_id>/deliver")
def deliver_posting_file(posting_file_id):
    require_roles("ProviderAdmin")
    f = get_posting_file_or_404(posting_file_id)
    r = get_remittance_or_404(f["remittance_advice_id"])
    if f["status"] != "READY":
        raise ApiError("ERR_POSTING_FILE_NOT_DELIVERABLE", 409, "posting file is not READY")
    if r["status"] != "POSTED":
        raise err_invalid_state("remittance is not POSTED")
    f["status"] = "DELIVERED"
    return ok_object(ser_posting_file(f))


# =============================================================================
# Eligibility inquiries
# =============================================================================

def _inquiry_payload_fingerprint(data):
    import json
    keys = ["payer_id", "subscriber_id", "service_type_code"]
    return json.dumps({k: data.get(k) for k in keys}, sort_keys=True, default=str)


@app.post("/clearinghouse/providers/<provider_id>/eligibility")
def create_eligibility(provider_id):
    require_roles("ProviderAdmin")
    provider = get_provider_or_404(provider_id)
    data = body()
    payer_id = data.get("payer_id")
    payer = get_payer_or_404(payer_id)
    if provider["status"] != "ACTIVE":
        raise ApiError("ERR_PROVIDER_NOT_ACTIVE", 409, "provider is not ACTIVE")
    idem_key = data.get("idempotency_key")
    if not isinstance(idem_key, str) or not idem_key:
        raise err_invalid_request("idempotency_key is required")
    fingerprint = _inquiry_payload_fingerprint(data)
    for existing in db["inquiries"].values():
        if existing["provider_id"] == provider_id and existing["idempotency_key"] == idem_key:
            if existing.get("_payload_fingerprint") == fingerprint:
                return ok_object(ser_inquiry(existing), status=201)
            raise ApiError("ERR_IDEMPOTENCY_CONFLICT", 409,
                           "idempotency_key replayed with a different payload")
    if find_approved_enrollment(provider_id, payer_id, "ELIGIBILITY_270") is None:
        raise ApiError("ERR_ENROLLMENT_NOT_APPROVED", 409,
                       "no APPROVED ELIGIBILITY_270 enrollment for this (provider, payer)")
    if payer_posture_for(payer_id, "ELIGIBILITY_270") == "OFFLINE":
        raise ApiError("ERR_PAYER_OFFLINE", 409, "payer is OFFLINE for ELIGIBILITY_270")
    requested = now()
    deadline = requested + timedelta(seconds=payer["eligibility_lead_time_seconds"])
    i = stamp_new({
        "provider_id": provider_id,
        "payer_id": payer_id,
        "subscriber_id": data.get("subscriber_id"),
        "service_type_code": data.get("service_type_code"),
        "idempotency_key": idem_key,
        "status": "PENDING",
        "requested_at": fmt_instant(requested),
        "deadline_at": fmt_instant(deadline),
        "responded_at": None,
        "benefit_summary": None,
        "_payload_fingerprint": fingerprint,
    })
    db["inquiries"][i["id"]] = i
    # If an ACTIVE eligibility outage exists for this payer, queue immediately.
    for o in db["outages"].values():
        if (o["payer_id"] == payer_id and o["status"] == "ACTIVE"
                and "ELIGIBILITY_270" in o["affects_transaction_types"]):
            i["status"] = "QUEUED_OUTAGE"
            touch(i)
            break
    return ok_object(ser_inquiry(i), status=201)


@app.get("/clearinghouse/providers/<provider_id>/eligibility")
def list_eligibility(provider_id):
    require_roles("ProviderAdmin", "ClearinghouseOps", "PayerOperator")
    get_provider_or_404(provider_id)
    items = [i for i in db["inquiries"].values() if i["provider_id"] == provider_id]
    items = _apply_filters(items, {
        "payer_id": request.args.get("payer_id"),
        "status": request.args.get("status"),
    })
    return ok_list([ser_inquiry(i) for i in _sorted_by_created(items)])


@app.get("/clearinghouse/eligibility/<inquiry_id>")
def get_inquiry(inquiry_id):
    require_roles("ProviderAdmin", "ClearinghouseOps", "PayerOperator")
    return ok_object(ser_inquiry(get_inquiry_or_404(inquiry_id)))


@app.get("/clearinghouse/eligibility")
def list_all_eligibility():
    require_roles("ClearinghouseOps", "ProviderAdmin", "PayerOperator")
    items = list(db["inquiries"].values())
    items = _apply_filters(items, {
        "provider_id": request.args.get("provider_id"),
        "payer_id": request.args.get("payer_id"),
        "status": request.args.get("status"),
    })
    return ok_list([ser_inquiry(i) for i in _sorted_by_created(items)])


@app.post("/clearinghouse/eligibility/<inquiry_id>/respond")
def respond_to_inquiry(inquiry_id):
    require_roles("PayerOperator", payer_code_required=True)
    i = get_inquiry_or_404(inquiry_id)
    payer = get_payer_or_404(i["payer_id"])
    check_payer_code(payer)
    if i["status"] != "PENDING":
        raise err_invalid_state("inquiry is not PENDING")
    deadline = parse_instant(i["deadline_at"]) if i.get("deadline_at") else None
    if deadline is not None and now() > deadline:
        raise ApiError("ERR_INQUIRY_TIMED_OUT", 409, "271 response arrived after deadline_at")
    data = body()
    i["status"] = "RESPONDED"
    i["responded_at"] = fmt_instant(now())
    i["benefit_summary"] = data.get("benefit_summary")
    touch(i)
    record_meter_event(i["provider_id"], "eligibility", 1, payer)
    return ok_object(ser_inquiry(i))


# =============================================================================
# Connectivity outages & notifications
# =============================================================================

def _queue_pending_inquiries(payer_id, transaction_types):
    for i in db["inquiries"].values():
        if (i["payer_id"] == payer_id and i["status"] == "PENDING"
                and "ELIGIBILITY_270" in transaction_types):
            i["status"] = "QUEUED_OUTAGE"
            touch(i)


def _notify_providers(outage):
    """Record and dispatch one notification per provider holding an APPROVED
    enrollment on the affected (payer, transaction_type) combinations."""
    affected_providers = []
    seen = set()
    for e in db["enrollments"].values():
        if (e["payer_id"] == outage["payer_id"] and e["status"] == "APPROVED"
                and e["transaction_type"] in outage["affects_transaction_types"]):
            if e["provider_id"] not in seen:
                seen.add(e["provider_id"])
                affected_providers.append(e["provider_id"])
    outage["notified_provider_ids"] = affected_providers
    for pid in affected_providers:
        body_text = (f"Connectivity outage opened for payer {outage['payer_id']} "
                     f"affecting {', '.join(outage['affects_transaction_types'])} "
                     f"(severity {outage['severity']})")
        n = {
            "id": new_id(),
            "outage_id": outage["id"],
            "provider_id": pid,
            "sent_at": fmt_instant(now()),
            "channel": "WEBHOOK",
            "payload_summary": body_text[:120],
            "created_at": fmt_instant(now()),
            "_seq": next_seq(),
        }
        db["notifications"][n["id"]] = n


@app.post("/clearinghouse/payers/<payer_id>/outages")
def create_outage(payer_id):
    require_roles("ClearinghouseOps")
    payer = get_payer_or_404(payer_id)
    data = body()
    severity = data.get("severity")
    affects = data.get("affects_transaction_types")
    if severity not in ("PARTIAL", "FULL"):
        raise err_invalid_request("severity must be PARTIAL or FULL")
    if not isinstance(affects, list) or not affects \
            or any(t not in TRANSACTION_TYPES for t in affects):
        raise err_invalid_request("affects_transaction_types must be a non-empty subset of transaction types")
    o = stamp_new({
        "payer_id": payer_id,
        "started_at": fmt_instant(now()),
        "ended_at": None,
        "severity": severity,
        "affects_transaction_types": list(affects),
        "status": "ACTIVE",
        "notified_provider_ids": [],
    })
    db["outages"][o["id"]] = o
    recompute_connectivity(payer)
    _queue_pending_inquiries(payer_id, affects)
    _notify_providers(o)
    return ok_object(ser_outage(o), status=201)


@app.get("/clearinghouse/payers/<payer_id>/outages")
def list_outages(payer_id):
    require_roles("ClearinghouseOps", "ProviderAdmin", "PayerOperator")
    get_payer_or_404(payer_id)
    items = [o for o in db["outages"].values() if o["payer_id"] == payer_id]
    items = _apply_filters(items, {"status": request.args.get("status")})
    return ok_list([ser_outage(o) for o in _sorted_by_created(items)])


@app.get("/clearinghouse/outages/<outage_id>")
def get_outage(outage_id):
    require_roles("ClearinghouseOps", "ProviderAdmin", "PayerOperator")
    return ok_object(ser_outage(get_outage_or_404(outage_id)))


@app.get("/clearinghouse/outages")
def list_all_outages():
    require_roles("ClearinghouseOps", "ProviderAdmin", "PayerOperator")
    items = list(db["outages"].values())
    items = _apply_filters(items, {
        "payer_id": request.args.get("payer_id"),
        "status": request.args.get("status"),
    })
    return ok_list([ser_outage(o) for o in _sorted_by_created(items)])


@app.post("/clearinghouse/outages/<outage_id>/resolve")
def resolve_outage(outage_id):
    require_roles("ClearinghouseOps")
    o = get_outage_or_404(outage_id)
    if o["status"] != "ACTIVE":
        raise err_invalid_state("outage is not ACTIVE")
    o["status"] = "RESOLVED"
    o["ended_at"] = fmt_instant(now())
    touch(o)
    payer = get_payer_or_404(o["payer_id"])
    recompute_connectivity(payer)
    # Restore queued inquiries whose payer has no remaining eligibility outage.
    for i in db["inquiries"].values():
        if i["payer_id"] == o["payer_id"] and i["status"] == "QUEUED_OUTAGE":
            still_affected = any(
                other["payer_id"] == o["payer_id"] and other["status"] == "ACTIVE"
                and "ELIGIBILITY_270" in other["affects_transaction_types"]
                for other in db["outages"].values()
            )
            if not still_affected:
                i["status"] = "PENDING"
                i["deadline_at"] = fmt_instant(now() + timedelta(seconds=payer["eligibility_lead_time_seconds"]))
                touch(i)
    return ok_object(ser_outage(o))


@app.get("/clearinghouse/outages/<outage_id>/notifications")
def list_outage_notifications(outage_id):
    require_roles("ClearinghouseOps", "ProviderAdmin")
    get_outage_or_404(outage_id)
    items = [n for n in db["notifications"].values() if n["outage_id"] == outage_id]
    return ok_list([ser_notification(n) for n in _sorted_by_created(items)])


@app.get("/clearinghouse/notifications")
def list_all_notifications():
    require_roles("ClearinghouseOps", "ProviderAdmin")
    items = list(db["notifications"].values())
    items = _apply_filters(items, {
        "outage_id": request.args.get("outage_id"),
        "provider_id": request.args.get("provider_id"),
    })
    return ok_list([ser_notification(n) for n in _sorted_by_created(items)])


@app.get("/clearinghouse/notifications/<notification_id>")
def get_notification(notification_id):
    require_roles("ClearinghouseOps", "ProviderAdmin")
    return ok_object(ser_notification(get_notification_or_404(notification_id)))


# =============================================================================
# Usage invoices
# =============================================================================

TIER_2_FLOOR = 10000
TIER_3_FLOOR = 100000


def _invoice_fee_breakdown(inv):
    """Compute per-(kind, payer) fee lines from the meter log for the invoice's period.

    Returns (gross_fee_cents, provider_funded_fees_by_payer).
    """
    per_kind_payer = _meter_events_for(inv["provider_id"], inv["period_yyyy_mm"])

    kind_map = {"claim": "CLAIM", "eligibility": "ELIGIBILITY", "remittance": "REMITTANCE"}
    gross = 0
    provider_funded_fees = {}
    for (kind, payer_id), units in per_kind_payer.items():
        if units <= 0:
            continue
        payer = db["payers"].get(payer_id)
        if payer is None:
            continue
        tiers = sorted(
            (t for t in db["pricing_tiers"].values()
             if t["payer_id"] == payer_id and t["applies_to"] == kind_map[kind]),
            key=lambda t: t["volume_floor"],
        )
        fee = 0
        for t in tiers:
            if t["volume_floor"] > units:
                continue
            ceiling = t["volume_ceiling"] if t["volume_ceiling"] is not None else units
            covered = min(units, ceiling) - t["volume_floor"] + 1
            if covered > 0:
                fee += covered * t["rate_cents"]
        if payer["pricing_model"] == "SHARED":
            fee = round_half_up(fee * float(payer.get("shared_provider_pct") or 0))
        gross += fee
        if payer["pricing_model"] == "PROVIDER_FUNDED":
            provider_funded_fees[payer_id] = provider_funded_fees.get(payer_id, 0) + fee
    return gross, provider_funded_fees


def _recompute_volume_tier(provider, finalized_invoice):
    """trailing = this period + two prior FINALIZED periods' billable_units."""
    period = finalized_invoice["period_yyyy_mm"]
    year, month = int(period[:4]), int(period[5:7])

    def prior_period(y, m, n):
        for _ in range(n):
            m -= 1
            if m == 0:
                m = 12
                y -= 1
        return f"{y:04d}-{m:02d}"

    periods = {period, prior_period(year, month, 1), prior_period(year, month, 2)}
    trailing = 0
    for inv in db["invoices"].values():
        if (inv["provider_id"] == provider["id"] and inv["period_yyyy_mm"] in periods
                and inv["status"] in ("FINALIZED", "PAID")):
            trailing += inv["billable_units"]
    provider["trailing_billable_units_3m"] = trailing
    if trailing >= TIER_3_FLOOR:
        provider["volume_tier_code"] = "TIER_3"
    elif trailing >= TIER_2_FLOOR:
        provider["volume_tier_code"] = "TIER_2"
    else:
        provider["volume_tier_code"] = "TIER_1"


def _recompute_account_balance(provider):
    """Balance is maintained incrementally: finalization adds amount_due_cents,
    record-payment subtracts it; OPEN and VOID invoices contribute nothing.
    Negative values are credits in the provider's favor."""
    return provider.get("account_balance_cents", 0)


@app.post("/clearinghouse/providers/<provider_id>/usage-invoices")
def create_usage_invoice(provider_id):
    require_roles("ClearinghouseOps")
    get_provider_or_404(provider_id)
    data = body()
    period = data.get("period_yyyy_mm")
    if not isinstance(period, str) or not PERIOD_RE.fullmatch(period):
        raise err_invalid_request("period_yyyy_mm must be in YYYY-MM format")
    for inv in db["invoices"].values():
        if inv["provider_id"] == provider_id and inv["period_yyyy_mm"] == period:
            raise err_invalid_request("period_yyyy_mm must be unique per provider")
    inv = stamp_new({
        "provider_id": provider_id,
        "period_yyyy_mm": period,
        "claim_units": 0,
        "eligibility_units": 0,
        "remittance_units": 0,
        "billable_units": 0,
        "gross_fee_cents": 0,
        "monthly_minimum_applied_cents": 0,
        "amount_due_cents": 0,
        "status": "OPEN",
    })
    db["invoices"][inv["id"]] = inv
    return ok_object(ser_invoice(inv), status=201)


@app.get("/clearinghouse/providers/<provider_id>/usage-invoices")
def list_usage_invoices(provider_id):
    require_roles("ProviderAdmin", "ClearinghouseOps")
    get_provider_or_404(provider_id)
    items = [v for v in db["invoices"].values() if v["provider_id"] == provider_id]
    items = _apply_filters(items, {
        "status": request.args.get("status"),
        "period_yyyy_mm": request.args.get("period_yyyy_mm"),
    })
    for v in items:
        sync_invoice_counters(v)
    return ok_list([ser_invoice(v) for v in _sorted_by_created(items)])


@app.get("/clearinghouse/usage-invoices/<invoice_id>")
def get_usage_invoice(invoice_id):
    require_roles("ProviderAdmin", "ClearinghouseOps")
    inv = get_invoice_or_404(invoice_id)
    sync_invoice_counters(inv)
    return ok_object(ser_invoice(inv))


@app.get("/clearinghouse/usage-invoices")
def list_all_usage_invoices():
    require_roles("ClearinghouseOps", "ProviderAdmin")
    items = list(db["invoices"].values())
    items = _apply_filters(items, {
        "provider_id": request.args.get("provider_id"),
        "period_yyyy_mm": request.args.get("period_yyyy_mm"),
        "status": request.args.get("status"),
    })
    for v in items:
        sync_invoice_counters(v)
    return ok_list([ser_invoice(v) for v in _sorted_by_created(items)])


@app.post("/clearinghouse/usage-invoices/<invoice_id>/finalize")
def finalize_invoice(invoice_id):
    require_roles("ClearinghouseOps")
    inv = get_invoice_or_404(invoice_id)
    data = body()
    expected_version = data.get("expected_invoice_version")
    if inv["status"] != "OPEN":
        raise err_invalid_state("invoice is not OPEN")
    current = current_period(now())
    if current <= inv["period_yyyy_mm"]:
        raise ApiError("ERR_PERIOD_NOT_CLOSED", 409,
                       "billing period has not ended on the logical clock")
    if expected_version is None or not isinstance(expected_version, int) \
            or expected_version != inv["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_invoice_version does not match current version")
    sync_invoice_counters(inv)
    gross, provider_funded_fees = _invoice_fee_breakdown(inv)
    minimum_applied = 0
    for payer_id, fee in provider_funded_fees.items():
        payer = db["payers"].get(payer_id)
        if payer is None:
            continue
        shortfall = payer.get("monthly_minimum_cents", 0) - fee
        if shortfall > 0:
            minimum_applied += shortfall
    inv["gross_fee_cents"] = gross
    inv["monthly_minimum_applied_cents"] = minimum_applied
    inv["amount_due_cents"] = gross + minimum_applied
    inv["status"] = "FINALIZED"
    touch(inv)
    provider = get_provider_or_404(inv["provider_id"])
    provider["account_balance_cents"] = provider.get("account_balance_cents", 0) + inv["amount_due_cents"]
    _recompute_volume_tier(provider, inv)
    touch(provider)
    return ok_object(ser_invoice(inv))


@app.post("/clearinghouse/usage-invoices/<invoice_id>/record-payment")
def record_payment(invoice_id):
    require_roles("ClearinghouseOps")
    inv = get_invoice_or_404(invoice_id)
    data = body()
    payment = data.get("payment_amount_cents")
    if inv["status"] != "FINALIZED":
        raise err_invalid_state("invoice is not FINALIZED")
    if not isinstance(payment, int) or isinstance(payment, bool):
        raise err_invalid_request("payment_amount_cents must be an integer")
    if payment != inv["amount_due_cents"]:
        raise ApiError("ERR_PAYMENT_AMOUNT_MISMATCH", 422,
                       "payment_amount_cents must equal amount_due_cents")
    inv["status"] = "PAID"
    touch(inv)
    provider = get_provider_or_404(inv["provider_id"])
    provider["account_balance_cents"] = provider.get("account_balance_cents", 0) - inv["amount_due_cents"]
    touch(provider)
    return ok_object(ser_invoice(inv))


@app.post("/clearinghouse/usage-invoices/<invoice_id>/void")
def void_invoice(invoice_id):
    require_roles("ClearinghouseOps")
    inv = get_invoice_or_404(invoice_id)
    if inv["status"] != "OPEN":
        raise err_invalid_state("invoice is not OPEN")
    sync_invoice_counters(inv)
    gross, _ = _invoice_fee_breakdown(inv)
    if inv["claim_units"] != 0 or inv["eligibility_units"] != 0 or inv["remittance_units"] != 0 or gross != 0:
        raise err_invalid_state("invoice has recorded units")
    inv["status"] = "VOID"
    touch(inv)
    return ok_object(ser_invoice(inv))


# =============================================================================
# Entry point
# =============================================================================

if __name__ == "__main__":
    import os
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
