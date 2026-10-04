"""PrintRunDecision resource: propose, approve and supersede.

Approval carries the platform's ordered six-check sequence (PRD 3.9):
  1. card set is APPROVED                ERR_INVALID_STATE
  2. expected_card_set_version matches   ERR_STALE_VERSION
  3. authority freshness precondition    ERR_INSUFFICIENT_SALES_HISTORY /
                                         ERR_MARKET_SIGNAL_UNAVAILABLE
  4. expected_product_line_version       ERR_AUTHORITY_OUTDATED
  5. recomputed final_quantity == declared  ERR_INVALID_REQUEST
  6. validity window                     ERR_PRINT_DECISION_WINDOW_CLOSED
"""

import datetime

from flask import jsonify, request

import calc
import db
import requtil
import response
from core import app
from common import serialize
from constants import (
    PRINT_DECISION_AUTHORITIES,
    PRINT_DECISION_VALIDITY_DAYS,
    SALES_HISTORY_MIN_RECORDS,
)
from errors import (
    ApiError,
    ERR_AUTHORITY_OUTDATED,
    ERR_INSUFFICIENT_SALES_HISTORY,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_MARKET_SIGNAL_UNAVAILABLE,
    ERR_PRINT_RUN_DECISION_NOT_FOUND,
    ERR_PRINT_DECISION_WINDOW_CLOSED,
    ERR_PRODUCT_LINE_STATE_BLOCKED,
    ERR_REFERENCE_NOT_FOUND,
    ERR_STALE_VERSION,
)
from middleware import authenticate, require_role

READ_ROLES = ["ProductionPlanner", "ProductManager", "PlatformAdmin"]


def _get(decision_id):
    rec = db.STORE.get("print_run_decisions", decision_id)
    if rec is None:
        raise ApiError(
            ERR_PRINT_RUN_DECISION_NOT_FOUND,
            "No PrintRunDecision exists with id %s" % decision_id,
        )
    return rec


def _serialize(rec):
    return serialize("print_run_decisions", rec)


def _authority_freshness(store, decision, card_set, now):
    """The freshness precondition of the chosen authority."""
    authority = decision["authority"]
    if authority == "SALES_HISTORY":
        count = calc.sales_history_count(store, card_set["id"], now)
        if count < SALES_HISTORY_MIN_RECORDS:
            raise ApiError(
                ERR_INSUFFICIENT_SALES_HISTORY,
                "Fewer than %d qualifying complaints in the back-date window"
                % SALES_HISTORY_MIN_RECORDS,
            )
    elif authority == "MARKET_DEMAND":
        if not calc.market_demand_signals(store, card_set["product_line_id"]):
            raise ApiError(
                ERR_MARKET_SIGNAL_UNAVAILABLE,
                "No HOBBY or MASS distribution allocation exists for the line",
            )


@app.route("/api/print-run-decisions", methods=["POST"])
def create_print_run_decision():
    principal = authenticate(request.headers)
    require_role(principal, ["ProductionPlanner"])

    data = requtil.body()
    card_set_id = requtil.required_str(data, "card_set_id")
    authority = requtil.required_enum(data, "authority", PRINT_DECISION_AUTHORITIES)
    proposed_against_line_version = requtil.required_int(
        data, "proposed_against_line_version"
    )
    demand_multiplier = requtil.required(data, "demand_multiplier")
    demand_multiplier = requtil.as_number(demand_multiplier, "demand_multiplier")
    declared_quantity = requtil.required_int(data, "declared_quantity")
    announced = requtil.required_bool(data, "announced")
    proposed_on = requtil.required_dt(data, "proposed_on")

    store = db.STORE
    card_set = store.get("card_sets", card_set_id)
    if card_set is None:
        raise ApiError(
            ERR_REFERENCE_NOT_FOUND, "card_set_id %s does not resolve" % card_set_id
        )

    now = store.now()
    rec = db.record("print_run_decisions", {
        "card_set_id": card_set_id,
        "authority": authority,
        "proposed_against_line_version": proposed_against_line_version,
        "demand_multiplier": demand_multiplier,
        "declared_quantity": declared_quantity,
        "announced": announced,
        "final_quantity": 0,
        "proposed_on": proposed_on,
        "status": "PROPOSED",
    }, now)
    # final_quantity is computed immediately so the planner can see it.  The
    # authority projection may legitimately fail here (insufficient sales
    # history, no market signal), and that failure is reported at proposal
    # time; the same check is re-run and enforced at approval.
    rec["final_quantity"] = calc.print_run_projection(store, rec, card_set, now)
    store.insert("print_run_decisions", rec)
    return jsonify(response.ok_object(_serialize(rec))), 201


@app.route("/api/print-run-decisions", methods=["GET"])
def list_print_run_decisions():
    principal = authenticate(request.headers)
    require_role(principal, READ_ROLES)

    store = db.STORE
    items = list(store.all("print_run_decisions"))
    card_set_id = requtil.filter_value("card_set_id")
    status = requtil.filter_value("status")
    authority = requtil.filter_value("authority")
    if card_set_id is not None:
        items = [d for d in items if d["card_set_id"] == card_set_id]
    if status is not None:
        items = [d for d in items if d["status"] == status]
    if authority is not None:
        items = [d for d in items if d["authority"] == authority]
    items.sort(key=lambda r: r["created_at"])
    return jsonify(response.paginate([_serialize(d) for d in items], request.args)), 200


