"""CarrierInvoice endpoints: intake, capture, rating, finalization, void,
write-off, plus nested collection reads (lines, exceptions, run items, claims)."""

from flask import request

from db import STORE, create_entity, touch, public, sort_default
from errors import (ApiError, ERR_INVALID_STATE, ERR_DUPLICATE_INVOICE_NUMBER,
                    ERR_AMOUNT_MISMATCH, ERR_AMOUNT_INVALID, ERR_NOT_FOUND,
                    ERR_INVALID_REQUEST, ERR_INVOICE_NOT_PAYABLE,
                    ERR_EXCEPTION_STILL_ACTIVE)
from middleware import (authenticate, require_roles, guard_read_scope,
                        in_read_scope, require_client_active, resolve,
                        READ_ROLES)
from response import success_object, success_list
from services import (CHARGE_CODES, rate_invoice, no_contract_transition,
                      detect_fuzzy_duplicate, finalize_invoice, invoice_lines,
                      invoice_exceptions, run_items_of)
from validate import get_body, check_shape, parse_pagination

RATE_POLICIES = ["SHIP_DATE", "INVOICE_DATE"]


def serialize_invoice(invoice):
    return public(invoice)


def serialize_line(line):
    return public(line)


def _validate_lines_shape(lines):
    for entry in lines:
        if not isinstance(entry, dict):
            raise ApiError(ERR_INVALID_REQUEST, 400, "Each line must be an object")
        for key in entry:
            if key not in ("charge_code", "billed_amount_minor"):
                raise ApiError(ERR_INVALID_REQUEST, 400,
                               "Unknown line field: %s" % key)
        if "charge_code" not in entry or "billed_amount_minor" not in entry:
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "Line missing charge_code or billed_amount_minor")
        if entry["charge_code"] not in CHARGE_CODES:
            raise ApiError(ERR_INVALID_REQUEST, 400, "Invalid charge_code")
        if not isinstance(entry["billed_amount_minor"], int) \
                or isinstance(entry["billed_amount_minor"], bool):
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "billed_amount_minor must be an integer")


