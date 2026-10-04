import os
from flask import Flask, request
from store import db, new_id, get_clock, set_clock, parse_dt, format_dt
from resp import ok, error_response, ApiError, err, parse_pagination, list_page
from auth import auth_headers, require_role
import helpers as H

app = Flask(__name__)

ALL_STAFF = ['LabManager', 'EditorialDirector', 'MethodologyOfficer', 'SurveyDirector',
             'SafetyOfficer', 'ContentEditor', 'ComplianceOfficer', 'PurchasingAgent',
             'LabTechnician']


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return error_response('ERR_NOT_FOUND', 'Resource not found', 404)


@app.errorhandler(405)
def handle_405(e):
    return error_response('ERR_NOT_FOUND', 'Resource not found', 404)


@app.errorhandler(Exception)
def handle_exc(e):
    return error_response('ERR_INVALID_REQUEST', str(e), 400)


def body():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        err('ERR_INVALID_REQUEST', 'Request body must be a JSON object', 400)
    return data


def require_fields(data, fields):
    for f in fields:
        if f not in data or data[f] is None:
            err('ERR_INVALID_REQUEST', f'Missing required field: {f}', 400)


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_num(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def get_or_404(store, rid):
    r = db[store].get(rid)
    if r is None:
        err('ERR_NOT_FOUND', f'{store} {rid} not found', 404)
    return r


# ---------------------------------------------------------------- clock/cycle

@app.route('/_clock/set_current_utc', methods=['POST'])
def set_clock_ep():
    uid, role = auth_headers()
    require_role(role, ['LabManager'])
    data = body()
    require_fields(data, ['to_iso8601'])
    dt = parse_dt(data['to_iso8601'])
    if dt is None:
        err('ERR_INVALID_REQUEST', 'to_iso8601 must be a valid ISO8601 timestamp', 400)
    set_clock(dt)
    return ok({'current_utc': format_dt(dt)})


@app.route('/_cycle/run', methods=['POST'])
def cycle_run():
    uid, role = auth_headers()
    require_role(role, ['LabManager'])
    clock = get_clock()
    categories_rescored = 0
    for cat in db['product_categories'].values():
        if cat['status'] == 'RETIRED':
            continue
        cat['selection_score'] = H.compute_selection_score(cat)
        categories_rescored += 1
    subscriptions_transitioned = 0
    members_lapsed = 0
    for member in db['members'].values():
        for sub in member['subscriptions']:
            if sub['status'] not in ('ACTIVE', 'GRACE'):
                continue
            term_end = parse_dt(sub['term_end'])
            grace_until = parse_dt(sub['grace_until'])
            if clock <= term_end:
                new_status = 'ACTIVE'
            elif clock <= grace_until:
                new_status = 'GRACE'
            else:
                new_status = 'EXPIRED'
            if new_status != sub['status']:
                sub['status'] = new_status
                subscriptions_transitioned += 1
        # member cascade: latest subscription EXPIRED -> LAPSED
        subs = member['subscriptions']
        if subs and subs[-1]['status'] == 'EXPIRED' and member['status'] == 'ACTIVE':
            member['status'] = 'LAPSED'
            H.bump(member)
            members_lapsed += 1
    return ok({
        'categories_rescored': categories_rescored,
        'subscriptions_transitioned': subscriptions_transitioned,
        'members_lapsed': members_lapsed,
    })


# ---------------------------------------------------------------- categories

@app.route('/product-categories', methods=['POST'])
def create_category():
    uid, role = auth_headers()
    require_role(role, ['LabManager'])
    data = body()
    require_fields(data, ['name', 'refresh_cycle_months', 'market_share_pct', 'member_interest_pct'])
    name = data['name']
    if any(c['name'] == name for c in db['product_categories'].values()):
        err('ERR_DUPLICATE', 'Category name must be unique', 422)
    rcm = data['refresh_cycle_months']
    ms = data['market_share_pct']
    mi = data['member_interest_pct']
    if not isinstance(name, str) or not name:
        err('ERR_INVALID_REQUEST', 'name must be a non-empty string', 400)
    if not is_int(rcm) or rcm < 1:
        err('ERR_INVALID_REQUEST', 'refresh_cycle_months must be an integer >= 1', 400)
    if not is_num(ms) or ms < 0 or ms > 100:
        err('ERR_INVALID_REQUEST', 'market_share_pct must be a number in [0,100]', 400)
    if not is_num(mi) or mi < 0 or mi > 100:
        err('ERR_INVALID_REQUEST', 'member_interest_pct must be a number in [0,100]', 400)
    cat = H.new_common({
        'id': new_id(),
        'name': name,
        'refresh_cycle_months': rcm,
        'market_share_pct': ms,
        'member_interest_pct': mi,
        'last_published_at': None,
        'selection_score': 0,
        'status': 'ACTIVE',
    })
    cat['selection_score'] = H.compute_selection_score(cat)
    db['product_categories'][cat['id']] = cat
    return ok(cat, 201)


@app.route('/product-categories/<cid>', methods=['GET'])
def get_category(cid):
    uid, role = auth_headers()
    require_role(role, ALL_STAFF)
    return ok(get_or_404('product_categories', cid))


# ---------------------------------------------------------------- programs

@app.route('/test-programs', methods=['POST'])
def create_program():
    uid, role = auth_headers()
    require_role(role, ['LabManager'])
    data = body()
    require_fields(data, ['category_id', 'fiscal_year', 'budget_cents'])
    cat = db['product_categories'].get(data['category_id'])
    if cat is None or cat['status'] != 'ACTIVE':
        err('ERR_REFERENTIAL_INTEGRITY', 'category_id must reference an ACTIVE category', 422)
    if not is_int(data['fiscal_year']):
        err('ERR_INVALID_REQUEST', 'fiscal_year must be an integer', 400)
    if not is_int(data['budget_cents']) or data['budget_cents'] < 0:
        err('ERR_INVALID_REQUEST', 'budget_cents must be an integer >= 0', 400)
    prog = H.new_common({
        'id': new_id(),
        'category_id': data['category_id'],
        'fiscal_year': data['fiscal_year'],
        'budget_cents': data['budget_cents'],
        'committed_cents': 0,
        'proposed_by_user_id': uid,
        'approved_by_user_id': None,
        'status': 'PROPOSED',
    })
    db['test_programs'][prog['id']] = prog
    return ok(prog, 201)


@app.route('/test-programs', methods=['GET'])
def list_programs():
    uid, role = auth_headers()
    require_role(role, ALL_STAFF)
    limit, offset = parse_pagination(request.args)
    items = sorted(db['test_programs'].values(), key=lambda r: r['created_at'])
    cid = request.args.get('category_id')
    if cid:
        items = [p for p in items if p['category_id'] == cid]
    st = request.args.get('status')
    if st:
        items = [p for p in items if p['status'] == st]
    page, pag = list_page(items, limit, offset)
    return ok(page, 200, pag)


@app.route('/test-programs/<pid>', methods=['GET'])
def get_program(pid):
    uid, role = auth_headers()
    require_role(role, ALL_STAFF)
    return ok(get_or_404('test_programs', pid))


@app.route('/test-programs/<pid>/transitions', methods=['POST'])
def program_transition(pid):
    uid, role = auth_headers()
    require_role(role, ['LabManager', 'EditorialDirector'])
    prog = get_or_404('test_programs', pid)
    data = body()
    action = data.get('action')
    valid = {'approve', 'start_sourcing', 'start_testing', 'start_scoring', 'ready', 'cancel'}
    if action not in valid:
        err('ERR_INVALID_STATE', f'Unknown action: {action}', 409)
    # per-action role checks
    if action in ('approve', 'cancel'):
        require_role(role, ['EditorialDirector'])
    else:
        require_role(role, ['LabManager'])

    if action == 'approve':
        if prog['status'] != 'PROPOSED':
            err('ERR_INVALID_STATE', 'approve requires PROPOSED', 409)
        if uid == prog['proposed_by_user_id']:
            err('ERR_SOD_VIOLATION', 'approver must differ from proposer', 422)
        prog['approved_by_user_id'] = uid
        prog['status'] = 'APPROVED'
        H.bump(prog)
    elif action == 'cancel':
        if prog['status'] not in ('PROPOSED', 'APPROVED'):
            err('ERR_INVALID_STATE', 'cancel requires PROPOSED or APPROVED', 409)
        for po in H.pos_of_program(pid):
            if po['status'] == 'DRAFT':
                po['status'] = 'CANCELLED'
                H.bump(po)
        prog['status'] = 'CANCELLED'
        H.bump(prog)
    elif action == 'start_sourcing':
        if prog['status'] != 'APPROVED':
            err('ERR_INVALID_STATE', 'start_sourcing requires APPROVED', 409)
        samples = H.samples_of_program(pid)
        if not samples:
            err('ERR_INVALID_STATE', 'program needs >= 1 TestSample', 409)
        if H.active_protocol_of_category(prog['category_id']) is None:
            err('ERR_INVALID_STATE', 'no ACTIVE protocol for category', 409)
        for s in samples:
            if s['status'] == 'PLANNED':
                s['status'] = 'SOURCING'
                H.bump(s)
        prog['status'] = 'SAMPLE_SOURCING'
        H.bump(prog)
    elif action == 'start_testing':
        if prog['status'] != 'SAMPLE_SOURCING':
            err('ERR_INVALID_STATE', 'start_testing requires SAMPLE_SOURCING', 409)
        for s in H.samples_of_program(pid):
            if not s['sourcing_complete']:
                err('ERR_INVALID_STATE', 'all samples must have sourcing_complete', 409)
        for po in H.pos_of_program(pid):
            if po['status'] in ('DRAFT', 'PLACED'):
                err('ERR_INVALID_STATE', 'no DRAFT or PLACED purchase orders allowed', 409)
        for s in H.samples_of_program(pid):
            s['status'] = 'IN_LAB'
            H.bump(s)
        prog['status'] = 'TESTING'
        H.bump(prog)
    elif action == 'start_scoring':
        if prog['status'] != 'TESTING':
            err('ERR_INVALID_STATE', 'start_scoring requires TESTING', 409)
        for s in H.samples_of_program(pid):
            H.recompute_sample_testing(s)
            if not s['testing_complete']:
                err('ERR_INVALID_STATE', 'all samples must have testing_complete', 409)
        for s in H.samples_of_program(pid):
            s['lab_score'] = H.compute_lab_score(s)
            H.bump(s)
        prog['status'] = 'SCORING'
        H.bump(prog)
    elif action == 'ready':
        if prog['status'] != 'SCORING':
            err('ERR_INVALID_STATE', 'ready requires SCORING', 409)
        for f in H.findings_of_program(pid):
            if f['status'] in ('OPEN', 'ESCALATED') and f['escalation_tier'] >= 2:
                err('ERR_SAFETY_GATE', 'open high-tier safety finding blocks ready', 422)
        for s in H.samples_of_program(pid):
            if s['status'] == 'IN_LAB':
                s['status'] = 'SCORED'
                H.bump(s)
        prog['status'] = 'READY_FOR_PUBLICATION'
        H.bump(prog)
    return ok(prog)


# ---------------------------------------------------------------- protocols

@app.route('/lab-protocols', methods=['POST'])
def create_protocol():
    uid, role = auth_headers()
    require_role(role, ['LabManager'])
    data = body()
    require_fields(data, ['category_id', 'protocol_code', 'measurement_repeat_min',
                          'perf_weight_pct', 'reliability_weight_pct'])
    cat = db['product_categories'].get(data['category_id'])
    if cat is None:
        err('ERR_REFERENTIAL_INTEGRITY', 'category_id must reference an existing category', 422)
    mrm = data['measurement_repeat_min']
    pw = data['perf_weight_pct']
    rw = data['reliability_weight_pct']
    if not is_int(mrm) or mrm < 1:
        err('ERR_PROTOCOL_WEIGHTS', 'measurement_repeat_min must be >= 1', 422)
    if not is_int(pw) or pw < 1 or pw > 98 or not is_int(rw) or rw < 1 or rw > 98 or (pw + rw) > 99:
        err('ERR_PROTOCOL_WEIGHTS', 'weights must be 1..98 and sum <= 99', 422)
    code = data['protocol_code']
    if not isinstance(code, str) or not code:
        err('ERR_INVALID_REQUEST', 'protocol_code must be a non-empty string', 400)
    for p in db['lab_protocols'].values():
        if (p['category_id'] == data['category_id'] and p['protocol_code'] == code
                and p['status'] in ('DRAFT', 'IN_REVIEW', 'ACTIVE')):
            err('ERR_PROTOCOL_WEIGHTS', 'duplicate live protocol_code in category', 422)
    prot = H.new_common({
        'id': new_id(),
        'category_id': data['category_id'],
        'protocol_code': code,
        'measurement_repeat_min': mrm,
        'perf_weight_pct': pw,
        'reliability_weight_pct': rw,
        'convenience_weight_pct': 100 - pw - rw,
        'activated_at': None,
        'status': 'DRAFT',
    })
    db['lab_protocols'][prot['id']] = prot
    return ok(prot, 201)


@app.route('/lab-protocols', methods=['GET'])
def list_protocols():
    uid, role = auth_headers()
    require_role(role, ['LabManager', 'EditorialDirector', 'MethodologyOfficer', 'LabTechnician', 'ContentEditor'])
    limit, offset = parse_pagination(request.args)
    items = sorted(db['lab_protocols'].values(), key=lambda r: r['created_at'])
    cid = request.args.get('category_id')
    if cid:
        items = [p for p in items if p['category_id'] == cid]
    st = request.args.get('status')
    if st:
        items = [p for p in items if p['status'] == st]
    page, pag = list_page(items, limit, offset)
    return ok(page, 200, pag)


@app.route('/lab-protocols/<pid>', methods=['GET'])
def get_protocol(pid):
    uid, role = auth_headers()
    require_role(role, ['LabManager', 'EditorialDirector', 'MethodologyOfficer', 'LabTechnician', 'ContentEditor'])
    return ok(get_or_404('lab_protocols', pid))


@app.route('/lab-protocols/<pid>/transitions', methods=['POST'])
def protocol_transition(pid):
    uid, role = auth_headers()
    require_role(role, ['LabManager', 'MethodologyOfficer'])
    prot = get_or_404('lab_protocols', pid)
    data = body()
    action = data.get('action')
    valid = {'submit_review', 'return_draft', 'activate', 'retire'}
    if action not in valid:
        err('ERR_INVALID_STATE', f'Unknown action: {action}', 409)
    if action == 'submit_review':
        require_role(role, ['LabManager'])
    else:
        require_role(role, ['MethodologyOfficer'])

    if action == 'submit_review':
        if prot['status'] != 'DRAFT':
            err('ERR_INVALID_STATE', 'submit_review requires DRAFT', 409)
        if prot['measurement_repeat_min'] < 1 or prot['perf_weight_pct'] + prot['reliability_weight_pct'] > 99:
            err('ERR_PROTOCOL_WEIGHTS', 'protocol weights invalid', 422)
        prot['status'] = 'IN_REVIEW'
        H.bump(prot)
    elif action == 'return_draft':
        if prot['status'] != 'IN_REVIEW':
            err('ERR_INVALID_STATE', 'return_draft requires IN_REVIEW', 409)
        prot['status'] = 'DRAFT'
        H.bump(prot)
    elif action == 'activate':
        if prot['status'] != 'IN_REVIEW':
            err('ERR_INVALID_STATE', 'activate requires IN_REVIEW', 409)
        if 'expected_category_version' not in data:
            err('ERR_INVALID_REQUEST', 'expected_category_version is required for activate', 400)
        cat = db['product_categories'][prot['category_id']]
        if data['expected_category_version'] != cat['version']:
            err('ERR_STALE_VERSION', 'category version mismatch', 412)
        for p in db['lab_protocols'].values():
            if p['category_id'] == prot['category_id'] and p['status'] == 'ACTIVE' and p['id'] != pid:
                p['status'] = 'SUPERSEDED'
                H.bump(p)
        prot['activated_at'] = format_dt(get_clock())
        prot['status'] = 'ACTIVE'
        H.bump(cat)
        H.bump(prot)
    elif action == 'retire':
        if prot['status'] not in ('DRAFT', 'ACTIVE'):
            err('ERR_INVALID_STATE', 'retire requires DRAFT or ACTIVE', 409)
        if prot['status'] == 'ACTIVE':
            for prog in H.programs_of_category(prot['category_id']):
                if prog['status'] in ('SAMPLE_SOURCING', 'TESTING', 'SCORING'):
                    err('ERR_INVALID_STATE', 'ACTIVE protocol cannot retire while programs in flight', 409)
        prot['status'] = 'RETIRED'
        H.bump(prot)
    return ok(prot)


# ---------------------------------------------------------------- samples

@app.route('/test-samples', methods=['POST'])
def create_sample():
    uid, role = auth_headers()
    require_role(role, ['LabManager'])
    data = body()
    require_fields(data, ['program_id', 'model_label', 'required_units'])
    prog = db['test_programs'].get(data['program_id'])
    if prog is None or prog['status'] not in ('PROPOSED', 'APPROVED'):
        err('ERR_REFERENTIAL_INTEGRITY', 'program must be PROPOSED or APPROVED', 422)
    if not isinstance(data['model_label'], str) or not data['model_label']:
        err('ERR_INVALID_REQUEST', 'model_label must be a non-empty string', 400)
    if not is_int(data['required_units']) or data['required_units'] < 1:
        err('ERR_INVALID_REQUEST', 'required_units must be an integer >= 1', 400)
    s = H.new_common({
        'id': new_id(),
        'program_id': data['program_id'],
        'model_label': data['model_label'],
        'required_units': data['required_units'],
        'sourcing_mode': 'ANONYMOUS_RETAIL',
        'sourced_units': 0,
        'sourcing_complete': False,
        'tested_units': 0,
        'testing_complete': False,
        'lab_score': None,
        'status': 'PLANNED',
    })
    db['test_samples'][s['id']] = s
    return ok(s, 201)


@app.route('/test-samples', methods=['GET'])
def list_samples():
    uid, role = auth_headers()
    require_role(role, ['LabManager', 'LabTechnician', 'PurchasingAgent', 'ComplianceOfficer', 'ContentEditor', 'SafetyOfficer'])
    limit, offset = parse_pagination(request.args)
    items = sorted(db['test_samples'].values(), key=lambda r: r['created_at'])
    pid = request.args.get('program_id')
    if pid:
        items = [s for s in items if s['program_id'] == pid]
    st = request.args.get('status')
    if st:
        items = [s for s in items if s['status'] == st]
    page, pag = list_page(items, limit, offset)
    return ok(page, 200, pag)


@app.route('/test-samples/<sid>', methods=['GET'])
def get_sample(sid):
    uid, role = auth_headers()
    require_role(role, ['LabManager', 'LabTechnician', 'PurchasingAgent', 'ComplianceOfficer', 'ContentEditor', 'SafetyOfficer'])
    return ok(get_or_404('test_samples', sid))


@app.route('/test-samples/<sid>/measurements', methods=['GET'])
def list_sample_measurements(sid):
    uid, role = auth_headers()
    require_role(role, ['LabTechnician', 'LabManager', 'MethodologyOfficer'])
    get_or_404('test_samples', sid)
    limit, offset = parse_pagination(request.args)
    items = sorted([m for m in db['measurements'].values() if m['sample_id'] == sid],
                   key=lambda r: r['created_at'])
    page, pag = list_page(items, limit, offset)
    return ok(page, 200, pag)


# ---------------------------------------------------------------- measurements

@app.route('/measurements', methods=['POST'])
def create_measurement():
    uid, role = auth_headers()
    require_role(role, ['LabTechnician'])
    data = body()
    require_fields(data, ['sample_id', 'unit_index', 'metric_code', 'value_num'])
    sample = db['test_samples'].get(data['sample_id'])
    if sample is None or sample['status'] != 'IN_LAB':
        err('ERR_REFERENTIAL_INTEGRITY', 'sample must exist and be IN_LAB', 422)
    if not is_int(data['unit_index']) or not (1 <= data['unit_index'] <= sample['required_units']):
        err('ERR_INVALID_REQUEST', 'unit_index out of range', 400)
    if not isinstance(data['metric_code'], str) or not data['metric_code']:
        err('ERR_INVALID_REQUEST', 'metric_code must be a non-empty string', 400)
    if not is_num(data['value_num']):
        err('ERR_INVALID_REQUEST', 'value_num must be a number', 400)
    m = {
        'id': new_id(),
        'sample_id': sample['id'],
        'unit_index': data['unit_index'],
        'metric_code': data['metric_code'],
        'value_num': data['value_num'],
        'recorded_at': format_dt(get_clock()),
        'recorded_by_user_id': uid,
        'created_at': format_dt(get_clock()),
    }
    db['measurements'][m['id']] = m
    H.recompute_sample_testing(sample)
    return ok(m, 201)


# ---------------------------------------------------------------- purchase orders

@app.route('/purchase-orders', methods=['POST'])
def create_po():
    uid, role = auth_headers()
    require_role(role, ['PurchasingAgent'])
    data = body()
    require_fields(data, ['program_id', 'buyer_alias', 'retailer_name', 'receipt_doc_ref',
                          'shipping_cents', 'lines'])
    prog = db['test_programs'].get(data['program_id'])
    if prog is None or prog['status'] != 'SAMPLE_SOURCING':
        err('ERR_REFERENTIAL_INTEGRITY', 'program must be SAMPLE_SOURCING', 422)
    # sourcing integrity (priority 5)
    if H.is_manufacturer_direct(data['retailer_name']) or H.is_manufacturer_name(data['buyer_alias']):
        err('ERR_SOURCING_INTEGRITY', 'manufacturer-direct sourcing or manufacturer identity detected', 422)
    if not isinstance(data['buyer_alias'], str) or not data['buyer_alias']:
        err('ERR_INVALID_REQUEST', 'buyer_alias must be a non-empty string', 400)
    if not isinstance(data['retailer_name'], str) or not data['retailer_name']:
        err('ERR_INVALID_REQUEST', 'retailer_name must be a non-empty string', 400)
    if not isinstance(data['receipt_doc_ref'], str):
        err('ERR_INVALID_REQUEST', 'receipt_doc_ref must be a string', 400)
    if not is_int(data['shipping_cents']) or data['shipping_cents'] < 0:
        err('ERR_INVALID_REQUEST', 'shipping_cents must be an integer >= 0', 400)
    lines = data['lines']
    if not isinstance(lines, list) or len(lines) < 1:
        err('ERR_INVALID_REQUEST', 'lines must be a non-empty array', 400)
    prog_samples = {s['id'] for s in H.samples_of_program(prog['id'])}
    subtotal = 0
    tax = 0
    new_lines = []
    for line in lines:
        if not isinstance(line, dict):
            err('ERR_INVALID_REQUEST', 'each line must be an object', 400)
        for f in ('sample_id', 'unit_price_cents', 'qty', 'tax_rate_bp'):
            if f not in line or line[f] is None:
                err('ERR_INVALID_REQUEST', f'line missing field: {f}', 400)
        if line['sample_id'] not in prog_samples:
            err('ERR_REFERENTIAL_INTEGRITY', 'line sample must belong to the program', 422)
        if not is_int(line['unit_price_cents']) or line['unit_price_cents'] < 0:
            err('ERR_INVALID_REQUEST', 'unit_price_cents must be >= 0', 400)
        if not is_int(line['qty']) or line['qty'] < 1:
            err('ERR_INVALID_REQUEST', 'qty must be >= 1', 400)
        if not is_int(line['tax_rate_bp']) or not (0 <= line['tax_rate_bp'] <= 20000):
            err('ERR_INVALID_REQUEST', 'tax_rate_bp must be in [0,20000]', 400)
        raw = line['unit_price_cents'] * line['qty'] * line['tax_rate_bp']
        line_tax = H.round0(raw / 10000)
        subtotal += line['unit_price_cents'] * line['qty']
        tax += line_tax
        new_lines.append({
            'sample_id': line['sample_id'],
            'unit_price_cents': line['unit_price_cents'],
            'qty': line['qty'],
            'tax_rate_bp': line['tax_rate_bp'],
            'line_tax_cents': line_tax,
        })
    po = H.new_common({
        'id': new_id(),
        'program_id': prog['id'],
        'buyer_alias': data['buyer_alias'],
        'retailer_name': data['retailer_name'],
        'receipt_doc_ref': data['receipt_doc_ref'],
        'lines': new_lines,
        'subtotal_cents': subtotal,
        'shipping_cents': data['shipping_cents'],
        'tax_cents': tax,
        'total_cents': subtotal + data['shipping_cents'] + tax,
        'placed_by_user_id': None,
        'verified_by_user_id': None,
        'placed_at': None,
        'status': 'DRAFT',
    })
    db['purchase_orders'][po['id']] = po
    return ok(po, 201)


@app.route('/purchase-orders', methods=['GET'])
def list_pos():
    uid, role = auth_headers()
    require_role(role, ['PurchasingAgent', 'ComplianceOfficer', 'LabManager'])
    limit, offset = parse_pagination(request.args)
    items = sorted(db['purchase_orders'].values(), key=lambda r: r['created_at'])
    pid = request.args.get('program_id')
    if pid:
        items = [p for p in items if p['program_id'] == pid]
    st = request.args.get('status')
    if st:
        items = [p for p in items if p['status'] == st]
    page, pag = list_page(items, limit, offset)
    return ok(page, 200, pag)


@app.route('/purchase-orders/<poid>', methods=['GET'])
def get_po(poid):
    uid, role = auth_headers()
    require_role(role, ['PurchasingAgent', 'ComplianceOfficer', 'LabManager'])
    return ok(get_or_404('purchase_orders', poid))


@app.route('/purchase-orders/<poid>/transitions', methods=['POST'])
def po_transition(poid):
    uid, role = auth_headers()
    require_role(role, ['PurchasingAgent', 'ComplianceOfficer'])
    po = get_or_404('purchase_orders', poid)
    data = body()
    action = data.get('action')
    valid = {'place', 'receive', 'verify', 'cancel'}
    if action not in valid:
        err('ERR_INVALID_STATE', f'Unknown action: {action}', 409)
    if action == 'verify':
        require_role(role, ['ComplianceOfficer'])
    else:
        require_role(role, ['PurchasingAgent'])
    prog = db['test_programs'][po['program_id']]

    if action == 'place':
        if po['status'] != 'DRAFT':
            err('ERR_INVALID_STATE', 'place requires DRAFT', 409)
        if prog['status'] != 'SAMPLE_SOURCING':
            err('ERR_INVALID_STATE', 'program must be SAMPLE_SOURCING', 409)
        # sourcing integrity re-check
        if H.is_manufacturer_direct(po['retailer_name']) or H.is_manufacturer_name(po['buyer_alias']):
            err('ERR_SOURCING_INTEGRITY', 'manufacturer-direct sourcing detected', 422)
        if po['total_cents'] > prog['budget_cents'] - prog['committed_cents']:
            err('ERR_BUDGET_EXCEEDED', 'PO total exceeds remaining budget', 422)
        po['placed_at'] = format_dt(get_clock())
        po['placed_by_user_id'] = uid
        po['status'] = 'PLACED'
        prog['committed_cents'] += po['total_cents']
        H.bump(prog)
        H.bump(po)
    elif action == 'receive':
        if po['status'] != 'PLACED':
            err('ERR_INVALID_STATE', 'receive requires PLACED', 409)
        po['status'] = 'RECEIVED'
        H.bump(po)
        for line in po['lines']:
            s = db['test_samples'].get(line['sample_id'])
            if s:
                H.recompute_sample_sourcing(s)
                H.bump(s)
    elif action == 'verify':
        if po['status'] != 'RECEIVED':
            err('ERR_INVALID_STATE', 'verify requires RECEIVED', 409)
        if H.is_manufacturer_direct(po['retailer_name']) or H.is_manufacturer_name(po['buyer_alias']):
            err('ERR_SOURCING_INTEGRITY', 'manufacturer-direct sourcing detected', 422)
        if not po['receipt_doc_ref']:
            err('ERR_REFERENTIAL_INTEGRITY', 'receipt_doc_ref must be non-empty for verify', 422)
        if uid == po['placed_by_user_id']:
            err('ERR_SOD_VIOLATION', 'verifier must differ from placer', 422)
        po['verified_by_user_id'] = uid
        po['status'] = 'VERIFIED'
        H.bump(po)
    elif action == 'cancel':
        if po['status'] not in ('DRAFT', 'PLACED'):
            err('ERR_INVALID_STATE', 'cancel requires DRAFT or PLACED', 409)
        if po['status'] == 'PLACED':
            prog['committed_cents'] -= po['total_cents']
            H.bump(prog)
        po['status'] = 'CANCELLED'
        H.bump(po)
    return ok(po)


# ---------------------------------------------------------------- survey waves

@app.route('/survey-waves', methods=['POST'])
def create_wave():
    uid, role = auth_headers()
    require_role(role, ['SurveyDirector'])
    data = body()
    require_fields(data, ['category_id', 'field_start', 'field_end', 'min_responses'])
    cat = db['product_categories'].get(data['category_id'])
    if cat is None:
        err('ERR_REFERENTIAL_INTEGRITY', 'category_id must reference an existing category', 422)
    fs = parse_dt(data['field_start'])
    fe = parse_dt(data['field_end'])
    if fs is None or fe is None:
        err('ERR_INVALID_REQUEST', 'field_start/field_end must be ISO8601 timestamps', 400)
    if fe <= fs:
        err('ERR_TEMPORAL_WINDOW', 'field_end must be strictly after field_start', 422)
    if not is_int(data['min_responses']) or data['min_responses'] < 1:
        err('ERR_INVALID_REQUEST', 'min_responses must be an integer >= 1', 400)
    wave = H.new_common({
        'id': new_id(),
        'category_id': data['category_id'],
        'field_start': format_dt(fs),
        'field_end': format_dt(fe),
        'min_responses': data['min_responses'],
        'responses': [],
        'response_count': 0,
        'threshold_met': False,
        'status': 'OPEN',
    })
    db['survey_waves'][wave['id']] = wave
    return ok(wave, 201)


@app.route('/survey-waves', methods=['GET'])
def list_waves():
    uid, role = auth_headers()
    require_role(role, ['SurveyDirector', 'LabManager', 'ContentEditor', 'EditorialDirector'])
    limit, offset = parse_pagination(request.args)
    items = sorted(db['survey_waves'].values(), key=lambda r: r['created_at'])
    cid = request.args.get('category_id')
    if cid:
        items = [w for w in items if w['category_id'] == cid]
    st = request.args.get('status')
    if st:
        items = [w for w in items if w['status'] == st]
    page, pag = list_page(items, limit, offset)
    return ok(page, 200, pag)


@app.route('/survey-waves/<wid>', methods=['GET'])
def get_wave(wid):
    uid, role = auth_headers()
    require_role(role, ['SurveyDirector', 'LabManager', 'ContentEditor', 'EditorialDirector'])
    return ok(get_or_404('survey_waves', wid))


def _recompute_wave(wave):
    wave['response_count'] = sum(1 for r in wave['responses'] if r['status'] == 'COUNTED')
    wave['threshold_met'] = wave['response_count'] >= wave['min_responses']


@app.route('/survey-waves/<wid>/transitions', methods=['POST'])
def wave_transition(wid):
    uid, role = auth_headers()
    require_role(role, ['SurveyDirector', 'Member'])
    wave = get_or_404('survey_waves', wid)
    data = body()
    action = data.get('action')
    valid = {'submit_response', 'exclude_response', 'close', 'qualify', 'disqualify'}
    if action not in valid:
        err('ERR_INVALID_STATE', f'Unknown action: {action}', 409)
    if action == 'submit_response':
        require_role(role, ['Member'])
    else:
        require_role(role, ['SurveyDirector'])
    clock = get_clock()

    if action == 'submit_response':
        if wave['status'] != 'OPEN':
            err('ERR_INVALID_STATE', 'submit_response requires OPEN', 409)
        for f in ('member_id', 'model_label', 'reliability_score', 'satisfaction_score'):
            if f not in data or data[f] is None:
                err('ERR_INVALID_REQUEST', f'Missing required field: {f}', 400)
        fs = parse_dt(wave['field_start'])
        fe = parse_dt(wave['field_end'])
        if clock < fs or clock > fe:
            err('ERR_TEMPORAL_WINDOW', 'outside survey window', 422)
        if data['member_id'] != uid:
            err('ERR_MEMBERSHIP_INACTIVE', 'member_id must equal acting X-User-ID', 403)
        member = db['members'].get(data['member_id'])
        if member is None or member['status'] != 'ACTIVE':
            err('ERR_MEMBERSHIP_INACTIVE', 'member must be ACTIVE', 403)
        if any(r['member_id'] == data['member_id'] and r['status'] == 'COUNTED' for r in wave['responses']):
            err('ERR_SAMPLE_SIZE_NOT_MET', 'member already has a COUNTED response in this wave', 422)
        if not is_num(data['reliability_score']) or not (0 <= data['reliability_score'] <= 100):
            err('ERR_INVALID_REQUEST', 'reliability_score must be in [0,100]', 400)
        if not is_num(data['satisfaction_score']) or not (0 <= data['satisfaction_score'] <= 100):
            err('ERR_INVALID_REQUEST', 'satisfaction_score must be in [0,100]', 400)
        resp = {
            'response_index': len(wave['responses']) + 1,
            'member_id': data['member_id'],
            'model_label': data['model_label'],
            'reliability_score': data['reliability_score'],
            'satisfaction_score': data['satisfaction_score'],
            'submitted_at': format_dt(clock),
            'submitted_by_user_id': uid,
            'status': 'COUNTED',
        }
        wave['responses'].append(resp)
        _recompute_wave(wave)
        H.bump(wave)
    elif action == 'exclude_response':
        if wave['status'] not in ('OPEN', 'CLOSED'):
            err('ERR_INVALID_STATE', 'exclude_response requires OPEN or CLOSED', 409)
        if 'response_index' not in data or data['response_index'] is None:
            err('ERR_INVALID_REQUEST', 'response_index is required', 400)
        target = None
        for r in wave['responses']:
            if r['response_index'] == data['response_index']:
                target = r
                break
        if target is None or target['status'] == 'EXCLUDED':
            err('ERR_SAMPLE_SIZE_NOT_MET', 'response_index does not exist', 422)
        target['status'] = 'EXCLUDED'
        _recompute_wave(wave)
        H.bump(wave)
    elif action == 'close':
        if wave['status'] != 'OPEN':
            err('ERR_INVALID_STATE', 'close requires OPEN', 409)
        if clock < parse_dt(wave['field_end']):
            err('ERR_TEMPORAL_WINDOW', 'clock must be >= field_end to close', 422)
        wave['status'] = 'CLOSED'
        H.bump(wave)
    elif action == 'qualify':
        if wave['status'] != 'CLOSED':
            err('ERR_INVALID_STATE', 'qualify requires CLOSED', 409)
        if not wave['threshold_met']:
            err('ERR_SAMPLE_SIZE_NOT_MET', 'threshold not met', 422)
        if 'expected_wave_version' not in data:
            err('ERR_INVALID_REQUEST', 'expected_wave_version is required for qualify', 400)
        if data['expected_wave_version'] != wave['version']:
            err('ERR_STALE_VERSION', 'wave version mismatch', 412)
        wave['status'] = 'QUALIFIED'
        H.bump(wave)
    elif action == 'disqualify':
        if wave['status'] != 'CLOSED':
            err('ERR_INVALID_STATE', 'disqualify requires CLOSED', 409)
        if wave['threshold_met']:
            err('ERR_INVALID_STATE', 'threshold met; cannot disqualify', 409)
        wave['status'] = 'DISQUALIFIED'
        H.bump(wave)
    return ok(wave)


# ---------------------------------------------------------------- rating publications

def latest_qualified_wave(cat_id):
    waves = [w for w in db['survey_waves'].values()
             if w['category_id'] == cat_id and w['status'] == 'QUALIFIED']
    if not waves:
        return None
    return sorted(waves, key=lambda w: (parse_dt(w['field_end']).timestamp(), -parse_dt(w['created_at']).timestamp()),
                  reverse=True)[0]


def _build_rated_model(pub, sample):
    program = db['test_programs'][pub['program_id']]
    cat = db['product_categories'][program['category_id']]
    # protocol weights
    prot = None
    if pub.get('protocol_id_snapshot'):
        prot = db['lab_protocols'].get(pub['protocol_id_snapshot'])
    if prot is None:
        prot = H.active_protocol_of_category(cat['id'])
    p = prot['perf_weight_pct'] if prot else 0
    r = prot['reliability_weight_pct'] if prot else 0
    # survey score from pinned-or-available QUALIFIED wave
    wave = None
    if pub.get('survey_wave_id_snapshot'):
        wave = db['survey_waves'].get(pub['survey_wave_id_snapshot'])
    if wave is None:
        wave = latest_qualified_wave(cat['id'])
    survey_score = H.compute_survey_score(sample, wave)
    lab = sample['lab_score']
    if survey_score is not None:
        from decimal import Decimal, ROUND_HALF_UP
        overall = (Decimal(str(lab)) * Decimal(p) / 100
                   + Decimal(str(survey_score)) * Decimal(r + (100 - p - r)) / 100)
        overall = float(overall.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))
    else:
        overall = lab
    price = H.median_price_cents(sample)
    designation = H.designation_for(program, sample, overall, price)
    return {
        'sample_id': sample['id'],
        'lab_score': lab,
        'survey_score': survey_score,
        'overall_score': overall,
        'designation': designation,
        'price_cents': price,
    }


