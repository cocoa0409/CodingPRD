"""All API routes."""
from flask import Blueprint, request

from db import STORE, parse_dt
from errors import (
    ApiError, invalid_request, invalid_state, not_found, forbidden,
    stale_version,
    ERR_MONOPOLISTIC_STATE_EXCLUDED, ERR_RATING_TABLE_OVERLAP,
    ERR_RETRO_WINDOW_INVALID, ERR_PAYMENT_AMOUNT_MISMATCH,
    ERR_SEGREGATION_OF_DUTIES,
)
from middleware import require_roles
from response import success_object, success_list
from helpers import (
    base_record, touch, stamp, get_body, req_str, req_int, req_bool,
    req_number, req_dt, req_enum, get_limit_offset,
    get_employer_or_404, get_table_or_404, get_policy_or_404,
    get_report_or_404, get_invoice_or_404, get_dispute_or_404,
    get_audit_or_404, get_integration_or_404,
    policy_class_codes, policy_reports, policy_invoices, policy_disputes,
    policy_audits, policy_tax_filings, policy_integration,
    mutate_policy, recompute_policy_aggregates, sorted_list, paginate,
    tables_covering_period,
    ser_employer, ser_table, ser_policy, ser_class_code, ser_integration,
    ser_report, ser_line, ser_invoice, ser_dispute, ser_audit, ser_tax_filing,
)
from workflows import (
    submit_payroll_report, reevaluate_billing, decide_dispute,
    open_audit, file_audit, verify_audit, maybe_close_audit,
    cancel_policy, run_sweep, report_lines,
)

bp = Blueprint("api", __name__)


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_roles("PlatformAdmin")
    body = get_body()
    current = req_dt(body, "current_utc")
    STORE.set_clock(current)
    run_sweep()
    return success_object({"current_utc": stamp(STORE.now())})


# ---------------------------------------------------------------------------
# Employers
# ---------------------------------------------------------------------------

@bp.route("/wc/employers", methods=["POST"])
def create_employer():
    require_roles("PlatformAdmin")
    body = get_body()
    e = base_record()
    e.update({
        "legal_name": req_str(body, "legal_name"),
        "fein": req_str(body, "fein"),
        "contact_email": req_str(body, "contact_email"),
        "home_state": req_str(body, "home_state"),
        "status": "ACTIVE",
    })
    STORE.register("employers", e)
    return success_object(ser_employer(e), status=201)


@bp.route("/wc/employers", methods=["GET"])
def list_employers():
    require_roles("PlatformAdmin", "Underwriter")
    limit, offset = get_limit_offset()
    items = sorted_list(list(STORE.employers.values()))
    page, total = paginate(items, limit, offset)
    return success_list([ser_employer(e) for e in page], limit, offset, total)


@bp.route("/wc/employers/<eid>", methods=["GET"])
def get_employer(eid):
    user_id, role = require_roles("PlatformAdmin", "Underwriter", "EmployerAdmin")
    e = get_employer_or_404(eid)
    if role == "EmployerAdmin" and e["id"] != user_id:
        raise forbidden()
    return success_object(ser_employer(e))


@bp.route("/wc/employers/<eid>/policies", methods=["GET"])
def list_employer_policies(eid):
    user_id, role = require_roles("PlatformAdmin", "Underwriter", "EmployerAdmin")
    e = get_employer_or_404(eid)
    if role == "EmployerAdmin" and e["id"] != user_id:
        raise forbidden()
    limit, offset = get_limit_offset()
    items = sorted_list([p for p in STORE.policies.values() if p["employer_id"] == eid])
    page, total = paginate(items, limit, offset)
    return success_list([ser_policy(p) for p in page], limit, offset, total)


# ---------------------------------------------------------------------------
# State rating tables
# ---------------------------------------------------------------------------

