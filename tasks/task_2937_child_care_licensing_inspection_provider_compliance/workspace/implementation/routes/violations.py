"""Citations, their frozen point assessment and their dispositions (PRD §3.5, §3.6)."""

from flask import Blueprint, request

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

bp = Blueprint("violations", __name__)

VIOLATION_READERS = (
    "AgencyAdmin",
    "Applicant",
    "LicensingSupervisor",
    "LicensingInspector",
    "ComplaintInvestigator",
    "PublicPortalReader",
)

DISPOSITIONS = ("VERIFIED_CORRECTED", "UNCORRECTED", "VACATED")

DISPOSITION_ORIGINS = {
    "VERIFIED_CORRECTED": ("CORRECTION_PENDING", "UNCORRECTED"),
    "UNCORRECTED": ("CORRECTION_PENDING",),
    "VACATED": ("CITED", "CORRECTION_PENDING", "UNCORRECTED"),
}


@bp.post("/licensing/violations")
def cite_violation():
    user_id, role = authenticate(("LicensingInspector",))
    vals = validate.body(
        [
            F("inspection_id", "string", required=True),
            F("checklist_item_id", "string", required=True),
            F("primary_age_group", "enum", required=True, values=K.AGE_GROUPS),
            F("narrative", "string", required=True, min_len=1, max_len=2000, not_blank=True),
            F("severity_override", "enum", values=K.SEVERITIES),
            F("repeat_of_violation_id", "string"),
        ]
    )
    inspection = helpers.need("inspection", vals["inspection_id"])
    item = helpers.need("checklist_item", vals["checklist_item_id"])
    parent = None
    if vals.get("repeat_of_violation_id") is not None:
        parent = helpers.need("violation", vals["repeat_of_violation_id"])

    require_inspection_owner(role, user_id, inspection)
    if inspection["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_INSPECTION_STATE", "The visit is not IN_PROGRESS.")

    if parent is not None:
        parent_inspection = store.inspections[parent["inspection_id"]]
        cutoff = clock.sub_months(clock.now_dt(), K.REPEAT_LOOKBACK_MONTHS)
        if (
            parent_inspection["provider_id"] != inspection["provider_id"]
            or parent["checklist_item_id"] != item["id"]
            or clock.at(parent["created_at"]) <= cutoff
            or parent["status"] == "VACATED"
        ):
            raise ApiError(
                "ERR_REPEAT_REFERENCE_INVALID",
                "The referenced earlier citation cannot anchor a repeat chain.",
            )

    severity = vals.get("severity_override") or item["default_severity"]
    record = derive.create_violation(
        inspection,
        item,
        vals["primary_age_group"],
        vals["narrative"],
        severity,
        parent_violation=parent,
    )
    record["severity_override"] = vals.get("severity_override")

    provider = store.providers[inspection["provider_id"]]
    derive.recompute_violation_count(inspection)
    derive.recompute_preliminary_score(inspection)
    derive.recompute_final_score(inspection)
    store.touch(inspection)
    derive.recompute_provider(provider)
    store.touch(provider)
    return envelope.created(serialize.violation(record))


@bp.get("/licensing/violations")
def list_violations():
    authenticate(VIOLATION_READERS)
    limit, offset = envelope.pagination(request.args)
    status = validate.query_enum("status", K.VIOLATION_STATUSES)
    severity = validate.query_enum("severity", K.SEVERITIES)
    inspection_id = validate.query_str("inspection_id")
    checklist_item_id = validate.query_str("checklist_item_id")
    repeat_of_violation_id = validate.query_str("repeat_of_violation_id")
    rows = store.ordered(store.violations)
    if inspection_id is not None:
        rows = [r for r in rows if r["inspection_id"] == inspection_id]
    if checklist_item_id is not None:
        rows = [r for r in rows if r["checklist_item_id"] == checklist_item_id]
    if repeat_of_violation_id is not None:
        rows = [r for r in rows if r.get("repeat_of_violation_id") == repeat_of_violation_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if severity is not None:
        rows = [r for r in rows if r["severity"] == severity]
    return helpers.listing(rows, serialize.violation, limit, offset)


@bp.get("/licensing/violations/<violation_id>")
def read_violation(violation_id):
    authenticate(VIOLATION_READERS)
    record = helpers.need("violation", violation_id)
    return envelope.ok(serialize.violation(record))


@bp.post("/licensing/violations/<violation_id>/disposition")
def disposition_violation(violation_id):
    user_id, role = authenticate(("LicensingInspector", "LicensingSupervisor"))
    vals = validate.body(
        [
            F("disposition", "enum", required=True, values=DISPOSITIONS),
            F("vacated_reason", "string", min_len=1, max_len=500, not_blank=True),
        ]
    )
    disposition = vals["disposition"]
    if disposition == "VACATED" and vals.get("vacated_reason") is None:
        raise ApiError(
            "ERR_INVALID_REQUEST", "vacated_reason is required when vacating a citation."
        )
    violation = helpers.need("violation", violation_id)
    if disposition == "VACATED" and role != "LicensingSupervisor":
        raise ApiError("ERR_UNAUTHORIZED", "Only a supervisor may vacate a citation.")
    if violation["status"] not in DISPOSITION_ORIGINS[disposition]:
        raise ApiError(
            "ERR_INVALID_VIOLATION_STATE",
            "A violation in %s cannot take this disposition." % violation["status"],
        )

    violation["status"] = disposition
    if disposition == "VERIFIED_CORRECTED":
        violation["corrected_at"] = clock.now()
    elif disposition == "VACATED":
        violation["vacated_reason"] = vals["vacated_reason"]
    store.touch(violation)

    inspection = store.inspections[violation["inspection_id"]]
    provider = store.providers[inspection["provider_id"]]
    derive.recompute_violation_count(inspection)
    derive.recompute_final_score(inspection)
    store.touch(inspection)
    derive.recompute_provider(provider)
    store.touch(provider)
    return envelope.ok(serialize.violation(violation))
