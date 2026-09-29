"""In-memory store. Starts empty on every boot; nothing is ever seeded."""

import itertools
import uuid

import clock

DISTRICTS = {}
CANDIDATES = {}
ITEMS = {}
AGREEMENTS = {}
TEACHERS = {}
SUPERVISORS = {}
REQUESTS = {}
PLACEMENTS = {}
CYCLES = {}
ASSESSMENTS = {}

_seq = itertools.count(1)

# Rows already version-bumped during the current request. A cascade that touches
# three entities bumps three versions, but one row never bumps twice per request.
_touched = set()


def begin_request():
    _touched.clear()


def new_id():
    return str(uuid.uuid4())


def new_row(extra=None):
    inst = clock.now()
    row = {
        "id": new_id(),
        "created_at": inst,
        "updated_at": inst,
        "version": 1,
        "_seq": next(_seq),
    }
    if extra:
        row.update(extra)
    _touched.add(row["id"])
    return row


def touch(row):
    """Bump version / updated_at at most once per row per request."""
    if row is None:
        return row
    if row["id"] in _touched:
        return row
    row["version"] = row["version"] + 1
    row["updated_at"] = clock.now()
    _touched.add(row["id"])
    return row


def ordered(rows):
    """Default ordering: created_at ascending, stable by insertion sequence."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def all_of(table):
    return ordered(list(table.values()))


# --- path / foreign-key lookups (ladder rungs 5 and 7) ---------------------

def _get(table, row_id, error_id):
    from errors import ApiError
    if not isinstance(row_id, str) or row_id not in table:
        raise ApiError(error_id)
    return table[row_id]


def get_district(row_id):
    return _get(DISTRICTS, row_id, "ERR_DISTRICT_NOT_FOUND")


def get_candidate(row_id):
    return _get(CANDIDATES, row_id, "ERR_CANDIDATE_NOT_FOUND")


def get_item(row_id):
    return _get(ITEMS, row_id, "ERR_READINESS_ITEM_NOT_FOUND")


def get_agreement(row_id):
    return _get(AGREEMENTS, row_id, "ERR_AGREEMENT_NOT_FOUND")


def get_teacher(row_id):
    return _get(TEACHERS, row_id, "ERR_TEACHER_NOT_FOUND")


def get_supervisor(row_id):
    return _get(SUPERVISORS, row_id, "ERR_SUPERVISOR_NOT_FOUND")


def get_request(row_id):
    return _get(REQUESTS, row_id, "ERR_REQUEST_NOT_FOUND")


def get_placement(row_id):
    return _get(PLACEMENTS, row_id, "ERR_PLACEMENT_NOT_FOUND")


def get_cycle(row_id):
    return _get(CYCLES, row_id, "ERR_CYCLE_NOT_FOUND")


def get_assessment(row_id):
    return _get(ASSESSMENTS, row_id, "ERR_ASSESSMENT_NOT_FOUND")


def items_of(candidate_id):
    return ordered([r for r in ITEMS.values()
                    if r["candidate_id"] == candidate_id])


def placements_of_agreement(agreement_id):
    return ordered([r for r in PLACEMENTS.values()
                    if r["agreement_id"] == agreement_id])


def placements_of_teacher(teacher_id):
    return ordered([r for r in PLACEMENTS.values()
                    if r["cooperating_teacher_id"] == teacher_id])


def placements_of_supervisor(supervisor_id):
    return ordered([r for r in PLACEMENTS.values()
                    if r["supervisor_id"] == supervisor_id])


def placements_of_request(request_id):
    return ordered([r for r in PLACEMENTS.values()
                    if r["request_id"] == request_id])


def placements_of_candidate(candidate_id):
    return ordered([r for r in PLACEMENTS.values()
                    if r["candidate_id"] == candidate_id])


def cycles_of_placement(placement_id):
    return ordered([r for r in CYCLES.values()
                    if r["placement_id"] == placement_id])


def assessment_of_placement(placement_id):
    rows = ordered([r for r in ASSESSMENTS.values()
                    if r["placement_id"] == placement_id])
    return rows[0] if rows else None


def agreements_of_district(district_id):
    return ordered([r for r in AGREEMENTS.values()
                    if r["district_id"] == district_id])
