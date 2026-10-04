"""Service-visit routes: request, schedule, perform and cancel."""

from flask import request

import db
import middleware
import response
import serializers
from errors import ApiError
from routes._common import endpoint, q
from services import calculations as calc
from services import factory, queries, workflows
from util import fmt_ts, parse_ts

VISIT_READERS = ["ServiceCoordinator", "Customer", "PlatformAdmin"]


def register(app):

    @endpoint(app, "POST", "/alarm-funding/service-visits", ["ServiceCoordinator"])
    def create_visit(actor):
        body = middleware.body_or_empty(request)
        middleware.required(body, "contract_id", "scheduled_at", "work_type", "technician_id")
        contract = middleware.require_fk("contracts", body.get("contract_id"), "contract_id")
        scheduled_at = middleware.as_timestamp(body["scheduled_at"], "scheduled_at")
        work_type = middleware.as_enum(body["work_type"], "work_type", {"REPAIR", "WARRANTY_REPAIR"})
        technician_id = middleware.as_str(body["technician_id"], "technician_id")
        duration = middleware.as_int(body.get("duration_minutes", 120) or 120,
                                     "duration_minutes", 1, None)
        allowed = middleware.as_int(body.get("allowed_duration_minutes", 60) or 60,
                                    "allowed_duration_minutes", 1, None)
        visit = factory.make_service_visit(contract["id"], scheduled_at, work_type,
                                           technician_id, duration, allowed)
        return response.envelope_object(serializers.serialize("service_visit", visit)), 201

    @endpoint(app, "GET", "/alarm-funding/service-visits", VISIT_READERS)
    def list_visits(actor):
        rows = db.state.all("service_visits")
        for field in ("contract_id", "technician_id", "visit_status"):
            value = q(field)
            if value is not None:
                rows = [r for r in rows if r.get(field) == value]
        rows = queries.sorted_by_created(rows)
        limit, offset = response.resolve_pagination(request.args)
        page, total = response.paginate(rows, limit, offset)
        return response.envelope_array(serializers.serialize_many("service_visit", page), limit, offset, total), 200

    @endpoint(app, "GET", "/alarm-funding/service-visits/<id>", VISIT_READERS)
    def read_visit(actor, id):
        visit = middleware.resolve("service_visits", id)
        return response.envelope_object(serializers.serialize("service_visit", visit)), 200

    @endpoint(app, "POST", "/alarm-funding/service-visits/<id>/schedule", ["ServiceCoordinator"])
    def schedule_visit(actor, id):
        visit = middleware.resolve("service_visits", id)
        if visit.get("visit_status") != "REQUESTED":
            raise ApiError("ERR_INVALID_STATE")
        body = middleware.body_or_empty(request)
        middleware.required(body, "scheduled_at")
        scheduled_at = middleware.as_timestamp(body["scheduled_at"], "scheduled_at")
        minutes = visit.get("allowed_duration_minutes", 60) or 60
        if workflows.technician_overlap(visit, visit.get("technician_id"), scheduled_at, minutes):
            raise ApiError("ERR_SERVICE_WINDOW_OVERLAP")
        contract = db.state.get("contracts", visit["contract_id"])
        visit["scheduled_at"] = fmt_ts(scheduled_at)
        visit["warranty_status_at_visit"] = workflows.warranty_status_at(contract, scheduled_at) \
            if contract is not None else False
        visit["visit_status"] = "SCHEDULED"
        db.bump(visit)
        return response.envelope_object(serializers.serialize("service_visit", visit)), 200

    @endpoint(app, "POST", "/alarm-funding/service-visits/<id>/perform", ["ServiceCoordinator"])
    def perform_visit(actor, id):
        visit = middleware.resolve("service_visits", id)
        if visit.get("visit_status") != "SCHEDULED":
            raise ApiError("ERR_INVALID_STATE")
        contract = middleware.resolve("contracts", visit["contract_id"])
        dealer = db.state.get("dealers", contract.get("dealer_id"))
        in_warranty = bool(visit.get("warranty_status_at_visit"))
        visit["billed_cents"] = calc.DEALER_VISIT_FEE_CENTS
        if in_warranty:
            visit["billing_route"] = "CUSTOMER"
            visit["dealer_sweep_cents"] = 0
        else:
            visit["billing_route"] = "DEALER_HOLDBACK"
            visit["dealer_sweep_cents"] = calc.DEALER_VISIT_FEE_CENTS
            if dealer is not None:
                calc.post_warranty_service_sweep(contract, dealer)
                db.bump(dealer)
        visit["performed_at"] = fmt_ts(db.now())
        visit["visit_status"] = "PERFORMED"
        db.bump(visit)
        return response.envelope_object(serializers.serialize("service_visit", visit)), 200

    @endpoint(app, "POST", "/alarm-funding/service-visits/<id>/cancel", ["ServiceCoordinator"])
    def cancel_visit(actor, id):
        visit = middleware.resolve("service_visits", id)
        if visit.get("visit_status") != "SCHEDULED":
            raise ApiError("ERR_INVALID_STATE")
        scheduled_at = parse_ts(visit.get("scheduled_at"))
        if scheduled_at is None or not (db.now() < scheduled_at):
            raise ApiError("ERR_INVALID_STATE",
                           "A visit may be cancelled only strictly before its scheduled instant.")
        visit["visit_status"] = "CANCELLED"
        db.bump(visit)
        return response.envelope_object(serializers.serialize("service_visit", visit)), 200