@bp.route("/wc/state-rating-tables", methods=["POST"])
def create_table():
    require_roles("PlatformAdmin")
    body = get_body()
    state_code = req_str(body, "state_code")
    eff_from = req_dt(body, "effective_from")
    eff_to = req_dt(body, "effective_to")
    if not eff_from < eff_to:
        raise invalid_request("effective_from must be strictly before effective_to")
    monopolistic = req_bool(body, "monopolistic")
    per_capita = req_int(body, "per_capita_admin_fee_cents")
    expense_constant = req_int(body, "expense_constant_cents")
    min_threshold = req_int(body, "min_payroll_threshold_cents")
    state_min_premium = req_int(body, "state_minimum_premium_cents")
    ot_basis = req_enum(body, "ot_basis", {"GROSS", "NET"})
    max_exec = req_int(body, "max_payroll_per_executive_cents")
    class_rates = body.get("class_rates")
    if not isinstance(class_rates, list):
        raise invalid_request("Field class_rates must be an array")
    seen = set()
    parsed_rates = []
    for entry in class_rates:
        if not isinstance(entry, dict):
            raise invalid_request("class_rates entries must be objects")
        cc = entry.get("class_code")
        rate = entry.get("rate_per_100_cents")
        if not isinstance(cc, str):
            raise invalid_request("class_rates entry class_code must be a string")
        if isinstance(rate, bool) or not isinstance(rate, int):
            raise invalid_request("class_rates entry rate_per_100_cents must be an integer")
        if cc in seen:
            raise ApiError(ERR_RATING_TABLE_OVERLAP,
                           "class_code appears more than once in class_rates", 409)
        seen.add(cc)
        parsed_rates.append({"class_code": cc, "rate_per_100_cents": rate})

    for t in STORE.rating_tables.values():
        if t["state_code"] != state_code:
            continue
        if t["_from"] < eff_to and eff_from < t["_to"]:
            raise ApiError(ERR_RATING_TABLE_OVERLAP,
                           "Rating table interval overlaps an existing table for this state",
                           409)

    t = base_record()
    t.update({
        "state_code": state_code,
        "effective_from": stamp(eff_from),
        "effective_to": stamp(eff_to),
        "monopolistic": monopolistic,
        "per_capita_admin_fee_cents": per_capita,
        "expense_constant_cents": expense_constant,
        "min_payroll_threshold_cents": min_threshold,
        "state_minimum_premium_cents": state_min_premium,
        "ot_basis": ot_basis,
        "class_rates": parsed_rates,
        "max_payroll_per_executive_cents": max_exec,
        "_from": eff_from,
        "_to": eff_to,
    })
    STORE.register("rating_tables", t)
    return success_object(ser_table(t), status=201)


@bp.route("/wc/state-rating-tables", methods=["GET"])
def list_tables():
    require_roles("PlatformAdmin", "Underwriter", "EmployerAdmin",
                  "PayrollProvider", "TaxFiler", "Auditor")
    limit, offset = get_limit_offset()
    state_filter = request.args.get("state_code")
    items = list(STORE.rating_tables.values())
    if state_filter is not None:
        items = [t for t in items if t["state_code"] == state_filter]
    items = sorted_list(items)
    page, total = paginate(items, limit, offset)
    return success_list([ser_table(t) for t in page], limit, offset, total)


@bp.route("/wc/state-rating-tables/<tid>", methods=["GET"])
def get_table(tid):
    require_roles("PlatformAdmin", "Underwriter")
    t = get_table_or_404(tid)
    return success_object(ser_table(t))


# ---------------------------------------------------------------------------
# Policies
# ---------------------------------------------------------------------------

