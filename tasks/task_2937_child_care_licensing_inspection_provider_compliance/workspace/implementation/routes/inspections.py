"""Scheduling a visit and walking it to finalization (PRD §3.4)."""

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
from auth import authenticate, require_inspection_owner
from errors import ApiError
from validate import F

bp = Blueprint("inspections", __name__)

INSPECTION_READERS = (
    "AgencyAdmin",
    "Applicant",
    "LicensingSupervisor",
    "LicensingInspector",
    "ComplaintInvestigator",
    "PublicPortalReader",
)


def _active_inspections(predicate):
    return [
        i
        for i in store.ordered(store.inspections)
        if i["status"] in K.ACTIVE_INSPECTION_STATUSES and predicate(i)
    ]


@bp.post("/licensing/inspections")
def schedule_inspection():
    authenticate(("LicensingSupervisor", "AgencyAdmin"))
    vals = validate.body(
        [
            F("provider_id", "string", required=True),
            F("inspector_id", "string", required=True),
            F("inspection_type", "enum", required=True, values=K.INSPECTION_TYPES),
            F("scheduled_for", "instant", required=True),
            F(
                "target_age_groups",
                "enum_array",
                required=True,
                values=K.AGE_GROUPS,
                non_empty=True,
                unique=True,
            ),
            F("duration_minutes", "int", min_val=30, max_val=480),
            F("complaint_id", "string"),
        ]
    )
    provider = helpers.need("provider", vals["provider_id"])
    inspector = helpers.need("inspector", vals["inspector_id"])
    complaint = None
    if vals.get("complaint_id") is not None:
        complaint = helpers.need("complaint", vals["complaint_id"])

    duration = vals.get("duration_minutes", 120)
    start = clock.parse_instant(vals["scheduled_for"])
    end = clock.add_minutes(start, duration)

    for other in _active_inspections(lambda i: i["inspector_id"] == inspector["id"]):
        other_start = clock.at(other["scheduled_for"])
        other_end = clock.at(other["visit_window_end"])
        if start < other_end and other_start < end:
            raise ApiError(
                "ERR_INSPECTOR_DOUBLE_BOOKED",
                "The inspector already has a visit overlapping this window.",
            )
    buffer_minutes = K.PROVIDER_VISIT_BUFFER_MINUTES
    for other in _active_inspections(lambda i: i["provider_id"] == provider["id"]):
        other_start = clock.add_minutes(clock.at(other["scheduled_for"]), -buffer_minutes)
        other_end = clock.add_minutes(clock.at(other["visit_window_end"]), buffer_minutes)
        padded_start = clock.add_minutes(start, -buffer_minutes)
        padded_end = clock.add_minutes(end, buffer_minutes)
        if padded_start <= other_end and other_start <= padded_end:
            raise ApiError(
                "ERR_PROVIDER_VISIT_BUFFER_CONFLICT",
                "Another visit at this site is within the 60-minute buffer.",
            )
    if start <= clock.now_dt():
        raise ApiError(
            "ERR_SCHEDULE_IN_PAST", "scheduled_for must be strictly after the current instant."
        )
    if not set(vals["target_age_groups"]).issubset(set(inspector["certified_age_groups"])):
        raise ApiError(
            "ERR_INSPECTOR_NOT_CERTIFIED_FOR_AGE_GROUP",
            "The inspector is not certified for every target age group.",
        )
    if inspector["status"] != "ACTIVE":
        raise ApiError("ERR_INSPECTOR_ON_LEAVE", "The inspector is on leave.")
    same_day = 0
    for other in _active_inspections(lambda i: i["inspector_id"] == inspector["id"]):
        if clock.at(other["scheduled_for"]).date() == start.date():
            same_day += 1
    if same_day >= inspector["max_daily_visits"]:
        raise ApiError(
            "ERR_INSPECTOR_DAILY_LIMIT_REACHED",
            "The inspector has reached the daily visit ceiling for that date.",
        )
    if vals["inspection_type"] == "COMPLAINT":
        if complaint is None:
            raise ApiError(
                "ERR_INVALID_REQUEST", "A COMPLAINT visit must name a complaint_id."
            )
        if complaint["provider_id"] != provider["id"]:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "The named complaint belongs to a different provider.",
            )
    elif complaint is not None:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "complaint_id is only accepted on a COMPLAINT visit.",
        )

    record = {
        "provider_id": provider["id"],
        "inspector_id": inspector["id"],
        "complaint_id": complaint["id"] if complaint else None,
        "inspection_type": vals["inspection_type"],
        "status": "SCHEDULED",
        "scheduled_for": clock.fmt(start),
        "duration_minutes": duration,
        "visit_window_end": clock.fmt(end),
        "started_at": None,
        "submitted_at": None,
        "finalized_at": None,
        "target_age_groups": list(vals["target_age_groups"]),
        "age_groups_observed": None,
        "outcome": None,
        "preliminary_compliance_score": None,
        "final_compliance_score": None,
        "raw_deduction_points": None,
        "violation_count": 0,
        "cap_required": False,
        "reopen_count": 0,
    }
    store.create(store.inspections, record)
    derive.recompute_inspector_visit_count(inspector)
    return envelope.created(serialize.inspection(record))


