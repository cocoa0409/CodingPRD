"""Complaint intake, screening, assignment and the substantiation cascade (PRD §3.7)."""

from flask import Blueprint, request

import calc
import clock
import constants as K
import derive
import envelope
import helpers
import serialize
import store
import validate
from auth import authenticate, require_complaint_owner
from errors import ApiError
from validate import F

bp = Blueprint("complaints", __name__)

COMPLAINT_READERS = (
    "AgencyAdmin",
    "LicensingSupervisor",
    "ComplaintIntakeSpecialist",
    "ComplaintInvestigator",
)

CLIENT_INTAKE_CHANNELS = tuple(c for c in K.INTAKE_CHANNELS if c != "AGENCY_INCIDENT")


def new_complaint(
    provider,
    intake_channel,
    allegation_category,
    affected_age_group,
    narrative,
    alleged_serious_harm,
    complainant_name,
    anonymous,
    priority,
    status,
    screened_at=None,
):
    received_at = clock.now_dt()
    due = clock.add_days(received_at, K.DETERMINATION_DAYS[priority])
    record = {
        "provider_id": provider["id"],
        "assigned_investigator_id": None,
        "intake_channel": intake_channel,
        "allegation_category": allegation_category,
        "alleged_serious_harm": alleged_serious_harm,
        "affected_age_group": affected_age_group,
        "complainant_name": complainant_name,
        "anonymous": anonymous,
        "narrative": narrative,
        "priority": priority,
        "status": status,
        "received_at": clock.fmt(received_at),
        "screened_at": screened_at,
        "investigation_due_at": clock.fmt(due),
        "determination": None,
        "determined_at": None,
        "timeliness_flag": None,
        "closure_note": None,
    }
    return store.create(store.complaints, record)


@bp.post("/licensing/complaints")
def intake_complaint():
    authenticate(("ComplaintIntakeSpecialist", "AgencyAdmin"))
    vals = validate.body(
        [
            F("provider_id", "string", required=True),
            F("intake_channel", "enum", required=True, values=K.INTAKE_CHANNELS),
            F(
                "allegation_category",
                "enum",
                required=True,
                values=K.ALLEGATION_CATEGORIES,
            ),
            F("affected_age_group", "enum", required=True, values=K.AGE_GROUPS),
            F("narrative", "string", required=True, min_len=1, max_len=2000, not_blank=True),
            F("alleged_serious_harm", "bool"),
            F("complainant_name", "string", min_len=1, max_len=200, not_blank=True),
            F("anonymous", "bool"),
        ]
    )
    if vals["intake_channel"] not in CLIENT_INTAKE_CHANNELS:
        raise ApiError(
            "ERR_INVALID_ENUM_VALUE",
            "AGENCY_INCIDENT is reserved for agency-initiated investigations.",
        )
    anonymous = bool(vals.get("anonymous", False))
    if anonymous and vals.get("complainant_name") is not None:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "An anonymous complaint may not carry a complainant_name.",
        )
    provider = helpers.need("provider", vals["provider_id"])
    priority = calc.complaint_priority(
        vals["allegation_category"], vals["affected_age_group"], provider["license_status"]
    )
    record = new_complaint(
        provider,
        vals["intake_channel"],
        vals["allegation_category"],
        vals["affected_age_group"],
        vals["narrative"],
        bool(vals.get("alleged_serious_harm", False)),
        vals.get("complainant_name"),
        anonymous,
        priority,
        "RECEIVED",
    )
    return envelope.created(serialize.complaint(record))


