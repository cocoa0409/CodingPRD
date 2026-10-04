"""Property risk profiles and premium quoting (PRD §3.8)."""
from decimal import Decimal

from flask import Blueprint, request

import db
from cascade import apply_classification
from errors import fail
from middleware import auth, require_role
from response import ok, ok_list
from scoring import (premium_amounts, EXPOSURE_CAP_CENTS, COVERAGE_VALUE_CAP_RATIO)
from util import (body, need, v_int, v_num, v_str, v_enum, v_range, v_date,
                  pagination_params, page_of, parse_date, dec)

bp = Blueprint("insurance", __name__)

CONSTRUCTION_TYPES = ("FRAME", "MASONRY", "NON_COMBUSTIBLE", "FIRE_RESISTIVE")


@bp.route("/ppc/property-risk-profiles", methods=["POST"])
def create_property():
    uid, role = auth()
    require_role(role, "EvaluationCoordinator")
    b = body()
    community_id = v_str(need(b, "community_id"), "community_id")
    community = db.find("communities", community_id)
    if community is None:
        fail("ERR_COMMUNITY_NOT_FOUND", "community does not exist")
    address = v_str(need(b, "address"), "address")
    dist_hydrant = v_range(v_int(need(b, "distance_to_nearest_hydrant_ft"), "distance_to_nearest_hydrant_ft"),
                           "distance_to_nearest_hydrant_ft", lo=0)
    dist_station = v_range(v_num(need(b, "distance_to_nearest_station_road_miles"),
                                 "distance_to_nearest_station_road_miles"),
                           "distance_to_nearest_station_road_miles", lo=0)
    construction = v_enum(need(b, "construction_type"), "construction_type", CONSTRUCTION_TYPES)
    insured = v_range(v_int(need(b, "insured_value_cents"), "insured_value_cents"),
                      "insured_value_cents", lo=0, lo_inclusive=False)

    prop = db.new_entity("properties", {
        "community_id": community_id,
        "address": address,
        "distance_to_nearest_hydrant_ft": dist_hydrant,
        "distance_to_nearest_station_road_miles": dist_station,
        "construction_type": construction,
        "insured_value_cents": insured,
        "applicable_class": None,
        "applicable_premium_modifier": None,
    })
    effective = db.effective_classification_of_community(community_id)
    if effective is not None:
        apply_classification(prop, effective)
    return ok(db.pub(prop), 201)


@bp.route("/ppc/property-risk-profiles", methods=["GET"])
def list_properties():
    auth()
    limit, offset = pagination_params()
    items = db.all_of("properties")
    v = request.args.get("community_id")
    if v is not None:
        items = [p for p in items if p["community_id"] == v]
    page, total = page_of(items, limit, offset)
    return ok_list([db.pub(p) for p in page], total, limit, offset)


@bp.route("/ppc/property-risk-profiles/<propertyId>", methods=["GET"])
def get_property(propertyId):
    auth()
    prop = db.find("properties", propertyId)
    if prop is None:
        fail("ERR_PROPERTY_NOT_FOUND", "property risk profile does not exist")
    return ok(db.pub(prop))


@bp.route("/ppc/premium-quotes", methods=["POST"])
def create_quote():
    uid, role = auth()
    require_role(role, "Insurer")
    b = body()
    property_id = v_str(need(b, "property_id"), "property_id")
    prop = db.find("properties", property_id)
    if prop is None:
        fail("ERR_PROPERTY_NOT_FOUND", "property risk profile does not exist")
    community = db.find("communities", prop["community_id"])
    effective = db.effective_classification_of_community(community["id"])
    if effective is None or prop["applicable_premium_modifier"] is None:
        fail("ERR_NO_EFFECTIVE_CLASSIFICATION",
             "community has no EFFECTIVE classification to rate against")

    start = v_date(need(b, "coverage_start_date"), "coverage_start_date")
    end = v_date(need(b, "coverage_end_date"), "coverage_end_date")
    if start < db.clock_date() or end < start:
        fail("ERR_COVERAGE_PERIOD_INVALID",
             "coverage start must not precede the clock date and end must not precede start")

    coverage = v_range(v_int(need(b, "coverage_amount_cents"), "coverage_amount_cents"),
                       "coverage_amount_cents", lo=0, lo_inclusive=False)
    base_rate = v_range(v_int(need(b, "base_rate_bp"), "base_rate_bp"),
                        "base_rate_bp", lo=0, lo_inclusive=False)
    term = v_range(v_int(need(b, "term_months"), "term_months"), "term_months", lo=1, hi=120)

    if dec(coverage) > COVERAGE_VALUE_CAP_RATIO * dec(prop["insured_value_cents"]):
        fail("ERR_COVERAGE_EXCEEDS_VALUE", "coverage exceeds 150% of insured value")

    provisional, _final = premium_amounts(coverage, base_rate,
                                          prop["applicable_premium_modifier"], term)
    quote = db.new_entity("quotes", {
        "property_id": property_id,
        "classification_id": effective["id"],
        "coverage_amount_cents": coverage,
        "base_rate_bp": base_rate,
        "term_months": term,
        "coverage_start_date": start.isoformat(),
        "coverage_end_date": end.isoformat(),
        "provisional_premium_cents": provisional,
        "final_premium_cents": None,
        "status": "QUOTED",
        "bound_by": None,
        "bound_at": None,
    })
    return ok(db.pub(quote), 201)