@bp.route("/wc/policies", methods=["POST"])
def create_policy():
    require_roles("Underwriter")
    body = get_body()
    employer_id = req_str(body, "employer_id")
    employer = STORE.employers.get(employer_id)
    if employer is None:
        raise not_found("Employer not found")
    policy_number = req_str(body, "policy_number")
    effective_date = req_dt(body, "effective_date")
    expiry_date = req_dt(body, "expiry_date")
    if not effective_date < expiry_date:
        raise invalid_request("effective_date must be strictly before expiry_date")
    experience_mod = req_number(body, "experience_mod")
    class_codes_in = body.get("class_codes")
    if not isinstance(class_codes_in, list):
        raise invalid_request("Field class_codes must be an array")
    parsed = []
    for entry in class_codes_in:
        if not isinstance(entry, dict):
            raise invalid_request("class_codes entries must be objects")
        sc = entry.get("state_code")
        cc = entry.get("class_code")
        est = entry.get("estimated_annual_payroll_cents")
        if not isinstance(sc, str) or not isinstance(cc, str):
            raise invalid_request("class_codes entries require state_code and class_code strings")
        if isinstance(est, bool) or not isinstance(est, int):
            raise invalid_request("estimated_annual_payroll_cents must be an integer")
        parsed.append({"state_code": sc, "class_code": cc,
                       "estimated_annual_payroll_cents": est})

    # Monopolistic exclusion at creation: an assignment state whose governing
    # rating table at the policy effective date is monopolistic is refused.
    for entry in parsed:
        from helpers import table_effective_at, tables_covering_period
        t = table_effective_at(entry["state_code"], effective_date)
        if t is None:
            covering = tables_covering_period(entry["state_code"], effective_date, expiry_date)
            if any(x["monopolistic"] for x in covering):
                raise ApiError(ERR_MONOPOLISTIC_STATE_EXCLUDED,
                               "Class assignment references a monopolistic state", 422)
            continue
        if t["monopolistic"]:
            raise ApiError(ERR_MONOPOLISTIC_STATE_EXCLUDED,
                           "Class assignment references a monopolistic state", 422)

    p = base_record()
    p.update({
        "employer_id": employer_id,
        "policy_number": policy_number,
        "effective_date": stamp(effective_date),
        "expiry_date": stamp(expiry_date),
        "experience_mod": experience_mod,
        "coverage_status": "PENDING",
        "reporting_status": "COMPLIANT",
        "billing_status": "CURRENT",
        "last_report_received_at": None,
        "consecutive_missed_cycles": 0,
        "cumulative_billed_cents": 0,
        "cumulative_collected_cents": 0,
        "_non_reporting_since": None,
    })
    STORE.register("policies", p)

    for entry in parsed:
        c = base_record()
        c.update({
            "policy_id": p["id"],
            "state_code": entry["state_code"],
            "class_code": entry["class_code"],
            "estimated_annual_payroll_cents": entry["estimated_annual_payroll_cents"],
            "effective_from": stamp(effective_date),
            "assignment_status": "ACTIVE",
        })
        STORE.register("class_codes", c)

    return success_object(ser_policy(p), status=201)


@bp.route("/wc/policies", methods=["GET"])
def list_policies():
    user_id, role = require_roles("Underwriter", "EmployerAdmin", "Auditor", "TaxFiler")
    limit, offset = get_limit_offset()
    items = list(STORE.policies.values())
    employer_filter = request.args.get("employer_id")
    coverage_filter = request.args.get("coverage_status")
    if role == "EmployerAdmin":
        items = [p for p in items if p["employer_id"] == user_id]
    if employer_filter is not None:
        items = [p for p in items if p["employer_id"] == employer_filter]
    if coverage_filter is not None:
        items = [p for p in items if p["coverage_status"] == coverage_filter]
    items = sorted_list(items)
    page, total = paginate(items, limit, offset)
    return success_list([ser_policy(p) for p in page], limit, offset, total)


@bp.route("/wc/policies/<pid>", methods=["GET"])
def get_policy(pid):
    user_id, role = require_roles("Underwriter", "EmployerAdmin", "Auditor",
                                  "TaxFiler", "PayrollProvider")
    p = get_policy_or_404(pid)
    if role == "EmployerAdmin" and p["employer_id"] != user_id:
        raise forbidden()
    return success_object(ser_policy(p))


@bp.route("/wc/policies/<pid>/bind", methods=["POST"])
def bind_policy(pid):
    require_roles("Underwriter")
    p = get_policy_or_404(pid)
    get_body()
    if p["coverage_status"] != "PENDING":
        raise invalid_state("Policy is not in PENDING")
    assignments = policy_class_codes(pid)
    for c in assignments:
        sc = c["state_code"]
        covering = tables_covering_period(sc, parse_dt(p["effective_date"]),
                                          parse_dt(p["expiry_date"]))
        if any(t["monopolistic"] for t in covering):
            raise ApiError(ERR_MONOPOLISTIC_STATE_EXCLUDED,
                           "Class assignment references a monopolistic state", 422)
    active = [c for c in assignments if c["assignment_status"] == "ACTIVE"]
    if not active:
        raise ApiError(ERR_MONOPOLISTIC_STATE_EXCLUDED,
                       "Policy has no ACTIVE class assignment to bind", 422)
    now = STORE.now()
    if not (parse_dt(p["effective_date"]) <= now < parse_dt(p["expiry_date"])):
        raise invalid_state("Logical clock is outside the policy term")

    p["coverage_status"] = "ACTIVE"
    mutate_policy(p)

    integ = base_record()
    integ.update({
        "policy_id": p["id"],
        "provider": None,
        "connection_status": "CONNECTED",
        "last_heartbeat_at": stamp(now),
    })
    STORE.register("integrations", integ)
    return success_object(ser_policy(p))


