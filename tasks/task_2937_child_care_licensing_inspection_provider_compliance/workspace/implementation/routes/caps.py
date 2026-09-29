"""Corrective action plans: submission, review, resubmission and outcome (PRD §3.6)."""

from flask import Blueprint, request

import clock
import constants as K
import derive
import envelope
import helpers
import serialize
import store
import validate
from auth import authenticate, require_provider_owner
from errors import ApiError
from validate import F

bp = Blueprint("caps", __name__)

CAP_READERS = ("AgencyAdmin", "Applicant", "LicensingSupervisor")

CAP_INPUT_FIELDS = [
    F("violation_ids", "array", required=True, non_empty=True, unique=True),
    F("narrative", "string", required=True, min_len=1, max_len=2000, not_blank=True),
    F("proposed_completion_date", "date", required=True),
]


def _resolve_violations(violation_ids):
    return [helpers.need("violation", vid) for vid in violation_ids]


def _check_agreement(violations, inspection, provider_id):
    if inspection["provider_id"] != provider_id:
        raise ApiError(
            "ERR_VIOLATION_INSPECTION_MISMATCH",
            "The inspection does not belong to the plan's provider.",
        )
    for violation in violations:
        if violation["inspection_id"] != inspection["id"] or violation["status"] == "VACATED":
            raise ApiError(
                "ERR_VIOLATION_INSPECTION_MISMATCH",
                "Every covered violation must be a live citation of the plan's inspection.",
            )


def _check_window(inspection):
    limit = clock.add_days(clock.at(inspection["finalized_at"]), K.CAP_SUBMISSION_WINDOW_DAYS)
    if clock.now_dt() > limit:
        raise ApiError(
            "ERR_CAP_WINDOW_CLOSED",
            "The ten-day plan submission window has closed for this inspection.",
        )


def _due_at(violations):
    allowance = min(K.CORRECTION_DAYS[v["severity"]] for v in violations)
    return clock.fmt(clock.add_days(clock.now_dt(), allowance))


@bp.post("/licensing/corrective-action-plans")
def submit_cap():
    user_id, role = authenticate(("Applicant",))
    vals = validate.body(
        [F("inspection_id", "string", required=True)]
        + CAP_INPUT_FIELDS
        + [F("expected_inspection_version", "int", required=True)]
    )
    inspection = helpers.need("inspection", vals["inspection_id"])
    violations = _resolve_violations(vals["violation_ids"])
    require_provider_owner(role, user_id, inspection["provider_id"])
    if vals["expected_inspection_version"] != inspection["version"]:
        raise ApiError(
            "ERR_STALE_INSPECTION_VERSION",
            "expected_inspection_version does not match the inspection's current version.",
        )
    if inspection["status"] != "FINALIZED":
        raise ApiError("ERR_INVALID_INSPECTION_STATE", "The visit is not FINALIZED.")
    _check_window(inspection)
    _check_agreement(violations, inspection, inspection["provider_id"])

    for plan in store.caps_of_inspection(inspection["id"]):
        if plan["status"] in ("SUBMITTED", "REJECTED"):
            plan["status"] = "SUPERSEDED"
            store.touch(plan)

    record = {
        "provider_id": inspection["provider_id"],
        "inspection_id": inspection["id"],
        "violation_ids": list(vals["violation_ids"]),
        "narrative": vals["narrative"],
        "proposed_completion_date": vals["proposed_completion_date"],
        "status": "SUBMITTED",
        "review_cycle_count": 1,
        "submitted_at": clock.now(),
        "reviewed_at": None,
        "approved_at": None,
        "completed_at": None,
        "due_at": _due_at(violations),
        "reviewed_by_user_id": None,
        "review_note": None,
        "expected_inspection_version": vals["expected_inspection_version"],
    }
    store.create(store.caps, record)
    store.touch(inspection)
    return envelope.created(serialize.cap(record))


