"""Monthly reports, royalty periods, ledger views, and default cases."""
from flask import Blueprint, g, request

import db
import services as svc
from auth import REPORTED_BY_ROLE, forbidden_ownership, require_roles
from envelope import ok
from errors import ApiError
from helpers import body, paginate, req_enum, req_int, req_period_month, serialize

bp = Blueprint('billing', __name__)


def _check_report_ownership(agreement):
    if g.role == 'FranchiseeAdmin' and g.uid != agreement['brokerage_id']:
        raise forbidden_ownership()


def _check_agreement_live(agreement):
    if agreement['status'] not in ('ACTIVE', 'SUSPENDED'):
        raise ApiError('ERR_AGREEMENT_NOT_LIVE', 409,
                       'reports and assessments require an ACTIVE or SUSPENDED agreement')


# --- Agent count reports -------------------------------------------------------

@bp.route('/franchise/agreements/<agreement_id>/agent-count-reports', methods=['POST'])
@require_roles('FranchiseeAdmin', 'FranchisorOps')
def create_agent_count_report(agreement_id):
    ag = svc.get_or_404(db.AGREEMENTS, agreement_id, 'agreement')
    _check_report_ownership(ag)
    d = body()
    period_month = req_period_month(d)
    count = req_int(d, 'active_agent_count')
    if count < 0:
        raise ApiError('ERR_INVALID_REQUEST', 400, 'active_agent_count must be >= 0')
    if any(r['agreement_id'] == agreement_id and r['period_month'] == period_month
           for r in db.AC_REPORTS.values()):
        raise ApiError('ERR_DUPLICATE_REPORT', 409,
                       'an agent count report already exists for this agreement and month')
    _check_agreement_live(ag)
    report = {
        'id': db.new_id(),
        'agreement_id': agreement_id,
        'period_month': period_month,
        'active_agent_count': count,
        'reported_at': db.logical_now_iso(),
    }
    svc.stamp_append(report)
    db.AC_REPORTS[report['id']] = report
    return ok(serialize(report), 201)


@bp.route('/franchise/agreements/<agreement_id>/agent-count-reports', methods=['GET'])
@require_roles('FranchisorOps', 'FranchiseeAdmin')
def list_agent_count_reports(agreement_id):
    svc.get_or_404(db.AGREEMENTS, agreement_id, 'agreement')
    items = [r for r in db.AC_REPORTS.values() if r['agreement_id'] == agreement_id]
    return paginate(items, request.args)


# --- GCI reports ---------------------------------------------------------------

@bp.route('/franchise/agreements/<agreement_id>/gci-reports', methods=['POST'])
@require_roles('FranchiseeAdmin', 'FranchisorOps')
def create_gci_report(agreement_id):
    ag = svc.get_or_404(db.AGREEMENTS, agreement_id, 'agreement')
    _check_report_ownership(ag)
    d = body()
    period_month = req_period_month(d)
    gci_cents = req_int(d, 'gci_cents')
    if gci_cents < 0:
        raise ApiError('ERR_INVALID_REQUEST', 400, 'gci_cents must be >= 0')
    if any(r['agreement_id'] == agreement_id and r['period_month'] == period_month
           for r in db.GCI_REPORTS.values()):
        raise ApiError('ERR_DUPLICATE_REPORT', 409,
                       'a GCI report already exists for this agreement and month')
    _check_agreement_live(ag)
    report = {
        'id': db.new_id(),
        'agreement_id': agreement_id,
        'period_month': period_month,
        'gci_cents': gci_cents,
        'reported_at': db.logical_now_iso(),
        'reported_by_role': REPORTED_BY_ROLE[g.role],
    }
    svc.stamp_append(report)
    db.GCI_REPORTS[report['id']] = report
    return ok(serialize(report), 201)


@bp.route('/franchise/agreements/<agreement_id>/gci-reports', methods=['GET'])
@require_roles('FranchisorOps', 'FranchiseeAdmin')
def list_gci_reports(agreement_id):
    svc.get_or_404(db.AGREEMENTS, agreement_id, 'agreement')
    items = [r for r in db.GCI_REPORTS.values() if r['agreement_id'] == agreement_id]
    return paginate(items, request.args)


# --- Royalty periods -----------------------------------------------------------

@bp.route('/franchise/agreements/<agreement_id>/royalty-periods', methods=['POST'])
@require_roles('FranchisorOps')
def assess_royalty_period(agreement_id):
    ag = svc.get_or_404(db.AGREEMENTS, agreement_id, 'agreement')
    d = body()
    period_month = req_period_month(d)
    # Period uniqueness (priority 12) before missing-report (13) and liveness (24).
    if any(p['agreement_id'] == agreement_id and p['period_month'] == period_month
           for p in db.PERIODS.values()):
        raise ApiError('ERR_DUPLICATE_PERIOD', 409,
                       'a royalty period already exists for this agreement and month')
    report = next((r for r in db.GCI_REPORTS.values()
                   if r['agreement_id'] == agreement_id
                   and r['period_month'] == period_month), None)
    if report is None:
        raise ApiError('ERR_GCI_REPORT_MISSING', 422,
                       'no GCI report exists for this agreement and month')
    _check_agreement_live(ag)
    period = svc.assess_royalty(ag, period_month, report)
    return ok(serialize(period), 201)


@bp.route('/franchise/agreements/<agreement_id>/royalty-periods', methods=['GET'])
@require_roles('FranchisorOps', 'FranchiseeAdmin')
def list_royalty_periods(agreement_id):
    svc.get_or_404(db.AGREEMENTS, agreement_id, 'agreement')
    items = [p for p in db.PERIODS.values() if p['agreement_id'] == agreement_id]
    return paginate(items, request.args)


