"""Regulator complaints: intake, the response with its remedy, and escalation."""

from flask import Blueprint

import config
import derive
import serializers
import timeutil
from errors import ApiError
from response import object_response, paginate
from routes.claims import lookup_claim
from routes.enrollments import lookup_enrollment
from routes.partners import lookup_partner
from services import calc, cascades
from store import create_record, ordered, store, touch
from validation import Field, current_user_id, filter_enum, filter_value, parse_body, require_path_uuid, require_role

bp = Blueprint("complaints", __name__)

READ_ROLES = (
    config.ROLE_PLATFORM_ADMIN,
    config.ROLE_CLAIMS_ADJUSTER,
    config.ROLE_APPEALS_OFFICER,
    config.ROLE_REGULATORY_AFFAIRS,
    config.ROLE_OPERATIONS_ADMIN,
)

CREATE_SPEC = {
    "partner_id": Field("uuid", required=True),
    "regulator": Field("enum", required=True, enum=config.REGULATORS),
    "allegation": Field("string", required=True, min_len=1, max_len=1000),
    "claim_id": Field("uuid"),
    "enrollment_id": Field("uuid"),
}

RESPONSE_SPEC = {
    "response_summary": Field("string", required=True, min_len=1, max_len=1000),
    "disposition": Field("enum", required=True, enum=config.DISPOSITIONS),
    "remedy_type": Field("enum", required=True, enum=config.REMEDY_TYPES),
    "expected_complaint_version": Field("integer", required=True),
    "remedy_amount_cents": Field("integer", minimum=0),
}

ESCALATION_SPEC = {"escalation_note": Field("string", required=True, min_len=1, max_len=1000)}


def lookup_complaint(complaint_id):
    complaint = store.complaints.get(complaint_id)
    if complaint is None:
        raise ApiError("ERR_COMPLAINT_NOT_FOUND", "No regulator complaint with id %s" % complaint_id)
    return complaint


@bp.post("/regulator-complaints")
def create_complaint():
    current_user_id()
    require_role(config.ROLE_REGULATORY_AFFAIRS)
    body = parse_body(CREATE_SPEC)

    partner = lookup_partner(body["partner_id"])
    claim = lookup_claim(body["claim_id"]) if body["claim_id"] else None
    enrollment = lookup_enrollment(body["enrollment_id"]) if body["enrollment_id"] else None

    # The deadline is read from the cited claim's state before intake reopens it.
    received_at = store.now()
    days = calc.complaint_response_days(body["regulator"], claim)
    record = create_record(
        store.complaints,
        {
            "partner_id": partner["id"],
            "claim_id": claim["id"] if claim else None,
            "enrollment_id": enrollment["id"] if enrollment else None,
            "regulator": body["regulator"],
            "allegation": body["allegation"],
            "received_at": store.now_iso(),
            "response_due_at": timeutil.render_instant(timeutil.add_days(received_at, days)),
            "status": "OPEN",
            "responded_at": None,
            "response_summary": None,
            "disposition": None,
            "remedy_type": None,
            "remedy_amount_cents": None,
            "escalation_count": 0,
        },
    )

    # A regulator reopens a denied claim past every limit that binds a homeowner.
    if claim is not None and claim["status"] in config.COMPLAINT_EXPEDITING_CLAIM_STATUSES:
        cascades.open_appeal(claim, "REGULATOR")
    if enrollment is not None:
        premises = derive.premises_of_enrollment(enrollment)
        if premises is not None and not premises.get("regulator_hold"):
            premises["regulator_hold"] = True
            touch(premises)

    return object_response(serializers.complaint(record), 201)


@bp.get("/regulator-complaints")
def list_complaints():
    current_user_id()
    require_role(*READ_ROLES)
    partner_id = filter_value("partner_id")
    claim_id = filter_value("claim_id")
    enrollment_id = filter_value("enrollment_id")
    status = filter_enum("status", config.COMPLAINT_STATUSES)

    def matches(complaint):
        if partner_id is not None and complaint["partner_id"] != partner_id:
            return False
        if claim_id is not None and complaint["claim_id"] != claim_id:
            return False
        if enrollment_id is not None and complaint["enrollment_id"] != enrollment_id:
            return False
        if status is not None and complaint["status"] != status:
            return False
        return True

    return paginate(ordered(store.complaints, matches), serializers.complaint)


@bp.get("/regulator-complaints/<complaint_id>")
def get_complaint(complaint_id):
    current_user_id()
    require_role(*READ_ROLES)
    require_path_uuid(complaint_id)
    return object_response(serializers.complaint(lookup_complaint(complaint_id)))


