"""Audit cases, settlement negotiation and fee assessments (PRD 3.9)."""

from flask import Blueprint

import access
import calc
import db
import serializers
import services
from core import (
    ASSESSMENT_KINDS,
    ASSESSMENT_STATUSES,
    AUDIT_STATUSES,
    AUDIT_TRIGGERS,
    CLOSED_REASONS,
    MAX_DISPUTE_ROUNDS,
    ROLE_ADMIN,
    ROLE_AUDITOR,
    ROLE_OFFICER,
    ROLE_OPERATOR,
    Ladder,
    P_BODY_REFERENCE,
    P_DEPARTURE_STATE,
    P_DISPUTE_BOUND,
    P_EFFECTIVE_SCHEDULE,
    P_INTERVAL,
    P_LOOKBACK_ELAPSED,
    P_PAYMENT_CEILING,
    P_REQUEST_SHAPE,
    P_SEGREGATION,
    P_SETTLEMENT_FLOOR,
    P_SETTLE_ASSESSMENT,
    ApiError,
    authenticate,
    conflict,
    fk_array_candidates,
    fk_candidate,
    forbidden,
    invalid_interval,
    not_found,
    paginate,
    query_enum,
    query_str,
    read_body,
    read_pagination,
    respond_list,
    respond_object,
    rhu,
    validate_fields,
)

bp = Blueprint("audit", __name__)

CASE_CREATE_SPEC = [
    ("venue_id", "str", {"required": True}),
    ("audit_trigger", "enum", {"required": True, "values": AUDIT_TRIGGERS}),
    ("lookback_start", "instant", {"required": True}),
    ("lookback_end", "instant", {"required": True}),
    ("society_ids", "id_array", {"required": True, "min_items": 1, "max_items": 4}),
]
CLOSE_SPEC = [("closed_reason", "enum", {"required": True, "values": CLOSED_REASONS})]
OFFER_SPEC = [
    ("offer_amount_cents", "int", {"required": True, "min": 0}),
    ("payment_plan_months", "int", {"nullable": True, "min": 1, "default": None}),
]
PAY_SPEC = [("amount_cents", "int", {"required": True, "min": 0})]


@bp.post("/licensing/audit-cases")
def create_case():
    user_id, role = authenticate([ROLE_AUDITOR])
    ladder = Ladder(user_id, role)
    body = read_body()
    state = {}

    @ladder.check(P_BODY_REFERENCE)
    def _body_refs():
        venue_id = fk_candidate(body, "venue_id")
        if venue_id is not None and db.venue(venue_id) is None:
            raise not_found(access.ERR_VENUE)
        # Elements are validated left to right, so the first element naming no
        # society determines the rejection (PRD 3.9).
        for society_id in fk_array_candidates(body, "society_ids"):
            if db.society(society_id) is None:
                raise not_found(access.ERR_SOCIETY)

    @ladder.check(P_REQUEST_SHAPE)
    def _shape():
        state["fields"] = validate_fields(body, CASE_CREATE_SPEC)

    @ladder.check(P_INTERVAL)
    def _interval():
        if state["fields"]["lookback_start"] >= state["fields"]["lookback_end"]:
            raise invalid_interval("lookback_start must be strictly before lookback_end.")

    ladder.run()
    fields = state["fields"]
    venue = db.venue(fields["venue_id"])
    row = db.new_row(
        "audit_cases",
        {
            "venue_id": fields["venue_id"],
            "audit_trigger": fields["audit_trigger"],
            "lookback_start": fields["lookback_start"],
            "lookback_end": fields["lookback_end"],
            "society_ids": list(fields["society_ids"]),
            "status": "OPEN",
            "unlicensed_month_count": 0,
            "back_license_exposure_cents": 0,
            "penalty_cents": 0,
            "pre_credit_total_cents": 0,
            "goodwill_credit_cents": 0,
            "settlement_total_cents": 0,
            "settlement_floor_cents": 0,
            "offered_amount_cents": None,
            "payment_plan_months": None,
            "dispute_round": 0,
            "findings_issued_by_user_id": None,
            "settlement_proposed_by_user_id": None,
            "settled_by_user_id": None,
            "closed_reason": None,
        },
    )
    # Opening a case raises the venue's audit hold.
    services.recompute_venue(venue, audit_hold=True)
    return respond_object(serializers.case_json(row), 201)