@bp.route("/wc/policies/<pid>/cancel", methods=["POST"])
def cancel_policy_route(pid):
    require_roles("Underwriter")
    p = get_policy_or_404(pid)
    get_body()
    if p["coverage_status"] != "ACTIVE":
        raise invalid_state("Policy coverage is not ACTIVE")
    cancel_policy(p)
    return success_object(ser_policy(p))


@bp.route("/wc/policies/<pid>/class-codes", methods=["GET"])
def list_policy_class_codes(pid):
    user_id, role = require_roles("Underwriter", "EmployerAdmin", "PayrollProvider")
    p = get_policy_or_404(pid)
    if role == "EmployerAdmin" and p["employer_id"] != user_id:
        raise forbidden()
    limit, offset = get_limit_offset()
    items = sorted_list(policy_class_codes(pid))
    page, total = paginate(items, limit, offset)
    return success_list([ser_class_code(c) for c in page], limit, offset, total)


@bp.route("/wc/policies/<pid>/reports", methods=["GET"])
def list_policy_reports(pid):
    user_id, role = require_roles("Underwriter", "EmployerAdmin", "PayrollProvider", "Auditor")
    p = get_policy_or_404(pid)
    if role == "EmployerAdmin" and p["employer_id"] != user_id:
        raise forbidden()
    limit, offset = get_limit_offset()
    status_filter = request.args.get("status")
    items = policy_reports(pid)
    if status_filter is not None:
        items = [r for r in items if r["status"] == status_filter]
    items = sorted_list(items)
    page, total = paginate(items, limit, offset)
    return success_list([ser_report(r) for r in page], limit, offset, total)


@bp.route("/wc/policies/<pid>/invoices", methods=["GET"])
def list_policy_invoices(pid):
    user_id, role = require_roles("Underwriter", "EmployerAdmin", "Auditor")
    p = get_policy_or_404(pid)
    if role == "EmployerAdmin" and p["employer_id"] != user_id:
        raise forbidden()
    limit, offset = get_limit_offset()
    status_filter = request.args.get("status")
    kind_filter = request.args.get("kind")
    items = policy_invoices(pid)
    if status_filter is not None:
        items = [i for i in items if i["status"] == status_filter]
    if kind_filter is not None:
        items = [i for i in items if i["kind"] == kind_filter]
    items = sorted_list(items)
    page, total = paginate(items, limit, offset)
    return success_list([ser_invoice(i) for i in page], limit, offset, total)


@bp.route("/wc/policies/<pid>/disputes", methods=["GET"])
def list_policy_disputes(pid):
    user_id, role = require_roles("Underwriter", "EmployerAdmin")
    p = get_policy_or_404(pid)
    if role == "EmployerAdmin" and p["employer_id"] != user_id:
        raise forbidden()
    limit, offset = get_limit_offset()
    status_filter = request.args.get("status")
    items = policy_disputes(pid)
    if status_filter is not None:
        items = [d for d in items if d["status"] == status_filter]
    items = sorted_list(items)
    page, total = paginate(items, limit, offset)
    return success_list([ser_dispute(d) for d in page], limit, offset, total)


@bp.route("/wc/policies/<pid>/audits", methods=["GET"])
def list_policy_audits(pid):
    require_roles("Underwriter", "Auditor", "TaxFiler")
    get_policy_or_404(pid)
    limit, offset = get_limit_offset()
    status_filter = request.args.get("status")
    items = policy_audits(pid)
    if status_filter is not None:
        items = [a for a in items if a["status"] == status_filter]
    items = sorted_list(items)
    page, total = paginate(items, limit, offset)
    return success_list([ser_audit(a) for a in page], limit, offset, total)


@bp.route("/wc/policies/<pid>/tax-filings", methods=["GET"])
def list_policy_tax_filings(pid):
    require_roles("Underwriter", "Auditor", "TaxFiler")
    get_policy_or_404(pid)
    limit, offset = get_limit_offset()
    items = sorted_list(policy_tax_filings(pid))
    page, total = paginate(items, limit, offset)
    return success_list([ser_tax_filing(t) for t in page], limit, offset, total)


