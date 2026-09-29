"""Brand rate rules and network registrations."""

from decimal import Decimal

from flask import Blueprint

import auth
import calc
import cascades
import listing
import serialize
import validation as v
from auth import authorize
from envelope import created, ok
from errors import ApiError
from routes_programs import check_pinned_documentation_active
from store import db, add_days, base_row, touch
from validation import MISSING, as_decimal, as_enum, as_instant, as_int, as_string, field, parse_body

bp = Blueprint("rates", __name__)

BRANDS = ("VISA", "MASTERCARD", "DISCOVER", "AMEX")
PRODUCT_TIERS = ("ALL", "CONSUMER_CREDIT", "COMMERCIAL_CREDIT", "REWARDS_CREDIT")
REGISTRATION_STATES = ("SUBMITTED", "ACKNOWLEDGED", "EFFECTIVE", "REJECTED", "REVOKED")
LIVE_REGISTRATION_STATES = ("SUBMITTED", "ACKNOWLEDGED", "EFFECTIVE")
DECISIONS = ("ACKNOWLEDGE", "REJECT", "REVOKE")


def _whole_days(later, earlier):
    return int((later - earlier).total_seconds() // 86400)


def _gap_days(candidate_from, candidate_to, peer_from, peer_to):
    """Whole days between two closed intervals; overlapping intervals give zero."""
    if candidate_from > peer_to:
        return _whole_days(candidate_from, peer_to)
    if peer_from > candidate_to:
        return _whole_days(peer_from, candidate_to)
    return 0


@bp.post("/surcharge-programs/<program_id>/rate-rules")
def file_rate_rule(program_id):
    actor = authorize(["ComplianceOfficer"])
    program = auth.get_program(program_id)
    body, malformed = parse_body()
    if malformed:
        raise v.bad("The request body must be a JSON object.")
    v.require_present(body, ["brand", "product_tier", "rate_pct", "effective_from",
                            "effective_to", "expected_program_version"])
    brand = as_enum(body["brand"], "brand", BRANDS)
    product_tier = as_enum(body["product_tier"], "product_tier", PRODUCT_TIERS)
    rate_pct = as_decimal(body["rate_pct"], "rate_pct", minimum=Decimal(0), maximum=Decimal(100),
                          exclusive_min=True, max_decimals=4)
    effective_from = as_instant(body["effective_from"], "effective_from")
    effective_to = as_instant(body["effective_to"], "effective_to")
    if effective_to <= effective_from:
        raise v.bad("effective_to must be strictly after effective_from.")
    expected = as_int(body["expected_program_version"], "expected_program_version", 0)

    if expected != program["version"]:
        raise ApiError("ERR_STALE_PROGRAM_VERSION",
                       "expected_program_version %d does not match the program's current version %d."
                       % (expected, program["version"]))

    if program["status"] == "WITHDRAWN":
        raise ApiError("ERR_INVALID_PROGRAM_STATE",
                       "A WITHDRAWN program accepts no further rate rules.")

    check_pinned_documentation_active(program)

    # Step 26: window separation against same program, same brand, same tier.
    for peer in calc.program_rate_rules(program["id"]):
        if peer["brand"] != brand or peer["product_tier"] != product_tier:
            continue
        gap = _gap_days(effective_from, effective_to, peer["effective_from"], peer["effective_to"])
        if gap < calc.RATE_CHANGE_BUFFER_DAYS:
            raise ApiError("ERR_RATE_WINDOW_BUFFER_VIOLATION",
                           "Only %d whole days separate this rule from an existing rule of the same "
                           "brand and product tier; 30 are required." % gap)

    # Step 29: product-tier scope agreement in both directions.
    if program["consistency_scope"] == "BRAND_LEVEL" and product_tier != "ALL":
        raise ApiError("ERR_PRODUCT_TIER_SCOPE_VIOLATION",
                       "A BRAND_LEVEL program requires product_tier ALL.")
    if program["consistency_scope"] == "PRODUCT_LEVEL" and product_tier == "ALL":
        raise ApiError("ERR_PRODUCT_TIER_SCOPE_VIOLATION",
                       "A PRODUCT_LEVEL program requires a specific product tier.")

    # Step 36: the rate must sit at or under the program's cap.
    if rate_pct > Decimal(program["effective_cap_pct"]):
        raise ApiError("ERR_SURCHARGE_CAP_EXCEEDED",
                       "rate_pct exceeds the program's effective cap of %s." % program["effective_cap_pct"])

    row = base_row()
    row.update({
        "program_id": program["id"],
        "brand": brand,
        "product_tier": product_tier,
        "rate_pct": rate_pct,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "created_by_user_id": actor.user_id,
    })
    db.rate_rules[row["id"]] = row
    touch(program)
    return created(serialize.rate_rule(row))


@bp.get("/brand-rate-rules/<rule_id>")
def read_rate_rule(rule_id):
    authorize(auth.READ_ROLES)
    return ok(serialize.rate_rule(auth.get_rate_rule(rule_id)))


@bp.get("/brand-rate-rules")
def list_rate_rules():
    authorize(auth.READ_ROLES)
    rows = listing.filtered(list(db.rate_rules.values()), [
        (listing.arg("program_id"), "program_id"),
        (listing.enum_arg("brand", BRANDS), "brand"),
        (listing.enum_arg("product_tier", PRODUCT_TIERS), "product_tier"),
    ])
    return listing.list_response(rows, serialize.rate_rule)


# ------------------------------------------------------- network registrations
@bp.post("/surcharge-programs/<program_id>/network-registrations")
def submit_registration(program_id):
    authorize(["ComplianceOfficer"])
    program = auth.get_program(program_id)
    body, malformed = parse_body()
    if malformed:
        raise v.bad("The request body must be a JSON object.")
    v.require_present(body, ["network", "registration_ref"])
    network = as_enum(body["network"], "network", BRANDS)
    registration_ref = as_string(body["registration_ref"], "registration_ref", 1, 64)

    # Step 11: at most one live registration per network.
    for reg in calc.program_registrations(program["id"]):
        if reg["network"] == network and reg["state"] in LIVE_REGISTRATION_STATES:
            raise ApiError("ERR_DUPLICATE_NETWORK_REGISTRATION",
                           "This program already holds a live %s registration." % network)

    if program["program_type"] != "SURCHARGE" or program["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_PROGRAM_STATE",
                       "Only a SURCHARGE program in DRAFT may submit a network registration.")

    submitted_at = db.now()
    row = base_row()
    row.update({
        "program_id": program["id"],
        "network": network,
        "registration_ref": registration_ref,
        "submitted_at": submitted_at,
        "notice_days": calc.NOTICE_PERIOD_DAYS,
        "earliest_effective_at": add_days(submitted_at, calc.NOTICE_PERIOD_DAYS),
        "state": "SUBMITTED",
        "decided_by_user_id": None,
        "decision_note": None,
        "effective_at": None,
        "revoked_at": None,
    })
    db.registrations[row["id"]] = row

    program["status"] = "PENDING_REGISTRATION"
    touch(program)
    return created(serialize.registration(row))


@bp.get("/network-registrations/<registration_id>")
def read_registration(registration_id):
    authorize(auth.READ_ROLES)
    return ok(serialize.registration(auth.get_registration(registration_id)))


@bp.get("/network-registrations")
def list_registrations():
    authorize(auth.READ_ROLES)
    rows = listing.filtered(list(db.registrations.values()), [
        (listing.arg("program_id"), "program_id"),
        (listing.enum_arg("network", BRANDS), "network"),
        (listing.enum_arg("state", REGISTRATION_STATES), "state"),
    ])
    return listing.list_response(rows, serialize.registration)


@bp.post("/network-registrations/<registration_id>/decision")
def decide_registration(registration_id):
    actor = authorize(["NetworkAuditor"])
    reg = auth.get_registration(registration_id)
    body, malformed = parse_body()
    if malformed:
        raise v.bad("The request body must be a JSON object.")
    v.require_present(body, ["decision"])
    decision = as_enum(body["decision"], "decision", DECISIONS)
    note_raw = field(body, "decision_note")
    note = None
    if note_raw is not MISSING and note_raw is not None:
        note = as_string(note_raw, "decision_note", 1, 1000)

    if decision in ("ACKNOWLEDGE", "REJECT"):
        if reg["state"] != "SUBMITTED":
            raise ApiError("ERR_INVALID_REGISTRATION_STATE",
                           "Only a SUBMITTED registration can be %sd." % decision.lower())
    else:
        if reg["state"] != "EFFECTIVE":
            raise ApiError("ERR_INVALID_REGISTRATION_STATE",
                           "Only an EFFECTIVE registration can be revoked.")

    reg["decided_by_user_id"] = actor.user_id
    reg["decision_note"] = note
    if decision == "ACKNOWLEDGE":
        reg["state"] = "ACKNOWLEDGED"
    elif decision == "REJECT":
        # The owning program deliberately does not move.
        reg["state"] = "REJECTED"
    else:
        reg["state"] = "REVOKED"
        reg["revoked_at"] = db.now()
    touch(reg)

    if decision == "REVOKE":
        program = db.programs.get(reg["program_id"])
        if program is not None and program["status"] == "ACTIVE":
            cascades.suspend_program(program, "REGISTRATION_REVOKED", "PROGRAM_SUSPENDED")

    return ok(serialize.registration(reg))


@bp.post("/network-registrations/<registration_id>/effectuate")
def effectuate_registration(registration_id):
    authorize(["ComplianceOfficer"])
    reg = auth.get_registration(registration_id)
    body, malformed = parse_body()
    if malformed:
        raise v.bad("The request body must be a JSON object.")

    if reg["state"] != "ACKNOWLEDGED":
        raise ApiError("ERR_INVALID_REGISTRATION_STATE",
                       "Only an ACKNOWLEDGED registration can be effectuated.")

    # Step 28: the notice bound is inclusive.
    if db.now() < reg["earliest_effective_at"]:
        raise ApiError("ERR_NOTICE_PERIOD_NOT_ELAPSED",
                       "The 30-day notice period has not elapsed for this registration.")

    reg["state"] = "EFFECTIVE"
    reg["effective_at"] = db.now()
    touch(reg)
    return ok(serialize.registration(reg))
