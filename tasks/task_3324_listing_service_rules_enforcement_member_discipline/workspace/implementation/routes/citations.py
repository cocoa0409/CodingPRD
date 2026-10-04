"""Citation endpoints: create/list/get/pay/request-hearing/donate-credit +
flat routes; fine schedules."""

from datetime import timedelta

from flask import Blueprint, request

import services
from auth import require_roles, require_member_actor
from db import store, now, _parse_iso
from errors import (raise_err, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
                    ERR_TENDER_MISMATCH, ERR_CREDIT_CAP_EXCEEDED,
                    ERR_HEARING_WINDOW_CLOSED,
                    ERR_CROSS_ASSOCIATION_REFERENCE)
from helpers import (body, touch, get_association, get_citation, page,
                     parse_dt)
from response import success_object, success_list
from routes.members import check_not_merged

bp = Blueprint("citations", __name__)

RULE_CODES = ("LATE_LISTING", "LATE_STATUS", "INACCURACY", "CLEAR_COOP",
              "COMP_OFFER", "FEED_ABUSE")
HEARING_WINDOW_DAYS = 20


def _filter_citations(items):
    member_id = request.args.get("member_id")
    if member_id is not None:
        items = [c for c in items if c["member_id"] == member_id]
    listing_id = request.args.get("listing_id")
    if listing_id is not None:
        items = [c for c in items if c.get("listing_id") == listing_id]
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    rule_code = request.args.get("rule_code")
    if rule_code is not None:
        items = [c for c in items if c["rule_code"] == rule_code]
    return items


@bp.route("/mls/associations/<assoc_id>/citations", methods=["POST"])
def create_citation_route(assoc_id):
    require_roles("AssociationStaff")
    assoc = get_association(assoc_id)
    check_not_merged(assoc)
    data = body()
    for f in ("member_id", "rule_code"):
        if data.get(f) is None:
            raise_err(ERR_INVALID_REQUEST, "Missing required field '%s'" % f)
    if data["rule_code"] not in RULE_CODES:
        raise_err(ERR_INVALID_REQUEST, "rule_code must be one of %s"
                  % ", ".join(RULE_CODES))
    member = store.members.get(data["member_id"])
    if member is None or member["association_id"] != assoc_id:
        raise_err(ERR_CROSS_ASSOCIATION_REFERENCE,
                  "Cited member must belong to the citing association")
    listing_id = data.get("listing_id")
    if listing_id is not None:
        listing = store.listings.get(listing_id)
        if listing is None:
            raise_err(ERR_CROSS_ASSOCIATION_REFERENCE,
                      "listing_id does not reference an existing listing")
        office = store.offices.get(listing["office_id"])
        if office is None or office["association_id"] != assoc_id:
            raise_err(ERR_CROSS_ASSOCIATION_REFERENCE,
                      "listing_id references a listing of another association")
    cit = services.create_citation(assoc_id, data["member_id"],
                                   data["rule_code"], "STAFF",
                                   listing_id=listing_id)
    return success_object(cit, 201)


@bp.route("/mls/associations/<assoc_id>/citations", methods=["GET"])
def list_citations(assoc_id):
    require_roles("AssociationStaff", "Member")
    get_association(assoc_id)
    items = [c for c in store.citations.values()
             if c["association_id"] == assoc_id]
    items = _filter_citations(items)
    items, limit, offset, total = page(items)
    return success_list(items, limit, offset, total)


@bp.route("/mls/associations/<assoc_id>/citations/<citation_id>", methods=["GET"])
def get_citation_route(assoc_id, citation_id):
    require_roles("AssociationStaff", "Member")
    get_association(assoc_id)
    return success_object(get_citation(citation_id, assoc_id))


@bp.route("/mls/citations", methods=["GET"])
def flat_list_citations():
    require_roles("AssociationStaff", "Member")
    items = _filter_citations(list(store.citations.values()))
    items, limit, offset, total = page(items)
    return success_list(items, limit, offset, total)


