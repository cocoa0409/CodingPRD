"""Supplements, the adjuster's decision, resubmission and the owner's consent."""
from flask import Blueprint, request

import auth
import calc
import db
import guards
import response
import serialize
import validate
from db import store
from errors import raise_error
from validate import F

bp = Blueprint("supplements", __name__)

REASON_CODES = ("HIDDEN_DAMAGE", "PROCEDURE_REQUIREMENT", "PARTS_PRICE_VARIANCE",
                "CALIBRATION_REQUIRED")
DECISIONS = ("APPROVE", "PARTIAL", "DENY", "REQUEST_INFO")
CONSENT_DECISIONS = ("CONSENT", "DECLINE")

CREATE_SPEC = [
    F("reason_code", "string", required=True, enum=REASON_CODES),
    F("requested_amount_cents", "integer", required=True),
    F("expected_repair_order_version", "integer", required=True),
]


def _occ(order, expected):
    """Rung 11 (PRD 2.7)."""
    if int(order["version"]) != int(expected):
        raise_error("ERR_STALE_REPAIR_ORDER_VERSION")


@bp.route("/repair-orders/<order_id>/supplements", methods=["POST"])
def create_supplement(order_id):
    auth.authenticate(("Estimator",))
    data = validate.body(CREATE_SPEC)
    validate.require(data["requested_amount_cents"] > 0,
                     "requested_amount_cents must be > 0.")
    order = guards.find_order(order_id)
    _occ(order, data["expected_repair_order_version"])
    guards.not_terminal(order)

    bumper = calc.Bumper()
    row = db.base_row()
    row.update({
        "repair_order_id": order["id"],
        "reason_code": data["reason_code"],
        "requested_amount_cents": data["requested_amount_cents"],
        "approved_amount_cents": None,
        "status": "SUBMITTED",
        "round_count": 1,
        "submitted_at": db.now_iso(),
        "decided_at": None,
        "info_request_note": None,
        "adjuster_note": None,
    })
    store.supplements[row["id"]] = row
    calc.derive_posture(order)
    bumper.add(order)
    bumper.flush()
    return response.created(serialize.supplement(row))


@bp.route("/repair-orders/<order_id>/supplements", methods=["GET"])
def list_order_supplements(order_id):
    actor = auth.authenticate(("ShopAdmin", "Estimator", "InsurerAdjuster"))
    order = store.repair_orders.get(order_id)
    auth.own_order(actor, order)
    limit, offset = response.read_pagination(request.args)
    order = guards.find_order(order_id)
    rows = calc.order_supplements(order["id"])
    return response.paginate(rows, limit, offset, serialize.supplement)


@bp.route("/supplements/<supplement_id>", methods=["GET"])
def read_supplement(supplement_id):
    actor = auth.authenticate(("ShopAdmin", "Estimator", "InsurerAdjuster"))
    row = store.supplements.get(supplement_id)
    if row is not None:
        auth.own_order(actor, store.repair_orders.get(row["repair_order_id"]))
    if row is None:
        raise_error("ERR_SUPPLEMENT_NOT_FOUND")
    return response.ok(serialize.supplement(row))


DECISION_SPEC = [
    F("decision", "string", required=True, enum=DECISIONS),
    F("approved_amount_cents", "integer"),
    F("note", "string"),
]


def _rerun_after_decision(order, bumper):
    calc.apply_non_refinish_hours(order, bumper)
    calc.refinish_allocation(order, "FINAL", bumper)
    calc.approved_hours_rollup(order)
    calc.estimate_totals(order, bumper)
    calc.derive_posture(order)


