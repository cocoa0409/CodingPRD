"""The immutable award tier ladder (PRD 3.1)."""

from flask import Blueprint

import serialize
from auth import ALL_ROLES, authorize
from envelope import created, ok, paginate
from errors import fail
from gates import filtered, lookup
from schema import body, f_enum, f_id, f_int, f_str, raw_fk, validate
from store import db

bp = Blueprint("award_tiers", __name__)

CABINS = ("ECONOMY", "PREMIUM_ECONOMY", "BUSINESS")


@bp.post("/award-tiers")
def create_tier():
    authorize("ProgramDirector")
    payload = body()

    program_id = raw_fk(payload, "program_id")
    if program_id is not None:
        lookup("program", program_id)

    data = validate(payload, [
        f_id("program_id"),
        f_str("tier_code", max_len=40),
        f_int("tier_rank", minimum=1),
        f_int("qualification_threshold", minimum=0),
        f_int("budget_per_qualifier_cents", minimum=0),
        f_int("guest_allowance", required=False, default=0, minimum=0, maximum=2),
        f_enum("air_cabin_class", CABINS),
        f_int("upgrade_allowance_cents", required=False, default=0, minimum=0),
        f_int("service_load_bp", required=False, default=0, minimum=0, maximum=5000),
    ])
    lookup("program", data["program_id"])

    for tier in db.award_tiers.values():
        if tier["program_id"] != data["program_id"]:
            continue
        if tier["tier_code"] == data["tier_code"] or tier["tier_rank"] == data["tier_rank"]:
            fail("ERR_DUPLICATE_TIER_KEY")

    row = {
        "program_id": data["program_id"],
        "tier_code": data["tier_code"],
        "tier_rank": data["tier_rank"],
        "qualification_threshold": data["qualification_threshold"],
        "budget_per_qualifier_cents": data["budget_per_qualifier_cents"],
        "guest_allowance": data["guest_allowance"],
        "air_cabin_class": data["air_cabin_class"],
        "upgrade_allowance_cents": data["upgrade_allowance_cents"],
        "service_load_bp": data["service_load_bp"],
    }
    db.stamp_new(row, versioned=False)
    db.award_tiers[row["id"]] = row
    return created(serialize.award_tier(row))


@bp.get("/award-tiers/<tier_id>")
def read_tier(tier_id):
    authorize(*ALL_ROLES)
    return ok(serialize.award_tier(lookup("tier", tier_id)))


@bp.get("/award-tiers")
def list_tiers():
    authorize(*ALL_ROLES)
    rows = filtered(db.ordered(db.award_tiers),
                    [("program_id", "program_id"), ("tier_code", "tier_code")])
    return paginate(rows, serialize.award_tier)