@app.route('/rating-publications', methods=['POST'])
def create_pub():
    uid, role = auth_headers()
    require_role(role, ['ContentEditor'])
    data = body()
    require_fields(data, ['program_id', 'embargo_until'])
    prog = db['test_programs'].get(data['program_id'])
    if prog is None:
        err('ERR_REFERENTIAL_INTEGRITY', 'program_id must reference an existing program', 422)
    emb = parse_dt(data['embargo_until'])
    if emb is None:
        err('ERR_INVALID_REQUEST', 'embargo_until must be a valid ISO8601 timestamp', 400)
    pub = H.new_common({
        'id': new_id(),
        'program_id': prog['id'],
        'embargo_until': format_dt(emb),
        'version_note': data.get('version_note', '') or '',
        'rated_models': [],
        'model_count': 0,
        'protocol_id_snapshot': None,
        'survey_wave_id_snapshot': None,
        'manufacturer_responses': [],
        'manufacturer_response_text': None,
        'published_at': None,
        'status': 'DRAFT',
    })
    db['rating_publications'][pub['id']] = pub
    return ok(pub, 201)


def _marketing_check():
    if request.headers.get('X-Marketing-Use', '').lower() == 'true':
        err('ERR_MARKETING_USE_FORBIDDEN', 'ratings may not be used in marketing', 422)


