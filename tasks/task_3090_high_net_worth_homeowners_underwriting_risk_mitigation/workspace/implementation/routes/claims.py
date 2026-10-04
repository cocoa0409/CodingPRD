"""Claims, cash settlement and the settlement cascade (PRD §3.8)."""

from flask import Blueprint

import calc
import db
import reqs
from clock import fmt_dt, parse_dt
from errors import err
from middleware import authorize
from response import array, ok, paginate
from serialize import render, render_list
from services import core

bp = Blueprint("claims", __name__)

CAUSES = ("WILDFIRE", "WIND", "HALL", "WATER", "THEFT", "OTHER")
CLAIM_READERS = ("ClaimsAdjuster", "Underwriter", "ComplianceReporter", "PlatformAdmin",
                 "AgencyProducer", "RiskConsultant")
CLAIM_WRITERS = ("ClaimsAdjuster",)


def common_fields():
    now = fmt_dt(db.now())
    return {"id": db.new_id(), "created_at": now, "updated_at": now, "version": 1}


def _require_state(claim, states):
    if claim["status"] not in states:
        raise err("ERR_INVALID_STATE",
                  "Claim is not in a state from which this transition is declared.")


@bp.route("/hnw/enrollments/<enrollment_id>/claims", methods=["POST"])
def create_claim(enrollment_id):
    authorize(CLAIM_WRITERS)
    enrollment = core.get(db.ENROLLMENTS, enrollment_id, "Enrollment")
    data = reqs.body()
    loss_date = parse_dt(reqs.require(data, "loss_date"))
    if loss_date is None:
        raise err("ERR_INVALID_REQUEST", "loss_date must be an ISO 8601 instant.")
    # The claim names the enrollment supplied in the path, but the property's
    # standing policy of record must be the bound enrollment the coverage is
    # drawn from (PRD §3.8).
    of_record = core.attached_or_approved_enrollment(enrollment["property_id"])
    if of_record is not None:
        enrollment = of_record
    record = common_fields()
    record.update({
        "enrollment_id": enrollment["id"],
        "property_id": enrollment["property_id"],
        "cause_of_loss": reqs.enum(data, "cause_of_loss", CAUSES),
        "loss_date": loss_date,
        "reported_at": fmt_dt(db.now()),
        "reported_indemnity_cents": reqs.integer(data, "reported_indemnity_cents",
                                                 required=True, minimum=0),
        "adjuster_user_id": reqs.string(data, "adjuster_user_id", default=None),
        "adjuster_override": reqs.boolean(data, "adjuster_override", default=False),
        "settlement_amount_cents": 0,
        "deductible_applied_cents": 0,
        "limit_applied_cents": 0,
        "cash_settlement_eligible": False,
        "status": "REPORTED",
    })
    db.CLAIMS[record["id"]] = record
    return ok(render(record), status=201)


@bp.route("/hnw/enrollments/<enrollment_id>/claims", methods=["GET"])
def list_enrollment_claims(enrollment_id):
    authorize(CLAIM_READERS)
    core.get(db.ENROLLMENTS, enrollment_id, "Enrollment")
    limit, offset = reqs.pagination()
    rows = [c for c in db.CLAIMS.values() if c["enrollment_id"] == enrollment_id]
    rows = _filter_claims(rows)
    rows = reqs.sorted_by_created(rows)
    page, meta = paginate(rows, limit, offset)
    return array(render_list(page), meta)


@bp.route("/hnw/properties/<property_id>/claims", methods=["GET"])
def list_property_claims(property_id):
    authorize(CLAIM_READERS)
    core.get(db.PROPERTIES, property_id, "Property")
    limit, offset = reqs.pagination()
    rows = [c for c in db.CLAIMS.values() if c["property_id"] == property_id]
    rows = _filter_claims(rows)
    rows = reqs.sorted_by_created(rows)
    page, meta = paginate(rows, limit, offset)
    return array(render_list(page), meta)


@bp.route("/hnw/claims", methods=["GET"])
def list_claims():
    authorize(("ClaimsAdjuster", "Underwriter", "PlatformAdmin", "ComplianceReporter"))
    limit, offset = reqs.pagination()
    rows = list(db.CLAIMS.values())
    for field in ("enrollment_id", "property_id"):
        value = reqs.query(field)
        if value:
            rows = [c for c in rows if c.get(field) == value]
    rows = _filter_claims(rows)
    rows = reqs.sorted_by_created(rows)
    page, meta = paginate(rows, limit, offset)
    return array(render_list(page), meta)


