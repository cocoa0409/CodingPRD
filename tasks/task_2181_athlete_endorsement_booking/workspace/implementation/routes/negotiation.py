"""Opportunity intake, brand-fit screening and the term-sheet negotiation."""

import datetime as _dt

from flask import Blueprint, request

import calc
import domain
import validation as V
from auth import ALL_ROLES, require
from envelope import created, ok, paginated, read_pagination
from errors import ApiError
from store import db, fmt_date, fmt_dt, new_record, now, stamp, touch
from validation import parse_date, parse_datetime

bp = Blueprint("negotiation", __name__)


def _opportunity_of(sheet):
    return db.opportunities.get(sheet["opportunity_id"])


def _athlete_of_opportunity(opportunity):
    return db.athletes.get(opportunity["athlete_id"])


def _provisional(sheet, athlete):
    return calc.fee_engine(
        sheet["fee_cents"], sheet["usage_rights_tier"], sheet["morals_clause_tier"],
        sheet["territory"], athlete["base_appearance_rate_cents"],
        sheet["exclusivity_months"], 0,
    )


# ----------------------------------------------------------- opportunities
@bp.post("/opportunities")
def create_opportunity():
    caller = require("BrandRep")
    payload = V.body()
    athlete_id = V.id_field(payload, "athlete_id")
    brand_id = V.id_field(payload, "brand_id")
    start_raw, start_date = V.date_field(payload, "requested_start_date")
    end_raw, end_date = V.date_field(payload, "requested_end_date")
    if end_date < start_date:
        V.bad("requested_end_date must be on or after requested_start_date")
    proposed_fee_cents = V.int_field(payload, "proposed_fee_cents", minimum=0)
    planned_posts = V.int_field(payload, "planned_posts", minimum=0)
    planned_appearances = V.int_field(payload, "planned_appearances", minimum=0)
    planned_shoots = V.int_field(payload, "planned_shoots", minimum=0)
    exclusivity_category = V.enum_field(payload, "exclusivity_category", calc.CATEGORIES)
    exclusivity_months = V.int_field(payload, "exclusivity_months", minimum=0, maximum=36)
    territory = V.enum_field(payload, "territory", calc.TERRITORIES)
    usage_rights_tier = V.enum_field(payload, "usage_rights_tier", calc.USAGE_TIERS)

    domain.must_get("athletes", athlete_id)
    domain.must_get("brands", brand_id)

    if caller.user_id != brand_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "brand_id must equal X-User-ID")

    opportunity = new_record({
        "brand_id": brand_id,
        "athlete_id": athlete_id,
        "requested_start_date": start_raw,
        "requested_end_date": end_raw,
        "proposed_fee_cents": proposed_fee_cents,
        "planned_posts": planned_posts,
        "planned_appearances": planned_appearances,
        "planned_shoots": planned_shoots,
        "exclusivity_category": exclusivity_category,
        "exclusivity_months": exclusivity_months,
        "territory": territory,
        "usage_rights_tier": usage_rights_tier,
        "status": "INTAKE",
        "expected_fee_cents": None,
        "brand_fit_score": None,
        "screened_by_user_id": None,
        "screened_at": None,
    })
    db.opportunities[opportunity["id"]] = opportunity
    return created(opportunity)


@bp.get("/opportunities/<opportunity_id>")
def get_opportunity(opportunity_id):
    require(ALL_ROLES)
    return ok(domain.must_get("opportunities", opportunity_id))


@bp.get("/opportunities")
def list_opportunities():
    require(ALL_ROLES)
    limit, offset = read_pagination()
    rows = list(db.opportunities.values())
    for field in ("athlete_id", "brand_id", "status"):
        value = request.args.get(field)
        if value:
            rows = [r for r in rows if r[field] == value]
    return paginated(rows, limit, offset)


