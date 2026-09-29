"""WorkPackage endpoints (PRD 3.4)."""
from flask import Blueprint, g

import guards
import lookups
import response as resp
import serializers
import validation as v
from db import db, new_record, sorted_rows, touch
from errors import ApiError
from money import MONEY_ZERO, q2
from middleware import (
    CONSTRUCTION_MANAGER,
    INDEPENDENT_AUDITOR,
    OWNER_REPRESENTATIVE,
    PROCUREMENT_OFFICER,
    PROGRAM_ADMIN,
    endpoint,
    require_action_role,
)
from services import derive

bp = Blueprint("work_packages", __name__)

PROCUREMENT_STATUSES = (
    "BUDGETED",
    "SOLICITING",
    "AWARDED",
    "REPROCUREMENT",
    "CLOSED",
)
TRANSPARENCY_STATUSES = ("SEALED", "DISCLOSED", "AUDITED")
READ_ROLES = (
    CONSTRUCTION_MANAGER,
    PROCUREMENT_OFFICER,
    OWNER_REPRESENTATIVE,
    INDEPENDENT_AUDITOR,
    PROGRAM_ADMIN,
)


@bp.route("/work-packages", methods=["POST"])
@endpoint(CONSTRUCTION_MANAGER)
def create_work_package():
    body = v.json_body()
    project_id = v.get_id(body, "project_id", required=True)
    trade_division = v.get_str(
        body, "trade_division", required=True, min_len=1, max_len=60
    )
    budget_amount = v.get_money(body, "budget_amount", required=True, positive=True)
    self_perform_intent = v.get_bool(
        body, "self_perform_intent", required=False, default=False
    )
    project = lookups.project(project_id)
    package = new_record({
        "project_id": project["id"],
        "trade_division": trade_division,
        "budget_amount": budget_amount,
        "self_perform_intent": self_perform_intent,
        "procurement_status": "BUDGETED",
        "transparency_status": "SEALED",
        "solicitation_opens_at": None,
        "solicitation_closes_at": None,
        "awarded_bid_id": None,
        "awarded_amount": MONEY_ZERO,
        "committed_amount": MONEY_ZERO,
        "replacement_reserve_amount": MONEY_ZERO,
        "bid_count": 0,
    })
    db.work_packages[package["id"]] = package
    return resp.created(serializers.work_package(package))


@bp.route("/work-packages/<wid>/solicit", methods=["POST"])
@endpoint(CONSTRUCTION_MANAGER)
def solicit(wid):
    body = v.json_body()
    opens_at = v.get_datetime(body, "solicitation_opens_at", required=True)
    closes_at = v.get_datetime(body, "solicitation_closes_at", required=True)
    v.require_before(
        opens_at, closes_at, "solicitation_opens_at", "solicitation_closes_at"
    )
    package = lookups.work_package(wid)
    project = lookups.project(package["project_id"])
    if project["gmp_status"] not in ("GMP_UNDER_REVIEW", "EXECUTED"):
        raise ApiError(
            "ERR_GMP_NOT_EXECUTED",
            "project gmp_status is %s; soliciting requires GMP_UNDER_REVIEW or "
            "EXECUTED" % project["gmp_status"],
        )
    if package["procurement_status"] not in ("BUDGETED", "REPROCUREMENT"):
        raise ApiError(
            "ERR_PACKAGE_STATE_INVALID",
            "procurement_status is %s; soliciting requires BUDGETED or REPROCUREMENT"
            % package["procurement_status"],
        )
    package["solicitation_opens_at"] = opens_at
    package["solicitation_closes_at"] = closes_at
    package["procurement_status"] = "SOLICITING"
    touch(package)
    return resp.ok(serializers.work_package(package))


