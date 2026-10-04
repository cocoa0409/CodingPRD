"""Suppliers, tenders, bids, and blind quality panels."""
from decimal import Decimal

from flask import Blueprint, g

import calc
import svc
from core import (
    ApiError,
    body,
    db,
    dump,
    endpoint,
    f_int,
    f_str,
    forbid_unless,
    new_row,
    paginate,
    q_enum,
    q_str,
    respond_object,
    sort_created,
    touch,
)

bp = Blueprint("procurement", __name__)


# ---------------------------------------------------------------------------
# Suppliers
# ---------------------------------------------------------------------------
@bp.post("/v1/suppliers")
@endpoint("ProcurementLead")
def create_supplier():
    payload = body()
    name = f_str(payload, "name")
    contact_email = f_str(payload, "contact_email")
    supplier = new_row(
        "Supplier",
        name=name,
        contact_email=contact_email,
        quality_score=Decimal("80.0"),
        status="ACTIVE",
    )
    db.suppliers[supplier["id"]] = supplier
    return respond_object(dump(supplier), 201)


@bp.get("/v1/suppliers/<supplier_id>")
@endpoint("ProcurementLead", "CategoryManager", "QualityAssuranceLead")
def read_supplier(supplier_id):
    return respond_object(dump(svc.need_supplier(supplier_id)))


@bp.get("/v1/suppliers/<supplier_id>/products")
@endpoint("ProcurementLead", "CategoryManager")
def list_supplier_products(supplier_id):
    svc.need_supplier(supplier_id)
    rows = sort_created(
        [
            p
            for p in db.products.values()
            if p["primary_supplier_id"] == supplier_id
            or p["secondary_supplier_id"] == supplier_id
        ]
    )
    return paginate(rows)


@bp.get("/v1/suppliers/<supplier_id>/bids")
@endpoint("ProcurementLead", "QualityAssuranceLead")
def list_supplier_bids(supplier_id):
    svc.need_supplier(supplier_id)
    rows = sort_created(
        [b for b in db.bids.values() if b["supplier_id"] == supplier_id]
    )
    return paginate(rows)


# ---------------------------------------------------------------------------
# Tenders
# ---------------------------------------------------------------------------
@bp.post("/v1/tenders")
@endpoint("ProcurementLead")
def create_tender():
    payload = body()
    product_id = f_str(payload, "product_id")
    bid_ceiling_cents = f_int(payload, "bid_ceiling_cents", minimum=1)
    f_int(
        payload,
        "min_sources",
        required=False,
        default=calc.MIN_SOURCES_FIXED,
        minimum=1,
    )
    # tier 4 -- body FK existence
    svc.need_product(product_id)
    tender = new_row(
        "SupplierTender",
        product_id=product_id,
        bid_ceiling_cents=bid_ceiling_cents,
        min_sources=calc.MIN_SOURCES_FIXED,
        status="DRAFT",
        winning_primary_bid_id=None,
        winning_secondary_bid_id=None,
    )
    db.tenders[tender["id"]] = tender
    return respond_object(dump(tender), 201)


@bp.get("/v1/tenders/<tender_id>")
@endpoint("ProcurementLead", "QualityAssuranceLead", "CategoryManager")
def read_tender(tender_id):
    return respond_object(dump(svc.need_tender(tender_id)))


@bp.post("/v1/tenders/<tender_id>/open")
@endpoint("ProcurementLead")
def open_tender(tender_id):
    tender = svc.need_tender(tender_id)
    if tender["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE")
    tender["status"] = "OPEN"
    touch(tender)
    return respond_object(dump(tender))


@bp.post("/v1/tenders/<tender_id>/close")
@endpoint("ProcurementLead")
def close_tender(tender_id):
    tender = svc.need_tender(tender_id)
    if tender["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE")
    tender["status"] = "CLOSED"
    touch(tender)
    return respond_object(dump(tender))


