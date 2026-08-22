"""Funds and share classes (PRD 3.1)."""

from flask import Blueprint, request

import db
import response
import serializers
import validation
from constants import (CLASS_CODES, DEFAULT_CUTOFF, DEFAULT_TWELVE_B_ONE, DISTRIBUTION_STATUSES,
                       DISTRIBUTION_TYPES, FUND_STATUSES, MAX_LOAD_PCT, NAV_STATUSES,
                       REGISTRATION_STATUSES)
from errors import invalid
from middleware import ALL_ROLES, ROLE_FA, authenticate
from money import ZERO, q3
from routes import helpers

bp = Blueprint("funds", __name__)


@bp.route("/funds", methods=["POST"])
def create_fund():
    authenticate((ROLE_FA,))
    body = validation.body()
    name = validation.get_string(body, "name", required=True, max_len=120)
    family = validation.get_string(body, "fund_family_code", required=True, max_len=12)
    cutoff = validation.get_time_of_day(body, "cutoff_time_utc", default=DEFAULT_CUTOFF)
    status = validation.get_enum(body, "status", FUND_STATUSES, default="ACTIVE")

    fund = db.create(db.store.funds, {
        "name": name,
        "fund_family_code": family,
        "cutoff_time_utc": cutoff,
        "status": status,
    })
    return response.created(serializers.fund(fund))


@bp.route("/funds/<fund_id>", methods=["GET"])
def read_fund(fund_id):
    authenticate(ALL_ROLES)
    fund = helpers.get_fund(fund_id)
    return response.ok(serializers.fund(fund))


def _parse_breakpoint_tiers(body):
    if not validation.present(body, "breakpoint_tiers"):
        raise invalid("Field 'breakpoint_tiers' is required.")
    raw = body["breakpoint_tiers"]
    if not isinstance(raw, list) or len(raw) == 0:
        raise invalid("Field 'breakpoint_tiers' must be a non-empty array.")
    tiers = []
    previous_min = None
    for index, element in enumerate(raw):
        if not isinstance(element, dict):
            raise invalid("Each breakpoint tier must be an object.")
        minimum = validation.get_decimal(element, "min_qualifying_amount", 2,
                                         required=True, non_negative=True)
        load_pct = validation.get_decimal(element, "load_pct", 4, required=True,
                                          non_negative=True)
        if load_pct > MAX_LOAD_PCT:
            raise invalid("A breakpoint load_pct may not exceed 0.0850.")
        if index == 0 and minimum != 0:
            raise invalid("The first breakpoint tier must start at a min_qualifying_amount of 0.")
        if previous_min is not None and minimum <= previous_min:
            raise invalid("Breakpoint tiers must strictly ascend by min_qualifying_amount.")
        previous_min = minimum
        tiers.append({"min_qualifying_amount": minimum, "load_pct": load_pct})
    return tiers


@bp.route("/share-classes", methods=["POST"])
def create_share_class():
    authenticate((ROLE_FA,))
    body = validation.body()
    fund_id = validation.get_id(body, "fund_id", required=True)
    class_code = validation.get_enum(body, "class_code", CLASS_CODES, required=True)
    seed_nav = validation.get_decimal(body, "seed_nav_per_share", 4, required=True, positive=True)
    tiers = _parse_breakpoint_tiers(body)
    cdsc_enabled = validation.get_bool(body, "cdsc_enabled", default=False)
    twelve_b_one = validation.get_decimal(body, "twelve_b_one_fee_pct", 4,
                                          default=DEFAULT_TWELVE_B_ONE, non_negative=True)

    fund = helpers.get_fund(fund_id)

    for existing in db.store.share_classes.values():
        if existing["fund_id"] == fund["id"] and existing["class_code"] == class_code:
            raise invalid("class_code must be unique within the fund.")

    share_class = db.create(db.store.share_classes, {
        "fund_id": fund["id"],
        "class_code": class_code,
        "seed_nav_per_share": seed_nav,
        "breakpoint_tiers": tiers,
        "cdsc_enabled": cdsc_enabled,
        "twelve_b_one_fee_pct": twelve_b_one,
        "total_shares_outstanding": q3(ZERO),
    })
    return response.created(serializers.share_class(share_class))


@bp.route("/share-classes/<share_class_id>", methods=["GET"])
def read_share_class(share_class_id):
    authenticate(ALL_ROLES)
    share_class = helpers.get_share_class(share_class_id)
    return response.ok(serializers.share_class(share_class))


@bp.route("/share-classes", methods=["GET"])
def list_share_classes():
    authenticate(ALL_ROLES)
    limit, offset = validation.pagination()
    records = db.values(db.store.share_classes)
    records = helpers.filter_equals(records, "fund_id", request.args.get("fund_id"))
    records = helpers.filter_equals(
        records, "class_code", validation.query_enum("class_code", CLASS_CODES))
    items, total = helpers.page(records, limit, offset)
    return response.listing([serializers.share_class(r) for r in items], total, limit, offset)


@bp.route("/share-classes/<share_class_id>/nav-records", methods=["GET"])
def list_class_nav_records(share_class_id):
    authenticate(ALL_ROLES)
    share_class = helpers.get_share_class(share_class_id)
    limit, offset = validation.pagination()
    records = [r for r in db.store.nav_records.values()
               if r["share_class_id"] == share_class["id"]]
    records = helpers.filter_equals(records, "valuation_date", validation.query_date("valuation_date"))
    records = helpers.filter_equals(records, "status", validation.query_enum("status", NAV_STATUSES))
    items, total = helpers.page(records, limit, offset)
    return response.listing([serializers.nav_record(r) for r in items], total, limit, offset)


@bp.route("/share-classes/<share_class_id>/blue-sky-registrations", methods=["GET"])
def list_class_registrations(share_class_id):
    authenticate(ALL_ROLES)
    share_class = helpers.get_share_class(share_class_id)
    limit, offset = validation.pagination()
    records = [r for r in db.store.registrations.values()
               if r["share_class_id"] == share_class["id"]]
    records = helpers.filter_equals(records, "state_code", request.args.get("state_code"))
    records = helpers.filter_equals(
        records, "status", validation.query_enum("status", REGISTRATION_STATUSES))
    items, total = helpers.page(records, limit, offset)
    return response.listing([serializers.registration(r) for r in items], total, limit, offset)


@bp.route("/share-classes/<share_class_id>/distributions", methods=["GET"])
def list_class_distributions(share_class_id):
    authenticate(ALL_ROLES)
    share_class = helpers.get_share_class(share_class_id)
    limit, offset = validation.pagination()
    records = [r for r in db.store.distributions.values()
               if r["share_class_id"] == share_class["id"]]
    records = helpers.filter_equals(
        records, "distribution_type", validation.query_enum("distribution_type", DISTRIBUTION_TYPES))
    records = helpers.filter_equals(
        records, "status", validation.query_enum("status", DISTRIBUTION_STATUSES))
    items, total = helpers.page(records, limit, offset)
    return response.listing([serializers.distribution(r) for r in items], total, limit, offset)