@bp.route("/work-packages/<wid>/transparency", methods=["POST"])
@endpoint(PROCUREMENT_OFFICER, INDEPENDENT_AUDITOR)
def transparency(wid):
    body = v.json_body()
    raw_target = body.get("target_status")
    # Action level authorization runs before request shape validation (PRD 2.11).
    if raw_target == "DISCLOSED":
        require_action_role(PROCUREMENT_OFFICER)
    elif raw_target == "AUDITED":
        require_action_role(INDEPENDENT_AUDITOR)
    target_status = v.get_enum(
        body, "target_status", TRANSPARENCY_STATUSES, required=True
    )
    v.get_str(body, "disclosure_note", required=False, min_len=0)
    package = lookups.work_package(wid)
    current = package["transparency_status"]
    if target_status == "DISCLOSED":
        if current != "SEALED":
            raise ApiError(
                "ERR_PACKAGE_STATE_INVALID",
                "transparency_status is %s; DISCLOSED requires SEALED" % current,
            )
        if package["bid_count"] < 1:
            raise ApiError(
                "ERR_PACKAGE_STATE_INVALID",
                "disclosure requires at least one bid on the package",
            )
    elif target_status == "AUDITED":
        if current != "DISCLOSED":
            raise ApiError(
                "ERR_PACKAGE_STATE_INVALID",
                "transparency_status is %s; AUDITED requires DISCLOSED" % current,
            )
    else:
        raise ApiError(
            "ERR_PACKAGE_STATE_INVALID",
            "the transparency ladder never regresses to SEALED",
        )
    package["transparency_status"] = target_status
    touch(package)
    return resp.ok(serializers.work_package(package))


@bp.route("/work-packages/<wid>/award", methods=["POST"])
@endpoint(PROCUREMENT_OFFICER)
def award(wid):
    body = v.json_body()
    bid_id = v.get_id(body, "bid_id", required=True)
    v.get_str(body, "award_note", required=False, min_len=0)
    package = lookups.work_package(wid)
    bid = lookups.bid(bid_id)
    project = lookups.project(package["project_id"])

    guards.require_gmp_executed(project)
    if package["procurement_status"] not in ("SOLICITING", "REPROCUREMENT"):
        raise ApiError(
            "ERR_PACKAGE_STATE_INVALID",
            "procurement_status is %s; award requires SOLICITING or REPROCUREMENT"
            % package["procurement_status"],
        )
    if bid["status"] != "OPENED":
        raise ApiError(
            "ERR_BID_STATE_INVALID",
            "bid status is %s; award requires OPENED" % bid["status"],
        )
    if bid["work_package_id"] != package["id"]:
        raise ApiError(
            "ERR_WORK_PACKAGE_PROJECT_MISMATCH",
            "the named bid does not belong to this work package",
        )

    was_reprocurement = package["procurement_status"] == "REPROCUREMENT"
    package["procurement_status"] = "AWARDED"
    package["awarded_bid_id"] = bid["id"]
    package["awarded_amount"] = bid["base_bid_amount"]
    if was_reprocurement:
        package["replacement_reserve_amount"] = MONEY_ZERO

    bid["status"] = "AWARDED"
    touch(bid)
    for other in db.bids.values():
        if other["id"] == bid["id"]:
            continue
        if other["work_package_id"] != package["id"]:
            continue
        if other["status"] != "OPENED":
            continue
        other["status"] = "NOT_AWARDED"
        touch(other)

    derive.recompute_buyout_savings(project)
    touch(package)
    touch(project)
    return resp.ok(serializers.work_package(package))


@bp.route("/work-packages", methods=["GET"])
@endpoint(*READ_ROLES)
def list_work_packages():
    limit, offset = v.pagination()
    project_id = v.query_filter("project_id")
    awarded_bid_id = v.query_filter("awarded_bid_id")
    procurement_status = v.query_filter("procurement_status", PROCUREMENT_STATUSES)
    transparency_status = v.query_filter("transparency_status", TRANSPARENCY_STATUSES)
    trade_division = v.query_filter("trade_division")
    rows = []
    for row in db.work_packages.values():
        if project_id is not None and row["project_id"] != project_id:
            continue
        if awarded_bid_id is not None and row["awarded_bid_id"] != awarded_bid_id:
            continue
        if procurement_status is not None \
                and row["procurement_status"] != procurement_status:
            continue
        if transparency_status is not None \
                and row["transparency_status"] != transparency_status:
            continue
        if trade_division is not None and row["trade_division"] != trade_division:
            continue
        rows.append(row)
    rows = sorted_rows(rows)
    page, total = v.paginate(rows, limit, offset)
    return resp.listing(
        [serializers.work_package(r) for r in page], limit, offset, total
    )


@bp.route("/work-packages/<wid>", methods=["GET"])
@endpoint(*READ_ROLES)
def read_work_package(wid):
    return resp.ok(serializers.work_package(lookups.work_package(wid)))