def _member_visible(pub, uid):
    """Member reads: only PUBLISHED, embargoed check, membership ACTIVE."""
    member = db['members'].get(uid)
    if member is None or member['status'] != 'ACTIVE':
        err('ERR_MEMBERSHIP_INACTIVE', 'member must be ACTIVE', 403)
    if pub['status'] != 'PUBLISHED':
        err('ERR_NOT_FOUND', 'publication not visible', 404)
    if get_clock() < parse_dt(pub['embargo_until']):
        err('ERR_EMBARGOED', 'publication under embargo', 422)


@app.route('/rating-publications', methods=['GET'])
def list_pubs():
    uid, role = auth_headers()
    require_role(role, ['ContentEditor', 'EditorialDirector', 'LabManager', 'SafetyOfficer', 'Member'])
    _marketing_check()
    limit, offset = parse_pagination(request.args)
    items = sorted(db['rating_publications'].values(), key=lambda r: r['created_at'])
    pid = request.args.get('program_id')
    if pid:
        items = [p for p in items if p['program_id'] == pid]
    st = request.args.get('status')
    if st:
        items = [p for p in items if p['status'] == st]
    if role == 'Member':
        member = db['members'].get(uid)
        if member is None or member['status'] != 'ACTIVE':
            err('ERR_MEMBERSHIP_INACTIVE', 'member must be ACTIVE', 403)
        clock = get_clock()
        items = [p for p in items if p['status'] == 'PUBLISHED' and clock >= parse_dt(p['embargo_until'])]
    page, pag = list_page(items, limit, offset)
    return ok(page, 200, pag)


