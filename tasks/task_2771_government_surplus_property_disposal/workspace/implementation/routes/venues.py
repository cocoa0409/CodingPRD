"""Sale venue endpoints (PRD section 3.1)."""
import db as store
from db import db, by_created
from errors import ApiError
from middleware import Fields, endpoint, list_params, read_body
from response import collection, created, ok
from services import rollups
from services.enums import VENUE_STATUS
from services.serialize import view, views
from decimal import Decimal


def register(app):

    @app.route("/venues", methods=["POST"])
    @endpoint(["ProgramAdmin"])
    def create_venue(ctx):
        body = read_body()
        f = Fields(body)
        f.string("name", required=True, minlen=1, maxlen=120)
        f.string("venue_code", required=True, minlen=1, maxlen=24)
        f.integer("concurrent_lot_capacity", required=True, minv=1)
        f.rate("buyer_premium_pct", required=True, minv=Decimal("0"), maxv=Decimal("0.30"))
        f.rate("sales_tax_pct", required=True, minv=Decimal("0"), maxv=Decimal("0.15"))
        f.done()
        for row in db.venues.values():
            if row["venue_code"] == f["venue_code"]:
                raise ApiError("ERR_DUPLICATE_VENUE_CODE",
                               "venue_code is already registered")
        venue = store.base_row()
        venue.update({
            "name": f["name"],
            "venue_code": f["venue_code"],
            "concurrent_lot_capacity": f["concurrent_lot_capacity"],
            "buyer_premium_pct": f["buyer_premium_pct"],
            "sales_tax_pct": f["sales_tax_pct"],
            "status": "ACTIVE",
            "active_lot_count": 0,
        })
        db.venues[venue["id"]] = venue
        return created(view("SaleVenue", venue))

    @app.route("/venues/<venue_id>", methods=["GET"])
    @endpoint(["ProgramAdmin", "DisposalOfficer", "FinanceController", "Bidder"])
    def get_venue(ctx, venue_id):
        venue = rollups.fetch(db.venues, venue_id, "ERR_VENUE_NOT_FOUND")
        return ok(view("SaleVenue", venue))

    @app.route("/venues", methods=["GET"])
    @endpoint(["ProgramAdmin", "DisposalOfficer", "FinanceController", "Bidder"])
    def list_venues(ctx):
        filters, limit, offset = list_params({"status": VENUE_STATUS})
        rows = by_created(db.venues.values())
        for key, value in filters.items():
            rows = [r for r in rows if r[key] == value]
        return collection(views("SaleVenue", rows), limit, offset)

    @app.route("/venues/<venue_id>/status", methods=["POST"])
    @endpoint(["ProgramAdmin"])
    def set_venue_status(ctx, venue_id):
        body = read_body()
        f = Fields(body)
        f.enum("status", VENUE_STATUS, required=True)
        f.done()
        venue = rollups.fetch(db.venues, venue_id, "ERR_VENUE_NOT_FOUND")
        target = f["status"]
        if venue["status"] == target or target != "CLOSED":
            raise ApiError("ERR_INVALID_STATE",
                           "the venue cannot move to " + target +
                           " from " + venue["status"])
        venue["status"] = target
        ctx.touch(venue)
        return ok(view("SaleVenue", venue))
