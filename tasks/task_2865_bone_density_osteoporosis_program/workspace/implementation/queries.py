"""Lookup helpers: existence checks (ladder 4-16) and scoped collections."""
from db import by_created_asc, db
from errors import ApiError

NOT_FOUND = {
    "densitometers": "ERR_DENSITOMETER_NOT_FOUND",
    "qc_runs": "ERR_QC_RUN_NOT_FOUND",
    "calibration_events": "ERR_CALIBRATION_EVENT_NOT_FOUND",
    "patients": "ERR_PATIENT_NOT_FOUND",
    "scan_orders": "ERR_SCAN_ORDER_NOT_FOUND",
    "scan_appointments": "ERR_SCAN_APPOINTMENT_NOT_FOUND",
    "scan_sessions": "ERR_SCAN_SESSION_NOT_FOUND",
    "frax_assessments": "ERR_FRAX_ASSESSMENT_NOT_FOUND",
    "diagnostic_reports": "ERR_DIAGNOSTIC_REPORT_NOT_FOUND",
    "treatment_plans": "ERR_TREATMENT_PLAN_NOT_FOUND",
    "payer_policies": "ERR_PAYER_POLICY_NOT_FOUND",
    "risk_factor_profiles": "ERR_RISK_FACTOR_PROFILE_NOT_FOUND",
}


def fetch(collection_name, identifier):
    collection = getattr(db, collection_name)
    if not isinstance(identifier, str) or identifier not in collection:
        raise ApiError(NOT_FOUND[collection_name])
    return collection[identifier]


def device(identifier):
    return fetch("densitometers", identifier)


def patient(identifier):
    return fetch("patients", identifier)


def order(identifier):
    return fetch("scan_orders", identifier)


def appointment(identifier):
    return fetch("scan_appointments", identifier)


def session(identifier):
    return fetch("scan_sessions", identifier)


def report(identifier):
    return fetch("diagnostic_reports", identifier)


def plan(identifier):
    return fetch("treatment_plans", identifier)


def policy_of(patient_row):
    return db.payer_policies.get(patient_row["primary_payer_policy_id"])


def measurements(session_id, include_superseded=False):
    result = [
        row for row in db.site_measurements.values()
        if row["scan_session_id"] == session_id
        and (include_superseded or not row["superseded"])
    ]
    result.sort(key=by_created_asc)
    return result


def measurement_at(session_id, site_code):
    for row in measurements(session_id):
        if row["site_code"] == site_code:
            return row
    return None


def session_of_report(report_row):
    return db.scan_sessions.get(report_row["scan_session_id"])


def order_of_session(session_row):
    appt = db.scan_appointments.get(session_row["scan_appointment_id"])
    if appt is None:
        return None
    return db.scan_orders.get(appt["scan_order_id"])


def appointment_of_session(session_row):
    return db.scan_appointments.get(session_row["scan_appointment_id"])


def active_profile(patient_id):
    candidates = [
        row for row in db.risk_factor_profiles.values()
        if row["patient_id"] == patient_id and row["status"] == "ACTIVE"
    ]
    candidates.sort(key=by_created_asc)
    return candidates[-1] if candidates else None


def reports_of_session(session_id):
    result = [
        row for row in db.diagnostic_reports.values()
        if row["scan_session_id"] == session_id
    ]
    result.sort(key=by_created_asc)
    return result


def finalized_reports_of_patient(patient_id):
    result = []
    for row in db.diagnostic_reports.values():
        if row["status"] != "FINALIZED":
            continue
        session_row = db.scan_sessions.get(row["scan_session_id"])
        if session_row is not None and session_row["patient_id"] == patient_id:
            result.append(row)
    result.sort(key=by_created_asc)
    return result


def orders_of_patient(patient_id, statuses=None):
    result = [
        row for row in db.scan_orders.values()
        if row["patient_id"] == patient_id
        and (statuses is None or row["status"] in statuses)
    ]
    result.sort(key=by_created_asc)
    return result


def appointments_of_order(order_id, statuses=None):
    result = [
        row for row in db.scan_appointments.values()
        if row["scan_order_id"] == order_id
        and (statuses is None or row["status"] in statuses)
    ]
    result.sort(key=lambda row: (row["start_utc"], row["created_at"], row["_seq"]))
    return result


def appointments_of_device(densitometer_id, statuses=None):
    result = [
        row for row in db.scan_appointments.values()
        if row["densitometer_id"] == densitometer_id
        and (statuses is None or row["status"] in statuses)
    ]
    result.sort(key=lambda row: (row["start_utc"], row["created_at"], row["_seq"]))
    return result


def sessions_of_appointment(appointment_id):
    result = [
        row for row in db.scan_sessions.values()
        if row["scan_appointment_id"] == appointment_id
    ]
    result.sort(key=by_created_asc)
    return result


def sessions_of_device(densitometer_id):
    return [
        row for row in db.scan_sessions.values()
        if row["densitometer_id"] == densitometer_id
    ]


def plans_of_patient(patient_id):
    result = [
        row for row in db.treatment_plans.values()
        if row["patient_id"] == patient_id
    ]
    result.sort(key=by_created_asc)
    return result


def refills_of_plan(plan_id):
    result = [
        row for row in db.adherence_refills.values()
        if row["treatment_plan_id"] == plan_id
    ]
    result.sort(key=lambda row: (row["dispensed_date"], row["created_at"], row["_seq"]))
    return result


def qc_runs_of_device(densitometer_id, purpose=None):
    result = [
        row for row in db.qc_runs.values()
        if row["densitometer_id"] == densitometer_id
        and (purpose is None or row["purpose"] == purpose)
    ]
    result.sort(key=lambda row: (row["performed_at_utc"], row["created_at"], row["_seq"]))
    return result


def qc_runs_of_event(event_id, purpose):
    return [
        row for row in db.qc_runs.values()
        if row["calibration_event_id"] == event_id and row["purpose"] == purpose
    ]


def events_of_device(densitometer_id, statuses=None):
    result = [
        row for row in db.calibration_events.values()
        if row["densitometer_id"] == densitometer_id
        and (statuses is None or row["status"] in statuses)
    ]
    result.sort(key=by_created_asc)
    return result


def risk_profiles_of_patient(patient_id):
    result = [
        row for row in db.risk_factor_profiles.values()
        if row["patient_id"] == patient_id
    ]
    result.sort(key=by_created_asc)
    return result


def sessions_of_patient(patient_id):
    result = [
        row for row in db.scan_sessions.values()
        if row["patient_id"] == patient_id
    ]
    result.sort(key=by_created_asc)
    return result
