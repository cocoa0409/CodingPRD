"""SelfPerformBid endpoints (PRD 3.4)."""
from flask import Blueprint, g

import clock
import lookups
import response as resp
import serializers
import validation as v
from db import db, new_record, sorted_rows, touch
from errors import ApiError, bad_request
from money import MONEY_ZERO, q2
from middleware import (
    CONSTRUCTION_MANAGER,
    INDEPENDENT_AUDITOR,
    OWNER_REPRESENTATIVE,
    PROCUREMENT_OFFICER,
    PROGRAM_ADMIN,
    endpoint,
)

bp = Blueprint("bids", __name__)

BIDDER_TYPES = ("CM_SELF_PERFORM", "THIRD_PARTY")
BID_STATUSES = ("SEALED", "OPENED", "AWARDED", "NOT_AWARDED")
BREAKDOWN_COMPONENTS = ("labor", "material", "equipment", "overhead", "profit")
READ_ROLES = (
    CONSTRUCTION_MANAGER,
    PROCUREMENT_OFFICER,
    OWNER_REPRESENTATIVE,
    INDEPENDENT_AUDITOR,
    PROGRAM_ADMIN,
)


def _parse_breakdown(raw):
    if not isinstance(raw, dict):
        raise bad_request("field 'open_book_cost_breakdown' must be an object")
    parsed = {}
    for component in BREAKDOWN_COMPONENTS:
        if component not in raw or raw[component] is None:
            raise bad_request(
                "open_book_cost_breakdown is missing component '%s'" % component
            )
        parsed[component] = v.get_money(raw, component, required=True)
    return parsed


@bp.route("/self-perform-bids", methods=["POST"])
@endpoint(CONSTRUCTION_MANAGER)
def create_bid():
    body = v.json_body()
    work_package_id = v.get_id(body, "work_package_id", required=True)
    bidder_type = v.get_enum(body, "bidder_type", BIDDER_TYPES, required=True)
    bidder_name = v.get_str(body, "bidder_name", required=True, min_len=1, max_len=200)
    base_bid_amount = v.get_money(
        body, "base_bid_amount", required=True, positive=True
    )
    breakdown = None
    if bidder_type == "CM_SELF_PERFORM":
        if not v.present(body, "open_book_cost_breakdown"):
            raise bad_request(
                "field 'open_book_cost_breakdown' is required for a "
                "CM_SELF_PERFORM bid"
            )
        breakdown = _parse_breakdown(body["open_book_cost_breakdown"])
    else:
        if v.present(body, "open_book_cost_breakdown"):
            raise bad_request(
                "field 'open_book_cost_breakdown' must be null for a THIRD_PARTY bid"
            )

    package = lookups.work_package(work_package_id)
    if package["procurement_status"] != "SOLICITING":
        raise ApiError(
            "ERR_PACKAGE_STATE_INVALID",
            "procurement_status is %s; bids are only accepted while SOLICITING"
            % package["procurement_status"],
        )

    if breakdown is not None:
        total = MONEY_ZERO
        for component in BREAKDOWN_COMPONENTS:
            total = total + breakdown[component]
        if q2(total) != base_bid_amount:
            raise ApiError(
                "ERR_OPEN_BOOK_BREAKDOWN_MISMATCH",
                "open-book components sum to %s, not base_bid_amount %s"
                % (q2(total), base_bid_amount),
            )

    bid = new_record({
        "work_package_id": package["id"],
        "bidder_type": bidder_type,
        "bidder_name": bidder_name,
        "base_bid_amount": base_bid_amount,
        "open_book_cost_breakdown": breakdown,
        "prepared_by_user_id": g.user_id,
        "opened_by_user_id": None,
        "opened_at": None,
        "status": "SEALED",
    })
    db.bids[bid["id"]] = bid
    package["bid_count"] = package["bid_count"] + 1
    touch(package)
    return resp.created(serializers.bid(bid))


@bp.route("/self-perform-bids/<bid_id>/open", methods=["POST"])
@endpoint(PROCUREMENT_OFFICER)
def open_bid(bid_id):
    body = v.json_body()
    v.get_str(body, "open_note", required=False, min_len=0)
    bid = lookups.bid(bid_id)
    package = lookups.work_package(bid["work_package_id"])

    if bid["status"] != "SEALED":
        raise ApiError(
            "ERR_BID_STATE_INVALID",
            "bid status is %s; opening requires SEALED" % bid["status"],
        )
    if g.user_id == bid["prepared_by_user_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "the bid preparer may not open the same bid",
        )
    if bid["bidder_type"] == "CM_SELF_PERFORM" \
            and package["transparency_status"] not in ("DISCLOSED", "AUDITED"):
        raise ApiError(
            "ERR_OPEN_BOOK_DISCLOSURE_REQUIRED",
            "a CM_SELF_PERFORM bid may only be opened once the package "
            "transparency_status is DISCLOSED or AUDITED",
        )
    closes_at = package["solicitation_closes_at"]
    if closes_at is not None and clock.now() < closes_at:
        raise ApiError(
            "ERR_SOLICITATION_STILL_OPEN",
            "the logical clock has not reached solicitation_closes_at",
        )

    bid["status"] = "OPENED"
    bid["opened_by_user_id"] = g.user_id
    bid["opened_at"] = clock.now()
    touch(bid)
    return resp.ok(serializers.bid(bid))


@bp.route("/self-perform-bids", methods=["GET"])
@endpoint(*READ_ROLES)
def list_bids():
    limit, offset = v.pagination()
    work_package_id = v.query_filter("work_package_id")
    status = v.query_filter("status", BID_STATUSES)
    bidder_type = v.query_filter("bidder_type", BIDDER_TYPES)
    rows = []
    for row in db.bids.values():
        if work_package_id is not None and row["work_package_id"] != work_package_id:
            continue
        if status is not None and row["status"] != status:
            continue
        if bidder_type is not None and row["bidder_type"] != bidder_type:
            continue
        rows.append(row)
    rows = sorted_rows(rows)
    page, total = v.paginate(rows, limit, offset)
    return resp.listing([serializers.bid(r) for r in page], limit, offset, total)


@bp.route("/self-perform-bids/<bid_id>", methods=["GET"])
@endpoint(*READ_ROLES)
def read_bid(bid_id):
    return resp.ok(serializers.bid(lookups.bid(bid_id)))
