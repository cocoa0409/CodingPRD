"""Shared helpers: validation, serialization, lookups, policy mutation."""
import math
from datetime import datetime, timezone, timedelta

from db import STORE, new_id, parse_dt, fmt_dt
from errors import ApiError, invalid_request, not_found


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

def stamp(dt):
    return fmt_dt(dt)


def try_parse_dt(value):
    try:
        return parse_dt(value)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Field validation helpers
# ---------------------------------------------------------------------------

def get_body():
    from flask import request
    body = request.get_json(silent=True)
    if body is None or not isinstance(body, dict):
        raise invalid_request("Request body must be a JSON object")
    return body


def req_field(body, name):
    if name not in body or body[name] is None:
        raise invalid_request(f"Missing required field: {name}")
    return body[name]


def opt_field(body, name, default=None):
    v = body.get(name, default)
    if v is None:
        return default
    return v


def req_str(body, name):
    v = req_field(body, name)
    if not isinstance(v, str):
        raise invalid_request(f"Field {name} must be a string")
    return v


def req_int(body, name):
    v = req_field(body, name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise invalid_request(f"Field {name} must be an integer")
    return v


def opt_int(body, name, default):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, int):
        raise invalid_request(f"Field {name} must be an integer")
    return v


def req_bool(body, name):
    v = req_field(body, name)
    if not isinstance(v, bool):
        raise invalid_request(f"Field {name} must be a boolean")
    return v


