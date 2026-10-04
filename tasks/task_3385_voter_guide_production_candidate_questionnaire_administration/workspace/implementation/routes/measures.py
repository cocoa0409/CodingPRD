"""BallotMeasure + MeasureArgument + NeutralityReview routes (PRD 3.5)."""
from flask import Blueprint

import calc
import helpers
import serialize
import shape
from authz import (CHAPTER_COORDINATOR, LEAGUE_ADMIN, NEUTRALITY_REVIEWER,
                   QUESTIONNAIRE_EDITOR, check_active_current, require_roles)
from errors import (advocacy_separation, contest_kind_mismatch,
                    cycle_not_open, duplicate_measure,
                    duplicate_review_this_round, invalid_state,
                    missing_pro_or_con, only_drafter_may_revise,
                    sod_drafter_cannot_review)
from helpers import base_entity, touch
from respond import listing, success
from store import store

bp = Blueprint("measures", __name__)

ARGUMENT_SIDES = ("PRO", "CON")
VERDICTS = ("NEUTRAL", "LOADED_LANGUAGE", "UNBALANCED")


@bp.post("/contests/<cid>/measure")
def create_measure(cid):
    uid, role, volunteer = require_roles(QUESTIONNAIRE_EDITOR)
    b = shape.body()
    shape.no_extra(b, {"measure_title", "official_text", "explanation_text"})
    measure_title = shape.s_str(b, "measure_title")
    official_text = shape.s_str(b, "official_text")
    explanation_text = shape.s_str(b, "explanation_text")
    contest = helpers.get_contest(cid)
    cycle = helpers.cycle_of_contest(contest)
    if cycle["status"] != "OPEN":
        raise cycle_not_open()
    if contest["status"] != "QUESTIONNAIRE_PHASE":
        raise invalid_state("The contest is not in QUESTIONNAIRE_PHASE")
    check_active_current(volunteer)
    if volunteer["advocacy_flag"]:
        raise advocacy_separation(
            "An advocacy-flagged volunteer may not draft a measure")
    if helpers.measure_of_contest(contest["id"]) is not None:
        raise duplicate_measure()
    if contest["kind"] != "BALLOT_MEASURE":
        raise contest_kind_mismatch(
            "Only a BALLOT_MEASURE contest carries a measure")
    grade_fk, grade_smog = calc.reading_grades(explanation_text)
    measure = base_entity()
    measure.update({
        "contest_id": contest["id"],
        "measure_title": measure_title,
        "official_text": official_text,
        "explanation_text": explanation_text,
        "drafter_volunteer_id": uid,
        "status": "DRAFTING",
        "review_round_count": 0,
        "approvals_this_round": 0,
        "grade_fk": grade_fk,
        "grade_smog": grade_smog,
    })
    store.measures[measure["id"]] = measure
    return success(serialize.measure_json(measure), status=201)


@bp.get("/contests/<cid>/measure")
def read_contest_measure(cid):
    require_roles(LEAGUE_ADMIN, CHAPTER_COORDINATOR, QUESTIONNAIRE_EDITOR,
                  NEUTRALITY_REVIEWER)
    contest = helpers.get_contest(cid)
    measure = helpers.measure_of_contest(contest["id"])
    rows = [] if measure is None else [serialize.measure_json(measure)]
    limit, offset = shape.pagination_params()
    return listing(rows, limit, offset, len(rows))


@bp.get("/measures/<mid>")
def read_measure(mid):
    require_roles(LEAGUE_ADMIN, QUESTIONNAIRE_EDITOR, NEUTRALITY_REVIEWER)
    return success(serialize.measure_json(helpers.get_measure(mid)))


@bp.post("/measures/<mid>/revise")
def revise_measure(mid):
    uid, role, volunteer = require_roles(QUESTIONNAIRE_EDITOR)
    b = shape.body()
    shape.no_extra(b, {"explanation_text"})
    explanation_text = shape.s_str(b, "explanation_text")
    measure = helpers.get_measure(mid)
    if measure["status"] not in ("DRAFTING", "REMANDED"):
        raise invalid_state("Only a DRAFTING or REMANDED measure may be revised")
    check_active_current(volunteer)
    if uid != measure["drafter_volunteer_id"]:
        raise only_drafter_may_revise()
    measure["explanation_text"] = explanation_text
    measure["grade_fk"], measure["grade_smog"] = calc.reading_grades(
        explanation_text)
    measure["status"] = "DRAFTING"
    touch(measure)
    return success(serialize.measure_json(measure))


