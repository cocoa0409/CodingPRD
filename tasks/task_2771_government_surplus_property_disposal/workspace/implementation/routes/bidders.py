"""Bidder registration, deposits and bid listing (PRD section 3.6)."""
import db as store
from db import db
from errors import ApiError
from middleware import (Fields, bidder_scope, endpoint, list_params,
                        read_body)
from response import collection, created, ok
from services import cascades, rollups
from services.enums import BID_STATUS, BIDDER_STATUS, BIDDER_TYPE
from services.serialize import view, views

# Bidder status machine (PRD 3.6): PENDING -> REGISTERED, REGISTERED <-> SUSPENDED,
# REGISTERED|SUSPENDED -> DEBARRED (terminal).
BIDDER_TRANSITIONS = {
    ("PENDING", "REGISTERED"): True,
    ("REGISTERED", "SUSPENDED"): True,
    ("SUSPENDED", "REGISTERED"): True,
    ("REGISTERED", "DEBARRED"): True,
    ("SUSPENDED", "DEBARRED"): True,
}


def register(app):

    @app.route("/bidders", methods=["POST"])
    @endpoint(["ProgramAdmin", "DisposalOfficer"])
    def create_bidder(ctx):
        body = read_body()
        f = Fields(body)
        f.string("legal_name", required=True, minlen=1, maxlen=160)
        f.string("email", required=True, minlen=1, maxlen=254)
        f.enum("bidder_type", BIDDER_TYPE, required=True)
        f.done()
        # Precedence 13: email uniqueness is compared case-insensitively.
        lowered = f["email"].lower()
        for row in db.bidders.values():
            if row["email"].lower() == lowered:
                raise ApiError("ERR_DUPLICATE_BIDDER_EMAIL",
                               "email is already registered to another bidder")
        bidder = store.base_row()
        bidder.update({
            "legal_name": f["legal_name"],
            "email": f["email"],
            "bidder_type": f["bidder_type"],
            "status": "PENDING",
            "end_use_certificate_expires_on": None,
            "deposit_paid_cents": 0,
            "deposit_held_cents": 0,
            "deposit_applied_cents": 0,
            "deposit_forfeited_cents": 0,
            "winning_lot_count": 0,
        })
        db.bidders[bidder["id"]] = bidder
        return created(view("Bidder", bidder))

    @app.route("/bidders/<bidder_id>", methods=["GET"])
    @endpoint(["ProgramAdmin", "DisposalOfficer", "FinanceController", "Bidder"])
    def get_bidder(ctx, bidder_id):
        bidder_scope(ctx, bidder_id)
        bidder = rollups.fetch(db.bidders, bidder_id, "ERR_BIDDER_NOT_FOUND")
        return ok(view("Bidder", bidder))

    @app.route("/bidders", methods=["GET"])
    @endpoint(["ProgramAdmin", "DisposalOfficer", "FinanceController"])
    def list_bidders(ctx):
        filters, limit, offset = list_params({"status": BIDDER_STATUS,
                                              "bidder_type": BIDDER_TYPE})
        rows = store.by_created(db.bidders.values())
        for key, value in filters.items():
            rows = [r for r in rows if r[key] == value]
        return collection(views("Bidder", rows), limit, offset)

    @app.route("/bidders/<bidder_id>/status", methods=["POST"])
    @endpoint(["ProgramAdmin", "DisposalOfficer"])
    def set_bidder_status(ctx, bidder_id):
        body = read_body()
        f = Fields(body)
        f.enum("status", BIDDER_STATUS, required=True)
        f.done()
        bidder = rollups.fetch(db.bidders, bidder_id, "ERR_BIDDER_NOT_FOUND")
        target = f["status"]
        if not BIDDER_TRANSITIONS.get((bidder["status"], target)):
            raise ApiError("ERR_INVALID_STATE",
                           "a bidder in " + bidder["status"] +
                           " may not move to " + target)
        if target == "DEBARRED":
            cascades.debar_bidder(bidder, ctx)
        else:
            bidder["status"] = target
            ctx.touch(bidder)
        return ok(view("Bidder", bidder))

    @app.route("/bidders/<bidder_id>/end-use-certificate", methods=["POST"])
    @endpoint(["ProgramAdmin", "DisposalOfficer"])
    def set_end_use_certificate(ctx, bidder_id):
        body = read_body()
        f = Fields(body)
        f.date("end_use_certificate_expires_on", required=True)
        f.done()
        bidder = rollups.fetch(db.bidders, bidder_id, "ERR_BIDDER_NOT_FOUND")
        bidder["end_use_certificate_expires_on"] = store.iso_date(
            f["end_use_certificate_expires_on"])
        ctx.touch(bidder)
        return ok(view("Bidder", bidder))

    @app.route("/bidders/<bidder_id>/deposits", methods=["POST"])
    @endpoint(["Bidder", "FinanceController"])
    def record_deposit(ctx, bidder_id):
        bidder_scope(ctx, bidder_id)
        body = read_body()
        f = Fields(body)
        f.integer("amount_cents", required=True, minv=1)
        f.done()
        bidder = rollups.fetch(db.bidders, bidder_id, "ERR_BIDDER_NOT_FOUND")
        if bidder["status"] != "REGISTERED":
            raise ApiError("ERR_BIDDER_NOT_REGISTERED",
                           "deposits may only be recorded for a REGISTERED bidder")
        amount = f["amount_cents"]
        bidder["deposit_paid_cents"] += amount
        bidder["deposit_held_cents"] += amount
        ctx.touch(bidder)
        return ok(view("Bidder", bidder))

    @app.route("/bidders/<bidder_id>/bids", methods=["GET"])
    @endpoint(["ProgramAdmin", "DisposalOfficer", "FinanceController", "Bidder"])
    def list_bidder_bids(ctx, bidder_id):
        bidder_scope(ctx, bidder_id)
        filters, limit, offset = list_params({"status": BID_STATUS})
        bidder = rollups.fetch(db.bidders, bidder_id, "ERR_BIDDER_NOT_FOUND")
        rows = rollups.bids_of_bidder(bidder["id"])
        for key, value in filters.items():
            rows = [r for r in rows if r[key] == value]
        return collection(views("Bid", rows), limit, offset)
