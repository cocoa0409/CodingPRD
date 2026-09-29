"""Territories, comparable titles, buyers and territory valuations."""
from __future__ import annotations

import re
from decimal import Decimal

from flask import Blueprint, request

import calc
from envelope import created, ok, ok_list
from errors import ApiError
from serializers import buyer_out, comparable_out, territory_out, valuation_out
from store import (
    base_row,
    buyers_of_territory,
    comparables_of_territory,
    db,
    get_buyer,
    get_film,
    get_territory,
    get_valuation,
    now,
    touch,
    valuations_of_film,
)
from util import ZERO2, q2
from validation import actor, body, page, raw_id, require_roles

bp = Blueprint("territories", __name__)

REGIONS = ("EMEA", "APAC", "LATAM", "NORTH_AMERICA")
GENRES = ("ACTION", "DRAMA", "COMEDY", "THRILLER", "DOCUMENTARY")
CREDIT_RATINGS = ("AAA", "AA", "A", "BBB", "SPECULATIVE")
BUYER_STATUSES = ("ACTIVE", "WATCHLIST", "BLOCKED")
VALUATION_METHODS = ("COMPARABLE_WEIGHTED", "CAST_ADJUSTED")

CODE_RE = re.compile(r"^[A-Z]{2,3}$")

READ_ROLES = (
    "SalesAgent",
    "HeadOfSales",
    "DeliveryManager",
    "CollectionAgent",
    "Lender",
    "PlatformAdmin",
)
VALUATION_READ_ROLES = (
    "SalesAgent",
    "HeadOfSales",
    "CollectionAgent",
    "Lender",
    "PlatformAdmin",
)


# ---------------------------------------------------------------- territories


@bp.post("/territories")
@require_roles("PlatformAdmin")
def create_territory():
    payload = body()
    code = payload.req_string("code")
    if not CODE_RE.match(code):
        raise ApiError(
            "ERR_INVALID_REQUEST", "Field 'code' must be 2-3 uppercase letters."
        )
    name = payload.req_string("name")
    region = payload.req_enum("region", REGIONS)
    market_tier = payload.req_int("market_tier", 1, 3)
    currency_code = payload.req_string("currency_code")
    base_value_index = payload.req_number(
        "base_value_index", minimum=Decimal("0.10"), maximum=Decimal("2.00")
    )
    for existing in db.territories.values():
        if existing["code"] == code:
            raise ApiError("ERR_TERRITORY_CODE_TAKEN")
    row = base_row(versioned=False)
    row.update(
        {
            "code": code,
            "name": name,
            "region": region,
            "market_tier": market_tier,
            "currency_code": currency_code,
            "base_value_index": base_value_index,
        }
    )
    db.territories[row["id"]] = row
    return created(territory_out(row))


@bp.get("/territories")
@require_roles(*READ_ROLES)
def list_territories():
    rows = list(db.territories.values())
    region = request.args.get("region")
    market_tier = request.args.get("market_tier")
    if region:
        rows = [r for r in rows if r["region"] == region]
    if market_tier:
        rows = [r for r in rows if str(r["market_tier"]) == str(market_tier)]
    rows.sort(key=lambda r: r["code"])
    items, meta = page(rows, territory_out)
    return ok_list(items, meta)


@bp.get("/territories/<territory_id>")
@require_roles(*READ_ROLES)
def read_territory(territory_id):
    return ok(territory_out(get_territory(territory_id)))


# ------------------------------------------------------------ comparables


@bp.post("/territories/<territory_id>/comparable-titles")
@require_roles("PlatformAdmin", "SalesAgent")
def create_comparable(territory_id):
    territory = get_territory(territory_id)
    payload = body()
    row = base_row(versioned=False)
    row.update(
        {
            "territory_id": territory["id"],
            "name": payload.req_string("name"),
            "genre": payload.req_enum("genre", GENRES),
            "cast_score": payload.req_int("cast_score", 0, 100),
            "gross_license_fee_usd": q2(payload.req_number("gross_license_fee_usd")),
            "release_year": payload.req_int("release_year"),
            "verified": payload.opt_bool("verified", False),
        }
    )
    db.comparables[row["id"]] = row
    return created(comparable_out(row))


@bp.get("/territories/<territory_id>/comparable-titles")
@require_roles("SalesAgent", "HeadOfSales", "PlatformAdmin")
def list_comparables(territory_id):
    territory = get_territory(territory_id)
    items, meta = page(comparables_of_territory(territory["id"]), comparable_out)
    return ok_list(items, meta)


# ------------------------------------------------------------------- buyers