@bp.post("/licensing/audit-cases/<audit_case_id>/findings")
def issue_findings(audit_case_id):
    user_id, role = authenticate([ROLE_AUDITOR])
    ladder = Ladder(user_id, role)
    case = access.fetch("audit_cases", audit_case_id, access.ERR_CASE, narrow=False)
    venue = db.venue(case["venue_id"])
    state = {}

    @ladder.check(P_DEPARTURE_STATE)
    def _departure():
        if case["status"] != "OPEN":
            raise conflict(
                "ERR_AUDIT_CASE_STATE_INVALID", "Only an OPEN case may have findings issued."
            )

    @ladder.check(P_LOOKBACK_ELAPSED)
    def _elapsed():
        if case["lookback_end"] > db.now():
            raise conflict(
                "ERR_AUDIT_CASE_STATE_INVALID",
                "An audit cannot conclude over a period that has not finished.",
            )

    @ladder.check(P_EFFECTIVE_SCHEDULE)
    def _schedules():
        chosen = {}
        for society_id in case["society_ids"]:
            schedule = calc.select_schedule(society_id, venue["venue_category"])
            if schedule is None:
                raise conflict(
                    "ERR_NO_EFFECTIVE_RATE_SCHEDULE",
                    "No EFFECTIVE rate schedule covers one of the societies in scope.",
                )
            chosen[society_id] = schedule
        state["schedules"] = chosen

    ladder.run()
    schedules = state["schedules"]
    months = calc.whole_months(case["lookback_start"], case["lookback_end"])
    societies = [db.society(society_id) for society_id in case["society_ids"]]
    societies = [row for row in societies if row is not None]
    societies.sort(key=lambda row: (row["created_at"], row["_seq"]))

    unlicensed_month_count = 0
    back_license_exposure_cents = 0
    for society in societies:
        schedule = schedules[society["id"]]
        annual = calc.annual_fee(
            schedule,
            society,
            venue["seating_capacity"],
            venue["standing_capacity"],
            venue["annual_cover_revenue_cents"],
            venue["weekly_live_performance_nights"],
            venue["music_use_profile"],
        )
        # The monthly instalment is rounded before any summing takes place.
        monthly = rhu(annual, 12)
        for month_start in months:
            if calc.month_covered(venue["id"], society["id"], month_start):
                continue
            unlicensed_month_count += 1
            back_license_exposure_cents += monthly

    waterfall = calc.settlement_waterfall(back_license_exposure_cents, unlicensed_month_count)
    case["unlicensed_month_count"] = unlicensed_month_count
    case["back_license_exposure_cents"] = back_license_exposure_cents
    case.update(waterfall)
    case["findings_issued_by_user_id"] = user_id
    case["status"] = "FINDINGS_ISSUED"
    db.touch(case)

    if case["pre_credit_total_cents"] > 0:
        services.issue_assessment(
            venue, None, case["id"], "AUDIT_BACK_LICENSE", case["pre_credit_total_cents"]
        )
        services.recompute_venue(venue, ledger=True)
        services.delinquency_sweep(venue)

    return respond_object(serializers.case_json(case))


@bp.post("/licensing/audit-cases/<audit_case_id>/close")
def close_case(audit_case_id):
    user_id, role = authenticate([ROLE_AUDITOR])
    ladder = Ladder(user_id, role)
    case = access.fetch("audit_cases", audit_case_id, access.ERR_CASE, narrow=False)
    body = read_body()
    state = {}

    @ladder.check(P_REQUEST_SHAPE)
    def _shape():
        state["fields"] = validate_fields(body, CLOSE_SPEC)

    @ladder.check(P_DEPARTURE_STATE)
    def _departure():
        if case["status"] != "OPEN":
            raise conflict("ERR_AUDIT_CASE_STATE_INVALID", "Only an OPEN case may be closed.")

    ladder.run()
    case["status"] = "CLOSED_NO_ACTION"
    case["closed_reason"] = state["fields"]["closed_reason"]
    db.touch(case)
    services.recompute_venue(db.venue(case["venue_id"]), audit_hold=True)
    return respond_object(serializers.case_json(case))


def back_license_assessment(case_id):
    for row in db.where("assessments", audit_case_id=case_id):
        if row["assessment_kind"] == "AUDIT_BACK_LICENSE":
            return row
    return None