@bp.post("/regulator-complaints/<complaint_id>/response")
def respond_to_complaint(complaint_id):
    current_user_id()
    require_role(config.ROLE_REGULATORY_AFFAIRS)
    require_path_uuid(complaint_id)
    body = parse_body(RESPONSE_SPEC)
    remedy = body["remedy_type"]
    if remedy in config.REMEDIES_REQUIRING_AMOUNT and body["remedy_amount_cents"] is None:
        raise ApiError("ERR_INVALID_REQUEST", "remedy_amount_cents is required for a %s remedy" % remedy)

    complaint = lookup_complaint(complaint_id)
    if body["expected_complaint_version"] != complaint["version"]:
        raise ApiError("ERR_STALE_COMPLAINT_VERSION", "The complaint has changed since it was read")
    if complaint["status"] not in config.OPEN_COMPLAINT_STATUSES:
        raise ApiError("ERR_INVALID_COMPLAINT_STATE", "The complaint is already closed")

    claim = store.claims.get(complaint["claim_id"]) if complaint["claim_id"] else None
    enrollment = store.enrollments.get(complaint["enrollment_id"]) if complaint["enrollment_id"] else None

    # A remedy must have something to act on.
    if remedy == "BENEFIT_REVERSAL" and claim is None:
        raise ApiError("ERR_REMEDY_TARGET_MISSING", "A benefit reversal needs a cited claim")
    if remedy in ("PREMIUM_REFUND", "REINSTATEMENT") and enrollment is None:
        raise ApiError("ERR_REMEDY_TARGET_MISSING", "That remedy needs a cited policy")
    if body["disposition"] == "UNSUBSTANTIATED" and remedy not in ("NONE", "APOLOGY_ONLY"):
        raise ApiError("ERR_REMEDY_NOT_PERMITTED", "An unsubstantiated finding may not move money")

    amount = body["remedy_amount_cents"]
    if remedy == "BENEFIT_REVERSAL":
        paid = derive.claim_benefit_paid_cents(claim)
        if amount > paid:
            raise ApiError("ERR_REVERSAL_EXCEEDS_BENEFIT", "The reversal exceeds the benefit posted on the claim")
        _apply_benefit_reversal(claim, amount)
    elif remedy == "PREMIUM_REFUND":
        cascades.post_ledger(enrollment, "PRORATION_REFUND", -abs(amount), store.today())
        enrollment["billing_status"] = "REFUND_ISSUED"
        touch(enrollment)
    elif remedy == "REINSTATEMENT":
        _apply_reinstatement(enrollment)

    complaint["responded_at"] = store.now_iso()
    complaint["response_summary"] = body["response_summary"]
    complaint["disposition"] = body["disposition"]
    complaint["remedy_type"] = remedy
    complaint["remedy_amount_cents"] = amount
    complaint["status"] = (
        "CLOSED_SUBSTANTIATED" if body["disposition"] == "SUBSTANTIATED" else "CLOSED_UNSUBSTANTIATED"
    )
    touch(complaint)

    # The address's regulator hold and standing suppression are re-derived.
    for target in (enrollment, store.enrollments.get(claim["enrollment_id"]) if claim else None):
        if target is not None:
            cascades.refresh_regulator_hold(derive.premises_of_enrollment(target))
    return object_response(serializers.complaint(complaint))


def _apply_benefit_reversal(claim, amount):
    """A compensating negative benefit row; it genuinely gives cap room back."""
    enrollment = derive.enrollment_of_claim(claim)
    cascades.post_ledger(
        enrollment, "BENEFIT_REVERSAL", -abs(amount), store.today(), claim_id=claim["id"]
    )
    touch(enrollment)
    cascades.refresh_cap_status(enrollment)


def _apply_reinstatement(enrollment):
    """The fullest reversal: cash, both dimensions and the term all return."""
    paid_out = abs(enrollment.get("refund_cents") or 0) + abs(enrollment.get("credit_cents") or 0)
    if paid_out:
        cascades.post_ledger(enrollment, "REFUND_CLAWBACK", paid_out, store.today())
    if enrollment["coverage_status"] == "CANCELLED":
        enrollment["coverage_status"] = "ACTIVE"
    enrollment["billing_status"] = "CURRENT"
    enrollment["cancellation_effective_date"] = None
    enrollment["cancellation_reason"] = None
    enrollment["refund_cents"] = None
    enrollment["credit_cents"] = None
    enrollment["cancellation_fee_cents"] = None
    term_start = timeutil.parse_date(enrollment["term_start"])
    months = config.TERM_MONTHS * (1 + enrollment.get("renewal_count", 0))
    enrollment["term_end"] = timeutil.render_date(timeutil.add_months(term_start, months))
    touch(enrollment)


@bp.post("/regulator-complaints/<complaint_id>/escalation")
def escalate_complaint(complaint_id):
    current_user_id()
    require_role(config.ROLE_REGULATORY_AFFAIRS)
    require_path_uuid(complaint_id)
    parse_body(ESCALATION_SPEC)
    complaint = lookup_complaint(complaint_id)

    if complaint["status"] != "CLOSED_UNSUBSTANTIATED":
        raise ApiError("ERR_INVALID_COMPLAINT_STATE", "Only an unsubstantiated closure may be escalated")

    complaint["status"] = "ESCALATED"
    complaint["escalation_count"] = complaint.get("escalation_count", 0) + 1
    # The file genuinely reopens rather than carrying a stale finding.
    complaint["responded_at"] = None
    complaint["response_summary"] = None
    complaint["disposition"] = None
    complaint["remedy_type"] = None
    complaint["remedy_amount_cents"] = None
    touch(complaint)

    if complaint["enrollment_id"]:
        enrollment = store.enrollments.get(complaint["enrollment_id"])
        premises = derive.premises_of_enrollment(enrollment) if enrollment is not None else None
        if premises is not None and not premises.get("regulator_hold"):
            premises["regulator_hold"] = True
            touch(premises)

    return object_response(serializers.complaint(complaint))