def register(app):

    @app.route("/fap/clients/<cid>/invoices", methods=["POST"])
    def create_invoice(cid):
        uid, role = authenticate()
        require_roles(role, {"AuditAnalyst"})
        client = resolve(STORE.clients, cid)
        body = get_body(allow_empty=False)
        # Stage 3: body FK existence — carrier_id and shipment_id.
        carrier_id = body.get("carrier_id")
        carrier = None
        if carrier_id is not None:
            carrier = STORE.carriers.get(carrier_id)
            if carrier is None or carrier["client_id"] != cid:
                raise ApiError(ERR_NOT_FOUND, 404,
                               "Referenced carrier_id does not exist")
        shipment_id = body.get("shipment_id")
        shipment = None
        if shipment_id is not None:
            shipment = STORE.shipments.get(shipment_id)
            if shipment is None or shipment["client_id"] != cid:
                raise ApiError(ERR_NOT_FOUND, 404,
                               "Referenced shipment_id does not exist")
        # Stage 5: client lifecycle gate.
        require_client_active(client)
        # Stage 6: request shape.
        check_shape(body, {
            "carrier_id": {"kind": "string", "required": True},
            "invoice_number": {"kind": "string", "required": True},
            "invoice_date": {"kind": "date", "required": True},
            "currency": {"kind": "string", "required": True},
            "billed_total_minor": {"kind": "integer", "required": True},
            "lines": {"kind": "array", "required": True},
            "shipment_id": {"kind": "string", "required": False},
        })
        _validate_lines_shape(body["lines"])
        if body["currency"] != carrier["billing_currency"]:
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "Invoice currency must equal the carrier billing_currency")
        # Stage 9: uniqueness, then line-total agreement.
        for other in STORE.invoices.values():
            if other["client_id"] == cid and other["carrier_id"] == carrier_id \
                    and other["audit_status"] != "VOIDED" \
                    and other["invoice_number"] == body["invoice_number"]:
                raise ApiError(ERR_DUPLICATE_INVOICE_NUMBER, 409,
                               "invoice_number already used by a non-VOIDED invoice")
        line_sum = sum(l["billed_amount_minor"] for l in body["lines"])
        if body["billed_total_minor"] != line_sum:
            raise ApiError(ERR_AMOUNT_MISMATCH, 422,
                           "billed_total_minor != sum of line billed amounts")
        # Stage 10: referential status — linked shipment must not be VOIDED.
        if shipment is not None and shipment["status"] == "VOIDED":
            raise ApiError(ERR_INVALID_STATE, 409,
                           "Linked shipment is VOIDED")
        # Stage 11: fiscal amounts.
        if body["billed_total_minor"] <= 0:
            raise ApiError(ERR_AMOUNT_INVALID, 422,
                           "billed_total_minor must be positive")
        for l in body["lines"]:
            if l["billed_amount_minor"] <= 0:
                raise ApiError(ERR_AMOUNT_INVALID, 422,
                               "Line billed_amount_minor must be positive")

        invoice = create_entity(STORE.invoices, {
            "client_id": cid,
            "carrier_id": carrier_id,
            "shipment_id": shipment_id,
            "rated_contract_id": None,
            "invoice_number": body["invoice_number"],
            "invoice_date": body["invoice_date"],
            "currency": body["currency"],
            "billed_total_minor": body["billed_total_minor"],
            "audit_status": "RECEIVED",
            "payment_status": "UNPAID",
            "duplicate_flag": None,
            "rated_total_minor": 0,
            "variance_minor": 0,
            "variance_pct_bp": 0,
            "approved_amount_minor": 0,
            "home_total_minor": 0,
            "scheduled_minor": 0,
            "paid_minor": 0,
            "due_date": None,
        })
        for l in body["lines"]:
            create_entity(STORE.lines, {
                "invoice_id": invoice["id"],
                "gl_account_id": None,
                "charge_code": l["charge_code"],
                "billed_amount_minor": l["billed_amount_minor"],
                "rated_amount_minor": 0,
                "variance_minor": 0,
                "_invalid_accessorial": False,
            })
        return success_object(serialize_invoice(invoice), status=201)

    @app.route("/fap/invoices/<iid>", methods=["GET"])
    def get_invoice(iid):
        uid, role = authenticate()
        require_roles(role, READ_ROLES)
        invoice = guard_read_scope(role, uid, "invoice", STORE.invoices.get(iid))
        return success_object(serialize_invoice(invoice))

    @app.route("/fap/invoices", methods=["GET"])
    def list_invoices():
        uid, role = authenticate()
        require_roles(role, READ_ROLES)
        limit, offset = parse_pagination()
        rows = [i for i in STORE.invoices.values()
                if in_read_scope(role, uid, "invoice", i)]
        for param in ("client_id", "carrier_id", "shipment_id",
                      "rated_contract_id", "audit_status", "payment_status"):
            value = request.args.get(param)
            if value is not None:
                rows = [i for i in rows if str(i.get(param)) == value]
        rows = sort_default(rows)
        total = len(rows)
        page = rows[offset:offset + limit]
        return success_list([serialize_invoice(i) for i in page], limit, offset, total)

    @app.route("/fap/invoices/<iid>/capture", methods=["POST"])
    def capture_invoice(iid):
        uid, role = authenticate()
        require_roles(role, {"AuditAnalyst"})
        invoice = resolve(STORE.invoices, iid)
        require_client_active(STORE.clients.get(invoice["client_id"]))
        body = get_body()
        check_shape(body, {})
        if invoice["audit_status"] != "RECEIVED":
            raise ApiError(ERR_INVALID_STATE, 409,
                           "Invoice cannot be captured from %s"
                           % invoice["audit_status"])
        invoice["duplicate_flag"] = detect_fuzzy_duplicate(invoice)
        invoice["audit_status"] = "CAPTURED"
        touch(invoice)
        shipment = STORE.shipments.get(invoice.get("shipment_id")) \
            if invoice.get("shipment_id") else None
        if shipment is not None and shipment["status"] == "REGISTERED":
            shipment["status"] = "INVOICED"
            touch(shipment)
        return success_object(serialize_invoice(invoice))

    @app.route("/fap/invoices/<iid>/rate", methods=["POST"])
    def rate_invoice_endpoint(iid):
        uid, role = authenticate()
        require_roles(role, {"AuditAnalyst"})
        invoice = resolve(STORE.invoices, iid)
        require_client_active(STORE.clients.get(invoice["client_id"]))
        body = get_body()
        check_shape(body, {
            "policy": {"kind": "string", "required": False, "enum": RATE_POLICIES},
        })
        if invoice["audit_status"] != "CAPTURED":
            raise ApiError(ERR_INVALID_STATE, 409,
                           "Invoice cannot be rated from %s"
                           % invoice["audit_status"])
        policy = body.get("policy", "SHIP_DATE")
        if rate_invoice(invoice, policy=policy):
            invoice["audit_status"] = "RATED"
            touch(invoice)
        else:
            no_contract_transition(invoice)
        return success_object(serialize_invoice(invoice))

    @app.route("/fap/invoices/<iid>/finalize_audit", methods=["POST"])
    def finalize_audit(iid):
        uid, role = authenticate()
        require_roles(role, {"AuditAnalyst"})
        invoice = resolve(STORE.invoices, iid)
        client = STORE.clients.get(invoice["client_id"])
        require_client_active(client)
        body = get_body()
        check_shape(body, {})
        if invoice["audit_status"] != "RATED":
            raise ApiError(ERR_INVALID_STATE, 409,
                           "Invoice cannot be finalized from %s"
                           % invoice["audit_status"])
        finalize_invoice(invoice, client)
        return success_object(serialize_invoice(invoice))

    @app.route("/fap/invoices/<iid>/rerate", methods=["POST"])
    def rerate_invoice(iid):
        uid, role = authenticate()
        require_roles(role, {"AuditAnalyst"})
        invoice = resolve(STORE.invoices, iid)
        require_client_active(STORE.clients.get(invoice["client_id"]))
        body = get_body()
        check_shape(body, {
            "policy": {"kind": "string", "required": False, "enum": RATE_POLICIES},
        })
        if invoice["audit_status"] != "EXCEPTION":
            raise ApiError(ERR_INVALID_STATE, 409,
                           "Invoice cannot be rerated from %s"
                           % invoice["audit_status"])
        active = [e for e in invoice_exceptions(iid)
                  if e["status"] in ("OPEN", "CARRIER_NOTIFIED",
                                     "CARRIER_RESPONDED", "ESCALATED")]
        if active:
            raise ApiError(ERR_EXCEPTION_STILL_ACTIVE, 409,
                           "Rerate attempted while an exception is still active")
        policy = body.get("policy", "SHIP_DATE")
        if rate_invoice(invoice, policy=policy):
            invoice["audit_status"] = "RATED"
            touch(invoice)
        else:
            no_contract_transition(invoice)
        return success_object(serialize_invoice(invoice))

    @app.route("/fap/invoices/<iid>/void", methods=["POST"])
    def void_invoice(iid):
        uid, role = authenticate()
        require_roles(role, {"AuditAnalyst"})
        invoice = resolve(STORE.invoices, iid)
        require_client_active(STORE.clients.get(invoice["client_id"]))
        body = get_body()
        check_shape(body, {})
        if invoice["audit_status"] not in ("RECEIVED", "CAPTURED"):
            raise ApiError(ERR_INVALID_STATE, 409,
                           "Invoice cannot be voided from %s"
                           % invoice["audit_status"])
        invoice["audit_status"] = "VOIDED"
        touch(invoice)
        return success_object(serialize_invoice(invoice))

    @app.route("/fap/invoices/<iid>/write_off", methods=["POST"])
    def write_off_invoice(iid):
        uid, role = authenticate()
        require_roles(role, {"FinanceController"})
        invoice = resolve(STORE.invoices, iid)
        require_client_active(STORE.clients.get(invoice["client_id"]))
        body = get_body()
        check_shape(body, {})
        if invoice["payment_status"] != "UNPAID":
            raise ApiError(ERR_INVALID_STATE, 409,
                           "Invoice payment cannot be written off from %s"
                           % invoice["payment_status"])
        if invoice["audit_status"] != "CLEARED":
            raise ApiError(ERR_INVOICE_NOT_PAYABLE, 409,
                           "Invoice audit status is not CLEARED")
        invoice["payment_status"] = "WRITTEN_OFF"
        touch(invoice)
        return success_object(serialize_invoice(invoice))

    # --- nested collection reads -------------------------------------------

    @app.route("/fap/invoices/<iid>/lines", methods=["GET"])
    def list_invoice_lines(iid):
        uid, role = authenticate()
        require_roles(role, READ_ROLES)
        invoice = guard_read_scope(role, uid, "invoice", STORE.invoices.get(iid))
        limit, offset = parse_pagination()
        rows = invoice_lines(invoice["id"])
        total = len(rows)
        page = rows[offset:offset + limit]
        return success_list([serialize_line(l) for l in page], limit, offset, total)

    @app.route("/fap/invoices/<iid>/exceptions", methods=["GET"])
    def list_invoice_exceptions(iid):
        uid, role = authenticate()
        require_roles(role, READ_ROLES)
        invoice = guard_read_scope(role, uid, "invoice", STORE.invoices.get(iid))
        limit, offset = parse_pagination()
        rows = invoice_exceptions(invoice["id"])
        total = len(rows)
        page = rows[offset:offset + limit]
        return success_list([public(e) for e in page], limit, offset, total)

    @app.route("/fap/invoices/<iid>/payment-run-items", methods=["GET"])
    def list_invoice_run_items(iid):
        uid, role = authenticate()
        require_roles(role, READ_ROLES)
        invoice = guard_read_scope(role, uid, "invoice", STORE.invoices.get(iid))
        limit, offset = parse_pagination()
        rows = [it for it in STORE.run_items.values()
                if it["invoice_id"] == invoice["id"]]
        rows = sort_default(rows)
        total = len(rows)
        page = rows[offset:offset + limit]
        return success_list([public(it) for it in page], limit, offset, total)

    @app.route("/fap/invoices/<iid>/recovery-claims", methods=["GET"])
    def list_invoice_claims(iid):
        uid, role = authenticate()
        require_roles(role, READ_ROLES)
        invoice = guard_read_scope(role, uid, "invoice", STORE.invoices.get(iid))
        limit, offset = parse_pagination()
        rows = [c for c in STORE.claims.values() if c["invoice_id"] == invoice["id"]]
        rows = sort_default(rows)
        total = len(rows)
        page = rows[offset:offset + limit]
        return success_list([public(c) for c in page], limit, offset, total)