@bp.route("/mls/citations/<citation_id>", methods=["GET"])
def flat_get_citation(citation_id):
    require_roles("AssociationStaff", "Member")
    return success_object(get_citation(citation_id))


@bp.route("/mls/associations/<assoc_id>/citations/<citation_id>/pay",
          methods=["POST"])
def pay_citation(assoc_id, citation_id):
    user_id, _ = require_roles("Member")
    assoc = get_association(assoc_id)
    citation = get_citation(citation_id, assoc_id)
    check_not_merged(assoc)
    require_member_actor(user_id, citation["member_id"])
    if citation["status"] != "OPEN":
        raise_err(ERR_INVALID_STATE, "Only an OPEN citation may be paid")
    data = body()
    tender = data.get("tender_cents")
    if tender is None or isinstance(tender, bool) or not isinstance(tender, int):
        raise_err(ERR_INVALID_REQUEST, "tender_cents must be an integer")
    member = store.members[citation["member_id"]]
    credit_portion = min(citation["fine_amount_cents"],
                         member["sanction_credit_balance_cents"])
    expected_tender = citation["fine_amount_cents"] - credit_portion
    if tender != expected_tender:
        raise_err(ERR_TENDER_MISMATCH,
                  "tender_cents must equal fine minus auto-applied credits")
    # Cap check BEFORE any state change.
    if member["sanction_credit_balance_cents"] + citation["fine_amount_cents"] \
       > assoc["sanction_credit_cap_cents"]:
        raise_err(ERR_CREDIT_CAP_EXCEEDED,
                  "Crediting the fine would exceed the association cap")
    citation["status"] = "PAID"
    touch(citation)
    services.credit_member_for_paid_citation(member, citation)
    return success_object(citation)


@bp.route("/mls/associations/<assoc_id>/citations/<citation_id>/request-hearing",
          methods=["POST"])
def request_hearing(assoc_id, citation_id):
    user_id, _ = require_roles("Member")
    assoc = get_association(assoc_id)
    citation = get_citation(citation_id, assoc_id)
    check_not_merged(assoc)
    require_member_actor(user_id, citation["member_id"])
    if citation["status"] != "OPEN" or citation["hearing_requested"]:
        raise_err(ERR_INVALID_STATE,
                  "Hearing may be requested only once, from OPEN status")
    assessed = _parse_iso(citation["assessed_at"])
    if now() > assessed + timedelta(days=HEARING_WINDOW_DAYS):
        raise_err(ERR_HEARING_WINDOW_CLOSED,
                  "Hearing requested after assessed_at + 20 days")
    citation["hearing_requested"] = True
    citation["status"] = "HEARING_PENDING"
    touch(citation)
    return success_object(citation)


@bp.route("/mls/associations/<assoc_id>/citations/<citation_id>/donate-credit",
          methods=["POST"])
def donate_credit(assoc_id, citation_id):
    user_id, _ = require_roles("Member")
    assoc = get_association(assoc_id)
    citation = get_citation(citation_id, assoc_id)
    check_not_merged(assoc)
    require_member_actor(user_id, citation["member_id"])
    if citation["status"] != "PAID":
        raise_err(ERR_INVALID_STATE,
                  "Only a PAID citation may be used to donate credit")
    data = body()
    amount = data.get("amount_cents")
    if amount is None or isinstance(amount, bool) or not isinstance(amount, int) \
       or amount < 0:
        raise_err(ERR_INVALID_REQUEST, "amount_cents must be an integer >= 0")
    member = store.members[citation["member_id"]]
    # Landing exactly AT the cap is allowed; exceeding it is rejected.
    if member["sanction_credit_balance_cents"] + amount \
       > assoc["sanction_credit_cap_cents"]:
        raise_err(ERR_CREDIT_CAP_EXCEEDED,
                  "Donation would exceed the association credit cap")
    member["sanction_credit_balance_cents"] += amount
    touch(member)
    return success_object(citation)
