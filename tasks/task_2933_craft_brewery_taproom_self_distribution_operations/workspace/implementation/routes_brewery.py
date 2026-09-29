"""Brewery singleton, brewer's notice and beer brand approvals."""

from decimal import Decimal

from flask import Blueprint

import calc
import cascades
import derive
import envelope
import helpers
import store
import validation
from errors import ApiError
from store import DB
from validation import ALL_ROLES, authenticate

bp = Blueprint("brewery", __name__)

REGISTRATION_STATES = ("DRAFT", "FORMULA_PENDING", "FORMULA_APPROVED", "FORMULA_EXEMPT")
LABEL_STATES = ("NO_LABEL", "COLA_PENDING", "COLA_APPROVED", "COLA_REVOKED")
NOTICE_ACTIONS = ("ACTIVATE", "SUSPEND", "REINSTATE", "REVOKE")
FILING_TYPES = ("FORMULA", "LABEL")
DECISIONS = ("APPROVED", "REJECTED", "REVOKED")
BEER_LABEL_KEYS = ("brand_name", "abv_statement", "net_contents", "health_warning")


# ---------------------------------------------------------------------------
# brewery
# ---------------------------------------------------------------------------

@bp.get("/brewery")
def read_brewery():
    authenticate(ALL_ROLES)
    row = helpers.brewery()
    return envelope.object_response(derive.serialize_brewery(row))


@bp.post("/brewery")
def create_brewery():
    authenticate(["BreweryAdmin"])
    payload = validation.body()
    legal_name = validation.field_string(payload, "legal_name", 1, 120)
    home_state_code = validation.field_state_code(payload, "home_state_code")
    notice_number = validation.field_string(payload, "ttb_brewers_notice_number", 1, 32)
    carry_in_taproom = validation.field_number(
        payload, "carry_in_taproom_bbl", 3, minimum=0, required=False, default=0)
    carry_in_distribution = validation.field_number(
        payload, "carry_in_distribution_bbl", 3, minimum=0, required=False, default=0)
    if DB["brewery"] is not None:
        raise ApiError("ERR_BREWERY_ALREADY_EXISTS")
    row = store.new_row({
        "legal_name": legal_name,
        "home_state_code": home_state_code,
        "ttb_brewers_notice_number": notice_number,
        "notice_status": "PENDING_NOTICE",
        "notice_effective_utc": None,
        "suspension_reason": None,
        "carry_in_taproom_bbl": calc.bbl(carry_in_taproom),
        "carry_in_distribution_bbl": calc.bbl(carry_in_distribution),
    })
    DB["brewery"] = row
    return envelope.object_response(derive.serialize_brewery(row), 201)


@bp.post("/brewery/notice")
def drive_notice():
    authenticate(["StateRegulator"])
    payload = validation.body()
    action = validation.field_enum(payload, "action", NOTICE_ACTIONS)
    row = helpers.brewery()
    status = row.get("notice_status")

    legal = {
        "ACTIVATE": ("PENDING_NOTICE",),
        "SUSPEND": ("ACTIVE",),
        "REINSTATE": ("SUSPENDED",),
        "REVOKE": ("SUSPENDED",),
    }
    if status not in legal[action]:
        raise ApiError("ERR_NOTICE_TRANSITION_INVALID")

    reason = None
    if action in ("SUSPEND", "REVOKE"):
        reason = validation.field_string(payload, "reason", 1, None)

    seen = set()
    if action == "ACTIVATE":
        row["notice_status"] = "ACTIVE"
        row["notice_effective_utc"] = helpers.now()
        row["suspension_reason"] = None
    elif action == "SUSPEND":
        row["notice_status"] = "SUSPENDED"
        row["suspension_reason"] = reason
        cascades.notice_suspended_cascade(seen)
    elif action == "REINSTATE":
        row["notice_status"] = "ACTIVE"
        row["notice_effective_utc"] = helpers.now()
        row["suspension_reason"] = None
        cascades.notice_reinstated_cascade(seen)
    else:
        row["notice_status"] = "REVOKED"
        row["suspension_reason"] = reason
        cascades.notice_revoked_cascade(seen)
    cascades.touch_once(row, seen)
    return envelope.object_response(derive.serialize_brewery(row))


@bp.post("/brewery/ytd-adjustments")
def brewery_ytd_adjustments():
    authenticate(["ComplianceOfficer"])
    payload = validation.body()
    taproom = _carry_in(payload, "carry_in_taproom_bbl", "taproom_bbl")
    distribution = _carry_in(payload, "carry_in_distribution_bbl", "distribution_bbl")
    row = helpers.brewery()
    row["carry_in_taproom_bbl"] = calc.bbl(taproom)
    row["carry_in_distribution_bbl"] = calc.bbl(distribution)
    store.touch(row)
    return envelope.object_response(derive.serialize_brewery(row))


def _carry_in(payload, primary, alias):
    if primary in payload and payload[primary] is not None:
        return validation.field_number(payload, primary, 3, minimum=0)
    if alias in payload and payload[alias] is not None:
        return validation.field_number(payload, alias, 3, minimum=0)
    validation.bad("Field '%s' is required." % primary)


# ---------------------------------------------------------------------------
# beers
# ---------------------------------------------------------------------------

