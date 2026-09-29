"""Diligence underwriting and program agreements."""
from flask import Blueprint, g

import calc
import cascade
import respond
import schema
import serialize
import store
from authz import auth, scope_rows, sod
from errors import fail

bp = Blueprint("diligence", __name__)
READ_ROLES = ("ProgramOfficer", "ComplianceOfficer", "RiskCommittee", "InternalAudit",
              "FintechPartner")
OPEN_REVIEW = ("DRAFT", "SUBMITTED", "INFO_REQUESTED")
TERMINAL_PARTNER = ("DILIGENCE_FAILED", "TERMINATED")


def _body_partner(data):
    if data.get("partner_id") is not None:                          # rank 10
        return store.must("partners", data["partner_id"])
    return None


@bp.post("/oversight/diligence-reviews")
@auth("ProgramOfficer")
def create_review():
    data = schema.body()
    partner = _body_partner(data)
    schema.req_str(data, "partner_id")                              # rank 18
    review_type = schema.req_enum(data, "review_type", schema.REVIEW_TYPES)
    bm = schema.req_int(data, "business_model_score", 0, 100)
    fs = schema.req_int(data, "funding_score", 0, 100)
    cc = schema.req_int(data, "compliance_capability_score", 0, 100)
    ch = schema.req_int(data, "complaint_history_score", 0, 100)
    expected = schema.req_int(data, "expected_partner_version")
    if expected != int(partner["version"]):                         # rank 28
        fail("ERR_STALE_PARTNER_VERSION", "expected_partner_version is stale")
    if partner["status"] in TERMINAL_PARTNER:                       # rank 32
        fail("ERR_PARTNER_TERMINAL", "partner is terminal")
    for row in store.rows("diligence_reviews"):                     # rank 70
        if row["partner_id"] == partner["id"] and row["status"] in OPEN_REVIEW:
            fail("ERR_DILIGENCE_ALREADY_OPEN", "an open diligence file already exists")
    record = {
        "partner_id": partner["id"],
        "review_type": review_type,
        "business_model_score": bm,
        "funding_score": fs,
        "compliance_capability_score": cc,
        "complaint_history_score": ch,
        "effective_complaint_history_score": 0,
        "composite_score": 0.0,
        "tier": "UNRATED",
        "status": "DRAFT",
        "revision_round": 0,
        "requested_info_items": [],
        "submitted_by_user_id": None,
        "decided_by_user_id": None,
    }
    store.insert("diligence_reviews", record)
    store.touch(partner)
    return respond.ok(serialize.diligence_review(record), 201)


@bp.get("/oversight/diligence-reviews")
@auth(*READ_ROLES)
def list_reviews():
    rows = store.rows("diligence_reviews")
    partner_id = schema.filter_str("partner_id")
    if partner_id is not None:
        rows = [r for r in rows if r["partner_id"] == partner_id]
    status = schema.filter_enum("status", schema.REVIEW_STATUSES)
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    review_type = schema.filter_enum("review_type", schema.REVIEW_TYPES)
    if review_type is not None:
        rows = [r for r in rows if r["review_type"] == review_type]
    return respond.paginate(scope_rows(rows), serialize.diligence_review)


@bp.get("/oversight/diligence-reviews/<rid>")
@auth(*READ_ROLES)
def read_review(rid):
    review = store.must("diligence_reviews", rid)
    from authz import scope_partner_id
    scope_partner_id(review["partner_id"])
    return respond.ok(serialize.diligence_review(review))


@bp.post("/oversight/diligence-reviews/<rid>/submit")
@auth("ProgramOfficer")
def submit_review(rid):
    review = store.must("diligence_reviews", rid)                   # rank 8
    data = schema.body()
    schema.opt_str(data, "submission_note")                         # rank 18
    partner = store.get("partners", review["partner_id"])
    if review["status"] not in ("DRAFT", "INFO_REQUESTED"):          # rank 34
        fail("ERR_REVIEW_NOT_DRAFT_OR_INFO_REQUESTED", "review is not submittable")
    if review["status"] == "DRAFT":
        if partner["status"] not in ("PROSPECT", "DILIGENCE_PASSED"):
            fail("ERR_REVIEW_NOT_DRAFT_OR_INFO_REQUESTED", "partner is not in diligence")
        if partner["status"] == "DILIGENCE_PASSED":
            for row in store.rows("diligence_reviews"):
                if row["id"] != review["id"] and row["partner_id"] == partner["id"] \
                        and row["status"] in OPEN_REVIEW:
                    fail("ERR_REVIEW_NOT_DRAFT_OR_INFO_REQUESTED",
                         "another open diligence file exists")
        review["revision_round"] = 1
    else:
        if partner["status"] != "IN_DILIGENCE":
            fail("ERR_REVIEW_NOT_DRAFT_OR_INFO_REQUESTED", "partner is not in diligence")
        review["revision_round"] = int(review["revision_round"]) + 1
        review["requested_info_items"] = []
    review["status"] = "SUBMITTED"
    review["submitted_by_user_id"] = g.user_id
    calc.score_diligence(review, partner)
    store.touch(review)
    if partner["status"] in ("PROSPECT", "DILIGENCE_PASSED"):
        partner["status"] = "IN_DILIGENCE"
        store.touch(partner)
    return respond.ok(serialize.diligence_review(review))


@bp.post("/oversight/diligence-reviews/<rid>/decide")
@auth("ComplianceOfficer")
def decide_review(rid):
    review = store.must("diligence_reviews", rid)                   # rank 8
    sod(review["submitted_by_user_id"])                             # rank 14
    data = schema.body()
    outcome = schema.req_enum(data, "outcome",                      # rank 18
                              ["PASSED", "FAILED", "INFO_REQUESTED"])
    schema.opt_str(data, "decision_note")
    items = None
    if outcome == "INFO_REQUESTED":
        items = schema.req_str_array(data, "requested_info_items", non_empty=True)
    if review["status"] != "SUBMITTED":                              # rank 34
        fail("ERR_REVIEW_NOT_SUBMITTED", "review is not SUBMITTED")
    partner = store.get("partners", review["partner_id"])
    if outcome == "PASSED":
        if int(review["compliance_capability_score"]) < 60:          # rank 56
            fail("ERR_COMPLIANCE_CAPABILITY_FLOOR", "compliance capability below floor")
        if float(review["composite_score"]) < 55.0:                 # rank 57
            fail("ERR_DILIGENCE_SCORE_BELOW_FLOOR", "composite score below floor")
    review["decided_by_user_id"] = g.user_id
    if outcome == "INFO_REQUESTED":
        review["status"] = "INFO_REQUESTED"
        review["requested_info_items"] = items
        store.touch(review)
    elif outcome == "PASSED":
        review["status"] = "PASSED"
        store.touch(review)
        partner["status"] = "DILIGENCE_PASSED"
        partner["capability_tier"] = review["tier"]
        partner["latest_composite_score"] = float(review["composite_score"])
        store.touch(partner)
    else:
        review["status"] = "FAILED"
        store.touch(review)
        partner["status"] = "DILIGENCE_FAILED"
        partner["capability_tier"] = "UNRATED"
        partner["latest_composite_score"] = float(review["composite_score"])
        store.touch(partner)
    return respond.ok(serialize.diligence_review(review))