@bp.route("/supplements/<supplement_id>/decision", methods=["POST"])
def decide_supplement(supplement_id):
    actor = auth.authenticate(("InsurerAdjuster",))
    supplement = store.supplements.get(supplement_id)
    if supplement is not None:
        auth.own_order(actor, store.repair_orders.get(supplement["repair_order_id"]))
    data = validate.body(DECISION_SPEC)
    if data["decision"] == "REQUEST_INFO":
        validate.require(bool(data["note"]) and data["note"].strip() != "",
                         "REQUEST_INFO requires a non-empty note.")
    if supplement is None:
        raise_error("ERR_SUPPLEMENT_NOT_FOUND")
    order = store.repair_orders.get(supplement["repair_order_id"])
    guards.not_terminal(order)
    if supplement["status"] != "SUBMITTED":
        raise_error("ERR_SUPPLEMENT_NOT_OPEN")

    decision = data["decision"]
    amount = data.get("approved_amount_cents")
    if decision == "PARTIAL":
        if amount is None or amount <= 0 or amount >= int(supplement["requested_amount_cents"]):
            raise_error("ERR_INVALID_PARTIAL_AMOUNT")
    elif decision in ("APPROVE", "DENY"):
        if amount is not None:
            raise_error("ERR_INVALID_PARTIAL_AMOUNT")

    bumper = calc.Bumper()
    linked = [l for l in calc.order_estimate_lines(order["id"])
              if l.get("supplement_id") == supplement["id"]]

    if decision == "REQUEST_INFO":
        supplement["status"] = "INFO_REQUESTED"
        supplement["info_request_note"] = data["note"]
        calc.derive_posture(order)
    else:
        if decision == "APPROVE":
            supplement["status"] = "APPROVED"
            supplement["approved_amount_cents"] = int(supplement["requested_amount_cents"])
        elif decision == "PARTIAL":
            supplement["status"] = "PARTIAL"
            supplement["approved_amount_cents"] = int(amount)
        else:
            supplement["status"] = "DENIED"
            supplement["approved_amount_cents"] = 0
        supplement["decided_at"] = db.now_iso()
        supplement["adjuster_note"] = data["note"]
        new_status = "REJECTED" if decision == "DENY" else "APPROVED"
        for line in linked:
            if line["line_status"] == "PENDING_SUPPLEMENT":
                line["line_status"] = new_status
                bumper.add(line)
        _rerun_after_decision(order, bumper)

    bumper.add(supplement)
    bumper.add(order)
    bumper.flush()
    return response.ok(serialize.supplement(supplement))


RESUBMIT_SPEC = [F("requested_amount_cents", "integer", required=True)]


@bp.route("/supplements/<supplement_id>/resubmit", methods=["POST"])
def resubmit_supplement(supplement_id):
    auth.authenticate(("Estimator",))
    data = validate.body(RESUBMIT_SPEC)
    validate.require(data["requested_amount_cents"] > 0,
                     "requested_amount_cents must be > 0.")
    supplement = store.supplements.get(supplement_id)
    if supplement is None:
        raise_error("ERR_SUPPLEMENT_NOT_FOUND")
    order = store.repair_orders.get(supplement["repair_order_id"])
    guards.not_terminal(order)
    if supplement["status"] != "INFO_REQUESTED":
        raise_error("ERR_SUPPLEMENT_NOT_OPEN")
    insurer = store.insurers.get(order["insurer_id"]) or {}
    limit = int(insurer.get("supplement_round_limit", 3))
    if int(supplement["round_count"]) >= limit:
        raise_error("ERR_SUPPLEMENT_ROUND_LIMIT")

    bumper = calc.Bumper()
    supplement["status"] = "SUBMITTED"
    supplement["requested_amount_cents"] = data["requested_amount_cents"]
    supplement["round_count"] = int(supplement["round_count"]) + 1
    supplement["submitted_at"] = db.now_iso()
    supplement["info_request_note"] = None
    calc.derive_posture(order)
    bumper.add(supplement)
    bumper.add(order)
    bumper.flush()
    return response.ok(serialize.supplement(supplement))


CONSENT_SPEC = [
    F("decision", "string", required=True, enum=CONSENT_DECISIONS),
    F("alternate_parts_ok", "boolean", required=True),
    F("expected_repair_order_version", "integer", required=True),
]


@bp.route("/repair-orders/<order_id>/consent-decisions", methods=["POST"])
def record_consent(order_id):
    actor = auth.authenticate(("Customer",))
    order = store.repair_orders.get(order_id)
    auth.own_order(actor, order)
    data = validate.body(CONSENT_SPEC)
    order = guards.find_order(order_id)
    _occ(order, data["expected_repair_order_version"])
    guards.not_terminal(order)

    bumper = calc.Bumper()
    if data["decision"] == "CONSENT":
        order["consent_state"] = "CONSENTED"
        order["consent_basis_cents"] = int(order.get("customer_pay_cents") or 0)
        order["consent_alternate_parts"] = bool(data["alternate_parts_ok"])
        alternate_ok = bool(data["alternate_parts_ok"])
    else:
        order["consent_state"] = "DECLINED"
        alternate_ok = False

    new_status = "CUSTOMER_CONSENTED" if alternate_ok else "CUSTOMER_DECLINED"
    for parts_line in calc.order_parts_lines(order["id"]):
        if parts_line["authorization_status"] == "PENDING_CONSENT":
            parts_line["authorization_status"] = new_status
            bumper.add(parts_line)

    calc.estimate_totals(order, bumper)
    calc.derive_posture(order)
    bumper.add(order)
    bumper.flush()
    return response.ok(serialize.repair_order(order))
