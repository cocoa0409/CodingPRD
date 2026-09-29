"""Regulatory escalation and challenges to the tariff itself (PRD §3.9).

The regulator's order is recorded, not posted: nothing in this module moves a
charge, an invoice total or a consignee's credit balance.
"""

from flask import Blueprint, request

import guards
import schema
from auth import (ROLE_BILLING, ROLE_CUSTOMER, ROLE_RAILROAD, ROLE_REGULATOR,
                  authenticate, require_owner)
from calc import COMPLAINT_RESPONSE_DAYS
from clockcal import date_of, eod, nth_business
from derive import complaint_json
from envelope import listing, ok
from errors import fail
from store import base_record, db, touch

bp = Blueprint("regulatory", __name__)

COMPLAINT_TYPES = ("RULE_REASONABLENESS", "BILLING_PRACTICE")
OUTCOMES = ("DECIDED_FOR_CUSTOMER", "DECIDED_FOR_RAILROAD", "DISMISSED")
OPEN_COMPLAINT_STATUSES = ("FILED", "RAILROAD_ANSWERED")


def _docket_number():
    """`D-` plus the zero-padded one-based position among all complaints."""
    return "D-%05d" % (len(db.complaints) + 1)


# --------------------------------------------------------------------------
# filing
# --------------------------------------------------------------------------

@bp.post("/regulatory-complaints")
def create_complaint():
    actor = authenticate(ROLE_CUSTOMER)
    data = schema.body()
    with db.lock:
        # Band 7: the two body references, in their declared order.  Ownership
        # (band 4) is applied the moment the dispute makes the owner knowable.
        dispute = tariff = None
        raw_dispute = schema.opt_ref(data, "demurrage_dispute_id")
        if raw_dispute is not None:
            dispute = guards.dispute(raw_dispute)
            require_owner(actor, dispute["customer_id"])
        raw_tariff = schema.opt_ref(data, "tariff_rule_set_id")
        if raw_tariff is not None:
            tariff = guards.tariff(raw_tariff)

        # Band 8.
        dispute_id = schema.req_ref(data, "demurrage_dispute_id")
        complaint_type = schema.req_enum(data, "complaint_type", COMPLAINT_TYPES)
        narrative = schema.req_str(data, "docket_narrative", 1, 2000)
        tariff_id = schema.opt_ref(data, "tariff_rule_set_id")

        # Band 10: not DECIDED at all is a state failure, and it is reported
        # ahead of the narrower exhaustion failure.
        if dispute["status"] != "DECIDED":
            fail("ERR_DISPUTE_INVALID_STATE",
                 "Only a DECIDED dispute can be escalated to the regulator.")

        # Band 14: the type/tariff pairing rule.
        if complaint_type == "RULE_REASONABLENESS" and tariff_id is None:
            fail("ERR_DISPUTE_SCOPE_MISMATCH",
                 "A RULE_REASONABLENESS complaint must cite a tariff rule set.")
        if complaint_type == "BILLING_PRACTICE" and tariff_id is not None:
            fail("ERR_DISPUTE_SCOPE_MISMATCH",
                 "A BILLING_PRACTICE complaint must not cite a tariff rule set.")

        # Band 27: exhaustion, reserved for a DECIDED dispute that never
        # reached appeal.
        if dispute["round_number"] < 2:
            fail("ERR_APPEAL_NOT_EXHAUSTED",
                 "The dispute was decided without ever being appealed.")

        filed_at = db.now()
        rec = base_record("complaint")
        rec.update({
            "demurrage_dispute_id": dispute_id,
            "tariff_rule_set_id": tariff_id,
            "complaint_type": complaint_type,
            "docket_narrative": narrative,
            "docket_number": _docket_number(),
            "filed_at": filed_at,
            "response_due_at": eod(
                nth_business(date_of(filed_at), COMPLAINT_RESPONSE_DAYS)),
            "answer_narrative": None,
            "ordered_credit_cents": 0,
            "status": "FILED",
        })
        db.complaints[rec["id"]] = rec

        # Cascade one: the dispute escalates.  §3.9 declares no version
        # increment on it, so per §2.9 none occurs.
        dispute["status"] = "ESCALATED"

        # Cascade two: a rule-reasonableness complaint challenges the tariff.
        # A challenged rule set stays in force.  §3.9 declares the increment of
        # challenge_count here but no version increment - unlike the decision,
        # which states one explicitly.
        if complaint_type == "RULE_REASONABLENESS" and tariff is not None:
            tariff["challenge_count"] += 1
            if tariff["status"] == "PUBLISHED":
                tariff["status"] = "CHALLENGED"
        return ok(complaint_json(rec), 201)


