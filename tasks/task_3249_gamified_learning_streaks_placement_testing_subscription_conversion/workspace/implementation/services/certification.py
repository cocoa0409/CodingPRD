"""Certification exams: purchase, proctoring, scoring and institutional reports."""

from datetime import timedelta

import core
import middleware as mw
import serialize
from core import ApiError
from db import STORE
from runtime import CLOCK
from services import calc, common


def _qualifying_placement(learner_id):
    # PRD 3.8: the session must "sits in `SCORED` state" with a calibrated band
    # of B2 or C1.  A session calibrated before purchase stays CALIBRATED, and
    # PRD 3.6 treats CALIBRATED as a SCORED-equivalent operable state whose band
    # was computed from the same stored sub-scores, so both postures qualify.
    for test in STORE.placement_tests.values():
        if test["learner_id"] != learner_id:
            continue
        if test["status"] not in ("SCORED", "CALIBRATED"):
            continue
        if test.get("calibrated_cefr_band") not in ("B2", "C1"):
            continue
        return test
    return None


def create_exam(body, actor):
    learner_id = core.as_str(core.get_field(body, "learner_id"), "learner_id")
    mw.check_learner_param(actor, learner_id)
    mw.own(actor, learner_id)
    learner = common.learner_or_404(learner_id)
    product_code = core.enum_check(
        core.get_field(body, "product_code"), core.VALID_PRODUCT_CODES, "product_code"
    )
    proctor_user_id = core.as_str(core.get_field(body, "proctor_user_id"), "proctor_user_id")
    if not proctor_user_id.strip():
        raise ApiError(core.ERR_INVALID_REQUEST, "proctor_user_id must be a non-empty operator id.")
    window_hours = core.as_int(core.get_field(body, "proctor_window_hours"), "proctor_window_hours")
    guard = core.as_int(core.get_field(body, "expected_learner_version"), "expected_learner_version")

    if guard != int(learner["version"]):
        raise ApiError(core.ERR_STALE_VERSION)
    if learner["program_tier"] != "CERTIFICATION_ELITE":
        raise ApiError(core.ERR_INVALID_REQUEST, "The learner is not on the certification tier.")

    test = _qualifying_placement(learner_id)
    if test is None:
        raise ApiError(core.ERR_INVALID_REQUEST, "No scored placement session qualifies for a purchase.")
    if not test.get("proctor_user_id"):
        raise ApiError(core.ERR_INVALID_REQUEST, "The placement session is not proctored.")

    now = CLOCK.get()
    exam = {
        "id": core.new_id(),
        "learner_id": learner_id,
        "product_code": product_code,
        "status": "PURCHASED",
        "purchased_at": core.to_iso(now),
        "proctored_by_user_id": proctor_user_id,
        "proctor_started_at": None,
        "score_band": None,
        "raw_score": None,
        "report_id": None,
        "expires_at": core.to_iso(now + timedelta(hours=window_hours)),
        "created_at": core.to_iso(now),
        "updated_at": core.to_iso(now),
        "version": 1,
    }
    STORE.certification_exams[exam["id"]] = exam

    if test.get("placed_unit_index") is not None and int(test["placed_unit_index"]) >= 5:
        test["status"] = "CERTIFIED"
        common.touch(test, CLOCK)
    common.recompute_xp_total(learner_id)
    common.touch(learner, CLOCK)
    return exam


def update_exam(exam_id, body, actor):
    exam = STORE.certification_exams.get(exam_id)
    if exam is None:
        raise ApiError(core.ERR_INVALID_REQUEST, "The named certification exam does not exist.")
    if actor["role"] == "Learner":
        mw.own(actor, exam["learner_id"])
    action = core.as_str(core.get_field(body, "action"), "action")

    if action == "PROCTOR":
        return _proctor(exam, body)
    if action in ("SUBMIT_SCORE", "SUBMIT"):
        return _submit_score(exam, body)
    if action in ("FINALIZE", "SCORE"):
        return _finalize(exam, body, actor)
    raise ApiError(core.ERR_INVALID_REQUEST, "Unsupported exam action.")


