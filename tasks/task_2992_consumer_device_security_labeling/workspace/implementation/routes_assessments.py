"""Conformity assessments, criterion responses and the review cycle
(PRD 3.3, 3.4)."""

from flask import Blueprint

import calc
import cascades
import lookups
import serialize
import store
import validation as v
from auth import (
    CONFORMITY_REVIEWER,
    MANUFACTURER,
    PROGRAM_ADMINISTRATOR,
    TEST_LAB_OPERATOR,
    caller,
    own,
    sod,
)
from envelope import clock_now, created, created_list, ok
from errors import ApiError, bad_request
from store import base_row, touch
from validation import ensure

bp = Blueprint("assessments", __name__)

ASSESSMENT_STATUSES = ("DRAFT", "UNDER_REVIEW", "DEFICIENT", "APPROVED", "REJECTED", "SUPERSEDED")
ROUTES = ("SELF_ATTESTATION", "THIRD_PARTY_TEST")
DECISIONS = ("APPROVED", "DEFICIENT", "REJECTED")
ASSESSMENT_READERS = (
    PROGRAM_ADMINISTRATOR,
    CONFORMITY_REVIEWER,
    MANUFACTURER,
    TEST_LAB_OPERATOR,
)


def _owned_assessment(identifier, actor):
    """Ownership compares the acting id to the assessment's product's
    manufacturer_id; an unresolvable id falls through to the existence rung."""
    assessment = store.assessments.get(identifier)
    if assessment is not None:
        product = store.product_of_assessment(assessment)
        if product is not None:
            own(product["manufacturer_id"] == actor.user_id)
    return lookups.need_assessment(identifier)


def _covered_areas(criterion_ids):
    areas = set()
    for criterion_id in criterion_ids:
        criterion = store.security_criteria.get(criterion_id)
        if criterion is not None:
            areas.add(criterion["practice_area"])
    return areas


def _require_full_coverage(criterion_ids):
    areas = _covered_areas(criterion_ids)
    for area in calc.PRACTICE_AREAS:
        ensure(
            area in areas,
            "ERR_PRACTICE_AREA_UNCOVERED",
            "Practice area %s has no criterion response." % area,
        )


def _write_provisional(assessment, tier):
    area_scores, overall, min_area, gate_applied, grade = calc.conformance_score(
        assessment, tier, calc.PROVISIONAL
    )
    assessment["provisional_area_scores"] = area_scores
    assessment["provisional_overall_score"] = overall
    assessment["decided_min_area_score"] = min_area
    assessment["gate_applied"] = gate_applied
    if assessment["route"] == "SELF_ATTESTATION":
        assessment["decided_overall_score"] = overall
        assessment["grade"] = grade


@bp.get("/labeling/assessments/<identifier>")
def read_assessment(identifier):
    caller(*ASSESSMENT_READERS)
    return ok(serialize.assessment(lookups.need_assessment(identifier)))


@bp.get("/labeling/assessments")
def list_assessments():
    caller(*ASSESSMENT_READERS)
    product_id = v.query_str("product_id")
    superseded_by = v.query_str("superseded_by_assessment_id")
    status = v.query_enum("status", ASSESSMENT_STATUSES)
    route = v.query_enum("route", ROUTES)

    rows = list(store.assessments.values())
    if product_id is not None:
        rows = [row for row in rows if row["product_id"] == product_id]
    if superseded_by is not None:
        rows = [row for row in rows if row["superseded_by_assessment_id"] == superseded_by]
    if status is not None:
        rows = [row for row in rows if row["status"] == status]
    if route is not None:
        rows = [row for row in rows if row["route"] == route]
    return lookups.listing(store.sort_created_id(rows), serialize.assessment)


@bp.get("/labeling/criterion-responses/<identifier>")
def read_criterion_response(identifier):
    caller(*ASSESSMENT_READERS)
    return ok(serialize.criterion_response(lookups.need_response(identifier)))


@bp.get("/labeling/criterion-responses")
def list_criterion_responses():
    caller(*ASSESSMENT_READERS)
    assessment_id = v.query_str("assessment_id")
    criterion_id = v.query_str("criterion_id")
    lab_verified = v.query_bool("lab_verified")

    rows = list(store.criterion_responses.values())
    if assessment_id is not None:
        rows = [row for row in rows if row["assessment_id"] == assessment_id]
    if criterion_id is not None:
        rows = [row for row in rows if row["criterion_id"] == criterion_id]
    if lab_verified is not None:
        rows = [row for row in rows if row["lab_verified"] == lab_verified]
    return lookups.listing(store.sort_created_id(rows), serialize.criterion_response)


