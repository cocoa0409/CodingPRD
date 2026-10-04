"""Conversion programs, line-item evaluations, review decisions (PRD 3.3)."""
import uuid

from flask import Blueprint, request

import db
import helpers as H
import services
from errors import (
    ApiError, ERR_AGREEMENT_NOT_ACTIVE, ERR_INVALID_STATE,
    ERR_ITEMS_NOT_TRAINED, ERR_PROGRAM_ITEMS_FAILED, ERR_SAME_PRODUCT_CONVERSION,
    bad_request, not_found,
)
from routes_products import CATEGORIES

bp = Blueprint('conversion', __name__)

READ_ROLES = ('SupplyChainAdmin', 'ConversionManager', 'Clinician')


@bp.post('/supply/conversion-programs')
def create_program():
    _, role = H.auth()
    H.require_roles(role, ('ConversionManager',))
    b = H.get_body()
    facility_id = H.v_str(H.required(b, 'facility_id'), 'facility_id')
    name = H.v_str(H.required(b, 'name'), 'name')
    target_categories = H.v_arr(H.required(b, 'target_categories'), 'target_categories', min_len=1)
    for c in target_categories:
        H.v_enum(c, 'target_categories', CATEGORIES)
    line_items = H.v_arr(H.required(b, 'line_items'), 'line_items', min_len=1, max_len=20)
    # Priority 3: facility and all referenced products must exist
    if facility_id not in db.STORES['facilities']:
        not_found('facility')
    parsed = []
    for i, item in enumerate(line_items):
        if not isinstance(item, dict):
            bad_request('line_items[{}] must be an object'.format(i))
        inc = H.v_str(H.required(item, 'incumbent_product_id'), 'incumbent_product_id')
        rep = H.v_str(H.required(item, 'replacement_product_id'), 'replacement_product_id')
        if inc not in db.STORES['products']:
            not_found('incumbent product')
        if rep not in db.STORES['products']:
            not_found('replacement product')
        parsed.append((inc, rep))
    # Priority 8.7: incumbent != replacement; replacement must be ACTIVE
    for inc, rep in parsed:
        if inc == rep:
            raise ApiError(ERR_SAME_PRODUCT_CONVERSION, 422,
                           'incumbent_product_id must differ from replacement_product_id')
        if db.STORES['products'][rep]['availability'] != 'ACTIVE':
            raise ApiError(ERR_SAME_PRODUCT_CONVERSION, 422,
                           'replacement product is not ACTIVE')
    prog = H.base_resource()
    prog.update({
        'facility_id': facility_id,
        'name': name,
        'target_categories': list(target_categories),
        'line_items': [
            {
                'line_id': str(uuid.uuid4()),
                'incumbent_product_id': inc,
                'replacement_product_id': rep,
                'evaluation_status': 'PENDING',
                'training_completed': False,
                'evaluated_by': None,
                'evaluation_notes': None,
            }
            for inc, rep in parsed
        ],
        'status': 'IN_EVALUATION',
        'reviewed_by': None,
        'review_decision_at': None,
    })
    db.STORES['programs'][prog['id']] = prog
    return H.success(prog, 201)


@bp.get('/supply/conversion-programs')
def list_programs():
    _, role = H.auth()
    H.require_roles(role, READ_ROLES)
    items = list(db.STORES['programs'].values())
    f = request.args.get('facility_id')
    if f is not None:
        items = [p for p in items if p['facility_id'] == f]
    f = request.args.get('status')
    if f is not None:
        items = [p for p in items if p['status'] == f]
    items.sort(key=lambda e: e['created_at'])
    return H.list_response(items)


@bp.get('/supply/conversion-programs/<pid>')
def get_program(pid):
    _, role = H.auth()
    H.require_roles(role, READ_ROLES)
    prog = db.STORES['programs'].get(pid)
    if prog is None:
        not_found('conversion program')
    return H.success(prog, 200)


@bp.post('/supply/conversion-programs/<pid>/line-item-evaluations')
def line_item_evaluation(pid):
    uid, role = H.auth()
    H.require_roles(role, ('Clinician',))
    b = H.get_body()
    line_id = H.v_str(H.required(b, 'line_id'), 'line_id')
    outcome = H.v_enum(H.required(b, 'outcome'), 'outcome', ('PASSED', 'FAILED'))
    training_completed = H.v_bool(H.required(b, 'training_completed'), 'training_completed')
    notes = b.get('notes')
    if notes is not None:
        H.v_str(notes, 'notes')
    prog = db.STORES['programs'].get(pid)
    if prog is None:
        not_found('conversion program')
    item = None
    for li in prog['line_items']:
        if li['line_id'] == line_id:
            item = li
            break
    if item is None:
        not_found('line item')
    # Only PENDING or FAILED items may be evaluated; PASSED is immutable
    if item['evaluation_status'] not in ('PENDING', 'FAILED'):
        raise ApiError(ERR_INVALID_STATE, 409,
                       'Line item with evaluation_status PASSED is immutable')
    item['evaluation_status'] = outcome
    item['training_completed'] = training_completed
    item['evaluated_by'] = uid
    if notes is not None:
        item['evaluation_notes'] = notes
    # Bubble-up: zero PENDING remaining moves IN_EVALUATION -> IN_REVIEW
    if prog['status'] == 'IN_EVALUATION':
        if all(li['evaluation_status'] != 'PENDING' for li in prog['line_items']):
            prog['status'] = 'IN_REVIEW'
    services.touch(prog)
    return H.success(prog, 200)


@bp.post('/supply/conversion-programs/<pid>/review-decision')
def review_decision(pid):
    uid, role = H.auth()
    H.require_roles(role, ('ConversionManager',))
    b = H.get_body()
    decision = H.v_enum(H.required(b, 'decision'), 'decision', ('APPROVE', 'REDESIGN'))
    prog = db.STORES['programs'].get(pid)
    if prog is None:
        not_found('conversion program')
    if prog['status'] != 'IN_REVIEW':
        raise ApiError(ERR_INVALID_STATE, 409,
                       'Review decision requires status IN_REVIEW')
    if decision == 'APPROVE':
        # Priority 8.9: every line item PASSED
        if any(li['evaluation_status'] != 'PASSED' for li in prog['line_items']):
            raise ApiError(ERR_PROGRAM_ITEMS_FAILED, 409,
                           'A line item has evaluation_status != PASSED')
        # Priority 8.91: every line item trained
        if any(not li['training_completed'] for li in prog['line_items']):
            raise ApiError(ERR_ITEMS_NOT_TRAINED, 409,
                           'A line item has training_completed == false')
        # Priority 9.2: facility agreement exists, ACTIVE, clock <= end_date
        agr = services.facility_agreement(prog['facility_id'])
        if agr is None or agr['status'] != 'ACTIVE':
            raise ApiError(ERR_AGREEMENT_NOT_ACTIVE, 409,
                           'Facility has no ACTIVE prime vendor agreement')
        prog['status'] = 'CONVERTED'
    else:  # REDESIGN loops back to IN_EVALUATION
        prog['status'] = 'IN_EVALUATION'
    prog['reviewed_by'] = uid
    prog['review_decision_at'] = db.clock_iso()
    services.touch(prog)
    return H.success(prog, 200)
