"""Lookup helpers shared by every service and route module."""
from db import order_key, store
from errors import fail
from util import parse_date, parse_instant


def _find(collection, row_id, error_id):
    row = collection.get(row_id)
    if row is None:
        fail(error_id, "resource not found")
    return row


def get_cycle(cycle_id):
    return _find(store.cycles, cycle_id, "ERR_CYCLE_NOT_FOUND")


def get_frozen_file(file_id):
    return _find(store.frozen_files, file_id, "ERR_FROZEN_FILE_NOT_FOUND")


def get_component(component_id):
    return _find(store.components, component_id, "ERR_COMPONENT_NOT_FOUND")


def get_metric(metric_id):
    return _find(store.metrics, metric_id, "ERR_METRIC_NOT_FOUND")


def get_edit_check(check_id):
    return _find(store.edit_checks, check_id, "ERR_EDIT_CHECK_NOT_FOUND")


def get_cohort(cohort_id):
    return _find(store.cohorts, cohort_id, "ERR_COHORT_NOT_FOUND")


def get_member(member_id):
    return _find(store.members, member_id, "ERR_MEMBER_NOT_FOUND")


def get_definition(definition_id):
    return _find(store.definitions, definition_id, "ERR_DEFINITION_NOT_FOUND")


def get_mapping(mapping_id):
    return _find(store.mappings, mapping_id, "ERR_MAPPING_NOT_FOUND")


def get_submission(submission_id):
    return _find(store.submissions, submission_id, "ERR_SUBMISSION_NOT_FOUND")


def get_publication(publication_id):
    return _find(store.publications, publication_id, "ERR_PUBLICATION_NOT_FOUND")


def get_restatement(restatement_id):
    return _find(store.restatements, restatement_id, "ERR_RESTATEMENT_NOT_FOUND")


def get_data_request(request_id):
    return _find(store.data_requests, request_id, "ERR_DATA_REQUEST_NOT_FOUND")


def get_cell(cell_id):
    return _find(store.cells, cell_id, "ERR_CELL_NOT_FOUND")


def children(collection, key, value):
    """Every row of `collection` whose `key` equals `value`, in created_at ASC order."""
    rows = [r for r in collection.values() if r.get(key) == value]
    rows.sort(key=order_key)
    return rows


def files_of(cycle_id):
    return children(store.frozen_files, "cycle_id", cycle_id)


def components_of(cycle_id):
    return children(store.components, "cycle_id", cycle_id)


def metrics_of(component_id):
    return children(store.metrics, "component_id", component_id)


def checks_of(component_id):
    """EditCheck children in sequence_no ASC order (PRD 2.3 / 2.7)."""
    rows = [r for r in store.edit_checks.values() if r.get("component_id") == component_id]
    rows.sort(key=lambda r: (r.get("sequence_no") or 0, r.get("_seq") or 0))
    return rows


def cohorts_of(cycle_id):
    return children(store.cohorts, "cycle_id", cycle_id)


def members_of(cohort_id):
    return children(store.members, "cohort_id", cohort_id)


def publications_of(component_id):
    return children(store.publications, "component_id", component_id)


def restatements_of(publication_id):
    return children(store.restatements, "publication_id", publication_id)


def cells_of(request_id):
    return children(store.cells, "request_id", request_id)


def cycle_of_component(component):
    return store.cycles.get(component.get("cycle_id"))


def cycle_of_publication(publication):
    component = store.components.get(publication.get("component_id"))
    if component is None:
        return None
    return store.cycles.get(component.get("cycle_id"))


def clock_date():
    return store.now().date()


def clock_instant():
    return store.now()


def as_date(value):
    return parse_date(value)


def as_instant(value):
    return parse_instant(value)