@bp.get("/beers")
def list_beers():
    authenticate(ALL_ROLES)
    registration_state = validation.query_enum("registration_state", REGISTRATION_STATES)
    label_state = validation.query_enum("label_state", LABEL_STATES)

    def predicate(row):
        return (helpers.matches(row, "registration_state", registration_state)
                and helpers.matches(row, "label_state", label_state))

    rows, limit, offset, total = helpers.listing("beers", derive.serialize_beer, predicate)
    return envelope.list_response(rows, limit, offset, total)


@bp.get("/beers/<beer_id>")
def read_beer(beer_id):
    authenticate(ALL_ROLES)
    row = helpers.find("beers", beer_id)
    return envelope.object_response(derive.serialize_beer(row))


@bp.post("/beers")
def create_beer():
    authenticate(["BreweryAdmin", "ComplianceOfficer"])
    payload = validation.body()
    name = validation.field_string(payload, "name", 1, 80)
    style = validation.field_string(payload, "style", 1, 40)
    abv_pct = validation.field_number(payload, "abv_pct", 1,
                                      minimum=Decimal("0.5"), maximum=Decimal("20.0"))
    price = validation.field_int(payload, "price_per_bbl_cents", minimum=1)
    requires_formula = validation.field_bool(payload, "requires_formula",
                                             required=False, default=True)
    helpers.unique("beers", name)
    row = store.new_row({
        "name": name,
        "style": style,
        "abv_pct": abv_pct,
        "requires_formula": bool(requires_formula),
        "price_per_bbl_cents": price,
        "registration_state": "DRAFT" if requires_formula else "FORMULA_EXEMPT",
        "label_state": "NO_LABEL",
        "cola_id": None,
        "label_fields": None,
    })
    helpers.insert("beers", row)
    return envelope.object_response(derive.serialize_beer(row), 201)


@bp.post("/beers/<beer_id>/filings")
def create_filing(beer_id):
    authenticate(["ComplianceOfficer"])
    payload = validation.body()
    filing_type = validation.field_enum(payload, "filing_type", FILING_TYPES)
    beer = helpers.find("beers", beer_id)

    if filing_type == "FORMULA":
        if beer.get("registration_state") != "DRAFT" or not beer.get("requires_formula"):
            raise ApiError("ERR_FILING_TRANSITION_INVALID")
        ingredients = payload.get("ingredient_list")
        if ingredients is None:
            validation.bad("Field 'ingredient_list' is required for a FORMULA filing.")
        if isinstance(ingredients, str):
            if ingredients.strip() == "":
                validation.bad("Field 'ingredient_list' must not be empty.")
        elif isinstance(ingredients, (list, dict)):
            if len(ingredients) == 0:
                validation.bad("Field 'ingredient_list' must not be empty.")
        else:
            validation.bad("Field 'ingredient_list' must not be empty.")
        beer["registration_state"] = "FORMULA_PENDING"
    else:
        if beer.get("label_state") not in ("NO_LABEL", "COLA_REVOKED"):
            raise ApiError("ERR_FILING_TRANSITION_INVALID")
        label_fields = validation.field_object(payload, "label_fields")
        if not validation.non_blank_members(label_fields, BEER_LABEL_KEYS):
            validation.bad("Field 'label_fields' must carry non-blank %s."
                           % ", ".join(BEER_LABEL_KEYS))
        was_revoked = beer.get("label_state") == "COLA_REVOKED"
        beer["label_state"] = "COLA_PENDING"
        beer["label_fields"] = label_fields
        if was_revoked:
            beer["cola_id"] = None
    store.touch(beer)
    return envelope.object_response(derive.serialize_beer(beer))


@bp.post("/beers/<beer_id>/filings/<filing_type>/decision")
def decide_filing(beer_id, filing_type):
    authenticate(["StateRegulator"])
    payload = validation.body()
    decision = validation.field_enum(payload, "decision", DECISIONS)
    beer = helpers.find("beers", beer_id)
    if filing_type not in FILING_TYPES:
        validation.bad("Path parameter 'filingType' must be FORMULA or LABEL.")

    seen = set()
    if filing_type == "FORMULA":
        if decision == "APPROVED":
            if beer.get("registration_state") != "FORMULA_PENDING":
                raise ApiError("ERR_FILING_TRANSITION_INVALID")
            beer["registration_state"] = "FORMULA_APPROVED"
        elif decision == "REJECTED":
            if beer.get("registration_state") != "FORMULA_PENDING":
                raise ApiError("ERR_FILING_TRANSITION_INVALID")
            beer["registration_state"] = "DRAFT"
        else:
            raise ApiError("ERR_FILING_TRANSITION_INVALID")
    else:
        if decision == "APPROVED":
            if beer.get("label_state") != "COLA_PENDING":
                raise ApiError("ERR_FILING_TRANSITION_INVALID")
            cola_id = validation.field_string(payload, "cola_id", 1, None)
            beer["label_state"] = "COLA_APPROVED"
            beer["cola_id"] = cola_id
        elif decision == "REJECTED":
            if beer.get("label_state") != "COLA_PENDING":
                raise ApiError("ERR_FILING_TRANSITION_INVALID")
            beer["label_state"] = "NO_LABEL"
            beer["label_fields"] = None
        else:
            if beer.get("label_state") != "COLA_APPROVED":
                raise ApiError("ERR_FILING_TRANSITION_INVALID")
            beer["label_state"] = "COLA_REVOKED"
            cascades.cola_revoked_cascade(beer, seen)
    cascades.touch_once(beer, seen)
    return envelope.object_response(derive.serialize_beer(beer))
