"""Bid packages: support letters, incentive requests, fund decisions,
submission and the planner's verdict (PRD 3.7, 3.8)."""

from flask import Blueprint, request

import aggregates
import calc
import domain
import impact
import queries
import resolve
import serialize
from auth import (BOARD_ANALYST, BUREAU_ADMIN, INCENTIVE_APPROVER,
                  MEETING_PLANNER, SALES_MANAGER, caller_id, endpoint,
                  require_owner)
from errors import ApiError, bad_request
from response import created, list_response, object_response, pagination
from store import db, ordered, touch
from validation import (body_json, opt_enum, query_enum, query_str, req_enum,
                        req_instant, req_int, req_money, req_ref, req_str,
                        req_str_list)

bp = Blueprint("bids", __name__)

READ_ROLES = (BUREAU_ADMIN, SALES_MANAGER, INCENTIVE_APPROVER, BOARD_ANALYST)


@bp.route("/bid-packages", methods=["POST"])
@endpoint(SALES_MANAGER)
def create_package():
    body = body_json()
    opportunity_id = req_ref(body, "opportunity_id")
    expected_version = req_int(body, "expected_opportunity_version", minimum=0)
    opportunity = resolve.opportunity(opportunity_id)

    if expected_version != opportunity["version"]:
        raise ApiError("ERR_STALE_OPPORTUNITY_VERSION",
                       "The opportunity has moved on since it was read.")
    if opportunity["sales_stage"] != "QUALIFIED":
        raise ApiError("ERR_INVALID_OPPORTUNITY_STAGE",
                       "A bid package is opened only against a QUALIFIED lead.")
    if queries.live_package(opportunity["id"]) is not None:
        raise ApiError("ERR_BID_ROUND_LIMIT_REACHED",
                       "A package of this lead is still live.")

    row = db.new_row()
    row.update({
        "opportunity_id": opportunity["id"],
        "round_number": 1,
        "status": "DRAFT",
        "prepared_by_user_id": caller_id(),
        "incentive_requested_by_user_id": None,
        "incentive_request_amount": None,
        "incentive_cap_amount": None,
        "service_commitment_codes": [],
        "support_letter_type_count": 0,
        "approved_incentive_amount": None,
        "admin_fee_amount": None,
        "total_fund_charge_amount": None,
        "tax_payback_ratio": None,
        "submitted_at": None,
        "response_due_at": None,
        "planner_response": None,
        "decline_reason": None,
        "_fund_id": None,
        "_charge_live": False,
    })
    db.bid_packages[row["id"]] = row
    touch(opportunity)
    return created(serialize.bid_package(row))


@bp.route("/bid-packages/<row_id>", methods=["GET"])
@endpoint(BUREAU_ADMIN, SALES_MANAGER, INCENTIVE_APPROVER, MEETING_PLANNER,
          BOARD_ANALYST)
def get_package(row_id):
    return object_response(serialize.bid_package(resolve.bid_package(row_id)))