@bp.get("/licensing/complaints")
def list_complaints():
    authenticate(COMPLAINT_READERS)
    limit, offset = envelope.pagination(request.args)
    status = validate.query_enum("status", K.COMPLAINT_STATUSES)
    priority = validate.query_enum("priority", K.PRIORITIES)
    determination = validate.query_enum("determination", K.DETERMINATIONS)
    provider_id = validate.query_str("provider_id")
    investigator_id = validate.query_str("assigned_investigator_id")
    rows = store.ordered(store.complaints)
    if provider_id is not None:
        rows = [r for r in rows if r["provider_id"] == provider_id]
    if investigator_id is not None:
        rows = [r for r in rows if r.get("assigned_investigator_id") == investigator_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if priority is not None:
        rows = [r for r in rows if r["priority"] == priority]
    if determination is not None:
        rows = [r for r in rows if r.get("determination") == determination]
    return helpers.listing(rows, serialize.complaint, limit, offset)


@bp.get("/licensing/complaints/<complaint_id>")
def read_complaint(complaint_id):
    authenticate(COMPLAINT_READERS)
    record = helpers.need("complaint", complaint_id)
    return envelope.ok(serialize.complaint(record))


@bp.post("/licensing/complaints/<complaint_id>/screen")
def screen_complaint(complaint_id):
    authenticate(("ComplaintIntakeSpecialist",))
    vals = validate.body(
        [F("decision", "enum", required=True, values=K.SCREEN_DECISIONS)]
    )
    complaint = helpers.need("complaint", complaint_id)
    if complaint["status"] != "RECEIVED":
        raise ApiError("ERR_INVALID_COMPLAINT_STATE", "The complaint is not RECEIVED.")
    if vals["decision"] == "SCREEN_OUT" and complaint["priority"] == "P1":
        raise ApiError(
            "ERR_P1_CANNOT_BE_SCREENED_OUT", "A P1 allegation can never be screened out."
        )
    complaint["status"] = (
        "SCREENED_IN" if vals["decision"] == "SCREEN_IN" else "SCREENED_OUT"
    )
    complaint["screened_at"] = clock.now()
    store.touch(complaint)
    return envelope.ok(serialize.complaint(complaint))


@bp.post("/licensing/complaints/<complaint_id>/assign-investigator")
def assign_investigator(complaint_id):
    authenticate(("LicensingSupervisor",))
    vals = validate.body([F("investigator_id", "string", required=True)])
    complaint = helpers.need("complaint", complaint_id)
    inspector = helpers.need("inspector", vals["investigator_id"])
    if derive.inspector_finalized_recently(inspector["id"], complaint["provider_id"]):
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "That inspector finalized an inspection of this provider within 12 months.",
        )
    if complaint["status"] != "SCREENED_IN":
        raise ApiError("ERR_INVALID_COMPLAINT_STATE", "The complaint is not SCREENED_IN.")
    if inspector["status"] != "ACTIVE":
        raise ApiError("ERR_INSPECTOR_ON_LEAVE", "The inspector is on leave.")
    complaint["status"] = "UNDER_INVESTIGATION"
    complaint["assigned_investigator_id"] = inspector["id"]
    store.touch(complaint)
    return envelope.ok(serialize.complaint(complaint))


@bp.post("/licensing/complaints/<complaint_id>/determination")
def record_determination(complaint_id):
    user_id, role = authenticate(("ComplaintInvestigator",))
    vals = validate.body(
        [F("determination", "enum", required=True, values=K.DETERMINATIONS)]
    )
    complaint = helpers.need("complaint", complaint_id)
    require_complaint_owner(role, user_id, complaint)
    if complaint["status"] != "UNDER_INVESTIGATION":
        raise ApiError(
            "ERR_INVALID_COMPLAINT_STATE", "The complaint is not UNDER_INVESTIGATION."
        )
    determination = vals["determination"]
    provider = store.providers[complaint["provider_id"]]

    target = None
    item = None
    if determination == "SUBSTANTIATED":
        candidates = [
            i
            for i in store.ordered(store.inspections)
            if i.get("complaint_id") == complaint["id"] and i["status"] == "FINALIZED"
        ]
        target = derive.latest_finalized(candidates)
        if target is None:
            raise ApiError(
                "ERR_COMPLAINT_INSPECTION_REQUIRED",
                "No finalized inspection of this complaint can carry the citation.",
            )
        code = K.COMPLAINT_CATEGORY_CHECKLIST_CODE[complaint["allegation_category"]]
        item = store.checklist_by_code(code)
        if item is None:
            raise ApiError(
                "ERR_CHECKLIST_ITEM_NOT_FOUND",
                "The catalog has no checklist item with code %s." % code,
            )

    determined_at = clock.now_dt()
    complaint["status"] = "DETERMINED"
    complaint["determination"] = determination
    complaint["determined_at"] = clock.fmt(determined_at)
    complaint["timeliness_flag"] = (
        "ON_TIME"
        if determined_at <= clock.at(complaint["investigation_due_at"])
        else "LATE"
    )
    store.touch(complaint)

    if determination != "SUBSTANTIATED":
        derive.recompute_provider(provider)
        store.touch(provider)
        return envelope.ok(serialize.complaint(complaint))

    derive.create_violation(
        target,
        item,
        complaint["affected_age_group"],
        complaint["narrative"],
        item["default_severity"],
        auto_generated=True,
        status="CORRECTION_PENDING",
        with_due_date=True,
    )
    derive.recompute_violation_count(target)
    derive.recompute_final_score(target)
    store.touch(target)
    derive.recompute_provider(provider)
    derive.auto_propose_enforcement(provider, target)
    store.touch(provider)
    return envelope.ok(serialize.complaint(complaint))


@bp.post("/licensing/complaints/<complaint_id>/close")
def close_complaint(complaint_id):
    authenticate(("LicensingSupervisor",))
    vals = validate.body(
        [F("closure_note", "string", required=True, min_len=1, max_len=2000, not_blank=True)]
    )
    complaint = helpers.need("complaint", complaint_id)
    if complaint["status"] != "DETERMINED":
        raise ApiError("ERR_INVALID_COMPLAINT_STATE", "The complaint is not DETERMINED.")
    complaint["status"] = "CLOSED"
    complaint["closure_note"] = vals["closure_note"]
    store.touch(complaint)
    return envelope.ok(serialize.complaint(complaint))