@app.route('/rating-publications/<pid>', methods=['GET'])
def get_pub(pid):
    uid, role = auth_headers()
    require_role(role, ['ContentEditor', 'EditorialDirector', 'LabManager', 'SafetyOfficer', 'Member'])
    _marketing_check()
    pub = get_or_404('rating_publications', pid)
    if role == 'Member':
        _member_visible(pub, uid)
    return ok(pub)


def _revert_program_from_published(prog):
    if prog['status'] == 'PUBLISHED':
        prog['status'] = 'READY_FOR_PUBLICATION'
        H.bump(prog)


def _recompute_category_after_withdraw(prog):
    cat = db['product_categories'][prog['category_id']]
    H.recompute_category_last_published(cat)
    cat['selection_score'] = H.compute_selection_score(cat)
    H.bump(cat)


def _withdraw_pub(pub):
    prog = db['test_programs'][pub['program_id']]
    was_published = pub['status'] == 'PUBLISHED'
    pub['status'] = 'WITHDRAWN'
    H.bump(pub)
    if was_published:
        _revert_program_from_published(prog)
        _recompute_category_after_withdraw(prog)


@app.route('/rating-publications/<pid>/transitions', methods=['POST'])
def pub_transition(pid):
    uid, role = auth_headers()
    require_role(role, ['ContentEditor', 'EditorialDirector'])
    pub = get_or_404('rating_publications', pid)
    data = body()
    action = data.get('action')
    valid = {'add_rated_model', 'submit', 'approve', 'request_revision', 'publish',
             'withdraw', 'log_manufacturer_response', 'accept_manufacturer_response',
             'reject_manufacturer_response'}
    if action not in valid:
        err('ERR_INVALID_STATE', f'Unknown action: {action}', 409)
    if action in ('add_rated_model', 'submit', 'log_manufacturer_response',
                  'accept_manufacturer_response', 'reject_manufacturer_response'):
        require_role(role, ['ContentEditor'])
    else:
        require_role(role, ['EditorialDirector'])
    prog = db['test_programs'][pub['program_id']]
    cat = db['product_categories'][prog['category_id']]
    clock = get_clock()

    if action == 'add_rated_model':
        if pub['status'] != 'DRAFT':
            err('ERR_INVALID_STATE', 'add_rated_model requires DRAFT', 409)
        require_fields(data, ['sample_id'])
        sample = db['test_samples'].get(data['sample_id'])
        if sample is None or sample['program_id'] != pub['program_id'] or sample['status'] != 'SCORED':
            err('ERR_REFERENTIAL_INTEGRITY', 'sample must be SCORED in the publication program', 422)
        entry = _build_rated_model(pub, sample)
        pub['rated_models'].append(entry)
        pub['model_count'] = len(pub['rated_models'])
        H.bump(pub)
    elif action == 'submit':
        if pub['status'] not in ('DRAFT', 'REVISION_REQUESTED'):
            err('ERR_INVALID_STATE', 'submit requires DRAFT or REVISION_REQUESTED', 409)
        if prog['status'] != 'READY_FOR_PUBLICATION':
            err('ERR_INVALID_STATE', 'program must be READY_FOR_PUBLICATION', 409)
        if pub['model_count'] < 1:
            err('ERR_INVALID_STATE', 'model_count must be >= 1', 409)
        pub['status'] = 'UNDER_REVIEW'
        H.bump(pub)
    elif action == 'approve':
        if pub['status'] != 'UNDER_REVIEW':
            err('ERR_INVALID_STATE', 'approve requires UNDER_REVIEW', 409)
        for f in H.findings_of_program(prog['id']):
            if f['status'] in ('OPEN', 'ESCALATED') and f['escalation_tier'] == 3:
                err('ERR_SAFETY_GATE', 'open tier-3 finding blocks approval', 422)
        if 'expected_program_version' not in data:
            err('ERR_INVALID_REQUEST', 'expected_program_version is required for approve', 400)
        if data['expected_program_version'] != prog['version']:
            err('ERR_STALE_VERSION', 'program version mismatch', 412)
        prot = H.active_protocol_of_category(cat['id'])
        pub['protocol_id_snapshot'] = prot['id'] if prot else None
        wave = latest_qualified_wave(cat['id'])
        pub['survey_wave_id_snapshot'] = wave['id'] if wave else None
        pub['status'] = 'APPROVED'
        H.bump(prog)
        H.bump(pub)
    elif action == 'request_revision':
        if pub['status'] != 'UNDER_REVIEW':
            err('ERR_INVALID_STATE', 'request_revision requires UNDER_REVIEW', 409)
        pub['status'] = 'REVISION_REQUESTED'
        H.bump(pub)
    elif action == 'publish':
        if pub['status'] != 'APPROVED':
            err('ERR_INVALID_STATE', 'publish requires APPROVED', 409)
        if clock < parse_dt(pub['embargo_until']):
            err('ERR_EMBARGOED', 'publication under embargo', 422)
        for other in H.pubs_of_program(prog['id']):
            if other['id'] != pid and other['status'] == 'PUBLISHED':
                err('ERR_DUPLICATE', 'another publication of this program is already PUBLISHED', 422)
        for f in H.findings_of_program(prog['id']):
            if f['status'] in ('OPEN', 'ESCALATED') and f['escalation_tier'] == 3:
                err('ERR_SAFETY_GATE', 'open tier-3 finding blocks publish', 422)
        if prog['status'] != 'READY_FOR_PUBLICATION':
            err('ERR_INVALID_STATE', 'program must be READY_FOR_PUBLICATION', 409)
        pub['published_at'] = format_dt(clock)
        pub['status'] = 'PUBLISHED'
        prog['status'] = 'PUBLISHED'
        H.bump(prog)
        cat['last_published_at'] = pub['published_at']
        cat['selection_score'] = H.compute_selection_score(cat)
        H.bump(cat)
        H.bump(pub)
    elif action == 'withdraw':
        if pub['status'] not in ('DRAFT', 'UNDER_REVIEW', 'REVISION_REQUESTED', 'PUBLISHED'):
            err('ERR_INVALID_STATE', 'withdraw requires DRAFT/UNDER_REVIEW/REVISION_REQUESTED/PUBLISHED', 409)
        if pub['status'] == 'PUBLISHED':
            has_t3 = any(f['status'] == 'ESCALATED' and f['escalation_tier'] == 3
                         for f in H.findings_of_program(prog['id']))
            if not has_t3 and not pub.get('version_note'):
                err('ERR_INVALID_STATE', 'manual withdrawal from PUBLISHED requires an ESCALATED tier-3 finding or a non-empty version_note', 409)
        _withdraw_pub(pub)
    elif action == 'log_manufacturer_response':
        require_fields(data, ['manufacturer_name', 'body_text'])
        entry = {
            'response_index': len(pub['manufacturer_responses']) + 1,
            'manufacturer_name': data['manufacturer_name'],
            'body_text': data['body_text'],
            'received_at': format_dt(clock),
            'status': 'RECEIVED',
        }
        pub['manufacturer_responses'].append(entry)
        H.bump(pub)
    elif action in ('accept_manufacturer_response', 'reject_manufacturer_response'):
        require_fields(data, ['response_index'])
        target = None
        for r in pub['manufacturer_responses']:
            if r['response_index'] == data['response_index']:
                target = r
                break
        if target is None:
            err('ERR_INVALID_STATE', 'response_index does not exist', 409)
        target['status'] = 'ACCEPTED' if action == 'accept_manufacturer_response' else 'REJECTED'
        accepted = [r for r in pub['manufacturer_responses'] if r['status'] == 'ACCEPTED']
        pub['manufacturer_response_text'] = accepted[-1]['body_text'] if accepted else None
        H.bump(pub)
    return ok(pub)