@bp.post("/v1/tenders/<tender_id>/cancel")
@endpoint("ProcurementLead")
def cancel_tender(tender_id):
    tender = svc.need_tender(tender_id)
    if tender["status"] not in ("DRAFT", "OPEN"):
        raise ApiError("ERR_INVALID_STATE")
    tender["status"] = "CANCELLED"
    touch(tender)
    return respond_object(dump(tender))


@bp.post("/v1/tenders/<tender_id>/evaluate")
@endpoint("ProcurementLead")
def evaluate_tender(tender_id):
    tender = svc.need_tender(tender_id)
    if tender["status"] != "CLOSED":
        raise ApiError("ERR_INVALID_STATE")
    svc.evaluate_tender(tender)
    return respond_object(dump(tender))


@bp.post("/v1/tenders/<tender_id>/award")
@endpoint("ProcurementLead")
def award_tender(tender_id):
    tender = svc.need_tender(tender_id)
    payload = body()
    primary_bid_id = f_str(payload, "primary_bid_id")
    secondary_bid_id = f_str(payload, "secondary_bid_id")
    # tier 4 -- body references resolve
    primary = svc.need_bid(primary_bid_id)
    secondary = svc.need_bid(secondary_bid_id)
    # tier 5 -- state admissibility
    if tender["status"] != "EVALUATING":
        raise ApiError("ERR_INVALID_STATE")
    # tier 8 -- structural dual-source rules
    if primary["supplier_id"] == secondary["supplier_id"]:
        raise ApiError("ERR_DUAL_SOURCE_REQUIRED")
    eligible = [
        b for b in svc.bids_of_tender(tender["id"]) if b["status"] == "ELIGIBLE"
    ]
    if primary not in eligible or secondary not in eligible:
        raise ApiError("ERR_INVALID_STATE")
    distinct = {b["supplier_id"] for b in eligible}
    if len(distinct) < tender["min_sources"]:
        raise ApiError("ERR_DUAL_SOURCE_REQUIRED")
    product = db.products[tender["product_id"]]
    if product["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_STATE")
    if product["kind"] == "CORE":
        category = db.categories[product["category_id"]]
        if category["active_sku_count"] >= category["sku_cap"]:
            raise ApiError("ERR_SKU_CAP_EXCEEDED")
    svc.award_tender(tender, primary, secondary)
    return respond_object(dump(tender))


@bp.post("/v1/tenders/<tender_id>/retender")
@endpoint("ProcurementLead")
def retender_tender(tender_id):
    tender = svc.need_tender(tender_id)
    if tender["status"] != "EVALUATING":
        raise ApiError("ERR_INVALID_STATE")
    eligible = [
        b for b in svc.bids_of_tender(tender["id"]) if b["status"] == "ELIGIBLE"
    ]
    if len({b["supplier_id"] for b in eligible}) >= tender["min_sources"]:
        raise ApiError("ERR_INVALID_STATE")
    svc.retender(tender)
    return respond_object(dump(tender))


# ---------------------------------------------------------------------------
# Bids
# ---------------------------------------------------------------------------
@bp.post("/v1/tenders/<tender_id>/bids")
@endpoint("SupplierRep")
def create_bid(tender_id):
    # tier 4 -- path existence first
    tender = svc.need_tender(tender_id)
    payload = body()
    supplier_id = f_str(payload, "supplier_id")
    unit_cost_cents = f_int(payload, "unit_cost_cents", minimum=0)
    svc.need_supplier(supplier_id)
    # tier 2 -- entity-backed ownership: a rep bids only as their own supplier
    forbid_unless(g.user_id == supplier_id)
    # tier 5 -- tender must be OPEN
    if tender["status"] != "OPEN":
        raise ApiError("ERR_TENDER_NOT_OPEN")
    # tier 8 -- one bid per supplier per tender; suspended suppliers cannot bid
    if any(
        b["tender_id"] == tender["id"] and b["supplier_id"] == supplier_id
        for b in db.bids.values()
    ):
        raise ApiError("ERR_BID_DUPLICATE")
    supplier = db.suppliers[supplier_id]
    if supplier["status"] == "SUSPENDED":
        raise ApiError("ERR_SUPPLIER_SUSPENDED")
    # tier 9 -- fiscal rule last
    if unit_cost_cents > tender["bid_ceiling_cents"]:
        raise ApiError("ERR_BID_CEILING_EXCEEDED")
    bid = new_row(
        "TenderBid",
        tender_id=tender["id"],
        supplier_id=supplier_id,
        unit_cost_cents=unit_cost_cents,
        award_score=None,
        status="SUBMITTED",
    )
    db.bids[bid["id"]] = bid
    return respond_object(dump(bid), 201)


