"""Recognition surveys, program evaluation, the expiry sweep and the clock
(PRD 3.7, 3.10, 2.4)."""

from flask import Blueprint

import calc
import cascades
import lookups
import serialize
import store
import validation as v
from auth import CONFORMITY_REVIEWER, CONSUMER, PROGRAM_ADMINISTRATOR, caller
from envelope import clock_now, clock_set, created, iso, ok
from errors import bad_request
from store import base_row

bp = Blueprint("program", __name__)

SURVEY_READERS = (PROGRAM_ADMINISTRATOR, CONFORMITY_REVIEWER, CONSUMER)


@bp.post("/labeling/recognition-surveys")
def create_survey():
    caller(PROGRAM_ADMINISTRATOR)
    body = v.raw_body()
    survey_period_label = v.field_str(body, "survey_period_label", max_len=64)
    survey_period_end = v.field_instant(body, "survey_period_end")
    respondents_count = v.field_int(body, "respondents_count", minimum=0)
    recognized_count = v.field_int(body, "recognized_count", minimum=0)
    if recognized_count > respondents_count:
        raise bad_request("Field 'recognized_count' may not exceed 'respondents_count'.")
    lookups.unique_or_reject(
        store.recognition_surveys, "survey_period_label", survey_period_label
    )

    # A survey wave carries only id and created_at: nothing ever updates it.
    row = base_row(with_common=False)
    row.update(
        {
            "survey_period_label": survey_period_label,
            "survey_period_end": survey_period_end,
            "respondents_count": respondents_count,
            "recognized_count": recognized_count,
        }
    )
    store.recognition_surveys[row["id"]] = row
    return created(serialize.recognition_survey(row))


@bp.get("/labeling/recognition-surveys/<identifier>")
def read_survey(identifier):
    caller(*SURVEY_READERS)
    return ok(serialize.recognition_survey(lookups.need_survey(identifier)))


@bp.get("/labeling/recognition-surveys")
def list_surveys():
    caller(*SURVEY_READERS)
    rows = list(store.recognition_surveys.values())
    rows.sort(key=lambda row: (row["survey_period_end"], row["created_at"], row["id"]))
    return lookups.listing(rows, serialize.recognition_survey)


@bp.get("/labeling/program-evaluation")
def program_evaluation():
    caller(*SURVEY_READERS)
    now = clock_now()

    enrolled_manufacturer_count = len(store.manufacturers)

    participating = set()
    labeled = set()
    for grant in store.label_grants.values():
        product = store.products.get(grant["product_id"])
        if product is None:
            continue
        # Participation admits SUSPENDED; the labeled-product count does not.
        if grant["grant_status"] in ("ACTIVE", "SUSPENDED"):
            participating.add(product["manufacturer_id"])
        if grant["grant_status"] == "ACTIVE":
            labeled.add(product["id"])

    eligible_product_count = 0
    for product in store.products.values():
        if product["eligibility_status"] == "ELIGIBLE":
            eligible_product_count += 1

    respondents_total = 0
    recognized_total = 0
    for survey in store.recognition_surveys.values():
        # Inclusive upper bound: a wave closing exactly on the clock counts.
        if survey["survey_period_end"] <= now:
            respondents_total += survey["respondents_count"]
            recognized_total += survey["recognized_count"]

    participation_rate = calc.rate(len(participating), enrolled_manufacturer_count)
    recognition_rate = calc.rate(recognized_total, respondents_total)

    # The comparison is made against the rounded, reported figures.
    cleared = 0
    if participation_rate >= calc.PARTICIPATION_TARGET:
        cleared += 1
    if recognition_rate >= calc.RECOGNITION_TARGET:
        cleared += 1
    if cleared == 2:
        grade = "MEETING_TARGET"
    elif cleared == 1:
        grade = "PARTIAL"
    else:
        grade = "BELOW_TARGET"

    return ok(
        {
            "enrolled_manufacturer_count": enrolled_manufacturer_count,
            "participating_manufacturer_count": len(participating),
            "manufacturer_participation_rate": serialize.num(participation_rate),
            "eligible_product_count": eligible_product_count,
            "labeled_product_count": len(labeled),
            "respondents_count": respondents_total,
            "recognized_total": recognized_total,
            "consumer_recognition_rate": serialize.num(recognition_rate),
            "evaluation_grade": grade,
        }
    )


@bp.post("/labeling/program/expiry-sweep")
def expiry_sweep():
    caller(PROGRAM_ADMINISTRATOR)
    return ok(cascades.expiry_sweep())


@bp.post("/_clock/set_current_utc")
def set_clock():
    caller(PROGRAM_ADMINISTRATOR)
    body = v.raw_body()
    value = v.field_instant(body, "to_iso8601")
    return ok({"current_utc": iso(clock_set(value))})
