"""Server-derived aggregates and cascades (PRD 2.6, 2.7, 3.4, 3.8)."""
from decimal import Decimal

from db import db, touch
from money import MONEY_ZERO, RATIO_ZERO, q2, q4

CONSTRAINED_POSTURE_PCT = Decimal("0.1000")
HELD_REASON = "CONSTRUCTION_CONTINGENCY_CONSTRAINED"

ACTIVE_COMMITMENT_STATUSES = ("ACTIVE", "DEFAULT_NOTICED", "COMPLETED")
BUYOUT_PACKAGE_STATUSES = ("AWARDED", "REPROCUREMENT", "CLOSED")
PENDING_AMENDMENT_STATUSES = ("DRAFT", "OWNER_REVIEW", "RETURNED_FOR_REVISION")


# ------------------------------------------------------------------ posture

def remaining_pct(project):
    original = project["construction_contingency_original"]
    if original == MONEY_ZERO:
        return RATIO_ZERO
    return q4(project["construction_contingency_remaining"] / original)


def derive_posture(project):
    if project["closeout_status"] == "SETTLEMENT_EXECUTED":
        return "FROZEN"
    if remaining_pct(project) <= CONSTRAINED_POSTURE_PCT:
        return "CONSTRAINED"
    return "OPEN"


def apply_posture(project):
    """Re-derive the posture gate and run the asymmetric freeze cascade."""
    previous = project["contingency_posture"]
    current = derive_posture(project)
    project["contingency_posture"] = current
    if previous == "OPEN" and current == "CONSTRAINED":
        hold_open_cost_reports(project)
    return current


def hold_open_cost_reports(project):
    held = []
    for report in db.cost_reports.values():
        if report["project_id"] != project["id"]:
            continue
        if report["status"] != "OPEN":
            continue
        report["status"] = "RECONCILIATION_HELD"
        report["held_reason"] = HELD_REASON
        touch(report)
        held.append(report)
    return held


# ----------------------------------------------------------- buyout savings

def recompute_buyout_savings(project):
    trade_level = MONEY_ZERO
    project_net = MONEY_ZERO
    for package in db.work_packages.values():
        if package["project_id"] != project["id"]:
            continue
        if package["procurement_status"] not in BUYOUT_PACKAGE_STATUSES:
            continue
        delta = package["budget_amount"] - package["awarded_amount"]
        project_net = project_net + delta
        if delta > MONEY_ZERO:
            trade_level = trade_level + delta
    project["buyout_savings_trade_level"] = q2(trade_level)
    project["buyout_savings_project_net"] = q2(project_net)


# --------------------------------------------------------- work package roll

def recount_committed_amount(package):
    total = MONEY_ZERO
    for sub in db.subcontracts.values():
        if sub["work_package_id"] != package["id"]:
            continue
        if sub["contract_status"] in ACTIVE_COMMITMENT_STATUSES:
            total = total + sub["contract_amount"]
        elif sub["contract_status"] == "TERMINATED_FOR_DEFAULT":
            total = total + sub["paid_to_date"]
    package["committed_amount"] = q2(total)


# ------------------------------------------------------------ amendment roll

def rollup_amendments(project):
    """Rewrite proposed_gmp_amount and pending_amendment_count together."""
    total = project["gmp_amount"]
    pending = 0
    for proposal in db.proposals.values():
        if proposal["project_id"] != project["id"]:
            continue
        if proposal["proposal_type"] != "AMENDMENT":
            continue
        if proposal["status"] not in PENDING_AMENDMENT_STATUSES:
            continue
        total = total + proposal["amount_delta"]
        pending += 1
    project["proposed_gmp_amount"] = q2(total)
    project["pending_amendment_count"] = pending


def mark_reconciled_estimates_stale(project):
    """Third level of the scope-change cascade (PRD 3.6)."""
    touched = []
    for estimate in db.estimates.values():
        if estimate["project_id"] != project["id"]:
            continue
        if estimate["status"] != "RECONCILED":
            continue
        if estimate["reconciliation_stale"]:
            continue
        estimate["reconciliation_stale"] = True
        touch(estimate)
        touched.append(estimate)
    return touched


# ------------------------------------------------------------- cost reports

def recompute_report_totals(report):
    reported = MONEY_ZERO
    undisputed = MONEY_ZERO
    disputed = MONEY_ZERO
    for line in report["lines"]:
        amount = line["line_amount"]
        reported = reported + amount
        if line["disputed"]:
            disputed = disputed + amount
        else:
            undisputed = undisputed + amount
    report["reported_cost_total"] = q2(reported)
    report["undisputed_cost_total"] = q2(undisputed)
    report["disputed_cost_total"] = q2(disputed)
    report["line_count"] = len(report["lines"])


def project_reports(project_id):
    return [r for r in db.cost_reports.values() if r["project_id"] == project_id]
