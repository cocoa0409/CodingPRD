"""Enforcement remedies: certification, notice, contest, decision, activation
and release (PRD 3.6).
"""
import common
import db
import middleware
import response
import serialize
import util
import validate
from common import PREFIX
from errors import ApiError
from services import cascade, interest, risk

ACTION_TYPES = ("LICENSE_SUSPENSION", "TAX_REFUND_INTERCEPT", "PROPERTY_LIEN",
                "CONTEMPT_REFERRAL", "CREDIT_BUREAU_REPORT")
CONTEST_GROUNDS = ("MISTAKE_OF_FACT", "IDENTITY", "PAYMENT_MADE",
                   "INABILITY_TO_PAY")
REVIEW_DECISIONS = ("UPHOLD", "VACATE")
RELEASE_REASONS = ("ARREARS_SATISFIED", "COMPROMISE_ACCEPTED", "ORDER_VACATED",
                   "PLAN_COMPLIANT", "INTERCEPT_REVERSED")

CONTEST_WINDOW_DAYS = 30
DELINQUENCY_MULTIPLE = 2

# Fixed per remedy; TAX_REFUND_INTERCEPT is the one assistance-conditional row.
THRESHOLDS = {
    "LICENSE_SUSPENSION": 300000,
    "PROPERTY_LIEN": 500000,
    "CONTEMPT_REFERRAL": 1000000,
    "CREDIT_BUREAU_REPORT": 100000,
}
TAX_INTERCEPT_TANF_CENTS = 15000
TAX_INTERCEPT_NON_TANF_CENTS = 50000

READ_ROLES = ["CaseWorker", "SupervisingAttorney", "InterstateLiaison",
              "ProgramAdmin", "NoncustodialParty"]
LIST_ROLES = ["CaseWorker", "SupervisingAttorney", "InterstateLiaison",
              "ProgramAdmin"]


def threshold_for(action_type, case):
    if action_type == "TAX_REFUND_INTERCEPT":
        return (TAX_INTERCEPT_TANF_CENTS if case["tanf_assistance"]
                else TAX_INTERCEPT_NON_TANF_CENTS)
    return THRESHOLDS[action_type]


def _current_support_monthly(case):
    """The most recently created ENTERED CURRENT_SUPPORT order's obligation."""
    entered = [o for o in db.case_orders(case["id"])
               if o["status"] == "ENTERED" and o["order_type"] == "CURRENT_SUPPORT"]
    if not entered:
        return 0
    return entered[-1]["monthly_obligation_cents"] or 0


def activate(action, case, cascade_referral):
    """The shared ACTIVE join point (PRD 3.6)."""
    participant = db.participants.get(case["noncustodial_party_id"])
    action["status"] = "ACTIVE"
    action["activated_at"] = db.now()
    action["remedy_applied"] = True
    db.touch(action)
    if participant is not None:
        cascade.apply_remedy_flag(participant, action["action_type"])
        db.touch(participant)
    case["enforcement_posture"] = "ESCALATED"
    db.touch(case)
    if cascade_referral:
        for referral in db.case_referrals(case["id"]):
            if referral["status"] == "REGISTERED" \
                    and referral["transmittal_type"] == "ENFORCEMENT":
                referral["status"] = "ENFORCING"
                db.touch(referral)


