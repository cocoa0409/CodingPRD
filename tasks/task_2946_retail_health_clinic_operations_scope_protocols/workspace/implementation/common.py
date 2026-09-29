"""Shared route helpers: reference resolution and list responses."""

import errors
from envelope import list_response
from errors import raise_error
from shapes import read_pagination
from store import db, ordered


def _resolve(table, row_id, error_id):
    if row_id is None:
        raise_error(error_id)
    row = table.get(row_id)
    if row is None:
        raise_error(error_id)
    return row


def get_state_rule(row_id):
    return _resolve(db.state_rules, row_id, errors.ERR_STATE_RULE_NOT_FOUND)


def get_protocol(row_id):
    return _resolve(db.protocols, row_id, errors.ERR_PROTOCOL_NOT_FOUND)


def get_clinic(row_id):
    return _resolve(db.clinics, row_id, errors.ERR_CLINIC_NOT_FOUND)


def get_physician(row_id):
    return _resolve(db.physicians, row_id, errors.ERR_PHYSICIAN_NOT_FOUND)


def get_clinician(row_id):
    return _resolve(db.clinicians, row_id, errors.ERR_CLINICIAN_NOT_FOUND)


def get_patient(row_id):
    return _resolve(db.patients, row_id, errors.ERR_PATIENT_NOT_FOUND)


def get_assignment(row_id):
    return _resolve(
        db.assignments, row_id, errors.ERR_STAFFING_ASSIGNMENT_NOT_FOUND
    )


def get_queue_entry(row_id):
    return _resolve(db.queue_entries, row_id, errors.ERR_QUEUE_ENTRY_NOT_FOUND)


def get_visit(row_id):
    return _resolve(db.visits, row_id, errors.ERR_VISIT_NOT_FOUND)


def get_assessment(row_id):
    return _resolve(db.assessments, row_id, errors.ERR_ASSESSMENT_NOT_FOUND)


def get_prescription(row_id):
    return _resolve(db.prescriptions, row_id, errors.ERR_PRESCRIPTION_NOT_FOUND)


def get_chart_review(row_id):
    return _resolve(db.chart_reviews, row_id, errors.ERR_CHART_REVIEW_NOT_FOUND)


def get_visit_summary(row_id):
    return _resolve(
        db.visit_summaries, row_id, errors.ERR_VISIT_SUMMARY_NOT_FOUND
    )


def state_rule_or_404(state_code):
    import calc

    rule = calc.state_rule_for(state_code)
    if rule is None:
        raise_error(
            errors.ERR_STATE_RULE_NOT_FOUND,
            "No state rule is registered for state %s." % state_code,
        )
    return rule


def respond_list(rows, serializer, limit, offset):
    total = len(rows)
    window = rows[offset:offset + limit]
    return list_response(
        [serializer(row) for row in window], limit, offset, total
    )


def collection(table, serializer, filters):
    """Standard filtered list: filters is a list of (value, predicate)."""
    limit, offset = read_pagination()
    rows = ordered(table.values())
    for value, predicate in filters:
        if value is None:
            continue
        rows = [row for row in rows if predicate(row, value)]
    return respond_list(rows, serializer, limit, offset)
