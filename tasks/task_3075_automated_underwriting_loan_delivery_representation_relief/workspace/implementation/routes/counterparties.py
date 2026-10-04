"""Clock + counterparties: sellers and servicers."""
from flask import Blueprint

from core import (
    ApiError, db, dump, endpoint, f_dt, f_enum, f_int, f_str, body, fmt_dt,
    new_row, now, paginate, respond_object, sort_created, touch,
)
from svc import (
    MAX_QC_DEFECT_BPS, MIN_NET_WORTH_CENTS, advance_dependent_transitions,
    recompute_oversight_score,
)

bp = Blueprint("counterparties", __name__)

QC_RATINGS = ("SATISFACTORY", "NEEDS_IMPROVEMENT", "UNSATISFACTORY")


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
@bp.post("/gse/_clock/set_current_utc")
@endpoint("GseAdmin")
def set_clock():
    payload = body()
    current_utc = f_dt(payload, "current_utc")
    db.clock = current_utc
    advance_dependent_transitions()
    return respond_object({"current_utc": fmt_dt(db.clock)}, 200)


# ---------------------------------------------------------------------------
# Sellers
# ---------------------------------------------------------------------------
@bp.post("/gse/sellers")
@endpoint("GseAdmin")
def create_seller():
    payload = body()
    legal_name = f_str(payload, "legal_name")
    seller_number = f_str(payload, "seller_number")
    net_worth_cents = f_int(payload, "net_worth_cents")
    qc_defect_rate_bps = f_int(payload, "qc_defect_rate_bps")
    for existing in db.sellers.values():
        if existing["seller_number"] == seller_number:
            raise ApiError("ERR_DUPLICATE_IDENTIFIER", "seller_number already in use.")
    seller = new_row(
        "seller",
        legal_name=legal_name,
        seller_number=seller_number,
        net_worth_cents=net_worth_cents,
        qc_defect_rate_bps=qc_defect_rate_bps,
        status="PENDING_APPROVAL",
        approval_cycle=1,
        probation_relief_enabled=False,
    )
    db.sellers[seller["id"]] = seller
    return respond_object(dump(seller), 201)


def get_seller_or_404(seller_id):
    seller = db.sellers.get(seller_id)
    if seller is None:
        raise ApiError("ERR_NOT_FOUND", "Seller not found.")
    return seller


@bp.get("/gse/sellers/<seller_id>")
@endpoint("GseAdmin", "GseUnderwritingEngine", "SellerOfficer", "Underwriter", "QcAuditor", "ServicerOfficer")
def get_seller(seller_id):
    return respond_object(dump(get_seller_or_404(seller_id)), 200)


@bp.post("/gse/sellers/<seller_id>/approve")
@endpoint("GseAdmin")
def approve_seller(seller_id):
    seller = get_seller_or_404(seller_id)
    if seller["status"] not in ("PENDING_APPROVAL", "SUSPENDED"):
        raise ApiError("ERR_INVALID_STATE", "Seller cannot be approved from status %s." % seller["status"])
    if int(seller["net_worth_cents"]) < MIN_NET_WORTH_CENTS:
        raise ApiError("ERR_NET_WORTH_BELOW_MINIMUM", "Seller net worth below minimum.")
    if int(seller["qc_defect_rate_bps"]) > MAX_QC_DEFECT_BPS:
        raise ApiError("ERR_QC_DEFECT_RATE_EXCEEDED", "Seller QC defect rate above maximum.")
    reapproval = seller["status"] == "SUSPENDED"
    seller["status"] = "APPROVED"
    if reapproval:
        seller["approval_cycle"] = int(seller["approval_cycle"]) + 1
        if seller["approval_cycle"] == 2:
            seller["probation_relief_enabled"] = True
    touch(seller)
    if reapproval:
        # The probation cap may lower relief tiers on this seller's loans.
        from svc import recompute_relief_tier
        for loan in db.loans.values():
            if loan["seller_id"] == seller["id"]:
                recompute_relief_tier(loan)
    return respond_object(dump(seller), 200)


@bp.post("/gse/sellers/<seller_id>/suspend")
@endpoint("GseAdmin")
def suspend_seller(seller_id):
    seller = get_seller_or_404(seller_id)
    if seller["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", "Only an APPROVED seller can be suspended.")
    seller["status"] = "SUSPENDED"
    touch(seller)
    return respond_object(dump(seller), 200)


