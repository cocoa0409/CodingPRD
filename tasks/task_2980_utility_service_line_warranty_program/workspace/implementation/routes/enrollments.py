"""Enrollments: admission gates, the coverage clock, billing and settlement."""

from datetime import date

from flask import Blueprint

import config
import derive
import serializers
import timeutil
from errors import ApiError
from response import object_response, paginate
from routes.campaigns import lookup_campaign
from routes.premises import lookup_premises
from routes.products import lookup_product
from services import calc, cascades
from store import create_record, ordered, store, touch
from validation import Field, current_user_id, filter_enum, filter_value, parse_body, require_path_uuid, require_role

bp = Blueprint("enrollments", __name__)

READ_ROLES = (
    config.ROLE_PLATFORM_ADMIN,
    config.ROLE_MARKETING_OPS,
    config.ROLE_CUSTOMER_SERVICE_REP,
    config.ROLE_BILLING_OPS,
    config.ROLE_CLAIMS_ADJUSTER,
    config.ROLE_APPEALS_OFFICER,
    config.ROLE_REGULATORY_AFFAIRS,
    config.ROLE_OPERATIONS_ADMIN,
)
SINGLE_READ_ROLES = READ_ROLES + (config.ROLE_POLICYHOLDER,)

CREATE_SPEC = {
    "premises_id": Field("uuid", required=True),
    "product_id": Field("uuid", required=True),
    "billing_mode": Field("enum", required=True, enum=config.BILLING_MODES),
    "expected_premises_version": Field("integer", required=True),
    "source_campaign_id": Field("uuid"),
    "prepaid_amount_cents": Field("integer", minimum=0),
}

BILLING_SPEC = {
    "event_type": Field("enum", required=True, enum=config.BILLING_EVENT_TYPES),
    "effective_date": Field("date", required=True),
    "amount_cents": Field("integer", minimum=0),
    "memo": Field("string", max_len=500),
}

RENEWAL_SPEC = {
    "new_price_cents": Field("integer", required=True, minimum=0),
    "renewal_effective_date": Field("date", required=True),
    "expected_enrollment_version": Field("integer", required=True),
}

CANCELLATION_SPEC = {
    "reason": Field("enum", required=True, enum=config.CANCELLATION_REASONS),
    "requested_effective_date": Field("date", required=True),
}


def lookup_enrollment(enrollment_id):
    enrollment = store.enrollments.get(enrollment_id)
    if enrollment is None:
        raise ApiError("ERR_ENROLLMENT_NOT_FOUND", "No enrollment with id %s" % enrollment_id)
    return enrollment


def guard_not_terminal(enrollment):
    if enrollment["coverage_status"] in ("CANCELLED", "LAPSED"):
        raise ApiError("ERR_ENROLLMENT_TERMINAL", "The policy is %s" % enrollment["coverage_status"])