def _proctor(exam, body):
    if exam["status"] != "PURCHASED":
        raise ApiError(core.ERR_EXAM_NOT_PROCTORING)
    proctor_user_id = None
    if core.has_field(body, "proctor_user_id"):
        proctor_user_id = core.as_str(body["proctor_user_id"], "proctor_user_id")
    if not proctor_user_id or not proctor_user_id.strip():
        proctor_user_id = exam.get("proctored_by_user_id")
    if not proctor_user_id:
        raise ApiError(core.ERR_INVALID_REQUEST, "A non-empty proctor_user_id is required.")
    if CLOCK.get() > core.parse_iso8601(exam["expires_at"]):
        raise ApiError(core.ERR_PROCTOR_WINDOW_EXPIRED)
    exam["proctored_by_user_id"] = proctor_user_id
    exam["proctor_started_at"] = core.to_iso(CLOCK.get())
    exam["status"] = "PROCTORING"
    common.touch(exam, CLOCK)
    return exam


def _submit_score(exam, body):
    if exam["status"] != "PROCTORING":
        raise ApiError(core.ERR_EXAM_NOT_PROCTORING)
    started = core.parse_iso8601(exam["proctor_started_at"]) if exam.get("proctor_started_at") else CLOCK.get()
    if CLOCK.get() > started + timedelta(hours=core.PROCTOR_WINDOW_HOURS):
        raise ApiError(core.ERR_PROCTOR_WINDOW_EXPIRED)
    raw_score = core.as_int(core.get_field(body, "raw_score"), "raw_score")
    exam["raw_score"] = raw_score
    exam["status"] = "SUBMITTED"
    common.touch(exam, CLOCK)
    return exam


def _finalize(exam, body, actor):
    void_reason = None
    if core.has_field(body, "void_reason"):
        void_reason = core.as_str(body["void_reason"], "void_reason")

    if void_reason:
        if exam["status"] != "PROCTORING":
            raise ApiError(core.ERR_EXAM_NOT_PROCTORING)
        exam["score_band"] = "NOT_CERTIFIED"
        exam["status"] = "VOID"
        common.touch(exam, CLOCK)
        for offer in STORE.engagement_offers.values():
            if offer["learner_id"] == exam["learner_id"] and offer["status"] == "ISSUED":
                offer["status"] = "SUPPRESSED"
                common.touch(offer, CLOCK)
        return exam

    if exam["status"] != "SUBMITTED":
        raise ApiError(core.ERR_EXAM_NOT_PROCTORING)
    penalty = 0
    if core.has_field(body, "discipline_penalty"):
        penalty = core.as_int(body["discipline_penalty"], "discipline_penalty")
    proctored = bool(exam.get("proctored_by_user_id"))
    band = calc.certification_band(exam["raw_score"], penalty, proctored)
    exam["score_band"] = band
    exam["status"] = "SCORED"
    common.touch(exam, CLOCK)
    return exam


def create_report(exam_id, body, actor):
    exam = STORE.certification_exams.get(exam_id)
    if exam is None:
        raise ApiError(core.ERR_INVALID_REQUEST, "The named certification exam does not exist.")
    institution_name = core.as_str(core.get_field(body, "institution_name"), "institution_name")
    institution_learner_code = core.as_str(
        core.get_field(body, "institution_learner_code"), "institution_learner_code"
    )
    if exam["status"] != "SCORED":
        raise ApiError(core.ERR_EXAM_NOT_PROCTORING)
    if exam["score_band"] not in ("PASS", "STRONG_PASS", "DISTINCTION"):
        raise ApiError(core.ERR_INVALID_REQUEST, "Only a passing exam can be reported.")

    now = CLOCK.get()
    report = {
        "id": core.new_id(),
        "exam_id": exam["id"],
        "learner_id": exam["learner_id"],
        "institution_name": institution_name,
        "institution_learner_code": institution_learner_code,
        "score_band": exam["score_band"],
        "raw_score": exam["raw_score"],
        "reported_at": core.to_iso(now),
        "created_at": core.to_iso(now),
        "updated_at": core.to_iso(now),
        "version": 1,
    }
    STORE.score_reports[report["id"]] = report
    exam["report_id"] = report["id"]
    exam["status"] = "REPORTED"
    common.touch(exam, CLOCK)
    common.recompute_xp_total(exam["learner_id"])
    return report


def exam_expiry(clock):
    for exam in STORE.certification_exams.values():
        if exam["status"] != "PURCHASED":
            continue
        if clock.get() > core.parse_iso8601(exam["expires_at"]):
            exam["status"] = "EXPIRED"
            common.touch(exam, clock)


def offer_expiry(clock):
    for offer in STORE.engagement_offers.values():
        if offer["status"] != "ISSUED":
            continue
        if clock.get() > core.parse_iso8601(offer["expires_at"]):
            offer["status"] = "EXPIRED"
            common.touch(offer, clock)