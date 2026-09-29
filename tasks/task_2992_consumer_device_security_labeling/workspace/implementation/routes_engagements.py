"""Accredited laboratories and third-party bench testing (PRD 3.5)."""

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
)
from envelope import clock_now, created, ok
from errors import ApiError, bad_request
from store import base_row, touch
from validation import ensure

bp = Blueprint("engagements", __name__)

ENGAGEMENT_STATUSES = ("SCHEDULED", "IN_PROGRESS", "COMPLETED", "CANCELLED")
RESERVING_STATUSES = ("SCHEDULED", "IN_PROGRESS")
ENGAGEMENT_READERS = (
    PROGRAM_ADMINISTRATOR,
    CONFORMITY_REVIEWER,
    MANUFACTURER,
    TEST_LAB_OPERATOR,
)


@bp.post("/labeling/test-engagements")
def create_test_engagement():
    caller(MANUFACTURER)
    body = v.raw_body()

    lookups.resolve_fk(body, "assessment_id", lookups.need_assessment)
    lookups.resolve_fk(body, "test_lab_id", lookups.need_lab)

    assessment_id = v.field_str(body, "assessment_id")
    test_lab_id = v.field_str(body, "test_lab_id")
    window_start = v.field_instant(body, "window_start")
    window_end = v.field_instant(body, "window_end")
    bench_hours = v.field_int(body, "bench_hours", minimum=1)
    if window_end <= window_start:
        raise bad_request("Field 'window_end' must be strictly after 'window_start'.")

    assessment = lookups.need_assessment(assessment_id)
    lab = lookups.need_lab(test_lab_id)

    ensure(
        lab["accreditation_status"] == "ACCREDITED",
        "ERR_LAB_NOT_ACCREDITED",
        "The named laboratory is not accredited.",
    )

    # Half-open windows: an engagement starting exactly when another ends
    # does not intersect it and does not consume a slot.
    occupied = 0
    for other in store.engagements_of_lab(lab["id"]):
        if other["status"] not in RESERVING_STATUSES:
            continue
        if other["window_start"] < window_end and window_start < other["window_end"]:
            occupied += 1
    ensure(
        occupied < lab["concurrent_bench_capacity"],
        "ERR_LAB_BENCH_CAPACITY_CONFLICT",
        "The laboratory's concurrent bench capacity is exhausted for that window.",
    )
    ensure(
        bench_hours <= lab["available_bench_hours"],
        "ERR_LAB_BENCH_HOURS_EXCEEDED",
        "The requested bench hours exceed the laboratory's available balance.",
    )

    row = base_row()
    row.update(
        {
            "assessment_id": assessment["id"],
            "test_lab_id": lab["id"],
            "window_start": window_start,
            "window_end": window_end,
            "bench_hours": bench_hours,
            "status": "SCHEDULED",
            "failed_criterion_codes": None,
            "report_reference": None,
            "cancellation_reason": None,
            "completed_at": None,
        }
    )
    store.test_engagements[row["id"]] = row
    cascades.recompute_lab_ledger(lab)
    return created(serialize.test_engagement(row))


@bp.get("/labeling/test-engagements/<identifier>")
def read_test_engagement(identifier):
    caller(*ENGAGEMENT_READERS)
    return ok(serialize.test_engagement(lookups.need_engagement(identifier)))


@bp.get("/labeling/test-engagements")
def list_test_engagements():
    caller(*ENGAGEMENT_READERS)
    assessment_id = v.query_str("assessment_id")
    test_lab_id = v.query_str("test_lab_id")
    status = v.query_enum("status", ENGAGEMENT_STATUSES)

    rows = list(store.test_engagements.values())
    if assessment_id is not None:
        rows = [row for row in rows if row["assessment_id"] == assessment_id]
    if test_lab_id is not None:
        rows = [row for row in rows if row["test_lab_id"] == test_lab_id]
    if status is not None:
        rows = [row for row in rows if row["status"] == status]
    rows.sort(key=lambda row: (row["window_start"], row["created_at"], row["id"]))
    return lookups.listing(rows, serialize.test_engagement)


