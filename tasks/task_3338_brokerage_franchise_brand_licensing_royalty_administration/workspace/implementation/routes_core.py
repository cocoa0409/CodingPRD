"""Brands, markets, brokerages, agents."""
import re

from flask import Blueprint, g, request

import db
import helpers
import services as svc
from auth import forbidden_ownership, require_roles
from envelope import ok
from errors import ApiError
from helpers import body, paginate, req_nonempty_str, req_str, serialize

bp = Blueprint('core', __name__)

BRAND_CODE_RE = re.compile(r'^[A-Z0-9]{2,16}$')


# --- Brands -------------------------------------------------------------------

@bp.route('/franchise/brands', methods=['POST'])
@require_roles('FranchisorOps')
def create_brand():
    d = body()
    brand_code = d.get('brand_code')
    if not isinstance(brand_code, str) or not BRAND_CODE_RE.match(brand_code):
        raise ApiError('ERR_INVALID_REQUEST', 400,
                       'brand_code must be 2-16 uppercase letters/digits')
    display_name = req_str(d, 'display_name')
    if any(b['brand_code'] == brand_code for b in db.BRANDS.values()):
        raise ApiError('ERR_INVALID_REQUEST', 400, 'brand_code must be unique')
    brand = {
        'id': db.new_id(),
        'brand_code': brand_code,
        'display_name': display_name,
        'status': 'ACTIVE',
    }
    svc.stamp_new(brand)
    db.BRANDS[brand['id']] = brand
    return ok(serialize(brand), 201)


@bp.route('/franchise/brands', methods=['GET'])
@require_roles('FranchisorOps', 'FranchiseeAdmin', 'BrandAuditor')
def list_brands():
    return paginate(db.BRANDS.values(), request.args, ('status',))


@bp.route('/franchise/brands/<brand_id>', methods=['GET'])
@require_roles('FranchisorOps', 'FranchiseeAdmin', 'BrandAuditor')
def get_brand(brand_id):
    return ok(serialize(svc.get_or_404(db.BRANDS, brand_id, 'brand')))


@bp.route('/franchise/brands/<brand_id>/ad-fund-balance', methods=['GET'])
@require_roles('FranchisorOps', 'FranchiseeAdmin')
def brand_ad_fund_balance(brand_id):
    brand = svc.get_or_404(db.BRANDS, brand_id, 'brand')
    return ok({'balance_cents': svc.fund_balance(brand['id']),
               'brand_id': brand['id']})


@bp.route('/franchise/brands/<brand_id>/ad-fund-ledger', methods=['GET'])
@require_roles('FranchisorOps', 'FranchiseeAdmin')
def brand_ad_fund_ledger(brand_id):
    svc.get_or_404(db.BRANDS, brand_id, 'brand')
    items = [e for e in db.LEDGER if e['brand_id'] == brand_id]
    return paginate(items, request.args, ('entry_type', 'agreement_id', 'period_id'))


# --- Markets ------------------------------------------------------------------

@bp.route('/franchise/markets', methods=['POST'])
@require_roles('FranchisorOps')
def create_market():
    d = body()
    market_code = req_nonempty_str(d, 'market_code')
    name = req_str(d, 'name')
    if any(m['market_code'] == market_code for m in db.MARKETS.values()):
        raise ApiError('ERR_INVALID_REQUEST', 400, 'market_code must be unique')
    market = {
        'id': db.new_id(),
        'market_code': market_code,
        'name': name,
    }
    svc.stamp_new(market)
    db.MARKETS[market['id']] = market
    return ok(serialize(market), 201)


@bp.route('/franchise/markets', methods=['GET'])
@require_roles('FranchisorOps', 'FranchiseeAdmin', 'BrandAuditor')
def list_markets():
    return paginate(db.MARKETS.values(), request.args)


# --- Brokerages ---------------------------------------------------------------

@bp.route('/franchise/brokerages', methods=['POST'])
@require_roles('FranchisorOps')
def create_brokerage():
    d = body()
    home_market_id = d.get('home_market_id')
    if isinstance(home_market_id, str):  # existence (priority 4) before payload
        svc.get_or_404(db.MARKETS, home_market_id, 'market')
    legal_name = req_str(d, 'legal_name')
    principal_email = req_str(d, 'principal_email')
    home_market_id = req_str(d, 'home_market_id')
    brokerage = {
        'id': db.new_id(),
        'legal_name': legal_name,
        'home_market_id': home_market_id,
        'principal_email': principal_email,
        'status': 'PROSPECT',
    }
    svc.stamp_new(brokerage)
    db.BROKERAGES[brokerage['id']] = brokerage
    return ok(serialize(brokerage), 201)