@bp.post("/enrollments")
def create_enrollment():
    current_user_id()
    require_role(config.ROLE_CUSTOMER_SERVICE_REP)
    body = parse_body(CREATE_SPEC)

    premises = lookup_premises(body["premises_id"])
    product = lookup_product(body["product_id"])
    campaign = lookup_campaign(body["source_campaign_id"]) if body["source_campaign_id"] else None

    if body["expected_premises_version"] != premises["version"]:
        raise ApiError("ERR_STALE_PREMISES_VERSION", "The premises has changed since it was read")

    partner = store.partners.get(product["partner_id"])
    if partner is None or partner["status"] != "ACTIVE":
        raise ApiError("ERR_PARTNER_NOT_ACTIVE", "The sponsoring partner is not ACTIVE")
    if product["status"] != "AVAILABLE":
        raise ApiError("ERR_PRODUCT_WITHDRAWN", "The product has been withdrawn")
    if campaign is not None:
        if campaign["status"] != "MAILED":
            raise ApiError("ERR_CAMPAIGN_NOT_MAILED", "The sourcing campaign has not been mailed")
        if premises["last_mailed_campaign_id"] != campaign["id"] or premises["last_mail_decision"] == "SUPPRESSED":
            raise ApiError("ERR_MAILING_SUPPRESSED", "The campaign did not mail this address")
    if body["billing_mode"] == "BILL_INSERT" and not partner["bill_insert_supported"]:
        raise ApiError("ERR_BILL_INSERT_NOT_SUPPORTED", "The partner does not support bill-insert billing")
    if product["required_owned_segment"] not in premises["owned_segments"]:
        raise ApiError("ERR_OWNERSHIP_NOT_ELIGIBLE", "The address does not own the required segment")
    for existing in derive.enrollments_of_premises(premises["id"]):
        if existing["product_id"] == product["id"] and existing["coverage_status"] in config.LIVE_COVERAGE_STATUSES:
            raise ApiError("ERR_DUPLICATE_ACTIVE_ENROLLMENT", "The address already holds a live policy on this product")

    term_start = store.today()
    term_end = timeutil.add_months(term_start, config.TERM_MONTHS)
    monthly_price = product["monthly_price_cents"]
    if body["prepaid_amount_cents"] is not None:
        prepaid = body["prepaid_amount_cents"]
    elif body["billing_mode"] == "DIRECT_BILL":
        prepaid = monthly_price * config.TERM_MONTHS
    else:
        prepaid = 0
    if product["cap_reset_basis"] == "CALENDAR_YEAR":
        cap_year_start = date(term_start.year, 1, 1)
    else:
        cap_year_start = term_start
    coverage_effective = timeutil.date_to_instant(timeutil.add_days(term_start, product["waiting_period_days"]))

    record = create_record(
        store.enrollments,
        {
            "premises_id": premises["id"],
            "product_id": product["id"],
            "source_campaign_id": campaign["id"] if campaign else None,
            "billing_mode": body["billing_mode"],
            "enrollment_date": store.now_iso(),
            "term_start": timeutil.render_date(term_start),
            "term_end": timeutil.render_date(term_end),
            "coverage_effective_at": timeutil.render_instant(coverage_effective),
            "coverage_status": "PENDING_WAITING_PERIOD",
            "billing_status": "CURRENT",
            "cap_status": "WITHIN_CAP",
            "monthly_price_cents": monthly_price,
            "prepaid_amount_cents": prepaid,
            "cap_year_start": timeutil.render_date(cap_year_start),
            "past_due_since": None,
            "retention_hold": False,
            "renewal_price_cents": None,
            "renewal_effective_date": None,
            "renewal_notice_sent_at": None,
            "renewal_notice_status": "NONE",
            "renewal_count": 0,
            "cancellation_effective_date": None,
            "cancellation_reason": None,
            "refund_cents": None,
            "credit_cents": None,
            "cancellation_fee_cents": None,
        },
    )
    # The address's standing suppression is re-derived; its version rises with it.
    touch(premises)
    return object_response(serializers.enrollment(record), 201)


@bp.get("/enrollments")
def list_enrollments():
    current_user_id()
    require_role(*READ_ROLES)
    premises_id = filter_value("premises_id")
    product_id = filter_value("product_id")
    campaign_id = filter_value("source_campaign_id")
    coverage_status = filter_enum("coverage_status", config.COVERAGE_STATUSES)

    def matches(enrollment):
        if premises_id is not None and enrollment["premises_id"] != premises_id:
            return False
        if product_id is not None and enrollment["product_id"] != product_id:
            return False
        if campaign_id is not None and enrollment["source_campaign_id"] != campaign_id:
            return False
        if coverage_status is not None and enrollment["coverage_status"] != coverage_status:
            return False
        return True

    return paginate(ordered(store.enrollments, matches), serializers.enrollment)


@bp.get("/enrollments/<enrollment_id>")
def get_enrollment(enrollment_id):
    current_user_id()
    require_role(*SINGLE_READ_ROLES)
    require_path_uuid(enrollment_id)
    return object_response(serializers.enrollment(lookup_enrollment(enrollment_id)))


@bp.post("/enrollments/<enrollment_id>/billing-events")
def post_billing_event(enrollment_id):
    current_user_id()
    require_role(config.ROLE_BILLING_OPS)
    require_path_uuid(enrollment_id)
    body = parse_body(BILLING_SPEC)
    event_type = body["event_type"]
    if event_type in config.BILLING_EVENTS_REQUIRING_AMOUNT and body["amount_cents"] is None:
        raise ApiError("ERR_INVALID_REQUEST", "amount_cents is required for a %s event" % event_type)

    enrollment = lookup_enrollment(enrollment_id)
    guard_not_terminal(enrollment)

    effective_date = body["effective_date"]
    amount = body["amount_cents"]

    if event_type == "MISSED_PAYMENT":
        if enrollment["billing_status"] == "CURRENT" and enrollment["coverage_status"] in (
            "PENDING_WAITING_PERIOD",
            "ACTIVE",
        ):
            enrollment["billing_status"] = "PAST_DUE"
            enrollment["past_due_since"] = timeutil.render_date(effective_date)
    elif event_type in ("PREMIUM_PAYMENT", "INSERT_REMITTANCE"):
        cascades.post_ledger(
            enrollment,
            event_type,
            amount,
            effective_date,
            memo=body["memo"],
        )
        if enrollment["billing_status"] == "PAST_DUE" and amount >= enrollment["monthly_price_cents"]:
            enrollment["billing_status"] = "CURRENT"
            enrollment["past_due_since"] = None
            if enrollment["coverage_status"] == "SUSPENDED_NONPAY":
                enrollment["coverage_status"] = "ACTIVE"
    else:  # WRITE_OFF
        cascades.post_ledger(
            enrollment,
            "WRITE_OFF",
            -abs(amount),
            effective_date,
            memo=body["memo"],
        )
        if enrollment["billing_status"] == "PAST_DUE":
            enrollment["billing_status"] = "WRITTEN_OFF"

    touch(enrollment)
    return object_response(serializers.enrollment(enrollment))


