"""Lookup helpers: existence checks left-to-right with resource-specific 404s."""
import db
from errors import err


def get_sp(sp_id):
    sp = db.service_providers.get(sp_id)
    if sp is None:
        raise err("ERR_SERVICE_PROVIDER_NOT_FOUND")
    return sp


def get_member(member_id):
    m = db.members.get(member_id)
    if m is None:
        raise err("ERR_MEMBER_NOT_FOUND")
    return m


def get_payee(payee_id):
    p = db.payees.get(payee_id)
    if p is None:
        raise err("ERR_PAYEE_NOT_FOUND")
    return p


def get_work(work_id):
    w = db.works.get(work_id)
    if w is None:
        raise err("ERR_WORK_NOT_FOUND")
    return w


def get_share(share_id):
    s = db.work_shares.get(share_id)
    if s is None:
        raise err("ERR_SHARE_NOT_FOUND")
    return s


def get_schedule(schedule_id):
    s = db.rate_schedules.get(schedule_id)
    if s is None:
        raise err("ERR_RATE_SCHEDULE_NOT_FOUND")
    return s


def get_report(report_id):
    r = db.usage_reports.get(report_id)
    if r is None:
        raise err("ERR_USAGE_REPORT_NOT_FOUND")
    return r


def get_line(line_id):
    l = db.usage_lines.get(line_id)
    if l is None:
        raise err("ERR_USAGE_LINE_NOT_FOUND")
    return l


def get_accrual(accrual_id):
    a = db.accruals.get(accrual_id)
    if a is None:
        raise err("ERR_ACCRUAL_NOT_FOUND")
    return a


def get_claim(claim_id):
    c = db.claims.get(claim_id)
    if c is None:
        raise err("ERR_CLAIM_NOT_FOUND")
    return c


def get_dispute(dispute_id):
    d = db.disputes.get(dispute_id)
    if d is None:
        raise err("ERR_DISPUTE_NOT_FOUND")
    return d


def get_statement(statement_id):
    s = db.statements.get(statement_id)
    if s is None:
        raise err("ERR_STATEMENT_NOT_FOUND")
    return s


def get_audit(audit_id):
    a = db.audits.get(audit_id)
    if a is None:
        raise err("ERR_AUDIT_NOT_FOUND")
    return a


def get_cycle_run(run_id):
    c = db.cycle_runs.get(run_id)
    if c is None:
        raise err("ERR_CYCLE_RUN_NOT_FOUND")
    return c


def get_distribution_line(line_id):
    d = db.distribution_lines.get(line_id)
    if d is None:
        raise err("ERR_CYCLE_RUN_NOT_FOUND")
    return d


def get_statement_line(line_id):
    s = db.statement_lines.get(line_id)
    if s is None:
        raise err("ERR_STATEMENT_NOT_FOUND")
    return s


def check_child(child, parent_field, parent_id, not_found_error):
    """Verify a nested resource belongs to the parent in the URL path."""
    if child.get(parent_field) != parent_id:
        raise err(not_found_error)
