"""Asset release endpoint (PRD section 3.8)."""
import db as store
from db import db, iso_date
from errors import ApiError
from middleware import Fields, endpoint, read_body
from response import ok
from services import calc, rollups
from services.serialize import view


def _settled_lot_invoice(asset_id):
    for lot in reversed(rollups.lots_of_asset(asset_id)):
        if lot["status"] in ("CLOSED_MET", "SETTLED"):
            return lot, rollups.live_invoice_of_lot(lot["id"])
    return None, None


def _acknowledged_order(asset_id):
    orders = [o for o in db.transfer_orders.values() if o["asset_id"] == asset_id]
    for order in reversed(store.by_created(orders)):
        if order["status"] == "ACKNOWLEDGED":
            return order
    return None


def register(app):

    @app.route("/assets/<asset_id>/release", methods=["POST"])
    @endpoint(["DisposalOfficer"])
    def release_asset(ctx, asset_id):
        body = read_body()
        f = Fields(body)
        f.integer("odometer_disclosure_reading", minv=0)
        f.string("lien_release_reference")
        f.string("title_recipient_name")
        f.done()
        asset = rollups.fetch(db.assets, asset_id, "ERR_ASSET_NOT_FOUND")
        disposition = asset["disposition_status"]
        order = None
        if disposition == "SOLD":
            lot, invoice = _settled_lot_invoice(asset["id"])
            if invoice is None or invoice["status"] != "PAID":
                raise ApiError("ERR_INVALID_STATE",
                               "the lot's sale invoice is not PAID")
        elif disposition == "AWARDED_TRANSFER":
            order = _acknowledged_order(asset["id"])
            if order is None:
                raise ApiError("ERR_INVALID_STATE",
                               "the asset's transfer order has not been acknowledged")
        else:
            raise ApiError("ERR_INVALID_STATE",
                           "only a SOLD or AWARDED_TRANSFER asset may be released")
        if asset["is_data_bearing"] and asset["clearance_status"] != "CLEARED":
            raise ApiError("ERR_SANITIZATION_NOT_CERTIFIED",
                           "a data-bearing asset requires a verified "
                           "DATA_SANITIZATION certificate before release")
        if asset["is_restricted"] and asset["clearance_status"] != "CLEARED":
            raise ApiError("ERR_DEMIL_NOT_CERTIFIED",
                           "a restricted asset requires a verified "
                           "DEMILITARIZATION certificate before release")
        if asset["clearance_status"] not in ("NOT_REQUIRED", "CLEARED"):
            raise ApiError("ERR_INVALID_STATE",
                           "the asset's clearance gate is not open")
        if asset["category"] == "VEHICLE":
            reading = f["odometer_disclosure_reading"]
            recipient = f["title_recipient_name"]
            recorded = asset["odometer_reading"]
            if (reading is None
                    or (recorded is not None and reading < recorded)
                    or recipient is None or recipient.strip() == ""):
                raise ApiError("ERR_ODOMETER_DISCLOSURE_REQUIRED",
                               "releasing a VEHICLE requires an odometer disclosure "
                               "at or above the recorded reading and a title "
                               "recipient name")
        if asset["lien_holder_name"] is not None:
            reference = f["lien_release_reference"]
            if reference is None or reference.strip() == "":
                raise ApiError("ERR_LIEN_NOT_RELEASED",
                               "a lien-encumbered asset requires a "
                               "lien_release_reference")
        asset["disposition_status"] = "RELEASED"
        asset["released_at"] = store.iso(store.db.now)
        if f["odometer_disclosure_reading"] is not None:
            asset["odometer_disclosure_reading"] = f["odometer_disclosure_reading"]
        if f["lien_release_reference"] is not None:
            asset["lien_release_reference"] = f["lien_release_reference"]
        if f["title_recipient_name"] is not None:
            asset["title_recipient_name"] = f["title_recipient_name"]
        ctx.touch(asset)
        if order is not None:
            order["status"] = "COMPLETED"
            if asset["federal_source"] and order["acknowledged_at"] is not None:
                acknowledged = store.parse_instant(order["acknowledged_at"]).date()
                order["use_period_end_on"] = iso_date(
                    calc.use_period_end(acknowledged, asset["category"]))
            ctx.touch(order)
        rollups.bubble_up_turn_in(db.turn_ins.get(asset["turn_in_id"]), ctx)
        return ok(view("SurplusAsset", asset))