@bp.route("/wc/policies/<pid>/integration", methods=["GET"])
def get_policy_integration(pid):
    user_id, role = require_roles("Underwriter", "EmployerAdmin", "PayrollProvider")
    p = get_policy_or_404(pid)
    if role == "EmployerAdmin" and p["employer_id"] != user_id:
        raise forbidden()
    integ = policy_integration(pid)
    items = [ser_integration(integ)] if integ is not None else []
    limit, offset = get_limit_offset()
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


# ---------------------------------------------------------------------------
# Payroll reports
# ---------------------------------------------------------------------------

@bp.route("/wc/payroll-reports", methods=["POST"])
def create_payroll_report():
    user_id, role = require_roles("PayrollProvider")
    body = get_body()
    report, status_override = submit_payroll_report(body, user_id)
    status_code = status_override if status_override is not None else 201
    # status_override None means idempotent replay: return original as it stands
    # with its original creation semantics (201 for ACCEPTED, 200 for REJECTED).
    if status_override is None:
        status_code = 201 if report["status"] == "ACCEPTED" else 200
    return success_object(ser_report(report), status=status_code)


@bp.route("/wc/payroll-reports/<rid>", methods=["GET"])
def get_payroll_report(rid):
    user_id, role = require_roles("Underwriter", "EmployerAdmin", "PayrollProvider", "Auditor")
    r = get_report_or_404(rid)
    if role == "EmployerAdmin":
        p = STORE.policies.get(r["policy_id"])
        if p is None or p["employer_id"] != user_id:
            raise forbidden()
    return success_object(ser_report(r))


@bp.route("/wc/payroll-reports/<rid>/lines", methods=["GET"])
def get_payroll_report_lines(rid):
    user_id, role = require_roles("Underwriter", "EmployerAdmin", "PayrollProvider", "Auditor")
    r = get_report_or_404(rid)
    if role == "EmployerAdmin":
        p = STORE.policies.get(r["policy_id"])
        if p is None or p["employer_id"] != user_id:
            raise forbidden()
    limit, offset = get_limit_offset()
    items = sorted_list(report_lines(rid))
    page, total = paginate(items, limit, offset)
    return success_list([ser_line(l) for l in page], limit, offset, total)


