from flask import Blueprint

import calc
import db
import middleware as mw
import response
import util
from errors import ApiError

bp = Blueprint("institutions", __name__)

CAPITAL_CATEGORIES = ("WELL_CAPITALIZED", "ADEQUATELY_CAPITALIZED", "UNDERCAPITALIZED",
                      "SIGNIFICANTLY_UNDERCAPITALIZED", "CRITICALLY_UNDERCAPITALIZED")

READ_ROLES = ("SystemAdmin", "FundingDeskOfficer", "ComplianceReviewer",
              "TreasuryController", "Examiner")


def find_institution(institution_id):
    record = db.institutions.get(institution_id)
    if record is None:
        raise ApiError("ERR_INSTITUTION_NOT_FOUND")
    return record


@bp.post("/institutions")
def create_institution():
    mw.auth("SystemAdmin")
    data = mw.body()
    legal_name = mw.req_str(data, "legal_name")
    cert_id = mw.req_str(data, "cert_id")
    capital_category = mw.opt_enum(data, "capital_category", CAPITAL_CATEGORIES,
                                  "WELL_CAPITALIZED")
    core_deposits_cents = mw.req_int(data, "core_deposits_cents", minimum=0)
    total_liabilities_cents = mw.req_int(data, "total_liabilities_cents", minimum=0)
    if total_liabilities_cents <= 0:
        raise mw.bad("total_liabilities_cents must be strictly greater than zero.")
    tier1_capital_cents = mw.req_int(data, "tier1_capital_cents", minimum=0)
    liquidity_buffer_cents = mw.req_int(data, "liquidity_buffer_cents", minimum=0)

    for existing in db.institutions.values():
        if existing["cert_id"] == cert_id:
            raise ApiError("ERR_DUPLICATE_KEY", "cert_id is already registered.")

    record = {
        "legal_name": legal_name,
        "cert_id": cert_id,
        "capital_category": capital_category,
        "rate_cap_regime": calc.rate_cap_regime(capital_category),
        "core_deposits_cents": core_deposits_cents,
        "brokered_deposits_cents": 0,
        "listing_service_deposits_cents": 0,
        "reciprocal_deposits_cents": 0,
        "total_deposits_cents": core_deposits_cents,
        "total_liabilities_cents": total_liabilities_cents,
        "tier1_capital_cents": tier1_capital_cents,
        "liquidity_buffer_cents": liquidity_buffer_cents,
        "wholesale_funding_ratio_bps": 0,
        "single_broker_max_ratio_bps": 0,
        "concentration_posture": "OPEN",
        "breached_metric_count": 0,
    }
    db.stamp_new(record)
    db.institutions[record["id"]] = record
    return response.created(db.public(record))


@bp.get("/institutions/<institution_id>")
def read_institution(institution_id):
    mw.auth(*READ_ROLES)
    return response.ok(db.public(find_institution(institution_id)))


@bp.get("/institutions")
def list_institutions():
    mw.auth(*READ_ROLES)
    limit, offset = mw.page()
    rows = list(db.institutions.values())
    for field in ("capital_category", "rate_cap_regime", "concentration_posture"):
        wanted = mw.q(field)
        if wanted is not None:
            rows = [r for r in rows if r[field] == wanted]
    rows.sort(key=lambda r: (r["created_at"], r["cert_id"], r["_seq"]))
    return response.listing(db.public_list(rows), limit, offset)


