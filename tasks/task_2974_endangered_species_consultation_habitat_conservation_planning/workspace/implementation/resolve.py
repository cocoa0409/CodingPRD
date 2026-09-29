"""Rung 4 / rung 6: existence resolution.  Path ids resolve left to right, so
callers invoke these in path order and the leftmost failure decides."""
import store
from errors import ApiError

_TABLE_ERROR = {
    "species": "ERR_SPECIES_NOT_FOUND",
    "proponents": "ERR_PROPONENT_NOT_FOUND",
    "actions": "ERR_PROJECT_ACTION_NOT_FOUND",
    "habitat_units": "ERR_CRITICAL_HABITAT_UNIT_NOT_FOUND",
    "determinations": "ERR_PRESENCE_DETERMINATION_NOT_FOUND",
    "consultations": "ERR_CONSULTATION_NOT_FOUND",
    "plans": "ERR_HCP_NOT_FOUND",
    "banks": "ERR_CONSERVATION_BANK_NOT_FOUND",
    "permits": "ERR_PERMIT_NOT_FOUND",
    "reports": "ERR_MONITORING_REPORT_NOT_FOUND",
    "events": "ERR_CIRCUMSTANCE_EVENT_NOT_FOUND",
}


def must(table, row_id):
    row = store.get(table, row_id)
    if row is None:
        raise ApiError(_TABLE_ERROR[table])
    return row


def species(row_id):
    return must("species", row_id)


def proponent(row_id):
    return must("proponents", row_id)


def action(row_id):
    return must("actions", row_id)


def habitat_unit(row_id):
    return must("habitat_units", row_id)


def determination(row_id):
    return must("determinations", row_id)


def consultation(row_id):
    return must("consultations", row_id)


def plan(row_id):
    return must("plans", row_id)


def bank(row_id):
    return must("banks", row_id)


def permit(row_id):
    return must("permits", row_id)


def report(row_id):
    return must("reports", row_id)


def event(row_id):
    return must("events", row_id)
