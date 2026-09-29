"""Brewer placement, compliance evaluation and asset recovery (PRD 3.3, 3.7)."""
from flask import Blueprint

import calc
import cascade
import lookup
import serializers
import shape
from authz import (ROLE_ACCOUNT_MANAGER, ROLE_BILLING_SPECIALIST, ROLE_PROGRAM_ADMIN,
                  authenticate)
from envelope import created, ok
from errors import ApiError
from routes.accounts import OPERATING_POSTURES
from store import bump, db, insert, now, ordered

bp = Blueprint("placements", __name__)

TERMS_TYPES = ("LOAN", "RENTAL")
ASSET_CONDITIONS = ("SERVICEABLE", "UNSERVICEABLE")
EVALUABLE_PLACEMENT_STATUSES = ("ACTIVE", "RETRIEVAL_SCHEDULED")
RETRIEVABLE_PLACEMENT_STATUSES = ("RETRIEVAL_SCHEDULED", "UNRETURNED_BILLED")


@bp.post("/ocs/equipment-placements")
def create_placement():
    authenticate((ROLE_ACCOUNT_MANAGER,))
    fields = shape.fields()
    site_id = fields.string("site_id", min_len=1)
    asset_id = fields.string("asset_id", min_len=1)
    terms_type = fields.enum("terms_type", TERMS_TYPES)
    minimum_purchase = fields.integer("minimum_purchase_cents", minimum=0)
    min_term_months = fields.integer("min_term_months", minimum=1, maximum=60)
    expected_site_version = fields.integer("expected_site_version")

    site = lookup.site(site_id)
    asset = lookup.equipment_asset(asset_id)

    # Rung 9: stale-version rejection precedes every state, safety and fiscal gate.
    if expected_site_version != site["version"]:
        raise ApiError("ERR_STALE_SITE_VERSION",
                       "The site has moved on since it was last read.")
    account = db.accounts.get(site["account_id"])
    if account is None or account["program_posture"] not in OPERATING_POSTURES:
        raise ApiError("ERR_ACCOUNT_NOT_OPERATING",
                       "The owning account does not accept new placements.")
    if asset["asset_status"] != "IN_STOCK":
        raise ApiError("ERR_ASSET_NOT_AVAILABLE",
                       "Asset fleet state %s cannot be installed." % asset["asset_status"])
    if asset["asset_role"] != "PLACEMENT":
        raise ApiError("ERR_ASSET_ROLE_MISMATCH",
                       "Only a PLACEMENT asset may be installed at a site.")
    if site["recommended_model_id"] is None:
        raise ApiError("ERR_SITE_NOT_PLANNED",
                       "The site must be planned before equipment is installed.")
    if terms_type == "LOAN" and minimum_purchase < calc.LOAN_MINIMUM_FLOOR_CENTS:
        raise ApiError("ERR_MINIMUM_BELOW_LOAN_FLOOR",
                       "A LOAN placement requires a minimum purchase of at least %d cents."
                       % calc.LOAN_MINIMUM_FLOOR_CENTS)

    # Creation supersedes the site's prior active placement.
    prior = calc.active_placement_of_site(site["id"])
    if prior is not None:
        prior["placement_status"] = "SUPERSEDED"
        bump(prior)
        prior_asset = db.equipment_assets.get(prior["asset_id"])
        if prior_asset is not None:
            prior_asset["asset_status"] = "IN_STOCK"
            bump(prior_asset)

    row = insert(db.equipment_placements, {
        "site_id": site_id,
        "asset_id": asset_id,
        "terms_type": terms_type,
        "minimum_purchase_cents": minimum_purchase,
        "min_term_months": min_term_months,
        "placement_status": "ACTIVE",
        "compliance_status": "MEETING_MINIMUM",
        "trailing_purchase_cents": 0,
        "shortfall_fee_cents": 0,
        "rent_charge_cents": 0,
        "placed_at": now(),
        "retrieval_due_by": None,
        "unreturned_billed_cents": 0,
        "_shortfall_line_emitted": False,
    })
    asset["asset_status"] = "PLACED"
    bump(asset)
    bump(site)
    # Bubble-up: the account leaves onboarding the moment equipment is installed.
    if account["program_posture"] == "ONBOARDING":
        account["program_posture"] = "ACTIVE"
        bump(account)
    return created(serializers.placement(row))


