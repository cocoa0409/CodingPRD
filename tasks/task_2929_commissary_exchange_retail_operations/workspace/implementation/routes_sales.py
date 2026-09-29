"""Opening a visit, ringing lines, tender, void and the sale/sale-line reads
(PRD 3.5, 3.6)."""

from flask import Blueprint

import calculations as calc
import constants as C
import derive
import lookups
import service_fund
import service_patron
import service_sale
import serialize
import validation as V
from db import clock_now, db, new_record, sorted_records, touch
from envelope import array_response, object_response
from errors import ApiError

bp = Blueprint("sales", __name__)


@bp.post("/sales")
def open_sale():
    V.authenticate(("StoreCashier",))
    body = V.raw_body()
    store_id = V.want_string(body, "store_id", required=True)
    patron_id = V.want_string(body, "patron_id", required=True)
    acting_delegation_id = V.want_string(body, "acting_delegation_id", required=False,
                                         default=None)

    store = lookups.store(store_id)
    patron = lookups.patron(patron_id)
    delegation = None
    if acting_delegation_id is not None:
        delegation = lookups.delegation(acting_delegation_id)

    business_date = clock_now()

    # The eligibility gate, in the exact order of PRD 3.5.
    if delegation is not None and delegation["status"] != "ACTIVE":
        raise ApiError("ERR_DELEGATION_NOT_ACTIVE")
    service_sale.require_card_valid(patron)
    service_sale.require_sponsor_card_valid(patron)
    service_sale.require_channel_and_region(patron, store)
    if delegation is not None and not service_sale.delegation_covers(delegation, business_date):
        raise ApiError("ERR_DELEGATION_WINDOW_NOT_COVERING")

    sale = new_record()
    sale.update({
        "store_id": store_id,
        "patron_id": patron_id,
        "acting_delegation_id": acting_delegation_id,
        "business_date": business_date,
        "tender_state": "OPEN",
        "compliance_state": "CLEARED",
        "line_count": 0,
        "merchandise_cents": 0,
        "markup_total_cents": 0,
        "surcharge_total_cents": 0,
        "tax_cents": 0,
        "total_due_cents": 0,
        "provisional_allowance_cents": 0,
        "settled_allowance_cents": None,
        "allowance_variance_cents": None,
        "subsidized_shipping_cents": 0,
        "voided_reason": None,
    })
    db.sales[sale["id"]] = sale
    return object_response(serialize.sale_out(sale), 201)


@bp.post("/sales/<sale_id>/lines")
def add_line(sale_id):
    V.authenticate(("StoreCashier",))
    sale = lookups.sale(sale_id)
    body = V.raw_body()
    product_id = V.want_string(body, "product_id", required=True)
    quantity = V.want_int(body, "quantity", required=True, minimum=1)
    product = lookups.product(product_id)

    store = db.stores[sale["store_id"]]
    patron = db.patrons[sale["patron_id"]]

    # Four gates, in this order (PRD 3.5).
    if sale["tender_state"] != "OPEN":
        raise ApiError("ERR_SALE_NOT_OPEN")
    service_sale.require_card_valid(patron)

    existing_lines = derive.lines_of_sale(sale["id"])
    limit = product["quantity_limit_per_visit"]
    if limit is not None:
        already = sum(l["quantity"] for l in existing_lines if l["product_id"] == product_id)
        if already + quantity > limit:
            raise ApiError("ERR_QUANTITY_LIMIT_EXCEEDED")

    if patron["resale_watch_status"] == "RESTRICTED" and product["resale_restricted"]:
        raise ApiError("ERR_RESTRICTED_ITEM_BLOCKED_BY_WATCH")

    governing = service_sale.governing_for(sale["store_id"], product_id, sale["business_date"])
    if governing is None:
        raise ApiError("ERR_ITEM_NOT_IN_ASSORTMENT")

    priced = calc.line_retail_price(store, product, quantity, governing)
    line = new_record(with_version=False)
    line.update({
        "sale_id": sale["id"],
        "product_id": product_id,
        "quantity": quantity,
        "line_surcharge_cents": 0,
        "line_allowance_cents": 0,
    })
    line.update(priced)
    db.sale_lines[line["id"]] = line

    lines = service_sale.rollup(sale)
    service_sale.refresh_provisional_allowance(sale, lines)
    service_patron.recompute_risk(patron)
    touch(sale)
    return object_response(serialize.sale_line_out(line), 201)


