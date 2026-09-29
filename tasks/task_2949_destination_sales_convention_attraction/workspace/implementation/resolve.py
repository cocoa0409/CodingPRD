"""Existence resolution (ladder rungs 5 and 6).

Rung 5: every id in the path resolves, validated left to right, before any body
field is examined.  Rung 6: every foreign key supplied in the body resolves.
Both rungs answer 404 with the not-found code of the kind that failed to
resolve (PRD 2.7).
"""

from errors import ApiError
from store import db


def _resolve(collection, row_id, error_id, label):
    row = collection.get(row_id)
    if row is None:
        raise ApiError(error_id, "No %s exists with id '%s'." % (label, row_id))
    return row


def planner(row_id):
    return _resolve(db.planners, row_id, "ERR_PLANNER_NOT_FOUND", "meeting planner")


def hotel(row_id):
    return _resolve(db.hotels, row_id, "ERR_HOTEL_NOT_FOUND", "hotel")


def hall(row_id):
    return _resolve(db.halls, row_id, "ERR_HALL_NOT_FOUND", "center hall")


def opportunity(row_id):
    return _resolve(db.opportunities, row_id, "ERR_OPPORTUNITY_NOT_FOUND",
                    "opportunity")


def space_hold(row_id):
    return _resolve(db.space_holds, row_id, "ERR_SPACE_HOLD_NOT_FOUND",
                    "space hold")


def commitment(row_id):
    return _resolve(db.commitments, row_id, "ERR_COMMITMENT_NOT_FOUND",
                    "room block commitment")


def bid_package(row_id):
    return _resolve(db.bid_packages, row_id, "ERR_BID_PACKAGE_NOT_FOUND",
                    "bid package")


def fund(row_id):
    return _resolve(db.funds, row_id, "ERR_FUND_NOT_FOUND", "incentive fund")


def servicing_order(row_id):
    return _resolve(db.servicing_orders, row_id, "ERR_SERVICING_ORDER_NOT_FOUND",
                    "servicing order")


def board_report(row_id):
    return _resolve(db.board_reports, row_id, "ERR_BOARD_REPORT_NOT_FOUND",
                    "board report")