@bp.post("/territories/<territory_id>/buyers")
@require_roles("PlatformAdmin")
def create_buyer(territory_id):
    territory = get_territory(territory_id)
    payload = body()
    row = base_row()
    row.update(
        {
            "territory_id": territory["id"],
            "company_name": payload.req_string("company_name"),
            "credit_rating": payload.req_enum("credit_rating", CREDIT_RATINGS),
            "exposure_limit_usd": q2(payload.req_number("exposure_limit_usd")),
            "status": payload.opt_enum("status", BUYER_STATUSES, "ACTIVE"),
        }
    )
    db.buyers[row["id"]] = row
    return created(buyer_out(row))


@bp.get("/territories/<territory_id>/buyers")
@require_roles(*READ_ROLES)
def list_buyers(territory_id):
    territory = get_territory(territory_id)
    items, meta = page(buyers_of_territory(territory["id"]), buyer_out)
    return ok_list(items, meta)


@bp.get("/buyers/<buyer_id>")
@require_roles(*READ_ROLES, "Buyer")
def read_buyer(buyer_id):
    return ok(buyer_out(get_buyer(buyer_id)))


@bp.patch("/buyers/<buyer_id>")
@require_roles("PlatformAdmin")
def patch_buyer(buyer_id):
    buyer = get_buyer(buyer_id)
    payload = body()
    status = payload.opt_enum("status", BUYER_STATUSES)
    credit_rating = payload.opt_enum("credit_rating", CREDIT_RATINGS)
    exposure_limit = payload.opt_number("exposure_limit_usd")
    if status is not None:
        buyer["status"] = status
    if credit_rating is not None:
        buyer["credit_rating"] = credit_rating
    if exposure_limit is not None:
        buyer["exposure_limit_usd"] = q2(exposure_limit)
    touch(buyer)
    calc.refresh_facilities_for_buyer(buyer["id"])
    return ok(buyer_out(buyer))


# -------------------------------------------------------------- valuations


@bp.post("/territory-valuations")
@require_roles("SalesAgent", "HeadOfSales")
def create_valuation():
    film_ref = raw_id("film_id")
    film = get_film(film_ref) if film_ref is not None else None
    territory_ref = raw_id("territory_id")
    territory = get_territory(territory_ref) if territory_ref is not None else None
    payload = body()
    payload.req_id("film_id")
    payload.req_id("territory_id")
    method = payload.req_enum("method", VALUATION_METHODS)
    if film is None:
        raise ApiError("ERR_FILM_NOT_FOUND")
    if territory is None:
        raise ApiError("ERR_TERRITORY_NOT_FOUND")

    sample = calc.comparable_sample(film, territory["id"])
    if len(sample) == 0:
        raise ApiError("ERR_NO_COMPARABLE_TITLES")
    if len(sample) < calc.MIN_COMP_SAMPLE:
        raise ApiError("ERR_INSUFFICIENT_COMP_SAMPLE")

    figures = calc.valuation_figures(film, territory, method, sample)
    row = base_row()
    row.update(
        {
            "film_id": film["id"],
            "territory_id": territory["id"],
            "method": method,
            "status": "DRAFT",
            "published_by_user_id": None,
            "published_at": None,
        }
    )
    row.update(figures)
    db.valuations[row["id"]] = row
    return created(valuation_out(row))


@bp.get("/territory-valuations")
@require_roles(*VALUATION_READ_ROLES)
def list_valuations():
    from store import by_creation

    rows = by_creation(list(db.valuations.values()))
    for key in ("film_id", "territory_id", "status", "method"):
        value = request.args.get(key)
        if value:
            rows = [r for r in rows if r[key] == value]
    items, meta = page(rows, valuation_out)
    return ok_list(items, meta)


@bp.get("/territory-valuations/<valuation_id>")
@require_roles(*VALUATION_READ_ROLES)
def read_valuation(valuation_id):
    return ok(valuation_out(get_valuation(valuation_id)))


@bp.post("/territory-valuations/<valuation_id>/publish")
@require_roles("HeadOfSales")
def publish_valuation(valuation_id):
    valuation = get_valuation(valuation_id)
    payload = body()
    expected = payload.req_int("expected_film_version")
    film = get_film(valuation["film_id"])
    if expected != film["version"]:
        raise ApiError("ERR_STALE_FILM_VERSION")
    if valuation["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE")
    if calc.agreement_in_force(film["id"]) is None:
        raise ApiError("ERR_AGENCY_AGREEMENT_NOT_IN_FORCE")
    if valuation["comp_sample_size"] < calc.MIN_COMP_SAMPLE:
        raise ApiError("ERR_INSUFFICIENT_COMP_SAMPLE")

    for other in valuations_of_film(film["id"]):
        if (
            other["id"] != valuation["id"]
            and other["territory_id"] == valuation["territory_id"]
            and other["status"] == "PUBLISHED"
        ):
            other["status"] = "STALE"
            touch(other)
    valuation["status"] = "PUBLISHED"
    valuation["published_by_user_id"] = actor()
    valuation["published_at"] = now()
    touch(valuation)
    touch(film)
    return ok(valuation_out(valuation))
