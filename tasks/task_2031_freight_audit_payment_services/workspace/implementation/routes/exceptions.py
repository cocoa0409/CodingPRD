"""AuditException endpoints: negotiation loop, resolution, escalation."""

from flask import request

import db
from db import STORE, touch, public, sort_default, today, parse_date
from errors import (ApiError, ERR_INVALID_STATE, ERR_NEGOTIATION_ROUND_LIMIT,
                    ERR_DISPUTE_WINDOW_EXPIRED, ERR_CREDIT_EXCEEDS_DISPUTED,
                    ERR_INVALID_REQUEST, ERR_AMOUNT_INVALID)
from middleware import (authenticate, require_roles, guard_read_scope,
                        guard_mutation_scope, in_read_scope,
                        require_client_active, resolve, READ_ROLES)
from response import success_object, success_list
from services import apply_resolution
from validate import get_body, check_shape, parse_pagination


def _dispute_window_open(exc, client):
    deadline = parse_date(db.add_days(exc["opened_date"],
                                      client["dispute_window_days"]))
    if today() > deadline:
        raise ApiError(ERR_DISPUTE_WINDOW_EXPIRED, 409,
                       "Dispute window has expired for this exception")


def register(app):

    @app.route("/fap/clients/<cid>/exceptions", methods=["GET"])
    def list_client_exceptions(cid):
        uid, role = authenticate()
        require_roles(role, READ_ROLES)
        client = guard_read_scope(role, uid, "client", STORE.clients.get(cid))
        limit, offset = parse_pagination()
        rows = [e for e in STORE.exceptions.values() if e["client_id"] == cid]
        rows = [e for e in rows if in_read_scope(role, uid, "exception", e)]
        status = request.args.get("status")
        if status is not None:
            rows = [e for e in rows if e["status"] == status]
        rows = sort_default(rows)
        total = len(rows)
        page = rows[offset:offset + limit]
        return success_list([public(e) for e in page], limit, offset, total)

    @app.route("/fap/exceptions/<eid>/notify_carrier", methods=["POST"])
    def notify_carrier(eid):
        uid, role = authenticate()
        require_roles(role, {"AuditAnalyst"})
        exc = resolve(STORE.exceptions, eid)
        client = STORE.clients.get(exc["client_id"])
        require_client_active(client)
        body = get_body()
        check_shape(body, {})
        if exc["status"] != "OPEN":
            raise ApiError(ERR_INVALID_STATE, 409,
                           "Exception cannot be notified from %s" % exc["status"])
        _dispute_window_open(exc, client)
        exc["status"] = "CARRIER_NOTIFIED"
        touch(exc)
        return success_object(public(exc))

    @app.route("/fap/exceptions/<eid>/carrier_respond", methods=["POST"])
    def carrier_respond(eid):
        uid, role = authenticate()
        require_roles(role, {"CarrierRep"})
        exc = resolve(STORE.exceptions, eid)
        guard_mutation_scope(role, uid, "exception", exc)
        client = STORE.clients.get(exc["client_id"])
        require_client_active(client)
        body = get_body()
        check_shape(body, {
            "response_note": {"kind": "string", "required": False},
        })
        if exc["status"] != "CARRIER_NOTIFIED":
            raise ApiError(ERR_INVALID_STATE, 409,
                           "Exception cannot be answered from %s" % exc["status"])
        _dispute_window_open(exc, client)
        exc["status"] = "CARRIER_RESPONDED"
        touch(exc)
        return success_object(public(exc))

    @app.route("/fap/exceptions/<eid>/counter", methods=["POST"])
    def counter(eid):
        uid, role = authenticate()
        require_roles(role, {"AuditAnalyst"})
        exc = resolve(STORE.exceptions, eid)
        require_client_active(STORE.clients.get(exc["client_id"]))
        body = get_body()
        check_shape(body, {})
        if exc["status"] != "CARRIER_RESPONDED":
            raise ApiError(ERR_INVALID_STATE, 409,
                           "Exception cannot be countered from %s" % exc["status"])
        if exc["round_count"] >= 3:
            raise ApiError(ERR_NEGOTIATION_ROUND_LIMIT, 409,
                           "Counter attempted when round_count == 3")
        exc["round_count"] += 1
        exc["status"] = "CARRIER_NOTIFIED"
        touch(exc)
        return success_object(public(exc))

    @app.route("/fap/exceptions/<eid>/resolve", methods=["POST"])
    def resolve_exception(eid):
        uid, role = authenticate()
        require_roles(role, {"AuditAnalyst", "FapAdmin"})
        exc = resolve(STORE.exceptions, eid)
        require_client_active(STORE.clients.get(exc["client_id"]))
        body = get_body(allow_empty=False)
        check_shape(body, {
            "outcome": {"kind": "string", "required": True,
                        "enum": ["ACCEPT", "CONCEDE"]},
            "credit_minor": {"kind": "integer", "required": False},
        })
        outcome = body["outcome"]
        credit = body.get("credit_minor")
        if role == "FapAdmin":
            # Force-resolution: ESCALATED -> RESOLVED_CONCEDED only.
            if exc["status"] != "ESCALATED" or outcome != "CONCEDE":
                raise ApiError(ERR_INVALID_STATE, 409,
                               "Exception cannot be resolved from %s"
                               % exc["status"])
        else:  # AuditAnalyst
            if exc["status"] != "CARRIER_RESPONDED":
                raise ApiError(ERR_INVALID_STATE, 409,
                               "Exception cannot be resolved from %s"
                               % exc["status"])
        if outcome == "CONCEDE":
            if credit is None:
                raise ApiError(ERR_INVALID_REQUEST, 400,
                               "Missing required field: credit_minor")
            if credit < 0:
                raise ApiError(ERR_AMOUNT_INVALID, 422,
                               "credit_minor must be non-negative")
            if credit > exc["disputed_amount_minor"]:
                raise ApiError(ERR_CREDIT_EXCEEDS_DISPUTED, 409,
                               "Concession credit exceeds disputed_amount_minor")
        apply_resolution(exc, outcome, credit)
        return success_object(public(exc))

    @app.route("/fap/exceptions/<eid>/escalate", methods=["POST"])
    def escalate(eid):
        uid, role = authenticate()
        require_roles(role, {"AuditAnalyst"})
        exc = resolve(STORE.exceptions, eid)
        require_client_active(STORE.clients.get(exc["client_id"]))
        body = get_body()
        check_shape(body, {})
        if exc["status"] not in ("OPEN", "CARRIER_NOTIFIED", "CARRIER_RESPONDED"):
            raise ApiError(ERR_INVALID_STATE, 409,
                           "Exception cannot be escalated from %s" % exc["status"])
        exc["status"] = "ESCALATED"
        touch(exc)
        return success_object(public(exc))