@bp.post("/sales/<sale_id>/tender")
def tender_sale(sale_id):
    V.authenticate(("StoreCashier",))
    sale = lookups.sale(sale_id)
    body = V.raw_body()
    collected_tax_cents = V.want_int(body, "collected_tax_cents", required=False, default=None)

    store = db.stores[sale["store_id"]]
    patron = db.patrons[sale["patron_id"]]
    delegation = None
    if sale["acting_delegation_id"] is not None:
        delegation = db.delegations.get(sale["acting_delegation_id"])

    # Eight gates in a fixed order (PRD 3.6).
    if sale["tender_state"] != "OPEN":
        raise ApiError("ERR_SALE_NOT_OPEN")
    if delegation is not None and delegation["status"] != "ACTIVE":
        raise ApiError("ERR_DELEGATION_NOT_ACTIVE")
    if sale["line_count"] < 1:
        raise ApiError("ERR_SALE_HAS_NO_LINES")
    if sale["compliance_state"] != "CLEARED":
        raise ApiError("ERR_SALE_COMPLIANCE_FLAGGED")
    service_sale.require_card_valid(patron)
    if delegation is not None and not service_sale.delegation_covers(
        delegation, sale["business_date"]
    ):
        raise ApiError("ERR_DELEGATION_WINDOW_NOT_COVERING")
    if delegation is not None and sale["total_due_cents"] > delegation["per_sale_spend_cap_cents"]:
        raise ApiError("ERR_DELEGATION_SPEND_CAP_EXCEEDED")
    if collected_tax_cents is not None and collected_tax_cents != 0:
        raise ApiError("ERR_TAX_COLLECTION_FORBIDDEN")

    # Step 1: settle the vendor promotional allowance at the tender instant.
    lines = derive.lines_of_sale(sale["id"])
    settled = service_sale.settled_allowance(sale, lines, clock_now())
    sale["settled_allowance_cents"] = settled
    sale["allowance_variance_cents"] = settled - sale["provisional_allowance_cents"]

    # Steps 2 and 3: the ledger entries, in this order.
    derive.append_ledger_entry(
        store, "SURCHARGE", "SURCHARGE_COLLECTION", sale["surcharge_total_cents"],
        "SALE", sale["id"],
    )
    if settled > 0:
        derive.append_ledger_entry(
            store, "DIVIDEND", "ALLOWANCE_CREDIT", settled, "SALE", sale["id"]
        )

    # Cascade hops 1, 2 and 4 are the derived fund figures, correct by
    # construction.  Hop 3 walks the store's parked capital projects.
    service_fund.walk_awaiting_funds(store)

    # The compliance axis is untouched by tender: no sale-scoped operation
    # ever writes compliance_state, so the visit leaves OPEN before the
    # patron rescore runs its own cascade.
    sale["tender_state"] = "TENDERED"
    service_patron.recompute_risk(patron)
    touch(store)
    touch(sale)
    return object_response(serialize.sale_out(sale), 200)


@bp.post("/sales/<sale_id>/void")
def void_sale(sale_id):
    V.authenticate(("ComplianceOfficer",))
    sale = lookups.sale(sale_id)
    body = V.raw_body()
    voided_reason = V.want_enum(body, "voided_reason", C.VOIDED_REASONS, required=True)
    if sale["tender_state"] == "VOIDED":
        raise ApiError("ERR_SALE_ALREADY_VOIDED")

    store = db.stores[sale["store_id"]]
    patron = db.patrons[sale["patron_id"]]
    was_tendered = sale["tender_state"] == "TENDERED"

    sale["tender_state"] = "VOIDED"
    sale["voided_reason"] = voided_reason

    if was_tendered:
        derive.append_ledger_entry(
            store, "SURCHARGE", "SURCHARGE_REVERSAL", -sale["surcharge_total_cents"],
            "SALE", sale["id"],
        )
        settled = sale["settled_allowance_cents"] or 0
        if settled > 0:
            derive.append_ledger_entry(
                store, "DIVIDEND", "ALLOWANCE_REVERSAL", -settled, "SALE", sale["id"]
            )

    # The voided visit is now excluded from every risk input set.
    service_patron.recompute_risk(patron)
    if was_tendered:
        touch(store)
    touch(sale)
    return object_response(serialize.sale_out(sale), 200)


@bp.get("/sales")
def list_sales():
    V.authenticate(("StoreCashier", "ComplianceOfficer"))
    limit, offset = V.pagination()
    store_id = V.query_string("store_id")
    patron_id = V.query_string("patron_id")
    acting_delegation_id = V.query_string("acting_delegation_id")
    tender_state = V.query_enum("tender_state", C.TENDER_STATES)
    compliance_state = V.query_enum("compliance_state", C.COMPLIANCE_STATES)
    rows = sorted_records(db.sales)
    if store_id is not None:
        rows = [r for r in rows if r["store_id"] == store_id]
    if patron_id is not None:
        rows = [r for r in rows if r["patron_id"] == patron_id]
    if acting_delegation_id is not None:
        rows = [r for r in rows if r["acting_delegation_id"] == acting_delegation_id]
    if tender_state is not None:
        rows = [r for r in rows if r["tender_state"] == tender_state]
    if compliance_state is not None:
        rows = [r for r in rows if r["compliance_state"] == compliance_state]
    page, total = V.paginate(rows, limit, offset)
    return array_response([serialize.sale_out(r) for r in page], limit, offset, total)


@bp.get("/sales/<sale_id>")
def read_sale(sale_id):
    caller = V.authenticate(("StoreCashier", "ComplianceOfficer", "Patron"))
    sale = lookups.sale(sale_id)
    if caller.role == "Patron" and sale["patron_id"] != caller.user_id:
        raise ApiError("ERR_PATRON_SCOPE_VIOLATION")
    return object_response(serialize.sale_out(sale), 200)


@bp.get("/sale-lines")
def list_sale_lines():
    V.authenticate(("StoreCashier", "ComplianceOfficer"))
    limit, offset = V.pagination()
    sale_id = V.query_string("sale_id")
    product_id = V.query_string("product_id")
    rows = sorted_records(db.sale_lines)
    if sale_id is not None:
        rows = [r for r in rows if r["sale_id"] == sale_id]
    if product_id is not None:
        rows = [r for r in rows if r["product_id"] == product_id]
    page, total = V.paginate(rows, limit, offset)
    return array_response([serialize.sale_line_out(r) for r in page], limit, offset, total)


@bp.get("/sale-lines/<line_id>")
def read_sale_line(line_id):
    V.authenticate(("StoreCashier", "ComplianceOfficer"))
    line = lookups.sale_line(line_id)
    return object_response(serialize.sale_line_out(line), 200)
