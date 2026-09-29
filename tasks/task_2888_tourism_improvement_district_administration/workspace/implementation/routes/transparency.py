"""Transparency records (PRD 3.9)."""
from flask import Blueprint

import config
import envelope
import serialize
import store
import validate
from auth import authenticate
from errors import fail
from routes.common import ADMIN, AUDITOR, BOARD, OPERATOR, VIEWER
from services import core
from store import put, touch

bp = Blueprint("transparency", __name__)


@bp.get("/transparency-records/<record_id>")
def read_record(record_id):
    authenticate([VIEWER, ADMIN, BOARD, AUDITOR, OPERATOR], public=True)
    return envelope.ok(serialize.record(validate.record(record_id)))


@bp.post("/transparency-records")
def create_record():
    actor = authenticate([ADMIN])
    b = validate.body()
    district_id = validate.id_ref(b, "district_id")
    record_type = validate.enum(b, "record_type", config.RECORD_TYPES)
    fiscal_year = validate.integer(b, "fiscal_year", minimum=2020, maximum=2050)
    scheduled_for = validate.instant(b, "scheduled_for")
    required_by = validate.instant(b, "required_by")

    district = validate.district(district_id)
    if district["status"] in config.DISTRICT_TERMINAL:
        fail("ERR_DISTRICT_NOT_ACTIVE",
             "A %s district accepts no transparency activity." % district["status"])

    if record_type == "PUBLIC_MEETING":
        for other in core.records_of_district(district["id"]):
            if other["record_type"] != "PUBLIC_MEETING":
                continue
            gap = abs((other["scheduled_for"] - scheduled_for.dt).total_seconds())
            if int(gap // 86400) < config.MIN_MEETING_SEPARATION_DAYS:
                fail("ERR_MEETING_SEPARATION_VIOLATION",
                     "Two public meetings must be at least %d whole days apart."
                     % config.MIN_MEETING_SEPARATION_DAYS)

    rec = store.new_record("record")
    rec.update({
        "district_id": district["id"],
        "record_type": record_type,
        "fiscal_year": fiscal_year,
        "status": "SCHEDULED",
        "noticed_on": None,
        "completed_on": None,
        "published_on": None,
        "document_reference": None,
        "engaged_by_user_id": actor.user_id,
    })
    validate.assign(rec, "scheduled_for", scheduled_for)
    validate.assign(rec, "required_by", required_by)
    put("records", rec)
    return envelope.created(serialize.record(rec))


@bp.post("/transparency-records/<record_id>/advance")
def advance_record(record_id):
    actor = authenticate([ADMIN])
    b = validate.body()
    to_status = validate.enum(b, "to_status", config.ADVANCE_STATUSES)
    document_reference = validate.text(b, "document_reference", required=False)
    if to_status == "PUBLISHED" and (document_reference is None
                                     or not document_reference.strip()):
        fail("ERR_INVALID_REQUEST",
             "document_reference is required to publish a transparency record.")

    rec = validate.record(record_id)
    now = store.clock()

    if to_status == "NOTICED":
        if rec["status"] != "SCHEDULED":
            fail("ERR_INVALID_STATE_TRANSITION",
                 "Only a SCHEDULED record may be noticed.")
        if store.whole_days_between(now, rec["scheduled_for"]) < config.MIN_NOTICE_DAYS:
            fail("ERR_MEETING_NOTICE_TOO_LATE",
                 "Notice must be posted at least %d whole days ahead." % config.MIN_NOTICE_DAYS)
        rec["status"] = "NOTICED"
        rec["noticed_on"] = now
        rec["_raw"].pop("noticed_on", None)

    elif to_status == "COMPLETED":
        if rec["status"] != "NOTICED":
            fail("ERR_INVALID_STATE_TRANSITION",
                 "Only a NOTICED record may be completed.")
        if now < rec["scheduled_for"]:
            fail("ERR_INVALID_STATE_TRANSITION",
                 "A record may not be completed before its scheduled instant.")
        if (rec["record_type"] == "FINANCIAL_AUDIT"
                and actor.user_id == rec["engaged_by_user_id"]):
            fail("ERR_SEGREGATION_OF_DUTIES",
                 "The user who engaged the audit may not record its completion.")
        rec["status"] = "COMPLETED"
        rec["completed_on"] = now
        rec["_raw"].pop("completed_on", None)

    else:
        if rec["status"] != "COMPLETED":
            fail("ERR_INVALID_STATE_TRANSITION",
                 "Only a COMPLETED record may be published.")
        if (rec["record_type"] == "FINANCIAL_AUDIT"
                and actor.user_id == rec["engaged_by_user_id"]):
            fail("ERR_SEGREGATION_OF_DUTIES",
                 "The user who engaged the audit may not publish it.")
        rec["status"] = "PUBLISHED"
        rec["published_on"] = now
        rec["_raw"].pop("published_on", None)
        rec["document_reference"] = document_reference

    touch(rec)
    core.rederive_transparency_standing(store.state.districts[rec["district_id"]])
    return envelope.ok(serialize.record(rec))