@bp.get("/licensing/inspections")
def list_inspections():
    authenticate(INSPECTION_READERS)
    limit, offset = envelope.pagination(request.args)
    status = validate.query_enum("status", K.INSPECTION_STATUSES)
    inspection_type = validate.query_enum("inspection_type", K.INSPECTION_TYPES)
    provider_id = validate.query_str("provider_id")
    inspector_id = validate.query_str("inspector_id")
    complaint_id = validate.query_str("complaint_id")
    rows = store.ordered(store.inspections)
    if provider_id is not None:
        rows = [r for r in rows if r["provider_id"] == provider_id]
    if inspector_id is not None:
        rows = [r for r in rows if r["inspector_id"] == inspector_id]
    if complaint_id is not None:
        rows = [r for r in rows if r.get("complaint_id") == complaint_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if inspection_type is not None:
        rows = [r for r in rows if r["inspection_type"] == inspection_type]
    return helpers.listing(rows, serialize.inspection, limit, offset)


@bp.get("/licensing/inspections/<inspection_id>")
def read_inspection(inspection_id):
    authenticate(INSPECTION_READERS)
    record = helpers.need("inspection", inspection_id)
    return envelope.ok(serialize.inspection(record))


@bp.post("/licensing/inspections/<inspection_id>/start")
def start_inspection(inspection_id):
    user_id, role = authenticate(("LicensingInspector",))
    validate.body([])
    inspection = helpers.need("inspection", inspection_id)
    require_inspection_owner(role, user_id, inspection)
    if inspection["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_INSPECTION_STATE", "The visit is not SCHEDULED.")
    inspector = store.inspectors[inspection["inspector_id"]]
    if inspector["status"] != "ACTIVE":
        raise ApiError("ERR_INSPECTOR_ON_LEAVE", "The inspector is on leave.")
    inspection["status"] = "IN_PROGRESS"
    inspection["started_at"] = clock.now()
    store.touch(inspection)
    return envelope.ok(serialize.inspection(inspection))


@bp.post("/licensing/inspections/<inspection_id>/submit-for-review")
def submit_for_review(inspection_id):
    user_id, role = authenticate(("LicensingInspector",))
    vals = validate.body(
        [
            F("outcome", "enum", required=True, values=K.INSPECTION_OUTCOMES),
            F(
                "age_groups_observed",
                "enum_array",
                required=True,
                values=K.AGE_GROUPS,
                non_empty=True,
                unique=True,
            ),
        ]
    )
    inspection = helpers.need("inspection", inspection_id)
    require_inspection_owner(role, user_id, inspection)
    if inspection["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_INSPECTION_STATE", "The visit is not IN_PROGRESS.")
    inspector = store.inspectors[inspection["inspector_id"]]
    if not set(vals["age_groups_observed"]).issubset(set(inspector["certified_age_groups"])):
        raise ApiError(
            "ERR_INSPECTOR_NOT_CERTIFIED_FOR_AGE_GROUP",
            "The inspector is not certified for every observed age group.",
        )
    live = [
        v
        for v in store.inspection_violations(inspection["id"])
        if v["status"] != "VACATED"
    ]
    if any(v["severity"] == "CRITICAL" for v in live):
        if vals["outcome"] != "FAIL":
            raise ApiError(
                "ERR_OUTCOME_SEVERITY_MISMATCH",
                "A critical citation requires the outcome FAIL.",
            )
    elif not live:
        if vals["outcome"] != "PASS":
            raise ApiError(
                "ERR_OUTCOME_SEVERITY_MISMATCH",
                "An inspection with no citation requires the outcome PASS.",
            )
    inspection["status"] = "PENDING_REVIEW"
    inspection["submitted_at"] = clock.now()
    inspection["outcome"] = vals["outcome"]
    inspection["age_groups_observed"] = list(vals["age_groups_observed"])
    store.touch(inspection)
    return envelope.ok(serialize.inspection(inspection))


@bp.post("/licensing/inspections/<inspection_id>/reopen")
def reopen_inspection(inspection_id):
    authenticate(("LicensingSupervisor",))
    validate.body([])
    inspection = helpers.need("inspection", inspection_id)
    if inspection["status"] != "PENDING_REVIEW":
        raise ApiError("ERR_INVALID_INSPECTION_STATE", "The visit is not PENDING_REVIEW.")
    if inspection["reopen_count"] >= K.INSPECTION_MAX_REOPENS:
        raise ApiError(
            "ERR_INVALID_INSPECTION_STATE", "The reopen allowance is exhausted."
        )
    inspection["status"] = "IN_PROGRESS"
    inspection["reopen_count"] += 1
    inspection["outcome"] = None
    inspection["age_groups_observed"] = None
    inspection["submitted_at"] = None
    store.touch(inspection)
    return envelope.ok(serialize.inspection(inspection))


@bp.post("/licensing/inspections/<inspection_id>/finalize")
def finalize_inspection(inspection_id):
    authenticate(("LicensingSupervisor",))
    validate.body([])
    inspection = helpers.need("inspection", inspection_id)
    if inspection["status"] != "PENDING_REVIEW":
        raise ApiError("ERR_INVALID_INSPECTION_STATE", "The visit is not PENDING_REVIEW.")
    provider = store.providers[inspection["provider_id"]]
    if inspection["inspection_type"] == "INITIAL" and not derive.provider_clearance_complete(
        provider
    ):
        raise ApiError("ERR_CLEARANCE_INCOMPLETE", "Not every attached person is cleared.")

    inspection["status"] = "FINALIZED"
    inspection["finalized_at"] = clock.now()
    for violation in store.inspection_violations(inspection["id"]):
        if violation["status"] == "CITED":
            violation["status"] = "CORRECTION_PENDING"
            violation["correction_due_date"] = derive.correction_due_date(violation)
            store.touch(violation)
    derive.recompute_violation_count(inspection)
    inspection["cap_required"] = inspection["violation_count"] > 0
    derive.recompute_preliminary_score(inspection)
    derive.recompute_final_score(inspection)
    derive.recompute_provider_points(provider)
    derive.recompute_provider_complaint_counts(provider)
    derive.recompute_provider_risk(provider)
    if (
        inspection["inspection_type"] == "INITIAL"
        and inspection["outcome"] in ("PASS", "CONDITIONAL_PASS")
        and provider["application_status"] == "CHECKS_CLEARED"
    ):
        provider["application_status"] = "INITIAL_INSPECTION_PASSED"
    store.touch(inspection)
    store.touch(provider)
    derive.recompute_inspector_visit_count(store.inspectors[inspection["inspector_id"]])
    return envelope.ok(serialize.inspection(inspection))


@bp.post("/licensing/inspections/<inspection_id>/void")
def void_inspection_route(inspection_id):
    authenticate(("LicensingSupervisor",))
    validate.body([])
    inspection = helpers.need("inspection", inspection_id)
    if inspection["status"] not in ("SCHEDULED", "IN_PROGRESS", "PENDING_REVIEW"):
        raise ApiError(
            "ERR_INVALID_INSPECTION_STATE", "A finalized or voided visit cannot be voided."
        )
    derive.void_inspection(inspection, "Inspection voided by the supervisor.")
    derive.recompute_provider_tracked(store.providers[inspection["provider_id"]])
    return envelope.ok(serialize.inspection(inspection))


@bp.get("/licensing/inspections/<inspection_id>/compliance-score")
def compliance_score(inspection_id):
    authenticate(("AgencyAdmin", "LicensingSupervisor", "LicensingInspector"))
    variant = validate.query_enum("variant", K.SCORE_VARIANTS) or "FINAL"
    inspection = helpers.need("inspection", inspection_id)
    rows = store.inspection_violations(inspection["id"])
    score, raw, count = calc.compliance_score(rows, variant)
    return envelope.ok(
        {
            "variant": variant,
            "compliance_score": calc.as_number(score),
            "raw_deduction": calc.as_number(raw),
            "violation_count": count,
        }
    )
