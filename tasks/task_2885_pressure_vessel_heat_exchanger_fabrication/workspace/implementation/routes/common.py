"""Helpers shared by every route module."""

import db
import response
import validation
from errors import fail
from services import derive

# Path existence (ladder step 5) and body-reference existence (step 6) share
# these store / error-id pairings.
NOT_FOUND = {
    "personnel": "ERR_PERSONNEL_NOT_FOUND",
    "certificates": "ERR_CERTIFICATE_NOT_FOUND",
    "audits": "ERR_AUDIT_NOT_FOUND",
    "jobs": "ERR_JOB_NOT_FOUND",
    "calculations": "ERR_CALCULATION_NOT_FOUND",
    "heats": "ERR_HEAT_NOT_FOUND",
    "parts": "ERR_PART_NOT_FOUND",
    "wps": "ERR_WPS_NOT_FOUND",
    "qualifications": "ERR_QUALIFICATION_NOT_FOUND",
    "welds": "ERR_WELD_NOT_FOUND",
    "exams": "ERR_EXAM_NOT_FOUND",
    "nonconformances": "ERR_NONCONFORMANCE_NOT_FOUND",
    "batches": "ERR_BATCH_NOT_FOUND",
    "tests": "ERR_TEST_NOT_FOUND",
    "reports": "ERR_REPORT_NOT_FOUND",
}


def must_exist(store_name, rec_id):
    record = db.get(store_name, rec_id)
    if record is None:
        fail(NOT_FOUND[store_name], "No such record: %s." % rec_id)
    return record


VIEWS = {
    "certificates": derive.certificate_view,
    "jobs": derive.job_view,
    "parts": derive.part_view,
    "qualifications": derive.qualification_view,
    "reports": derive.report_view,
}


def view(store_name, record):
    return VIEWS.get(store_name, db.public)(record)


def one(store_name, record, status=200):
    return response.object_response(view(store_name, record), status)


def many(store_name, records):
    limit, offset = validation.pagination()
    total = len(records)
    window = records[offset:offset + limit]
    return response.array_response([view(store_name, r) for r in window],
                                   limit, offset, total)


def created(store_name, record):
    return one(store_name, record, 201)


def apply_filters(records, names):
    """Conjunctive equality filters on the declared query parameters."""
    active = validation.filters(*names)
    if not active:
        return records
    out = []
    for record in records:
        keep = True
        for name, wanted in active.items():
            stored = record.get(name)
            if stored is None or str(stored) != wanted:
                keep = False
                break
        if keep:
            out.append(record)
    return out


def listing(store_name, names, derived_getters=None):
    """List endpoint body: pagination shape gate, then conjunctive filters."""
    limit, offset = validation.pagination()
    records = db.all_of(store_name)
    active = validation.filters(*names)
    if active:
        kept = []
        for record in records:
            keep = True
            for name, wanted in active.items():
                if derived_getters and name in derived_getters:
                    stored = derived_getters[name](record)
                else:
                    stored = record.get(name)
                if stored is None or str(stored) != wanted:
                    keep = False
                    break
            if keep:
                kept.append(record)
        records = kept
    total = len(records)
    window = records[offset:offset + limit]
    return response.array_response([view(store_name, r) for r in window],
                                   limit, offset, total)
