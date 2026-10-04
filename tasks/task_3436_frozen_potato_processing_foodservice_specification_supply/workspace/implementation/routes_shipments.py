"""Shipment endpoints: create (IN_TRANSIT), deliver, reject-on-arrival.

Creation precedence (PRD 2.10): shape (4, including cold-chain setpoint and
lines syntax) -> existence: agreement then line run ids (5) -> line semantics:
runs RELEASED and owned by the agreement (ERR_INVALID_REQUEST, 400) -> state:
agreement ACTIVE (6) -> released-inventory capacity (10) -> SLA-review gate (11).
"""

from decimal import Decimal

import calcs
import domain
from db import store
from errors import ApiError
from flask import Blueprint, request
from middleware import ANY_ROLES, require_roles
from response import list_response, sort_default, success_object
from util import as_int, body_json, req_enum, req_int, req_number, req_present, req_str
from constants import EXCURSION_LIMIT_MINUTES, ROUTE_TYPES

bp = Blueprint("shipments", __name__)


def _bad(msg):
    raise ApiError("ERR_INVALID_REQUEST", msg, 400)


@bp.route("/potato-ops/shipments", methods=["POST"])
@require_roles("LogisticsCoordinator")
def create_shipment():
    body = body_json()
    agreement_id = req_str(body, "agreement_id")
    carrier_name = req_str(body, "carrier_name")
    setpoint = req_number(body, "trailer_setpoint_f")
    if setpoint > 0:
        _bad("Field 'trailer_setpoint_f': must be <= 0.0 (frozen cold chain)")
    route_type = req_enum(body, "route_type", ROUTE_TYPES)
    lines = req_present(body, "lines")
    if not isinstance(lines, list) or not lines:
        _bad("Field 'lines': must be a non-empty array of {run_id, cases}")
    normalized_lines = []
    for ln in lines:
        if not isinstance(ln, dict):
            _bad("Field 'lines': each entry must be an object {run_id, cases}")
        if not isinstance(ln.get("run_id"), str):
            _bad("Field 'lines[].run_id': must be a string")
        cases = as_int(ln.get("cases"))
        if cases is None or cases < 1:
            _bad("Field 'lines[].cases': must be an integer >= 1")
        normalized_lines.append({"run_id": ln["run_id"], "cases": cases})
    # Existence: agreement first, then run ids in line order.
    agreement = domain.get_agreement_or_404(agreement_id)
    runs = [domain.get_run_or_404(ln["run_id"]) for ln in normalized_lines]
    # Line semantics: every run must be RELEASED and belong to this agreement.
    for run in runs:
        if run["status"] != "RELEASED" or run["agreement_id"] != agreement["id"]:
            _bad(
                "Shipment lines reference a run of another agreement or a "
                "non-RELEASED run"
            )
    # State: agreement ACTIVE.
    if agreement["status"] != "ACTIVE":
        raise ApiError(
            "ERR_AGREEMENT_NOT_ACTIVE",
            "shipment creation requires the agreement ACTIVE",
            409,
        )
    # Capacity: total cases <= released_unshipped_cases.
    total_cases = sum(ln["cases"] for ln in normalized_lines)
    if total_cases > domain.released_unshipped_cases(agreement):
        raise ApiError(
            "ERR_UNRELEASED_CASES_EXCEEDED",
            "Shipment cases exceed the agreement's released_unshipped_cases",
            422,
        )
    # Credit/SLA gate.
    if agreement["under_sla_review"]:
        raise ApiError(
            "ERR_AGREEMENT_UNDER_SLA_REVIEW",
            "Shipment creation while the agreement is under SLA review",
            409,
        )
    ship = domain.new_entity()
    ship.update({
        "agreement_id": agreement_id,
        "carrier_name": carrier_name,
        "trailer_setpoint_f": body["trailer_setpoint_f"],
        "route_type": route_type,
        "lines": normalized_lines,
        "cases_shipped": total_cases,
        "max_transit_temp_f": None,
        "minutes_above_setpoint": None,
        "excursion_flag": False,
        "invoice_cents": None,
        "credit_memo_cents": None,
        "status": "IN_TRANSIT",
    })
    store.shipments[ship["id"]] = ship
    # lifetime_shipped_cases counts IN_TRANSIT shipments -> agreement changed.
    domain.touch(agreement)
    return success_object(domain.shipment_view(ship), 201)


@bp.route("/potato-ops/shipments", methods=["GET"])
@require_roles(*ANY_ROLES)
def list_shipments():
    items = list(store.shipments.values())
    agreement_id = request.args.get("agreement_id")
    status = request.args.get("status")
    if agreement_id is not None:
        items = [s for s in items if s["agreement_id"] == agreement_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    return list_response(sort_default(items), domain.shipment_view)


@bp.route("/potato-ops/shipments/<sid>", methods=["GET"])
@require_roles(*ANY_ROLES)
def get_shipment(sid):
    return success_object(domain.shipment_view(domain.get_shipment_or_404(sid)), 200)


@bp.route("/potato-ops/shipments/<sid>/deliver", methods=["POST"])
@require_roles("LogisticsCoordinator")
def deliver_shipment(sid):
    body = body_json()
    max_temp = req_number(body, "max_transit_temp_f")
    minutes = req_int(body, "minutes_above_setpoint")
    if minutes < 0:
        _bad("Field 'minutes_above_setpoint': must be >= 0")
    ship = domain.get_shipment_or_404(sid)
    if ship["status"] != "IN_TRANSIT":
        raise ApiError(
            "ERR_SHIPMENT_NOT_IN_TRANSIT",
            "deliver requires the shipment IN_TRANSIT",
            409,
        )
    agreement = store.agreements[ship["agreement_id"]]
    chain = store.chains[agreement["customer_id"]]
    old_fill = domain.compute_fill_rate_pct(chain["id"])
    ship["status"] = "DELIVERED"
    ship["max_transit_temp_f"] = body["max_transit_temp_f"]
    ship["minutes_above_setpoint"] = minutes
    ship["excursion_flag"] = minutes > EXCURSION_LIMIT_MINUTES
    ship["invoice_cents"] = calcs.invoice_cents(
        ship["lines"], agreement["price_per_case_cents"], ship["excursion_flag"]
    )
    domain.touch(ship)
    domain.apply_fill_rate_update(chain, old_fill)
    return success_object(domain.shipment_view(ship), 200)


@bp.route("/potato-ops/shipments/<sid>/reject-on-arrival", methods=["POST"])
@require_roles("LogisticsCoordinator")
def reject_shipment_on_arrival(sid):
    ship = domain.get_shipment_or_404(sid)
    if ship["status"] != "IN_TRANSIT":
        raise ApiError(
            "ERR_SHIPMENT_NOT_IN_TRANSIT",
            "reject-on-arrival requires the shipment IN_TRANSIT",
            409,
        )
    agreement = store.agreements[ship["agreement_id"]]
    chain = store.chains[agreement["customer_id"]]
    old_fill = domain.compute_fill_rate_pct(chain["id"])
    ship["status"] = "REJECTED_ON_ARRIVAL"
    ship["credit_memo_cents"] = calcs.credit_memo_cents(
        ship["lines"], agreement["price_per_case_cents"]
    )
    domain.touch(ship)
    # REJECTED_ON_ARRIVAL cases are not returned to inventory: the shipment stops
    # counting toward lifetime_shipped_cases -> agreement changed.
    domain.touch(agreement)
    domain.apply_fill_rate_update(chain, old_fill)
    return success_object(domain.shipment_view(ship), 200)