@bp.post("/opportunities/<opportunity_id>/screen")
def screen_opportunity(opportunity_id):
    caller = require("ComplianceOfficer")
    opportunity = domain.must_get("opportunities", opportunity_id)
    if opportunity["status"] != "INTAKE":
        raise ApiError("ERR_OPPORTUNITY_NOT_SCREENED", "opportunity is not in INTAKE")

    athlete = db.athletes[opportunity["athlete_id"]]
    brand = db.brands[opportunity["brand_id"]]
    expected_fee_cents, score = calc.brand_fit(opportunity, athlete, brand)

    opportunity["expected_fee_cents"] = expected_fee_cents
    opportunity["brand_fit_score"] = score
    opportunity["screened_by_user_id"] = caller.user_id
    opportunity["screened_at"] = stamp()
    opportunity["status"] = "SCREENED" if score >= calc.FIT_PASS_SCORE else "REJECTED_FIT"
    touch(opportunity)
    return ok(opportunity)


# ------------------------------------------------------------- term sheets
@bp.post("/term-sheets")
def create_term_sheet():
    require("TalentAgent")
    payload = V.body()
    opportunity_id = V.id_field(payload, "opportunity_id")
    fee_cents = V.int_field(payload, "fee_cents", minimum=1)
    usage_rights_tier = V.enum_field(payload, "usage_rights_tier", calc.USAGE_TIERS)
    usage_term_months = V.int_field(payload, "usage_term_months", minimum=1, maximum=60)
    territory = V.enum_field(payload, "territory", calc.TERRITORIES)
    morals_clause_tier = V.enum_field(payload, "morals_clause_tier", calc.MORALS_TIERS)
    exclusivity_months = V.int_field(payload, "exclusivity_months", minimum=0, maximum=36)
    appearance_days = V.int_field(payload, "appearance_days", minimum=0)

    opportunity = domain.must_get("opportunities", opportunity_id)
    if opportunity["status"] != "SCREENED":
        raise ApiError("ERR_OPPORTUNITY_NOT_SCREENED", "opportunity is not SCREENED")

    sheet = new_record({
        "opportunity_id": opportunity_id,
        "round_number": 1,
        "counter_count": 0,
        "fee_cents": fee_cents,
        "usage_rights_tier": usage_rights_tier,
        "usage_term_months": usage_term_months,
        "territory": territory,
        "morals_clause_tier": morals_clause_tier,
        "exclusivity_category": opportunity["exclusivity_category"],
        "exclusivity_months": exclusivity_months,
        "appearance_days": appearance_days,
        "provisional_fee_cents": None,
        "offer_expires_at": None,
        "last_counter_morals_tier": None,
        "status": "DRAFT",
    })
    db.term_sheets[sheet["id"]] = sheet
    return created(sheet)


@bp.get("/term-sheets/<sheet_id>")
def get_term_sheet(sheet_id):
    require(ALL_ROLES)
    return ok(domain.must_get("term_sheets", sheet_id))


@bp.get("/term-sheets")
def list_term_sheets():
    require(ALL_ROLES)
    limit, offset = read_pagination()
    rows = list(db.term_sheets.values())
    for field in ("opportunity_id", "status"):
        value = request.args.get(field)
        if value:
            rows = [r for r in rows if r[field] == value]
    return paginated(rows, limit, offset)


@bp.post("/term-sheets/<sheet_id>/submit")
def submit_term_sheet(sheet_id):
    require("TalentAgent")
    sheet = domain.must_get("term_sheets", sheet_id)
    opportunity = _opportunity_of(sheet)
    athlete = _athlete_of_opportunity(opportunity)

    if athlete["status"] != "ACTIVE":
        raise ApiError("ERR_ATHLETE_NOT_BOOKABLE", "athlete is not ACTIVE on the roster")
    if sheet["status"] != "DRAFT":
        raise ApiError("ERR_TERM_SHEET_INVALID_STATE", "term sheet is not DRAFT")

    sheet["status"] = "SUBMITTED"
    sheet["provisional_fee_cents"] = _provisional(sheet, athlete)
    sheet["offer_expires_at"] = fmt_dt(now() + _dt.timedelta(days=calc.OFFER_VALID_DAYS))
    touch(sheet)
    return ok(sheet)


