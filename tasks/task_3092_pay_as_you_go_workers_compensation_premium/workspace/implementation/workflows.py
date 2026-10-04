"""Business workflows: payroll acceptance, invoicing, disputes, audits, sweep."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import STORE, new_id
from errors import (
    ApiError, invalid_request, invalid_state, stale_version,
    ERR_MONOPOLISTIC_STATE_EXCLUDED, ERR_CLASS_CODE_NOT_ON_POLICY,
    ERR_PAYROLL_PERIOD_OVERLAP, ERR_RETRO_WINDOW_INVALID,
    ERR_BILLING_SUSPENDED, ERR_IDEMPOTENCY_CONFLICT,
    ERR_POLICY_NOT_ACTIVE, ERR_TAX_FILING_MISSING, ERR_NOT_FOUND,
    ERR_INVALID_REQUEST, ERR_INVALID_STATE,
)
from helpers import (
    base_record, touch, stamp, parse_dt, fmt_dt,
    policy_class_codes, policy_reports, policy_invoices, policy_disputes,
    policy_audits, policy_integration, mutate_policy, recompute_policy_aggregates,
    period_fully_covered, tables_covering_period, table_effective_at,
    sort_key, sorted_list, weeks_in_period,
)
from calculations import compute_line_basis, compute_invoice_totals


# ---------------------------------------------------------------------------
# Invoice creation
# ---------------------------------------------------------------------------

def create_invoice(policy, kind, payroll_report_id, totals):
    inv = base_record()
    inv.update({
        "policy_id": policy["id"],
        "payroll_report_id": payroll_report_id,
        "kind": kind,
        "status": "ISSUED",
        "manual_premium_cents": totals["manual_premium_cents"],
        "experience_mod_applied": totals["experience_mod_applied"],
        "premium_after_mod_cents": totals["premium_after_mod_cents"],
        "per_capita_fees_cents": totals["per_capita_fees_cents"],
        "expense_constant_cents": totals["expense_constant_cents"],
        "total_cents": totals["total_cents"],
        "due_date": stamp(STORE.now() + timedelta(days=7)),
    })
    STORE.register("invoices", inv)
    return inv


def void_invoice(inv):
    inv["status"] = "VOID"
    touch(inv)


# ---------------------------------------------------------------------------
# Payroll report submission
# ---------------------------------------------------------------------------

def submit_payroll_report(body, submitted_by):
    policy_id = body.get("policy_id")
    if not isinstance(policy_id, str):
        raise invalid_request("Field policy_id must be a string")
    policy = STORE.policies.get(policy_id)
    if policy is None:
        from errors import not_found
        raise not_found("Policy not found")

    period_start = None
    period_end = None
    from helpers import req_dt
    period_start = req_dt(body, "period_start")
    period_end = req_dt(body, "period_end")
    if not period_start < period_end:
        raise invalid_request("period_start must be strictly before period_end")

    idempotency_key = body.get("idempotency_key")
    if not isinstance(idempotency_key, str) or not idempotency_key:
        raise invalid_request("Field idempotency_key must be a string")

    lines_in = body.get("lines")
    if not isinstance(lines_in, list):
        raise invalid_request("Field lines must be an array")
    parsed_lines = []
    for raw in lines_in:
        if not isinstance(raw, dict):
            raise invalid_request("Each line must be an object")
        for f in ("state_code", "class_code"):
            if f not in raw or not isinstance(raw[f], str):
                raise invalid_request(f"Line field {f} must be a string")
        if "gross_wages_cents" not in raw or isinstance(raw["gross_wages_cents"], bool) \
                or not isinstance(raw["gross_wages_cents"], int):
            raise invalid_request("Line field gross_wages_cents must be an integer")
        for f in ("ot_premium_cents", "severance_cents", "executive_wages_cents"):
            if f in raw and raw[f] is not None:
                if isinstance(raw[f], bool) or not isinstance(raw[f], int):
                    raise invalid_request(f"Line field {f} must be an integer")
        if "headcount" not in raw or isinstance(raw["headcount"], bool) \
                or not isinstance(raw["headcount"], int):
            raise invalid_request("Line field headcount must be an integer")
        parsed_lines.append({
            "state_code": raw["state_code"],
            "class_code": raw["class_code"],
            "gross_wages_cents": raw["gross_wages_cents"],
            "ot_premium_cents": raw.get("ot_premium_cents", 0) or 0,
            "severance_cents": raw.get("severance_cents", 0) or 0,
            "executive_wages_cents": raw.get("executive_wages_cents", 0) or 0,
            "headcount": raw["headcount"],
        })

    def canonical():
        return {
            "policy_id": policy_id,
            "period_start": fmt_dt(period_start),
            "period_end": fmt_dt(period_end),
            "lines": parsed_lines,
        }

    # Idempotency: same key on this policy.
    for r in STORE.reports.values():
        if r["policy_id"] == policy_id and r["idempotency_key"] == idempotency_key:
            if r["_payload"] == canonical():
                return r, None  # replay
            raise ApiError(ERR_IDEMPOTENCY_CONFLICT,
                           "idempotency_key reused with a different payload", 409)

    # Hard request faults.
    if policy["coverage_status"] != "ACTIVE":
        raise ApiError(ERR_POLICY_NOT_ACTIVE,
                       "Operation requires coverage_status == ACTIVE", 409)
    if policy["billing_status"] == "SUSPENDED":
        raise ApiError(ERR_BILLING_SUSPENDED,
                       "Payroll submission while billing_status == SUSPENDED", 409)

    # Persist the report (acceptance checks are business data on failure).
    report = base_record()
    report.update({
        "policy_id": policy_id,
        "period_start": fmt_dt(period_start),
        "period_end": fmt_dt(period_end),
        "status": "SUBMITTED",
        "failure_code": None,
        "submitted_by": submitted_by,
        "idempotency_key": idempotency_key,
        "_payload": canonical(),
    })
    STORE.register("reports", report)

    # Acceptance checks in PRD order:
    # 1. monopolistic exclusion
    # 2. class-code resolution
    # 3. period window + overlap
    # (billing suspension / idempotency already handled as hard faults)
    failure = None

    def line_table(state_code):
        # table effective over the whole period must exist (non-monopolistic)
        if not period_fully_covered(state_code, period_start, period_end):
            return None
        # check monopolistic flag on any table covering the period
        for t in tables_covering_period(state_code, period_start, period_end):
            if t["monopolistic"]:
                return "MONO"
        return "OK"

    if failure is None:
        for pl in parsed_lines:
            res = line_table(pl["state_code"])
            if res == "MONO":
                failure = ERR_MONOPOLISTIC_STATE_EXCLUDED
                break
            if res is None:
                # No non-monopolistic table across the whole period.
                # If a table exists at all covering part of the period and is
                # monopolistic, treat as monopolistic; otherwise class-code
                # resolution will fail next, but absence of a table is a
                # class-code/line failure — surface class-code error.
                any_table = tables_covering_period(pl["state_code"], period_start, period_end)
                if any(t["monopolistic"] for t in any_table):
                    failure = ERR_MONOPOLISTIC_STATE_EXCLUDED
                else:
                    failure = ERR_CLASS_CODE_NOT_ON_POLICY
                break

    if failure is None:
        assignments = policy_class_codes(policy_id)
        for pl in parsed_lines:
            ok = False
            for c in assignments:
                if c["state_code"] != pl["state_code"]:
                    continue
                if c["class_code"] != pl["class_code"]:
                    continue
                if c["assignment_status"] not in ("ACTIVE", "DISPUTED"):
                    continue
                if parse_dt(c["effective_from"]) <= period_end:
                    ok = True
                    break
            if not ok:
                failure = ERR_CLASS_CODE_NOT_ON_POLICY
                break

    if failure is None:
        p_start = parse_dt(policy["effective_date"])
        p_end = parse_dt(policy["expiry_date"])
        if period_start < p_start or period_end > p_end:
            failure = ERR_PAYROLL_PERIOD_OVERLAP
        else:
            for r in STORE.reports.values():
                if r["id"] == report["id"]:
                    continue
                if r["policy_id"] != policy_id:
                    continue
                if r["status"] not in ("SUBMITTED", "ACCEPTED"):
                    continue
                r_s = parse_dt(r["period_start"])
                r_e = parse_dt(r["period_end"])
                if r_s < period_end and period_start < r_e:
                    failure = ERR_PAYROLL_PERIOD_OVERLAP
                    break

    if failure is not None:
        report["status"] = "REJECTED"
        report["failure_code"] = failure
        return report, 200

    # Accepted: compute lines, invoice, update policy.
    report["status"] = "ACCEPTED"

    line_records = []
    for pl in parsed_lines:
        line = base_record()
        line.update({
            "payroll_report_id": report["id"],
            "state_code": pl["state_code"],
            "class_code": pl["class_code"],
            "gross_wages_cents": pl["gross_wages_cents"],
            "ot_premium_cents": pl["ot_premium_cents"],
            "severance_cents": pl["severance_cents"],
            "executive_wages_cents": pl["executive_wages_cents"],
            "headcount": pl["headcount"],
            "remuneration_basis_cents": 0,
        })
        STORE.register("lines", line)
        line_records.append(line)

    for line in line_records:
        compute_line_basis(line, period_start, period_end)
        touch(line)

    totals = compute_invoice_totals(line_records, period_start, period_end,
                                    policy["experience_mod"])
    create_invoice(policy, "PAYROLL", report["id"], totals)

    policy["last_report_received_at"] = stamp(STORE.now())
    policy["consecutive_missed_cycles"] = 0
    if policy["reporting_status"] in ("GRACE", "DELINQUENT", "NON_REPORTING"):
        policy["reporting_status"] = "COMPLIANT"
        policy["_non_reporting_since"] = None
    mutate_policy(policy)
    return report, 201


# ---------------------------------------------------------------------------
# Payment / billing health
# ---------------------------------------------------------------------------

def reevaluate_billing(policy):
    now = STORE.now()
    invoices = [i for i in policy_invoices(policy["id"]) if i["status"] == "ISSUED"]
    unpaid_14 = any(
        parse_dt(i["due_date"]) + timedelta(days=14) < now for i in invoices
    )
    past_due = any(parse_dt(i["due_date"]) < now for i in invoices)

    if policy["billing_status"] in ("OVERDUE", "SUSPENDED") and not invoices:
        policy["billing_status"] = "CURRENT"
    if policy["billing_status"] == "CURRENT" and past_due:
        policy["billing_status"] = "OVERDUE"
    if policy["billing_status"] == "OVERDUE" and unpaid_14:
        policy["billing_status"] = "SUSPENDED"


# ---------------------------------------------------------------------------
# Dispute decision cascade
# ---------------------------------------------------------------------------

def report_lines(report_id):
    return [l for l in STORE.lines.values() if l["payroll_report_id"] == report_id]


def decide_dispute(dispute, decision, decider_id):
    policy = STORE.policies[dispute["policy_id"]]
    now = STORE.now()

    dispute["decided_by"] = decider_id

    if decision == "DENIED":
        dispute["status"] = "DENIED"
        dispute["resolution_reason"] = "decided"
        touch(dispute)
        assignment = STORE.class_codes.get(dispute["policy_class_code_id"])
        if assignment is not None and assignment["assignment_status"] == "DISPUTED":
            assignment["assignment_status"] = "ACTIVE"
            touch(assignment)
        mutate_policy(policy)
        return dispute

    # APPROVED — retroactive cascade.
    dispute["status"] = "APPROVED"
    dispute["resolution_reason"] = "decided"
    touch(dispute)

    assignment = STORE.class_codes[dispute["policy_class_code_id"]]
    assignment["assignment_status"] = "REASSIGNED"
    touch(assignment)

    new_cc = base_record()
    new_cc.update({
        "policy_id": policy["id"],
        "state_code": assignment["state_code"],
        "class_code": dispute["requested_class_code"],
        "estimated_annual_payroll_cents": assignment["estimated_annual_payroll_cents"],
        "effective_from": dispute["effective_from"],
        "assignment_status": "ACTIVE",
    })
    STORE.register("class_codes", new_cc)

    eff_from = parse_dt(dispute["effective_from"])
    expiry = parse_dt(policy["expiry_date"])

    affected = []
    for r in STORE.reports.values():
        if r["policy_id"] != policy["id"] or r["status"] != "ACCEPTED":
            continue
        r_s = parse_dt(r["period_start"])
        r_e = parse_dt(r["period_end"])
        if r_s < expiry and eff_from < r_e:
            affected.append(r)
    affected.sort(key=lambda r: (parse_dt(r["period_start"]), r["created_at"]))

    delta = 0
    for r in affected:
        r_start = parse_dt(r["period_start"])
        r_end = parse_dt(r["period_end"])
        # Original PAYROLL invoice.
        original = None
        for inv in STORE.invoices.values():
            if inv["payroll_report_id"] == r["id"] and inv["kind"] == "PAYROLL" \
                    and inv["status"] in ("ISSUED", "PAID"):
                original = inv
                break
        original_total = original["total_cents"] if original is not None else 0

        lines = report_lines(r["id"])
        overrides = {}
        for line in lines:
            if line["state_code"] == assignment["state_code"] and \
                    line["class_code"] == assignment["class_code"]:
                overrides[line["id"]] = dispute["requested_class_code"]

        totals = compute_invoice_totals(lines, r_start, r_end,
                                        policy["experience_mod"],
                                        rate_overrides=overrides)
        replacement_total = totals["total_cents"]

        if original is not None:
            void_invoice(original)
        create_invoice(policy, "PAYROLL", r["id"], totals)

        delta += replacement_total - original_total

        r["status"] = "SUPERSEDED"
        touch(r)

    if affected:
        adj_totals = {
            "manual_premium_cents": 0,
            "experience_mod_applied": round(float(policy['experience_mod']), 3),
            "premium_after_mod_cents": 0,
            "per_capita_fees_cents": 0,
            "expense_constant_cents": 0,
            "total_cents": delta,
        }
        create_invoice(policy, "RETRO_ADJUSTMENT", None, adj_totals)

    mutate_policy(policy)
    return dispute


# ---------------------------------------------------------------------------
# Audit filing / verification
# ---------------------------------------------------------------------------

def open_audit(policy_id, period_start_dt, period_end_dt):
    a = base_record()
    a.update({
        "policy_id": policy_id,
        "period_start": stamp(period_start_dt),
        "period_end": stamp(period_end_dt),
        "status": "OPEN",
        "filed_by": None,
        "verified_by": None,
        "reported_payroll_cents": 0,
        "filing_payroll_cents": 0,
        "variance_cents": 0,
        "trueup_invoice_id": None,
    })
    STORE.register("audits", a)
    return a


def file_audit(audit, filer_id):
    policy = STORE.policies[audit["policy_id"]]
    a_start = parse_dt(audit["period_start"])
    a_end = parse_dt(audit["period_end"])

    # Tax coverage: every quarter intersecting the window must have a filing.
    # Quarters are calendar quarters.
    def quarter_bounds(year, q):
        start_month = (q - 1) * 3 + 1
        from datetime import datetime, timezone
        qs = datetime(year, start_month, 1, tzinfo=timezone.utc)
        if q == 4:
            qe = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
        else:
            qe = datetime(year, start_month + 3, 1, tzinfo=timezone.utc)
        return qs, qe

    def quarters_intersecting(start, end):
        from datetime import timezone, datetime
        qs = []
        y = start.year
        q = (start.month - 1) // 3 + 1
        while True:
            qs_dt, qe_dt = quarter_bounds(y, q)
            if qs_dt < end and qe_dt > start:
                qs.append((qs_dt, qe_dt))
            if qe_dt >= end:
                break
            q += 1
            if q == 5:
                q = 1
                y += 1
        return qs

    filings = [t for t in STORE.tax_filings.values() if t["policy_id"] == policy["id"]]
    for (qs, qe) in quarters_intersecting(a_start, a_end):
        covered = any(
            parse_dt(t["period_start"]) < qe and parse_dt(t["period_end"]) > qs
            for t in filings
        )
        if not covered:
            raise ApiError(ERR_TAX_FILING_MISSING,
                           "Audit window quarter lacks a TaxFilingRecord", 422)

    reported = 0
    last_report = None
    for r in STORE.reports.values():
        if r["policy_id"] != policy["id"] or r["status"] != "ACCEPTED":
            continue
        r_s = parse_dt(r["period_start"])
        r_e = parse_dt(r["period_end"])
        if a_start <= r_s and r_e <= a_end:
            for line in report_lines(r["id"]):
                reported += line["remuneration_basis_cents"]
            if last_report is None or \
                    (parse_dt(r["period_start"]), r["created_at"]) > \
                    (parse_dt(last_report["period_start"]), last_report["created_at"]):
                last_report = r

    filing_total = 0
    for t in filings:
        t_s = parse_dt(t["period_start"])
        t_e = parse_dt(t["period_end"])
        # PRD §3.7: filings "whose filing period intersects the audit window"
        # count in full. The filing side sums whole quarters (a quarter "that
        # only partially overlaps counts in full"), so quarter-level
        # intersection — including a quarter that begins exactly at the
        # window's end boundary — counts.
        if t_s <= a_end and t_e > a_start:
            filing_total += t["reported_wages_cents"]

    audit["reported_payroll_cents"] = reported
    audit["filing_payroll_cents"] = filing_total
    audit["variance_cents"] = filing_total - reported
    audit["filed_by"] = filer_id
    audit["status"] = "FILED"
    touch(audit)
    return audit


def verify_audit(audit, verifier_id):
    policy = STORE.policies[audit["policy_id"]]
    audit["verified_by"] = verifier_id
    audit["status"] = "VERIFIED"
    touch(audit)

    if audit["variance_cents"] > 0:
        # Build a true-up line set using the class mix of the last accepted
        # report in the window.
        a_start = parse_dt(audit["period_start"])
        a_end = parse_dt(audit["period_end"])
        last_report = None
        for r in STORE.reports.values():
            if r["policy_id"] != policy["id"] or r["status"] != "ACCEPTED":
                continue
            r_s = parse_dt(r["period_start"])
            r_e = parse_dt(r["period_end"])
            if a_start <= r_s and r_e <= a_end:
                if last_report is None or \
                        (parse_dt(r["period_start"]), r["created_at"]) > \
                        (parse_dt(last_report["period_start"]), last_report["created_at"]):
                    last_report = r

        if last_report is not None:
            mix_lines = report_lines(last_report["id"])
            count = len(mix_lines)
            variance = audit["variance_cents"]
            base_share = variance // count
            remainder = variance - base_share * count
            pseudo_lines = []
            for idx, src in enumerate(mix_lines):
                share = base_share + (1 if idx < remainder else 0)
                pseudo = {
                    "id": f"trueup-{idx}",
                    "state_code": src["state_code"],
                    "class_code": src["class_code"],
                    "gross_wages_cents": share,
                    "ot_premium_cents": 0,
                    "severance_cents": 0,
                    "executive_wages_cents": 0,
                    "headcount": 0,
                    "remuneration_basis_cents": share,
                }
                pseudo_lines.append(pseudo)
            totals = compute_invoice_totals(
                pseudo_lines, a_start, a_end, policy["experience_mod"],
                include_adders=False)
        else:
            totals = {
                "manual_premium_cents": 0,
                "experience_mod_applied": round(float(policy['experience_mod']), 3),
                "premium_after_mod_cents": 0,
                "per_capita_fees_cents": 0,
                "expense_constant_cents": 0,
                "total_cents": audit["variance_cents"],
            }
        inv = create_invoice(policy, "AUDIT_TRUEUP", None, totals)
        audit["trueup_invoice_id"] = inv["id"]
        recompute_policy_aggregates(policy)
        touch(policy)
    else:
        audit["trueup_invoice_id"] = None
        # No unpaid true-up: closes immediately.
        audit["status"] = "CLOSED"
    touch(audit)
    return audit


def maybe_close_audit(audit):
    if audit["status"] != "VERIFIED":
        return
    tid = audit["trueup_invoice_id"]
    if tid is None:
        audit["status"] = "CLOSED"
        touch(audit)
        return
    inv = STORE.invoices.get(tid)
    if inv is not None and inv["status"] == "PAID":
        audit["status"] = "CLOSED"
        touch(audit)


# ---------------------------------------------------------------------------
# Cancellation cascade
# ---------------------------------------------------------------------------

def cancel_policy(policy):
    policy["coverage_status"] = "CANCELLED"
    for inv in policy_invoices(policy["id"]):
        if inv["status"] == "DRAFT":
            inv["status"] = "VOID"
            touch(inv)
    for d in policy_disputes(policy["id"]):
        if d["status"] in ("FILED", "UNDER_REVIEW"):
            d["status"] = "DENIED"
            d["resolution_reason"] = "policy_cancelled"
            touch(d)
            assignment = STORE.class_codes.get(d["policy_class_code_id"])
            if assignment is not None and assignment["assignment_status"] == "DISPUTED":
                assignment["assignment_status"] = "ACTIVE"
                touch(assignment)
    for a in policy_audits(policy["id"]):
        if a["status"] in ("OPEN", "FILED"):
            a["status"] = "WAIVED"
            touch(a)
    recompute_policy_aggregates(policy)
    touch(policy)


# ---------------------------------------------------------------------------
# Daily threshold sweep
# ---------------------------------------------------------------------------

def run_sweep():
    now = STORE.now()
    for policy in list(STORE.policies.values()):
        if policy["coverage_status"] != "ACTIVE":
            continue
        changed = False

        # Expiry takes precedence over delinquency/cancellation processing.
        if now >= parse_dt(policy["expiry_date"]):
            policy["coverage_status"] = "EXPIRED"
            open_audit(policy["id"], parse_dt(policy["effective_date"]),
                       parse_dt(policy["expiry_date"]))
            recompute_policy_aggregates(policy)
            touch(policy)
            continue

        # Integration health: missed heartbeats.
        integ = policy_integration(policy["id"])
        if integ is not None and integ.get("last_heartbeat_at"):
            last_hb = parse_dt(integ["last_heartbeat_at"])
            days_since = (now - last_hb).total_seconds() / 86400.0
            if integ["connection_status"] == "CONNECTED" and days_since >= 7:
                integ["connection_status"] = "DEGRADED"
                touch(integ)
            if integ["connection_status"] == "DEGRADED" and days_since >= 14:
                integ["connection_status"] = "BROKEN"
                integ["_broken_since"] = stamp(now)
                touch(integ)

        # Reporting delinquency via broken-integration clock.
        if integ is not None and integ["connection_status"] == "BROKEN":
            broken_since_raw = integ.get("_broken_since")
            if broken_since_raw:
                broken_days = (now - parse_dt(broken_since_raw)).total_seconds() / 86400.0
                if broken_days >= 21 and policy["reporting_status"] != "NON_REPORTING":
                    policy["reporting_status"] = "NON_REPORTING"
                    policy["_non_reporting_since"] = stamp(now)
                    changed = True

        # Missed-cycle ladder (driven by consecutive_missed_cycles counter).
        cmc = policy["consecutive_missed_cycles"]
        if cmc >= 3 and policy["reporting_status"] != "NON_REPORTING":
            policy["reporting_status"] = "NON_REPORTING"
            policy["_non_reporting_since"] = stamp(now)
            changed = True
        elif cmc == 2 and policy["reporting_status"] in ("COMPLIANT", "GRACE"):
            policy["reporting_status"] = "DELINQUENT"
            changed = True
        elif cmc == 1 and policy["reporting_status"] == "COMPLIANT":
            policy["reporting_status"] = "GRACE"
            changed = True

        # Auto-cancel after 35 days NON_REPORTING.
        if policy["reporting_status"] == "NON_REPORTING":
            nr_since = policy.get("_non_reporting_since")
            if nr_since:
                nr_days = (now - parse_dt(nr_since)).total_seconds() / 86400.0
                if nr_days >= 35:
                    cancel_policy(policy)
                    continue

        # Billing health sweep.
        old_billing = policy["billing_status"]
        reevaluate_billing(policy)
        if policy["billing_status"] != old_billing:
            changed = True

        if changed:
            touch(policy)
