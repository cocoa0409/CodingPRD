"""Annual work plans (PRD 3.7): drafting, board action and amendment."""
from decimal import Decimal

from flask import Blueprint

import config
import envelope
import serialize
import store
import validate
from auth import authenticate
from errors import fail
from routes.common import ADMIN, AUDITOR, BOARD, DMO, VIEWER, narrow
from services import core, plans as planservice
from store import put, rhu_cents, touch

bp = Blueprint("workplans", __name__)


def _lines(b):
    """Rung 4 shape of expenditure_lines."""
    raw = validate.array(b, "expenditure_lines", required=True, min_len=1)
    seen = []
    lines = []
    for entry in raw:
        if not isinstance(entry, dict):
            fail("ERR_INVALID_REQUEST", "each expenditure line must be an object.")
        category = validate.enum(entry, "category", config.EXPENDITURE_CATEGORIES)
        amount = validate.cents(entry, "amount_cents", minimum=1)
        narrative = validate.text(entry, "narrative")
        if category in seen:
            fail("ERR_INVALID_REQUEST",
                 "at most one expenditure line per category may appear.")
        seen.append(category)
        lines.append({"category": category, "amount_cents": amount, "narrative": narrative})
    return lines


def _shadow(lines):
    """A proposed plan's rollups, for compliance checks before anything is committed."""
    total, totals = planservice.rollups(lines)
    shadow = {"total_budget_cents": total}
    for category, field in planservice.CATEGORY_FIELD.items():
        shadow[field] = totals[category]
    return shadow


# ---------------------------------------------------------------------------
# reads
# ---------------------------------------------------------------------------
@bp.get("/annual-work-plans/<plan_id>")
def read_plan(plan_id):
    authenticate([ADMIN, BOARD, AUDITOR, DMO, VIEWER], public=True)
    return envelope.ok(serialize.plan(validate.plan(plan_id)))


@bp.get("/annual-work-plans/<plan_id>/marketing-programs")
def list_plan_programs(plan_id):
    authenticate([ADMIN, BOARD, DMO, AUDITOR])
    plan = validate.plan(plan_id)
    status = envelope.enum_filter("status", config.PROGRAM_STATUSES)
    channel = envelope.enum_filter("channel", config.PROGRAM_CHANNELS)
    records = narrow(core.programs_of_plan(plan["id"]), status=status, channel=channel)
    return envelope.paginate(records, serialize.program)


# ---------------------------------------------------------------------------
# writes
# ---------------------------------------------------------------------------
@bp.post("/annual-work-plans")
def create_plan():
    authenticate([ADMIN])
    b = validate.body()
    district_id = validate.id_ref(b, "district_id")
    fiscal_year = validate.integer(b, "fiscal_year", minimum=2020, maximum=2050)
    lines = _lines(b)

    district = validate.district(district_id)
    if district["status"] in config.DISTRICT_TERMINAL:
        fail("ERR_DISTRICT_NOT_ACTIVE",
             "A %s district accepts no work plan activity." % district["status"])
    for existing in core.plans_of_district(district["id"]):
        if existing["fiscal_year"] == fiscal_year and existing["status"] != "CLOSED":
            fail("ERR_INVALID_REQUEST",
                 "A live work plan already claims fiscal year %d." % fiscal_year)

    rec = store.new_record("plan")
    rec.update({
        "district_id": district["id"],
        "fiscal_year": fiscal_year,
        "status": "DRAFT",
        "expenditure_lines": [],
        "total_budget_cents": 0,
        "administration_cents": 0,
        "contingency_reserve_cents": 0,
        "sales_and_marketing_cents": 0,
        "destination_events_cents": 0,
        "capital_improvement_cents": 0,
        "assessment_revenue_forecast_cents": 0,
        "funding_ratio": Decimal("0.0000"),
        "sponsor_user_id": None,
        "approver_user_id": None,
        "approved_at": None,
        "revision_count": 0,
        "committed_program_cents": 0,
    })
    planservice.write_rollups(rec, lines)
    planservice.write_forecast(rec, district)
    put("plans", rec)
    return envelope.created(serialize.plan(rec))