@app.route("/api/print-run-decisions/<decision_id>", methods=["GET"])
def get_print_run_decision(decision_id):
    principal = authenticate(request.headers)
    require_role(principal, READ_ROLES)
    return jsonify(response.ok_object(_serialize(_get(decision_id)))), 200


@app.route("/api/print-run-decisions/<decision_id>/approve", methods=["POST"])
def approve_print_run_decision(decision_id):
    principal = authenticate(request.headers)
    require_role(principal, ["ProductionPlanner"])

    store = db.STORE
    now = store.now()
    rec = _get(decision_id)

    data = requtil.body()
    expected_card_set_version = requtil.required_int(data, "expected_card_set_version")
    expected_product_line_version = requtil.required_int(
        data, "expected_product_line_version"
    )

    card_set = store.get("card_sets", rec["card_set_id"])
    if card_set is None:
        raise ApiError(ERR_REFERENCE_NOT_FOUND, "The referenced card set does not resolve")
    line = store.get("product_lines", card_set["product_line_id"])
    if line is None:
        raise ApiError(
            ERR_REFERENCE_NOT_FOUND, "The parent product line does not resolve"
        )

    # 1. card set must be APPROVED
    if card_set["status"] != "APPROVED":
        raise ApiError(ERR_INVALID_STATE, "The card set is not APPROVED")

    # 2. stale card-set version
    if expected_card_set_version != card_set["version"]:
        raise ApiError(
            ERR_STALE_VERSION,
            "expected_card_set_version does not match the card set's version",
        )

    # 3. authority freshness
    _authority_freshness(store, rec, card_set, now)

    # 4. authority outdated
    if expected_product_line_version != line["version"]:
        raise ApiError(
            ERR_AUTHORITY_OUTDATED,
            "expected_product_line_version does not match the product line's version",
        )

    # 5. declared quantity must equal the recomputed projection
    recomputed = calc.print_run_projection(store, rec, card_set, now)
    if rec["declared_quantity"] != recomputed:
        raise ApiError(
            ERR_INVALID_REQUEST,
            "declared_quantity does not equal the recomputed final_quantity",
        )

    # 6. validity window
    deadline = rec["proposed_on"] + datetime.timedelta(days=PRINT_DECISION_VALIDITY_DAYS)
    if now > deadline:
        raise ApiError(
            ERR_PRINT_DECISION_WINDOW_CLOSED, "The print-run decision window has closed"
        )

    if rec["status"] != "PROPOSED":
        raise ApiError(ERR_INVALID_STATE, "Print-run decision is not PROPOSED")

    # The freeze.
    rec["status"] = "APPROVED"
    rec["final_quantity"] = recomputed
    db.bump(rec, now)

    for other in store.all("print_run_decisions"):
        if other["id"] == rec["id"]:
            continue
        if other["card_set_id"] == card_set["id"] and other["status"] == "APPROVED":
            other["status"] = "SUPERSEDED"
            db.touch(other, now)

    card_set["print_run_quantity"] = rec["final_quantity"]
    card_set["announced"] = rec["announced"]
    card_set["print_run_status"] = (
        "DISCLOSED" if rec["announced"] else "UNDISCLOSED"
    )
    db.bump(card_set, now)

    from common import recompute_allocated_cards

    recompute_allocated_cards(store, line, now)
    return jsonify(response.ok_object(_serialize(rec))), 200


@app.route("/api/print-run-decisions/<decision_id>/supersede", methods=["POST"])
def supersede_print_run_decision(decision_id):
    principal = authenticate(request.headers)
    require_role(principal, ["ProductionPlanner"])

    store = db.STORE
    now = store.now()
    rec = _get(decision_id)
    if rec["status"] != "APPROVED":
        raise ApiError(ERR_INVALID_STATE, "Print-run decision is not APPROVED")

    card_set = store.get("card_sets", rec["card_set_id"])
    if card_set is None:
        raise ApiError(ERR_REFERENCE_NOT_FOUND, "The referenced card set does not resolve")
    line = store.get("product_lines", card_set["product_line_id"])
    if line is None:
        raise ApiError(
            ERR_REFERENCE_NOT_FOUND, "The parent product line does not resolve"
        )
    if line["status"] not in ("READY_FOR_APPROVAL", "APPROVED"):
        raise ApiError(
            ERR_PRODUCT_LINE_STATE_BLOCKED,
            "The product line is in a status that forbids superseding this decision",
        )

    rec["status"] = "SUPERSEDED"
    db.bump(rec, now)

    card_set["print_run_status"] = "UNDECIDED"
    card_set["print_run_quantity"] = 0
    card_set["announced"] = False
    db.bump(card_set, now)

    from common import recompute_allocated_cards

    recompute_allocated_cards(store, line, now)
    return jsonify(response.ok_object(_serialize(rec))), 200