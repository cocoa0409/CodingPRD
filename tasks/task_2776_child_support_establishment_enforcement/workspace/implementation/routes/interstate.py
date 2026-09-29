"""UIFSA interstate referrals: transmittal, registration, return and the
controlling-order determination (PRD 3.7).
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
from services import controlling

DIRECTIONS = ("INITIATING", "RESPONDING")
TRANSMITTAL_TYPES = ("ESTABLISHMENT", "ENFORCEMENT", "MODIFICATION")
RETURNED_REASONS = ("NO_ACK_RECEIVED", "INSUFFICIENT_INFO", "NO_JURISDICTION")
ACK_WINDOW_DAYS = 10

READ_ROLES = ["CaseWorker", "SupervisingAttorney", "InterstateLiaison",
              "ProgramAdmin"]


def _entered_orders(case):
    return [o for o in db.case_orders(case["id"]) if o["status"] == "ENTERED"]


def _settle_role(case, referral):
    """interstate_role returns to NONE once no other live referral remains."""
    if not controlling.live_referrals(case, exclude_id=referral["id"]):
        case["interstate_role"] = "NONE"


def register(app):
    @app.post(PREFIX + "/cases/<case_id>/interstate-referrals")
    def draft_referral(case_id):
        middleware.authenticate(["InterstateLiaison"])
        case = common.case(case_id)
        payload = validate.body()
        direction = validate.req_enum(payload, "direction", DIRECTIONS)
        other_state = validate.req_str(payload, "other_state_code")
        sister_states = [s for s in db.STATE_CODES if s != db.HOME_STATE_CODE]
        if other_state not in sister_states:
            validate.fail("other_state_code must be one of %s."
                          % ", ".join(sister_states))
        child_home = validate.req_str(payload, "child_home_state_code")
        if child_home not in db.STATE_CODES:
            validate.fail("child_home_state_code must be one of %s."
                          % ", ".join(db.STATE_CODES))
        transmittal_type = validate.req_enum(payload, "transmittal_type",
                                             TRANSMITTAL_TYPES)
        common.case_writable(case)

        row = db.stamp_new({
            "case_id": case["id"],
            "direction": direction,
            "other_state_code": other_state,
            "child_home_state_code": child_home,
            "transmittal_type": transmittal_type,
            "status": "DRAFT",
            "transmitted_at": None,
            "ack_due_at": None,
            "registered_at": None,
            "controlling_order_id": None,
            "controlling_order_state_code": None,
            "returned_reason": None,
        })
        db.interstate_referrals[row["id"]] = row
        return response.created(serialize.referral(row))

    @app.get(PREFIX + "/interstate-referrals/<interstate_referral_id>")
    def read_referral(interstate_referral_id):
        middleware.authenticate(READ_ROLES)
        row = common.referral(interstate_referral_id)
        return response.ok(serialize.referral(row))

    @app.get(PREFIX + "/interstate-referrals")
    def list_referrals():
        middleware.authenticate(READ_ROLES)
        response.page_params()
        rows = db.ordered(list(db.interstate_referrals.values()))
        rows = common.apply_filters(rows, [
            ("case_id", "case_id", "str"),
            ("controlling_order_id", "controlling_order_id", "str"),
            ("status", "status", "str"),
            ("direction", "direction", "str"),
            ("other_state_code", "other_state_code", "str"),
        ])
        return response.paginate(rows, serialize.referral)

    @app.post(PREFIX + "/interstate-referrals/<interstate_referral_id>"
                       "/transmittal")
    def transmit(interstate_referral_id):
        middleware.authenticate(["InterstateLiaison"])
        referral = common.referral(interstate_referral_id)
        case = db.cases[referral["case_id"]]
        common.case_writable(case)
        if referral["status"] != "DRAFT" \
                or referral["direction"] != "INITIATING" \
                or not _entered_orders(case):
            raise ApiError("ERR_INVALID_REFERRAL_STATUS")
        if case["good_cause_claim"]:
            raise ApiError("ERR_GOOD_CAUSE_BARS_DISCLOSURE")

        sent_at = db.now()
        referral["status"] = "TRANSMITTED"
        referral["transmitted_at"] = sent_at
        referral["ack_due_at"] = util.add_days(sent_at, ACK_WINDOW_DAYS)
        db.touch(referral)
        case["interstate_role"] = "INITIATING"
        db.touch(case)
        return response.ok(serialize.referral(referral))

    @app.post(PREFIX + "/interstate-referrals/<interstate_referral_id>"
                       "/registration")
    def register_referral(interstate_referral_id):
        middleware.authenticate(["InterstateLiaison"])
        referral = common.referral(interstate_referral_id)
        case = db.cases[referral["case_id"]]
        common.case_writable(case)
        if referral["status"] == "DRAFT":
            # The responding-state path registers a sister state's own order.
            foreign = [o for o in _entered_orders(case)
                       if o["origin_state_code"] == referral["other_state_code"]]
            if referral["direction"] != "RESPONDING" or not foreign:
                raise ApiError("ERR_INVALID_REFERRAL_STATUS")
        elif referral["status"] == "TRANSMITTED":
            # The acknowledgment boundary is inclusive.
            if db.now() > referral["ack_due_at"]:
                raise ApiError("ERR_INVALID_REFERRAL_STATUS")
        else:
            raise ApiError("ERR_INVALID_REFERRAL_STATUS")

        referral["status"] = "REGISTERED"
        referral["registered_at"] = db.now()
        order_id, state_code = controlling.determine(case, referral)
        referral["controlling_order_id"] = order_id
        referral["controlling_order_state_code"] = state_code
        db.touch(referral)
        if referral["direction"] == "RESPONDING":
            case["interstate_role"] = "RESPONDING"
        db.touch(case)
        return response.ok(serialize.referral(referral))

    @app.post(PREFIX + "/interstate-referrals/<interstate_referral_id>/return")
    def return_referral(interstate_referral_id):
        middleware.authenticate(["InterstateLiaison"])
        referral = common.referral(interstate_referral_id)
        case = db.cases[referral["case_id"]]
        payload = validate.body()
        reason = validate.req_enum(payload, "returned_reason", RETURNED_REASONS)
        common.case_writable(case)
        status = referral["status"]
        if status == "TRANSMITTED":
            if reason != "NO_ACK_RECEIVED" \
                    or not (db.now() > referral["ack_due_at"]):
                raise ApiError("ERR_INVALID_REFERRAL_STATUS")
        elif status == "REGISTERED":
            if reason not in ("INSUFFICIENT_INFO", "NO_JURISDICTION"):
                raise ApiError("ERR_INVALID_REFERRAL_STATUS")
        elif status == "ENFORCING":
            live = [a for a in db.case_actions(case["id"])
                    if a["status"] == "ACTIVE"]
            if live:
                raise ApiError("ERR_INVALID_REFERRAL_STATUS")
        else:
            raise ApiError("ERR_INVALID_REFERRAL_STATUS")

        referral["status"] = "RETURNED"
        referral["returned_reason"] = reason
        if status == "REGISTERED":
            referral["controlling_order_id"] = None
            referral["controlling_order_state_code"] = None
        db.touch(referral)
        _settle_role(case, referral)
        db.touch(case)
        return response.ok(serialize.referral(referral))
