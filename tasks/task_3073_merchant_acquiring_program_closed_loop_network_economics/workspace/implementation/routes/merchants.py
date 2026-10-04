"""Merchant onboarding, the acceptance cycle, declined attempts and gaps."""

from flask import Blueprint, request

from auth import authenticate, require_owned_by_caller, require_role
from db import STORE
from errors import ERR_INVALID_REQUEST, ERR_NOT_FOUND, ApiError
from paging import bool_arg, filter_arg, paginate, pagination, sort_rows
from response import ok_array, ok_object
from routes import _common
from services import gap_engine, merchant as merchant_service, risk
from validation import (
    body_object,
    optional_int,
    optional_string,
    require_datetime,
    require_enum,
    require_int,
    require_string,
)

bp = Blueprint("merchants", __name__)

ACQUISITION_CHANNELS = ("DIRECT", "THIRD_PARTY")
ACCEPTANCE_STATUSES = ("PROSPECT", "ACCEPTED", "ACTIVE", "DORMANT", "SUPPRESSED")
CARD_PRODUCTS = ("GREEN", "GOLD", "PLATINUM", "CENTURION")
DECLINE_REASONS = (
    "MERCHANT_NOT_ACCEPTED",
    "INSUFFICIENT_CREDIT",
    "FRAUD_SUSPECT",
    "EXPIRED_CARD",
)
QUALIFIED_STATUSES = ("PROSPECTING", "BELOW_THRESHOLD", "DORMANT")
GAP_WINDOW_DAYS = (30, 60, 90)

ACQUIRER = ["NetworkAcquirer"]
ACQUIRER_OR_COMPLIANCE = ["NetworkAcquirer", "NetworkCompliance"]
ACQUIRER_COMPLIANCE_OR_MERCHANT = ["NetworkAcquirer", "NetworkCompliance", "Merchant"]


# --- Merchant CRUD ---------------------------------------------------------

@bp.post("/merchants")
def create_merchant():
    caller = authenticate(STORE, request.headers)
    require_role(caller, ACQUIRER)
    body = body_object(
        request.get_json(silent=True) or {},
        {"industry_category_id", "merchant_name", "region_code", "acquisition_channel",
         "channel_partner", "negotiated_rate_bps"},
    )
    industry_category_id = require_string(body, "industry_category_id")
    merchant_name = require_string(body, "merchant_name")
    region_code = require_string(body, "region_code")
    acquisition_channel = require_enum(body, "acquisition_channel", ACQUISITION_CHANNELS)
    channel_partner = optional_string(body, "channel_partner", None)
    negotiated_rate_bps = optional_int(body, "negotiated_rate_bps", minimum=0, default=None)

    # Path/body identifiers resolve before anything else and use the
    # relationship-specific codes: an unknown industry category is ERR_NOT_FOUND.
    if industry_category_id not in STORE.industry_categories:
        raise ApiError(ERR_NOT_FOUND, "The referenced industry category does not exist.")

    if acquisition_channel == "THIRD_PARTY":
        if not channel_partner:
            raise ApiError(ERR_INVALID_REQUEST,
                           "channel_partner is required when acquisition_channel is THIRD_PARTY.")
    elif channel_partner is not None:
        raise ApiError(ERR_INVALID_REQUEST,
                       "channel_partner must be null when acquisition_channel is DIRECT.")

    if merchant_name in STORE.merchants_by_name:
        raise ApiError(ERR_INVALID_REQUEST, "merchant_name must be unique.")

    with STORE.lock:
        industry = STORE.industry_categories[industry_category_id]
        merchant_id = STORE.new_id()
        now = STORE.clock.now()
        row = {
            "id": merchant_id,
            "created_at": now,
            "updated_at": now,
            "version": 0,
            "_seq": STORE.next_created_seq(),
            "industry_category_id": industry_category_id,
            "merchant_name": merchant_name,
            "region_code": region_code,
            "acquisition_channel": acquisition_channel,
            "channel_partner": channel_partner,
            "volume_tier": "ACTIVITY",
            "acceptance_status": "PROSPECT",
            "applied_discount_rate_bps": 0,
            "billed_volume_mtd_cents": 0,
            "rolling_90d_billed_volume_cents": 0,
            "rolling_90d_settled_volume_cents": 0,
            "last_batch_discount_fee_cents": 0,
            "negotiated_rate_bps": negotiated_rate_bps,
            "reserve_required_cents": 0,
            "reserve_held_cents": 0,
            "status_version": 0,
        }
        STORE.merchants[merchant_id] = row
        STORE.merchants_by_name[merchant_name] = merchant_id
        risk.create_risk_state(STORE, merchant_id)

        # Pricing is stamped immediately: the negotiated rate when one was
        # supplied, the ACTIVITY-tier rate otherwise.
        industry_base = industry["base_discount_rate_bps"]
        row["applied_discount_rate_bps"] = (
            negotiated_rate_bps if negotiated_rate_bps is not None else industry_base
        )
    return ok_object(_common.render(row)), 201


