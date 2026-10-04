"""Brand equity agreements: appointment, OCC-guarded amendment, equity index
(§3.1, §3.2, §2.7)."""

from flask import Blueprint, request

import calc
import clock
import db
from auth import ALL_ROLES, ROLE_BREWER_ADMIN, require_roles
from db import touch
from envelope import created, ok, paginate
from errors import (ApiError, ERR_AGREEMENT_NOT_ACTIVE, ERR_INVALID_REQUEST,
                    ERR_NOT_FOUND, ERR_PORTFOLIO_CONCENTRATION_EXCEEDED,
                    ERR_ROFR_HOLDER_CONFLICT, ERR_STALE_VERSION,
                    ERR_TERRITORY_NOT_VACANT, ERR_WHOLESALER_NOT_ELIGIBLE)
from validate import check_string_array, field, get_body, validate_body

bp = Blueprint("agreements", __name__)

QUARTER_RANK = {"Q1": 1, "Q2": 2, "Q3": 3, "Q4": 4}
WEIGHTING_PROFILES = ("STANDARD", "SHARE_TILTED")
EQUITY_VARIANTS = ("PROVISIONAL", "AUDITED")

AMENDABLE_FIELDS = [
    "distribution_target_pct", "freshness_target_index", "share_target_pct",
    "declared_distribution_pct", "declared_freshness_index", "declared_share_pct",
    "brand_scope", "weighting_profile", "term_years", "rofr_holder_wholesaler_id",
]

CREATE_SPEC = {
    "territory_id": field("string", required=True),
    "wholesaler_id": field("string", required=True),
    "rofr_holder_wholesaler_id": field("string", nullable=True),
    "brand_scope": field("array", required=True),
    "weighting_profile": field("enum", enum=WEIGHTING_PROFILES, default="STANDARD"),
    "distribution_target_pct": field("number", required=True),
    "freshness_target_index": field("number", required=True),
    "share_target_pct": field("number", required=True),
    "declared_distribution_pct": field("number", required=True),
    "declared_freshness_index": field("number", required=True),
    "declared_share_pct": field("number", required=True),
    "term_years": field("integer", required=True),
}

AMEND_SPEC = {
    "expected_agreement_version": field("integer", required=True),
    "distribution_target_pct": field("number"),
    "freshness_target_index": field("number"),
    "share_target_pct": field("number"),
    "declared_distribution_pct": field("number"),
    "declared_freshness_index": field("number"),
    "declared_share_pct": field("number"),
    "brand_scope": field("array"),
    "weighting_profile": field("enum", enum=WEIGHTING_PROFILES),
    "term_years": field("integer"),
    "rofr_holder_wholesaler_id": field("string", nullable=True),
}


@bp.route("/agreements", methods=["POST"])
@require_roles(ROLE_BREWER_ADMIN)
def create_agreement(user_id, caller_role):
    data, _ = validate_body(get_body(), CREATE_SPEC)
    check_string_array("brand_scope", data["brand_scope"])
    territory = db.territories.get(data["territory_id"])
    if territory is None:
        raise ApiError(ERR_NOT_FOUND, "Territory not found", 404)
    wholesaler = db.wholesalers.get(data["wholesaler_id"])
    if wholesaler is None:
        raise ApiError(ERR_NOT_FOUND, "Wholesaler not found", 404)
    rofr_id = data["rofr_holder_wholesaler_id"]
    rofr_holder = None
    if rofr_id is not None:
        rofr_holder = db.wholesalers.get(rofr_id)
        if rofr_holder is None:
            raise ApiError(ERR_NOT_FOUND, "ROFR holder wholesaler not found", 404)
    if territory["status"] != "VACANT":
        raise ApiError(ERR_TERRITORY_NOT_VACANT, "Territory is not VACANT", 409)
    if wholesaler["status"] not in ("APPLICANT", "APPOINTED"):
        raise ApiError(ERR_WHOLESALER_NOT_ELIGIBLE,
                       "Wholesaler is not eligible for appointment", 409)
    if rofr_id is not None and (rofr_id == data["wholesaler_id"]
                                or rofr_holder["status"] == "TERMINATED"):
        raise ApiError(ERR_ROFR_HOLDER_CONFLICT,
                       "ROFR holder must differ from the appointed wholesaler and "
                       "reference an existing non-TERMINATED wholesaler", 422)
    if calc.book_concentration_breached(wholesaler["supplier_book"]):
        raise ApiError(ERR_PORTFOLIO_CONCENTRATION_EXCEEDED,
                       "Portfolio concentration limit exceeded", 409)
    agreement = db.stamped()
    agreement.update({
        "territory_id": territory["id"],
        "wholesaler_id": wholesaler["id"],
        "rofr_holder_wholesaler_id": rofr_id,
        "brand_scope": list(data["brand_scope"]),
        "weighting_profile": data["weighting_profile"],
        "distribution_target_pct": data["distribution_target_pct"],
        "freshness_target_index": data["freshness_target_index"],
        "share_target_pct": data["share_target_pct"],
        "declared_distribution_pct": data["declared_distribution_pct"],
        "declared_freshness_index": data["declared_freshness_index"],
        "declared_share_pct": data["declared_share_pct"],
        "term_years": data["term_years"],
        "status": "ACTIVE",
        "amendment_log": [],
    })
    db.agreements[agreement["id"]] = agreement
    territory["status"] = "AWARDED"
    territory["incumbent_wholesaler_id"] = wholesaler["id"]
    touch(territory)
    if wholesaler["status"] == "APPLICANT":
        wholesaler["status"] = "APPOINTED"
        touch(wholesaler)
    return created(agreement)


