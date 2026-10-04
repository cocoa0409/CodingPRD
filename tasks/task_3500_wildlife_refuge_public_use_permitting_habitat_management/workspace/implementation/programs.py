"""Interpretive programs, volunteers, and volunteer assignments (PRD 3.6)."""
from flask import Blueprint, request
import store
from store import DB, mutate
from envelope import ok, fail
from auth import endpoint, not_found, invalid_state, forbidden
from util import get_body, req_str, req_int, req_date, parse_d, paged
from calc import full_closure_covers

bp = Blueprint('programs', __name__)

PROGRAM_FIELDS = (
    'id', 'management_unit_id', 'title', 'program_date', 'min_volunteers',
    'max_volunteers', 'status', 'created_at', 'updated_at', 'version',
)
VOLUNTEER_FIELDS = (
    'id', 'full_name', 'email', 'background_status', 'cleared_on',
    'created_at', 'updated_at', 'version',
)
ASSIGNMENT_FIELDS = (
    'id', 'volunteer_id', 'program_id', 'status',
    'created_at', 'updated_at', 'version',
)

COORDINATORS = ('VolunteerCoordinator', 'RefugeManager')
PROGRAM_READERS = ('VolunteerCoordinator', 'RefugeManager', 'Anonymous')
ASSIGNMENT_READERS = ('VolunteerCoordinator', 'RefugeManager', 'Volunteer')


def pub_program(p):
    return store.pub(p, PROGRAM_FIELDS)


def pub_volunteer(v):
    return store.pub(v, VOLUNTEER_FIELDS)


def pub_assignment(a):
    return store.pub(a, ASSIGNMENT_FIELDS)


@bp.route('/refuge/management-units/<unit_id>/programs', methods=['POST'], strict_slashes=False)
@endpoint(COORDINATORS)
def create_program(role, uid, unit_id):
    body = get_body()
    title = req_str(body, 'title')
    program_date = req_date(body, 'program_date')
    min_volunteers = req_int(body, 'min_volunteers', minimum=1)
    max_volunteers = req_int(body, 'max_volunteers', minimum=1)
    if max_volunteers < min_volunteers:
        fail('ERR_INVALID_REQUEST', 'max_volunteers must be >= min_volunteers')
    unit = DB.units.get(unit_id)
    if unit is None:
        not_found('management unit not found')
    # priority 8: date-scoped posture gate -- program_date must not intersect
    # an ACTIVE FULL-scope closure window on the same unit
    if full_closure_covers(unit_id, parse_d(program_date)):
        fail('ERR_POSTURE_CLOSED', 'program date intersects an active full-scope closure')
    # priority 19: program date must not precede the current clock date
    if parse_d(program_date) < store.clock_date():
        fail('ERR_WINDOW_IN_PAST', 'program_date precedes the current clock date')
    rec = store.new_record({
        'management_unit_id': unit_id,
        'title': title,
        'program_date': program_date,
        'min_volunteers': min_volunteers,
        'max_volunteers': max_volunteers,
        'status': 'SCHEDULED',
    })
    DB.programs[rec['id']] = rec
    return ok(pub_program(rec), 201)


@bp.route('/refuge/management-units/<unit_id>/programs', methods=['GET'], strict_slashes=False)
@endpoint(PROGRAM_READERS)
def list_programs(role, uid, unit_id):
    unit = DB.units.get(unit_id)
    if unit is None:
        not_found('management unit not found')
    status = request.args.get('status')
    items = [p for p in DB.programs.values() if p['management_unit_id'] == unit_id]
    if status is not None:
        items = [p for p in items if p['status'] == status]
    return paged(items, pub_program)


@bp.route('/refuge/volunteers', methods=['POST'], strict_slashes=False)
@endpoint(['Anonymous'])
def create_volunteer(role, uid):
    body = get_body()
    full_name = req_str(body, 'full_name')
    email = req_str(body, 'email')
    rec = store.new_record({
        'full_name': full_name,
        'email': email,
        'background_status': 'PENDING',
        'cleared_on': None,
    })
    DB.volunteers[rec['id']] = rec
    return ok(pub_volunteer(rec), 201)