@bp.get("/merchants/<merchant_id>")
def get_merchant(merchant_id):
    caller = authenticate(STORE, request.headers)
    require_role(caller, ACQUIRER_COMPLIANCE_OR_MERCHANT)
    row = _common.merchant(merchant_id)
    if caller.role == "Merchant":
        require_owned_by_caller(caller, row["id"])
    with STORE.lock:
        merchant_service.refresh_trailing(STORE, row)
    return ok_object(_common.render(row))


@bp.get("/merchants")
def list_merchants():
    caller = authenticate(STORE, request.headers)
    require_role(caller, ACQUIRER_OR_COMPLIANCE)
    limit, offset = pagination(request.args)
    acceptance_status = filter_arg(request.args, "acceptance_status", ACCEPTANCE_STATUSES)
    industry_category_id = filter_arg(request.args, "industry_category_id")

    rows = list(STORE.merchants.values())
    with STORE.lock:
        for row in rows:
            merchant_service.refresh_trailing(STORE, row)
    if acceptance_status is not None:
        rows = [row for row in rows if row["acceptance_status"] == acceptance_status]
    if industry_category_id is not None:
        rows = [row for row in rows if row["industry_category_id"] == industry_category_id]
    rows = sort_rows(rows, "created_at")
    total = len(rows)
    page = paginate(rows, limit, offset)
    return ok_array([_common.render(row) for row in page], total, limit, offset)


# --- Acceptance cycle ------------------------------------------------------

@bp.post("/merchants/<merchant_id>/accept")
def accept_merchant(merchant_id):
    caller = authenticate(STORE, request.headers)
    require_role(caller, ACQUIRER)
    body = body_object(request.get_json(silent=True) or {},
                       {"expected_merchant_version", "negotiated_rate_bps"})
    expected_version = optional_int(body, "expected_merchant_version", minimum=0, default=None)
    negotiated_rate_bps = optional_int(body, "negotiated_rate_bps", minimum=0, default=None)

    row = _common.merchant(merchant_id)
    with STORE.lock:
        merchant_service.accept_merchant(STORE, row, expected_version, negotiated_rate_bps)
    return ok_object(_common.render(row))


@bp.post("/merchants/<merchant_id>/activate")
def activate_merchant(merchant_id):
    caller = authenticate(STORE, request.headers)
    require_role(caller, ACQUIRER)
    body_object(request.get_json(silent=True) or {}, set())
    row = _common.merchant(merchant_id)
    with STORE.lock:
        merchant_service.activate_merchant(STORE, row)
    return ok_object(_common.render(row))