# ---------------------------------------------------------------- safety findings

@app.route('/safety-findings', methods=['POST'])
def create_finding():
    uid, role = auth_headers()
    require_role(role, ['SafetyOfficer', 'LabTechnician'])
    data = body()
    require_fields(data, ['program_id', 'sample_id', 'severity', 'description_text'])
    prog = db['test_programs'].get(data['program_id'])
    if prog is None:
        err('ERR_REFERENTIAL_INTEGRITY', 'program_id must reference an existing program', 422)
    sample = db['test_samples'].get(data['sample_id'])
    if sample is None or sample['program_id'] != prog['id']:
        err('ERR_REFERENTIAL_INTEGRITY', 'sample must belong to program', 422)
    if data['severity'] not in ('CRITICAL', 'MAJOR', 'MINOR'):
        err('ERR_INVALID_REQUEST', 'severity must be CRITICAL, MAJOR, or MINOR', 400)
    if not isinstance(data['description_text'], str):
        err('ERR_INVALID_REQUEST', 'description_text must be a string', 400)
    hazard = data.get('hazard_flag', False)
    if not isinstance(hazard, bool):
        err('ERR_INVALID_REQUEST', 'hazard_flag must be boolean', 400)
    f = H.new_common({
        'id': new_id(),
        'program_id': prog['id'],
        'sample_id': sample['id'],
        'severity': data['severity'],
        'description_text': data['description_text'],
        'hazard_flag': hazard,
        'recalled_model_count': 0,
        'escalation_tier': 0,
        'status': 'OPEN',
    })
    f['recalled_model_count'] = H.compute_recalled_model_count(f)
    f['escalation_tier'] = H.compute_escalation_tier(f)
    db['safety_findings'][f['id']] = f
    return ok(f, 201)


