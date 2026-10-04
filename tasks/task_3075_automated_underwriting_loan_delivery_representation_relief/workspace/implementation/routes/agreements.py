"""Master agreements and LLPA matrices."""
from flask import Blueprint

from core import (
    ApiError, db, dump, endpoint, f_dt, f_str, body, new_row, now,
    paginate, q_enum, q_str, respond_object, sort_created, touch, bad_request,
)
from svc import on_matrix_swap

bp = Blueprint("agreements", __name__)

ALL_ROLES = ("GseAdmin", "GseUnderwritingEngine", "SellerOfficer", "Underwriter", "QcAuditor", "ServicerOfficer")


# ---------------------------------------------------------------------------
# Master agreements
# ---------------------------------------------------------------------------
@bp.post("/gse/master-agreements")
@endpoint("GseAdmin")
def create_agreement():
    payload = body()
    seller_id = f_str(payload, "seller_id")
    servicer_id = f_str(payload, "servicer_id")
    effective_date = f_dt(payload, "effective_date")
    expiration_date = f_dt(payload, "expiration_date")
    if expiration_date <= effective_date:
        bad_request("expiration_date must be strictly after effective_date.")
    if seller_id not in db.sellers:
        raise ApiError("ERR_NOT_FOUND", "Seller not found.")
    if servicer_id not in db.servicers:
        raise ApiError("ERR_NOT_FOUND", "Servicer not found.")
    agreement = new_row(
        "agreement",
        seller_id=seller_id,
        servicer_id=servicer_id,
        effective_date=effective_date,
        expiration_date=expiration_date,
        status="DRAFT",
    )
    db.agreements[agreement["id"]] = agreement
    return respond_object(dump(agreement), 201)


def get_agreement_or_404(agreement_id):
    agreement = db.agreements.get(agreement_id)
    if agreement is None:
        raise ApiError("ERR_NOT_FOUND", "Master agreement not found.")
    return agreement


@bp.get("/gse/master-agreements/<agreement_id>")
@endpoint(*ALL_ROLES)
def get_agreement(agreement_id):
    return respond_object(dump(get_agreement_or_404(agreement_id)), 200)


@bp.get("/gse/master-agreements")
@endpoint(*ALL_ROLES)
def list_agreements():
    rows = list(db.agreements.values())
    seller_id = q_str("seller_id")
    servicer_id = q_str("servicer_id")
    status = q_enum("status", ("DRAFT", "ACTIVE", "EXPIRED", "TERMINATED"))
    if seller_id is not None:
        rows = [r for r in rows if r["seller_id"] == seller_id]
    if servicer_id is not None:
        rows = [r for r in rows if r["servicer_id"] == servicer_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(sort_created(rows))


@bp.post("/gse/master-agreements/<agreement_id>/activate")
@endpoint("GseAdmin")
def activate_agreement(agreement_id):
    agreement = get_agreement_or_404(agreement_id)
    if agreement["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "Only a DRAFT agreement can be activated.")
    seller = db.sellers.get(agreement["seller_id"])
    if seller is None or seller["status"] != "APPROVED":
        raise ApiError("ERR_SELLER_NOT_APPROVED", "Seller is not APPROVED.")
    servicer = db.servicers.get(agreement["servicer_id"])
    if servicer is None or servicer["status"] != "APPROVED":
        raise ApiError("ERR_SERVICER_NOT_APPROVED", "Servicer is not APPROVED.")
    ts = now()
    if not (agreement["effective_date"] <= ts < agreement["expiration_date"]):
        raise ApiError("ERR_AGREEMENT_NOT_EFFECTIVE", "Agreement is outside its effective window.")
    agreement["status"] = "ACTIVE"
    touch(agreement)
    return respond_object(dump(agreement), 200)


@bp.post("/gse/master-agreements/<agreement_id>/terminate")
@endpoint("GseAdmin")
def terminate_agreement(agreement_id):
    agreement = get_agreement_or_404(agreement_id)
    if agreement["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Only an ACTIVE agreement can be terminated.")
    agreement["status"] = "TERMINATED"
    touch(agreement)
    return respond_object(dump(agreement), 200)


# ---------------------------------------------------------------------------
# LLPA matrices
# ---------------------------------------------------------------------------
REQUIRED_ROW_KEYS = ("occupancy", "product_type", "llpa_bps", "ltv_max_bp", "ltv_min_bp", "credit_min", "credit_max")


def _validate_rows(rows):
    if not isinstance(rows, list):
        bad_request("Field 'rows' must be an array.")
    validated = []
    for row in rows:
        if not isinstance(row, dict):
            bad_request("Each pricing row must be an object.")
        for key in REQUIRED_ROW_KEYS:
            if key not in row or row[key] is None:
                bad_request("Pricing row is missing '%s'." % key)
        if not isinstance(row["occupancy"], str) or not isinstance(row["product_type"], str):
            bad_request("Pricing row occupancy and product_type must be strings.")
        for key in ("llpa_bps", "ltv_max_bp", "ltv_min_bp", "credit_min", "credit_max"):
            value = row[key]
            if isinstance(value, bool) or not isinstance(value, int):
                bad_request("Pricing row '%s' must be an integer." % key)
        validated.append({
            "occupancy": row["occupancy"],
            "product_type": row["product_type"],
            "llpa_bps": row["llpa_bps"],
            "ltv_max_bp": row["ltv_max_bp"],
            "ltv_min_bp": row["ltv_min_bp"],
            "credit_min": row["credit_min"],
            "credit_max": row["credit_max"],
        })
    return validated


@bp.post("/gse/llpa-matrices")
@endpoint("GseAdmin")
def create_matrix():
    payload = body()
    effective_from = f_dt(payload, "effective_from")
    effective_until = f_dt(payload, "effective_until")
    if effective_until <= effective_from:
        bad_request("effective_until must be strictly after effective_from.")
    if "rows" not in payload:
        bad_request("Field 'rows' is required.")
    rows = _validate_rows(payload["rows"])
    old_active = None
    for matrix in db.matrices.values():
        if matrix["status"] == "ACTIVE":
            old_active = matrix
            matrix["status"] = "SUPERSEDED"
            touch(matrix)
    matrix = new_row(
        "matrix",
        effective_from=effective_from,
        effective_until=effective_until,
        rows=rows,
        status="ACTIVE",
    )
    db.matrices[matrix["id"]] = matrix
    on_matrix_swap(old_active, matrix)
    return respond_object(dump(matrix), 201)


def get_matrix_or_404(matrix_id):
    matrix = db.matrices.get(matrix_id)
    if matrix is None:
        raise ApiError("ERR_NOT_FOUND", "LLPA matrix not found.")
    return matrix


@bp.get("/gse/llpa-matrices/<matrix_id>")
@endpoint(*ALL_ROLES)
def get_matrix(matrix_id):
    return respond_object(dump(get_matrix_or_404(matrix_id)), 200)


@bp.get("/gse/llpa-matrices")
@endpoint(*ALL_ROLES)
def list_matrices():
    rows = list(db.matrices.values())
    status = q_enum("status", ("ACTIVE", "SUPERSEDED"))
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(sort_created(rows))