@bp.post("/merchants/<merchant_id>/mark-dormant")
def mark_dormant(merchant_id):
    caller = authenticate(STORE, request.headers)
    require_role(caller, ACQUIRER)
    body_object(request.get_json(silent=True) or {}, set())
    row = _common.merchant(merchant_id)
    with STORE.lock:
        merchant_service.mark_dormant(STORE, row)
    return ok_object(_common.render(row))


@bp.post("/merchants/<merchant_id>/suppress")
def suppress_merchant(merchant_id):
    caller = authenticate(STORE, request.headers)
    require_role(caller, ["NetworkCompliance"])
    body_object(request.get_json(silent=True) or {}, set())
    row = _common.merchant(merchant_id)
    with STORE.lock:
        merchant_service.suppress_merchant(STORE, row, risk_gated=True)
    return ok_object(_common.render(row))


@bp.delete("/merchants/<merchant_id>")
def archive_merchant(merchant_id):
    caller = authenticate(STORE, request.headers)
    require_role(caller, ["NetworkCompliance"])
    row = _common.merchant(merchant_id)
    with STORE.lock:
        merchant_service.suppress_merchant(STORE, row, risk_gated=False)
    return ok_object(_common.render(row))


# --- Declined attempts -----------------------------------------------------

@bp.post("/merchants/<merchant_id>/declined-attempts")
def record_declined_attempt(merchant_id):
    caller = authenticate(STORE, request.headers)
    require_role(caller, ACQUIRER)
    body = body_object(request.get_json(silent=True) or {},
                       {"card_product", "attempted_amount_cents", "decline_reason",
                        "occurred_at"})
    card_product = require_enum(body, "card_product", CARD_PRODUCTS)
    attempted_amount_cents = require_int(body, "attempted_amount_cents", minimum=1)
    decline_reason = require_enum(body, "decline_reason", DECLINE_REASONS)
    occurred_at = require_datetime(body, "occurred_at")

    row = _common.merchant(merchant_id)
    with STORE.lock:
        attempt_id = STORE.new_id()
        attempt = {
            "id": attempt_id,
            "created_at": STORE.clock.now(),
            "_seq": STORE.next_created_seq(),
            "_append_only": True,
            "merchant_id": row["id"],
            "card_product": card_product,
            "attempted_amount_cents": attempted_amount_cents,
            "decline_reason": decline_reason,
            "occurred_at": occurred_at,
        }
        STORE.declined_attempts[attempt_id] = attempt

        if decline_reason == "MERCHANT_NOT_ACCEPTED":
            # The cycle-closing hop runs only when an open window already covers
            # this merchant's region and industry and the sweep generation matches.
            gap_engine.maybe_reenter_from_decline(STORE, row)
    return ok_object(_common.render(attempt)), 201


@bp.get("/merchants/<merchant_id>/declined-attempts")
def list_merchant_declined_attempts(merchant_id):
    caller = authenticate(STORE, request.headers)
    require_role(caller, ACQUIRER)
    limit, offset = pagination(request.args)
    row = _common.merchant(merchant_id)
    rows = [attempt for attempt in STORE.declined_attempts.values()
            if attempt["merchant_id"] == row["id"]]
    rows = sort_rows(rows, "created_at")
    total = len(rows)
    page = paginate(rows, limit, offset)
    return ok_array([_common.render(item) for item in page], total, limit, offset)


@bp.get("/declined-attempts")
def list_declined_attempts():
    caller = authenticate(STORE, request.headers)
    require_role(caller, ACQUIRER)
    limit, offset = pagination(request.args)
    merchant_id = filter_arg(request.args, "merchant_id")
    decline_reason = filter_arg(request.args, "decline_reason", DECLINE_REASONS)
    rows = list(STORE.declined_attempts.values())
    if merchant_id is not None:
        rows = [row for row in rows if row["merchant_id"] == merchant_id]
    if decline_reason is not None:
        rows = [row for row in rows if row["decline_reason"] == decline_reason]
    rows = sort_rows(rows, "created_at")
    total = len(rows)
    page = paginate(rows, limit, offset)
    return ok_array([_common.render(row) for row in page], total, limit, offset)


