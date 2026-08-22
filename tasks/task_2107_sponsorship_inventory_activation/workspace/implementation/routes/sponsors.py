"""Sponsor brands (PRD 3.4)."""

from decimal import Decimal

from flask import Blueprint, request

from db import store, new_row
from errors import ApiError
from middleware import endpoint
from response import ok, created
from services.serialize import sponsor_out
from util import body_of, fail, v_str, v_enum

bp = Blueprint("sponsors", __name__)

CATEGORIES = {"BEVERAGE", "AUTOMOTIVE", "FINANCIAL", "TELECOM", "APPAREL", "TECH"}
READ_ROLES = ["PropertyAdmin", "SponsorshipSeller", "ContractApprover", "PerformanceAuditor"]


def get_sponsor_or_404(sponsor_id):
    sponsor = store.sponsors.get(sponsor_id)
    if sponsor is None:
        raise ApiError("ERR_SPONSOR_NOT_FOUND", 404)
    return sponsor


@bp.post("/sponsors")
@endpoint(["SponsorshipSeller"])
def create_sponsor():
    body = body_of(request)
    name = v_str(body, "name", min_len=1, max_len=120)
    category = v_enum(body, "category", CATEGORIES)
    contact_email = v_str(body, "contact_email", min_len=1)
    if "@" not in contact_email:
        fail("Field 'contact_email' must contain '@'.")

    row = new_row()
    row.update({
        "name": name,
        "category": category,
        "contact_email": contact_email,
        "status": "PROSPECT",
        "renewal_likelihood_score": Decimal("0.00"),
        "renewal_band": "LOW",
    })
    store.sponsors[row["id"]] = row
    return created(sponsor_out(row))


@bp.get("/sponsors/<sponsor_id>")
@endpoint(READ_ROLES)
def read_sponsor(sponsor_id):
    return ok(sponsor_out(get_sponsor_or_404(sponsor_id)))
