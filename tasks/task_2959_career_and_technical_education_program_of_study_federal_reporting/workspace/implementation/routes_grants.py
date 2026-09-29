"""Grant award, expenditure and obligation-ledger routes (PRD sec 3.7)."""
from flask import Blueprint

import calc
import resolve
import serialize
import services
import shape
from auth import actor, endpoint
from envelope import created, listing, ok, page
from errors import ApiError
from store import (CAPITAL_THRESHOLD_CENTS, DECISIONS, EXPENDITURE_CATEGORIES,
                   EXPENDITURE_STATUSES, FINDING_CODES, GRANT_STATUSES,
                   INDIRECT_RATE_TIER_1, clock_date, db, fmt_date, parse_date,
                   stamp_new, touch)

bp = Blueprint("grants", __name__)
FISCAL = ("GrantFiscalOfficer",)
DIRECTOR = ("CteDirector",)
READERS = ("CteDirector", "StateComplianceReviewer", "GrantFiscalOfficer")
ASSET_PATTERN = r"[A-Z0-9-]{3,24}"


def _filter_expenditures(rows):
    status = shape.filter_enum("status", EXPENDITURE_STATUSES)
    category = shape.filter_enum("category", EXPENDITURE_CATEGORIES)
    asset_tag = shape.filter_str("asset_tag")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if category is not None:
        rows = [r for r in rows if r["category"] == category]
    if asset_tag is not None:
        rows = [r for r in rows if r["asset_tag"] == asset_tag]
    return rows


# ------------------------------------------------------------------ reads
@bp.get("/cte/grant-awards")
@endpoint(READERS)
def list_awards():
    limit, offset = shape.pagination()
    fiscal_year = shape.filter_int("fiscal_year")
    rows = list(db.awards.values())
    if fiscal_year is not None:
        rows = [r for r in rows if int(r["fiscal_year"]) == fiscal_year]
    rows.sort(key=lambda r: (int(r["fiscal_year"]), r["_seq"]), reverse=True)
    window, total = page(rows, limit, offset)
    return listing([serialize.award(r) for r in window], limit, offset, total)


@bp.get("/cte/grant-awards/<award_id>")
@endpoint(READERS)
def get_award(award_id):
    return ok(serialize.award(resolve.award(award_id)))


@bp.get("/cte/grant-awards/<award_id>/expenditures")
@endpoint(READERS)
def list_award_expenditures(award_id):
    limit, offset = shape.pagination()
    rows = _filter_expenditures(list(db.expenditures.values()))
    resolve.award(award_id)
    rows = [r for r in rows if r["grant_award_id"] == award_id]
    rows.sort(key=lambda r: r["_seq"])
    window, total = page(rows, limit, offset)
    return listing([serialize.expenditure(r) for r in window], limit, offset, total)


@bp.get("/cte/expenditures/<expenditure_id>")
@endpoint(READERS)
def get_expenditure(expenditure_id):
    return ok(serialize.expenditure(resolve.expenditure(expenditure_id)))


# ------------------------------------------------------------------ awards
@bp.post("/cte/grant-awards")
@endpoint(FISCAL)
def create_award():
    data = shape.body()
    fiscal_year = shape.req_int(data, "fiscal_year", minimum=2020, maximum=2035)
    allocation = shape.req_int(data, "allocation_cents", minimum=1)
    window_start = shape.req_date(data, "obligation_window_start")
    window_end = shape.req_date(data, "obligation_window_end")
    if window_end <= window_start:
        shape.bad("Field 'obligation_window_end' must be strictly after "
                  "'obligation_window_start'.")
    for existing in db.awards.values():
        if int(existing["fiscal_year"]) == fiscal_year:
            raise ApiError("ERR_FISCAL_YEAR_DUPLICATE",
                           "A grant award already exists for fiscal year %d."
                           % fiscal_year)
    award = stamp_new({
        "fiscal_year": fiscal_year,
        "allocation_cents": allocation,
        "obligation_window_start": fmt_date(window_start),
        "obligation_window_end": fmt_date(window_end),
        "direct_obligated_cents": 0,
        "indirect_rate": INDIRECT_RATE_TIER_1,
        "indirect_pool_cents": 0,
        "obligated_cents": 0,
        "remaining_cents": allocation,
        "admin_obligated_cents": 0,
        "admin_cap_cents": calc.admin_cap(allocation),
    })
    db.awards[award["id"]] = award
    return created(serialize.award(award))