def _filter_claims(rows):
    status = reqs.query("status")
    cause = reqs.query("cause_of_loss")
    if status:
        rows = [c for c in rows if c["status"] == status]
    if cause:
        rows = [c for c in rows if c["cause_of_loss"] == cause]
    return rows


@bp.route("/hnw/claims/<claim_id>/review", methods=["POST"])
def review_claim(claim_id):
    authorize(CLAIM_WRITERS)
    claim = core.get(db.CLAIMS, claim_id, "Claim")
    _require_state(claim, ("REPORTED",))
    enrollment = db.ENROLLMENTS.get(claim["enrollment_id"])
    if enrollment is None or enrollment["status"] != "ATTACHED":
        raise err("ERR_ENROLLMENT_NOT_BOUND",
                  "The parent enrollment is not ATTACHED.")
    claim["status"] = "UNDER_REVIEW"
    core.touch(claim)
    return ok(render(claim))


@bp.route("/hnw/claims/<claim_id>/approve", methods=["POST"])
def approve_claim(claim_id):
    authorize(CLAIM_WRITERS)
    claim = core.get(db.CLAIMS, claim_id, "Claim")
    _require_state(claim, ("UNDER_REVIEW",))
    if claim["adjuster_user_id"] is None:
        raise err("ERR_INVALID_STATE",
                  "An adjuster must be assigned before the claim may be approved.")
    enrollment = core.get(db.ENROLLMENTS, claim["enrollment_id"], "Enrollment")
    limit = calc.applicable_limit(enrollment)
    # Priority 13: the reported indemnity must not exceed the applicable limit.
    if limit is not None and claim["reported_indemnity_cents"] > limit:
        raise err("ERR_COVERAGE_ABOVE_APPRAISAL",
                  "The reported indemnity exceeds the applicable replacement-cost limit.")
    # Priority 24: the claim must be worth settling at all.
    deductible = calc.raw_deductible(claim["cause_of_loss"],
                                     enrollment["dwelling_coverage_cents"])
    if claim["reported_indemnity_cents"] <= deductible:
        raise err("ERR_CLAIM_BELOW_DEDUCTIBLE",
                  "The reported indemnity is at or below the deductible.")
    block = calc.settlement_block(enrollment, claim)
    claim["settlement_amount_cents"] = block["settlement_amount_cents"]
    claim["deductible_applied_cents"] = block["deductible_applied_cents"]
    claim["limit_applied_cents"] = block["limit_applied_cents"]
    claim["cash_settlement_eligible"] = block["cash_settlement_eligible"]
    claim["status"] = "APPROVED"
    core.touch(claim)
    return ok(render(claim))


@bp.route("/hnw/claims/<claim_id>/settle", methods=["POST"])
def settle_claim(claim_id):
    authorize(CLAIM_WRITERS)
    claim = core.get(db.CLAIMS, claim_id, "Claim")
    _require_state(claim, ("APPROVED",))
    if claim["settlement_amount_cents"] <= 0:
        raise err("ERR_INVALID_STATE",
                  "The settlement amount is not strictly greater than zero.")
    enrollment = core.get(db.ENROLLMENTS, claim["enrollment_id"], "Enrollment")
    claim["deductible_applied_cents"] = min(
        calc.raw_deductible(claim["cause_of_loss"], enrollment["dwelling_coverage_cents"]),
        claim["settlement_amount_cents"])
    claim["status"] = "SETTLED"
    core.touch(claim)
    # Settlement detaches every ATTACHED scheduled item of the property.
    for item in db.SCHEDULED_ITEMS.values():
        if item["property_id"] == claim["property_id"] and item["status"] == "ATTACHED":
            item["status"] = "APPROVED"
            item["attached_value_cents"] = 0
            core.touch(item)
    core.recompute_property(claim["property_id"])
    return ok(render(claim))


@bp.route("/hnw/claims/<claim_id>/pay", methods=["POST"])
def pay_claim(claim_id):
    authorize(CLAIM_WRITERS)
    claim = core.get(db.CLAIMS, claim_id, "Claim")
    _require_state(claim, ("SETTLED",))
    claim["status"] = "PAID"
    core.touch(claim)
    return ok(render(claim))


@bp.route("/hnw/claims/<claim_id>/deny", methods=["POST"])
def deny_claim(claim_id):
    authorize(CLAIM_WRITERS)
    claim = core.get(db.CLAIMS, claim_id, "Claim")
    data = reqs.body()
    if data.get("reason") is not None:
        reqs.string(data, "reason")
    _require_state(claim, ("REPORTED", "UNDER_REVIEW"))
    claim["status"] = "DENIED"
    core.touch(claim)
    return ok(render(claim))