@bp.post("/annual-work-plans/<plan_id>/board-actions")
def board_action(plan_id):
    actor = authenticate([BOARD])
    b = validate.body()
    action = validate.enum(b, "action", config.BOARD_ACTIONS)
    validate.text(b, "note", required=False)

    plan = validate.plan(plan_id)
    district = core.district_of_plan(plan)

    if action == "SPONSOR":
        if plan["status"] != "DRAFT":
            fail("ERR_INVALID_STATE_TRANSITION", "Only a DRAFT plan may be sponsored.")
        if not plan["expenditure_lines"]:
            fail("ERR_INVALID_STATE_TRANSITION",
                 "A plan with no expenditure lines may not be sponsored.")
        plan["status"] = "BOARD_REVIEW"
        plan["sponsor_user_id"] = actor.user_id

    elif action == "RETURN":
        if plan["status"] != "BOARD_REVIEW":
            fail("ERR_INVALID_STATE_TRANSITION", "Only a plan in BOARD_REVIEW may be returned.")
        plan["status"] = "DRAFT"
        plan["sponsor_user_id"] = None
        plan["revision_count"] = plan["revision_count"] + 1

    elif action == "APPROVE":
        if plan["status"] != "BOARD_REVIEW":
            fail("ERR_INVALID_STATE_TRANSITION", "Only a plan in BOARD_REVIEW may be approved.")
        if actor.user_id == plan["sponsor_user_id"]:
            fail("ERR_SEGREGATION_OF_DUTIES",
                 "The approving board member must differ from the sponsor.")
        planservice.enforce_category_caps(plan, district)
        planservice.enforce_match_ceiling(plan, district)
        planservice.write_forecast(plan, district)
        planservice.enforce_funding_ratio(plan)
        plan["status"] = "APPROVED"
        plan["approver_user_id"] = actor.user_id
        plan["approved_at"] = store.clock()
        plan["_raw"].pop("approved_at", None)

    else:
        if plan["status"] != "APPROVED":
            fail("ERR_INVALID_STATE_TRANSITION", "Only an APPROVED plan may be closed.")
        for program in core.programs_of_plan(plan["id"]):
            if program["status"] not in ("CLOSED", "CANCELLED"):
                fail("ERR_INVALID_STATE_TRANSITION",
                     "Every marketing program of the plan must already be CLOSED or CANCELLED.")
        plan["status"] = "CLOSED"

    touch(plan)
    return envelope.ok(serialize.plan(plan))


@bp.post("/annual-work-plans/<plan_id>/amendments")
def amend_plan(plan_id):
    authenticate([ADMIN, BOARD])
    b = validate.body()
    expected_version = validate.integer(b, "expected_work_plan_version")
    lines = _lines(b)
    validate.text(b, "amendment_reason", required=False)

    plan = validate.plan(plan_id)
    district = core.district_of_plan(plan)

    if plan["status"] not in ("APPROVED", "AMENDMENT_PENDING"):
        fail("ERR_INVALID_STATE_TRANSITION",
             "Only an APPROVED or AMENDMENT_PENDING plan may be amended.")
    if expected_version != plan["version"]:
        fail("ERR_STALE_WORK_PLAN_VERSION",
             "expected_work_plan_version %d does not match the stored version %d."
             % (expected_version, plan["version"]))

    shadow = _shadow(lines)
    planservice.enforce_category_caps(shadow, district)

    stored_total = plan["total_budget_cents"]
    allowance = rhu_cents(Decimal(stored_total) * config.AMENDMENT_VARIANCE_PCT)
    if abs(shadow["total_budget_cents"] - stored_total) > allowance:
        fail("ERR_AMENDMENT_VARIANCE_EXCEEDED",
             "The amended total may differ from %d cents by at most %d cents."
             % (stored_total, allowance))
    if plan["revision_count"] >= config.MAX_REVISIONS:
        fail("ERR_AMENDMENT_VARIANCE_EXCEEDED",
             "A plan may take at most %d revisions." % config.MAX_REVISIONS)
    planservice.enforce_match_ceiling(shadow, district)
    forecast = planservice.forecast_for(district, plan["fiscal_year"])
    ratio = planservice.funding_ratio_for(forecast, shadow["total_budget_cents"])
    if ratio < config.FUNDING_RATIO_FLOOR:
        fail("ERR_FUNDING_RATIO_BELOW_MINIMUM", "funding_ratio must be at least 0.9000.")

    planservice.write_rollups(plan, lines)
    plan["revision_count"] = plan["revision_count"] + 1
    plan["assessment_revenue_forecast_cents"] = forecast
    plan["funding_ratio"] = ratio
    plan["status"] = "APPROVED"
    touch(plan)
    planservice.release_programs(plan)
    return envelope.ok(serialize.plan(plan))