@bp.post("/gse/sellers/<seller_id>/terminate")
@endpoint("GseAdmin")
def terminate_seller(seller_id):
    seller = get_seller_or_404(seller_id)
    if seller["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", "Only an APPROVED seller can be terminated.")
    for loan in db.loans.values():
        if loan["seller_id"] == seller["id"] and loan["status"] == "DELIVERED":
            raise ApiError("ERR_SELLER_HAS_ACTIVE_LOANS", "Seller has loans in DELIVERED status.")
    seller["status"] = "TERMINATED"
    touch(seller)
    return respond_object(dump(seller), 200)


# ---------------------------------------------------------------------------
# Servicers
# ---------------------------------------------------------------------------
@bp.post("/gse/servicers")
@endpoint("GseAdmin")
def create_servicer():
    payload = body()
    legal_name = f_str(payload, "legal_name")
    servicer_number = f_str(payload, "servicer_number")
    net_worth_cents = f_int(payload, "net_worth_cents")
    qc_rating = f_enum(payload, "qc_rating", QC_RATINGS)
    for existing in db.servicers.values():
        if existing["servicer_number"] == servicer_number:
            raise ApiError("ERR_DUPLICATE_IDENTIFIER", "servicer_number already in use.")
    servicer = new_row(
        "servicer",
        legal_name=legal_name,
        servicer_number=servicer_number,
        net_worth_cents=net_worth_cents,
        qc_rating=qc_rating,
        status="PENDING_APPROVAL",
        oversight_score=100,
    )
    db.servicers[servicer["id"]] = servicer
    return respond_object(dump(servicer), 201)


def get_servicer_or_404(servicer_id):
    servicer = db.servicers.get(servicer_id)
    if servicer is None:
        raise ApiError("ERR_NOT_FOUND", "Servicer not found.")
    return servicer


@bp.get("/gse/servicers/<servicer_id>")
@endpoint("GseAdmin", "GseUnderwritingEngine", "SellerOfficer", "Underwriter", "QcAuditor", "ServicerOfficer")
def get_servicer(servicer_id):
    return respond_object(dump(get_servicer_or_404(servicer_id)), 200)


@bp.post("/gse/servicers/<servicer_id>/approve")
@endpoint("GseAdmin")
def approve_servicer(servicer_id):
    servicer = get_servicer_or_404(servicer_id)
    if servicer["status"] != "PENDING_APPROVAL":
        raise ApiError("ERR_INVALID_STATE", "Servicer cannot be approved from status %s." % servicer["status"])
    if int(servicer["net_worth_cents"]) < MIN_NET_WORTH_CENTS:
        raise ApiError("ERR_NET_WORTH_BELOW_MINIMUM", "Servicer net worth below minimum.")
    if servicer["qc_rating"] != "SATISFACTORY":
        raise ApiError("ERR_SERVICER_QC_RATING_INSUFFICIENT", "Servicer QC rating is not SATISFACTORY.")
    servicer["status"] = "APPROVED"
    touch(servicer)
    return respond_object(dump(servicer), 200)


@bp.post("/gse/servicers/<servicer_id>/suspend")
@endpoint("GseAdmin")
def suspend_servicer(servicer_id):
    servicer = get_servicer_or_404(servicer_id)
    if servicer["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", "Only an APPROVED servicer can be suspended.")
    servicer["status"] = "SUSPENDED"
    touch(servicer)
    return respond_object(dump(servicer), 200)


@bp.post("/gse/servicers/<servicer_id>/terminate")
@endpoint("GseAdmin")
def terminate_servicer(servicer_id):
    servicer = get_servicer_or_404(servicer_id)
    if servicer["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", "Only an APPROVED servicer can be terminated.")
    for loan in db.loans.values():
        if loan["servicer_id"] == servicer["id"] and loan["status"] in ("DELIVERED", "PURCHASED"):
            raise ApiError("ERR_SERVICER_HAS_ACTIVE_LOANS", "Servicer has loans in DELIVERED or PURCHASED status.")
    servicer["status"] = "TERMINATED"
    touch(servicer)
    return respond_object(dump(servicer), 200)