@bp.route("/bid-packages", methods=["GET"])
@endpoint(*READ_ROLES)
def list_packages():
    opportunity_id = query_str(request.args, "opportunity_id")
    status = query_enum(request.args, "status", domain.BID_STATUSES)
    limit, offset = pagination(request.args)
    rows = ordered(list(db.bid_packages.values()))
    if opportunity_id is not None:
        rows = [r for r in rows if r["opportunity_id"] == opportunity_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return list_response(rows, serialize.bid_package, limit, offset)


@bp.route("/bid-packages/<row_id>/support-letters", methods=["POST"])
@endpoint(SALES_MANAGER)
def add_letter(row_id):
    package = resolve.bid_package(row_id)
    body = body_json()
    organization_name = req_str(body, "organization_name", min_len=1, max_len=120)
    letter_type = req_enum(body, "letter_type", domain.LETTER_TYPES)

    if package["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_BID_STATE",
                       "Letters are attached only while the package is DRAFT.")

    row = db.new_row(versioned=False)
    row.update({
        "bid_package_id": package["id"],
        "organization_name": organization_name,
        "letter_type": letter_type,
        "received_at": db.clock,
    })
    db.support_letters[row["id"]] = row

    # breadth, not volume: the count of DISTINCT letter_type values attached
    types = {letter["letter_type"]
             for letter in queries.letters_of_package(package["id"])}
    package["support_letter_type_count"] = len(types)
    touch(package)
    return created(serialize.support_letter(row))


@bp.route("/bid-packages/<row_id>/support-letters", methods=["GET"])
@endpoint(BUREAU_ADMIN, SALES_MANAGER, INCENTIVE_APPROVER)
def list_letters(row_id):
    package = resolve.bid_package(row_id)
    letter_type = query_enum(request.args, "letter_type", domain.LETTER_TYPES)
    limit, offset = pagination(request.args)
    rows = queries.letters_of_package(package["id"])
    if letter_type is not None:
        rows = [r for r in rows if r["letter_type"] == letter_type]
    return list_response(rows, serialize.support_letter, limit, offset)


@bp.route("/bid-packages/<row_id>/request-incentive", methods=["POST"])
@endpoint(SALES_MANAGER)
def request_incentive(row_id):
    package = resolve.bid_package(row_id)
    body = body_json()
    amount = req_money(body, "incentive_request_amount")
    codes = req_str_list(body, "service_commitment_codes")

    if package["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_BID_STATE",
                       "An incentive is requested only from a DRAFT package.")

    opportunity = db.opportunities.get(package["opportunity_id"])
    planner = db.planners.get(opportunity["planner_id"])
    package["incentive_request_amount"] = amount
    package["service_commitment_codes"] = codes
    package["incentive_requested_by_user_id"] = caller_id()
    package["status"] = "INCENTIVE_PENDING"

    # a fresh PROVISIONAL snapshot, and the cap read from it -- the cap is
    # deliberately not enforced here, only at decision time
    estimate = impact.create_estimate(opportunity, "PROVISIONAL")
    package["incentive_cap_amount"] = calc.incentive_cap(
        opportunity, planner, estimate, fund=None)
    touch(package)
    return object_response(serialize.bid_package(package))


@bp.route("/bid-packages/<row_id>/incentive-decisions", methods=["POST"])
@endpoint(INCENTIVE_APPROVER)
def decide(row_id):
    package = resolve.bid_package(row_id)
    body = body_json()
    fund_id = req_ref(body, "fund_id")
    verdict = req_enum(body, "decision", domain.DECISIONS)
    approved = req_money(body, "approved_amount", positive=False)
    rationale = req_str(body, "rationale", min_len=1, max_len=500)
    expected_fund_version = req_int(body, "expected_fund_version", minimum=0)
    if verdict == "REJECTED" and approved != 0:
        raise bad_request("A REJECTED decision must approve exactly 0.")
    if verdict == "REDUCED" and approved <= 0:
        raise bad_request("A REDUCED decision must approve more than zero.")

    fund = resolve.fund(fund_id)
    if expected_fund_version != fund["version"]:
        raise ApiError("ERR_STALE_FUND_VERSION",
                       "The fund's balances have moved since they were read.")
    if package["status"] != "INCENTIVE_PENDING":
        raise ApiError("ERR_INVALID_BID_STATE",
                       "A decision is taken only on an INCENTIVE_PENDING package.")
    # segregation of duties is checked before any money question is asked
    actor = caller_id()
    if actor in (package["prepared_by_user_id"],
                 package["incentive_requested_by_user_id"]):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The officer who assembled or requested the incentive may "
                       "never decide it.")

    requested = package["incentive_request_amount"]
    if verdict == "APPROVED" and approved != requested:
        raise bad_request(
            "An APPROVED decision must approve exactly the requested amount.")
    if verdict == "REDUCED" and approved >= requested:
        raise bad_request(
            "A REDUCED decision must approve less than the requested amount.")

    opportunity = db.opportunities.get(package["opportunity_id"])
    planner = db.planners.get(opportunity["planner_id"])
    estimate = queries.newest_provisional_estimate(opportunity["id"])
    fee = None
    total = None
    ratio = None

    if verdict in ("APPROVED", "REDUCED"):
        if fund["posture"] == "EXHAUSTED":
            raise ApiError("ERR_FUND_EXHAUSTED",
                           "An exhausted fund refuses every new charge.")
        cap = calc.incentive_cap(opportunity, planner, estimate, fund=fund)
        if approved > cap:
            raise ApiError("ERR_INCENTIVE_EXCEEDS_CAP",
                           "The approved amount exceeds the incentive cap.")
        fee, total = calc.charge_composition(approved)
        if total > fund["uncommitted_amount"]:
            raise ApiError("ERR_FUND_INSUFFICIENT",
                           "The fund has less uncommitted money than the charge.")
        tax_yield = estimate["lodging_tax_yield_amount"] if estimate else 0
        ratio = calc.payback_ratio(tax_yield, total)
        if ratio is None or ratio < domain.TAX_PAYBACK_FLOOR:
            raise ApiError("ERR_TAX_PAYBACK_BELOW_FLOOR",
                           "The projected lodging tax does not pay back the charge "
                           "three times over.")

    row = db.new_row(versioned=False)
    row.update({
        "bid_package_id": package["id"],
        "fund_id": fund["id"],
        "decision": verdict,
        "requested_amount": requested,
        "approved_amount": approved,
        "admin_fee_amount": fee,
        "total_charge_amount": total,
        "tax_payback_ratio": ratio,
        "decided_by_user_id": actor,
        "rationale": rationale,
    })
    db.decisions[row["id"]] = row

    if verdict == "REJECTED":
        # a compensating revert: no charge was ever created, no round consumed,
        # and yet the fund's version still advances
        package["status"] = "DRAFT"
        package["incentive_request_amount"] = None
        touch(package)
        touch(fund)
    else:
        package["approved_incentive_amount"] = approved
        package["admin_fee_amount"] = fee
        package["total_fund_charge_amount"] = total
        package["tax_payback_ratio"] = ratio
        package["status"] = "APPROVED"
        package["_fund_id"] = fund["id"]
        package["_charge_live"] = True
        touch(package)
        aggregates.fund_commit(fund, total)
    return created(serialize.decision(row))


