"""Audit rights, the four-hop restatement and its unwind — PRD 3.8."""
import calc
from auth import ALL_ROLES, fetch, guard, require_owner
from envelope import created, listing, ok
from errors import ApiError
from logic import (build_reconciliation, cure_deadline_from_clock, lease_of, ordered,
                   recompute_outstanding)
from money import parse_date
from router import route
from shape import body, ref, req_date, req_int, req_str
from store import db, insert, touch

AUDITABLE_LEASE_STATES = ("ACTIVE", "HOLDOVER", "EXPIRED")


def _covered_reports(audit, statuses):
    """Reports whose half-open period lies inside the audit window."""
    window_start = parse_date(audit["audit_period_start"])
    window_end = parse_date(audit["audit_period_end"])
    rows = []
    for report in db.reports.values():
        if report["lease_id"] != audit["lease_id"] or report["status"] not in statuses:
            continue
        if parse_date(report["period_start"]) >= window_start \
                and parse_date(report["period_end"]) <= window_end:
            rows.append(report)
    rows.sort(key=lambda r: (r["period_start"], r["created_at"], r["_seq"]))
    return rows


def _lease_year_row(audit, lease):
    """The reconciliation for the lease year the audit window falls in."""
    window_start = parse_date(audit["audit_period_start"])
    term_start = parse_date(lease["term_start"])
    number = calc.lease_year_number(term_start, lease["term_years"], window_start)
    candidates = []
    for row in ordered(list(db.reconciliations.values())):
        if row["lease_id"] != lease["id"] or row["status"] not in ("PENDING_PAYMENT", "SETTLED"):
            continue
        inside = (parse_date(row["lease_year_start"]) <= window_start
                  <= parse_date(row["lease_year_end"]))
        if row["lease_year_number"] == number or inside:
            candidates.append(row)
    for row in candidates:
        if row["status"] == "PENDING_PAYMENT":
            return row
    return candidates[0] if candidates else None


@route("/audit-engagements", methods=["POST"])
def audits_create():
    guard("AuditorGeneral")
    data = body()
    lease = None
    lease_ref = ref(data, "lease_id")
    if lease_ref is not None:
        lease = fetch(db.leases, lease_ref, "ERR_LEASE_NOT_FOUND")
    row = {
        "lease_id": req_str(data, "lease_id"),
        "audit_period_start": req_date(data, "audit_period_start")[0],
        "audit_period_end": req_date(data, "audit_period_end")[0],
        "scope_note": req_str(data, "scope_note"),
        "reported_gross_receipts_cents": None,
        "adjusted_gross_receipts_cents": None,
        "underreport_pct": None,
        "penalty_applies": None,
        "finding_note": None,
        "contest_basis": None,
        "withdrawal_basis": None,
        "status": "OPENED",
    }
    if not parse_date(row["audit_period_start"]) < parse_date(row["audit_period_end"]):
        raise ApiError("ERR_INVALID_INTERVAL",
                       "audit_period_start must be strictly before its exclusive end")
    if lease["contract_status"] not in AUDITABLE_LEASE_STATES:
        raise ApiError("ERR_LEASE_STATUS_INVALID",
                       "Lease contract_status %s cannot be audited" % lease["contract_status"])
    return created(insert(db.audits, row))


@route("/audit-engagements/<audit_id>/begin-fieldwork", methods=["POST"])
def audits_begin_fieldwork(audit_id):
    guard("AuditorGeneral")
    audit = fetch(db.audits, audit_id, "ERR_AUDIT_NOT_FOUND")
    if audit["status"] != "OPENED":
        raise ApiError("ERR_AUDIT_STATUS_INVALID",
                       "Audit status %s cannot begin fieldwork" % audit["status"])
    reports = _covered_reports(audit, ("ACCEPTED",))
    if not reports:
        raise ApiError("ERR_AUDIT_PERIOD_EMPTY",
                       "No accepted report lies inside the audit window")
    audit["reported_gross_receipts_cents"] = sum(r["total_receipts_cents"] for r in reports)
    audit["status"] = "FIELDWORK"
    touch(audit)
    return ok(audit)


@route("/audit-engagements/<audit_id>/issue-findings", methods=["POST"])
def audits_issue_findings(audit_id):
    guard("AuditorGeneral")
    audit = fetch(db.audits, audit_id, "ERR_AUDIT_NOT_FOUND")
    data = body()
    adjusted = req_int(data, "adjusted_gross_receipts_cents", minimum=0)
    note = req_str(data, "finding_note")
    if audit["status"] != "FIELDWORK":
        raise ApiError("ERR_AUDIT_STATUS_INVALID",
                       "Audit status %s cannot issue findings" % audit["status"])
    audit["adjusted_gross_receipts_cents"] = adjusted
    audit["finding_note"] = note
    pct = calc.underreport_pct(audit["reported_gross_receipts_cents"] or 0, adjusted)
    audit["underreport_pct"] = pct
    audit["penalty_applies"] = calc.penalty_applies(pct)
    audit["status"] = "FINDINGS_ISSUED"
    touch(audit)
    return ok(audit)


@route("/audit-engagements/<audit_id>/contest", methods=["POST"])
def audits_contest(audit_id):
    guard("Concessionaire")
    audit = fetch(db.audits, audit_id, "ERR_AUDIT_NOT_FOUND")
    lease = lease_of(audit)
    require_owner(lease["offeror_id"] if lease is not None else None)
    data = body()
    basis = req_str(data, "contest_basis")
    if audit["status"] != "FINDINGS_ISSUED":
        raise ApiError("ERR_AUDIT_STATUS_INVALID",
                       "Audit status %s cannot be contested" % audit["status"])
    audit["contest_basis"] = basis
    audit["status"] = "CONTESTED"
    touch(audit)
    return ok(audit)