def req_number(body, name):
    v = req_field(body, name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise invalid_request(f"Field {name} must be a number")
    return v


def req_dt(body, name):
    v = req_field(body, name)
    dt = try_parse_dt(v)
    if dt is None:
        raise invalid_request(f"Field {name} must be an ISO8601 datetime")
    return dt


def req_enum(body, name, allowed):
    v = req_field(body, name)
    if not isinstance(v, str) or v not in allowed:
        raise invalid_request(f"Field {name} must be one of {sorted(allowed)}")
    return v


def req_range(body, start_name, end_name):
    s = req_dt(body, start_name)
    e = req_dt(body, end_name)
    if not s < e:
        raise invalid_request(f"{start_name} must be strictly before {end_name}")
    return s, e


def get_limit_offset():
    from flask import request
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise invalid_request("limit must be an integer")
        if limit < 1 or limit > 100:
            raise invalid_request("limit must be between 1 and 100")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise invalid_request("offset must be an integer")
        if offset < 0:
            raise invalid_request("offset must be >= 0")
    return limit, offset


# ---------------------------------------------------------------------------
# Entity construction and lookup
# ---------------------------------------------------------------------------

def base_record():
    now = STORE.now()
    return {
        "id": new_id(),
        "created_at": stamp(now),
        "updated_at": stamp(now),
        "version": 1,
    }


def touch(rec):
    rec["updated_at"] = stamp(STORE.now())
    rec["version"] += 1


def get_employer_or_404(eid):
    e = STORE.employers.get(eid)
    if e is None:
        raise not_found("Employer not found")
    return e


def get_table_or_404(tid):
    t = STORE.rating_tables.get(tid)
    if t is None:
        raise not_found("StateRatingTable not found")
    return t


def get_policy_or_404(pid):
    p = STORE.policies.get(pid)
    if p is None:
        raise not_found("Policy not found")
    return p


def get_class_code_or_404(cid):
    c = STORE.class_codes.get(cid)
    if c is None:
        raise not_found("PolicyClassCode not found")
    return c


def get_report_or_404(rid):
    r = STORE.reports.get(rid)
    if r is None:
        raise not_found("PayrollReport not found")
    return r


def get_invoice_or_404(iid):
    inv = STORE.invoices.get(iid)
    if inv is None:
        raise not_found("PremiumInvoice not found")
    return inv


def get_dispute_or_404(did):
    d = STORE.disputes.get(did)
    if d is None:
        raise not_found("ClassCodeDispute not found")
    return d


def get_audit_or_404(aid):
    a = STORE.audits.get(aid)
    if a is None:
        raise not_found("AuditReconciliation not found")
    return a


def get_integration_or_404(iid):
    integ = STORE.integrations.get(iid)
    if integ is None:
        raise not_found("PayrollIntegration not found")
    return integ


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def ser_employer(e):
    return {
        "id": e["id"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
        "legal_name": e["legal_name"],
        "fein": e["fein"],
        "contact_email": e["contact_email"],
        "home_state": e["home_state"],
        "status": e["status"],
    }


def ser_table(t):
    return {
        "id": t["id"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
        "state_code": t["state_code"],
        "effective_from": t["effective_from"],
        "effective_to": t["effective_to"],
        "monopolistic": t["monopolistic"],
        "per_capita_admin_fee_cents": t["per_capita_admin_fee_cents"],
        "expense_constant_cents": t["expense_constant_cents"],
        "min_payroll_threshold_cents": t["min_payroll_threshold_cents"],
        "state_minimum_premium_cents": t["state_minimum_premium_cents"],
        "ot_basis": t["ot_basis"],
        "class_rates": t["class_rates"],
        "max_payroll_per_executive_cents": t["max_payroll_per_executive_cents"],
    }


def ser_policy(p):
    return {
        "id": p["id"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
        "employer_id": p["employer_id"],
        "policy_number": p["policy_number"],
        "effective_date": p["effective_date"],
        "expiry_date": p["expiry_date"],
        "experience_mod": p["experience_mod"],
        "coverage_status": p["coverage_status"],
        "reporting_status": p["reporting_status"],
        "billing_status": p["billing_status"],
        "last_report_received_at": p["last_report_received_at"],
        "consecutive_missed_cycles": p["consecutive_missed_cycles"],
        "cumulative_billed_cents": p["cumulative_billed_cents"],
        "cumulative_collected_cents": p["cumulative_collected_cents"],
    }


def ser_class_code(c):
    return {
        "id": c["id"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
        "policy_id": c["policy_id"],
        "state_code": c["state_code"],
        "class_code": c["class_code"],
        "estimated_annual_payroll_cents": c["estimated_annual_payroll_cents"],
        "effective_from": c["effective_from"],
        "assignment_status": c["assignment_status"],
    }


def ser_integration(i):
    return {
        "id": i["id"],
        "created_at": i["created_at"],
        "updated_at": i["updated_at"],
        "version": i["version"],
        "policy_id": i["policy_id"],
        "provider": i["provider"],
        "connection_status": i["connection_status"],
        "last_heartbeat_at": i["last_heartbeat_at"],
    }


def ser_report(r):
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
        "policy_id": r["policy_id"],
        "period_start": r["period_start"],
        "period_end": r["period_end"],
        "status": r["status"],
        "failure_code": r["failure_code"],
        "submitted_by": r["submitted_by"],
        "idempotency_key": r["idempotency_key"],
    }


def ser_line(l):
    return {
        "id": l["id"],
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
        "version": l["version"],
        "payroll_report_id": l["payroll_report_id"],
        "state_code": l["state_code"],
        "class_code": l["class_code"],
        "gross_wages_cents": l["gross_wages_cents"],
        "ot_premium_cents": l["ot_premium_cents"],
        "severance_cents": l["severance_cents"],
        "executive_wages_cents": l["executive_wages_cents"],
        "headcount": l["headcount"],
        "remuneration_basis_cents": l["remuneration_basis_cents"],
    }


def ser_invoice(inv):
    return {
        "id": inv["id"],
        "created_at": inv["created_at"],
        "updated_at": inv["updated_at"],
        "version": inv["version"],
        "policy_id": inv["policy_id"],
        "payroll_report_id": inv["payroll_report_id"],
        "kind": inv["kind"],
        "status": inv["status"],
        "manual_premium_cents": inv["manual_premium_cents"],
        "experience_mod_applied": inv["experience_mod_applied"],
        "premium_after_mod_cents": inv["premium_after_mod_cents"],
        "per_capita_fees_cents": inv["per_capita_fees_cents"],
        "expense_constant_cents": inv["expense_constant_cents"],
        "total_cents": inv["total_cents"],
        "due_date": inv["due_date"],
    }


def ser_dispute(d):
    return {
        "id": d["id"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
        "policy_id": d["policy_id"],
        "policy_class_code_id": d["policy_class_code_id"],
        "requested_class_code": d["requested_class_code"],
        "effective_from": d["effective_from"],
        "supersedes_dispute_id": d["supersedes_dispute_id"],
        "status": d["status"],
        "resolution_reason": d["resolution_reason"],
        "filed_by": d["filed_by"],
        "decided_by": d["decided_by"],
    }


def ser_audit(a):
    return {
        "id": a["id"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
        "policy_id": a["policy_id"],
        "period_start": a["period_start"],
        "period_end": a["period_end"],
        "status": a["status"],
        "filed_by": a["filed_by"],
        "verified_by": a["verified_by"],
        "reported_payroll_cents": a["reported_payroll_cents"],
        "filing_payroll_cents": a["filing_payroll_cents"],
        "variance_cents": a["variance_cents"],
        "trueup_invoice_id": a["trueup_invoice_id"],
    }


def ser_tax_filing(t):
    return {
        "id": t["id"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
        "policy_id": t["policy_id"],
        "state_code": t["state_code"],
        "quarter": t["quarter"],
        "period_start": t["period_start"],
        "period_end": t["period_end"],
        "reported_wages_cents": t["reported_wages_cents"],
        "source": t["source"],
    }


# ---------------------------------------------------------------------------
# Policy helpers
# ---------------------------------------------------------------------------

def policy_class_codes(policy_id):
    return [c for c in STORE.class_codes.values() if c["policy_id"] == policy_id]


def policy_reports(policy_id):
    return [r for r in STORE.reports.values() if r["policy_id"] == policy_id]


def policy_invoices(policy_id):
    return [i for i in STORE.invoices.values() if i["policy_id"] == policy_id]


def policy_disputes(policy_id):
    return [d for d in STORE.disputes.values() if d["policy_id"] == policy_id]


def policy_audits(policy_id):
    return [a for a in STORE.audits.values() if a["policy_id"] == policy_id]


def policy_tax_filings(policy_id):
    return [t for t in STORE.tax_filings.values() if t["policy_id"] == policy_id]


def policy_integration(policy_id):
    for i in STORE.integrations.values():
        if i["policy_id"] == policy_id:
            return i
    return None


def recompute_policy_aggregates(p):
    billed = 0
    collected = 0
    for inv in STORE.invoices.values():
        if inv["policy_id"] != p["id"]:
            continue
        if inv["status"] in ("ISSUED", "PAID"):
            billed += inv["total_cents"]
        if inv["status"] == "PAID":
            collected += inv["total_cents"]
    p["cumulative_billed_cents"] = billed
    p["cumulative_collected_cents"] = collected


def mutate_policy(p):
    """Recompute aggregates, refresh updated_at, bump version."""
    recompute_policy_aggregates(p)
    touch(p)


def table_effective_at(state_code, instant):
    """Rating table for state whose half-open interval contains instant."""
    for t in STORE.rating_tables.values():
        if t["state_code"] != state_code:
            continue
        if t["_from"] <= instant < t["_to"]:
            return t
    return None


def tables_covering_period(state_code, start, end):
    """All tables for state intersecting [start, end), ordered by effective_from."""
    ts = [
        t for t in STORE.rating_tables.values()
        if t["state_code"] == state_code and t["_from"] < end and t["_to"] > start
    ]
    ts.sort(key=lambda t: t["_from"])
    return ts


def period_fully_covered(state_code, start, end):
    """Whether tables for state cover the whole half-open period [start, end)."""
    tables = tables_covering_period(state_code, start, end)
    if not tables:
        return False
    # Must cover from start through end with no gaps; intervals for a state never overlap.
    covered_from = start
    for t in tables:
        if t["_from"] > covered_from:
            return False
        if t["_to"] > covered_from:
            covered_from = t["_to"]
        if covered_from >= end:
            return True
    return covered_from >= end


def weeks_in_period(start_dt, end_dt):
    days = (end_dt - start_dt).total_seconds() / 86400.0
    return math.ceil(days / 7.0 - 1e-12)


# ---------------------------------------------------------------------------
# List helpers
# ---------------------------------------------------------------------------

def sort_key(rec):
    return (rec["created_at"], rec.get("_seq", 0))


def sorted_list(records):
    return sorted(records, key=sort_key)


def paginate(records, limit, offset):
    total = len(records)
    return records[offset:offset + limit], total
