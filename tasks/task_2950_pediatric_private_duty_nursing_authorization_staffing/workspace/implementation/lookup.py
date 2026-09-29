"""Path- and body-identifier resolution (PRD 2.7): each entity has its own 404."""
from errors import fail
from store import db

_TABLES = (
    ("payer", "payers", "ERR_PAYER_NOT_FOUND"),
    ("patient", "patients", "ERR_PATIENT_NOT_FOUND"),
    ("plan", "plans", "ERR_PLAN_OF_CARE_NOT_FOUND"),
    ("authorization", "authorizations", "ERR_AUTHORIZATION_NOT_FOUND"),
    ("nurse", "nurses", "ERR_NURSE_NOT_FOUND"),
    ("competency", "competencies", "ERR_COMPETENCY_NOT_FOUND"),
    ("case", "cases", "ERR_CASE_NOT_FOUND"),
    ("shift", "shifts", "ERR_SHIFT_NOT_FOUND"),
    ("assignment", "assignments", "ERR_ASSIGNMENT_NOT_FOUND"),
    ("timesheet", "timesheets", "ERR_TIMESHEET_NOT_FOUND"),
    ("incident", "incidents", "ERR_INCIDENT_NOT_FOUND"),
    ("dispute", "disputes", "ERR_DISPUTE_NOT_FOUND"),
)


def _getter(table_name, error_id, label):
    def get(row_id):
        row = getattr(db, table_name).get(row_id) if isinstance(row_id, str) else None
        if row is None:
            fail(error_id, "No %s with id %s." % (label, row_id))
        return row
    return get


get_payer = _getter("payers", "ERR_PAYER_NOT_FOUND", "payer")
get_patient = _getter("patients", "ERR_PATIENT_NOT_FOUND", "patient")
get_plan = _getter("plans", "ERR_PLAN_OF_CARE_NOT_FOUND", "plan of care")
get_authorization = _getter("authorizations", "ERR_AUTHORIZATION_NOT_FOUND", "authorization")
get_nurse = _getter("nurses", "ERR_NURSE_NOT_FOUND", "nurse")
get_competency = _getter("competencies", "ERR_COMPETENCY_NOT_FOUND", "competency")
get_case = _getter("cases", "ERR_CASE_NOT_FOUND", "case")
get_shift = _getter("shifts", "ERR_SHIFT_NOT_FOUND", "shift")
get_assignment = _getter("assignments", "ERR_ASSIGNMENT_NOT_FOUND", "assignment")
get_timesheet = _getter("timesheets", "ERR_TIMESHEET_NOT_FOUND", "timesheet")
get_incident = _getter("incidents", "ERR_INCIDENT_NOT_FOUND", "incident report")
get_dispute = _getter("disputes", "ERR_DISPUTE_NOT_FOUND", "dispute")