@bp.route("/bid-packages/<row_id>/incentive-decisions", methods=["GET"])
@endpoint(*READ_ROLES)
def list_decisions(row_id):
    package = resolve.bid_package(row_id)
    verdict = query_enum(request.args, "decision", domain.DECISIONS)
    limit, offset = pagination(request.args)
    rows = queries.decisions_of_package(package["id"])
    if verdict is not None:
        rows = [r for r in rows if r["decision"] == verdict]
    return list_response(rows, serialize.decision, limit, offset)


@bp.route("/bid-packages/<row_id>/submit", methods=["POST"])
@endpoint(SALES_MANAGER)
def submit(row_id):
    package = resolve.bid_package(row_id)
    body = body_json()
    response_due_at = req_instant(body, "response_due_at")
    if response_due_at <= db.clock:
        raise bad_request(
            "Field 'response_due_at' must be strictly later than the clock.")

    opportunity = db.opportunities.get(package["opportunity_id"])
    if package["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_BID_STATE",
                       "Only an APPROVED package may be submitted.")
    if opportunity["sales_stage"] != "QUALIFIED":
        raise ApiError("ERR_INVALID_OPPORTUNITY_STAGE",
                       "The lead must still be QUALIFIED at submission.")
    active = [h for h in queries.holds_of_opportunity(opportunity["id"])
              if h["status"] in ("HELD", "CHALLENGED", "CONFIRMED")]
    if not active:
        raise ApiError("ERR_NO_ACTIVE_SPACE_HOLD",
                       "The lead holds no space to promise.")
    if package["support_letter_type_count"] < domain.SUPPORT_LETTER_TYPE_MINIMUM:
        raise ApiError("ERR_SUPPORT_LETTERS_INSUFFICIENT",
                       "Two letters of the same constituency do not satisfy the "
                       "community-support requirement.")
    if opportunity["block_coverage_pct"] < domain.BLOCK_COVERAGE_FLOOR:
        raise ApiError("ERR_BLOCK_COVERAGE_INSUFFICIENT",
                       "The citywide block is less than 85 percent assembled.")
    if (opportunity["cutoff_alignment_spread_days"]
            > domain.CUTOFF_SPREAD_TOLERANCE_DAYS):
        raise ApiError("ERR_CUTOFF_MISALIGNED",
                       "The block cannot be advertised with a single citywide "
                       "cutoff.")

    package["submitted_at"] = db.clock
    package["response_due_at"] = response_due_at
    package["status"] = "SUBMITTED"
    touch(package)
    opportunity["sales_stage"] = "BIDDING"
    touch(opportunity)
    planner = db.planners.get(opportunity["planner_id"])
    aggregates.set_last_touch(planner)
    touch(planner)
    return object_response(serialize.bid_package(package))


