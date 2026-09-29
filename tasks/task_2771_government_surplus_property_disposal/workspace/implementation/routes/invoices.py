"""Sale invoice settlement, default and void (PRD section 3.7)."""
import db as store
from db import db, by_created, parse_instant
from errors import ApiError
from middleware import (Fields, bidder_scope, endpoint, list_params,
                        plain_filters, read_body)
from response import collection, ok
from services import rollups
from services.enums import INVOICE_STATUS
from services.serialize import view, views

UNSETTLED = ("ISSUED", "PARTIALLY_PAID")


def register(app):

    @app.route("/sale-invoices/<invoice_id>", methods=["GET"])
    @endpoint(["ProgramAdmin", "DisposalOfficer", "FinanceController", "Bidder"])
    def get_invoice(ctx, invoice_id):
        invoice = rollups.fetch(db.invoices, invoice_id, "ERR_SALE_INVOICE_NOT_FOUND")
        bidder_scope(ctx, invoice["bidder_id"])
        return ok(view("SaleInvoice", invoice))

    @app.route("/sale-invoices", methods=["GET"])
    @endpoint(["ProgramAdmin", "DisposalOfficer", "FinanceController", "Bidder"])
    def list_invoices(ctx):
        filters, limit, offset = list_params({"status": INVOICE_STATUS})
        plain = plain_filters(["auction_lot_id", "bidder_id"])
        rows = by_created(db.invoices.values())
        for key, value in filters.items():
            rows = [r for r in rows if r[key] == value]
        for key, value in plain.items():
            rows = [r for r in rows if r[key] == value]
        return collection(views("SaleInvoice", rows), limit, offset)

    @app.route("/sale-invoices/<invoice_id>/payments", methods=["POST"])
    @endpoint(["Bidder", "FinanceController"])
    def pay_invoice(ctx, invoice_id):
        body = read_body()
        f = Fields(body)
        f.integer("amount_cents", required=True)
        f.boolean("use_deposit", default=False)
        f.done()
        invoice = rollups.fetch(db.invoices, invoice_id, "ERR_SALE_INVOICE_NOT_FOUND")
        bidder_scope(ctx, invoice["bidder_id"])
        if invoice["status"] not in UNSETTLED:
            raise ApiError("ERR_INVALID_STATE",
                           "only an ISSUED or PARTIALLY_PAID invoice may take a "
                           "payment")
        bidder = db.bidders.get(invoice["bidder_id"])
        amount = f["amount_cents"]
        balance = invoice["balance_due_cents"]
        deposit_move = 0
        if f["use_deposit"] and bidder is not None:
            held = bidder["deposit_held_cents"]
            deposit_move = held if held < balance else balance
        if amount <= 0 or amount > balance or (amount + deposit_move) > balance:
            raise ApiError("ERR_PAYMENT_EXCEEDS_BALANCE",
                           "the payment would exceed the invoice's outstanding "
                           "balance")
        # The deposit moves first, and the moved amount counts as payment.
        if deposit_move:
            bidder["deposit_held_cents"] -= deposit_move
            bidder["deposit_applied_cents"] += deposit_move
            invoice["deposit_applied_cents"] += deposit_move
            invoice["amount_paid_cents"] += deposit_move
        invoice["amount_paid_cents"] += amount
        rollups.refresh_invoice_balance(invoice)
        if invoice["amount_paid_cents"] >= invoice["total_due_cents"]:
            invoice["status"] = "PAID"
            lot = db.lots.get(invoice["auction_lot_id"])
            if lot is not None and lot["status"] == "CLOSED_MET":
                lot["status"] = "SETTLED"
                ctx.touch(lot)
        else:
            invoice["status"] = "PARTIALLY_PAID"
        ctx.touch(invoice)
        if bidder is not None:
            ctx.touch(bidder)
        return ok(view("SaleInvoice", invoice))

    @app.route("/sale-invoices/<invoice_id>/default", methods=["POST"])
    @endpoint(["FinanceController", "DisposalOfficer"])
    def default_invoice(ctx, invoice_id):
        body = read_body()
        f = Fields(body)
        f.string("default_reason", required=True, minlen=1)
        f.done()
        invoice = rollups.fetch(db.invoices, invoice_id, "ERR_SALE_INVOICE_NOT_FOUND")
        if invoice["status"] not in UNSETTLED:
            raise ApiError("ERR_INVALID_STATE",
                           "only an ISSUED or PARTIALLY_PAID invoice may default")
        # Strictly after due_at: a default on the due instant itself is premature.
        if store.db.now <= parse_instant(invoice["due_at"]):
            raise ApiError("ERR_INVALID_STATE",
                           "the payment term has not yet lapsed")
        invoice["status"] = "DEFAULTED"
        invoice["default_reason"] = f["default_reason"]
        bidder = db.bidders.get(invoice["bidder_id"])
        moved = invoice["deposit_applied_cents"]
        if bidder is not None:
            if moved:
                bidder["deposit_applied_cents"] -= moved
                bidder["deposit_forfeited_cents"] += moved
            ctx.touch(bidder)
        ctx.touch(invoice)
        return ok(view("SaleInvoice", invoice))

    @app.route("/sale-invoices/<invoice_id>/void", methods=["POST"])
    @endpoint(["FinanceController", "DisposalOfficer"])
    def void_invoice(ctx, invoice_id):
        body = read_body()
        f = Fields(body)
        f.string("void_reason", required=True, minlen=1)
        f.done()
        invoice = rollups.fetch(db.invoices, invoice_id, "ERR_SALE_INVOICE_NOT_FOUND")
        if invoice["status"] not in UNSETTLED:
            raise ApiError("ERR_INVALID_STATE",
                           "only an ISSUED or PARTIALLY_PAID invoice may be voided")
        for dist in rollups.distributions_of_lot(invoice["auction_lot_id"]):
            if dist["status"] == "POSTED":
                raise ApiError("ERR_INVALID_STATE",
                               "a posted proceeds distribution already exists for "
                               "this lot")
        invoice["status"] = "VOIDED"
        invoice["void_reason"] = f["void_reason"]
        bidder = db.bidders.get(invoice["bidder_id"])
        moved = invoice["deposit_applied_cents"]
        if bidder is not None:
            if moved:
                bidder["deposit_applied_cents"] -= moved
                bidder["deposit_held_cents"] += moved
            ctx.touch(bidder)
        invoice["deposit_applied_cents"] = 0
        invoice["amount_paid_cents"] = 0
        rollups.refresh_invoice_balance(invoice)
        ctx.touch(invoice)
        return ok(view("SaleInvoice", invoice))
