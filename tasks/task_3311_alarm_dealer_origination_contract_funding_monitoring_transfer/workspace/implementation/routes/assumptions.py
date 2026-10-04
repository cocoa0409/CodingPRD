"""Assumption-request, contract-owner and rescission-request routes."""

from flask import request

import db
import middleware
import response
import serializers
from errors import ApiError
from routes._common import endpoint, q
from services import calculations as calc
from services import factory, queries, workflows
from util import fmt_ts, parse_ts, whole_calendar_days

ASSUMPTION_READERS = ["Customer", "FundingAnalyst", "ServiceCoordinator", "PlatformAdmin"]
OWNER_READERS = ["Customer", "FundingAnalyst", "ComplianceOfficer", "PlatformAdmin"]
RESCISSION_READERS = ["Customer", "ComplianceOfficer", "FundingAnalyst", "PlatformAdmin"]


def register(app):

    # --- Assumption -------------------------------------------------------

    @endpoint(app, "POST", "/alarm-funding/assumption-requests",
              ["Customer", "FundingAnalyst", "ServiceCoordinator"])
    def create_assumption(actor):
        body = middleware.body_or_empty(request)
        middleware.required(body, "contract_id", "incoming_customer_id",
                            "incoming_credit_score", "residence_state_code")
        contract = middleware.require_fk("contracts", body.get("contract_id"), "contract_id")
        incoming = middleware.require_fk("customers", body.get("incoming_customer_id"),
                                         "incoming_customer_id")
        score = middleware.as_int(body["incoming_credit_score"], "incoming_credit_score", 300, 850)
        state_code = middleware.as_str(body["residence_state_code"], "residence_state_code", length=2)
        request_row = factory.make_assumption_request(contract["id"], incoming["id"], score, state_code)
        return response.envelope_object(serializers.serialize("assumption_request", request_row)), 201

    @endpoint(app, "GET", "/alarm-funding/assumption-requests", ASSUMPTION_READERS)
    def list_assumptions(actor):
        rows = db.state.all("assumption_requests")
        for field in ("contract_id", "request_status"):
            value = q(field)
            if value is not None:
                rows = [r for r in rows if r.get(field) == value]
        rows = queries.sorted_by_created(rows)
        limit, offset = response.resolve_pagination(request.args)
        page, total = response.paginate(rows, limit, offset)
        return response.envelope_array(serializers.serialize_many("assumption_request", page), limit, offset, total), 200

    @endpoint(app, "GET", "/alarm-funding/assumption-requests/<id>", ASSUMPTION_READERS)
    def read_assumption(actor, id):
        request_row = middleware.resolve("assumption_requests", id)
        return response.envelope_object(serializers.serialize("assumption_request", request_row)), 200

    @endpoint(app, "GET", "/alarm-funding/assumption-requests/<id>/owners", OWNER_READERS)
    def assumption_owners(actor, id):
        middleware.resolve("assumption_requests", id)
        rows = [o for o in db.state.contract_owners.values() if o.get("assumption_request_id") == id]
        rows = queries.sorted_by_created(rows)
        limit, offset = response.resolve_pagination(request.args)
        page, total = response.paginate(rows, limit, offset)
        return response.envelope_array(serializers.serialize_many("contract_owner", page), limit, offset, total), 200

    @endpoint(app, "POST", "/alarm-funding/assumption-requests/<id>/accept", ["FundingAnalyst"])
    def accept_assumption(actor, id):
        request_row = middleware.resolve("assumption_requests", id)
        if request_row.get("request_status") != "PENDING_NEGOTIATION":
            raise ApiError("ERR_INVALID_STATE")
        if request_row.get("incoming_credit_score", 0) < calc.CREDIT_FLOOR:
            raise ApiError("ERR_CREDIT_SCORE_BELOW_FLOOR")
        request_row["request_status"] = "ACCEPTED"
        request_row["accepted_at"] = fmt_ts(db.now())
        db.bump(request_row)
        return response.envelope_object(serializers.serialize("assumption_request", request_row)), 200

    @endpoint(app, "POST", "/alarm-funding/assumption-requests/<id>/reject", ["FundingAnalyst"])
    def reject_assumption(actor, id):
        request_row = middleware.resolve("assumption_requests", id)
        status = request_row.get("request_status")
        if status not in ("PENDING_NEGOTIATION", "ACCEPTED"):
            raise ApiError("ERR_INVALID_STATE")
        if status == "ACCEPTED":
            # A counterparty withdrawal returns the request to negotiation.
            request_row["request_status"] = "PENDING_NEGOTIATION"
            request_row["accepted_at"] = None
            db.bump(request_row)
            return response.envelope_object(serializers.serialize("assumption_request", request_row)), 200
        state_code = request_row.get("residence_state_code")
        # PRD §3.9 — the reject paragraph states "a residence outside the radius is
        # refused with ERR_RESIDENCE_OUTSIDE_SERVICE_RADIUS", so the radius guard
        # fires on the reject path exactly as it does on the completion gate.
        if state_code not in calc.RELOCATION_RADIUS:
            raise ApiError("ERR_RESIDENCE_OUTSIDE_SERVICE_RADIUS")
        request_row["rejection_count"] = request_row.get("rejection_count", 0) + 1
        if request_row["rejection_count"] >= 3:
            request_row["request_status"] = "REJECTED"
            owner = queries.current_owner_for_contract(request_row["contract_id"])
            if owner is not None:
                owner["ended_at"] = fmt_ts(db.now())
                db.bump(owner)
        else:
            request_row["request_status"] = "PENDING_NEGOTIATION"
        db.bump(request_row)
        return response.envelope_object(serializers.serialize("assumption_request", request_row)), 200

    @endpoint(app, "POST", "/alarm-funding/assumption-requests/<id>/complete",
              ["Customer", "FundingAnalyst"])
    def complete_assumption(actor, id):
        request_row = middleware.resolve("assumption_requests", id)
        if request_row.get("request_status") != "ACCEPTED":
            raise ApiError("ERR_INVALID_STATE")
        contract = middleware.resolve("contracts", request_row["contract_id"])
        if request_row.get("incoming_credit_score", 0) < calc.CREDIT_FLOOR:
            raise ApiError("ERR_CREDIT_SCORE_BELOW_FLOOR")
        if request_row.get("residence_state_code") not in calc.RELOCATION_RADIUS:
            raise ApiError("ERR_RESIDENCE_OUTSIDE_SERVICE_RADIUS")
        outgoing_id = contract.get("customer_id")
        if not queries.customer_has_other_live_contract(outgoing_id, contract["id"]):
            raise ApiError("ERR_ASSUMED_CONTRACT_MUST_HAVE_SURVIVING_CONTRACT")
        if queries.open_service_required(contract["id"]) is not None:
            raise ApiError("ERR_FALSE_ALARM_WATCH_ACTIVE")
        workflows.complete_assumption(request_row)
        return response.envelope_object(serializers.serialize("assumption_request", request_row)), 200

    # --- Contract owners --------------------------------------------------

    @endpoint(app, "GET", "/alarm-funding/contract-owners", OWNER_READERS)
    def list_owners(actor):
        rows = db.state.all("contract_owners")
        for field in ("contract_id", "customer_id", "ownership_status"):
            value = q(field)
            if value is not None:
                rows = [r for r in rows if r.get(field) == value]
        rows = queries.sorted_by_created(rows)
        limit, offset = response.resolve_pagination(request.args)
        page, total = response.paginate(rows, limit, offset)
        return response.envelope_array(serializers.serialize_many("contract_owner", page), limit, offset, total), 200

    # --- Rescission -------------------------------------------------------

    @endpoint(app, "POST", "/alarm-funding/rescission-requests", ["Customer", "ComplianceOfficer"])
    def create_rescission(actor):
        body = middleware.body_or_empty(request)
        middleware.required(body, "contract_id", "operator_id")
        contract = middleware.require_fk("contracts", body.get("contract_id"), "contract_id")
        operator_id = middleware.as_str(body["operator_id"], "operator_id")
        funded_at = parse_ts(contract.get("funded_at"))
        days = whole_calendar_days(funded_at, db.now()) if funded_at is not None else 0
        request_row = factory.make_rescission_request(contract["id"], operator_id, days)
        return response.envelope_object(serializers.serialize("rescission_request", request_row)), 201

    @endpoint(app, "GET", "/alarm-funding/rescission-requests", RESCISSION_READERS)
    def list_rescissions(actor):
        rows = db.state.all("rescission_requests")
        for field in ("contract_id", "request_status"):
            value = q(field)
            if value is not None:
                rows = [r for r in rows if r.get(field) == value]
        rows = queries.sorted_by_created(rows)
        limit, offset = response.resolve_pagination(request.args)
        page, total = response.paginate(rows, limit, offset)
        return response.envelope_array(serializers.serialize_many("rescission_request", page), limit, offset, total), 200

    @endpoint(app, "GET", "/alarm-funding/rescission-requests/<id>", RESCISSION_READERS)
    def read_rescission(actor, id):
        request_row = middleware.resolve("rescission_requests", id)
        return response.envelope_object(serializers.serialize("rescission_request", request_row)), 200

    @endpoint(app, "POST", "/alarm-funding/rescission-requests/<id>/decision", ["ComplianceOfficer"])
    def decide_rescission(actor, id):
        request_row = middleware.resolve("rescission_requests", id)
        body = middleware.body_or_empty(request)
        middleware.required(body, "outcome")
        outcome = middleware.as_enum(body["outcome"], "outcome", {"APPROVED", "DECLINED"})
        request_row = workflows.decide_rescission(request_row, outcome, actor.user_id)
        # Both the contract and the dealer move on the approval path.
        contract = db.state.get("contracts", request_row["contract_id"])
        return response.envelope_object(serializers.serialize("rescission_request", request_row)), 200

    @endpoint(app, "POST", "/alarm-funding/rescission-requests/<id>/approve", ["ComplianceOfficer"])
    def approve_rescission(actor, id):
        request_row = middleware.resolve("rescission_requests", id)
        request_row = workflows.decide_rescission(request_row, "APPROVED", actor.user_id)
        return response.envelope_object(serializers.serialize("rescission_request", request_row)), 200

    # --- Logical clock ----------------------------------------------------

    @endpoint(app, "POST", "/alarm-funding/_clock/set_current_utc", ["PlatformAdmin"])
    def set_clock(actor):
        import db as db_module
        body = middleware.body_or_empty(request)
        middleware.required(body, "to_iso8601")
        instant = middleware.as_timestamp(body["to_iso8601"], "to_iso8601")
        db_module.set_clock(instant)
        return response.envelope_object({"current_utc": fmt_ts(db_module.now())}), 200