@bp.route('/franchise/brokerages', methods=['GET'])
@require_roles('FranchisorOps', 'BrandAuditor')
def list_brokerages():
    return paginate(db.BROKERAGES.values(), request.args, ('status', 'home_market_id'))


@bp.route('/franchise/brokerages/<brokerage_id>', methods=['GET'])
@require_roles('FranchisorOps', 'FranchiseeAdmin', 'BrandAuditor')
def get_brokerage(brokerage_id):
    return ok(serialize(svc.get_or_404(db.BROKERAGES, brokerage_id, 'brokerage')))


# --- Agents -------------------------------------------------------------------

@bp.route('/franchise/brokerages/<brokerage_id>/agents', methods=['POST'])
@require_roles('FranchisorOps', 'FranchiseeAdmin')
def create_agent(brokerage_id):
    # Ownership (priority 3): a FranchiseeAdmin may only act in own scope.
    if g.role == 'FranchiseeAdmin' and g.uid != brokerage_id:
        raise forbidden_ownership()
    brokerage = svc.get_or_404(db.BROKERAGES, brokerage_id, 'brokerage')
    d = body()
    full_name = req_str(d, 'full_name')
    license_no = req_nonempty_str(d, 'license_no')
    affiliated_on = d.get('affiliated_on')
    if not isinstance(affiliated_on, str) or db.parse_iso(affiliated_on) is None:
        raise ApiError('ERR_INVALID_REQUEST', 400,
                       'affiliated_on must be an ISO8601 date')
    if any(a['brokerage_id'] == brokerage_id and a['license_no'] == license_no
           for a in db.AGENTS.values()):
        raise ApiError('ERR_DUPLICATE_LICENSE', 409,
                       'license_no already registered under this brokerage')
    if brokerage['status'] == 'TERMINATED':
        raise ApiError('ERR_BROKERAGE_TERMINATED', 409,
                       'cannot register agents under a TERMINATED brokerage')
    agent = {
        'id': db.new_id(),
        'brokerage_id': brokerage_id,
        'full_name': full_name,
        'license_no': license_no,
        'affiliated_on': affiliated_on,
        'status': 'ACTIVE',
    }
    svc.stamp_new(agent)
    db.AGENTS[agent['id']] = agent
    return ok(serialize(agent), 201)


@bp.route('/franchise/brokerages/<brokerage_id>/agents', methods=['GET'])
@require_roles('FranchisorOps', 'FranchiseeAdmin', 'BrandAuditor')
def list_agents(brokerage_id):
    svc.get_or_404(db.BROKERAGES, brokerage_id, 'brokerage')
    items = [a for a in db.AGENTS.values() if a['brokerage_id'] == brokerage_id]
    return paginate(items, request.args, ('status',))


@bp.route('/franchise/agents/<agent_id>/deactivate', methods=['POST'])
@require_roles('FranchiseeAdmin')
def deactivate_agent(agent_id):
    agent = svc.get_or_404(db.AGENTS, agent_id, 'agent')
    if g.uid != agent['brokerage_id']:
        raise forbidden_ownership()
    if agent['status'] != 'ACTIVE':
        raise ApiError('ERR_INVALID_STATE', 409, 'agent is not ACTIVE')
    agent['status'] = 'INACTIVE'
    svc.touch(agent)
    return ok(serialize(agent))


@bp.route('/franchise/agents/<agent_id>/reactivate', methods=['POST'])
@require_roles('FranchiseeAdmin')
def reactivate_agent(agent_id):
    agent = svc.get_or_404(db.AGENTS, agent_id, 'agent')
    if g.uid != agent['brokerage_id']:
        raise forbidden_ownership()
    if agent['status'] != 'INACTIVE':
        raise ApiError('ERR_INVALID_STATE', 409, 'agent is not INACTIVE')
    brokerage = db.BROKERAGES.get(agent['brokerage_id'])
    if brokerage is not None and brokerage['status'] == 'TERMINATED':
        raise ApiError('ERR_BROKERAGE_TERMINATED', 409,
                       'cannot reactivate agents of a TERMINATED brokerage')
    if brokerage is None or brokerage['status'] != 'FRANCHISED':
        raise ApiError('ERR_INVALID_STATE', 409,
                       'brokerage must be FRANCHISED to reactivate agents')
    agent['status'] = 'ACTIVE'
    svc.touch(agent)
    return ok(serialize(agent))
