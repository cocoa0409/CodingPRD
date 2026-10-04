"""Compensation claim endpoints: creation on an EXONERATED case with the
frozen PROVISIONAL estimate, then the FILE / RECORD_DECISION / APPEAL /
RECORD_PAYMENT lifecycle with the FINAL_VERIFIED award."""

from flask import Blueprint

import cascades
import db
from auth import require_roles
from calculations import (
    final_verified_compensation_award,
    provisional_compensation_estimate,
)
from db import touch
from envelope import ok
from errors import (
    ERR_CASE_NOT_EXONERATED,
    ERR_CASE_NOT_FOUND,
    ERR_COMPENSATION_CLAIM_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_INVALID_TRANSITION_EVENT,
    ERR_NO_COMPENSATION_STATUTE,
    ERR_PAYMENT_AMOUNT_MISMATCH,
    raise_err,
)
from validation import (
    as_integer,
    as_string,
    body_json,
    reject_unknown,
    req_choice,
    req_field,
    req_int,
    req_str,
)

bp = Blueprint("compensation_claims", __name__)

ADVANCE_EVENTS = ("FILE", "RECORD_DECISION", "APPEAL", "RECORD_PAYMENT")
DECISIONS = ("APPROVED", "DENIED")


def _case_jurisdiction(case):
    ir = db.intake_requests.get(case["intake_request_id"])
    if ir is None:
        return None
    return db.jurisdictions.get(ir["jurisdiction_id"])


@bp.post("/compensation-claims")
def create_compensation_claim():
    require_roles("StaffAttorney")
    body = body_json()
    if "case_id" in body:
        db.lookup(db.cases, body.get("case_id"), ERR_CASE_NOT_FOUND)
    reject_unknown(body, {"case_id", "years_incarcerated_claimed",
                          "documented_legal_fees_cents"})
    case_id = req_str(body, "case_id")
    years_claimed = req_int(body, "years_incarcerated_claimed", minimum=1)
    fees_cents = 0
    if "documented_legal_fees_cents" in body:
        fees_cents = req_int(body, "documented_legal_fees_cents", minimum=0)
    case = db.cases[case_id]
    # priority 4.5: the case must be EXONERATED
    if case["status"] != "EXONERATED":
        raise_err(ERR_CASE_NOT_EXONERATED,
                  "Compensation claim creation requires an EXONERATED case")
    # priority 8(a): a compensation statute must exist
    jurisdiction = _case_jurisdiction(case)
    if jurisdiction is None or not jurisdiction["compensation_statute_exists"]:
        raise_err(ERR_NO_COMPENSATION_STATUTE,
                  "The jurisdiction has no wrongful-conviction compensation statute")
    claim = db.new_entity()
    claim.update({
        "case_id": case_id,
        "years_incarcerated_claimed": years_claimed,
        "documented_legal_fees_cents": fees_cents,
        "provisional_estimate_cents": provisional_compensation_estimate(
            jurisdiction, years_claimed),
        "final_award_cents": None,
        "status": "DRAFT",
        "paid_amount_cents": None,
    })
    db.compensation_claims[claim["id"]] = claim
    return ok(claim, 201)


@bp.post("/compensation-claims/<cid>/advance")
def advance_compensation_claim(cid):
    require_roles("StaffAttorney")
    claim = db.lookup(db.compensation_claims, cid, ERR_COMPENSATION_CLAIM_NOT_FOUND)
    body = body_json()
    reject_unknown(body, {"event", "decision", "paid_amount_cents"})
    event = as_string(req_field(body, "event"), "event")
    if event not in ADVANCE_EVENTS:
        raise_err(ERR_INVALID_TRANSITION_EVENT,
                  "Unknown event for compensation-claim advance: %s" % event)
    decision = None
    paid_amount = None
    if event == "RECORD_DECISION":
        decision = req_choice(body, "decision", DECISIONS)
    elif event == "RECORD_PAYMENT":
        paid_amount = as_integer(req_field(body, "paid_amount_cents"),
                                 "paid_amount_cents")
    status = claim["status"]
    if event == "FILE":
        if status != "DRAFT":
            raise_err(ERR_INVALID_STATE, "FILE requires status DRAFT")
        claim["status"] = "FILED"
    elif event == "RECORD_DECISION":
        if status not in ("FILED", "APPEALED"):
            raise_err(ERR_INVALID_STATE,
                      "RECORD_DECISION requires status FILED or APPEALED")
        if decision == "APPROVED":
            case = db.cases.get(claim["case_id"])
            ir = db.intake_requests.get(case["intake_request_id"]) if case else None
            jurisdiction = _case_jurisdiction(case) if case else None
            claim["final_award_cents"] = final_verified_compensation_award(
                claim, case, ir, jurisdiction)
            claim["status"] = "APPROVED"
        else:
            claim["status"] = "DENIED"
            cascades.apply_claim_denial_cascade(claim)
    elif event == "APPEAL":
        if status != "DENIED":
            raise_err(ERR_INVALID_STATE, "APPEAL requires status DENIED")
        claim["status"] = "APPEALED"
    else:  # RECORD_PAYMENT
        if status != "APPROVED":
            raise_err(ERR_INVALID_STATE, "RECORD_PAYMENT requires status APPROVED")
        if paid_amount != claim["final_award_cents"]:
            raise_err(ERR_PAYMENT_AMOUNT_MISMATCH,
                      "paid_amount_cents must equal final_award_cents exactly")
        claim["paid_amount_cents"] = paid_amount
        claim["status"] = "PAID"
    touch(claim)
    return ok(claim)
