"""Co-product sales: quoting, the collar, the rebate ladder and shipment."""
import calc
import derive
import guards
import serialize
from envelope import ok, ok_list
from errors import fail
from routes import bp
from shape import enum_param, no_body, page, pagination, require_auth, take
from store import db, new_row, touch
from util import D, rhu

SALE_SPEC = {
    "sale_code": {"type": "string", "required": True},
    "buyer_name": {"type": "string", "required": True},
    "product": {"type": "enum", "required": True,
                "values": ["DDGS_DRY", "DDGS_WET", "CORN_OIL"]},
    "pricing_basis": {"type": "enum", "required": True, "values": ["FLAT", "INDEX"]},
    "quantity": {"type": "dec", "required": True, "gt": 0, "places": 3},
    "quote_expires_at": {"type": "instant", "required": True},
    "quoted_price": {"type": "dec", "gt": 0, "places": 2},
    "index_pct": {"type": "dec", "ge": "0.10", "le": "2.00", "places": 4},
    "freight_rate_per_unit": {"type": "dec", "ge": 0, "places": 4,
                              "default": D("0.0000")},
}
RESPOND_SPEC = {
    "decision": {"type": "enum", "required": True, "values": ["ACCEPT", "DECLINE"]},
}
PRODUCTS = ("DDGS_DRY", "DDGS_WET", "CORN_OIL")
SALE_STATUSES = ("QUOTED", "ACCEPTED", "DECLINED", "SHIPPED")
BASES = ("FLAT", "INDEX")


@bp.route("/co-product-sales", methods=["POST"])
def create_sale():
    require_auth(["GrainBuyer"])
    body = take(SALE_SPEC)
    basis = body["pricing_basis"]
    if basis == "INDEX":
        if body["index_pct"] is None:
            fail("ERR_VALIDATION", "index_pct is required for an INDEX sale")
    else:
        if body["index_pct"] is not None:
            fail("ERR_VALIDATION", "index_pct must be null for a FLAT sale")
        if body["quoted_price"] is None:
            fail("ERR_VALIDATION", "quoted_price is required for a FLAT sale")
    guards.unique(db.sales, "sale_code", body["sale_code"])
    quoted_price = None
    reference_mark = None
    if basis == "FLAT":
        quoted_price = rhu(body["quoted_price"], 2)
    else:
        mark = calc.reference_mark(db.plant, body["product"])
        if mark is None:
            fail("ERR_MARKS_NOT_POSTED",
                 "The reference mark for %s has not been posted" % body["product"])
        reference_mark = D(mark)
        quoted_price = calc.index_quote_price(reference_mark, body["index_pct"])
    sale = new_row({
        "sale_code": body["sale_code"],
        "buyer_name": body["buyer_name"],
        "product": body["product"],
        "pricing_basis": basis,
        "quantity": rhu(body["quantity"], 3),
        "quoted_price": quoted_price,
        "index_pct": rhu(body["index_pct"], 4) if body["index_pct"] is not None else None,
        "freight_rate_per_unit": rhu(body["freight_rate_per_unit"], 4),
        "quote_expires_at": body["quote_expires_at"],
        "status": "QUOTED",
        "quote_reference_mark": reference_mark,
        "settlement_price": None,
        "collar_floor": None,
        "collar_ceiling": None,
        "subtotal_usd": None,
        "volume_rebate_usd": None,
        "freight_usd": None,
        "invoice_amount_cents": None,
        "responded_at": None,
        "shipped_at": None,
    })
    db.sales[sale["id"]] = sale
    return ok(serialize.sale_out(sale), 201)


@bp.route("/co-product-sales/<sale_id>", methods=["GET"])
def get_sale(sale_id):
    require_auth(["PlantManager", "GrainBuyer", "LogisticsCoordinator", "RiskManager"])
    sale = guards.get_sale(sale_id)
    return ok(serialize.sale_out(sale))


@bp.route("/co-product-sales", methods=["GET"])
def list_sales():
    require_auth(["PlantManager", "GrainBuyer", "LogisticsCoordinator", "RiskManager"])
    product = enum_param("product", PRODUCTS)
    status = enum_param("status", SALE_STATUSES)
    basis = enum_param("pricing_basis", BASES)
    limit, offset = pagination()
    rows = list(db.sales.values())
    if product is not None:
        rows = [r for r in rows if r["product"] == product]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if basis is not None:
        rows = [r for r in rows if r["pricing_basis"] == basis]
    rows = sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
    window = page(rows, limit, offset)
    return ok_list([serialize.sale_out(r) for r in window], limit, offset, len(rows))


@bp.route("/co-product-sales/<sale_id>/respond", methods=["POST"])
def respond_sale(sale_id):
    require_auth(["GrainBuyer"])
    body = take(RESPOND_SPEC)
    sale = guards.get_sale(sale_id)
    if sale["status"] != "QUOTED":
        fail("ERR_INVALID_SALE_STATE",
             "Sale is %s and may not be responded to" % sale["status"])
    decision = body["decision"]
    current_mark = None
    if decision == "ACCEPT" and sale["pricing_basis"] == "INDEX":
        current_mark = calc.reference_mark(db.plant, sale["product"])
        if current_mark is None or sale["quote_reference_mark"] is None:
            fail("ERR_MARKS_NOT_POSTED",
                 "The reference mark for %s is not readable" % sale["product"])
    if db.clock > sale["quote_expires_at"]:
        fail("ERR_QUOTE_EXPIRED",
             "Quote %s expired at %s" % (sale["sale_code"],
                                         sale["quote_expires_at"].isoformat()))
    sale["responded_at"] = db.clock
    if decision == "DECLINE":
        sale["status"] = "DECLINED"
        touch(sale)
        return ok(serialize.sale_out(sale))
    settled, floor, ceiling = calc.settlement_price(sale, current_mark)
    sale["settlement_price"] = settled
    sale["collar_floor"] = floor
    sale["collar_ceiling"] = ceiling
    invoice = calc.coproduct_invoice(sale["product"], sale["quantity"], settled,
                                     sale["freight_rate_per_unit"])
    sale["subtotal_usd"] = invoice["subtotal_usd"]
    sale["volume_rebate_usd"] = invoice["volume_rebate_usd"]
    sale["freight_usd"] = invoice["freight_usd"]
    sale["invoice_amount_cents"] = invoice["invoice_amount_cents"]
    sale["status"] = "ACCEPTED"
    touch(sale)
    return ok(serialize.sale_out(sale))


@bp.route("/co-product-sales/<sale_id>/ship", methods=["POST"])
def ship_sale(sale_id):
    require_auth(["LogisticsCoordinator"])
    no_body()
    sale = guards.get_sale(sale_id)
    if sale["status"] != "ACCEPTED":
        fail("ERR_INVALID_SALE_STATE",
             "Sale is %s and may not be shipped" % sale["status"])
    quantity = D(sale["quantity"])
    if sale["product"] == "CORN_OIL":
        on_hand = derive.plant_corn_oil_inventory()
        unit = "lbs of corn oil"
    else:
        on_hand = derive.plant_ddgs_inventory()
        unit = "tons of distillers grains"
    if on_hand < quantity:
        fail("ERR_INSUFFICIENT_COPRODUCT_INVENTORY",
             "The plant holds %s %s, less than the sale quantity"
             % (format(on_hand, "f"), unit))
    sale["status"] = "SHIPPED"
    sale["shipped_at"] = db.clock
    touch(sale)
    return ok(serialize.sale_out(sale))
