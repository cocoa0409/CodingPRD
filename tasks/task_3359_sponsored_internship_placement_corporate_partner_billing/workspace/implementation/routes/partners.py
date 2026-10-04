"""Corporate partner endpoints (PRD 3.3, 4)."""

from decimal import Decimal

from flask import Blueprint

import db
import middleware
import response
import validators
from routes.common import must_get
from services import partner_svc

bp = Blueprint("partners", __name__)

INDUSTRIES = ("TECH", "FINANCE", "HEALTHCARE", "RETAIL", "LOGISTICS")
FEE_TIERS = ("TIER_A", "TIER_B", "TIER_C")


@bp.post("/partners")
def create_partner():
    middleware.require(("ProgramStaff",))
    data = validators.body()
    legal_name = validators.as_str(data, "legal_name")
    industry = validators.as_enum(data, "industry", INDUSTRIES)
    billing_email = validators.as_str(data, "billing_email")
    fee_tier = validators.as_enum(data, "fee_tier", FEE_TIERS, required=False, default="TIER_C")

    row = db.make_row(
        legal_name=legal_name,
        industry=industry,
        billing_email=billing_email,
        fee_tier=fee_tier,
        status="ACTIVE",
        placement_quality_score=Decimal("0.00"),
        on_time_payment_ratio=Decimal("0.0000"),
        credit_hold=False,
        outstanding_balance_cents=0,
        billed_cents=0,
        collected_cents=0,
        collection_ratio=Decimal("0.0000"),
        oldest_open_due_date=None,
    )
    db.insert("partners", row)
    return response.success(row, status=201)


@bp.get("/partners/<partner_id>")
def read_partner(partner_id):
    middleware.require(("ProgramStaff", "Partner"))
    partner = must_get("partners", partner_id, "partner")
    partner_svc.refresh_partner(partner)
    return response.success(partner)


@bp.get("/partners/<partner_id>/agreements")
def list_partner_agreements(partner_id):
    middleware.require(("ProgramStaff", "Partner"))
    must_get("partners", partner_id, "partner")
    status_filter = validators.request_arg("status")
    rows = [a for a in db.all_rows("agreements") if a["partner_id"] == partner_id]
    if status_filter:
        rows = [a for a in rows if a["status"] == status_filter]
    return response.list_response(rows, key=response.by_created_at)