@bp.route("/agreements/<aid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_agreement(aid, user_id, caller_role):
    agreement = db.agreements.get(aid)
    if agreement is None:
        raise ApiError(ERR_NOT_FOUND, "Agreement not found", 404)
    return ok(agreement)


@bp.route("/agreements/<aid>/amendments", methods=["POST"])
@require_roles(ROLE_BREWER_ADMIN)
def amend_agreement(aid, user_id, caller_role):
    data, provided = validate_body(get_body(), AMEND_SPEC)
    if "brand_scope" in provided:
        check_string_array("brand_scope", data["brand_scope"])
    agreement = db.agreements.get(aid)
    if agreement is None:
        raise ApiError(ERR_NOT_FOUND, "Agreement not found", 404)
    if agreement["status"] != "ACTIVE":
        raise ApiError(ERR_AGREEMENT_NOT_ACTIVE, "Agreement is not ACTIVE", 409)
    if data["expected_agreement_version"] != agreement["version"]:
        raise ApiError(ERR_STALE_VERSION,
                       "expected_agreement_version does not match the current "
                       "agreement version", 412)
    changed = [f for f in AMENDABLE_FIELDS if f in provided]
    for name in changed:
        agreement[name] = data[name]
    agreement["amendment_log"].append({
        "amended_at": clock.now_iso(),
        "fields_changed": changed,
    })
    touch(agreement)
    return ok(agreement)


@bp.route("/agreements/<aid>/equity-index", methods=["GET"])
@require_roles(*ALL_ROLES)
def equity_index(aid, user_id, caller_role):
    agreement = db.agreements.get(aid)
    if agreement is None:
        raise ApiError(ERR_NOT_FOUND, "Agreement not found", 404)
    variant = request.args.get("variant", "PROVISIONAL")
    if variant not in EQUITY_VARIANTS:
        raise ApiError(ERR_INVALID_REQUEST,
                       "variant must be PROVISIONAL or AUDITED", 400)
    if variant == "PROVISIONAL":
        dist = agreement["declared_distribution_pct"]
        fresh = agreement["declared_freshness_index"]
        share = agreement["declared_share_pct"]
        source = "DECLARED"
    else:
        reviews = [r for r in db.reviews.values()
                   if r["wholesaler_id"] == agreement["wholesaler_id"]]
        if not reviews:
            return ok({
                "variant": variant,
                "equity_index": None,
                "distribution_component": None,
                "freshness_component": None,
                "share_component": None,
                "components_source": "NO_REVIEW",
            })
        latest = max(reviews, key=lambda r: (r["period_year"],
                                             QUARTER_RANK[r["period_quarter"]]))
        dist = latest["distribution_pct"]
        fresh = latest["freshness_index"]
        share = latest["share_pct"]
        source = "LATEST_REVIEW"
    return ok({
        "variant": variant,
        "equity_index": float(calc.equity_index(dist, fresh, share)),
        "distribution_component": dist,
        "freshness_component": fresh,
        "share_component": share,
        "components_source": source,
    })


@bp.route("/agreements/<aid>/transfer-applications", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_agreement_transfers(aid, user_id, caller_role):
    if aid not in db.agreements:
        raise ApiError(ERR_NOT_FOUND, "Agreement not found", 404)
    rows = [t for t in db.transfers.values() if t["agreement_id"] == aid]
    return paginate(rows, status_filter=request.args.get("status"))
