"""Transfer order endpoints (PRD section 3.5)."""
import db as store
from db import db, by_created, iso, parse_date, parse_instant
from errors import ApiError
from middleware import (Fields, agency_scope, endpoint, list_params,
                        plain_filters, read_body)
from response import collection, created, ok
from services import calc, rollups
from services.enums import TRANSFER_STATUS
from services.serialize import view, views


def register(app):

    @app.route("/transfer-orders", methods=["POST"])
    @endpoint(["DisposalOfficer"])
    def create_transfer_order(ctx):
        body = read_body()
        f = Fields(body)
        f.string("asset_id", required=True, minlen=1)
        f.string("recipient_agency_id", required=True, minlen=1)
        f.string("screening_request_id", required=True, minlen=1)
        f.done()
        asset = rollups.fetch(db.assets, f["asset_id"], "ERR_ASSET_NOT_FOUND")
        recipient = rollups.fetch(db.agencies, f["recipient_agency_id"],
                                  "ERR_AGENCY_NOT_FOUND")
        request_row = rollups.fetch(db.requests, f["screening_request_id"],
                                    "ERR_SCREENING_REQUEST_NOT_FOUND")
        if recipient["status"] != "ACTIVE":
            raise ApiError("ERR_AGENCY_SUSPENDED",
                           "a suspended recipient may not receive a transfer order")
        if recipient["agency_type"] == "ELIGIBLE_NONPROFIT" or asset["federal_source"]:
            expires = recipient["donee_certification_expires_on"]
            if (recipient["federal_donee_status"] != "CERTIFIED"
                    or expires is None
                    or parse_date(expires) < store.today()):
                raise ApiError("ERR_DONEE_CERTIFICATION_INVALID",
                               "the recipient lacks a current federal donee "
                               "certification")
        cycle = db.cycles.get(request_row["screening_cycle_id"])
        if (request_row["status"] != "APPROVED"
                or cycle is None
                or cycle["asset_id"] != asset["id"]
                or request_row["requesting_agency_id"] != recipient["id"]):
            raise ApiError("ERR_REQUEST_CYCLE_MISMATCH",
                           "the named request does not document this asset and "
                           "recipient")
        fmv = asset["fair_market_value_cents"] or 0
        base, fee, price = calc.transfer_price(fmv, recipient["agency_type"],
                                              asset["federal_source"])
        order = store.base_row()
        order.update({
            "asset_id": asset["id"],
            "recipient_agency_id": recipient["id"],
            "screening_request_id": request_row["id"],
            "base_transfer_cents": base,
            "handling_fee_cents": fee,
            "transfer_price_cents": price,
            "status": "ISSUED",
            "issued_by_user_id": ctx.user_id,
            "acknowledged_at": None,
            "use_period_end_on": None,
            "void_reason": None,
        })
        db.transfer_orders[order["id"]] = order
        return created(view("TransferOrder", order))

    @app.route("/transfer-orders/<order_id>", methods=["GET"])
    @endpoint(["ProgramAdmin", "DisposalOfficer", "FinanceController", "AgencyOfficer"])
    def get_transfer_order(ctx, order_id):
        order = rollups.fetch(db.transfer_orders, order_id, "ERR_TRANSFER_ORDER_NOT_FOUND")
        agency_scope(ctx, order["recipient_agency_id"])
        return ok(view("TransferOrder", order))

    @app.route("/transfer-orders", methods=["GET"])
    @endpoint(["ProgramAdmin", "DisposalOfficer", "FinanceController", "AgencyOfficer"])
    def list_transfer_orders(ctx):
        filters, limit, offset = list_params({"status": TRANSFER_STATUS})
        plain = plain_filters(["asset_id", "recipient_agency_id", "screening_request_id"])
        rows = by_created(db.transfer_orders.values())
        for key, value in filters.items():
            rows = [r for r in rows if r[key] == value]
        for key, value in plain.items():
            rows = [r for r in rows if r[key] == value]
        return collection(views("TransferOrder", rows), limit, offset)

    @app.route("/transfer-orders/<order_id>/acknowledge", methods=["POST"])
    @endpoint(["AgencyOfficer"])
    def acknowledge_transfer_order(ctx, order_id):
        read_body()
        order = rollups.fetch(db.transfer_orders, order_id, "ERR_TRANSFER_ORDER_NOT_FOUND")
        agency_scope(ctx, order["recipient_agency_id"])
        if order["status"] != "ISSUED":
            raise ApiError("ERR_INVALID_STATE",
                           "only an ISSUED transfer order may be acknowledged")
        recipient = db.agencies.get(order["recipient_agency_id"])
        if recipient is None or recipient["status"] != "ACTIVE":
            raise ApiError("ERR_AGENCY_SUSPENDED",
                           "the recipient organisation is not ACTIVE")
        order["status"] = "ACKNOWLEDGED"
        order["acknowledged_at"] = iso(store.db.now)
        ctx.touch(order)
        return ok(view("TransferOrder", order))

    @app.route("/transfer-orders/<order_id>/void", methods=["POST"])
    @endpoint(["DisposalOfficer"])
    def void_transfer_order(ctx, order_id):
        body = read_body()
        f = Fields(body)
        f.string("void_reason", required=True, minlen=1)
        f.done()
        order = rollups.fetch(db.transfer_orders, order_id, "ERR_TRANSFER_ORDER_NOT_FOUND")
        if order["status"] not in ("ISSUED", "ACKNOWLEDGED"):
            raise ApiError("ERR_INVALID_STATE",
                           "only an ISSUED or ACKNOWLEDGED order may be voided")
        order["status"] = "VOIDED"
        order["void_reason"] = f["void_reason"]
        ctx.touch(order)
        request_row = db.requests.get(order["screening_request_id"])
        if request_row is not None and request_row["status"] == "APPROVED":
            request_row["status"] = "DENIED"
            request_row["denial_reason"] = "TRANSFER_VOIDED"
            ctx.touch(request_row)
            cycle = db.cycles.get(request_row["screening_cycle_id"])
            if cycle is not None and cycle["status"] == "AWARDED":
                cycle["status"] = "OPEN"
                cycle["tier_opened_at"] = iso(store.db.now)
                cycle["tier_deadline_at"] = iso(
                    store.add_days(store.db.now, cycle["tier_window_days"]))
                cycle["awarded_by_user_id"] = None
                cycle["awarded_at"] = None
                rollups.recompute_cycle_open_requests(cycle, ctx)
                ctx.touch(cycle)
                asset = db.assets.get(cycle["asset_id"])
                if asset is not None and asset["disposition_status"] == "AWARDED_TRANSFER":
                    asset["disposition_status"] = "SCREENING"
                    ctx.touch(asset)
        return ok(view("TransferOrder", order))