@bp.post("/cte/grant-awards/<award_id>/expenditures")
@endpoint(DIRECTOR)
def request_expenditure(award_id):
    data = shape.body()
    pos_id = shape.req_string(data, "pos_id")
    category = shape.req_enum(data, "category", EXPENDITURE_CATEGORIES)
    description = shape.req_string(data, "description")
    unit_cost = shape.req_int(data, "unit_cost_cents", minimum=1)
    quantity = shape.req_int(data, "quantity", minimum=1)
    period_start = shape.req_date(data, "service_period_start")
    period_end = shape.req_date(data, "service_period_end")
    if period_end < period_start:
        shape.bad("Field 'service_period_end' must be on or after "
                  "'service_period_start'.")
    asset_tag = shape.opt_string(data, "asset_tag", min_len=3, max_len=24,
                                 pattern=ASSET_PATTERN)
    expected = shape.req_int(data, "expected_grant_award_version")

    award = resolve.award(award_id)
    resolve.program(pos_id)
    if int(award["version"]) != int(expected):
        raise ApiError("ERR_STALE_GRANT_VERSION",
                       "The grant award is at version %s, not %s."
                       % (award["version"], expected))
    if not services.award_window_open(award):
        raise ApiError("ERR_GRANT_WINDOW_CLOSED",
                       "The award's obligation window is not open on the current "
                       "logical date.")
    if asset_tag is not None and services.asset_conflict(award_id, asset_tag,
                                                        period_start, period_end):
        raise ApiError("ERR_ASSET_PERIOD_OVERLAP",
                       "Asset '%s' is already booked within the 14-day "
                       "mobilisation buffer." % asset_tag)

    expenditure = stamp_new({
        "grant_award_id": award_id,
        "pos_id": pos_id,
        "category": category,
        "description": description,
        "unit_cost_cents": unit_cost,
        "quantity": quantity,
        "gross_cents": unit_cost * quantity,
        "federal_share_pct": calc.federal_share(category),
        "approved_cents": None,
        "asset_tag": asset_tag,
        "service_period_start": fmt_date(period_start),
        "service_period_end": fmt_date(period_end),
        "status": "REQUESTED",
        "requested_by_user_id": actor(),
        "certified_by_user_id": None,
        "finding_code": None,
        "obligation_reference": None,
        "void_reason": None,
    })
    db.expenditures[expenditure["id"]] = expenditure
    touch(award)
    return created(serialize.expenditure(expenditure))