@bp.post("/licensing/audit-cases/<audit_case_id>/settlement-offer")
def propose_settlement(audit_case_id):
    user_id, role = authenticate([ROLE_OFFICER])
    ladder = Ladder(user_id, role)
    case = access.fetch("audit_cases", audit_case_id, access.ERR_CASE, narrow=False)
    body = read_body()
    state = {}

    @ladder.check(P_REQUEST_SHAPE)
    def _shape():
        state["fields"] = validate_fields(body, OFFER_SPEC)

    @ladder.check(P_DEPARTURE_STATE)
    def _departure():
        if case["status"] not in ("FINDINGS_ISSUED", "DISPUTED"):
            raise conflict(
                "ERR_AUDIT_CASE_STATE_INVALID",
                "An offer may only be made on a FINDINGS_ISSUED or DISPUTED case.",
            )

    @ladder.check(P_SEGREGATION)
    def _segregation():
        if case["findings_issued_by_user_id"] == user_id:
            raise ApiError(
                "ERR_SEGREGATION_OF_DUTIES",
                403,
                "The auditor who issued findings may not negotiate the settlement.",
            )

    @ladder.check(P_SETTLEMENT_FLOOR)
    def _floor():
        if state["fields"]["offer_amount_cents"] < case["settlement_floor_cents"]:
            raise conflict(
                "ERR_SETTLEMENT_BELOW_FLOOR",
                "The offer is below the case's settlement floor.",
            )

    ladder.run()
    case["status"] = "SETTLEMENT_PROPOSED"
    case["offered_amount_cents"] = state["fields"]["offer_amount_cents"]
    case["payment_plan_months"] = state["fields"]["payment_plan_months"]
    case["settlement_proposed_by_user_id"] = user_id
    db.touch(case)
    return respond_object(serializers.case_json(case))


@bp.post("/licensing/audit-cases/<audit_case_id>/dispute")
def dispute_settlement(audit_case_id):
    user_id, role = authenticate([ROLE_OPERATOR, ROLE_ADMIN])
    ladder = Ladder(user_id, role)
    case = access.fetch("audit_cases", audit_case_id, access.ERR_CASE)

    @ladder.check(P_DEPARTURE_STATE)
    def _departure():
        if case["status"] != "SETTLEMENT_PROPOSED":
            raise conflict(
                "ERR_AUDIT_CASE_STATE_INVALID",
                "Only a SETTLEMENT_PROPOSED case may be disputed.",
            )

    @ladder.check(P_DISPUTE_BOUND)
    def _bound():
        if case["dispute_round"] >= MAX_DISPUTE_ROUNDS:
            raise conflict(
                "ERR_DISPUTE_LIMIT_REACHED", "This case has exhausted its disputes."
            )

    ladder.run()
    case["status"] = "DISPUTED"
    case["dispute_round"] += 1
    case["offered_amount_cents"] = None
    case["payment_plan_months"] = None
    db.touch(case)
    return respond_object(serializers.case_json(case))


@bp.post("/licensing/audit-cases/<audit_case_id>/settle")
def settle_case(audit_case_id):
    user_id, role = authenticate([ROLE_OFFICER])
    ladder = Ladder(user_id, role)
    case = access.fetch("audit_cases", audit_case_id, access.ERR_CASE, narrow=False)
    venue = db.venue(case["venue_id"])
    state = {}

    @ladder.check(P_DEPARTURE_STATE)
    def _departure():
        if case["status"] != "SETTLEMENT_PROPOSED":
            raise conflict(
                "ERR_AUDIT_CASE_STATE_INVALID",
                "Only a SETTLEMENT_PROPOSED case may be accepted.",
            )

    @ladder.check(P_SEGREGATION)
    def _segregation():
        if case["findings_issued_by_user_id"] == user_id:
            raise ApiError(
                "ERR_SEGREGATION_OF_DUTIES",
                403,
                "The auditor who issued findings may not accept the settlement.",
            )

    @ladder.check(P_SETTLE_ASSESSMENT)
    def _assessment():
        assessment = back_license_assessment(case["id"])
        if assessment is None or assessment["status"] != "ISSUED":
            raise conflict(
                "ERR_ASSESSMENT_NOT_ISSUED",
                "The case's back-licence assessment is no longer ISSUED.",
            )
        state["assessment"] = assessment

    ladder.run()
    assessment = state["assessment"]
    offered = case["offered_amount_cents"]
    case["status"] = "SETTLED"
    case["settled_by_user_id"] = user_id
    db.touch(case)

    # The shortfall between the assessed amount and the accepted offer moves to
    # voided_amount_cents, which is what keeps the ledger identity of PRD 2.9.
    assessment["status"] = "SETTLED"
    assessment["paid_amount_cents"] = offered
    db.touch(assessment)

    services.recompute_venue(venue, ledger=True, audit_hold=True)
    services.relieve_venue_billing(venue)
    return respond_object(serializers.case_json(case))