# --------------------------------------------------------------------------
# reads
# --------------------------------------------------------------------------

@bp.get("/regulatory-complaints/<coid>")
def get_complaint(coid):
    actor = authenticate(ROLE_CUSTOMER, ROLE_RAILROAD, ROLE_REGULATOR,
                         ROLE_BILLING)
    with db.lock:
        rec = guards.complaint(coid)
        require_owner(actor, guards.owner_of_complaint(rec))
        return ok(complaint_json(rec))


@bp.get("/regulatory-complaints")
def list_complaints():
    actor = authenticate(ROLE_CUSTOMER, ROLE_RAILROAD, ROLE_REGULATOR,
                         ROLE_BILLING)
    with db.lock:
        rows = db.ordered("complaints")
        for name in ("demurrage_dispute_id", "tariff_rule_set_id", "status"):
            value = request.args.get(name)
            if value is not None:
                rows = [r for r in rows if r[name] == value]
        if actor.is_customer:
            rows = [r for r in rows
                    if guards.owner_of_complaint(r) == actor.user_id]
        return listing(rows, complaint_json)


# --------------------------------------------------------------------------
# the railroad's answer
# --------------------------------------------------------------------------

@bp.post("/regulatory-complaints/<coid>/answer")
def answer_complaint(coid):
    authenticate(ROLE_RAILROAD)
    with db.lock:
        rec = guards.complaint(coid)
        data = schema.body()
        narrative = schema.req_str(data, "answer_narrative", 1, 2000)

        if rec["status"] != "FILED":
            fail("ERR_COMPLAINT_INVALID_STATE",
                 "Only a FILED complaint can be answered.")

        rec["answer_narrative"] = narrative
        rec["status"] = "RAILROAD_ANSWERED"
        touch(rec)
        return ok(complaint_json(rec))


# --------------------------------------------------------------------------
# the regulator's decision
# --------------------------------------------------------------------------

def _still_cited(tariff_id, deciding_id):
    """True while another unresolved complaint cites this rule set."""
    for other in db.complaints.values():
        if other["id"] == deciding_id:
            continue
        if (other["tariff_rule_set_id"] == tariff_id
                and other["status"] in OPEN_COMPLAINT_STATUSES):
            return True
    return False


@bp.post("/regulatory-complaints/<coid>/decide")
def decide_complaint(coid):
    authenticate(ROLE_REGULATOR)
    with db.lock:
        rec = guards.complaint(coid)
        data = schema.body()
        outcome = schema.req_enum(data, "outcome", OUTCOMES)
        ordered = schema.req_int(data, "ordered_credit_cents", 0)

        if rec["status"] != "RAILROAD_ANSWERED":
            fail("ERR_COMPLAINT_INVALID_STATE",
                 "Only a RAILROAD_ANSWERED complaint can be decided.")

        dispute = db.disputes.get(rec["demurrage_dispute_id"])
        claimed = 0 if dispute is None else dispute["claimed_credit_cents"]

        # Band 25: both money rules report the same code.
        if ordered != 0 and outcome != "DECIDED_FOR_CUSTOMER":
            fail("ERR_ORDERED_CREDIT_EXCEEDS_CLAIM",
                 "Only a decision for the consignee may order credit.")
        if ordered > claimed:
            fail("ERR_ORDERED_CREDIT_EXCEEDS_CLAIM",
                 "The ordered credit exceeds the escalated dispute's claim.")

        rec["ordered_credit_cents"] = ordered
        rec["status"] = outcome
        touch(rec)

        # The tariff's own loop closes here, and this is the one place §3.9
        # declares a version increment on the rule set.
        if rec["complaint_type"] == "RULE_REASONABLENESS":
            tariff = db.tariffs.get(rec["tariff_rule_set_id"])
            if tariff is not None and tariff["status"] == "CHALLENGED":
                if outcome == "DECIDED_FOR_CUSTOMER":
                    tariff["status"] = "WITHDRAWN"
                    touch(tariff)
                elif not _still_cited(tariff["id"], rec["id"]):
                    # challenge_count is preserved, not reset.
                    tariff["status"] = "PUBLISHED"
                    touch(tariff)

        # The order is recorded, not posted: the dispute stays ESCALATED and no
        # charge, invoice or credit balance moves.
        return ok(complaint_json(rec))
