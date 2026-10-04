"""Lab analysis endpoints: heavily-gated creation (sample ledger debit,
lab bench window) and the laboratory lifecycle advance."""

from flask import Blueprint

import cascades
import db
from auth import require_roles
from calculations import lab_window_overlaps, refresh_testing_status, MIN_TESTABLE_NG
from clock import parse_iso
from db import touch
from envelope import ok
from errors import (
    ERR_AUTHORIZATION_NOT_EFFECTIVE,
    ERR_CASE_NOT_IN_TESTING,
    ERR_CONSUMED_EXCEEDS_RESERVED,
    ERR_EVIDENCE_ITEM_NOT_FOUND,
    ERR_INSUFFICIENT_SAMPLE,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_INVALID_TRANSITION_EVENT,
    ERR_LAB_ANALYSIS_NOT_FOUND,
    ERR_LAB_SCHEDULE_OVERLAP,
    ERR_TESTING_AUTHORIZATION_NOT_FOUND,
    raise_err,
)
from validation import (
    as_integer,
    as_string,
    body_json,
    reject_unknown,
    req_bool,
    req_choice,
    req_datetime,
    req_field,
    req_int,
    req_str,
)

bp = Blueprint("lab_analyses", __name__)

TEST_TYPES = ("DNA_STR", "DNA_TOUCH", "DNA_YSTR", "MITOCHONDRIAL_DNA", "SEROLOGY")
ADVANCE_EVENTS = ("SHIP_SAMPLE", "RECORD_RESULT", "RECORD_EXPERT_INTERPRETATION",
                  "RUN_DATABASE_COMPARISON", "CANCEL")
OUTCOMES = ("EXCLUSIONARY", "INCLUSIONARY", "INCONCLUSIVE", "NO_PROFILE")
INTERPRETATIONS = ("SUPPORTS_INNOCENCE", "NEUTRAL", "SUPPORTS_CONVICTION")
COMPARISON_RESULTS = ("HIT", "NO_HIT", "PARTIAL")
COMPARISON_STATUS = {
    "HIT": "COMPLETED_HIT",
    "NO_HIT": "COMPLETED_NO_HIT",
    "PARTIAL": "COMPLETED_PARTIAL",
}


@bp.post("/lab-analyses")
def create_lab_analysis():
    require_roles("StaffAttorney")
    body = body_json()
    # priority 3: body-id existence in payload field order
    if "evidence_item_id" in body:
        db.lookup(db.evidence_items, body.get("evidence_item_id"),
                  ERR_EVIDENCE_ITEM_NOT_FOUND)
    if "authorization_id" in body:
        db.lookup(db.testing_authorizations, body.get("authorization_id"),
                  ERR_TESTING_AUTHORIZATION_NOT_FOUND)
    # priority 3.8: shape
    reject_unknown(body, {"evidence_item_id", "authorization_id", "lab_name",
                          "test_type", "required_sample_ng", "scheduled_start",
                          "scheduled_end"})
    evidence_item_id = req_str(body, "evidence_item_id")
    authorization_id = req_str(body, "authorization_id")
    lab_name = req_str(body, "lab_name")
    test_type = req_choice(body, "test_type", TEST_TYPES)
    required_sample_ng = req_int(body, "required_sample_ng", minimum=1)
    scheduled_start = req_datetime(body, "scheduled_start")
    scheduled_end = req_datetime(body, "scheduled_end")
    start_dt = parse_iso(scheduled_start)
    end_dt = parse_iso(scheduled_end)
    if end_dt <= start_dt:
        raise_err(ERR_INVALID_REQUEST,
                  "scheduled_end must be strictly after scheduled_start")
    item = db.evidence_items[evidence_item_id]
    authorization = db.testing_authorizations[authorization_id]
    # priority 4.5: the owning case must be in TESTING
    case = db.cases.get(item["case_id"])
    if case is None or case["status"] != "TESTING":
        raise_err(ERR_CASE_NOT_IN_TESTING,
                  "LabAnalysis creation requires the owning case to be in TESTING")
    # priority 6: the authorization must be effective
    if authorization["status"] not in ("SIGNED", "GRANTED"):
        raise_err(ERR_AUTHORIZATION_NOT_EFFECTIVE,
                  "The referenced testing authorization is not SIGNED or GRANTED")
    # priority 7: half-open lab bench window overlap
    if lab_window_overlaps(lab_name, start_dt, end_dt):
        raise_err(ERR_LAB_SCHEDULE_OVERLAP,
                  "Another analysis for this lab has an overlapping window")
    # priority 8(c): sample sufficiency (reservation must cover the request
    # and the item must currently hold the minimum testable mass)
    if (item["remaining_sample_ng"] < required_sample_ng
            or item["remaining_sample_ng"] < MIN_TESTABLE_NG):
        raise_err(ERR_INSUFFICIENT_SAMPLE,
                  "Insufficient remaining sample for this analysis")
    analysis = db.new_entity()
    analysis.update({
        "evidence_item_id": evidence_item_id,
        "authorization_id": authorization_id,
        "lab_name": lab_name,
        "test_type": test_type,
        "required_sample_ng": required_sample_ng,
        "reserved_sample_ng": required_sample_ng,
        "actual_consumed_ng": None,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "status": "SCHEDULED",
        "outcome": None,
        "profile_obtained": None,
        "expert_name": None,
        "expert_interpretation": None,
        "db_comparison_status": "NOT_RUN",
        "db_matched_subject_name": None,
    })
    db.lab_analyses[analysis["id"]] = analysis
    # sample_ledger reservation (after the analysis is visible to derivation)
    item["remaining_sample_ng"] -= required_sample_ng
    refresh_testing_status(item)
    touch(item)
    return ok(analysis, 201)