@bp.get("/licensing/corrective-action-plans")
def list_caps():
    authenticate(CAP_READERS)
    limit, offset = envelope.pagination(request.args)
    status = validate.query_enum("status", K.CAP_STATUSES)
    provider_id = validate.query_str("provider_id")
    inspection_id = validate.query_str("inspection_id")
    rows = store.ordered(store.caps)
    if provider_id is not None:
        rows = [r for r in rows if r["provider_id"] == provider_id]
    if inspection_id is not None:
        rows = [r for r in rows if r["inspection_id"] == inspection_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return helpers.listing(rows, serialize.cap, limit, offset)


@bp.get("/licensing/corrective-action-plans/<cap_id>")
def read_cap(cap_id):
    authenticate(CAP_READERS)
    record = helpers.need("cap", cap_id)
    return envelope.ok(serialize.cap(record))


@bp.post("/licensing/corrective-action-plans/<cap_id>/review")
def review_cap(cap_id):
    user_id, _role = authenticate(("LicensingSupervisor",))
    vals = validate.body(
        [
            F("decision", "enum", required=True, values=K.CAP_REVIEW_DECISIONS),
            F("review_note", "string", min_len=1, max_len=2000, not_blank=True),
        ]
    )
    if vals["decision"] == "REJECT" and vals.get("review_note") is None:
        raise ApiError(
            "ERR_INVALID_REQUEST", "review_note is required when rejecting a plan."
        )
    plan = helpers.need("cap", cap_id)
    inspection = store.inspections[plan["inspection_id"]]
    if inspection["status"] != "FINALIZED":
        raise ApiError("ERR_INVALID_INSPECTION_STATE", "The visit is no longer FINALIZED.")
    if plan["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_CAP_STATE", "The plan is not SUBMITTED.")

    now = clock.now()
    plan["reviewed_at"] = now
    plan["reviewed_by_user_id"] = user_id
    if vals.get("review_note") is not None:
        plan["review_note"] = vals["review_note"]
    if vals["decision"] == "APPROVE":
        plan["status"] = "APPROVED"
        plan["approved_at"] = now
        moved = False
        for vid in plan["violation_ids"]:
            violation = store.violations.get(vid)
            if violation is not None and violation["status"] == "CITED":
                violation["status"] = "CORRECTION_PENDING"
                violation["correction_due_date"] = derive.correction_due_date(violation)
                store.touch(violation)
                moved = True
        if moved:
            derive.recompute_final_score(inspection)
            store.touch(inspection)
    else:
        plan["status"] = "REJECTED"
    store.touch(plan)
    return envelope.ok(serialize.cap(plan))


@bp.post("/licensing/corrective-action-plans/<cap_id>/resubmit")
def resubmit_cap(cap_id):
    user_id, role = authenticate(("Applicant",))
    vals = validate.body(list(CAP_INPUT_FIELDS))
    plan = helpers.need("cap", cap_id)
    violations = _resolve_violations(vals["violation_ids"])
    require_provider_owner(role, user_id, plan["provider_id"])
    if plan["status"] != "REJECTED":
        raise ApiError("ERR_INVALID_CAP_STATE", "Only a REJECTED plan can be resubmitted.")
    inspection = store.inspections[plan["inspection_id"]]
    _check_window(inspection)
    if plan["review_cycle_count"] >= K.CAP_MAX_REVIEW_CYCLES:
        raise ApiError(
            "ERR_CAP_REVIEW_CYCLE_EXHAUSTED", "The plan's review allowance is exhausted."
        )
    _check_agreement(violations, inspection, plan["provider_id"])

    plan["status"] = "SUBMITTED"
    plan["review_cycle_count"] += 1
    plan["submitted_at"] = clock.now()
    plan["violation_ids"] = list(vals["violation_ids"])
    plan["narrative"] = vals["narrative"]
    plan["proposed_completion_date"] = vals["proposed_completion_date"]
    plan["due_at"] = _due_at(violations)
    store.touch(plan)
    return envelope.ok(serialize.cap(plan))


@bp.post("/licensing/corrective-action-plans/<cap_id>/complete")
def complete_cap(cap_id):
    authenticate(("LicensingSupervisor",))
    vals = validate.body([F("result", "enum", required=True, values=K.CAP_RESULTS)])
    plan = helpers.need("cap", cap_id)
    if plan["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_CAP_STATE", "The plan is not APPROVED.")
    covered = [store.violations[vid] for vid in plan["violation_ids"] if vid in store.violations]
    if vals["result"] == "COMPLETED":
        for violation in covered:
            if violation["status"] not in ("VERIFIED_CORRECTED", "VACATED"):
                raise ApiError(
                    "ERR_INVALID_VIOLATION_STATE",
                    "Every covered violation must be corrected or vacated first.",
                )
    else:
        if clock.now_dt() <= clock.at(plan["due_at"]):
            raise ApiError(
                "ERR_CAP_WINDOW_CLOSED", "A plan cannot be failed before its own deadline."
            )

    inspection = store.inspections[plan["inspection_id"]]
    provider = store.providers[plan["provider_id"]]
    plan["status"] = vals["result"]
    plan["completed_at"] = clock.now()
    if vals["result"] == "FAILED":
        for violation in covered:
            if violation["status"] == "CORRECTION_PENDING":
                violation["status"] = "UNCORRECTED"
                store.touch(violation)
    store.touch(plan)
    derive.recompute_violation_count(inspection)
    derive.recompute_final_score(inspection)
    store.touch(inspection)
    derive.recompute_provider(provider)
    store.touch(provider)
    return envelope.ok(serialize.cap(plan))