@bp.route("/ppc/premium-quotes", methods=["GET"])
def list_quotes():
    auth()
    limit, offset = pagination_params()
    items = db.all_of("quotes")
    for f in ("property_id", "classification_id", "status"):
        v = request.args.get(f)
        if v is not None:
            items = [q for q in items if str(q[f]) == v]
    page, total = page_of(items, limit, offset)
    return ok_list([db.pub(q) for q in page], total, limit, offset)


@bp.route("/ppc/premium-quotes/<quoteId>", methods=["GET"])
def get_quote(quoteId):
    auth()
    quote = db.find("quotes", quoteId)
    if quote is None:
        fail("ERR_QUOTE_NOT_FOUND", "premium quote does not exist")
    return ok(db.pub(quote))


@bp.route("/ppc/premium-quotes/<quoteId>/bind", methods=["POST"])
def bind_quote(quoteId):
    uid, role = auth()
    require_role(role, "Insurer")
    quote = db.find("quotes", quoteId)
    if quote is None:
        fail("ERR_QUOTE_NOT_FOUND", "premium quote does not exist")
    if quote["status"] != "QUOTED":
        fail("ERR_QUOTE_INVALID_STATE", "quote must be QUOTED to bind, not %s" % quote["status"])
    prop = db.find("properties", quote["property_id"])
    community = db.find("communities", prop["community_id"])
    b = body()
    expected = v_int(need(b, "expected_community_version"), "expected_community_version")
    if expected != community["version"]:
        fail("ERR_STALE_VERSION", "expected_community_version does not match the community's version")

    start = parse_date(quote["coverage_start_date"])
    end = parse_date(quote["coverage_end_date"])
    for other in db.all_of("quotes"):
        if other["property_id"] == quote["property_id"] and other["status"] == "BOUND" \
                and other["id"] != quote["id"]:
            o_start = parse_date(other["coverage_start_date"])
            o_end = parse_date(other["coverage_end_date"])
            if start <= o_end and end >= o_start:
                fail("ERR_QUOTE_COVERAGE_OVERLAP",
                     "closed-interval coverage collision with another BOUND quote")

    if community["bound_exposure_cents"] + quote["coverage_amount_cents"] > EXPOSURE_CAP_CENTS:
        fail("ERR_EXPOSURE_CAP_EXCEEDED", "bind would push bound exposure over the cap")

    _prov, final = premium_amounts(quote["coverage_amount_cents"], quote["base_rate_bp"],
                                   prop["applicable_premium_modifier"], quote["term_months"])
    quote["final_premium_cents"] = final
    quote["status"] = "BOUND"
    quote["bound_by"] = uid
    quote["bound_at"] = db.clock_iso()
    db.touch(quote)
    community["bound_exposure_cents"] += quote["coverage_amount_cents"]
    db.touch(community)
    return ok(db.pub(quote))


@bp.route("/ppc/premium-quotes/<quoteId>/void", methods=["POST"])
def void_quote(quoteId):
    uid, role = auth()
    require_role(role, "Insurer")
    quote = db.find("quotes", quoteId)
    if quote is None:
        fail("ERR_QUOTE_NOT_FOUND", "premium quote does not exist")
    if quote["status"] != "BOUND":
        fail("ERR_QUOTE_INVALID_STATE", "quote must be BOUND to void, not %s" % quote["status"])
    prop = db.find("properties", quote["property_id"])
    community = db.find("communities", prop["community_id"])
    quote["status"] = "VOIDED"
    db.touch(quote)
    community["bound_exposure_cents"] -= quote["coverage_amount_cents"]
    db.touch(community)
    return ok(db.pub(quote))