@bp.route("/bid-packages/<row_id>/planner-response", methods=["POST"])
@endpoint(MEETING_PLANNER)
def planner_response(row_id):
    package = resolve.bid_package(row_id)
    opportunity = db.opportunities.get(package["opportunity_id"])
    require_owner(opportunity["planner_id"],
                  "A planner may only answer a bid addressed to it.")
    body = body_json()
    verdict = req_enum(body, "response", domain.PLANNER_RESPONSES)
    decline_reason = opt_enum(body, "decline_reason", domain.DECLINE_REASONS)

    if package["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_BID_STATE",
                       "Only a SUBMITTED package may be answered.")
    if package["response_due_at"] is not None and db.clock > package["response_due_at"]:
        raise ApiError("ERR_CHALLENGE_WINDOW_CLOSED",
                       "The planner may no longer answer this bid.")

    planner = db.planners.get(opportunity["planner_id"])
    planner_version_before = planner["version"] if planner is not None else None
    package["planner_response"] = verdict

    if verdict == "ACCEPTED":
        # hop 1
        package["status"] = "ACCEPTED"
        touch(package)
        # hop 2: the destination wins
        before_version = opportunity["version"]
        opportunity["sales_stage"] = "DEFINITE"
        opportunity["definite_at"] = db.clock
        opportunity["definite_room_nights"] = (opportunity["committed_peak_rooms"]
                                               * opportunity["event_nights"])
        touch(opportunity)
        # hops 3 and 4: the FIRST-rank hold is confirmed and its conflicting
        # siblings on the same hall are superseded
        aggregates.confirm_first_hold(opportunity)
        aggregates.refresh_planner_scores(opportunity)
        opportunity["version"] = before_version + 1
        opportunity["updated_at"] = db.clock
    elif verdict == "DECLINED":
        package["status"] = "DECLINED"
        package["decline_reason"] = decline_reason
        touch(package)
        aggregates.lose_opportunity(opportunity, "PLANNER_DECLINED_BID")
    elif package["round_number"] < domain.MAX_BID_ROUNDS:
        # the cyclic heart of the negotiation.  The charge leaves the committed
        # pool first: the decommit reads total_fund_charge_amount, which the
        # wipe below is about to clear.
        aggregates.decommit_charge(package)
        package["status"] = "DRAFT"
        package["round_number"] += 1
        package["submitted_at"] = None
        package["response_due_at"] = None
        package["incentive_request_amount"] = None
        package["approved_incentive_amount"] = None
        package["admin_fee_amount"] = None
        package["total_fund_charge_amount"] = None
        package["tax_payback_ratio"] = None
        package["incentive_requested_by_user_id"] = None
        touch(package)
        opportunity["sales_stage"] = "QUALIFIED"
        touch(opportunity)
    else:
        # the ladder terminates rather than looping
        package["status"] = "DECLINED"
        package["decline_reason"] = "REVISION_LIMIT_REACHED"
        touch(package)
        aggregates.lose_opportunity(opportunity, "REVISION_LIMIT_REACHED")

    # whatever the verdict, the planner's relationship was touched
    if planner is not None:
        aggregates.set_last_touch(planner)
        planner["version"] = planner_version_before + 1
        planner["updated_at"] = db.clock
    return object_response(serialize.bid_package(package))