@app.route('/safety-findings', methods=['GET'])
def list_findings():
    uid, role = auth_headers()
    require_role(role, ['SafetyOfficer', 'EditorialDirector', 'LabManager', 'ContentEditor'])
    limit, offset = parse_pagination(request.args)
    items = sorted(db['safety_findings'].values(), key=lambda r: r['created_at'])
    pid = request.args.get('program_id')
    if pid:
        items = [f for f in items if f['program_id'] == pid]
    sid = request.args.get('sample_id')
    if sid:
        items = [f for f in items if f['sample_id'] == sid]
    st = request.args.get('status')
    if st:
        items = [f for f in items if f['status'] == st]
    sev = request.args.get('severity')
    if sev:
        items = [f for f in items if f['severity'] == sev]
    page, pag = list_page(items, limit, offset)
    return ok(page, 200, pag)


@app.route('/safety-findings/<fid>', methods=['GET'])
def get_finding(fid):
    uid, role = auth_headers()
    require_role(role, ['SafetyOfficer', 'EditorialDirector', 'LabManager', 'ContentEditor'])
    return ok(get_or_404('safety_findings', fid))


@app.route('/safety-findings/<fid>/transitions', methods=['POST'])
def finding_transition(fid):
    uid, role = auth_headers()
    require_role(role, ['SafetyOfficer'])
    f = get_or_404('safety_findings', fid)
    data = body()
    action = data.get('action')
    valid = {'escalate', 'resolve', 'close'}
    if action not in valid:
        err('ERR_INVALID_STATE', f'Unknown action: {action}', 409)
    prog = db['test_programs'][f['program_id']]

    if action == 'escalate':
        if f['status'] != 'OPEN':
            err('ERR_INVALID_STATE', 'escalate requires OPEN', 409)
        f['recalled_model_count'] = H.compute_recalled_model_count(f)
        f['escalation_tier'] = H.compute_escalation_tier(f)
        if f['escalation_tier'] < 1:
            err('ERR_INVALID_STATE', 'tier-0 finding cannot be escalated', 409)
        f['status'] = 'ESCALATED'
        H.bump(f)
        sample = db['test_samples'][f['sample_id']]
        if f['escalation_tier'] >= 2:
            # designation flip cascade
            for pub in H.pubs_of_program(prog['id']):
                if pub['status'] == 'WITHDRAWN':
                    continue
                touched = False
                for entry in pub['rated_models']:
                    es = db['test_samples'][entry['sample_id']]
                    if es['model_label'] == sample['model_label']:
                        entry['designation'] = 'NOT_RECOMMENDED'
                        touched = True
                if touched:
                    H.bump(pub)
        if f['escalation_tier'] == 3:
            # publication withdrawal cascade
            for pub in H.pubs_of_program(prog['id']):
                if pub['status'] == 'PUBLISHED':
                    _withdraw_pub(pub)
    elif action == 'resolve':
        if f['status'] != 'ESCALATED':
            err('ERR_INVALID_STATE', 'resolve requires ESCALATED', 409)
        if f['escalation_tier'] > 1:
            has_accepted = any(
                r['status'] == 'ACCEPTED'
                for pub in H.pubs_of_program(prog['id'])
                for r in pub['manufacturer_responses'])
            if not has_accepted:
                err('ERR_INVALID_STATE', 'tier>1 resolve requires an ACCEPTED manufacturer response', 409)
        f['status'] = 'RESOLVED'
        H.bump(f)
    elif action == 'close':
        if f['status'] == 'OPEN':
            if f['escalation_tier'] != 0:
                err('ERR_INVALID_STATE', 'close from OPEN requires tier 0', 409)
            f['status'] = 'CLOSED'
            H.bump(f)
        elif f['status'] == 'RESOLVED':
            f['status'] = 'CLOSED'
            H.bump(f)
        else:
            err('ERR_INVALID_STATE', 'close requires OPEN or RESOLVED', 409)
    return ok(f)


