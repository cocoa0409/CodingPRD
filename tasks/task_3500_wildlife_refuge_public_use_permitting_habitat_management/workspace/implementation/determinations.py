"""Compatibility determinations and public comments (PRD 3.2)."""
from flask import Blueprint, request
import store
from store import DB, mutate
from envelope import ok, fail
from auth import endpoint, not_found, invalid_state
from util import (get_body, req_str, req_enum, req_date, opt_str, parse_d, paged)
from calc import DETERMINATION_USE_TYPES

bp = Blueprint('determinations', __name__)

DET_FIELDS = (
    'id', 'use_type', 'title', 'comment_open_date', 'comment_close_date',
    'status', 'finding', 'rationale', 'unresolved_comment_count',
    'created_at', 'updated_at', 'version',
)
COMMENT_FIELDS = (
    'id', 'determination_id', 'author_name', 'body', 'status', 'disposition',
    'note', 'created_at', 'updated_at', 'version',
)

OFFICERS = ('PermitOfficer', 'RefugeManager')
DET_READERS = ('PermitOfficer', 'RefugeManager', 'Anonymous')


def pub_det(d):
    return store.pub(d, DET_FIELDS)


def pub_comment(c):
    return store.pub(c, COMMENT_FIELDS)


@bp.route('/refuge/determinations', methods=['POST'], strict_slashes=False)
@endpoint(OFFICERS)
def create_determination(role, uid):
    body = get_body()
    use_type = req_enum(body, 'use_type', DETERMINATION_USE_TYPES)
    title = req_str(body, 'title')
    open_d = req_date(body, 'comment_open_date')
    close_d = req_date(body, 'comment_close_date')
    # priority 18: comment_close_date must be strictly after comment_open_date
    if parse_d(close_d) <= parse_d(open_d):
        fail('ERR_DATE_RANGE_INVALID', 'comment_close_date must be after comment_open_date')
    # priority 19: comment window must not open in the past
    if parse_d(open_d) < store.clock_date():
        fail('ERR_WINDOW_IN_PAST', 'comment_open_date precedes the current clock date')
    rec = store.new_record({
        'use_type': use_type,
        'title': title,
        'comment_open_date': open_d,
        'comment_close_date': close_d,
        'status': 'DRAFT',
        'finding': None,
        'rationale': None,
        'unresolved_comment_count': 0,
    })
    DB.determinations[rec['id']] = rec
    return ok(pub_det(rec), 201)


@bp.route('/refuge/determinations/<det_id>', methods=['GET'], strict_slashes=False)
@endpoint(DET_READERS)
def get_determination(role, uid, det_id):
    rec = DB.determinations.get(det_id)
    if rec is None:
        not_found('determination not found')
    return ok(pub_det(rec))


@bp.route('/refuge/determinations/<det_id>/open-comment', methods=['POST'], strict_slashes=False)
@endpoint(OFFICERS)
def open_comment(role, uid, det_id):
    rec = DB.determinations.get(det_id)
    if rec is None:
        not_found('determination not found')
    # priority 5: DRAFT only
    if rec['status'] != 'DRAFT':
        invalid_state('comment window can only be opened from DRAFT')
    # priority 19: clock date must fall within [open, close] inclusive
    today = store.clock_date()
    if not (parse_d(rec['comment_open_date']) <= today <= parse_d(rec['comment_close_date'])):
        fail('ERR_WINDOW_IN_PAST', 'current clock date is outside the comment window')
    mutate(rec, status='PUBLIC_COMMENT')
    return ok(pub_det(rec))


@bp.route('/refuge/determinations/<det_id>/finalize', methods=['POST'], strict_slashes=False)
@endpoint(OFFICERS)
def finalize(role, uid, det_id):
    body = get_body()
    finding = req_enum(body, 'finding', ('COMPATIBLE', 'NOT_COMPATIBLE'))
    rationale = req_str(body, 'rationale')
    rec = DB.determinations.get(det_id)
    if rec is None:
        not_found('determination not found')
    if rec['status'] != 'ADJUDICATION':
        invalid_state('determination can only be finalized from ADJUDICATION')
    # priority 17
    if rec['unresolved_comment_count'] > 0:
        fail('ERR_UNRESOLVED_COMMENTS', 'unresolved comments remain')
    mutate(rec, finding=finding, rationale=rationale, status='FINAL')
    return ok(pub_det(rec))


@bp.route('/refuge/determinations/<det_id>/comments', methods=['POST'], strict_slashes=False)
@endpoint(['Anonymous'])
def create_comment(role, uid, det_id):
    body = get_body()
    author_name = req_str(body, 'author_name')
    text = req_str(body, 'body')
    det = DB.determinations.get(det_id)
    if det is None:
        not_found('determination not found')
    if det['status'] != 'PUBLIC_COMMENT':
        invalid_state('comments are accepted only while the determination is in PUBLIC_COMMENT')
    rec = store.new_record({
        'determination_id': det_id,
        'author_name': author_name,
        'body': text,
        'status': 'SUBMITTED',
        'disposition': None,
        'note': None,
    })
    DB.comments[rec['id']] = rec
    mutate(det, unresolved_comment_count=det['unresolved_comment_count'] + 1)
    return ok(pub_comment(rec), 201)


@bp.route('/refuge/determinations/<det_id>/comments', methods=['GET'], strict_slashes=False)
@endpoint(DET_READERS)
def list_comments(role, uid, det_id):
    det = DB.determinations.get(det_id)
    if det is None:
        not_found('determination not found')
    status = request.args.get('status')
    items = [c for c in DB.comments.values() if c['determination_id'] == det_id]
    if status is not None:
        items = [c for c in items if c['status'] == status]
    return paged(items, pub_comment)


@bp.route('/refuge/comments/<comment_id>/adjudicate', methods=['POST'], strict_slashes=False)
@endpoint(OFFICERS)
def adjudicate(role, uid, comment_id):
    body = get_body()
    disposition = req_enum(body, 'disposition', ('ACCEPTED', 'REJECTED', 'NOTED'))
    note = opt_str(body, 'note')  # optional; recorded on the comment (PRD 3.2)
    rec = DB.comments.get(comment_id)
    if rec is None:
        not_found('comment not found')
    if rec['status'] != 'SUBMITTED':
        invalid_state('only a SUBMITTED comment can be adjudicated')
    det = DB.determinations.get(rec['determination_id'])
    if det is None or det['status'] not in ('PUBLIC_COMMENT', 'ADJUDICATION'):
        invalid_state('parent determination is not open for adjudication')
    changes = {'status': 'ADJUDICATED', 'disposition': disposition}
    if note is not None:
        changes['note'] = note
    mutate(rec, **changes)
    mutate(det, unresolved_comment_count=det['unresolved_comment_count'] - 1)
    return ok(pub_comment(rec))