@bp.route('/franchise/agreements/<agreement_id>/ad-fund-ledger', methods=['GET'])
@require_roles('FranchisorOps', 'FranchiseeAdmin')
def agreement_ad_fund_ledger(agreement_id):
    svc.get_or_404(db.AGREEMENTS, agreement_id, 'agreement')
    items = [e for e in db.LEDGER if e['agreement_id'] == agreement_id]
    return paginate(items, request.args, ('entry_type',))


@bp.route('/franchise/royalty-periods/<period_id>', methods=['GET'])
@require_roles('FranchisorOps', 'FranchiseeAdmin')
def get_royalty_period(period_id):
    return ok(serialize(svc.get_or_404(db.PERIODS, period_id, 'royalty period')))


@bp.route('/franchise/royalty-periods/<period_id>/ad-fund-ledger', methods=['GET'])
@require_roles('FranchisorOps', 'FranchiseeAdmin')
def period_ad_fund_ledger(period_id):
    svc.get_or_404(db.PERIODS, period_id, 'royalty period')
    items = [e for e in db.LEDGER if e['period_id'] == period_id]
    return paginate(items, request.args)


@bp.route('/franchise/royalty-periods/<period_id>/settle', methods=['POST'])
@require_roles('FranchisorOps')
def settle_royalty_period(period_id):
    period = svc.get_or_404(db.PERIODS, period_id, 'royalty period')
    if period['status'] != 'ASSESSED':
        raise ApiError('ERR_INVALID_STATE', 409, 'only ASSESSED periods can be settled')
    period['status'] = 'SETTLED'
    period['settled_at'] = db.logical_now_iso()
    svc.touch(period)
    return ok(serialize(period))


@bp.route('/franchise/royalty-periods/<period_id>/waive', methods=['POST'])
@require_roles('FranchisorOps')
def waive_royalty_period(period_id):
    period = svc.get_or_404(db.PERIODS, period_id, 'royalty period')
    if period['status'] != 'ASSESSED':
        raise ApiError('ERR_INVALID_STATE', 409, 'only ASSESSED periods can be waived')
    if period['royalty_due_cents'] != 0:
        raise ApiError('ERR_WAIVE_REQUIRES_ZERO_DUE', 422,
                       'only periods with royalty_due_cents == 0 may be waived')
    period['status'] = 'WAIVED'
    svc.touch(period)
    return ok(serialize(period))


# --- Default cases --------------------------------------------------------------

DEFAULT_REASON_CODES = {'PAYMENT', 'BRAND_STANDARDS', 'REPORTING', 'TERRITORY'}


@bp.route('/franchise/agreements/<agreement_id>/default-cases', methods=['POST'])
@require_roles('FranchisorOps')
def create_default_case(agreement_id):
    ag = svc.get_or_404(db.AGREEMENTS, agreement_id, 'agreement')
    d = body()
    reason = req_enum(d, 'reason_code', DEFAULT_REASON_CODES)
    case = svc.create_default_case(agreement_id, reason)
    svc.recompute_open_cure_count(ag)
    return ok(serialize(case), 201)


@bp.route('/franchise/agreements/<agreement_id>/default-cases', methods=['GET'])
@require_roles('FranchisorOps', 'FranchiseeAdmin', 'BrandAuditor')
def list_default_cases(agreement_id):
    svc.get_or_404(db.AGREEMENTS, agreement_id, 'agreement')
    items = [c for c in db.DEFAULTS.values() if c['agreement_id'] == agreement_id]
    return paginate(items, request.args, ('status',))


@bp.route('/franchise/default-cases/<case_id>/start-cure', methods=['POST'])
@require_roles('FranchisorOps')
def start_cure_default_case(case_id):
    case = svc.get_or_404(db.DEFAULTS, case_id, 'default case')
    if case['status'] != 'OPEN':
        raise ApiError('ERR_INVALID_STATE', 409, 'only OPEN defaults can start curing')
    case['status'] = 'CURING'
    svc.touch(case)
    return ok(serialize(case))


@bp.route('/franchise/default-cases/<case_id>/escalate', methods=['POST'])
@require_roles('FranchisorOps')
def escalate_default_case(case_id):
    case = svc.get_or_404(db.DEFAULTS, case_id, 'default case')
    if case['status'] not in ('OPEN', 'CURING'):
        raise ApiError('ERR_INVALID_STATE', 409,
                       'only OPEN or CURING defaults can be escalated')
    case['status'] = 'ESCALATED'
    case['escalated_at'] = db.logical_now_iso()
    svc.touch(case)
    # ESCALATED cases no longer count toward open_cure_count.
    ag = db.AGREEMENTS.get(case['agreement_id'])
    if ag is not None:
        svc.recompute_open_cure_count(ag)
    return ok(serialize(case))


@bp.route('/franchise/default-cases/<case_id>/resolve', methods=['POST'])
@require_roles('FranchisorOps')
def resolve_default_case(case_id):
    case = svc.get_or_404(db.DEFAULTS, case_id, 'default case')
    if case['status'] not in ('OPEN', 'CURING', 'ESCALATED'):
        raise ApiError('ERR_INVALID_STATE', 409,
                       'only OPEN, CURING, or ESCALATED defaults can be resolved')
    case['status'] = 'RESOLVED'
    svc.touch(case)
    ag = db.AGREEMENTS.get(case['agreement_id'])
    if ag is not None:
        svc.recompute_open_cure_count(ag)
        svc.maybe_resume_agreement(ag)
    return ok(serialize(case))
