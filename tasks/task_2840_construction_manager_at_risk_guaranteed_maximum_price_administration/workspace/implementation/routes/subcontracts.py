"""Subcontract endpoints, the termination cascade and the surety axis (PRD 3.5)."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, g

import clock
import guards
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
    require_action_role,
)
from services import derive

bp = Blueprint("subcontracts", __name__)

CONTRACT_STATUSES = ("ACTIVE", "DEFAULT_NOTICED", "COMPLETED", "TERMINATED_FOR_DEFAULT")
BOND_CLAIM_STATUSES = (
    "NOT_APPLICABLE",
    "NONE",
    "FILED",
    "ACKNOWLEDGED",
    "SETTLED",
    "DENIED",
)
STATUS_ACTIONS = ("NOTICE_DEFAULT", "CURE", "COMPLETE", "TERMINATE_FOR_DEFAULT")
BOND_ACTIONS = ("FILE", "ACKNOWLEDGE", "SETTLE", "DENY")
BLOCKING_STATUSES = ("ACTIVE", "DEFAULT_NOTICED", "COMPLETED")
MOBILIZATION_BUFFER = timedelta(hours=72)
REPLACEMENT_PREMIUM_MULTIPLIER = Decimal("1.15")
READ_ROLES = (
    CONSTRUCTION_MANAGER,
    PROCUREMENT_OFFICER,
    OWNER_REPRESENTATIVE,
    INDEPENDENT_AUDITOR,
    PROGRAM_ADMIN,
)


@bp.route("/subcontracts", methods=["POST"])
@endpoint(CONSTRUCTION_MANAGER)
def create_subcontract():
    body = v.json_body()
    work_package_id = v.get_id(body, "work_package_id", required=True)
    awarded_bid_id = v.get_id(body, "awarded_bid_id", required=True)
    subcontractor_name = v.get_str(
        body, "subcontractor_name", required=True, min_len=1, max_len=200
    )
    contract_amount = v.get_money(
        body, "contract_amount", required=True, positive=True
    )
    performance_start = v.get_datetime(body, "performance_start", required=True)
    performance_end = v.get_datetime(body, "performance_end", required=True)
    v.require_before(
        performance_start, performance_end, "performance_start", "performance_end"
    )
    bond_required = v.get_bool(body, "bond_required", required=False, default=False)
    expected_work_package_version = v.get_int(
        body, "expected_work_package_version", required=True
    )
    if bond_required:
        bond_amount = v.get_money(
            body, "bond_amount", required=True, positive=True
        )
    else:
        v.get_money(body, "bond_amount", required=False)
        bond_amount = MONEY_ZERO

    package = lookups.work_package(work_package_id)
    bid = lookups.bid(awarded_bid_id)

    if package["version"] != expected_work_package_version:
        raise ApiError(
            "ERR_STALE_WORK_PACKAGE_VERSION",
            "expected_work_package_version %s does not match %s"
            % (expected_work_package_version, package["version"]),
        )

    project = lookups.project(package["project_id"])
    guards.require_gmp_executed(project)

    if bid["status"] != "AWARDED":
        raise ApiError(
            "ERR_BID_STATE_INVALID",
            "awarded_bid_id status is %s, not AWARDED" % bid["status"],
        )
    if bid["work_package_id"] != package["id"]:
        raise ApiError(
            "ERR_WORK_PACKAGE_PROJECT_MISMATCH",
            "awarded_bid_id belongs to a different work package",
        )

    for sibling in db.subcontracts.values():
        if sibling["work_package_id"] != package["id"]:
            continue
        if sibling["contract_status"] not in BLOCKING_STATUSES:
            continue
        clear_after = performance_start - sibling["performance_end"]
        clear_before = sibling["performance_start"] - performance_end
        if clear_after < MOBILIZATION_BUFFER and clear_before < MOBILIZATION_BUFFER:
            raise ApiError(
                "ERR_PERFORMANCE_WINDOW_BUFFER_VIOLATION",
                "the performance window must be separated from subcontract %s by at "
                "least 72 hours of clear time" % sibling["id"],
            )

    subcontract = new_record({
        "work_package_id": package["id"],
        "awarded_bid_id": bid["id"],
        "subcontractor_name": subcontractor_name,
        "contract_amount": contract_amount,
        "performance_start": performance_start,
        "performance_end": performance_end,
        "bond_required": bond_required,
        "bond_amount": bond_amount,
        "paid_to_date": MONEY_ZERO,
        "unpaid_committed_amount": contract_amount,
        "replacement_cost_amount": MONEY_ZERO,
        "contract_status": "ACTIVE",
        "bond_claim_status": "NONE" if bond_required else "NOT_APPLICABLE",
        "bond_claim_amount": MONEY_ZERO,
        "bond_recovered_amount": MONEY_ZERO,
        "default_notice_at": None,
        "cure_count": 0,
    })
    db.subcontracts[subcontract["id"]] = subcontract

    derive.recount_committed_amount(package)
    derive.recompute_buyout_savings(project)
    touch(package)
    return resp.created(serializers.subcontract(subcontract))


@bp.route("/subcontracts/<sid>/progress-payment", methods=["POST"])
@endpoint(CONSTRUCTION_MANAGER)
def progress_payment(sid):
    body = v.json_body()
    payment_amount = v.get_money(body, "payment_amount", required=True)
    subcontract = lookups.subcontract(sid)
    if subcontract["contract_status"] not in ("ACTIVE", "DEFAULT_NOTICED"):
        raise ApiError(
            "ERR_SUBCONTRACT_STATE_INVALID",
            "contract_status is %s; a progress payment requires ACTIVE or "
            "DEFAULT_NOTICED" % subcontract["contract_status"],
        )
    subcontract["paid_to_date"] = q2(subcontract["paid_to_date"] + payment_amount)
    subcontract["unpaid_committed_amount"] = q2(
        subcontract["contract_amount"] - subcontract["paid_to_date"]
    )
    touch(subcontract)
    return resp.ok(serializers.subcontract(subcontract))


def _terminate_for_default(subcontract, package, project):
    unpaid = q2(subcontract["contract_amount"] - subcontract["paid_to_date"])
    replacement_cost = q2(unpaid * REPLACEMENT_PREMIUM_MULTIPLIER)
    premium = q2(replacement_cost - unpaid)

    subcontract["unpaid_committed_amount"] = unpaid
    subcontract["replacement_cost_amount"] = replacement_cost
    subcontract["contract_status"] = "TERMINATED_FOR_DEFAULT"

    if package["procurement_status"] == "AWARDED":
        package["procurement_status"] = "REPROCUREMENT"
    package["replacement_reserve_amount"] = replacement_cost
    package["awarded_amount"] = q2(package["awarded_amount"] + premium)
    derive.recount_committed_amount(package)
    derive.recompute_buyout_savings(project)

    draw = new_record({
        "project_id": project["id"],
        "change_event_id": None,
        "source_subcontract_id": subcontract["id"],
        "contingency_type": "CONSTRUCTION",
        "origin": "SUBCONTRACTOR_DEFAULT_PREMIUM",
        "amount": premium,
        "requires_owner_approval": True,
        "status": "POSTED",
        "approved_by_user_id": None,
        "posted_at": clock.now(),
        "voided_at": None,
        "void_reason": None,
    })
    db.draws[draw["id"]] = draw

    project["construction_contingency_remaining"] = q2(
        project["construction_contingency_remaining"] - premium
    )
    project["contingency_drawn_to_cost_total"] = q2(
        project["contingency_drawn_to_cost_total"] + premium
    )
    derive.apply_posture(project)

    touch(package)
    touch(project)


@bp.route("/subcontracts/<sid>/status-action", methods=["POST"])
@endpoint(CONSTRUCTION_MANAGER)
def status_action(sid):
    body = v.json_body()
    action = v.get_enum(body, "action", STATUS_ACTIONS, required=True)
    v.get_str(body, "default_reason", required=False, min_len=0)
    v.get_str(body, "cure_note", required=False, min_len=0)
    subcontract = lookups.subcontract(sid)
    package = lookups.work_package(subcontract["work_package_id"])
    project = lookups.project(package["project_id"])
    current = subcontract["contract_status"]

    if action == "TERMINATE_FOR_DEFAULT":
        guards.require_gmp_executed(project)

    if action == "NOTICE_DEFAULT":
        if current != "ACTIVE":
            raise ApiError(
                "ERR_SUBCONTRACT_STATE_INVALID",
                "contract_status is %s; NOTICE_DEFAULT requires ACTIVE" % current,
            )
        subcontract["contract_status"] = "DEFAULT_NOTICED"
        subcontract["default_notice_at"] = clock.now()
    elif action == "CURE":
        if current != "DEFAULT_NOTICED":
            raise ApiError(
                "ERR_SUBCONTRACT_STATE_INVALID",
                "contract_status is %s; CURE requires DEFAULT_NOTICED" % current,
            )
        subcontract["contract_status"] = "ACTIVE"
        subcontract["cure_count"] = subcontract["cure_count"] + 1
        subcontract["default_notice_at"] = None
    elif action == "COMPLETE":
        if current != "ACTIVE":
            raise ApiError(
                "ERR_SUBCONTRACT_STATE_INVALID",
                "contract_status is %s; COMPLETE requires ACTIVE" % current,
            )
        if subcontract["paid_to_date"] != subcontract["contract_amount"]:
            raise ApiError(
                "ERR_SUBCONTRACT_STATE_INVALID",
                "COMPLETE requires paid_to_date to equal contract_amount exactly",
            )
        subcontract["contract_status"] = "COMPLETED"
        derive.recount_committed_amount(package)
    else:
        if current != "DEFAULT_NOTICED":
            raise ApiError(
                "ERR_SUBCONTRACT_STATE_INVALID",
                "contract_status is %s; TERMINATE_FOR_DEFAULT requires "
                "DEFAULT_NOTICED" % current,
            )
        _terminate_for_default(subcontract, package, project)

    touch(subcontract)
    return resp.ok(serializers.subcontract(subcontract))


def _settlement_credit(project, subcontract, recovered):
    """Credit the posted default-premium draw, capped at its own amount."""
    match = None
    for draw in db.draws.values():
        if draw["project_id"] != project["id"]:
            continue
        if draw["source_subcontract_id"] != subcontract["id"]:
            continue
        if draw["origin"] != "SUBCONTRACTOR_DEFAULT_PREMIUM":
            continue
        if draw["status"] != "POSTED":
            continue
        match = draw
        break
    if match is None:
        return MONEY_ZERO
    return recovered if recovered < match["amount"] else match["amount"]


@bp.route("/subcontracts/<sid>/bond-claim", methods=["POST"])
@endpoint(CONSTRUCTION_MANAGER, OWNER_REPRESENTATIVE)
def bond_claim(sid):
    body = v.json_body()
    raw_action = body.get("action")
    if raw_action == "FILE":
        require_action_role(CONSTRUCTION_MANAGER)
    elif raw_action in ("ACKNOWLEDGE", "SETTLE", "DENY"):
        require_action_role(OWNER_REPRESENTATIVE)
    action = v.get_enum(body, "action", BOND_ACTIONS, required=True)
    claim_amount = None
    recovered_amount = None
    if action == "FILE":
        claim_amount = v.get_money(body, "claim_amount", required=True, positive=True)
    if action == "SETTLE":
        recovered_amount = v.get_money(body, "recovered_amount", required=True)
    v.get_str(body, "denial_reason", required=False, min_len=0)

    subcontract = lookups.subcontract(sid)
    current = subcontract["bond_claim_status"]
    if current == "NOT_APPLICABLE":
        raise ApiError(
            "ERR_BOND_CLAIM_STATE_INVALID",
            "this subcontract carries no bond; the surety axis is NOT_APPLICABLE",
        )

    project_touched = False
    project = lookups.project(
        lookups.work_package(subcontract["work_package_id"])["project_id"]
    )

    if action == "FILE":
        if current != "NONE":
            raise ApiError(
                "ERR_BOND_CLAIM_STATE_INVALID",
                "bond_claim_status is %s; FILE requires NONE" % current,
            )
        if subcontract["contract_status"] != "TERMINATED_FOR_DEFAULT":
            raise ApiError(
                "ERR_BOND_CLAIM_STATE_INVALID",
                "a bond claim may only be filed on a TERMINATED_FOR_DEFAULT "
                "subcontract",
            )
        if claim_amount > subcontract["bond_amount"]:
            raise ApiError(
                "ERR_BOND_CLAIM_STATE_INVALID",
                "claim_amount %s exceeds bond_amount %s"
                % (claim_amount, subcontract["bond_amount"]),
            )
        subcontract["bond_claim_status"] = "FILED"
        subcontract["bond_claim_amount"] = claim_amount
    elif action == "ACKNOWLEDGE":
        if current != "FILED":
            raise ApiError(
                "ERR_BOND_CLAIM_STATE_INVALID",
                "bond_claim_status is %s; ACKNOWLEDGE requires FILED" % current,
            )
        subcontract["bond_claim_status"] = "ACKNOWLEDGED"
    elif action == "DENY":
        if current not in ("FILED", "ACKNOWLEDGED"):
            raise ApiError(
                "ERR_BOND_CLAIM_STATE_INVALID",
                "bond_claim_status is %s; DENY requires FILED or ACKNOWLEDGED"
                % current,
            )
        subcontract["bond_claim_status"] = "DENIED"
    else:
        if current != "ACKNOWLEDGED":
            raise ApiError(
                "ERR_BOND_CLAIM_STATE_INVALID",
                "bond_claim_status is %s; SETTLE requires ACKNOWLEDGED" % current,
            )
        claimed = subcontract["bond_claim_amount"]
        recovered = recovered_amount if recovered_amount < claimed else claimed
        subcontract["bond_claim_status"] = "SETTLED"
        subcontract["bond_recovered_amount"] = recovered
        credit = _settlement_credit(project, subcontract, recovered)
        if credit != MONEY_ZERO:
            project["construction_contingency_remaining"] = q2(
                project["construction_contingency_remaining"] + credit
            )
            project["contingency_drawn_to_cost_total"] = q2(
                project["contingency_drawn_to_cost_total"] - credit
            )
        derive.apply_posture(project)
        project_touched = True

    touch(subcontract)
    if project_touched:
        touch(project)
    return resp.ok(serializers.subcontract(subcontract))


@bp.route("/subcontracts", methods=["GET"])
@endpoint(*READ_ROLES)
def list_subcontracts():
    limit, offset = v.pagination()
    work_package_id = v.query_filter("work_package_id")
    awarded_bid_id = v.query_filter("awarded_bid_id")
    contract_status = v.query_filter("contract_status", CONTRACT_STATUSES)
    bond_claim_status = v.query_filter("bond_claim_status", BOND_CLAIM_STATUSES)
    rows = []
    for row in db.subcontracts.values():
        if work_package_id is not None and row["work_package_id"] != work_package_id:
            continue
        if awarded_bid_id is not None and row["awarded_bid_id"] != awarded_bid_id:
            continue
        if contract_status is not None and row["contract_status"] != contract_status:
            continue
        if bond_claim_status is not None \
                and row["bond_claim_status"] != bond_claim_status:
            continue
        rows.append(row)
    rows = sorted_rows(rows)
    page, total = v.paginate(rows, limit, offset)
    return resp.listing(
        [serializers.subcontract(r) for r in page], limit, offset, total
    )


@bp.route("/subcontracts/<sid>", methods=["GET"])
@endpoint(*READ_ROLES)
def read_subcontract(sid):
    return resp.ok(serializers.subcontract(lookups.subcontract(sid)))