@bp.post("/measures/<mid>/arguments")
def create_argument(mid):
    uid, role, volunteer = require_roles(QUESTIONNAIRE_EDITOR)
    b = shape.body()
    shape.no_extra(b, {"side", "argument_text", "author_credit"})
    side = shape.s_enum(b, "side", ARGUMENT_SIDES)
    argument_text = shape.s_str(b, "argument_text")
    author_credit = shape.s_str(b, "author_credit")
    measure = helpers.get_measure(mid)
    check_active_current(volunteer)
    count = calc.word_count(argument_text, "STRICT")
    argument = base_entity()
    argument.update({
        "measure_id": measure["id"],
        "side": side,
        "argument_text": argument_text,
        "author_credit": author_credit,
        "word_count": count,
        "status": ("ACCEPTED" if count <= calc.ARGUMENT_WORD_LIMIT
                   else "REJECTED"),
    })
    store.arguments[argument["id"]] = argument
    return success(serialize.argument_json(argument), status=201)


@bp.get("/measures/<mid>/arguments")
def list_arguments(mid):
    require_roles(LEAGUE_ADMIN, QUESTIONNAIRE_EDITOR, NEUTRALITY_REVIEWER)
    measure = helpers.get_measure(mid)
    limit, offset = shape.pagination_params()
    status_filter = shape.q("status")
    side_filter = shape.q("side")
    rows = helpers.arguments_of_measure(measure["id"])
    if status_filter is not None:
        rows = [a for a in rows if a["status"] == status_filter]
    if side_filter is not None:
        rows = [a for a in rows if a["side"] == side_filter]
    rows, total = helpers.page_of(rows, limit, offset)
    return listing([serialize.argument_json(a) for a in rows],
                   limit, offset, total)


@bp.post("/measures/<mid>/submit-for-review")
def submit_for_review(mid):
    uid, role, volunteer = require_roles(QUESTIONNAIRE_EDITOR)
    b = shape.body()
    shape.no_extra(b, set())
    measure = helpers.get_measure(mid)
    if measure["status"] != "DRAFTING":
        raise invalid_state("Only a DRAFTING measure may be submitted for review")
    check_active_current(volunteer)
    if uid != measure["drafter_volunteer_id"]:
        raise only_drafter_may_revise()
    pro = con = 0
    for a in helpers.arguments_of_measure(measure["id"]):
        if a["status"] == "ACCEPTED":
            if a["side"] == "PRO":
                pro += 1
            else:
                con += 1
    if pro < 1 or con < 1:
        raise missing_pro_or_con()
    measure["status"] = "IN_NEUTRALITY_REVIEW"
    measure["review_round_count"] += 1
    measure["approvals_this_round"] = 0
    touch(measure)
    return success(serialize.measure_json(measure))


@bp.post("/measures/<mid>/reviews")
def create_review(mid):
    uid, role, volunteer = require_roles(NEUTRALITY_REVIEWER)
    b = shape.body()
    shape.no_extra(b, {"verdict", "notes"})
    verdict = shape.s_enum(b, "verdict", VERDICTS)
    notes = shape.s_str(b, "notes")
    measure = helpers.get_measure(mid)
    if measure["status"] != "IN_NEUTRALITY_REVIEW":
        raise invalid_state("The measure is not IN_NEUTRALITY_REVIEW")
    check_active_current(volunteer)
    if volunteer["advocacy_flag"]:
        raise advocacy_separation(
            "An advocacy-flagged volunteer may not review a measure")
    if uid == measure["drafter_volunteer_id"]:
        raise sod_drafter_cannot_review()
    for existing in helpers.reviews_of_measure(measure["id"]):
        if (existing["reviewer_volunteer_id"] == uid
                and existing["round_index"] == measure["review_round_count"]):
            raise duplicate_review_this_round()
    review = base_entity()
    review.update({
        "measure_id": measure["id"],
        "reviewer_volunteer_id": uid,
        "verdict": verdict,
        "notes": notes,
        "round_index": measure["review_round_count"],
    })
    store.reviews[review["id"]] = review
    if verdict == "NEUTRAL":
        measure["approvals_this_round"] += 1
        if measure["approvals_this_round"] >= calc.NEUTRAL_APPROVALS_REQUIRED:
            measure["status"] = "APPROVED_FOR_GUIDE"
    else:
        # A single remanding verdict ends the round immediately.
        measure["status"] = "REMANDED"
    touch(measure)
    return success(serialize.review_json(review), status=201)


@bp.get("/measures/<mid>/reviews")
def list_reviews(mid):
    require_roles(LEAGUE_ADMIN, QUESTIONNAIRE_EDITOR, NEUTRALITY_REVIEWER)
    measure = helpers.get_measure(mid)
    limit, offset = shape.pagination_params()
    rows, total = helpers.page_of(
        helpers.reviews_of_measure(measure["id"]), limit, offset)
    return listing([serialize.review_json(r) for r in rows],
                   limit, offset, total)