@route("/audit-engagements/<audit_id>/finalize", methods=["POST"])
def audits_finalize(audit_id):
    guard("AuditorGeneral")
    audit = fetch(db.audits, audit_id, "ERR_AUDIT_NOT_FOUND")
    if audit["status"] not in ("FINDINGS_ISSUED", "CONTESTED"):
        raise ApiError("ERR_AUDIT_STATUS_INVALID",
                       "Audit status %s cannot be finalized" % audit["status"])
    lease = lease_of(audit)
    prior = _lease_year_row(audit, lease) if lease is not None else None
    if prior is None:
        raise ApiError("ERR_NO_RECONCILIATION_FOR_PERIOD",
                       "No reconciliation exists for the audited lease year")
    adjusted = audit["adjusted_gross_receipts_cents"] or 0
    reported_total = audit["reported_gross_receipts_cents"] or 0
    # Hop one — restate the covered periods.
    reports = _covered_reports(audit, ("ACCEPTED",))
    shares = calc.allocate_restatement(reports, reported_total, adjusted)
    for report, share in zip(reports, shares):
        report["restated_receipts_cents"] = share
        report["status"] = "RESTATED"
        touch(report)
    # Hop two — supersede the lease year's invoice and mint the replacement.
    year_start = parse_date(prior["lease_year_start"])
    year_end = parse_date(prior["lease_year_end"])
    replacement = build_reconciliation(
        lease, year_start, year_end, audit=audit, gross_override=adjusted,
        penalty_source_due_date=parse_date(prior["due_date"]))
    if prior["status"] == "PENDING_PAYMENT":
        prior["status"] = "SUPERSEDED"
        prior["superseded_by_id"] = replacement["id"]
        touch(prior)
    # Hop three — recompute the lease's outstanding balance.
    outstanding = recompute_outstanding(lease)
    # Hop four — the deficiency notice.
    if outstanding > calc.DEFICIENCY_NOTICE_THRESHOLD_CENTS:
        if lease["compliance_status"] == "COMPLIANT":
            lease["compliance_status"] = "DEFICIENT"
            touch(lease)
        insert(db.compliance_actions, {
            "lease_id": lease["id"],
            "reconciliation_id": replacement["id"],
            "action_type": "FEE_DELINQUENCY",
            "origin": "SYSTEM_ISSUED",
            "deficiency_note": "Outstanding franchise fee balance following audit restatement",
            "cure_deadline": cure_deadline_from_clock(),
            "cure_note": None,
            "draw_amount_cents": None,
            "status": "NOTICE_ISSUED",
        })
    audit["status"] = "FINAL"
    touch(audit)
    return ok(audit)


@route("/audit-engagements/<audit_id>/withdraw-findings", methods=["POST"])
def audits_withdraw_findings(audit_id):
    guard("AuditorGeneral")
    audit = fetch(db.audits, audit_id, "ERR_AUDIT_NOT_FOUND")
    data = body()
    basis = req_str(data, "withdrawal_basis")
    if audit["status"] != "FINAL":
        raise ApiError("ERR_AUDIT_STATUS_INVALID",
                       "Audit status %s cannot be withdrawn" % audit["status"])
    minted = None
    for row in ordered(list(db.reconciliations.values())):
        if row["audit_engagement_id"] == audit_id:
            minted = row
    if minted is None or minted["status"] != "PENDING_PAYMENT":
        raise ApiError("ERR_AUDIT_ALREADY_SETTLED",
                       "The audit reconciliation is no longer PENDING_PAYMENT")
    lease = lease_of(audit)
    # The unwind runs in the reverse order of the restatement.
    minted["status"] = "VOIDED"
    touch(minted)
    for row in ordered(list(db.reconciliations.values())):
        if row["status"] == "SUPERSEDED" and row["superseded_by_id"] == minted["id"]:
            row["status"] = "PENDING_PAYMENT"
            row["superseded_by_id"] = None
            touch(row)
    for report in _covered_reports(audit, ("RESTATED",)):
        report["restated_receipts_cents"] = None
        report["status"] = "ACCEPTED"
        touch(report)
    for action in ordered(list(db.compliance_actions.values())):
        if (action["origin"] == "SYSTEM_ISSUED" and action["status"] == "NOTICE_ISSUED"
                and action["reconciliation_id"] == minted["id"]):
            action["status"] = "RESCINDED"
            touch(action)
    if lease is not None:
        recompute_outstanding(lease)
        if lease["compliance_status"] == "DEFICIENT":
            outstanding_notice = False
            for action in db.compliance_actions.values():
                if action["lease_id"] == lease["id"] and action["status"] == "NOTICE_ISSUED":
                    outstanding_notice = True
                    break
            if not outstanding_notice:
                lease["compliance_status"] = "COMPLIANT"
                touch(lease)
    audit["withdrawal_basis"] = basis
    audit["status"] = "WITHDRAWN"
    touch(audit)
    return ok(audit)


@route("/audit-engagements", methods=["GET"])
def audits_list():
    guard(*ALL_ROLES)
    return listing(db.audits, ("lease_id", "status"))


@route("/audit-engagements/<audit_id>", methods=["GET"])
def audits_read(audit_id):
    guard(*ALL_ROLES)
    return ok(fetch(db.audits, audit_id, "ERR_AUDIT_NOT_FOUND"))