@bp.post("/lab-analyses/<aid>/advance")
def advance_lab_analysis(aid):
    require_roles("StaffAttorney", "EvidenceAnalyst")
    analysis = db.lookup(db.lab_analyses, aid, ERR_LAB_ANALYSIS_NOT_FOUND)
    body = body_json()
    reject_unknown(body, {"event", "outcome", "actual_consumed_ng",
                          "profile_obtained", "expert_name",
                          "expert_interpretation", "database_name",
                          "comparison_result", "matched_subject_name"})
    event = as_string(req_field(body, "event"), "event")
    if event not in ADVANCE_EVENTS:
        raise_err(ERR_INVALID_TRANSITION_EVENT,
                  "Unknown event for lab-analysis advance: %s" % event)
    # event-specific shape (priority 3.8) before state checks
    outcome = consumed = None
    profile_obtained = None
    expert_name = expert_interpretation = None
    database_name = comparison_result = matched_subject_name = None
    if event == "RECORD_RESULT":
        outcome = req_choice(body, "outcome", OUTCOMES)
        consumed = as_integer(req_field(body, "actual_consumed_ng"),
                              "actual_consumed_ng")
        profile_obtained = req_bool(body, "profile_obtained")
    elif event == "RECORD_EXPERT_INTERPRETATION":
        expert_name = req_str(body, "expert_name")
        expert_interpretation = req_choice(body, "expert_interpretation",
                                           INTERPRETATIONS)
    elif event == "RUN_DATABASE_COMPARISON":
        database_name = req_str(body, "database_name")
        comparison_result = req_choice(body, "comparison_result",
                                       COMPARISON_RESULTS)
        if comparison_result == "HIT":
            matched_subject_name = req_str(body, "matched_subject_name")
        elif "matched_subject_name" in body and body["matched_subject_name"] is not None:
            raise_err(ERR_INVALID_REQUEST,
                      "matched_subject_name is only allowed on a HIT")

    status = analysis["status"]
    if event == "SHIP_SAMPLE":
        if status != "SCHEDULED":
            raise_err(ERR_INVALID_STATE, "SHIP_SAMPLE requires status SCHEDULED")
        analysis["status"] = "SAMPLE_SHIPPED"
    elif event == "RECORD_RESULT":
        if status != "SAMPLE_SHIPPED":
            raise_err(ERR_INVALID_STATE,
                      "RECORD_RESULT requires status SAMPLE_SHIPPED")
        if consumed < 1 or consumed > analysis["reserved_sample_ng"]:
            raise_err(ERR_CONSUMED_EXCEEDS_RESERVED,
                      "actual_consumed_ng must be between 1 and reserved_sample_ng")
        analysis["outcome"] = outcome
        analysis["actual_consumed_ng"] = consumed
        analysis["profile_obtained"] = profile_obtained
        analysis["status"] = "RESULT_RECORDED"
        # sample_ledger settle: refund the unconsumed reservation
        item = db.evidence_items[analysis["evidence_item_id"]]
        refund = analysis["reserved_sample_ng"] - consumed
        changed = False
        if refund:
            item["remaining_sample_ng"] += refund
            changed = True
        if refresh_testing_status(item):
            changed = True
        if changed:
            touch(item)
    elif event == "RECORD_EXPERT_INTERPRETATION":
        if status != "RESULT_RECORDED":
            raise_err(ERR_INVALID_STATE,
                      "RECORD_EXPERT_INTERPRETATION requires status RESULT_RECORDED")
        analysis["expert_name"] = expert_name
        analysis["expert_interpretation"] = expert_interpretation
        analysis["status"] = "INTERPRETED"
    elif event == "RUN_DATABASE_COMPARISON":
        if status not in ("RESULT_RECORDED", "INTERPRETED"):
            raise_err(ERR_INVALID_STATE,
                      "RUN_DATABASE_COMPARISON requires status RESULT_RECORDED "
                      "or INTERPRETED")
        if analysis["profile_obtained"] is not True:
            raise_err(ERR_INVALID_STATE,
                      "RUN_DATABASE_COMPARISON requires profile_obtained")
        analysis["db_comparison_status"] = COMPARISON_STATUS[comparison_result]
        analysis["db_matched_subject_name"] = (
            matched_subject_name if comparison_result == "HIT" else None)
        if comparison_result == "HIT":
            cascades.apply_hit_cascade(analysis)
    else:  # CANCEL
        if status != "SCHEDULED":
            raise_err(ERR_INVALID_STATE, "CANCEL requires status SCHEDULED")
        analysis["status"] = "CANCELLED"
        # sample_ledger refund: the full reservation is returned
        item = db.evidence_items[analysis["evidence_item_id"]]
        item["remaining_sample_ng"] += analysis["reserved_sample_ng"]
        refresh_testing_status(item)
        touch(item)
    touch(analysis)
    return ok(analysis)