@bp.get("/declined-attempts/<declined_attempt_id>")
def get_declined_attempt(declined_attempt_id):
    caller = authenticate(STORE, request.headers)
    require_role(caller, ACQUIRER)
    row = _common.declined_attempt(declined_attempt_id)
    return ok_object(_common.render(row))


# --- Acceptance gaps -------------------------------------------------------

@bp.post("/acceptance-gaps/rollup")
def rollup_acceptance_gap():
    caller = authenticate(STORE, request.headers)
    require_role(caller, ACQUIRER)
    body = body_object(
        request.get_json(silent=True) or {},
        {"region_code", "industry_category_id", "window_start", "window_end",
         "window_days"},
    )
    region_code = require_string(body, "region_code")
    industry_category_id = require_string(body, "industry_category_id")
    window_start = require_datetime(body, "window_start")
    window_end = require_datetime(body, "window_end")
    window_days = require_int(body, "window_days")

    if window_days not in GAP_WINDOW_DAYS:
        raise ApiError(ERR_INVALID_REQUEST, "window_days must be one of 30, 60, 90.")

    if industry_category_id not in STORE.industry_categories:
        raise ApiError(ERR_NOT_FOUND, "The referenced industry category does not exist.")

    with STORE.lock:
        gap = gap_engine.rollup_gap(STORE, region_code, industry_category_id,
                                    window_start, window_end, window_days)
    return ok_object(_common.render(gap))


@bp.get("/acceptance-gaps")
def list_acceptance_gaps():
    caller = authenticate(STORE, request.headers)
    require_role(caller, ACQUIRER)
    limit, offset = pagination(request.args)
    region_code = filter_arg(request.args, "region_code")
    industry_category_id = filter_arg(request.args, "industry_category_id")
    qualified_status = filter_arg(request.args, "qualified_status", QUALIFIED_STATUSES)

    rows = list(STORE.acceptance_gaps.values())
    if region_code is not None:
        rows = [row for row in rows if row["region_code"] == region_code]
    if industry_category_id is not None:
        rows = [row for row in rows if row["industry_category_id"] == industry_category_id]
    if qualified_status is not None:
        rows = [row for row in rows if row["qualified_status"] == qualified_status]
    rows = sort_rows(rows, "created_at")
    total = len(rows)
    page = paginate(rows, limit, offset)
    return ok_array([_common.render(row) for row in page], total, limit, offset)


@bp.get("/acceptance-gaps/<gap_id>")
def get_acceptance_gap(gap_id):
    caller = authenticate(STORE, request.headers)
    require_role(caller, ACQUIRER)
    row = _common.gap(gap_id)
    return ok_object(_common.render(row))


@bp.get("/merchants/<merchant_id>/acceptance-gaps")
def list_merchant_acceptance_gaps(merchant_id):
    caller = authenticate(STORE, request.headers)
    require_role(caller, ACQUIRER)
    limit, offset = pagination(request.args)
    row = _common.merchant(merchant_id)
    rows = [gap for gap in STORE.acceptance_gaps.values()
            if gap["region_code"] == row["region_code"]
            and gap["industry_category_id"] == row["industry_category_id"]]
    rows = sort_rows(rows, "created_at")
    total = len(rows)
    page = paginate(rows, limit, offset)
    return ok_array([_common.render(item) for item in page], total, limit, offset)


# --- Merchant risk state ---------------------------------------------------

@bp.get("/merchants/<merchant_id>/risk-state")
def get_merchant_risk_state(merchant_id):
    caller = authenticate(STORE, request.headers)
    require_role(caller, ACQUIRER_OR_COMPLIANCE)
    with STORE.lock:
        rows = _common.risk_state_of_merchant(merchant_id)
        for row in rows:
            risk.recompute(STORE, row)
        rendered = [_common.render(row) for row in rows]
    return ok_array(rendered, len(rendered), 10, 0)