@bp.route('/refuge/volunteers/<volunteer_id>/clear-background', methods=['POST'], strict_slashes=False)
@endpoint(COORDINATORS)
def clear_background(role, uid, volunteer_id):
    rec = DB.volunteers.get(volunteer_id)
    if rec is None:
        not_found('volunteer not found')
    if rec['background_status'] not in ('PENDING', 'EXPIRED'):
        invalid_state('only a PENDING or EXPIRED volunteer can be cleared')
    mutate(rec, background_status='CLEARED',
           cleared_on=store.clock_date().isoformat())
    return ok(pub_volunteer(rec))


@bp.route('/refuge/programs/<program_id>/assignments', methods=['POST'], strict_slashes=False)
@endpoint(COORDINATORS)
def create_assignment(role, uid, program_id):
    body = get_body()
    volunteer_id = req_str(body, 'volunteer_id')
    # priority 4: path first, then body FK
    program = DB.programs.get(program_id)
    if program is None:
        not_found('program not found')
    volunteer = DB.volunteers.get(volunteer_id)
    if volunteer is None:
        not_found('volunteer not found')
    # priority 5: program must still be SCHEDULED
    if program['status'] != 'SCHEDULED':
        invalid_state('assignments can only be added to a SCHEDULED program')
    # priority 11: volunteer must be CLEARED
    if volunteer['background_status'] != 'CLEARED':
        fail('ERR_VOLUNTEER_NOT_CLEARED', 'volunteer background is not CLEARED')
    # priority 14: at most one ACTIVE assignment per volunteer per program
    for a in DB.assignments.values():
        if (a['program_id'] == program_id and a['volunteer_id'] == volunteer_id
                and a['status'] == 'ACTIVE'):
            fail('ERR_DUPLICATE_ASSIGNMENT',
                 'volunteer already holds an ACTIVE assignment on this program')
    # priority 15: program staffing ceiling
    active = sum(1 for a in DB.assignments.values()
                 if a['program_id'] == program_id and a['status'] == 'ACTIVE')
    if active >= program['max_volunteers']:
        fail('ERR_PROGRAM_CAPACITY_EXCEEDED',
             'program already carries max_volunteers ACTIVE assignments')
    rec = store.new_record({
        'volunteer_id': volunteer_id,
        'program_id': program_id,
        'status': 'ACTIVE',
    })
    DB.assignments[rec['id']] = rec
    return ok(pub_assignment(rec), 201)


@bp.route('/refuge/assignments/<assignment_id>', methods=['GET'], strict_slashes=False)
@endpoint(ASSIGNMENT_READERS)
def get_assignment(role, uid, assignment_id):
    rec = DB.assignments.get(assignment_id)
    if rec is None:
        not_found('assignment not found')
    if role == 'Volunteer' and rec['volunteer_id'] != uid:
        forbidden('volunteers may only read their own assignments')
    return ok(pub_assignment(rec))


@bp.route('/refuge/assignments', methods=['GET'], strict_slashes=False)
@endpoint(ASSIGNMENT_READERS)
def list_assignments(role, uid):
    volunteer_id = request.args.get('volunteer_id')
    program_id = request.args.get('program_id')
    status = request.args.get('status')
    if role == 'Volunteer':
        # volunteer callers may only query their own volunteer_id
        if volunteer_id is not None and volunteer_id != uid:
            forbidden('volunteers may only list their own assignments')
        volunteer_id = uid
    items = list(DB.assignments.values())
    if volunteer_id is not None:
        items = [a for a in items if a['volunteer_id'] == volunteer_id]
    if program_id is not None:
        items = [a for a in items if a['program_id'] == program_id]
    if status is not None:
        items = [a for a in items if a['status'] == status]
    return paged(items, pub_assignment)
