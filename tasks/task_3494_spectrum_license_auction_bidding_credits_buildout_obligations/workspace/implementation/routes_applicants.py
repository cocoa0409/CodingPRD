"""Applicants: self-registration, disclosure (OCC), upfront ledger,
qualification review, resubmission, withdrawal (PRD §3.2, §3.3)."""
from flask import Blueprint, request

import store
import calcs
import serializers
import sweeps
from errors import ApiError, bad_request, success
from helpers import (auth, require_role, body, req_present, as_str, as_bool,
                     as_int, as_enum, get_or_404, paginate, touch, check_occ)

bp = Blueprint("applicants", __name__)

ANY_ROLE = ("AuctionAdmin", "Bidder", "IncumbentOperator", "TransferReviewer")
REVIEW_ACTIONS = ("START_REVIEW", "QUALIFY", "REQUEST_CORRECTION", "REJECT",
                  "DISQUALIFY")


def _validate_ownership_interests(value):
    if not isinstance(value, list):
        raise bad_request("ownership_interests must be an array")
    cleaned = []
    for entry in value:
        if not isinstance(entry, dict):
            raise bad_request("ownership_interests entries must be objects")
        holder_name = entry.get("holder_name")
        if not isinstance(holder_name, str) or holder_name == "":
            raise bad_request("ownership_interests.holder_name must be a "
                              "non-empty string")
        stake = entry.get("stake_pct")
        if isinstance(stake, bool) or not isinstance(stake, (int, float)):
            raise bad_request("ownership_interests.stake_pct must be a number")
        if stake < 0:
            raise bad_request("ownership_interests.stake_pct is out of range")
        revenue = entry.get("holder_annual_revenue_cents")
        if isinstance(revenue, bool) or not isinstance(revenue, int) or revenue < 0:
            raise bad_request("ownership_interests.holder_annual_revenue_cents "
                              "must be a non-negative integer")
        cleaned.append({"holder_name": holder_name, "stake_pct": stake,
                        "holder_annual_revenue_cents": revenue})
    return cleaned


def _check_ownership_total(interests):
    total = calcs.ownership_total(interests)
    if abs(total - 100) > 1e-9:
        raise ApiError("ERR_OWNERSHIP_TOTAL_INVALID", 422,
                       "ownership_interests stake_pct values must sum to "
                       "exactly 100")


@bp.route("/spectrum-auctions/applicants", methods=["POST"])
def register_applicant():
    _, role = auth()
    require_role(role, ("Bidder",))
    b = body()
    auction_id = as_str(req_present(b, "auction_id"), "auction_id")
    legal_name = as_str(req_present(b, "legal_name"), "legal_name")
    claims_sb = as_bool(req_present(b, "claims_small_business"),
                        "claims_small_business")
    claims_rural = as_bool(req_present(b, "claims_rural_credit"),
                           "claims_rural_credit")
    own_revenue = as_int(req_present(b, "own_annual_revenue_cents"),
                         "own_annual_revenue_cents", minimum=0)
    service_pop = as_int(req_present(b, "service_population"),
                         "service_population", minimum=0)
    interests = _validate_ownership_interests(
        req_present(b, "ownership_interests"))
    auction = get_or_404("auctions", auction_id)
    if auction["status"] != "APPLICATION_OPEN":
        raise ApiError("ERR_AUCTION_INVALID_STATE", 409,
                       "Registration requires the auction to be "
                       "APPLICATION_OPEN")
    _check_ownership_total(interests)
    applicant = store.stamp_new({
        "id": store.new_id(),
        "auction_id": auction_id,
        "legal_name": legal_name,
        "claims_small_business": claims_sb,
        "claims_rural_credit": claims_rural,
        "own_annual_revenue_cents": own_revenue,
        "service_population": service_pop,
        "ownership_interests": interests,
        "attributable_revenue_cents": None,
        "credit_pct": 0,
        "upfront_paid_cents": 0,
        "upfront_held_cents": 0,
        "upfront_refunded_cents": 0,
        "upfront_forfeited_cents": 0,
        "eligibility_units": 0,
        "initial_eligibility_units": 0,
        "status": "SUBMITTED",
    })
    store.DB["applicants"][applicant["id"]] = applicant
    return success(serializers.applicant(applicant), 201)


@bp.route("/spectrum-auctions/applicants/<aid>", methods=["GET"])
def get_applicant(aid):
    auth()
    return success(serializers.applicant(get_or_404("applicants", aid)), 200)