@bp.get("/v1/tenders/<tender_id>/bids")
@endpoint("ProcurementLead", "QualityAssuranceLead")
def list_tender_bids(tender_id):
    svc.need_tender(tender_id)
    return paginate(svc.bids_of_tender(tender_id))


@bp.get("/v1/bids/<bid_id>")
@endpoint("ProcurementLead", "QualityAssuranceLead", "SupplierRep")
def read_bid(bid_id):
    bid = svc.need_bid(bid_id)
    if g.role == "SupplierRep":
        forbid_unless(g.user_id == bid["supplier_id"])
    return respond_object(dump(bid))


# ---------------------------------------------------------------------------
# Blind quality panels
# ---------------------------------------------------------------------------
@bp.post("/v1/bids/<bid_id>/panels")
@endpoint("QualityAssuranceLead")
def create_panel(bid_id):
    bid = svc.need_bid(bid_id)
    payload = body()
    sample_code = f_str(payload, "sample_code")
    # tier 6 -- blind-panel integrity
    if svc.panel_of_bid(bid["id"]) is not None:
        raise ApiError("ERR_BLIND_VIOLATION")
    supplier = db.suppliers[bid["supplier_id"]]
    if (
        sample_code == supplier["id"]
        or supplier["id"] in sample_code
        or sample_code == supplier["name"]
        or (supplier["name"] and supplier["name"] in sample_code)
    ):
        raise ApiError("ERR_BLIND_VIOLATION")
    panel = new_row(
        "BlindQualityPanel",
        bid_id=bid["id"],
        sample_code=sample_code,
        score=None,
        status="SCHEDULED",
    )
    db.panels[panel["id"]] = panel
    return respond_object(dump(panel), 201)


@bp.get("/v1/panels")
@endpoint("QualityAssuranceLead", "ProcurementLead")
def list_panels():
    bid_id = q_str("bid_id")
    status = q_enum("status", calc.PANEL_STATUSES)
    rows = sort_created(list(db.panels.values()))
    if bid_id is not None:
        rows = [r for r in rows if r["bid_id"] == bid_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(rows)


@bp.get("/v1/panels/<panel_id>")
@endpoint("QualityAssuranceLead", "ProcurementLead")
def read_panel(panel_id):
    return respond_object(dump(svc.need_panel(panel_id)))


@bp.post("/v1/panels/<panel_id>/score")
@endpoint("QualityAssuranceLead")
def score_panel(panel_id):
    panel = svc.need_panel(panel_id)
    payload = body()
    score = f_int(payload, "score", minimum=0, maximum=100)
    # tier 5 -- panel must be SCHEDULED and its tender OPEN or CLOSED
    if panel["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE")
    bid = db.bids[panel["bid_id"]]
    tender = db.tenders[bid["tender_id"]]
    if tender["status"] not in ("OPEN", "CLOSED"):
        raise ApiError("ERR_INVALID_STATE")
    panel["score"] = score
    panel["status"] = "SCORED"
    touch(panel)
    return respond_object(dump(panel))
