"""Quality assurance inspections and the cure cycle (PRD 3.8)."""

from flask import Blueprint

import calc
import domain
import envelope
import store
import validation
from auth import ALL_ROLES, ROLE_BSD, ROLE_FDM, ROLE_OWNER, ROLE_QA, authenticate
from common import add_days, fmt_instant, parse_instant
from errors import ApiError
from serialize import dump, dump_all
from store import touch

bp = Blueprint("qa", __name__)

INSPECTION_SPECS = [
    {"name": "cleanliness_score", "type": "integer", "required": True, "minimum": 0,
     "maximum": 100},
    {"name": "condition_score", "type": "integer", "required": True, "minimum": 0,
     "maximum": 100},
    {"name": "brand_standard_score", "type": "integer", "required": True, "minimum": 0,
     "maximum": 100},
    {"name": "guest_experience_score", "type": "integer", "required": True,
     "minimum": 0, "maximum": 100},
    {"name": "critical_defect_count", "type": "integer", "required": True, "minimum": 0,
     "maximum": 20},
    {"name": "life_safety_defect", "type": "boolean", "required": True},
]


@bp.post("/agreements/<agreement_id>/qa-inspections")
def score_inspection(agreement_id):
    principal = authenticate((ROLE_QA,))
    agreement = store.get_agreement(agreement_id)
    payload = validation.body()
    fields = validation.take(payload, INSPECTION_SPECS)
    if agreement["status"] != "OPEN":
        raise ApiError("ERR_AGREEMENT_NOT_OPEN")
    stamp = domain.now()
    last = agreement["last_inspection_at"]
    if last is not None:
        earliest = fmt_instant(
            add_days(parse_instant(last), calc.MIN_INSPECTION_GAP_DAYS)
        )
        if stamp < earliest:
            raise ApiError("ERR_INSPECTION_TOO_SOON")

    weighted, total, grade, cure_days = calc.qa_scores(
        fields["cleanliness_score"],
        fields["condition_score"],
        fields["brand_standard_score"],
        fields["guest_experience_score"],
        fields["critical_defect_count"],
        fields["life_safety_defect"],
    )
    row = store.new_row("inspection")
    row["agreement_id"] = agreement["id"]
    row["inspection_at"] = stamp
    for spec in INSPECTION_SPECS:
        row[spec["name"]] = fields[spec["name"]]
    row["weighted_score"] = weighted
    row["total_score"] = total
    row["grade"] = grade
    row["cure_period_days"] = cure_days
    row["cure_deadline"] = (
        None
        if cure_days is None
        else fmt_instant(add_days(parse_instant(stamp), cure_days))
    )
    row["status"] = "CLOSED" if grade == "PASS" else "CURE_PENDING"
    row["inspector_user_id"] = principal.user_id
    row["cure_reviewer_user_id"] = None
    row["cure_evidence"] = None
    row["cure_submitted_at"] = None
    row["cure_reviewed_at"] = None
    row["review_notes"] = None
    store.inspections[row["id"]] = row

    domain.refresh_last_inspection(agreement)
    if grade in ("CONDITIONAL", "FAIL"):
        domain.set_compliance(agreement, "CURE_PERIOD")
    touch(agreement)
    return envelope.created(dump(row))


@bp.get("/agreements/<agreement_id>/qa-inspections")
def list_inspections(agreement_id):
    principal = authenticate(ALL_ROLES)
    agreement = store.get_agreement(agreement_id)
    domain.require_agreement_owner(principal, agreement)
    limit, offset = envelope.pagination()
    grade = validation.query_filter("grade")
    rows = store.ordered(
        store.inspections,
        lambda i: i["agreement_id"] == agreement["id"]
        and (grade is None or i["grade"] == grade),
    )
    return envelope.listing(
        dump_all(envelope.window(rows, limit, offset)), limit, offset, len(rows)
    )


@bp.post("/qa-inspections/<inspection_id>/cure-submission")
def submit_cure(inspection_id):
    principal = authenticate((ROLE_OWNER,))
    inspection = store.get_inspection(inspection_id)
    agreement = store.agreements.get(inspection["agreement_id"])
    domain.require_agreement_owner(principal, agreement)
    payload = validation.body()
    fields = validation.take(
        payload,
        [{"name": "cure_evidence", "type": "string", "required": True, "min_len": 1}],
    )
    if inspection["status"] != "CURE_PENDING":
        raise ApiError("ERR_INSPECTION_STAGE_INVALID")
    stamp = domain.now()
    if inspection["cure_deadline"] is not None and stamp > inspection["cure_deadline"]:
        raise ApiError("ERR_CURE_WINDOW_EXPIRED")

    inspection["status"] = "CURE_SUBMITTED"
    inspection["cure_evidence"] = fields["cure_evidence"]
    inspection["cure_submitted_at"] = stamp
    touch(inspection)
    return envelope.ok(dump(inspection))


@bp.post("/qa-inspections/<inspection_id>/cure-review")
def review_cure(inspection_id):
    principal = authenticate((ROLE_QA,))
    inspection = store.get_inspection(inspection_id)
    payload = validation.body()
    fields = validation.take(
        payload,
        [
            {"name": "outcome", "type": "enum", "required": True,
             "values": ("PASS", "FAIL")},
            {"name": "review_notes", "type": "string", "required": True, "min_len": 1},
        ],
    )
    if inspection["status"] != "CURE_SUBMITTED":
        raise ApiError("ERR_INSPECTION_STAGE_INVALID")
    if principal.user_id == inspection["inspector_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    stamp = domain.now()
    inspection["review_notes"] = fields["review_notes"]
    inspection["cure_reviewed_at"] = stamp
    inspection["cure_reviewer_user_id"] = principal.user_id
    agreement = store.agreements.get(inspection["agreement_id"])

    if fields["outcome"] == "PASS":
        inspection["status"] = "CURE_PASSED"
        touch(inspection)
        if agreement is not None:
            domain.set_compliance(agreement, "COMPLIANT")
            agreement["consecutive_qa_failure_count"] = 0
            if (
                agreement["channel_status"] == "SUSPENDED"
                and agreement["status"] == "OPEN"
            ):
                agreement["channel_status"] = "CONNECTED"
            touch(agreement)
        return envelope.ok(dump(inspection))

    inspection["status"] = "CURE_FAILED"
    touch(inspection)
    if agreement is not None:
        count = agreement["consecutive_qa_failure_count"] + 1
        agreement["consecutive_qa_failure_count"] = count
        if count >= calc.QA_FAILURE_TERMINATION_THRESHOLD:
            domain.set_compliance(agreement, "TERMINATION_ELIGIBLE")
        else:
            domain.set_compliance(agreement, "DEFAULT_NOTICE")
            agreement["default_notice_issued_at"] = stamp
        if agreement["channel_status"] == "CONNECTED":
            agreement["channel_status"] = "SUSPENDED"
        touch(agreement)
    return envelope.ok(dump(inspection))
