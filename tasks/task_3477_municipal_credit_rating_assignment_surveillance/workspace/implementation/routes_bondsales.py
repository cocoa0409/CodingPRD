"""Bond sale pricing (PRD §3.7): PROVISIONAL prices off the scorecard's
indicative notch; FINAL off the rating's current published notch."""
from flask import Blueprint, request

from auth import auth, authenticate
from constants import PRICING_MODES, ROLE_ISSUER, ROLE_UNDERWRITER
from envelope import paginate, parse_pagination, success_array, success_object
from errors import (
    ERR_INVALID_REQUEST,
    ERR_NOT_RESOURCE_OWNER,
    ERR_RATING_STATE_INVALID,
    raise_err,
)
from services_pricing import price
from services_scoring import current_scorecard
from store import db, new_entity
from validators import (
    body,
    get_bond_sale,
    get_issuer,
    get_rating,
    present,
    require_datetime,
    require_enum,
    require_fields,
    require_int,
)

bp = Blueprint("bondsales", __name__)


@bp.route("/muni/bond-sales", methods=["POST"])
def create_bond_sale():
    user_id, role = auth([ROLE_ISSUER, ROLE_UNDERWRITER])
    payload = body()

    # Priority 3: body-supplied FK references must exist (issuer, rating).
    issuer = get_issuer(payload["issuer_id"]) if present(payload, "issuer_id") else None
    rating = get_rating(payload["rating_id"]) if present(payload, "rating_id") else None

    # Priority 4: well-formedness and numeric/structural bounds.
    require_fields(
        payload,
        ["issuer_id", "rating_id", "par_amount_cents", "maturity_years", "sale_date", "pricing_mode"],
    )
    require_enum(payload, "pricing_mode", PRICING_MODES)
    par_amount_cents = require_int(payload, "par_amount_cents")
    if par_amount_cents <= 0:
        raise_err(ERR_INVALID_REQUEST, "par_amount_cents must be > 0")
    maturity_years = require_int(payload, "maturity_years")
    if maturity_years < 1 or maturity_years > 30:
        raise_err(ERR_INVALID_REQUEST, "maturity_years must be within 1..30")
    sale_date = require_datetime(payload, "sale_date")

    # Priority 5: an Issuer prices its own sales; the rating must belong to
    # the payload issuer.
    if role == ROLE_ISSUER and payload["issuer_id"] != user_id:
        raise_err(ERR_NOT_RESOURCE_OWNER, "issuer may only price its own bond sales")
    if rating["issuer_id"] != payload["issuer_id"]:
        raise_err(ERR_NOT_RESOURCE_OWNER, "rating does not belong to the named issuer")

    # Priority 6: FINAL requires PUBLISHED; PROVISIONAL requires ASSIGNED or
    # PUBLISHED.
    if payload["pricing_mode"] == "FINAL":
        if rating["status"] != "PUBLISHED":
            raise_err(ERR_RATING_STATE_INVALID, "FINAL pricing requires a PUBLISHED rating")
        notch = rating["notch"]
    else:
        if rating["status"] not in ("ASSIGNED", "PUBLISHED"):
            raise_err(ERR_RATING_STATE_INVALID, "PROVISIONAL pricing requires an ASSIGNED or PUBLISHED rating")
        scorecard = current_scorecard(rating["engagement_id"])
        if scorecard is None:
            raise_err(ERR_RATING_STATE_INVALID, "rating's engagement has no scorecard")
        notch = scorecard["indicative_notch"]

    effective_yield_bps, annual_interest_cents, total_interest_cents = price(
        par_amount_cents, maturity_years, notch
    )
    ent = new_entity()
    ent.update(
        issuer_id=payload["issuer_id"],
        rating_id=payload["rating_id"],
        par_amount_cents=par_amount_cents,
        maturity_years=maturity_years,
        sale_date=sale_date,
        pricing_mode=payload["pricing_mode"],
        effective_yield_bps=effective_yield_bps,
        annual_interest_cents=annual_interest_cents,
        total_interest_cents=total_interest_cents,
    )
    db.bond_sales[ent["id"]] = ent
    return success_object(ent, status=201)


@bp.route("/muni/bond-sales", methods=["GET"])
def list_bond_sales():
    authenticate()
    items = list(db.bond_sales.values())
    for field in ("issuer_id", "rating_id"):
        value = request.args.get(field)
        if value is not None:
            items = [b for b in items if b.get(field) == value]
    items.sort(key=lambda b: (b["created_at"], b["_seq"]))
    limit, offset = parse_pagination(request.args)
    page, total = paginate(items, limit, offset)
    return success_array(page, total, limit, offset)


@bp.route("/muni/bond-sales/<bond_sale_id>", methods=["GET"])
def get_one_bond_sale(bond_sale_id):
    authenticate()
    return success_object(get_bond_sale(bond_sale_id))
