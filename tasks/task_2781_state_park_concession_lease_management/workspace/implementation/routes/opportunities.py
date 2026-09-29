"""Concession opportunities and the market analysis — PRD 3.1."""
import calc
from auth import ALL_ROLES, fetch, guard
from envelope import created, listing, ok
from errors import ApiError
from router import route
from shape import body, opt_str, ref, req_enum, req_int, req_pct, req_str
from store import db, insert, touch

SERVICE_CATEGORIES = ("LODGING", "FOOD_SERVICE", "RETAIL", "GUIDED_ACTIVITY", "MARINA")


@route("/concession-opportunities", methods=["POST"])
def opportunities_create():
    guard("ConcessionSpecialist")
    data = body()
    park_ref = ref(data, "park_id")
    if park_ref is not None:
        fetch(db.parks, park_ref, "ERR_PARK_NOT_FOUND")
    row = {
        "park_id": req_str(data, "park_id"),
        "title": req_str(data, "title"),
        "service_category": req_enum(data, "service_category", SERVICE_CATEGORIES),
        "required_capital_investment_cents": req_int(
            data, "required_capital_investment_cents", minimum=0),
        "comparable_gross_receipts_cents": None,
        "market_capture_pct": None,
        "estimated_annual_gross_receipts_cents": None,
        "analyst_note": None,
        "status": "DRAFT",
    }
    return created(insert(db.opportunities, row))


@route("/concession-opportunities/<opportunity_id>/market-analysis", methods=["POST"])
def opportunities_market_analysis(opportunity_id):
    guard("ConcessionSpecialist")
    opportunity = fetch(db.opportunities, opportunity_id, "ERR_OPPORTUNITY_NOT_FOUND")
    data = body()
    comparable = req_int(data, "comparable_gross_receipts_cents", minimum=0)
    capture = req_pct(data, "market_capture_pct", gt=0, le=calc.MARKET_CAPTURE_MAX_PCT)
    note = opt_str(data, "analyst_note")
    if opportunity["status"] not in ("DRAFT", "ANALYSIS_COMPLETE"):
        raise ApiError("ERR_OPPORTUNITY_STATUS_INVALID",
                       "Opportunity status %s does not admit a market analysis"
                       % opportunity["status"])
    opportunity["comparable_gross_receipts_cents"] = comparable
    opportunity["market_capture_pct"] = capture
    opportunity["analyst_note"] = note
    opportunity["estimated_annual_gross_receipts_cents"] = calc.market_projection(
        comparable, capture)
    opportunity["status"] = "ANALYSIS_COMPLETE"
    touch(opportunity)
    return ok(opportunity)


@route("/concession-opportunities/<opportunity_id>/approve-solicitation", methods=["POST"])
def opportunities_approve(opportunity_id):
    guard("ContractingOfficer")
    opportunity = fetch(db.opportunities, opportunity_id, "ERR_OPPORTUNITY_NOT_FOUND")
    if opportunity["status"] != "ANALYSIS_COMPLETE":
        raise ApiError("ERR_OPPORTUNITY_STATUS_INVALID",
                       "Opportunity status %s cannot be approved for solicitation"
                       % opportunity["status"])
    projected = opportunity["estimated_annual_gross_receipts_cents"] or 0
    if projected < calc.MIN_VIABLE_ANNUAL_RECEIPTS_CENTS:
        raise ApiError("ERR_OPPORTUNITY_NOT_VIABLE",
                       "Projected annual receipts are below the viability floor")
    opportunity["status"] = "APPROVED_FOR_SOLICITATION"
    touch(opportunity)
    return ok(opportunity)


@route("/concession-opportunities", methods=["GET"])
def opportunities_list():
    guard(*ALL_ROLES)
    return listing(db.opportunities, ("park_id", "status", "service_category"))


@route("/concession-opportunities/<opportunity_id>", methods=["GET"])
def opportunities_read(opportunity_id):
    guard(*ALL_ROLES)
    return ok(fetch(db.opportunities, opportunity_id, "ERR_OPPORTUNITY_NOT_FOUND"))
