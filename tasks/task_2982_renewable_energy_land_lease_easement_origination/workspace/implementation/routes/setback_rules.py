"""Jurisdictional setback ordinances (PRD section 3.3, first half)."""

from flask import Blueprint

import access
import cascades
import serializers as ser
import validation as v
from auth import LAND_AGENT, PORTFOLIO_MANAGER, TITLE_COUNSEL, require
from envelope import ok, ok_list
from store import db, insert, ordered

bp = Blueprint("setback_rules", __name__, url_prefix="/land-origination")

RULE_TYPES = ("PROPERTY_LINE", "OCCUPIED_DWELLING", "PUBLIC_ROAD", "WETLAND")
READERS = (LAND_AGENT, TITLE_COUNSEL, PORTFOLIO_MANAGER)


@bp.get("/setback-rules/<rule_id>")
@require(*READERS)
def get_rule(rule_id):
    return ok(ser.setback_rule(access.setback_rule(rule_id)))


@bp.get("/setback-rules")
@require(*READERS)
def list_rules():
    limit, offset = v.pagination()
    rows = ordered(db.setback_rules.values())
    rows = v.apply_filters(rows, [
        ("jurisdiction_code", v.query_str("jurisdiction_code")),
        ("rule_type", v.query_str("rule_type")),
    ])
    page, total = v.paginate(rows, limit, offset)
    return ok_list(ser.many(ser.setback_rule, page), limit, offset, total)


@bp.post("/setback-rules")
@require(TITLE_COUNSEL)
def create_rule():
    body = v.json_body()
    jurisdiction = v.req_str(body, "jurisdiction_code", min_len=5, max_len=5,
                             pattern=r"^\d{5}$")
    rule_type = v.req_enum(body, "rule_type", RULE_TYPES)
    setback_feet = v.req_int(body, "setback_feet", lo=0)
    rate = v.req_num(body, "encumbrance_rate_per_acre", lo=0, hi=1)
    waivable = v.req_bool(body, "consent_waivable")

    row = insert("setback_rules", {
        "jurisdiction_code": jurisdiction,
        "rule_type": rule_type,
        "setback_feet": setback_feet,
        "encumbrance_rate_per_acre": rate,
        "consent_waivable": waivable,
    })

    # Publishing retroactively re-derives every parcel in the jurisdiction,
    # in created_at ASC order, through the whole four-procedure chain.
    for parcel in ordered([p for p in db.parcels.values()
                           if p["county_fips"] == jurisdiction]):
        cascades.run_parcel_chain(parcel)
    return ok(ser.setback_rule(row), 201)
