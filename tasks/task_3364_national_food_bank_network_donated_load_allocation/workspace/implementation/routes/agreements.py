"""Donor agreements, activation, poundage reporting and agreement-scoped lists."""

from decimal import Decimal, ROUND_FLOOR

from flask import Blueprint, request

import auth
import envelope
import serializers
import store
from errors import ERR_AGREEMENT_NOT_FOUND, ERR_INVALID_REQUEST, fail

bp = Blueprint("agreements", __name__)

DONOR_TYPES = ("MANUFACTURER", "RETAILER", "DISTRIBUTOR")
PRODUCT_CATEGORIES = ("DRY_GOODS", "PRODUCE", "DAIRY", "FROZEN_PROTEIN", "BAKERY")


def get_agreement_or_404(agreement_id):
    agreement = store.agreements.get(agreement_id)
    if agreement is None:
        fail(ERR_AGREEMENT_NOT_FOUND,
             "no donor agreement matches id %s" % agreement_id)
    return agreement


@bp.route("/network/donor-agreements", methods=["POST"])
def create_agreement():
    auth.require_roles("NetworkAdmin")
    data = auth.json_body()

    donor_name = auth.req_str(data, "donor_name")
    donor_type = auth.req_enum(data, "donor_type", DONOR_TYPES)
    category = auth.req_enum(data, "product_category", PRODUCT_CATEGORIES)
    committed_lbs = auth.req_int(data, "committed_lbs")
    if committed_lbs <= 0:
        fail(ERR_INVALID_REQUEST, "committed_lbs must be strictly positive")
    pool = auth.req_int(data, "freight_subsidy_pool_cents")
    if pool < 0:
        fail(ERR_INVALID_REQUEST, "freight_subsidy_pool_cents must be zero or greater")
    factor = auth.opt_number(data, "meal_equivalency_factor", 1.2)
    if factor <= 0:
        fail(ERR_INVALID_REQUEST, "meal_equivalency_factor must be strictly positive")

    agreement = store.new_record(
        donor_name=donor_name,
        donor_type=donor_type,
        product_category=category,
        committed_lbs=committed_lbs,
        meal_equivalency_factor=Decimal(str(factor)),
        status="DRAFT",
        freight_subsidy_pool_cents=pool,
        freight_subsidy_used_cents=0,
    )
    store.insert("agreements", agreement)
    return envelope.ok_object(serializers.agreement(agreement), 201)


@bp.route("/network/donor-agreements/<agreement_id>", methods=["GET"])
def read_agreement(agreement_id):
    auth.require_roles("NetworkAdmin", "MemberFoodBank")
    return envelope.ok_object(serializers.agreement(get_agreement_or_404(agreement_id)))


@bp.route("/network/donor-agreements/<agreement_id>/activate", methods=["POST"])
def activate_agreement(agreement_id):
    auth.require_roles("NetworkAdmin")
    agreement = get_agreement_or_404(agreement_id)
    if agreement["status"] != "ACTIVE":
        agreement["status"] = "ACTIVE"
        store.touch(agreement)
    return envelope.ok_object(serializers.agreement(agreement))


@bp.route("/network/donor-agreements/<agreement_id>/poundage-summary", methods=["GET"])
def poundage_summary(agreement_id):
    auth.require_roles("NetworkAdmin", "MemberFoodBank")
    agreement = get_agreement_or_404(agreement_id)
    factor = Decimal(str(agreement["meal_equivalency_factor"]))

    qualifying = [
        load for load in store.ordered(store.loads.values())
        if load["donor_agreement_id"] == agreement["id"]
        and load["status"] == "DELIVERED"
        and int(load.get("delivered_lbs") or 0) > 0
        and load["safety_status"] != "RECALLED"
    ]
    total_lbs = sum(int(load["delivered_lbs"]) for load in qualifying)
    basis = request.args.get("rounding_basis") or "PER_LOAD"
    if basis == "SUM_THEN_DIVIDE":
        total_meals = int((Decimal(total_lbs) / factor).to_integral_value(rounding=ROUND_FLOOR))
    else:
        total_meals = sum(
            int((Decimal(int(load["delivered_lbs"])) / factor).to_integral_value(rounding=ROUND_FLOOR))
            for load in qualifying
        )
    return envelope.ok_object({
        "donor_agreement_id": agreement["id"],
        "total_lbs": total_lbs,
        "total_meals": total_meals,
        "delivered_load_count": len(qualifying),
    })


@bp.route("/network/donor-agreements/<agreement_id>/loads", methods=["GET"])
def list_agreement_loads(agreement_id):
    auth.require_roles("NetworkAdmin", "MemberFoodBank")
    agreement = get_agreement_or_404(agreement_id)
    rows = [l for l in store.ordered(store.loads.values())
            if l["donor_agreement_id"] == agreement["id"]]
    status_filter = request.args.get("status")
    if status_filter:
        rows = [l for l in rows if l["status"] == status_filter]
    page, limit, offset, total = auth.paginate(rows)
    return envelope.ok_array([serializers.load(l) for l in page], limit, offset, total)


@bp.route("/network/donor-agreements/<agreement_id>/recalls", methods=["GET"])
def list_agreement_recalls(agreement_id):
    auth.require_roles("NetworkAdmin", "MemberFoodBank")
    agreement = get_agreement_or_404(agreement_id)
    rows = [r for r in store.ordered(store.recalls.values())
            if r["donor_agreement_id"] == agreement["id"]]
    status_filter = request.args.get("recall_status")
    if status_filter:
        rows = [r for r in rows if r["recall_status"] == status_filter]
    page, limit, offset, total = auth.paginate(rows)
    return envelope.ok_array([serializers.recall(r) for r in page], limit, offset, total)
