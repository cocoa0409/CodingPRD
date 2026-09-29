"""Service agreements, their standing machine and performance reviews."""

from decimal import Decimal

from flask import Blueprint, request

import auth
import calc
import cascades
import errors
import lookups
import response
import serializers
import validation as v
from auth import (CARRIER, COMMUNITY_REPRESENTATIVE, ELIGIBILITY_ANALYST,
                  PROGRAM_ADMIN, SELECTION_OFFICER, endpoint)
from db import base_row, by_seq, month_index, now_iso, store, touch

bp = Blueprint("agreements", __name__)

AGREEMENT_ACTIONS = ("SUSPEND", "REINSTATE", "TERMINATE")
REVIEW_BASES = ("STRICT", "ADJUSTED")
GOOD_STANDING = ("ACTIVE", "PROBATION")
UNSETTLED_PERIOD_STATUSES = ("REPORTED", "CERTIFIED")


@bp.route("/service-agreements/<aid>", methods=["GET"])
@endpoint(PROGRAM_ADMIN, SELECTION_OFFICER, ELIGIBILITY_ANALYST,
          COMMUNITY_REPRESENTATIVE, CARRIER)
def read_agreement(aid):
    return response.ok(serializers.agreement(lookups.agreement(aid)))


@bp.route("/service-agreements", methods=["GET"])
@endpoint(PROGRAM_ADMIN, SELECTION_OFFICER, COMMUNITY_REPRESENTATIVE, CARRIER)
def list_agreements():
    rows = list(store.agreements.values())
    for field in ("community_id", "carrier_id", "proposal_id",
                  "predecessor_agreement_id", "status"):
        wanted = request.args.get(field)
        if wanted is not None:
            rows = [r for r in rows if r[field] == wanted]
    return response.paginate(by_seq(rows), serializers.agreement)


@bp.route("/service-agreements/<aid>/status-actions", methods=["POST"])
@endpoint(PROGRAM_ADMIN)
def agreement_status_actions(aid):
    data = v.body()
    action = v.enum_field(data, "action", AGREEMENT_ACTIONS)
    v.str_field(data, "note", required=False, min_len=0, max_len=2000)
    agreement = lookups.agreement(aid)
    status = agreement["status"]

    if action == "SUSPEND":
        if status != "ACTIVE":
            errors.fail(errors.ERR_AGREEMENT_NOT_ACTIVE,
                        "An agreement in status %s may not be suspended." % status)
        agreement["status"] = "SUSPENDED"
        touch(agreement)
        return response.ok(serializers.agreement(agreement))

    if action == "REINSTATE":
        if status != "SUSPENDED":
            errors.fail(errors.ERR_AGREEMENT_NOT_ACTIVE,
                        "An agreement in status %s may not be reinstated." % status)
        carrier = lookups.carrier(agreement["carrier_id"])
        if carrier["status"] not in GOOD_STANDING:
            errors.fail(errors.ERR_CARRIER_NOT_IN_GOOD_STANDING,
                        "A carrier in standing %s cannot hold a reinstated agreement."
                        % carrier["status"])
        agreement["status"] = "ACTIVE"
        touch(agreement)
        community = lookups.community(agreement["community_id"])
        if community["status"] == "HOLD_IN":
            others = [a for a in lookups.agreements_of_community(community["id"])
                      if a["id"] != agreement["id"] and a["status"] != "TERMINATED"]
            if not others:
                community["status"] = "SUBSIDIZED"
                touch(community)
        return response.ok(serializers.agreement(agreement))

    # --- TERMINATE ---------------------------------------------------------
    if status == "TERMINATED":
        errors.fail(errors.ERR_AGREEMENT_NOT_ACTIVE,
                    "The agreement is already terminated.")
    for period in lookups.periods_of_agreement(agreement["id"]):
        if period["status"] in UNSETTLED_PERIOD_STATUSES:
            errors.fail(errors.ERR_AGREEMENT_NOT_ACTIVE,
                        "Month %s is still unsettled and must be resolved first."
                        % period["period_month"])
    if status == "HOLD_IN":
        successors = [a for a in store.agreements.values()
                      if a.get("predecessor_agreement_id") == agreement["id"]
                      and a["status"] == "ACTIVE"]
        if not successors:
            errors.fail(errors.ERR_REPLACEMENT_AGREEMENT_REQUIRED,
                        "A hold-in agreement may only be released once a successor "
                        "agreement is ACTIVE.")

    cascades.terminate_agreement(agreement)
    community = lookups.community(agreement["community_id"])
    cascades.decrement_active_agreements(community)
    cascades.settle_community_after_release(community)
    touch(community)

    return response.ok(serializers.agreement(agreement))


@bp.route("/service-agreements/<aid>/performance-reviews", methods=["GET"])
@endpoint(PROGRAM_ADMIN, SELECTION_OFFICER, COMMUNITY_REPRESENTATIVE, CARRIER)
def list_agreement_reviews(aid):
    agreement = lookups.agreement(aid)
    rows = [r for r in store.reviews.values()
            if r["agreement_id"] == agreement["id"]]
    for field in ("basis", "tier"):
        wanted = request.args.get(field)
        if wanted is not None:
            rows = [r for r in rows if r[field] == wanted]
    return response.paginate(by_seq(rows), serializers.review)


# =========================================================================
# performance review, carrier standing and enforcement (PRD 3.8)
# =========================================================================
@bp.route("/performance-reviews", methods=["POST"])
@endpoint(PROGRAM_ADMIN)
def create_performance_review():
    data = v.body()
    agreement_id = v.id_field(data, "agreement_id")
    basis = v.enum_field(data, "basis", REVIEW_BASES)
    start_month = v.month_field(data, "window_start_month")
    end_month = v.month_field(data, "window_end_month")
    if month_index(start_month) > month_index(end_month):
        v.bad("window_start_month may not be later than window_end_month.")

    agreement = lookups.agreement(agreement_id)
    figures = calc.review_figures(agreement, basis, start_month, end_month)

    review = base_row(False)
    review.update({
        "agreement_id": agreement["id"],
        "basis": basis,
        "window_start_month": start_month,
        "window_end_month": end_month,
        "action_taken": "NONE",
        "reviewed_by_user_id": auth.user_id(),
    })
    review.update(figures)
    store.reviews[review["id"]] = review

    carrier = lookups.carrier(agreement["carrier_id"])
    streak = cascades.refresh_carrier_headline(carrier)
    tier = figures["tier"]

    if tier == "DEFICIENT":
        review["action_taken"] = "AGREEMENT_SUSPENDED_AND_HOLD_IN"
        if carrier["status"] in GOOD_STANDING:
            carrier["status"] = "SUSPENDED"
        if agreement["status"] == "ACTIVE":
            agreement["status"] = "SUSPENDED"
            touch(agreement)
        community = lookups.community(agreement["community_id"])
        if community["status"] == "SUBSIDIZED":
            community["status"] = "HOLD_IN"
        cascades.decrement_active_agreements(community)
        touch(community)
        cascades.open_replacement_solicitation(community["id"])
    elif tier == "WATCH" and streak >= 2:
        review["action_taken"] = "CARRIER_PLACED_ON_PROBATION"
        if carrier["status"] == "ACTIVE":
            carrier["status"] = "PROBATION"

    touch(carrier)
    return response.created(serializers.review(review))
