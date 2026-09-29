"""Reference resolution (PRD section 2.5).  Each addressable variable resolves
to its own not-found error, and path variables are checked left to right."""
from errors import ApiError
from store import db


def _need(collection, record_id, error_id, label):
    if record_id is None:
        raise ApiError(error_id, "No %s matches the supplied identifier." % label)
    record = collection.get(record_id)
    if record is None:
        raise ApiError(error_id, "No %s matches the supplied identifier." % label)
    return record


def need_client(record_id):
    return _need(db.clients, record_id, "ERR_CLIENT_NOT_FOUND", "client")


def need_care_manager(record_id):
    return _need(db.care_managers, record_id, "ERR_CARE_MANAGER_NOT_FOUND",
                 "care manager")


def need_vendor(record_id):
    return _need(db.vendors, record_id, "ERR_VENDOR_NOT_FOUND", "vendor")


def need_contact(record_id):
    return _need(db.contacts, record_id, "ERR_CONTACT_NOT_FOUND",
                 "family contact")


def need_assessment(record_id):
    return _need(db.assessments, record_id, "ERR_ASSESSMENT_NOT_FOUND",
                 "assessment")


def need_care_plan(record_id):
    return _need(db.care_plans, record_id, "ERR_CARE_PLAN_NOT_FOUND",
                 "care plan")


def need_authorization(record_id):
    return _need(db.authorizations, record_id, "ERR_AUTHORIZATION_NOT_FOUND",
                 "service authorization")


def need_conference(record_id):
    return _need(db.conferences, record_id, "ERR_CONFERENCE_NOT_FOUND",
                 "family conference")


def need_decision(record_id):
    return _need(db.decisions, record_id, "ERR_DECISION_NOT_FOUND",
                 "conference decision")


def need_episode(record_id):
    return _need(db.episodes, record_id, "ERR_CRISIS_EPISODE_NOT_FOUND",
                 "crisis episode")


def need_time_entry(record_id):
    return _need(db.time_entries, record_id, "ERR_TIME_ENTRY_NOT_FOUND",
                 "time entry")


def need_invoice(record_id):
    return _need(db.invoices, record_id, "ERR_INVOICE_NOT_FOUND", "invoice")


def filter_records(records, spec, supplied):
    """Filters combine conjunctively: a record must satisfy every filter."""
    out = []
    for record in records:
        keep = True
        for name, value in supplied.items():
            getter = spec[name]
            if callable(getter):
                actual = getter(record)
            else:
                actual = record.get(getter)
            if actual is None or str(actual) != value:
                keep = False
                break
        if keep:
            out.append(record)
    return out
