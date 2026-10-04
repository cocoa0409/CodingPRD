"""SubstitutionRequest endpoints: file, review loop, decide."""
from flask import Blueprint, request

from auth import require_roles
from calculations import voc_as_supplied
from errors import ApiError
from helpers import (body, get_or_404, invalid, new_entity, page_args,
                     paginate, pub, req, touch)
from response import ok, ok_list
from specifications import get_spec_or_404
from storage import store

bp = Blueprint('substitutions', __name__)

SUB_ROLES = ('PlatformAdmin', 'TechnicalServiceEngineer', 'ProjectEngineer',
             'OwnerRepresentative')


def get_nested_request(spec_id, request_id):
    r = store.substitution_requests.get(request_id)
    if r is None or r['specification_id'] != spec_id:
        raise ApiError('ERR_SUBSTITUTION_REQUEST_NOT_FOUND', 404,
                       'substitution request not found')
    return r


@bp.post('/coating/specifications/<specId>/substitution-requests')
@require_roles('OwnerRepresentative')
def create_substitution_request(specId):
    spec = get_spec_or_404(specId)
    if spec['status'] != 'ISSUED':
        raise ApiError('ERR_SPEC_NOT_ISSUED', 409,
                       'substitution requests require an ISSUED specification')
    p = body()
    proposed_id = req(p, 'proposed_coating_system_id', 'str')
    get_or_404(store.coating_systems, proposed_id,
               'ERR_COATING_SYSTEM_NOT_FOUND', 'coating system not found')
    rationale = req(p, 'rationale', 'str')
    max_rounds = p.get('max_review_rounds', 3)
    if not isinstance(max_rounds, int) or isinstance(max_rounds, bool):
        invalid('max_review_rounds must be an integer')
    if max_rounds < 1:
        invalid('max_review_rounds must be at least 1')
    e = new_entity()
    e.update({
        'specification_id': specId,
        'proposed_coating_system_id': proposed_id,
        'rationale': rationale,
        'review_round': 1,
        'max_review_rounds': max_rounds,
        'decision_reason': None,
        'status': 'SUBMITTED',
    })
    store.substitution_requests[e['id']] = e
    return ok(pub(e), 201)


@bp.get('/coating/specifications/<specId>/substitution-requests')
@require_roles(*SUB_ROLES)
def list_substitution_requests(specId):
    get_spec_or_404(specId)
    limit, offset = page_args()
    items = [r for r in store.substitution_requests.values()
             if r['specification_id'] == specId]
    status = request.args.get('status')
    if status is not None:
        items = [r for r in items if r['status'] == status]
    page, total = paginate(items, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.get('/coating/specifications/<specId>/substitution-requests/<rid>')
@require_roles(*SUB_ROLES)
def get_substitution_request(specId, rid):
    get_spec_or_404(specId)
    return ok(pub(get_nested_request(specId, rid)))


@bp.post('/coating/specifications/<specId>/substitution-requests/<rid>/start-review')
@require_roles('TechnicalServiceEngineer')
def start_review(specId, rid):
    spec = get_spec_or_404(specId)
    r = get_nested_request(specId, rid)
    if spec['status'] != 'ISSUED':
        raise ApiError('ERR_SPEC_NOT_ISSUED', 409, 'specification is not ISSUED')
    if r['status'] != 'SUBMITTED':
        raise ApiError('ERR_INVALID_STATE', 409, 'request is not SUBMITTED')
    r['status'] = 'UNDER_REVIEW'
    touch(r)
    return ok(pub(r))


@bp.post('/coating/specifications/<specId>/substitution-requests/<rid>/request-info')
@require_roles('TechnicalServiceEngineer')
def request_info(specId, rid):
    get_spec_or_404(specId)
    r = get_nested_request(specId, rid)
    if r['status'] != 'UNDER_REVIEW':
        raise ApiError('ERR_INVALID_STATE', 409, 'request is not UNDER_REVIEW')
    if r['review_round'] >= r['max_review_rounds']:
        raise ApiError('ERR_REVIEW_ROUND_EXHAUSTED', 422,
                       'review round limit reached; a final decision is required')
    r['status'] = 'MORE_INFO_REQUESTED'
    touch(r)
    return ok(pub(r))


@bp.post('/coating/specifications/<specId>/substitution-requests/<rid>/resubmit')
@require_roles('OwnerRepresentative')
def resubmit(specId, rid):
    get_spec_or_404(specId)
    r = get_nested_request(specId, rid)
    if r['status'] != 'MORE_INFO_REQUESTED':
        raise ApiError('ERR_INVALID_STATE', 409, 'request is not MORE_INFO_REQUESTED')
    p = body()
    r['rationale'] = req(p, 'rationale', 'str')
    r['status'] = 'SUBMITTED'
    r['review_round'] += 1
    touch(r)
    return ok(pub(r))


@bp.post('/coating/specifications/<specId>/substitution-requests/<rid>/decide')
@require_roles('TechnicalServiceEngineer')
def decide(specId, rid):
    spec = get_spec_or_404(specId)
    r = get_nested_request(specId, rid)
    if r['status'] != 'UNDER_REVIEW':
        raise ApiError('ERR_INVALID_STATE', 409, 'request is not UNDER_REVIEW')
    p = body()
    decision = req(p, 'decision', 'str', enum={'APPROVE', 'REJECT'})
    reason = p.get('decision_reason')
    if decision == 'APPROVE':
        proposed = get_or_404(store.coating_systems, r['proposed_coating_system_id'],
                              'ERR_COATING_SYSTEM_NOT_FOUND',
                              'proposed coating system not found')
        if proposed['status'] != 'ACTIVE':
            raise ApiError('ERR_SYSTEM_OBSOLETE', 409,
                           'proposed coating system is OBSOLETE')
        pinned = store.voc_regulations.get(spec['pinned_voc_regulation_id'])
        if pinned is not None:
            if voc_as_supplied(proposed) > pinned['voc_limit_gpl']:
                raise ApiError('ERR_VOC_LIMIT_EXCEEDED', 422,
                               'proposed system VOC exceeds the pinned regulation limit')
        if reason is None or not isinstance(reason, str) or not reason:
            raise ApiError('ERR_DECISION_REASON_REQUIRED', 422,
                           'decision_reason is required on approval')
        incumbent = store.coating_systems.get(spec['coating_system_id'])
        if (incumbent is not None
                and proposed['total_dft_min_mils'] < incumbent['total_dft_min_mils']):
            raise ApiError('ERR_DFT_REGRESSION', 422,
                           'proposed system regresses the film build minimum')
        r['status'] = 'APPROVED'
        r['decision_reason'] = reason
        touch(r)
        # Approval seeds a successor DRAFT spec naming the proposed system.
        successor = new_entity()
        successor.update({
            'project_id': spec['project_id'],
            'coating_system_id': proposed['id'],
            'pinned_spec_revision': None,
            'supersedes_specification_id': spec['id'],
            'pinned_voc_regulation_id': None,
            'application_method': spec['application_method'],
            'voc_at_issuance_gpl': None,
            'status': 'DRAFT',
        })
        store.specifications[successor['id']] = successor
        return ok(pub(r))
    # REJECT
    if reason is None or not isinstance(reason, str) or not reason:
        raise ApiError('ERR_DECISION_REASON_REQUIRED', 422,
                       'decision_reason is required on rejection')
    r['status'] = 'REJECTED'
    r['decision_reason'] = reason
    touch(r)
    return ok(pub(r))
