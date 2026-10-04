"""Reporting reads: technicians, campaigns (PRD 3.11, 3.12, 3.14)."""

from flask import Blueprint, request

from constants import (ROLE_DISPATCHER, ROLE_TECHNICIAN, ROLE_MANAGER,
                       ROLE_CUSTOMER_SERVICE, ROLE_PLATFORM_ADMIN)
from common import require_roles, query_bool
import store
import serializers
import calc
from errors import not_found, invalid_request
from response import object_ok, success
from store import iso

bp = Blueprint("reporting", __name__)


def _query_int(name):
    """Query parameters arrive as strings, never from a JSON body."""
    raw = request.args.get(name)
    if raw in (None, ""):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise invalid_request("query parameter '%s' must be an integer" % name)


@bp.route("/technicians/<technician_id>", methods=["GET"])
def get_technician(technician_id):
    require_roles([ROLE_DISPATCHER, ROLE_TECHNICIAN, ROLE_MANAGER, ROLE_PLATFORM_ADMIN])
    row = store.technicians.get(technician_id)
    if row is None:
        raise not_found("technician")
    return object_ok(serializers.technician(row))


@bp.route("/technicians/<technician_id>/incentive-statement", methods=["GET"])
def incentive_statement(technician_id):
    require_roles([ROLE_MANAGER, ROLE_TECHNICIAN])
    row = store.technicians.get(technician_id)
    if row is None:
        raise not_found("technician")
    # period_year and period_month are informational; the computation walks the
    # technician's completed appointments as PRD 3.11 specifies.
    period_year = _query_int("period_year")
    period_month = _query_int("period_month")
    statement = calc.incentive_statement(row)
    statement["period_year"] = period_year
    statement["period_month"] = period_month
    return object_ok(statement)


@bp.route("/technicians/<technician_id>/performance", methods=["GET"])
def performance(technician_id):
    require_roles([ROLE_MANAGER, ROLE_TECHNICIAN])
    row = store.technicians.get(technician_id)
    if row is None:
        raise not_found("technician")
    review = calc.technician_performance_review(technician_id)
    return object_ok({
        "window_start_utc": iso(review["window_start_utc"]),
        "window_end_utc": iso(review["window_end_utc"]),
        "window_revenue_cents": review["window_revenue_cents"],
        "grade": review["grade"],
    })


@bp.route("/campaigns/<campaign_id>", methods=["GET"])
def get_campaign(campaign_id):
    require_roles([ROLE_DISPATCHER, ROLE_TECHNICIAN, ROLE_MANAGER, ROLE_CUSTOMER_SERVICE])
    row = store.campaigns.get(campaign_id)
    if row is None:
        raise not_found("campaign")
    include = query_bool("include_attribution", False)
    variant = request.args.get("attribution_variant")
    return object_ok(serializers.campaign(row, include_attribution=include, variant=variant))


@bp.route("/appointments/<appointment_id>/settlement", methods=["GET"])
def settlement(appointment_id):
    """Inert read of the appointment_settlement_balance read model (PRD 3.14).
    Not in the routing table of PRD section 4."""
    from common import auth
    auth()
    row = store.appointments.get(appointment_id)
    if row is None:
        raise not_found("appointment")
    variant = request.args.get("variant")
    return object_ok(calc.appointment_settlement(row, variant))