@bp.post("/enrollments/<enrollment_id>/renewal-notices")
def post_renewal_notice(enrollment_id):
    current_user_id()
    require_role(config.ROLE_BILLING_OPS)
    require_path_uuid(enrollment_id)
    body = parse_body(RENEWAL_SPEC)
    enrollment = lookup_enrollment(enrollment_id)

    if body["expected_enrollment_version"] != enrollment["version"]:
        raise ApiError("ERR_STALE_ENROLLMENT_VERSION", "The policy has changed since it was read")
    guard_not_terminal(enrollment)

    pct = calc.renewal_change_pct(enrollment["monthly_price_cents"], body["new_price_cents"])
    required_days = calc.required_notice_days(pct)
    lead_days = timeutil.whole_days_between(store.today(), body["renewal_effective_date"])
    if lead_days < required_days:
        raise ApiError(
            "ERR_INSUFFICIENT_RENEWAL_NOTICE",
            "A change of %s percent requires %d days of notice" % (pct, required_days),
        )
    partner = derive.partner_of_enrollment(enrollment)
    if partner is not None and partner["rate_filing_required"] and pct > config.RATE_FILING_PCT_THRESHOLD:
        raise ApiError("ERR_RATE_FILING_REQUIRED", "A rate filing is required before noticing this increase")

    enrollment["renewal_price_cents"] = body["new_price_cents"]
    enrollment["renewal_effective_date"] = timeutil.render_date(body["renewal_effective_date"])
    enrollment["renewal_notice_sent_at"] = store.now_iso()
    enrollment["renewal_notice_status"] = "SENT"
    touch(enrollment)
    return object_response(serializers.enrollment(enrollment))


@bp.post("/enrollments/<enrollment_id>/cancellation")
def cancel_enrollment(enrollment_id):
    current_user_id()
    require_role(config.ROLE_CUSTOMER_SERVICE_REP)
    require_path_uuid(enrollment_id)
    body = parse_body(CANCELLATION_SPEC)
    enrollment = lookup_enrollment(enrollment_id)
    guard_not_terminal(enrollment)

    term_start = timeutil.parse_date(enrollment["term_start"])
    term_end = timeutil.parse_date(enrollment["term_end"])
    effective = body["requested_effective_date"]
    if effective < term_start or effective > term_end:
        raise ApiError("ERR_INVALID_REQUEST", "requested_effective_date must fall inside the policy term")
    if enrollment.get("retention_hold"):
        raise ApiError("ERR_CANCELLATION_BLOCKED_APPEAL", "An appeal is open on this policy")

    settlement = calc.cancellation_settlement(
        enrollment, enrollment["monthly_price_cents"], term_start, effective
    )
    if enrollment["billing_mode"] == "DIRECT_BILL" and settlement["refund_cents"] < 0:
        raise ApiError("ERR_REFUND_NOT_AVAILABLE", "The earned premium and fee exceed the prepayment")

    enrollment["cancellation_effective_date"] = timeutil.render_date(effective)
    enrollment["cancellation_reason"] = body["reason"]
    enrollment["refund_cents"] = settlement["refund_cents"]
    enrollment["credit_cents"] = settlement["credit_cents"]
    enrollment["cancellation_fee_cents"] = settlement["cancellation_fee_cents"]
    enrollment["coverage_status"] = "CANCELLED"

    if enrollment["billing_mode"] == "DIRECT_BILL":
        cascades.post_ledger(enrollment, "PRORATION_REFUND", -settlement["refund_cents"], effective)
        enrollment["billing_status"] = "REFUND_ISSUED"
    else:
        cascades.post_ledger(enrollment, "PRORATION_CREDIT", -settlement["credit_cents"], effective)
        enrollment["billing_status"] = "CREDIT_ISSUED"
    if settlement["cancellation_fee_cents"]:
        cascades.post_ledger(enrollment, "CANCELLATION_FEE", settlement["cancellation_fee_cents"], effective)

    touch(enrollment)
    cascades.cancel_open_dispatches_of_enrollment(enrollment, "CLAIM_DENIED")
    return object_response(serializers.enrollment(enrollment))