@bp.route("/wc/payroll-reports/<rid>/invoices", methods=["GET"])
def get_payroll_report_invoices(rid):
    user_id, role = require_roles("Underwriter", "EmployerAdmin", "Auditor")
    r = get_report_or_404(rid)
    if role == "EmployerAdmin":
        p = STORE.policies.get(r["policy_id"])
        if p is None or p["employer_id"] != user_id:
            raise forbidden()
    limit, offset = get_limit_offset()
    items = sorted_list([i for i in STORE.invoices.values()
                         if i["payroll_report_id"] == rid])
    page, total = paginate(items, limit, offset)
    return success_list([ser_invoice(i) for i in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Invoices
# ---------------------------------------------------------------------------

@bp.route("/wc/invoices", methods=["GET"])
def list_invoices():
    user_id, role = require_roles("Underwriter", "EmployerAdmin", "Auditor")
    limit, offset = get_limit_offset()
    items = list(STORE.invoices.values())
    if role == "EmployerAdmin":
        items = [i for i in items
                 if STORE.policies.get(i["policy_id"]) is not None
                 and STORE.policies[i["policy_id"]]["employer_id"] == user_id]
    report_filter = request.args.get("payroll_report_id")
    status_filter = request.args.get("status")
    kind_filter = request.args.get("kind")
    if report_filter is not None:
        items = [i for i in items if i["payroll_report_id"] == report_filter]
    if status_filter is not None:
        items = [i for i in items if i["status"] == status_filter]
    if kind_filter is not None:
        items = [i for i in items if i["kind"] == kind_filter]
    items = sorted_list(items)
    page, total = paginate(items, limit, offset)
    return success_list([ser_invoice(i) for i in page], limit, offset, total)


@bp.route("/wc/invoices/<iid>", methods=["GET"])
def get_invoice(iid):
    user_id, role = require_roles("Underwriter", "EmployerAdmin", "Auditor")
    inv = get_invoice_or_404(iid)
    if role == "EmployerAdmin":
        p = STORE.policies.get(inv["policy_id"])
        if p is None or p["employer_id"] != user_id:
            raise forbidden()
    return success_object(ser_invoice(inv))


@bp.route("/wc/invoices/<iid>/payments", methods=["POST"])
def pay_invoice(iid):
    user_id, role = require_roles("EmployerAdmin")
    inv = get_invoice_or_404(iid)
    p = STORE.policies.get(inv["policy_id"])
    if p is None or p["employer_id"] != user_id:
        raise forbidden()
    body = get_body()
    amount = req_int(body, "amount_cents")
    if inv["status"] != "ISSUED":
        raise invalid_state("Invoice is not in ISSUED status")
    if amount != inv["total_cents"]:
        raise ApiError(ERR_PAYMENT_AMOUNT_MISMATCH,
                       "Payment amount must equal invoice total_cents exactly", 422)
    inv["status"] = "PAID"
    touch(inv)
    mutate_policy(p)
    reevaluate_billing(p)
    # Close any audits waiting on this true-up invoice (audit mutation does not
    # touch the policy, so the caller's observed policy version stays valid).
    for a in STORE.audits.values():
        if a.get("trueup_invoice_id") == inv["id"] and a["status"] == "VERIFIED":
            maybe_close_audit(a)
    return success_object(ser_invoice(inv))


@bp.route("/wc/invoices/<iid>/void", methods=["POST"])
def void_invoice_route(iid):
    require_roles("Underwriter")
    inv = get_invoice_or_404(iid)
    get_body()
    if inv["status"] == "PAID":
        raise invalid_state("A PAID invoice cannot be voided")
    if inv["status"] != "ISSUED":
        raise invalid_state("Invoice is not in ISSUED status")
    inv["status"] = "VOID"
    touch(inv)
    p = STORE.policies.get(inv["policy_id"])
    if p is not None:
        recompute_policy_aggregates(p)
        touch(p)
    return success_object(ser_invoice(inv))


# ---------------------------------------------------------------------------
# Disputes
# ---------------------------------------------------------------------------

@bp.route("/wc/disputes", methods=["POST"])
def create_dispute():
    user_id, role = require_roles("EmployerAdmin")
    body = get_body()
    policy_id = req_str(body, "policy_id")
    p = STORE.policies.get(policy_id)
    if p is None:
        raise not_found("Policy not found")
    if p["employer_id"] != user_id:
        raise forbidden()
    pcc_id = req_str(body, "policy_class_code_id")
    assignment = STORE.class_codes.get(pcc_id)
    if assignment is None or assignment["policy_id"] != policy_id:
        raise not_found("PolicyClassCode not found")
    requested = req_str(body, "requested_class_code")
    effective_from = req_dt(body, "effective_from")
    supersedes = body.get("supersedes_dispute_id")
    if supersedes is not None and not isinstance(supersedes, str):
        raise invalid_request("supersedes_dispute_id must be a string")

    if effective_from < parse_dt(p["effective_date"]) or effective_from >= STORE.now():
        raise ApiError(ERR_RETRO_WINDOW_INVALID,
                       "dispute effective_from outside [policy.effective_date, now)", 422)

    d = base_record()
    d.update({
        "policy_id": policy_id,
        "policy_class_code_id": pcc_id,
        "requested_class_code": requested,
        "effective_from": stamp(effective_from),
        "supersedes_dispute_id": supersedes,
        "status": "FILED",
        "resolution_reason": None,
        "filed_by": user_id,
        "decided_by": None,
    })
    STORE.register("disputes", d)
    return success_object(ser_dispute(d), status=201)


@bp.route("/wc/disputes", methods=["GET"])
def list_disputes():
    user_id, role = require_roles("Underwriter", "EmployerAdmin")
    limit, offset = get_limit_offset()
    items = list(STORE.disputes.values())
    if role == "EmployerAdmin":
        items = [d for d in items
                 if STORE.policies.get(d["policy_id"]) is not None
                 and STORE.policies[d["policy_id"]]["employer_id"] == user_id]
    pcc_filter = request.args.get("policy_class_code_id")
    supersedes_filter = request.args.get("supersedes_dispute_id")
    status_filter = request.args.get("status")
    if pcc_filter is not None:
        items = [d for d in items if d["policy_class_code_id"] == pcc_filter]
    if supersedes_filter is not None:
        items = [d for d in items if d["supersedes_dispute_id"] == supersedes_filter]
    if status_filter is not None:
        items = [d for d in items if d["status"] == status_filter]
    items = sorted_list(items)
    page, total = paginate(items, limit, offset)
    return success_list([ser_dispute(d) for d in page], limit, offset, total)


@bp.route("/wc/disputes/<did>", methods=["GET"])
def get_dispute(did):
    user_id, role = require_roles("Underwriter", "EmployerAdmin")
    d = get_dispute_or_404(did)
    if role == "EmployerAdmin":
        p = STORE.policies.get(d["policy_id"])
        if p is None or p["employer_id"] != user_id:
            raise forbidden()
    return success_object(ser_dispute(d))


@bp.route("/wc/disputes/<did>/open-review", methods=["POST"])
def open_review(did):
    require_roles("Underwriter")
    d = get_dispute_or_404(did)
    get_body()
    if d["status"] != "FILED":
        raise invalid_state("Dispute is not in FILED status")
    d["status"] = "UNDER_REVIEW"
    touch(d)
    assignment = STORE.class_codes.get(d["policy_class_code_id"])
    if assignment is not None and assignment["assignment_status"] == "ACTIVE":
        assignment["assignment_status"] = "DISPUTED"
        touch(assignment)
    return success_object(ser_dispute(d))


@bp.route("/wc/disputes/<did>/return-to-filed", methods=["POST"])
def return_to_filed(did):
    require_roles("Underwriter")
    d = get_dispute_or_404(did)
    get_body()
    if d["status"] != "UNDER_REVIEW":
        raise invalid_state("Dispute is not in UNDER_REVIEW status")
    d["status"] = "FILED"
    touch(d)
    assignment = STORE.class_codes.get(d["policy_class_code_id"])
    if assignment is not None and assignment["assignment_status"] == "DISPUTED":
        assignment["assignment_status"] = "ACTIVE"
        touch(assignment)
    return success_object(ser_dispute(d))


@bp.route("/wc/disputes/<did>/decide", methods=["POST"])
def decide(did):
    user_id, role = require_roles("Underwriter")
    d = get_dispute_or_404(did)
    body = get_body()
    decision = req_enum(body, "decision", {"APPROVED", "DENIED"})
    expected = body.get("expected_policy_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise invalid_request("expected_policy_version must be an integer")
    if d["status"] != "UNDER_REVIEW":
        raise invalid_state("Dispute is not in UNDER_REVIEW status")
    p = STORE.policies[d["policy_id"]]
    if expected != p["version"]:
        raise stale_version()
    if user_id == d["filed_by"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES,
                       "Decider must differ from the dispute filer", 403)
    decide_dispute(d, decision, user_id)
    return success_object(ser_dispute(d))


# ---------------------------------------------------------------------------
# Tax filings
# ---------------------------------------------------------------------------

@bp.route("/wc/tax-filings", methods=["POST"])
def create_tax_filing():
    require_roles("TaxFiler")
    body = get_body()
    policy_id = req_str(body, "policy_id")
    p = STORE.policies.get(policy_id)
    if p is None:
        raise not_found("Policy not found")
    state_code = req_str(body, "state_code")
    quarter = req_str(body, "quarter")
    period_start = req_dt(body, "period_start")
    period_end = req_dt(body, "period_end")
    if not period_start < period_end:
        raise invalid_request("period_start must be strictly before period_end")
    wages = req_int(body, "reported_wages_cents")
    source = req_enum(body, "source", {"SUI", "IRS_941", "MANUAL"})
    t = base_record()
    t.update({
        "policy_id": policy_id,
        "state_code": state_code,
        "quarter": quarter,
        "period_start": stamp(period_start),
        "period_end": stamp(period_end),
        "reported_wages_cents": wages,
        "source": source,
    })
    STORE.register("tax_filings", t)
    return success_object(ser_tax_filing(t), status=201)


# ---------------------------------------------------------------------------
# Audits
# ---------------------------------------------------------------------------

@bp.route("/wc/audits", methods=["POST"])
def create_audit():
    require_roles("Auditor")
    body = get_body()
    policy_id = req_str(body, "policy_id")
    p = STORE.policies.get(policy_id)
    if p is None:
        raise not_found("Policy not found")
    period_start = req_dt(body, "period_start")
    period_end = req_dt(body, "period_end")
    if not period_start < period_end:
        raise invalid_request("period_start must be strictly before period_end")
    a = open_audit(policy_id, period_start, period_end)
    return success_object(ser_audit(a), status=201)


@bp.route("/wc/audits", methods=["GET"])
def list_audits():
    require_roles("Underwriter", "Auditor", "TaxFiler")
    limit, offset = get_limit_offset()
    items = list(STORE.audits.values())
    trueup_filter = request.args.get("trueup_invoice_id")
    status_filter = request.args.get("status")
    if trueup_filter is not None:
        items = [a for a in items if a["trueup_invoice_id"] == trueup_filter]
    if status_filter is not None:
        items = [a for a in items if a["status"] == status_filter]
    items = sorted_list(items)
    page, total = paginate(items, limit, offset)
    return success_list([ser_audit(a) for a in page], limit, offset, total)


@bp.route("/wc/audits/<aid>", methods=["GET"])
def get_audit(aid):
    require_roles("Underwriter", "Auditor", "TaxFiler")
    a = get_audit_or_404(aid)
    return success_object(ser_audit(a))


@bp.route("/wc/audits/<aid>/file", methods=["POST"])
def file_audit_route(aid):
    user_id, role = require_roles("TaxFiler")
    a = get_audit_or_404(aid)
    body = get_body()
    expected = body.get("expected_policy_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise invalid_request("expected_policy_version must be an integer")
    if a["status"] != "OPEN":
        raise invalid_state("Audit is not in OPEN status")
    p = STORE.policies[a["policy_id"]]
    if expected != p["version"]:
        raise stale_version()
    file_audit(a, user_id)
    return success_object(ser_audit(a))


@bp.route("/wc/audits/<aid>/verify", methods=["POST"])
def verify_audit_route(aid):
    user_id, role = require_roles("Auditor")
    a = get_audit_or_404(aid)
    get_body()
    if a["status"] != "FILED":
        raise invalid_state("Audit is not in FILED status")
    if user_id == a["filed_by"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES,
                       "Verifier must differ from the audit filer", 403)
    verify_audit(a, user_id)
    return success_object(ser_audit(a))


@bp.route("/wc/audits/<aid>/waive", methods=["POST"])
def waive_audit(aid):
    require_roles("Underwriter")
    a = get_audit_or_404(aid)
    get_body()
    if a["status"] != "OPEN":
        raise invalid_state("Audit is not in OPEN status")
    a["status"] = "WAIVED"
    touch(a)
    return success_object(ser_audit(a))


# ---------------------------------------------------------------------------
# Integrations
# ---------------------------------------------------------------------------

@bp.route("/wc/integrations/<iid>/heartbeat", methods=["POST"])
def heartbeat(iid):
    user_id, role = require_roles("PayrollProvider")
    integ = get_integration_or_404(iid)
    body = get_body()
    outcome = req_enum(body, "outcome", {"OK", "DEGRADED", "BROKEN"})
    now = STORE.now()
    current = integ["connection_status"]
    if outcome == "OK":
        if current not in ("DEGRADED", "BROKEN", "CONNECTED"):
            raise invalid_state("Invalid heartbeat transition")
        integ["connection_status"] = "CONNECTED"
        integ["last_heartbeat_at"] = stamp(now)
        integ["_broken_since"] = None
        touch(integ)
    elif outcome == "DEGRADED":
        if current != "CONNECTED":
            raise invalid_state("Invalid heartbeat transition")
        integ["connection_status"] = "DEGRADED"
        integ["last_heartbeat_at"] = stamp(now)
        touch(integ)
    elif outcome == "BROKEN":
        # PRD §3.5: "A heartbeat reporting BROKEN ... moves it from DEGRADED to
        # BROKEN" — a heartbeat is the integration reporting its own current
        # health, so a BROKEN report is accepted from CONNECTED as well.
        if current not in ("CONNECTED", "DEGRADED"):
            raise invalid_state("Invalid heartbeat transition")
        integ["connection_status"] = "BROKEN"
        integ["_broken_since"] = stamp(now)
        touch(integ)
    return success_object(ser_integration(integ))
