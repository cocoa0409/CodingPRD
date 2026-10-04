"""Citations: law-enforcement instrument (PRD 3.8). Exactly one subject;
agreement subjects debit compliance points and carry the OCC guard."""
from flask import Blueprint, request
import store
from store import DB, mutate
from envelope import ok, fail
from auth import endpoint, not_found, invalid_state
from util import get_body, req_str, req_int, req_enum, paged
from calc import POINTS, SUSPEND_THRESHOLD_POINTS

bp = Blueprint('citations', __name__)

CITATION_FIELDS = (
    'id', 'severity', 'points', 'subject_permit_id', 'subject_agreement_id',
    'note', 'status', 'created_at', 'updated_at', 'version',
)

ENFORCEMENT = ('LawEnforcementOfficer', 'RefugeManager')
CITATION_READERS = ('LawEnforcementOfficer', 'RefugeManager', 'PermitOfficer')


def pub_citation(c):
    return store.pub(c, CITATION_FIELDS)


@bp.route('/refuge/citations', methods=['POST'], strict_slashes=False)
@endpoint(ENFORCEMENT)
def create_citation(role, uid):
    body = get_body()
    severity = req_enum(body, 'severity', ('MINOR', 'MAJOR', 'CRITICAL'))
    note = req_str(body, 'note')
    subject_permit_id = body.get('subject_permit_id')
    subject_agreement_id = body.get('subject_agreement_id')
    if subject_permit_id is not None and not isinstance(subject_permit_id, str):
        fail('ERR_INVALID_REQUEST', 'subject_permit_id must be a string')
    if subject_agreement_id is not None and not isinstance(subject_agreement_id, str):
        fail('ERR_INVALID_REQUEST', 'subject_agreement_id must be a string')
    # priority 3: exactly one of the two subject references
    if (subject_permit_id is None) == (subject_agreement_id is None):
        fail('ERR_INVALID_REQUEST', 'exactly one of subject_permit_id / subject_agreement_id is required')
    expected_version = None
    if subject_agreement_id is not None:
        # the OCC field is non-optional on the agreement-subject path
        expected_version = req_int(body, 'expected_agreement_version')
    # priority 4: body FK existence
    agreement = None
    if subject_permit_id is not None:
        if DB.permits.get(subject_permit_id) is None:
            not_found('subject permit not found')
    else:
        agreement = DB.agreements.get(subject_agreement_id)
        if agreement is None:
            not_found('subject agreement not found')
        # priority 6: optimistic concurrency (agreement subjects only)
        if expected_version != agreement['version']:
            fail('ERR_STALE_VERSION', 'expected_agreement_version does not match the agreement version')
    points = POINTS[severity]  # computed from severity; any input value ignored
    rec = store.new_record({
        'severity': severity,
        'points': points,
        'subject_permit_id': subject_permit_id,
        'subject_agreement_id': subject_agreement_id,
        'note': note,
        'status': 'ISSUED',
    })
    DB.citations[rec['id']] = rec
    if agreement is not None:
        # debit compliance points; cascade ACTIVE -> SUSPENDED below 60
        # (boundary: exactly 60 remains ACTIVE). One mutation = one version bump.
        # force: issuing an agreement-subject citation is a pinned modification
        # (PRD 2.4) — version bumps exactly once regardless of point movement.
        new_points = agreement['compliance_points'] - points
        changes = {'compliance_points': new_points}
        if agreement['status'] == 'ACTIVE' and new_points < SUSPEND_THRESHOLD_POINTS:
            changes['status'] = 'SUSPENDED'
        mutate(agreement, force=True, **changes)
    return ok(pub_citation(rec), 201)


@bp.route('/refuge/citations/<citation_id>', methods=['GET'], strict_slashes=False)
@endpoint(CITATION_READERS)
def get_citation(role, uid, citation_id):
    rec = DB.citations.get(citation_id)
    if rec is None:
        not_found('citation not found')
    return ok(pub_citation(rec))


@bp.route('/refuge/citations', methods=['GET'], strict_slashes=False)
@endpoint(CITATION_READERS)
def list_citations(role, uid):
    permit_id = request.args.get('subject_permit_id')
    agreement_id = request.args.get('subject_agreement_id')
    status = request.args.get('status')
    items = list(DB.citations.values())
    if permit_id is not None:
        items = [c for c in items if c.get('subject_permit_id') == permit_id]
    if agreement_id is not None:
        items = [c for c in items if c.get('subject_agreement_id') == agreement_id]
    if status is not None:
        items = [c for c in items if c['status'] == status]
    return paged(items, pub_citation)


@bp.route('/refuge/citations/<citation_id>/void', methods=['POST'], strict_slashes=False)
@endpoint(ENFORCEMENT)
def void_citation(role, uid, citation_id):
    body = get_body()
    req_str(body, 'reason')
    rec = DB.citations.get(citation_id)
    if rec is None:
        not_found('citation not found')
    if rec['status'] != 'ISSUED':
        invalid_state('only an ISSUED citation can be voided')
    mutate(rec, status='VOIDED')
    if rec.get('subject_agreement_id'):
        agreement = DB.agreements.get(rec['subject_agreement_id'])
        if agreement is not None:
            # credit the points back; cascade SUSPENDED -> ACTIVE at >= 60
            # force: voiding an agreement-subject citation is a pinned
            # modification (PRD 2.4) — version bumps exactly once regardless.
            new_points = agreement['compliance_points'] + rec['points']
            changes = {'compliance_points': new_points}
            if agreement['status'] == 'SUSPENDED' and new_points >= SUSPEND_THRESHOLD_POINTS:
                changes['status'] = 'ACTIVE'
            mutate(agreement, force=True, **changes)
    return ok(pub_citation(rec))
