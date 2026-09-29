"""Assessment periods, statement generation, closure and the delinquency sweep."""
from decimal import Decimal

from flask import Blueprint

import config
import envelope
import serialize
import store
import validate
from auth import authenticate
from errors import fail
from routes.common import ADMIN, AUDITOR, BOARD, HEARING, narrow
from services import core
from store import put, rhu_cents, touch

bp = Blueprint("periods", __name__)

SWEEPABLE_PAYMENT_STATUSES = ("UNPAID", "PARTIALLY_PAID")


def new_statement(period, business, district):
    rec = store.new_record("statement")
    rec.update({
        "assessment_period_id": period["id"],
        "lodging_business_id": business["id"],
        "zone_at_period_start": business["boundary_zone"],
        "classification_at_period_start": business["classification"],
        "assessment_method_at_period_start": district["assessment_method"],
        "reported_room_nights": None,
        "reported_gross_room_revenue_cents": None,
        "audited_room_nights": None,
        "audited_gross_room_revenue_cents": None,
        "provisional_assessment_cents": 0,
        "final_assessment_cents": None,
        "effective_assessment_cents": 0,
        "granted_adjustment_cents": 0,
        "filing_status": "NOT_FILED",
        "payment_status": "UNPAID",
        "delinquency_stage": "NONE",
        "penalty_cents": 0,
        "interest_cents": 0,
        "principal_paid_cents": 0,
        "penalty_paid_cents": 0,
        "interest_paid_cents": 0,
        "credit_balance_cents": 0,
        "total_due_cents": 0,
        "amendment_count": 0,
        "filed_at": None,
        "audited_by_user_id": None,
        "_original_reported_revenue_cents": None,
    })
    return put("statements", rec)


# ---------------------------------------------------------------------------
# reads
# ---------------------------------------------------------------------------
@bp.get("/assessment-periods/<period_id>")
def read_period(period_id):
    authenticate([ADMIN, BOARD, AUDITOR])
    return envelope.ok(serialize.period(validate.period(period_id)))


@bp.get("/assessment-periods/<period_id>/statements")
def list_period_statements(period_id):
    authenticate([ADMIN, AUDITOR, HEARING])
    period = validate.period(period_id)
    business_id = envelope.str_filter("lodging_business_id")
    filing_status = envelope.enum_filter("filing_status", config.FILING_STATUSES)
    payment_status = envelope.enum_filter("payment_status", config.PAYMENT_STATUSES)
    records = narrow(core.statements_of_period(period["id"]),
                     lodging_business_id=business_id,
                     filing_status=filing_status, payment_status=payment_status)
    return envelope.paginate(records, serialize.statement)


# ---------------------------------------------------------------------------
# writes
# ---------------------------------------------------------------------------
@bp.post("/assessment-periods")
def open_period():
    authenticate([ADMIN])
    b = validate.body()
    district_id = validate.id_ref(b, "district_id")
    label = validate.text(b, "period_label", max_len=32)
    if not label.strip():
        fail("ERR_INVALID_REQUEST", "period_label may not be blank.")
    period_start = validate.instant(b, "period_start")
    period_end = validate.instant(b, "period_end")
    due_date = validate.instant(b, "due_date")
    grace_days = validate.integer(b, "grace_days", required=False,
                                  default=config.DEFAULT_GRACE_DAYS, minimum=0, maximum=60)
    if period_end.dt <= period_start.dt:
        fail("ERR_INVALID_REQUEST", "period_end must fall strictly after period_start.")
    if due_date.dt < period_end.dt:
        fail("ERR_INVALID_REQUEST", "due_date must be at or after period_end.")

    district = validate.district(district_id)
    if district["status"] in config.DISTRICT_TERMINAL:
        fail("ERR_DISTRICT_NOT_ACTIVE",
             "A district in %s accepts no new assessment period." % district["status"])

    for existing in core.periods_of_district(district["id"]):
        if period_start.dt < existing["period_end"] and existing["period_start"] < period_end.dt:
            fail("ERR_PERIOD_OVERLAP",
                 "The window overlaps assessment period %s." % existing["id"])

    rec = store.new_record("period")
    rec.update({
        "district_id": district["id"],
        "period_label": label,
        "grace_days": grace_days,
        "status": "OPEN",
        "statement_count": 0,
        "billed_total_cents": 0,
        "collected_total_cents": 0,
    })
    validate.assign(rec, "period_start", period_start)
    validate.assign(rec, "period_end", period_end)
    validate.assign(rec, "due_date", due_date)
    put("periods", rec)
    return envelope.created(serialize.period(rec))