@bp.get("/ocs/equipment-placements")
def list_placements():
    authenticate((ROLE_ACCOUNT_MANAGER, ROLE_BILLING_SPECIALIST, ROLE_PROGRAM_ADMIN))
    rows = lookup.eq_filter(list(db.equipment_placements.values()), "site_id")
    rows = lookup.eq_filter(rows, "asset_id")
    rows = lookup.eq_filter(rows, "placement_status")
    rows = lookup.eq_filter(rows, "compliance_status")
    rows = lookup.eq_filter(rows, "terms_type")
    return lookup.listing(rows, serializers.placement)


@bp.get("/ocs/equipment-placements/<placement_id>")
def read_placement(placement_id):
    authenticate((ROLE_ACCOUNT_MANAGER, ROLE_BILLING_SPECIALIST, ROLE_PROGRAM_ADMIN))
    return ok(serializers.placement(lookup.placement(placement_id)))


@bp.post("/ocs/equipment-placements/<placement_id>/evaluate-compliance")
def evaluate_compliance(placement_id):
    authenticate((ROLE_BILLING_SPECIALIST,))
    placement = lookup.placement(placement_id)
    if placement["placement_status"] not in EVALUABLE_PLACEMENT_STATUSES:
        raise ApiError("ERR_PLACEMENT_STATE_INVALID",
                       "Placement state %s is not evaluable." % placement["placement_status"])

    placement["trailing_purchase_cents"] = calc.trailing_purchase_cents(placement["site_id"])
    status = placement["compliance_status"]
    if placement["trailing_purchase_cents"] < placement["minimum_purchase_cents"]:
        if status == "MEETING_MINIMUM":
            # The first shortfall is a warning; no fee at all is accrued.
            placement["compliance_status"] = "SHORTFALL_WARNED"
        elif status == "SHORTFALL_WARNED":
            placement["compliance_status"] = "SHORTFALL_BILLED"
            placement["shortfall_fee_cents"] = calc.shortfall_fee_cents(placement)
            placement["_shortfall_line_emitted"] = False
    else:
        if status == "SHORTFALL_BILLED":
            placement["compliance_status"] = "MEETING_MINIMUM"
            if not placement.get("_shortfall_line_emitted"):
                placement["shortfall_fee_cents"] = 0
        elif status == "SHORTFALL_WARNED":
            placement["compliance_status"] = "MEETING_MINIMUM"
    # Each evaluation increments the placement's version by 1.
    bump(placement)
    return ok(serializers.placement(placement))


@bp.post("/ocs/equipment-placements/<placement_id>/retrieve")
def retrieve_placement(placement_id):
    authenticate((ROLE_ACCOUNT_MANAGER,))
    fields = shape.fields()
    condition = fields.enum("retrieved_asset_condition", ASSET_CONDITIONS)
    placement = lookup.placement(placement_id)
    if placement["placement_status"] not in RETRIEVABLE_PLACEMENT_STATUSES:
        raise ApiError("ERR_PLACEMENT_STATE_INVALID",
                       "Placement state %s cannot be retrieved."
                       % placement["placement_status"])
    placement["placement_status"] = "RETRIEVED"
    bump(placement)
    asset = db.equipment_assets.get(placement["asset_id"])
    if asset is not None:
        if condition == "UNSERVICEABLE":
            asset["asset_status"] = "RETIRED"
            bump(asset)
        else:
            cascade.enter_reconditioning(asset, now())
    site = db.sites.get(placement["site_id"])
    account = db.accounts.get(site["account_id"]) if site is not None else None
    cascade.maybe_close_account(account)
    return ok(serializers.placement(placement))
