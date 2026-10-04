"""Population objectives and state agency surveys (PRD 3.9)."""
from flask import Blueprint
import store
from store import DB, mutate
from envelope import ok
from auth import endpoint, not_found, STAFF_READERS
from util import get_body, req_str, req_int, paged
from calc import population_status

bp = Blueprint('population', __name__)

OBJECTIVE_FIELDS = (
    'id', 'management_unit_id', 'species', 'target_count',
    'current_survey_count', 'status', 'created_at', 'updated_at', 'version',
)

PARTNERS = ('StateAgencyPartner', 'RefugeManager')


def pub_objective(o):
    return store.pub(o, OBJECTIVE_FIELDS)


@bp.route('/refuge/management-units/<unit_id>/population-objectives', methods=['POST'], strict_slashes=False)
@endpoint(PARTNERS)
def create_objective(role, uid, unit_id):
    body = get_body()
    species = req_str(body, 'species')
    target_count = req_int(body, 'target_count', minimum=1)
    unit = DB.units.get(unit_id)
    if unit is None:
        not_found('management unit not found')
    rec = store.new_record({
        'management_unit_id': unit_id,
        'species': species,
        'target_count': target_count,
        'current_survey_count': None,
        'status': 'NO_SURVEY',
    })
    DB.objectives[rec['id']] = rec
    return ok(pub_objective(rec), 201)


@bp.route('/refuge/management-units/<unit_id>/population-objectives', methods=['GET'], strict_slashes=False)
@endpoint(STAFF_READERS)
def list_objectives(role, uid, unit_id):
    unit = DB.units.get(unit_id)
    if unit is None:
        not_found('management unit not found')
    items = [o for o in DB.objectives.values() if o['management_unit_id'] == unit_id]
    return paged(items, pub_objective)


@bp.route('/refuge/population-objectives/<objective_id>/surveys', methods=['POST'], strict_slashes=False)
@endpoint(PARTNERS)
def record_survey(role, uid, objective_id):
    body = get_body()
    survey_count = req_int(body, 'survey_count')
    rec = DB.objectives.get(objective_id)
    if rec is None:
        not_found('population objective not found')
    mutate(rec,
           current_survey_count=survey_count,
           status=population_status(survey_count, rec['target_count']))
    return ok(pub_objective(rec))