def _validate_response_elements(body, field="responses", required=True):
    """Resolve every criterion_id (rung 5) before validating shape (rung 6)."""
    elements = v.field_array(body, field, required=required)
    if elements is None:
        return None
    for element in elements:
        if isinstance(element, dict):
            lookups.resolve_fk(element, "criterion_id", lookups.need_criterion)

    prepared = []
    for index, element in enumerate(elements):
        if not isinstance(element, dict):
            raise bad_request("Element %d of '%s' must be an object." % (index, field))
        criterion_id = v.field_str(element, "criterion_id")
        self_declared = v.field_bool(element, "self_declared_conformant")
        evidence_ref = v.field_str(element, "evidence_ref", required=False, max_len=500)
        criterion = lookups.need_criterion(criterion_id)
        prepared.append(
            {
                "criterion_id": criterion["id"],
                "self_declared_conformant": self_declared,
                "evidence_ref": evidence_ref,
            }
        )
    return prepared


@bp.post("/labeling/assessments/<identifier>/responses")
def create_criterion_responses(identifier):
    actor = caller(MANUFACTURER)
    assessment = _owned_assessment(identifier, actor)
    body = v.raw_body()

    prepared = _validate_response_elements(body)

    ensure(
        assessment["status"] == "DRAFT",
        "ERR_INVALID_ASSESSMENT_STATE",
        "Criterion responses may only be attached to a DRAFT assessment.",
    )

    existing = {row["criterion_id"] for row in store.responses_of(assessment["id"])}
    seen = set()
    for element in prepared:
        criterion_id = element["criterion_id"]
        if criterion_id in seen or criterion_id in existing:
            raise ApiError(
                "ERR_DUPLICATE_CRITERION_RESPONSE",
                "Criterion %s is answered more than once." % criterion_id,
            )
        seen.add(criterion_id)

    written = []
    for element in prepared:
        row = base_row()
        row.update(
            {
                "assessment_id": assessment["id"],
                "criterion_id": element["criterion_id"],
                "self_declared_conformant": element["self_declared_conformant"],
                "evidence_ref": element["evidence_ref"],
                "lab_result": "NOT_TESTED",
                "lab_verified": False,
            }
        )
        store.criterion_responses[row["id"]] = row
        written.append(serialize.criterion_response(row))
    return created_list(written)


@bp.post("/labeling/assessments/<identifier>/submit")
def submit_assessment(identifier):
    actor = caller(MANUFACTURER)
    assessment = _owned_assessment(identifier, actor)
    v.raw_body()

    ensure(
        assessment["status"] == "DRAFT",
        "ERR_INVALID_ASSESSMENT_STATE",
        "Only a DRAFT assessment may be submitted.",
    )
    product = store.product_of_assessment(assessment)
    ensure(
        product["eligibility_status"] == "ELIGIBLE",
        "ERR_DEVICE_CLASS_EXCLUDED",
        "The product's device category is outside the program scope.",
    )
    responses = store.responses_of(assessment["id"])
    _require_full_coverage([row["criterion_id"] for row in responses])

    tier = store.tier_of_assessment(assessment)
    assessment["status"] = "UNDER_REVIEW"
    # submitted_at records the FIRST submission and is never re-stamped.
    if assessment["submitted_at"] is None:
        assessment["submitted_at"] = clock_now()
    _write_provisional(assessment, tier)
    touch(assessment)
    return created(serialize.assessment(assessment))