@bp.post("/term-sheets/<sheet_id>/counter")
def counter_term_sheet(sheet_id):
    caller = require("BrandRep")
    sheet = domain.must_get("term_sheets", sheet_id)
    payload = V.body()
    counter_fee_cents = V.int_field(payload, "counter_fee_cents", minimum=1)
    counter_usage = V.enum_field(payload, "counter_usage_rights_tier", calc.USAGE_TIERS)
    counter_morals = V.enum_field(payload, "counter_morals_clause_tier", calc.MORALS_TIERS)
    counter_months = V.int_field(payload, "counter_exclusivity_months", minimum=0, maximum=36)
    V.str_field(payload, "note", required=False)

    opportunity = _opportunity_of(sheet)
    if caller.user_id != opportunity["brand_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "caller is not the brand behind this paper")

    if sheet["status"] != "SUBMITTED":
        raise ApiError("ERR_TERM_SHEET_INVALID_STATE", "term sheet is not SUBMITTED")
    if sheet["counter_count"] >= calc.MAX_COUNTER_ROUNDS:
        raise ApiError("ERR_COUNTER_LIMIT_EXCEEDED", "counter limit reached")

    sheet["fee_cents"] = counter_fee_cents
    sheet["usage_rights_tier"] = counter_usage
    sheet["morals_clause_tier"] = counter_morals
    sheet["exclusivity_months"] = counter_months
    sheet["counter_count"] += 1
    sheet["last_counter_morals_tier"] = counter_morals
    sheet["status"] = "COUNTERED"
    touch(sheet)
    return ok(sheet)


@bp.post("/term-sheets/<sheet_id>/revise")
def revise_term_sheet(sheet_id):
    require("TalentAgent")
    sheet = domain.must_get("term_sheets", sheet_id)
    payload = V.body()
    fee_cents = V.int_field(payload, "fee_cents", minimum=1)
    usage_rights_tier = V.enum_field(payload, "usage_rights_tier", calc.USAGE_TIERS)
    usage_term_months = V.int_field(payload, "usage_term_months", minimum=1, maximum=60)
    morals_clause_tier = V.enum_field(payload, "morals_clause_tier", calc.MORALS_TIERS)
    exclusivity_months = V.int_field(payload, "exclusivity_months", minimum=0, maximum=36)
    appearance_days = V.int_field(payload, "appearance_days", minimum=0)

    opportunity = _opportunity_of(sheet)
    athlete = _athlete_of_opportunity(opportunity)

    if athlete["status"] != "ACTIVE":
        raise ApiError("ERR_ATHLETE_NOT_BOOKABLE", "athlete is not ACTIVE on the roster")
    if sheet["status"] != "COUNTERED":
        raise ApiError("ERR_TERM_SHEET_INVALID_STATE", "term sheet is not COUNTERED")

    demanded = sheet.get("last_counter_morals_tier")
    if demanded is not None:
        if calc.MORALS_STRICTNESS[morals_clause_tier] < calc.MORALS_STRICTNESS[demanded]:
            raise ApiError("ERR_MORALS_TIER_DOWNGRADE_FORBIDDEN",
                           "morals clause may not be loosened below the last counter")

    sheet["fee_cents"] = fee_cents
    sheet["usage_rights_tier"] = usage_rights_tier
    sheet["usage_term_months"] = usage_term_months
    sheet["morals_clause_tier"] = morals_clause_tier
    sheet["exclusivity_months"] = exclusivity_months
    sheet["appearance_days"] = appearance_days
    sheet["round_number"] += 1
    sheet["status"] = "SUBMITTED"
    sheet["provisional_fee_cents"] = _provisional(sheet, athlete)
    sheet["offer_expires_at"] = fmt_dt(now() + _dt.timedelta(days=calc.OFFER_VALID_DAYS))
    touch(sheet)
    return ok(sheet)


@bp.post("/term-sheets/<sheet_id>/withdraw")
def withdraw_term_sheet(sheet_id):
    require("TalentAgent")
    sheet = domain.must_get("term_sheets", sheet_id)
    payload = V.body()
    V.str_field(payload, "reason", required=False)

    if sheet["status"] not in ("DRAFT", "SUBMITTED", "COUNTERED"):
        raise ApiError("ERR_TERM_SHEET_INVALID_STATE", "term sheet is already terminal")

    sheet["status"] = "WITHDRAWN"
    touch(sheet)

    opportunity = _opportunity_of(sheet)
    if opportunity is not None and opportunity["status"] == "SCREENED":
        live = [s for s in db.term_sheets.values()
                if s["opportunity_id"] == opportunity["id"]
                and s["status"] in ("DRAFT", "SUBMITTED", "COUNTERED")]
        if not live:
            opportunity["status"] = "CLOSED_LOST"
            touch(opportunity)
    return ok(sheet)


@bp.post("/term-sheets/<sheet_id>/accept")
def accept_term_sheet(sheet_id):
    caller = require("BrandRep")
    sheet = domain.must_get("term_sheets", sheet_id)
    opportunity = _opportunity_of(sheet)
    athlete = _athlete_of_opportunity(opportunity)
    brand = db.brands.get(opportunity["brand_id"])

    if caller.user_id != opportunity["brand_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "caller is not the brand behind this paper")

    if sheet["status"] != "SUBMITTED":
        raise ApiError("ERR_TERM_SHEET_INVALID_STATE", "term sheet is not SUBMITTED")

    expires_at = parse_datetime(sheet["offer_expires_at"], "offer_expires_at") \
        if sheet.get("offer_expires_at") else None
    if expires_at is not None and now() > expires_at:
        sheet["status"] = "EXPIRED"
        touch(sheet)
        raise ApiError("ERR_OFFER_EXPIRED", "the offer expired before acceptance")

    if brand is not None and brand.get("sanctioned"):
        raise ApiError("ERR_BRAND_SANCTIONED", "the brand is sanctioned")

    term_start = parse_date(opportunity["requested_start_date"], "requested_start_date")
    term_end = parse_date(opportunity["requested_end_date"], "requested_end_date")
    grant_start = term_start
    grant_end = calc.grant_end_date(term_start, sheet["exclusivity_months"])

    if domain.exclusivity_conflict(athlete["id"], sheet["exclusivity_category"],
                                   grant_start, grant_end):
        raise ApiError("ERR_EXCLUSIVITY_CONFLICT", "the category slot is already occupied")

    if sheet["fee_cents"] > athlete["base_appearance_rate_cents"] * calc.FEE_CAP_MULTIPLE:
        raise ApiError("ERR_FEE_CAP_EXCEEDED", "the negotiated fee exceeds the fee cap")

    engagement = new_record({
        "term_sheet_id": sheet["id"],
        "opportunity_id": opportunity["id"],
        "athlete_id": athlete["id"],
        "brand_id": opportunity["brand_id"],
        "contract_status": "PENDING_COUNTERSIGN",
        "settlement_status": "UNBILLED",
        "base_fee_cents": sheet["fee_cents"],
        "usage_rights_tier": sheet["usage_rights_tier"],
        "morals_clause_tier": sheet["morals_clause_tier"],
        "territory": sheet["territory"],
        "exclusivity_category": sheet["exclusivity_category"],
        "exclusivity_months": sheet["exclusivity_months"],
        "term_start_date": opportunity["requested_start_date"],
        "term_end_date": opportunity["requested_end_date"],
        "provisional_fee_cents": sheet["provisional_fee_cents"],
        "binding_fee_cents": None,
        "accrued_fee_cents": 0,
        "gross_settled_cents": 0,
        "required_deliverable_count": (opportunity["planned_posts"]
                                       + opportunity["planned_appearances"]
                                       + opportunity["planned_shoots"]),
        "approved_deliverable_count": 0,
        "appearance_days_committed": sheet["appearance_days"],
        "countersigned_by_user_id": None,
        "countersigned_at": None,
        "terminated_reason_code": None,
    })
    db.engagements[engagement["id"]] = engagement

    grant = new_record({
        "athlete_id": athlete["id"],
        "engagement_id": engagement["id"],
        "category": sheet["exclusivity_category"],
        "start_date": fmt_date(grant_start),
        "end_date": fmt_date(grant_end),
        "status": "PENDING",
        "released_at": None,
    })
    db.exclusivity_grants[grant["id"]] = grant

    sheet["status"] = "ACCEPTED"
    touch(sheet)

    opportunity["status"] = "CONTRACTED"
    touch(opportunity)

    for sibling in db.term_sheets.values():
        if sibling["id"] == sheet["id"]:
            continue
        if sibling["opportunity_id"] != opportunity["id"]:
            continue
        if sibling["status"] in ("DRAFT", "SUBMITTED", "COUNTERED"):
            sibling["status"] = "WITHDRAWN"
            touch(sibling)

    return created(engagement)