@bp.patch("/institutions/<institution_id>/capital-category")
def change_capital_category(institution_id):
    mw.auth("SystemAdmin", "Examiner")
    institution = find_institution(institution_id)
    data = mw.body()
    capital_category = mw.req_enum(data, "capital_category", CAPITAL_CATEGORIES)
    expected = mw.req_int(data, "expected_institution_version")
    if expected != institution["version"]:
        raise ApiError("ERR_STALE_INSTITUTION_VERSION")
    if calc.examiner_lock(institution_id):
        raise ApiError("ERR_EXAMINER_REVIEW_LOCK")

    institution["capital_category"] = capital_category
    institution["rate_cap_regime"] = calc.rate_cap_regime(capital_category)
    db.bump(institution)

    as_of = util.clock_date().isoformat()
    for program in calc.programs_of(institution_id):
        if program["state"] == "CLOSED":
            continue
        cap, _pub = calc.effective_cap(institution, program["tenor_bucket"],
                                       program.get("local_prevailing_rate_bps"),
                                       as_of, require=False)
        program["effective_cap_bps"] = cap
        db.bump(program)
        for placement in calc.placements_of_program(program["id"]):
            if placement["funding_status"] != "ACTIVE":
                continue
            if cap is not None and placement["rate_bps"] > cap:
                if placement["compliance_status"] != "FLAGGED":
                    placement["compliance_status"] = "FLAGGED"
                    db.bump(placement)
    calc.recompute_institution(institution)
    return response.ok(db.public(institution))


@bp.post("/institutions/<institution_id>/balance-adjustments")
def adjust_balances(institution_id):
    mw.auth("SystemAdmin", "TreasuryController")
    institution = find_institution(institution_id)
    data = mw.body()
    updates = {}
    if "core_deposits_cents" in data and data.get("core_deposits_cents") is not None:
        updates["core_deposits_cents"] = mw.req_int(data, "core_deposits_cents", minimum=0)
    if "total_liabilities_cents" in data and data.get("total_liabilities_cents") is not None:
        value = mw.req_int(data, "total_liabilities_cents", minimum=0)
        if value <= 0:
            raise mw.bad("total_liabilities_cents must be strictly greater than zero.")
        updates["total_liabilities_cents"] = value
    if "tier1_capital_cents" in data and data.get("tier1_capital_cents") is not None:
        updates["tier1_capital_cents"] = mw.req_int(data, "tier1_capital_cents", minimum=0)
    if "liquidity_buffer_cents" in data and data.get("liquidity_buffer_cents") is not None:
        updates["liquidity_buffer_cents"] = mw.req_int(data, "liquidity_buffer_cents",
                                                      minimum=0)
    if calc.examiner_lock(institution_id):
        raise ApiError("ERR_EXAMINER_REVIEW_LOCK")

    institution.update(updates)
    db.bump(institution)
    calc.recompute_institution(institution)
    return response.ok(db.public(institution))


@bp.get("/institutions/<institution_id>/wholesale-funding-summary")
def wholesale_funding_summary(institution_id):
    mw.auth("SystemAdmin", "TreasuryController", "ComplianceReviewer", "Examiner")
    institution = find_institution(institution_id)
    basis = mw.q("basis") or "POINT_IN_TIME"
    if basis not in ("POINT_IN_TIME", "AVERAGE_DAILY"):
        raise mw.bad("basis must be POINT_IN_TIME or AVERAGE_DAILY.")
    avg_wholesale = 0
    average_ratio = 0
    day_count = 0
    if basis == "AVERAGE_DAILY":
        period_start = mw.q("period_start")
        period_end = mw.q("period_end")
        if (period_start is None or period_end is None
                or util.parse_date(period_start) is None
                or util.parse_date(period_end) is None):
            raise mw.bad("basis=AVERAGE_DAILY requires period_start and period_end "
                         "formatted YYYY-MM-DD.")
        avg_wholesale, average_ratio, day_count = calc.average_daily(
            institution, period_start, period_end)
    payload = {
        "institution_id": institution["id"],
        "basis": basis,
        "wholesale_funding_ratio_bps": institution["wholesale_funding_ratio_bps"],
        "average_daily_ratio_bps": average_ratio,
        "avg_wholesale_cents": avg_wholesale,
        "day_count": day_count,
        "brokered_deposits_cents": institution["brokered_deposits_cents"],
        "listing_service_deposits_cents": institution["listing_service_deposits_cents"],
        "reciprocal_deposits_cents": institution["reciprocal_deposits_cents"],
        "total_deposits_cents": institution["total_deposits_cents"],
        "single_broker_max_ratio_bps": institution["single_broker_max_ratio_bps"],
        "brokered_headroom_cents": calc.brokered_headroom(institution),
        "concentration_posture": institution["concentration_posture"],
        "breached_metric_count": institution["breached_metric_count"],
    }
    return response.ok(payload)