@bp.post("/assessment-periods/<period_id>/statement-generation")
def generate_statements(period_id):
    authenticate([ADMIN])
    validate.body()
    period = validate.period(period_id)
    district = store.state.districts[period["district_id"]]

    roll = store.sorted_records(core.businesses_of_district(district["id"]))
    eligible = [b for b in roll if core.is_assessable_member(b, district)]
    already = set(s["lodging_business_id"] for s in core.statements_of_period(period["id"]))
    missing = [b for b in eligible if b["id"] not in already]

    if not missing:
        outside = [b for b in roll
                   if b["status"] == "OUTSIDE_BOUNDARY"
                   or b["boundary_zone"] not in district["included_zones"]]
        if roll and not eligible and outside:
            fail("ERR_BUSINESS_OUTSIDE_BOUNDARY",
                 "No property of the roll sits inside the district boundary.")
        fail("ERR_STATEMENT_ALREADY_EXISTS_FOR_PERIOD",
             "Every eligible property already holds a statement for this period.")

    statement_ids = []
    for business in missing:
        statement_ids.append(new_statement(period, business, district)["id"])

    period["statement_count"] = len(core.statements_of_period(period["id"]))
    touch(period)
    return envelope.created({
        "assessment_period_id": period["id"],
        "generated_count": len(statement_ids),
        "skipped_count": len(roll) - len(statement_ids),
        "statement_ids": statement_ids,
    })


@bp.post("/assessment-periods/<period_id>/closure")
def close_period(period_id):
    authenticate([ADMIN])
    validate.body()
    period = validate.period(period_id)
    if period["status"] != "OPEN":
        fail("ERR_INVALID_STATE_TRANSITION", "Only an OPEN period may be closed.")
    if store.clock() < period["period_end"]:
        fail("ERR_INVALID_STATE_TRANSITION",
             "The logical clock has not yet reached period_end.")
    if not core.statements_of_period(period["id"]):
        fail("ERR_INVALID_STATE_TRANSITION",
             "At least one statement must have been generated for the period.")

    period["status"] = "CLOSED"
    core.recompute_period_totals(period)
    touch(period)
    return envelope.ok(serialize.period(period))


@bp.post("/assessment-periods/<period_id>/delinquency-sweep")
def sweep_period(period_id):
    authenticate([ADMIN])
    validate.body()
    period = validate.period(period_id)
    if period["status"] != "CLOSED":
        fail("ERR_INVALID_STATE_TRANSITION", "Only a CLOSED period may be swept.")
    now = store.clock()
    deadline = core.grace_deadline(period)
    if now <= deadline:
        fail("ERR_INVALID_STATE_TRANSITION",
             "The logical clock must be strictly past the grace deadline.")

    district = store.state.districts[period["district_id"]]
    days_late = max(store.whole_days_between(deadline, now), 1)

    selected = [s for s in store.sorted_records(core.statements_of_period(period["id"]))
                if s["payment_status"] in SWEEPABLE_PAYMENT_STATUSES
                and s["total_due_cents"] > 0]
    # compliance_standing as it stood when the sweep began (PRD 3.5)
    standing_at_start = dict(
        (b["id"], b["compliance_standing"])
        for b in core.businesses_of_district(district["id"]))

    for statement in selected:
        outstanding = max(statement["effective_assessment_cents"]
                          - statement["principal_paid_cents"], 0)
        statement["penalty_cents"] = rhu_cents(Decimal(outstanding) * config.PENALTY_PCT)
        statement["interest_cents"] = rhu_cents(
            Decimal(outstanding) * config.DAILY_INTEREST_PCT * Decimal(days_late))

        business = core.business_of_statement(statement)
        was_suspended = standing_at_start.get(business["id"]) == "SUSPENDED"
        if outstanding >= config.LIEN_THRESHOLD_CENTS or was_suspended:
            statement["delinquency_stage"] = "LIEN_REFERRED"
        else:
            statement["delinquency_stage"] = "NOTICE"
        core.derive_payment_status(statement)
        touch(statement)

        # hop three: the strike and the standing it re-derives
        previous_standing = business["compliance_standing"]
        business["delinquency_strike_count"] = business["delinquency_strike_count"] + 1
        strikes = business["delinquency_strike_count"]
        if strikes >= config.STRIKE_SUSPENDED:
            business["compliance_standing"] = "SUSPENDED"
        elif strikes == config.STRIKE_WATCH:
            business["compliance_standing"] = "WATCH"
        else:
            business["compliance_standing"] = "GOOD"
        touch(business)

        # hop four: a property that has just reached SUSPENDED loses its signatures
        if (business["compliance_standing"] == "SUSPENDED"
                and previous_standing != "SUSPENDED"):
            core.disqualify_signatures(business, "COMPLIANCE_SUSPENDED")

    core.recompute_district_money(district)
    period["status"] = "DELINQUENCY_SWEPT"
    touch(period)
    return envelope.ok(serialize.period(period))