@bp.route("/spectrum-auctions/auctions/<aid>/applicants", methods=["GET"])
def list_applicants(aid):
    auth()
    get_or_404("auctions", aid)
    items = [a for a in store.DB["applicants"].values()
             if a["auction_id"] == aid]
    status = request.args.get("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    page, meta = paginate(items)
    return success([serializers.applicant(a) for a in page], 200, meta)


@bp.route("/spectrum-auctions/applicants/<aid>/disclosure", methods=["PATCH"])
def update_disclosure(aid):
    uid, role = auth()
    require_role(role, ("Bidder",))
    b = body()
    expected = req_present(b, "expected_applicant_version")
    as_int(expected, "expected_applicant_version")
    applicant = get_or_404("applicants", aid)
    if uid != applicant["id"]:
        raise ApiError("ERR_FORBIDDEN_OWNERSHIP", 403,
                       "X-User-ID must equal the applicant id")
    if applicant["status"] not in ("SUBMITTED", "NEEDS_CORRECTION"):
        raise ApiError("ERR_APPLICANT_INVALID_STATE", 409,
                       "Disclosure updates require SUBMITTED or "
                       "NEEDS_CORRECTION")
    check_occ(applicant, expected, "expected_applicant_version")
    auction = store.DB["auctions"][applicant["auction_id"]]
    if auction["status"] != "APPLICATION_OPEN":
        raise ApiError("ERR_QUIET_PERIOD_VIOLATION", 409,
                       "Anti-collusion freeze: disclosure updates are "
                       "rejected from the quiet period onward")
    updates = {}
    if "legal_name" in b:
        updates["legal_name"] = as_str(b["legal_name"], "legal_name")
    if "claims_small_business" in b:
        updates["claims_small_business"] = as_bool(
            b["claims_small_business"], "claims_small_business")
    if "claims_rural_credit" in b:
        updates["claims_rural_credit"] = as_bool(
            b["claims_rural_credit"], "claims_rural_credit")
    if "own_annual_revenue_cents" in b:
        updates["own_annual_revenue_cents"] = as_int(
            b["own_annual_revenue_cents"], "own_annual_revenue_cents",
            minimum=0)
    if "service_population" in b:
        updates["service_population"] = as_int(
            b["service_population"], "service_population", minimum=0)
    if "ownership_interests" in b:
        interests = _validate_ownership_interests(b["ownership_interests"])
        _check_ownership_total(interests)
        updates["ownership_interests"] = interests
    for key, value in updates.items():
        applicant[key] = value
    touch(applicant)
    return success(serializers.applicant(applicant), 200)


@bp.route("/spectrum-auctions/applicants/<aid>/upfront-payments",
          methods=["POST"])
def add_upfront_payment(aid):
    uid, role = auth()
    require_role(role, ("Bidder",))
    b = body()
    amount = as_int(req_present(b, "amount_cents"), "amount_cents", minimum=1)
    applicant = get_or_404("applicants", aid)
    if uid != applicant["id"]:
        raise ApiError("ERR_FORBIDDEN_OWNERSHIP", 403,
                       "X-User-ID must equal the applicant id")
    auction = store.DB["auctions"][applicant["auction_id"]]
    if auction["status"] not in ("APPLICATION_OPEN", "QUIET_PERIOD"):
        raise ApiError("ERR_UPFRONT_WINDOW_CLOSED", 409,
                       "Upfront payments require APPLICATION_OPEN or "
                       "QUIET_PERIOD")
    applicant["upfront_paid_cents"] += amount
    applicant["upfront_held_cents"] += amount
    applicant["eligibility_units"] = calcs.eligibility_for(
        applicant["upfront_held_cents"])
    touch(applicant)
    return success(serializers.applicant(applicant), 200)


@bp.route("/spectrum-auctions/applicants/<aid>/review", methods=["POST"])
def review_applicant(aid):
    _, role = auth()
    require_role(role, ("AuctionAdmin",))
    b = body()
    action = as_enum(req_present(b, "action"), "action", REVIEW_ACTIONS)
    applicant = get_or_404("applicants", aid)
    status = applicant["status"]

    def bad_state():
        raise ApiError("ERR_APPLICANT_INVALID_STATE", 409,
                       "Applicant transition %s is not available from %s"
                       % (action, status))

    if action == "START_REVIEW":
        if status != "SUBMITTED":
            bad_state()
        applicant["status"] = "UNDER_REVIEW"
        touch(applicant)
    elif action == "QUALIFY":
        if status != "UNDER_REVIEW":
            bad_state()
        _check_ownership_total(applicant["ownership_interests"])
        if applicant["claims_small_business"] and applicant["claims_rural_credit"]:
            raise ApiError("ERR_CREDIT_CLAIM_CONFLICT", 422,
                           "claims_small_business and claims_rural_credit are "
                           "mutually exclusive")
        if applicant["eligibility_units"] < 1:
            raise ApiError("ERR_INSUFFICIENT_UPFRONT", 422,
                           "QUALIFY requires at least one eligibility unit")
        attributable = calcs.compute_attributable_revenue(applicant)
        applicant["attributable_revenue_cents"] = attributable
        applicant["credit_pct"] = calcs.compute_credit_pct(applicant,
                                                           attributable)
        applicant["status"] = "QUALIFIED"
        touch(applicant)
    elif action == "REQUEST_CORRECTION":
        if status != "UNDER_REVIEW":
            bad_state()
        applicant["status"] = "NEEDS_CORRECTION"
        touch(applicant)
    elif action == "REJECT":
        if status != "UNDER_REVIEW":
            bad_state()
        applicant["status"] = "REJECTED"
        sweeps.refund_held(applicant)
        touch(applicant)
    else:  # DISQUALIFY — anti-collusion enforcement window only
        if status != "QUALIFIED":
            bad_state()
        auction = store.DB["auctions"][applicant["auction_id"]]
        if auction["status"] not in ("QUIET_PERIOD", "CLOCK_ACTIVE",
                                     "CLOCK_PAUSED"):
            bad_state()
        # Cascade hop 1: every SUBMITTED bid by this applicant in the
        # currently OPEN round of this auction becomes VOIDED.
        # Cascade hop 2: each voiding live-recomputes that round's
        # aggregate_demand (voided quantities removed).
        open_rounds = [r for r in store.DB["rounds"].values()
                       if r["auction_id"] == auction["id"]
                       and r["status"] == "OPEN"]
        for rnd in open_rounds:
            for bid in store.DB["bids"].values():
                if (bid["round_id"] == rnd["id"]
                        and bid["bidder_applicant_id"] == applicant["id"]
                        and bid["status"] == "SUBMITTED"):
                    bid["status"] = "VOIDED"
                    touch(bid)
                    for entry in rnd["aggregate_demand"]:
                        if (entry["area_code"] == bid["area_code"]
                                and entry["category"] == bid["category"]):
                            entry["demand_quantity"] -= bid["quantity"]
                            break
                    touch(rnd)
        sweeps.forfeit_held(applicant, auction)
        applicant["status"] = "DISQUALIFIED"
        touch(applicant)
    return success(serializers.applicant(applicant), 200)


@bp.route("/spectrum-auctions/applicants/<aid>/resubmit", methods=["POST"])
def resubmit_applicant(aid):
    uid, role = auth()
    require_role(role, ("Bidder",))
    b = body()
    expected = req_present(b, "expected_applicant_version")
    as_int(expected, "expected_applicant_version")
    applicant = get_or_404("applicants", aid)
    if uid != applicant["id"]:
        raise ApiError("ERR_FORBIDDEN_OWNERSHIP", 403,
                       "X-User-ID must equal the applicant id")
    if applicant["status"] != "NEEDS_CORRECTION":
        raise ApiError("ERR_APPLICANT_INVALID_STATE", 409,
                       "Resubmission requires NEEDS_CORRECTION")
    check_occ(applicant, expected, "expected_applicant_version")
    auction = store.DB["auctions"][applicant["auction_id"]]
    if auction["status"] != "APPLICATION_OPEN":
        raise ApiError("ERR_QUIET_PERIOD_VIOLATION", 409,
                       "Anti-collusion freeze: resubmission is rejected from "
                       "the quiet period onward")
    applicant["status"] = "UNDER_REVIEW"
    touch(applicant)
    return success(serializers.applicant(applicant), 200)


@bp.route("/spectrum-auctions/applicants/<aid>/withdraw", methods=["POST"])
def withdraw_applicant(aid):
    uid, role = auth()
    require_role(role, ("Bidder",))
    applicant = get_or_404("applicants", aid)
    if uid != applicant["id"]:
        raise ApiError("ERR_FORBIDDEN_OWNERSHIP", 403,
                       "X-User-ID must equal the applicant id")
    if applicant["status"] not in ("SUBMITTED", "UNDER_REVIEW",
                                   "NEEDS_CORRECTION", "QUALIFIED"):
        raise ApiError("ERR_APPLICANT_INVALID_STATE", 409,
                       "Withdrawal is not available from %s"
                       % applicant["status"])
    auction = store.DB["auctions"][applicant["auction_id"]]
    if auction["status"] != "APPLICATION_OPEN":
        raise ApiError("ERR_WITHDRAWAL_WINDOW_CLOSED", 409,
                       "Withdrawal requires the auction to be "
                       "APPLICATION_OPEN")
    applicant["status"] = "WITHDRAWN"
    sweeps.refund_held(applicant)
    touch(applicant)
    return success(serializers.applicant(applicant), 200)
