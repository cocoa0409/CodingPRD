"""Transport legs, escalation, the four outcomes and abandonment (PRD 3.7-3.9)."""
from flask import Blueprint

import calc
import services as S
import store as C
from authz import ALL_ROLES, authenticate
from envelope import created, obj, unpaginated
from errors import fail
from store import store
from util import public, public_list
from validators import json_body, opt_int, present, req_enum, req_int, req_str

bp = Blueprint("adjudication", __name__)


@bp.route("/arbitration/cases/<case_id>/transport-legs", methods=["POST"])
def record_leg(case_id):
    authenticate(["AuctionAdmin"])
    body = json_body()
    leg_type = req_enum(body, "leg_type", C.LEG_TYPES)
    miles = req_int(body, "miles", 0)
    carrier_name = req_str(body, "carrier_name", 1, 120)
    expected_case_version = req_int(body, "expected_case_version")
    case = S.get_case(case_id)
    if expected_case_version != int(case["version"]):
        fail("ERR_STALE_CASE_VERSION")
    if case["status"] not in C.NON_TERMINAL_CASE_STATUSES:
        fail("ERR_INVALID_CASE_STATE")
    S.touch(case)
    row = {
        "case_id": case["id"],
        "leg_type": leg_type,
        "miles": miles,
        "carrier_name": carrier_name,
        "cost_cents": calc.leg_cost_cents(miles),
        "recorded_at_utc": store.now_iso(),
        "case_version_after": int(case["version"]),
    }
    store.insert("legs", row, mutable=False)
    return created(public(row))


@bp.route("/arbitration/cases/<case_id>/transport-legs", methods=["GET"])
def list_legs(case_id):
    authenticate(ALL_ROLES)
    case = S.get_case(case_id)
    return unpaginated(public_list(S.children("legs", "case_id", case["id"])))


@bp.route("/arbitration/cases/<case_id>/escalate", methods=["POST"])
def escalate(case_id):
    authenticate(["Arbitrator"])
    body = json_body()
    req_str(body, "escalation_note")
    case = S.get_case(case_id)
    if case["status"] not in ("NEGOTIATION", "COUNTERED"):
        fail("ERR_INVALID_CASE_STATE")
    exhausted = (int(case["current_round_index"]) >= C.MAX_NEGOTIATION_ROUNDS
                 or bool(case["seller_response_timed_out"]))
    if not exhausted:
        fail("ERR_NEGOTIATION_NOT_EXHAUSTED")
    S.supersede_rounds(case, ("OPEN", "COUNTERED"))
    case["status"] = "ARBITRATOR_REVIEW"
    S.touch(case)
    return obj(public(case))


@bp.route("/arbitration/cases/<case_id>/decision", methods=["POST"])
def decide(case_id):
    role, user_id = authenticate(["Arbitrator"])
    body = json_body()
    outcome = req_enum(body, "outcome", C.OUTCOMES)
    fault_party = req_enum(body, "fault_party", C.FAULT_PARTIES)
    rationale = req_str(body, "rationale", 1, 1000)
    requested = None
    if outcome == "REPAIR_ALLOWANCE":
        requested = req_int(body, "requested_allowance_cents", 0)
    elif present(body, "requested_allowance_cents"):
        opt_int(body, "requested_allowance_cents", 0)

    case = S.get_case(case_id)
    if case["intake_arbitrator_user_id"] is not None \
            and case["intake_arbitrator_user_id"] == user_id:
        fail("ERR_SEGREGATION_OF_DUTIES")
    if case["status"] != "ARBITRATOR_REVIEW":
        fail("ERR_INVALID_CASE_STATE")
    sale = S.get_sale(case["sale_id"])
    buyer = S.get_buyer(case["claimant_buyer_id"])
    seller = S.get_seller(sale["seller_id"])
    policy = S.get_policy(case["policy_id"])

    if outcome != "UNWIND":
        if case["seller_conceded"]:
            fail("ERR_UNWIND_MANDATORY")
        if outcome == "REPAIR_ALLOWANCE" and int(policy["max_allowance_bps"]) <= 0:
            fail("ERR_UNWIND_MANDATORY")
    if outcome == "REPAIR_ALLOWANCE":
        if (case["defect_class"] != "MILEAGE_DISCREPANCY"
                and int(case["latest_verified_estimate_cents"]) <= 0):
            fail("ERR_THIRD_PARTY_VERIFICATION_REQUIRED")
        if requested > calc.allowance_cap_cents(sale, policy):
            fail("ERR_ALLOWANCE_EXCEEDS_CAP")

    decision = S.render_decision(case, sale, buyer, seller, policy, outcome, fault_party,
                                 rationale, requested, user_id)
    return created(public(decision))


@bp.route("/arbitration/cases/<case_id>/decision", methods=["GET"])
def read_decision(case_id):
    authenticate(ALL_ROLES)
    case = S.get_case(case_id)
    return unpaginated(public_list(S.children("decisions", "case_id", case["id"])))


@bp.route("/arbitration/cases/<case_id>/ledger-entries", methods=["GET"])
def list_case_ledger(case_id):
    authenticate(ALL_ROLES)
    case = S.get_case(case_id)
    return unpaginated(public_list(S.children("ledger", "case_id", case["id"])))


@bp.route("/arbitration/cases/<case_id>/withdraw", methods=["POST"])
def withdraw(case_id):
    role, user_id = authenticate(["BuyerRep"])
    body = json_body()
    req_str(body, "withdraw_reason")
    case = S.get_case(case_id)
    if case["claimant_buyer_id"] != user_id:
        fail("ERR_NOT_CASE_OWNER")
    if case["status"] not in ("SUBMITTED", "UNDER_REVIEW", "NEGOTIATION", "COUNTERED"):
        fail("ERR_INVALID_CASE_STATE")
    sale = S.get_sale(case["sale_id"])
    buyer = S.get_buyer(case["claimant_buyer_id"])
    seller = S.get_seller(sale["seller_id"])
    case["status"] = "WITHDRAWN"
    S.supersede_rounds(case, ("OPEN", "COUNTERED"))
    S.open_claim_release(sale, buyer, seller, resolved=False)
    S.touch(case)
    return obj(public(case))


@bp.route("/arbitration/cases/<case_id>/frivolous-fees", methods=["GET"])
def list_case_fees(case_id):
    authenticate(ALL_ROLES)
    case = S.get_case(case_id)
    return unpaginated(public_list(S.children("fees", "case_id", case["id"])))


@bp.route("/arbitration/cases/<case_id>/policy-actions", methods=["GET"])
def list_case_actions(case_id):
    authenticate(ALL_ROLES)
    case = S.get_case(case_id)
    return unpaginated(
        public_list(S.children("policy_actions", "triggered_by_case_id", case["id"])))