@bp.post("/labeling/assessments/<identifier>/decide")
def decide_assessment(identifier):
    actor = caller(CONFORMITY_REVIEWER)
    # Segregation of duties (rung 4) precedes existence (rung 5).
    pending = store.assessments.get(identifier)
    if pending is not None:
        sod(actor.user_id != pending["last_deficiency_by_user_id"])
    assessment = lookups.need_assessment(identifier)

    body = v.raw_body()
    decision = v.field_enum(body, "decision", DECISIONS)
    reviewer_note = v.field_str(body, "reviewer_note", max_len=2000)

    ensure(
        assessment["status"] == "UNDER_REVIEW",
        "ERR_INVALID_ASSESSMENT_STATE",
        "Only an UNDER_REVIEW assessment may be decided.",
    )

    tier = store.tier_of_assessment(assessment)
    now = clock_now()

    if decision == "APPROVED":
        if assessment["route"] == "THIRD_PARTY_TEST":
            completed = [
                engagement
                for engagement in store.engagements_of_assessment(assessment["id"])
                if engagement["status"] == "COMPLETED"
            ]
            ensure(
                len(completed) > 0,
                "ERR_THIRD_PARTY_TEST_REQUIRED",
                "A third-party-route assessment needs a COMPLETED test engagement.",
            )
        decided = assessment["decided_overall_score"]
        ensure(
            decided is not None and decided >= tier["min_overall_score"],
            "ERR_SCORE_BELOW_MINIMUM",
            "The decided overall score is below the tier minimum.",
        )
        assessment["status"] = "APPROVED"
        assessment["decided_at"] = now
        assessment["decided_by_user_id"] = actor.user_id
        assessment["reviewer_note"] = reviewer_note
    elif decision == "REJECTED":
        assessment["status"] = "REJECTED"
        assessment["decided_at"] = now
        assessment["decided_by_user_id"] = actor.user_id
        assessment["reviewer_note"] = reviewer_note
    else:
        # DEFICIENT: the increment always happens; exceeding the budget rejects.
        assessment["deficiency_round"] = assessment["deficiency_round"] + 1
        assessment["decided_at"] = now
        assessment["decided_by_user_id"] = actor.user_id
        assessment["last_deficiency_by_user_id"] = actor.user_id
        assessment["reviewer_note"] = reviewer_note
        if assessment["deficiency_round"] <= tier["max_deficiency_rounds"]:
            assessment["status"] = "DEFICIENT"
        else:
            assessment["status"] = "REJECTED"

    touch(assessment)
    return created(serialize.assessment(assessment))


@bp.post("/labeling/assessments/<identifier>/resubmit")
def resubmit_assessment(identifier):
    actor = caller(MANUFACTURER)
    assessment = _owned_assessment(identifier, actor)
    body = v.raw_body()

    # Body foreign keys resolve ahead of any shape complaint.
    supplied = body.get("responses")
    if isinstance(supplied, list):
        for element in supplied:
            if isinstance(element, dict):
                lookups.resolve_fk(element, "criterion_id", lookups.need_criterion)

    resubmission_note = v.field_str(body, "resubmission_note", max_len=2000)
    prepared = _validate_response_elements(body, required=False) or []

    ensure(
        assessment["status"] == "DEFICIENT",
        "ERR_INVALID_ASSESSMENT_STATE",
        "Only a DEFICIENT assessment may be resubmitted.",
    )

    existing_rows = store.responses_of(assessment["id"])
    by_criterion = {row["criterion_id"]: row for row in existing_rows}

    # Coverage is judged on the set as it will stand after the upsert.
    prospective = set(by_criterion.keys())
    for element in prepared:
        prospective.add(element["criterion_id"])
    _require_full_coverage(prospective)

    # Only repeats *within* the supplied array are duplicates on a resubmission.
    seen = set()
    for element in prepared:
        if element["criterion_id"] in seen:
            raise ApiError(
                "ERR_DUPLICATE_CRITERION_RESPONSE",
                "Criterion %s is repeated within the supplied array." % element["criterion_id"],
            )
        seen.add(element["criterion_id"])

    # A resubmission invalidates everything the laboratory had established.
    pending_changes = {}
    for row in existing_rows:
        pending_changes[row["id"]] = {"lab_result": "NOT_TESTED", "lab_verified": False}

    for element in prepared:
        row = by_criterion.get(element["criterion_id"])
        if row is None:
            new_row = base_row()
            new_row.update(
                {
                    "assessment_id": assessment["id"],
                    "criterion_id": element["criterion_id"],
                    "self_declared_conformant": element["self_declared_conformant"],
                    "evidence_ref": element["evidence_ref"],
                    "lab_result": "NOT_TESTED",
                    "lab_verified": False,
                }
            )
            store.criterion_responses[new_row["id"]] = new_row
        else:
            pending_changes[row["id"]].update(
                {
                    "self_declared_conformant": element["self_declared_conformant"],
                    "evidence_ref": element["evidence_ref"],
                }
            )

    for response_id, changes in pending_changes.items():
        cascades.apply_changes(store.criterion_responses[response_id], changes)

    assessment["status"] = "UNDER_REVIEW"
    assessment["verified_area_scores"] = None
    assessment["verified_overall_score"] = None
    if assessment["route"] == "THIRD_PARTY_TEST":
        assessment["decided_overall_score"] = None
        assessment["grade"] = None
    _write_provisional(assessment, store.tier_of_assessment(assessment))
    touch(assessment)
    return created(serialize.assessment(assessment))
