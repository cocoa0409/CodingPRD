"""Carrier endpoints: onboarding and lifecycle."""

from db import STORE, create_entity, touch, public, sort_default
from errors import ApiError, ERR_INVALID_STATE, ERR_CARRIER_HAS_OPEN_INVOICES
from middleware import (authenticate, require_roles, guard_read_scope,
                        in_read_scope, require_client_active, resolve,
                        READ_ROLES)
from response import success_object, success_list
from validate import get_body, check_shape, parse_pagination


def serialize_carrier(carrier):
    return public(carrier)


def _carrier_lifecycle(carrier_id, allowed_from, target):
    uid, role = authenticate()
    require_roles(role, {"FapAdmin"})
    carrier = resolve(STORE.carriers, carrier_id)
    require_client_active(STORE.clients.get(carrier["client_id"]))
    body = get_body()
    check_shape(body, {})
    if carrier["status"] not in allowed_from:
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Carrier cannot transition from %s" % carrier["status"])
    carrier["status"] = target
    touch(carrier)
    return success_object(serialize_carrier(carrier))


def register(app):

    @app.route("/fap/clients/<cid>/carriers", methods=["POST"])
    def create_carrier(cid):
        uid, role = authenticate()
        require_roles(role, {"FapAdmin"})
        client = resolve(STORE.clients, cid)
        require_client_active(client)
        body = get_body(allow_empty=False)
        check_shape(body, {
            "scac_code": {"kind": "string", "required": True},
            "legal_name": {"kind": "string", "required": True},
            "country": {"kind": "string", "required": True},
            "billing_currency": {"kind": "string", "required": True},
            "payment_terms_days": {"kind": "integer", "required": False},
            "remit_email": {"kind": "string", "required": True},
        })
        carrier = create_entity(STORE.carriers, {
            "client_id": cid,
            "scac_code": body["scac_code"],
            "legal_name": body["legal_name"],
            "country": body["country"],
            "billing_currency": body["billing_currency"],
            "payment_terms_days": body.get("payment_terms_days", 30),
            "remit_email": body["remit_email"],
            "status": "PENDING_ONBOARD",
        })
        return success_object(serialize_carrier(carrier), status=201)

    @app.route("/fap/carriers/<carrier_id>", methods=["GET"])
    def get_carrier(carrier_id):
        uid, role = authenticate()
        require_roles(role, READ_ROLES)
        carrier = guard_read_scope(role, uid, "carrier", STORE.carriers.get(carrier_id))
        return success_object(serialize_carrier(carrier))

    @app.route("/fap/carriers", methods=["GET"])
    def list_carriers():
        uid, role = authenticate()
        require_roles(role, READ_ROLES)
        limit, offset = parse_pagination()
        rows = list(STORE.carriers.values())
        rows = [c for c in rows if in_read_scope(role, uid, "carrier", c)]
        for param in ("client_id", "status"):
            value = _query(param)
            if value is not None:
                rows = [c for c in rows if str(c.get(param)) == value]
        rows = sort_default(rows)
        total = len(rows)
        page = rows[offset:offset + limit]
        return success_list([serialize_carrier(c) for c in page], limit, offset, total)

    @app.route("/fap/carriers/<carrier_id>/approve_onboard", methods=["POST"])
    def approve_onboard(carrier_id):
        return _carrier_lifecycle(carrier_id, {"PENDING_ONBOARD"}, "ACTIVE")

    @app.route("/fap/carriers/<carrier_id>/suspend", methods=["POST"])
    def suspend_carrier(carrier_id):
        return _carrier_lifecycle(carrier_id, {"ACTIVE"}, "SUSPENDED")

    @app.route("/fap/carriers/<carrier_id>/reinstate", methods=["POST"])
    def reinstate_carrier(carrier_id):
        return _carrier_lifecycle(carrier_id, {"SUSPENDED"}, "ACTIVE")

    @app.route("/fap/carriers/<carrier_id>/offboard", methods=["POST"])
    def offboard_carrier(carrier_id):
        uid, role = authenticate()
        require_roles(role, {"FapAdmin"})
        carrier = resolve(STORE.carriers, carrier_id)
        require_client_active(STORE.clients.get(carrier["client_id"]))
        body = get_body()
        check_shape(body, {})
        if carrier["status"] not in ("ACTIVE", "SUSPENDED"):
            raise ApiError(ERR_INVALID_STATE, 409,
                           "Carrier cannot be offboarded from %s" % carrier["status"])
        open_invoices = any(
            inv["carrier_id"] == carrier_id
            and inv["payment_status"] in ("UNPAID", "SCHEDULED")
            for inv in STORE.invoices.values()
        )
        if open_invoices:
            raise ApiError(ERR_CARRIER_HAS_OPEN_INVOICES, 409,
                           "Offboard attempted with UNPAID or SCHEDULED invoices")
        carrier["status"] = "OFFBOARDED"
        touch(carrier)
        return success_object(serialize_carrier(carrier))


def _query(name):
    from flask import request
    return request.args.get(name)