@bp.get("/merchant-risk-states/<risk_state_id>")
def get_risk_state(risk_state_id):
    caller = authenticate(STORE, request.headers)
    require_role(caller, ACQUIRER_OR_COMPLIANCE)
    with STORE.lock:
        row = _common.risk_state(risk_state_id)
        risk.recompute(STORE, row)
    return ok_object(_common.render(row))


@bp.get("/merchant-risk-states")
def list_risk_states():
    caller = authenticate(STORE, request.headers)
    require_role(caller, ACQUIRER_OR_COMPLIANCE)
    limit, offset = pagination(request.args)
    merchant_id = filter_arg(request.args, "merchant_id")
    suppression_flag = bool_arg(request.args, "suppression_flag", None)

    with STORE.lock:
        risk.recompute_all(STORE)
        rows = list(STORE.merchant_risk_states.values())
        if merchant_id is not None:
            rows = [row for row in rows if row["merchant_id"] == merchant_id]
        if suppression_flag is not None:
            rows = [row for row in rows if bool(row["suppression_flag"]) is suppression_flag]
        rows = sort_rows(rows, "created_at")
        total = len(rows)
        page = paginate(rows, limit, offset)
        rendered = [_common.render(row) for row in page]
    return ok_array(rendered, total, limit, offset)


# --- Settlements (merchant-scoped) -----------------------------------------

@bp.post("/merchants/<merchant_id>/settlements")
def capture_settlement(merchant_id):
    caller = authenticate(STORE, request.headers)
    require_role(caller, ["NetworkSettlementOps"])
    body = body_object(request.get_json(silent=True) or {},
                       {"settlement_cycle", "gross_volume_cents", "refund_volume_cents"})
    settlement_cycle = require_int(body, "settlement_cycle", minimum=1)
    gross_volume_cents = require_int(body, "gross_volume_cents", minimum=0)
    refund_volume_cents = require_int(body, "refund_volume_cents", minimum=0)

    row = _common.merchant(merchant_id)
    with STORE.lock:
        settlement = merchant_service.capture_settlement(
            STORE, row, settlement_cycle, gross_volume_cents, refund_volume_cents)
    return ok_object(_common.render(settlement)), 201


@bp.get("/merchants/<merchant_id>/settlements")
def list_merchant_settlements(merchant_id):
    caller = authenticate(STORE, request.headers)
    require_role(caller, ["NetworkSettlementOps", "Merchant"])
    limit, offset = pagination(request.args)
    settlement_status = filter_arg(request.args, "settlement_status",
                                   ("CAPTURED", "IN_FUNDING", "SETTLED", "REVERSED"))
    row = _common.merchant(merchant_id)
    if caller.role == "Merchant":
        require_owned_by_caller(caller, row["id"])
    rows = [settlement for settlement in STORE.settlements.values()
            if settlement["merchant_id"] == row["id"]]
    if settlement_status is not None:
        rows = [item for item in rows if item["settlement_status"] == settlement_status]
    rows = sort_rows(rows, "created_at")
    total = len(rows)
    page = paginate(rows, limit, offset)
    return ok_array([_common.render(item) for item in page], total, limit, offset)


@bp.post("/merchants/<merchant_id>/funding/batches/<batch_seq>/finalize")
def finalize_batch(merchant_id, batch_seq):
    caller = authenticate(STORE, request.headers)
    require_role(caller, ["NetworkSettlementOps"])
    body_object(request.get_json(silent=True) or {}, set())
    try:
        parsed_batch_seq = int(batch_seq)
    except (TypeError, ValueError):
        raise ApiError(ERR_INVALID_REQUEST, "batch_seq must be an integer.")

    row = _common.merchant(merchant_id)
    with STORE.lock:
        merchant_service.finalize_batch(STORE, row, parsed_batch_seq)
    return ok_object(_common.render(row))
