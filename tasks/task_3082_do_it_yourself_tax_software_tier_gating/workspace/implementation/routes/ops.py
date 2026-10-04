"""Ops / test-driving endpoints: logical clock, authority callback, catalog seeds."""
from datetime import datetime

from flask import Blueprint

from core import (
    ApiError,
    REJECTION_CODES,
    TIER_CODES,
    db,
    endpoint,
    f_bool,
    f_enum,
    f_int,
    f_str,
    f_str_list,
    body,
    dump,
    new_row,
    paginate,
    parse_dt,
    respond_object,
    touch,
    bad_request,
)
import svc

bp = Blueprint("ops", __name__)


@bp.post("/tax/_clock/set_current_utc")
@endpoint("PlatformOperator")
def set_clock():
    payload = body()
    to_iso = f_str(payload, "to_iso8601")
    parsed = parse_dt(to_iso)
    if parsed is None:
        bad_request("Field 'to_iso8601' must be an ISO-8601 UTC timestamp.")
    db.clock = parsed
    from core import fmt_dt
    return respond_object({"current_utc": fmt_dt(db.clock)})


@bp.post("/tax/_authority/filing-callback")
@endpoint("PlatformOperator")
def filing_callback():
    payload = body()
    attempt_id = f_str(payload, "filing_attempt_id")
    outcome = f_enum(payload, "outcome", ("ACCEPTED", "REJECTED"))
    attempt = db.filing_attempts.get(attempt_id)
    if attempt is None:
        raise ApiError("ERR_NOT_FOUND", "filing_attempt_id does not exist.")
    rejection_code = None
    if outcome == "REJECTED":
        rejection_code = f_enum(payload, "rejection_code", REJECTION_CODES)
    if attempt["outcome"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", "The targeted filing attempt is not PENDING.")
    svc.resolve_attempt(attempt, outcome, rejection_code)
    return respond_object(dump(attempt))


@bp.post("/tax/_tiers/seed")
@endpoint("PlatformOperator")
def seed_tier():
    payload = body()
    code = f_enum(payload, "code", TIER_CODES)
    price = f_int(payload, "price_cents", minimum=0)
    state_price = f_int(payload, "state_addon_price_cents", minimum=0)
    supported = f_str_list(payload, "supported_forms", required=False, default=[])
    rank = f_int(payload, "tier_rank", minimum=0)
    existing = db.tiers.get(code)
    if existing is not None:
        if (
            existing["price_cents"] == price
            and existing["state_addon_price_cents"] == state_price
            and existing["supported_forms"] == supported
            and existing["tier_rank"] == rank
        ):
            return respond_object(dump(existing), status=201)
        raise ApiError("ERR_INVALID_REQUEST", "A ProductTier with this code already exists.")
    tier = new_row(
        "tier",
        audited=False,
        code=code,
        price_cents=price,
        state_addon_price_cents=state_price,
        supported_forms=supported,
        tier_rank=rank,
    )
    db.tiers[code] = tier
    return respond_object(dump(tier), status=201)


@bp.post("/tax/_forms/seed")
@endpoint("PlatformOperator")
def seed_form():
    payload = body()
    code = f_str(payload, "code")
    minimum_tier = f_enum(payload, "minimum_tier", TIER_CODES)
    disqualifies = f_bool(payload, "disqualifies_free_file")
    counts = f_bool(payload, "counts_toward_refund", required=False, default=False)
    existing = db.form_specs.get(code)
    if existing is not None:
        if (
            existing["minimum_tier"] == minimum_tier
            and existing["disqualifies_free_file"] == disqualifies
            and existing["counts_toward_refund"] == counts
        ):
            return respond_object(dump(existing), status=201)
        raise ApiError("ERR_INVALID_REQUEST", "A FormSpec with this code already exists.")
    spec = new_row(
        "form_spec",
        audited=False,
        code=code,
        minimum_tier=minimum_tier,
        disqualifies_free_file=disqualifies,
        counts_toward_refund=counts,
    )
    db.form_specs[code] = spec
    return respond_object(dump(spec), status=201)


@bp.get("/tax/tiers")
@endpoint("Taxpayer", "PlatformOperator", "ClaimsAdjuster")
def list_tiers():
    return paginate(list(db.tiers.values()))


@bp.get("/tax/form-specs")
@endpoint("Taxpayer", "PlatformOperator", "ClaimsAdjuster")
def list_form_specs():
    return paginate(list(db.form_specs.values()))


@bp.post("/tax/accounts/<account_id>/suspend")
@endpoint("PlatformOperator")
def suspend_account(account_id):
    acct = svc.get_account(account_id)
    if acct["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Account is not ACTIVE.")
    acct["status"] = "SUSPENDED"
    touch(acct)
    return respond_object(dump(acct))