# ------------------------------------------------------------------ allowability
@bp.post("/cte/expenditures/<expenditure_id>/certify-allowability")
@endpoint(FISCAL)
def certify_allowability(expenditure_id):
    data = shape.body()
    decision = shape.req_enum(data, "decision", DECISIONS)
    finding_code = shape.opt_enum(data, "finding_code", FINDING_CODES)
    if decision == "DISALLOW" and finding_code is None:
        shape.bad("A DISALLOW decision requires a 'finding_code'.")

    expenditure = resolve.expenditure(expenditure_id)
    program = db.programs.get(expenditure["pos_id"])
    if program is not None:
        services.refresh_clna(program)

    if actor() == expenditure["requested_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The officer who requested this purchase may not rule on "
                       "its allowability.")
    if expenditure["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_EXPENDITURE_STATE",
                       "Expenditure status %s does not declare an allowability "
                       "ruling." % expenditure["status"])

    if decision == "DISALLOW":
        expenditure["status"] = "DISALLOWED"
        expenditure["finding_code"] = finding_code
        expenditure["certified_by_user_id"] = actor()
        touch(expenditure)
        return ok(serialize.expenditure(expenditure))

    award = db.awards[expenditure["grant_award_id"]]
    if program is None or program["approval_status"] != "STATE_APPROVED":
        raise ApiError("ERR_POS_NOT_APPROVED",
                       "The charged program of study is not STATE_APPROVED.")
    if program["clna_phase"] not in ("CERTIFIED", "EXPIRED"):
        raise ApiError("ERR_CLNA_NOT_CERTIFIED",
                       "The charged program's needs assessment has never been "
                       "certified.")
    expires = parse_date(program["clna_expires_on"])
    if program["clna_phase"] == "EXPIRED" or (
            expires is not None and clock_date() > expires):
        raise ApiError("ERR_CLNA_EXPIRED",
                       "The charged program's needs assessment has lapsed.")
    if not services.award_window_open(award):
        raise ApiError("ERR_GRANT_WINDOW_CLOSED",
                       "The award's obligation window is not open on the current "
                       "logical date.")
    if expenditure["category"] == "ENTERTAINMENT":
        raise ApiError("ERR_UNALLOWABLE_USE",
                       "Entertainment is never an allowable federal use.")
    if (expenditure["category"] == "EQUIPMENT"
            and int(expenditure["unit_cost_cents"]) >= CAPITAL_THRESHOLD_CENTS):
        if not services.capital_review_on_file(expenditure["pos_id"]):
            raise ApiError("ERR_CAPITAL_REVIEW_REQUIRED",
                           "A quorate EQUIPMENT_REVIEW meeting held within the "
                           "last 365 days is required for this capital purchase.")

    approved = calc.approved_cents(expenditure["gross_cents"],
                                   expenditure["federal_share_pct"])
    if expenditure["category"] == "ADMINISTRATION":
        if int(award["admin_obligated_cents"]) + approved > int(award["admin_cap_cents"]):
            raise ApiError("ERR_ADMIN_CAP_EXCEEDED",
                           "This administrative line would breach the 5% "
                           "administrative cost cap.")
    probe = dict(expenditure)
    probe["approved_cents"] = approved
    if calc.rebuild_ledger(award, extra=probe)["remaining_cents"] < 0:
        raise ApiError("ERR_GRANT_FUNDS_EXCEEDED",
                       "Certifying this line would overdraw the grant award.")

    expenditure["approved_cents"] = approved
    expenditure["certified_by_user_id"] = actor()
    expenditure["status"] = "CERTIFIED"
    if finding_code is not None:
        expenditure["finding_code"] = finding_code
    touch(expenditure)
    services.rebuild_award(award)
    return ok(serialize.expenditure(expenditure))


@bp.post("/cte/expenditures/<expenditure_id>/obligate")
@endpoint(FISCAL)
def obligate(expenditure_id):
    data = shape.body()
    reference = shape.req_string(data, "obligation_reference")
    expenditure = resolve.expenditure(expenditure_id)
    if expenditure["status"] != "CERTIFIED":
        raise ApiError("ERR_INVALID_EXPENDITURE_STATE",
                       "Expenditure status %s does not declare a transition to "
                       "OBLIGATED." % expenditure["status"])
    award = db.awards[expenditure["grant_award_id"]]
    window_end = parse_date(award["obligation_window_end"])
    if window_end is None or clock_date() > window_end:
        raise ApiError("ERR_GRANT_WINDOW_CLOSED",
                       "The award's obligation window has closed.")
    expenditure["obligation_reference"] = reference
    expenditure["status"] = "OBLIGATED"
    touch(expenditure)
    return ok(serialize.expenditure(expenditure))


@bp.post("/cte/expenditures/<expenditure_id>/void")
@endpoint(FISCAL)
def void(expenditure_id):
    data = shape.body()
    void_reason = shape.req_string(data, "void_reason")
    expenditure = resolve.expenditure(expenditure_id)
    if expenditure["status"] not in ("CERTIFIED", "OBLIGATED"):
        raise ApiError("ERR_INVALID_EXPENDITURE_STATE",
                       "Expenditure status %s does not declare a transition to "
                       "VOIDED." % expenditure["status"])
    award = db.awards[expenditure["grant_award_id"]]
    expenditure["void_reason"] = void_reason
    expenditure["approved_cents"] = None
    expenditure["status"] = "VOIDED"
    touch(expenditure)
    services.rebuild_award(award)
    return ok(serialize.expenditure(expenditure))