@bp.get("/licensing/audit-cases")
def list_cases():
    authenticate([ROLE_ADMIN, ROLE_OPERATOR, ROLE_AUDITOR, ROLE_OFFICER])
    limit, offset = read_pagination()
    venue_id = query_str("venue_id")
    audit_trigger = query_enum("audit_trigger", AUDIT_TRIGGERS)
    status = query_enum("status", AUDIT_STATUSES)
    rows = []
    for row in access.narrow_rows("audit_cases", db.ordered("audit_cases")):
        if venue_id is not None and row["venue_id"] != venue_id:
            continue
        if audit_trigger is not None and row["audit_trigger"] != audit_trigger:
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    page, total = paginate(rows, limit, offset)
    return respond_list([serializers.case_json(row) for row in page], limit, offset, total)


@bp.get("/licensing/audit-cases/<audit_case_id>")
def read_case(audit_case_id):
    authenticate([ROLE_ADMIN, ROLE_OPERATOR, ROLE_AUDITOR, ROLE_OFFICER])
    row = access.fetch("audit_cases", audit_case_id, access.ERR_CASE)
    return respond_object(serializers.case_json(row))


# ---------------------------------------------------------------------------
# Fee assessments (PRD 3.9)
# ---------------------------------------------------------------------------


@bp.post("/licensing/fee-assessments/<assessment_id>/pay")
def pay_assessment(assessment_id):
    user_id, role = authenticate([ROLE_OPERATOR, ROLE_ADMIN])
    ladder = Ladder(user_id, role)
    assessment = access.fetch("assessments", assessment_id, access.ERR_ASSESSMENT)
    venue = db.venue(assessment["venue_id"])
    body = read_body()
    state = {}

    @ladder.check(P_REQUEST_SHAPE)
    def _shape():
        state["fields"] = validate_fields(body, PAY_SPEC)

    @ladder.check(P_DEPARTURE_STATE)
    def _departure():
        if assessment["status"] != "ISSUED":
            raise conflict(
                "ERR_ASSESSMENT_NOT_ISSUED", "Only an ISSUED assessment may be paid."
            )

    @ladder.check(P_PAYMENT_CEILING)
    def _ceiling():
        remainder = assessment["amount_cents"] - assessment["paid_amount_cents"]
        if state["fields"]["amount_cents"] > remainder:
            raise conflict(
                "ERR_PAYMENT_EXCEEDS_BALANCE",
                "The payment exceeds the assessment's unpaid remainder.",
            )

    ladder.run()
    amount = state["fields"]["amount_cents"]
    assessment["paid_amount_cents"] += amount
    if assessment["paid_amount_cents"] >= assessment["amount_cents"]:
        assessment["status"] = "PAID"
    db.touch(assessment)

    services.recompute_venue(venue, ledger=True)
    if assessment["license_id"] is None:
        # A back-licence bill belongs to no single licence, so the relief sweep
        # runs venue-wide.
        services.relieve_venue_billing(venue)
    else:
        services.relieve_license_billing(venue, db.license_row(assessment["license_id"]))
    return respond_object(serializers.assessment_json(assessment))


@bp.get("/licensing/fee-assessments")
def list_assessments():
    authenticate([ROLE_ADMIN, ROLE_OPERATOR, ROLE_AUDITOR, ROLE_OFFICER])
    limit, offset = read_pagination()
    venue_id = query_str("venue_id")
    license_id = query_str("license_id")
    audit_case_id = query_str("audit_case_id")
    assessment_kind = query_enum("assessment_kind", ASSESSMENT_KINDS)
    status = query_enum("status", ASSESSMENT_STATUSES)
    rows = []
    for row in access.narrow_rows("assessments", db.ordered("assessments")):
        if venue_id is not None and row["venue_id"] != venue_id:
            continue
        if license_id is not None and row["license_id"] != license_id:
            continue
        if audit_case_id is not None and row["audit_case_id"] != audit_case_id:
            continue
        if assessment_kind is not None and row["assessment_kind"] != assessment_kind:
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    page, total = paginate(rows, limit, offset)
    return respond_list([serializers.assessment_json(row) for row in page], limit, offset, total)


@bp.get("/licensing/fee-assessments/<assessment_id>")
def read_assessment(assessment_id):
    authenticate([ROLE_ADMIN, ROLE_OPERATOR, ROLE_AUDITOR, ROLE_OFFICER])
    row = access.fetch("assessments", assessment_id, access.ERR_ASSESSMENT)
    return respond_object(serializers.assessment_json(row))