def register(app):
    @app.post(PREFIX + "/cases/<case_id>/enforcement-actions")
    def propose(case_id):
        middleware.authenticate(["CaseWorker"])
        case = common.case(case_id)
        payload = validate.body()
        action_type = validate.req_enum(payload, "action_type", ACTION_TYPES)
        common.case_writable(case)

        ncp = db.participants[case["noncustodial_party_id"]]
        certified = interest.certified_arrears(case)
        threshold = threshold_for(action_type, case)
        floor = DELINQUENCY_MULTIPLE * _current_support_monthly(case)
        eligible = certified >= threshold and certified >= floor
        if eligible and action_type == "CONTEMPT_REFERRAL":
            _score, enforcement_tier, _c, _ct = risk.scores(ncp)
            eligible = enforcement_tier == "HIGH"
        if not eligible:
            raise ApiError("ERR_ARREARS_BELOW_ENFORCEMENT_THRESHOLD")

        row = db.stamp_new({
            "case_id": case["id"],
            "action_type": action_type,
            "status": "PROPOSED",
            "arrears_certified_snapshot_cents": certified,
            "eligibility_threshold_cents": threshold,
            "notice_sent_at": None,
            "contest_deadline_at": None,
            "contested_at": None,
            "contest_grounds": None,
            "review_decision": None,
            "proposed_by_user_id": middleware.user_id(),
            "review_decided_by_user_id": None,
            "activated_at": None,
            "released_at": None,
            "release_reason": None,
            "remedy_applied": False,
        })
        db.enforcement_actions[row["id"]] = row
        return response.created(serialize.enforcement_action(row))

    @app.get(PREFIX + "/enforcement-actions/<enforcement_action_id>")
    def read_action(enforcement_action_id):
        middleware.authenticate(READ_ROLES)
        row = common.enforcement_action(enforcement_action_id)
        common.party_guard(db.cases[row["case_id"]])
        return response.ok(serialize.enforcement_action(row))

    @app.get(PREFIX + "/enforcement-actions")
    def list_actions():
        middleware.authenticate(LIST_ROLES)
        response.page_params()
        rows = db.ordered(list(db.enforcement_actions.values()))
        rows = common.apply_filters(rows, [
            ("case_id", "case_id", "str"),
            ("action_type", "action_type", "str"),
            ("status", "status", "str"),
        ])
        return response.paginate(rows, serialize.enforcement_action)

    @app.post(PREFIX + "/enforcement-actions/<enforcement_action_id>/notice")
    def send_notice(enforcement_action_id):
        middleware.authenticate(["CaseWorker"])
        action = common.enforcement_action(enforcement_action_id)
        case = db.cases[action["case_id"]]
        common.case_writable(case)
        if action["status"] != "PROPOSED":
            raise ApiError("ERR_INVALID_ACTION_STATUS")
        if case["good_cause_claim"]:
            raise ApiError("ERR_GOOD_CAUSE_BARS_DISCLOSURE")
        if case["enforcement_posture"] == "STAYED":
            raise ApiError("ERR_ENFORCEMENT_STAYED")

        sent_at = db.now()
        action["status"] = "NOTICE_SENT"
        action["notice_sent_at"] = sent_at
        action["contest_deadline_at"] = util.add_days(sent_at, CONTEST_WINDOW_DAYS)
        db.touch(action)
        return response.ok(serialize.enforcement_action(action))

    @app.post(PREFIX + "/enforcement-actions/<enforcement_action_id>/contest")
    def contest(enforcement_action_id):
        middleware.authenticate(["NoncustodialParty"])
        action = common.enforcement_action(enforcement_action_id)
        case = db.cases[action["case_id"]]
        middleware.require_case_party(case)
        payload = validate.body()
        grounds = validate.req_enum(payload, "contest_grounds", CONTEST_GROUNDS)
        common.case_writable(case)
        if action["status"] != "NOTICE_SENT":
            raise ApiError("ERR_INVALID_ACTION_STATUS")
        # The window is inclusive: an instant equal to the deadline is timely.
        if db.now() > action["contest_deadline_at"]:
            raise ApiError("ERR_CONTEST_WINDOW_CLOSED")

        action["status"] = "CONTESTED"
        action["contested_at"] = db.now()
        action["contest_grounds"] = grounds
        db.touch(action)
        return response.ok(serialize.enforcement_action(action))

    @app.post(PREFIX + "/enforcement-actions/<enforcement_action_id>"
                       "/review-decision")
    def review_decision(enforcement_action_id):
        middleware.authenticate(["SupervisingAttorney"])
        action = common.enforcement_action(enforcement_action_id)
        case = db.cases[action["case_id"]]
        payload = validate.body()
        decision = validate.req_enum(payload, "review_decision", REVIEW_DECISIONS)
        common.case_writable(case)
        if action["status"] != "CONTESTED":
            raise ApiError("ERR_INVALID_ACTION_STATUS")
        if middleware.user_id() == action["proposed_by_user_id"]:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES")

        action["review_decision"] = decision
        action["review_decided_by_user_id"] = middleware.user_id()
        if decision == "UPHOLD":
            activate(action, case, cascade_referral=False)
        else:
            action["status"] = "DENIED"
            db.touch(action)
        return response.ok(serialize.enforcement_action(action))

    @app.post(PREFIX + "/enforcement-actions/<enforcement_action_id>/activation")
    def activation(enforcement_action_id):
        middleware.authenticate(["CaseWorker"])
        action = common.enforcement_action(enforcement_action_id)
        case = db.cases[action["case_id"]]
        common.case_writable(case)
        if action["status"] != "NOTICE_SENT":
            raise ApiError("ERR_INVALID_ACTION_STATUS")
        # The obligor is entitled to the whole window, so entry is strict.
        if not (db.now() > action["contest_deadline_at"]):
            raise ApiError("ERR_CONTEST_WINDOW_OPEN")
        if case["enforcement_posture"] == "STAYED":
            raise ApiError("ERR_ENFORCEMENT_STAYED")

        activate(action, case, cascade_referral=True)
        return response.ok(serialize.enforcement_action(action))

    @app.post(PREFIX + "/enforcement-actions/<enforcement_action_id>/release")
    def release(enforcement_action_id):
        middleware.authenticate(["SupervisingAttorney"])
        action = common.enforcement_action(enforcement_action_id)
        case = db.cases[action["case_id"]]
        payload = validate.body()
        reason = validate.req_enum(payload, "release_reason", RELEASE_REASONS)
        common.case_writable(case)
        if action["status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_ACTION_STATUS")
        cascade.release_action(action, case, reason)
        return response.ok(serialize.enforcement_action(action))