# ---------------------------------------------------------------- members

@app.route('/members', methods=['POST'])
def create_member():
    uid, role = auth_headers()
    require_role(role, ['Member'])
    data = body()
    require_fields(data, ['email', 'full_name'])
    email = data['email']
    if not isinstance(email, str) or not email:
        err('ERR_INVALID_REQUEST', 'email must be a non-empty string', 400)
    if not isinstance(data['full_name'], str) or not data['full_name']:
        err('ERR_INVALID_REQUEST', 'full_name must be a non-empty string', 400)
    email = email.lower()
    if any(m['email'] == email for m in db['members'].values()):
        err('ERR_DUPLICATE', 'email must be unique', 422)
    m = H.new_common({
        'id': new_id(),
        'email': email,
        'full_name': data['full_name'],
        'subscriptions': [],
        'status': 'ACTIVE',
    })
    db['members'][m['id']] = m
    return ok(m, 201)


@app.route('/members/<mid>', methods=['GET'])
def get_member(mid):
    uid, role = auth_headers()
    require_role(role, ['Member', 'LabManager'])
    member = get_or_404('members', mid)
    if role == 'Member' and uid != mid:
        err('ERR_MEMBERSHIP_INACTIVE', 'members may only read their own record', 403)
    return ok(member)


@app.route('/members/<mid>/transitions', methods=['POST'])
def member_transition(mid):
    uid, role = auth_headers()
    require_role(role, ['Member'])
    member = get_or_404('members', mid)
    if uid != mid:
        err('ERR_MEMBERSHIP_INACTIVE', 'member actions require the acting member', 403)
    if member['status'] != 'ACTIVE':
        err('ERR_MEMBERSHIP_INACTIVE', 'member must be ACTIVE', 403)
    data = body()
    action = data.get('action')
    valid = {'add_subscription', 'renew', 'cancel'}
    if action not in valid:
        err('ERR_INVALID_STATE', f'Unknown action: {action}', 409)

    if action == 'add_subscription':
        require_fields(data, ['plan_tier', 'term_start', 'term_end'])
        if data['plan_tier'] not in ('DIGITAL', 'ALL_ACCESS'):
            err('ERR_INVALID_REQUEST', 'plan_tier must be DIGITAL or ALL_ACCESS', 400)
        ts = parse_dt(data['term_start'])
        te = parse_dt(data['term_end'])
        if ts is None or te is None:
            err('ERR_INVALID_REQUEST', 'term_start/term_end must be ISO8601 timestamps', 400)
        if te <= ts:
            err('ERR_TEMPORAL_WINDOW', 'term_end must be strictly after term_start', 422)
        if any(s['status'] in ('ACTIVE', 'GRACE') for s in member['subscriptions']):
            err('ERR_DUPLICATE', 'at most one ACTIVE or GRACE subscription per member', 422)
        from datetime import timedelta
        sub = {
            'subscription_id': str(len(member['subscriptions']) + 1),
            'plan_tier': data['plan_tier'],
            'term_start': format_dt(ts),
            'term_end': format_dt(te),
            'grace_until': format_dt(te + timedelta(days=14)),
            'status': 'ACTIVE',
            'renewal_count': 0,
        }
        member['subscriptions'].append(sub)
        H.bump(member)
    elif action == 'renew':
        require_fields(data, ['subscription_id', 'term_end'])
        sub = None
        for s in member['subscriptions']:
            if s['subscription_id'] == data['subscription_id']:
                sub = s
                break
        if sub is None or sub['status'] not in ('ACTIVE', 'GRACE'):
            err('ERR_REFERENTIAL_INTEGRITY', 'subscription_id must reference an ACTIVE or GRACE subscription', 422)
        te = parse_dt(data['term_end'])
        if te is None:
            err('ERR_INVALID_REQUEST', 'term_end must be a valid ISO8601 timestamp', 400)
        ts = parse_dt(sub['term_start'])
        if te <= ts:
            err('ERR_TEMPORAL_WINDOW', 'term_end must be strictly after term_start', 422)
        from datetime import timedelta
        was_grace = sub['status'] == 'GRACE'
        sub['term_end'] = format_dt(te)
        sub['grace_until'] = format_dt(te + timedelta(days=14))
        sub['status'] = 'ACTIVE'
        sub['renewal_count'] += 1
        if was_grace and member['status'] == 'LAPSED':
            member['status'] = 'ACTIVE'
        H.bump(member)
    elif action == 'cancel':
        require_fields(data, ['subscription_id'])
        sub = None
        for s in member['subscriptions']:
            if s['subscription_id'] == data['subscription_id']:
                sub = s
                break
        if sub is None or sub['status'] not in ('ACTIVE', 'GRACE'):
            err('ERR_REFERENTIAL_INTEGRITY', 'subscription_id must reference an ACTIVE or GRACE subscription', 422)
        sub['status'] = 'CANCELLED'
        member['status'] = 'CANCELLED'
        H.bump(member)
    return ok(member)


if __name__ == '__main__':
    port = int(os.environ.get('PORT', '10000'))
    app.run(host='0.0.0.0', port=port)