@bp.post("/labeling/test-engagements/<identifier>/report")
def report_test_engagement(identifier):
    actor = caller(TEST_LAB_OPERATOR)
    pending = store.test_engagements.get(identifier)
    if pending is not None:
        own(pending["test_lab_id"] == actor.user_id)
    engagement = lookups.need_engagement(identifier)

    body = v.raw_body()

    # Every supplied code must resolve: it must exist in the catalogue and have
    # a criterion response on this engagement's assessment (rung 5).
    answered_codes = set()
    for response in store.responses_of(engagement["assessment_id"]):
        criterion = store.security_criteria.get(response["criterion_id"])
        if criterion is not None:
            answered_codes.add(criterion["criterion_code"])
    raw_codes = body.get("failed_criterion_codes")
    if isinstance(raw_codes, list):
        for code in raw_codes:
            if isinstance(code, str):
                if store.criterion_by_code(code) is None or code not in answered_codes:
                    raise ApiError(
                        "ERR_CRITERION_NOT_FOUND",
                        "Criterion code %s is not answered on this assessment." % code,
                    )

    codes = v.field_array(body, "failed_criterion_codes")
    for index, code in enumerate(codes):
        if not isinstance(code, str) or code == "":
            raise bad_request(
                "Element %d of 'failed_criterion_codes' must be a non-empty string." % index
            )
    report_reference = v.field_str(body, "report_reference", max_len=200)

    ensure(
        engagement["status"] in RESERVING_STATUSES,
        "ERR_INVALID_ENGAGEMENT_STATE",
        "Only a SCHEDULED or IN_PROGRESS engagement may be reported on.",
    )

    failed = set(codes)
    engagement["status"] = "COMPLETED"
    engagement["completed_at"] = clock_now()
    engagement["failed_criterion_codes"] = list(codes)
    engagement["report_reference"] = report_reference
    touch(engagement)

    # The report covers the whole claim: nothing is left NOT_TESTED.
    assessment = store.assessments.get(engagement["assessment_id"])
    if assessment is not None:
        for response in store.responses_of(assessment["id"]):
            criterion = store.security_criteria.get(response["criterion_id"])
            verdict = "PASS"
            if criterion is not None and criterion["criterion_code"] in failed:
                verdict = "FAIL"
            cascades.apply_changes(response, {"lab_result": verdict, "lab_verified": True})

        tier = store.tier_of_assessment(assessment)
        if tier is not None:
            area_scores, overall, min_area, gate_applied, grade = calc.conformance_score(
                assessment, tier, calc.VERIFIED
            )
            assessment["verified_area_scores"] = area_scores
            assessment["verified_overall_score"] = overall
            if assessment["route"] == "THIRD_PARTY_TEST":
                assessment["decided_min_area_score"] = min_area
                assessment["gate_applied"] = gate_applied
                assessment["decided_overall_score"] = overall
                assessment["grade"] = grade
            touch(assessment)

    cascades.recompute_lab_ledger_by_id(engagement["test_lab_id"])
    return created(serialize.test_engagement(engagement))


@bp.post("/labeling/test-engagements/<identifier>/cancel")
def cancel_test_engagement(identifier):
    actor = caller(MANUFACTURER, TEST_LAB_OPERATOR)
    pending = store.test_engagements.get(identifier)
    if pending is not None:
        if actor.role == TEST_LAB_OPERATOR:
            own(pending["test_lab_id"] == actor.user_id)
        else:
            assessment = store.assessments.get(pending["assessment_id"])
            product = store.product_of_assessment(assessment) if assessment else None
            if product is not None:
                own(product["manufacturer_id"] == actor.user_id)
    engagement = lookups.need_engagement(identifier)

    body = v.raw_body()
    cancellation_reason = v.field_str(body, "cancellation_reason", max_len=500)

    ensure(
        engagement["status"] in RESERVING_STATUSES,
        "ERR_INVALID_ENGAGEMENT_STATE",
        "Only a SCHEDULED or IN_PROGRESS engagement may be cancelled.",
    )

    engagement["status"] = "CANCELLED"
    engagement["cancellation_reason"] = cancellation_reason
    touch(engagement)
    cascades.recompute_lab_ledger_by_id(engagement["test_lab_id"])
    return created(serialize.test_engagement(engagement))
