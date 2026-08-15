"""GL accounts, invoice-line coding/allocations, and FX rates."""

from flask import request

from db import STORE, create_entity, touch, public, sort_default
from errors import (ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST,
                    ERR_ALLOCATION_SUM_INVALID, ERR_GL_ACCOUNT_INACTIVE,
                    ERR_DUPLICATE_FX_RATE)
from middleware import (authenticate, require_roles, guard_read_scope,
                        in_read_scope, require_client_active, resolve,
                        READ_ROLES)
from response import success_object, success_list
from services import replace_allocations
from validate import get_body, check_shape, parse_pagination

FX_SOURCES = ["ECB", "MANUAL"]


def register(app):

    # --- GL accounts --------------------------------------------------------

    @app.route("/fap/clients/<cid>/gl-accounts", methods=["POST"])
    def create_gl_account(cid):
        uid, role = authenticate()
        require_roles(role, {"FinanceController"})
        client = resolve(STORE.clients, cid)
        require_client_active(client)
        body = get_body(allow_empty=False)
        check_shape(body, {
            "code": {"kind": "string", "required": True},
            "business_unit": {"kind": "string", "required": True},
            "country": {"kind": "string", "required": True},
            "active": {"kind": "boolean", "required": False},
        })
        # GL code uniqueness per client.
        for other in STORE.gl_accounts.values():
            if other["client_id"] == cid and other["code"] == body["code"]:
                raise ApiError(ERR_INVALID_REQUEST, 409,
                               "GL account code already exists for this client")
        gl = create_entity(STORE.gl_accounts, {
            "client_id": cid,
            "code": body["code"],
            "business_unit": body["business_unit"],
            "country": body["country"],
            "active": body.get("active", True),
        })
        return success_object(public(gl), status=201)

    @app.route("/fap/gl-accounts/<gid>", methods=["GET"])
    def get_gl_account(gid):
        uid, role = authenticate()
        require_roles(role, READ_ROLES)
        gl = guard_read_scope(role, uid, "gl_account", STORE.gl_accounts.get(gid))
        return success_object(public(gl))

    @app.route("/fap/gl-accounts", methods=["GET"])
    def list_gl_accounts():
        uid, role = authenticate()
        require_roles(role, READ_ROLES)
        limit, offset = parse_pagination()
        rows = [g for g in STORE.gl_accounts.values()
                if in_read_scope(role, uid, "gl_account", g)]
        client_id = request.args.get("client_id")
        if client_id is not None:
            rows = [g for g in rows if g["client_id"] == client_id]
        rows = sort_default(rows)
        total = len(rows)
        page = rows[offset:offset + limit]
        return success_list([public(g) for g in page], limit, offset, total)

    @app.route("/fap/gl-accounts/<gid>/cost-allocations", methods=["GET"])
    def list_gl_allocations(gid):
        uid, role = authenticate()
        require_roles(role, READ_ROLES)
        gl = guard_read_scope(role, uid, "gl_account", STORE.gl_accounts.get(gid))
        limit, offset = parse_pagination()
        rows = [a for a in STORE.allocations.values()
                if a["gl_account_id"] == gl["id"]]
        rows = [a for a in rows if in_read_scope(role, uid, "allocation", a)]
        rows = sort_default(rows)
        total = len(rows)
        page = rows[offset:offset + limit]
        return success_list([public(a) for a in page], limit, offset, total)

    # --- invoice lines ------------------------------------------------------

    @app.route("/fap/invoice-lines/<lid>", methods=["GET"])
    def get_line(lid):
        uid, role = authenticate()
        require_roles(role, READ_ROLES)
        line = guard_read_scope(role, uid, "line", STORE.lines.get(lid))
        return success_object(public(line))

    @app.route("/fap/invoice-lines", methods=["GET"])
    def list_lines():
        uid, role = authenticate()
        require_roles(role, READ_ROLES)
        limit, offset = parse_pagination()
        rows = [l for l in STORE.lines.values()
                if in_read_scope(role, uid, "line", l)]
        for param in ("invoice_id", "gl_account_id"):
            value = request.args.get(param)
            if value is not None:
                rows = [l for l in rows if str(l.get(param)) == value]
        rows = sort_default(rows)
        total = len(rows)
        page = rows[offset:offset + limit]
        return success_list([public(l) for l in page], limit, offset, total)

    @app.route("/fap/invoice-lines/<lid>/gl-code", methods=["POST"])
    def gl_code_line(lid):
        uid, role = authenticate()
        require_roles(role, {"FinanceController"})
        line = resolve(STORE.lines, lid)
        invoice = STORE.invoices.get(line["invoice_id"])
        body = get_body(allow_empty=False)
        # Stage 3: body FK — gl_account_id exists and belongs to same client.
        gl_id = body.get("gl_account_id")
        gl = None
        if gl_id is not None:
            gl = STORE.gl_accounts.get(gl_id)
            if gl is None or gl["client_id"] != invoice["client_id"]:
                raise ApiError(ERR_NOT_FOUND, 404,
                               "Referenced gl_account_id does not exist")
        require_client_active(STORE.clients.get(invoice["client_id"]))
        check_shape(body, {
            "gl_account_id": {"kind": "string", "required": True},
        })
        # Stage 10: referential status — GL account must be active.
        if not gl["active"]:
            raise ApiError(ERR_GL_ACCOUNT_INACTIVE, 409,
                           "GL coding targets an inactive GL account")
        line["gl_account_id"] = gl_id
        touch(line)
        return success_object(public(line))

    @app.route("/fap/invoice-lines/<lid>/allocations", methods=["POST"])
    def set_line_allocations(lid):
        uid, role = authenticate()
        require_roles(role, {"FinanceController"})
        line = resolve(STORE.lines, lid)
        invoice = STORE.invoices.get(line["invoice_id"])
        body = get_body(allow_empty=False)
        allocations = body.get("allocations")
        # Stage 3: body FK — each gl_account_id exists and is same-client.
        if isinstance(allocations, list):
            for entry in allocations:
                if isinstance(entry, dict) and entry.get("gl_account_id") is not None:
                    gl = STORE.gl_accounts.get(entry["gl_account_id"])
                    if gl is None or gl["client_id"] != invoice["client_id"]:
                        raise ApiError(ERR_NOT_FOUND, 404,
                                       "Referenced gl_account_id does not exist")
        require_client_active(STORE.clients.get(invoice["client_id"]))
        check_shape(body, {
            "allocations": {"kind": "array", "required": True},
        })
        for entry in allocations:
            if not isinstance(entry, dict):
                raise ApiError(ERR_INVALID_REQUEST, 400,
                               "Each allocation must be an object")
            for key in entry:
                if key not in ("gl_account_id", "percentage_bp"):
                    raise ApiError(ERR_INVALID_REQUEST, 400,
                                   "Unknown allocation field: %s" % key)
            if "gl_account_id" not in entry or "percentage_bp" not in entry:
                raise ApiError(ERR_INVALID_REQUEST, 400,
                               "Allocation missing gl_account_id or percentage_bp")
            if not isinstance(entry["gl_account_id"], str):
                raise ApiError(ERR_INVALID_REQUEST, 400,
                               "gl_account_id must be a string")
            if not isinstance(entry["percentage_bp"], int) \
                    or isinstance(entry["percentage_bp"], bool):
                raise ApiError(ERR_INVALID_REQUEST, 400,
                               "percentage_bp must be an integer")
        # Stage 9: structural — shares must sum to exactly 10000 bp.
        if sum(e["percentage_bp"] for e in allocations) != 10000:
            raise ApiError(ERR_ALLOCATION_SUM_INVALID, 422,
                           "Allocation percentage_bp values do not sum to exactly 10000")
        # Stage 10: referential status — targets must be active.
        for entry in allocations:
            gl = STORE.gl_accounts.get(entry["gl_account_id"])
            if gl is None or not gl["active"]:
                raise ApiError(ERR_GL_ACCOUNT_INACTIVE, 409,
                               "Allocation targets an inactive GL account")
        replace_allocations(line, allocations)
        return success_object(public(line))

    @app.route("/fap/invoice-lines/<lid>/allocations", methods=["GET"])
    def list_line_allocations(lid):
        uid, role = authenticate()
        require_roles(role, READ_ROLES)
        line = guard_read_scope(role, uid, "line", STORE.lines.get(lid))
        limit, offset = parse_pagination()
        rows = [a for a in STORE.allocations.values()
                if a["invoice_line_id"] == line["id"]]
        rows = sort_default(rows)
        total = len(rows)
        page = rows[offset:offset + limit]
        return success_list([public(a) for a in page], limit, offset, total)

    # --- FX rates -----------------------------------------------------------

    @app.route("/fap/clients/<cid>/fx-rates", methods=["POST"])
    def create_fx_rate(cid):
        uid, role = authenticate()
        require_roles(role, {"FinanceController"})
        client = resolve(STORE.clients, cid)
        require_client_active(client)
        body = get_body(allow_empty=False)
        check_shape(body, {
            "from_currency": {"kind": "string", "required": True},
            "to_currency": {"kind": "string", "required": True},
            "effective_date": {"kind": "date", "required": True},
            "rate_ppm": {"kind": "integer", "required": True},
            "source": {"kind": "string", "required": True, "enum": FX_SOURCES},
        })
        for other in STORE.fx_rates.values():
            if other["client_id"] == cid \
                    and other["from_currency"] == body["from_currency"] \
                    and other["to_currency"] == body["to_currency"] \
                    and other["effective_date"] == body["effective_date"]:
                raise ApiError(ERR_DUPLICATE_FX_RATE, 409,
                               "FxRate already exists for client + pair + date")
        rate = create_entity(STORE.fx_rates, {
            "client_id": cid,
            "from_currency": body["from_currency"],
            "to_currency": body["to_currency"],
            "effective_date": body["effective_date"],
            "rate_ppm": body["rate_ppm"],
            "source": body["source"],
        })
        return success_object(public(rate), status=201)

    @app.route("/fap/clients/<cid>/fx-rates", methods=["GET"])
    def list_fx_rates(cid):
        uid, role = authenticate()
        require_roles(role, READ_ROLES)
        client = guard_read_scope(role, uid, "client", STORE.clients.get(cid))
        limit, offset = parse_pagination()
        rows = [r for r in STORE.fx_rates.values() if r["client_id"] == cid]
        for param in ("from_currency", "to_currency"):
            value = request.args.get(param)
            if value is not None:
                rows = [r for r in rows if r[param] == value]
        rows = sort_default(rows)
        total = len(rows)
        page = rows[offset:offset + limit]
        return success_list([public(r) for r in page], limit, offset, total)
