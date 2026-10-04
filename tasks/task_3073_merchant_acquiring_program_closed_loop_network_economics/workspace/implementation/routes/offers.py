"""Spend-insight offers, redemption pools and member payouts."""

from flask import Blueprint, request

from auth import authenticate, require_owned_by_caller, require_role
from db import STORE
from errors import ERR_INVALID_REQUEST, ApiError
from paging import filter_arg, paginate, pagination, sort_rows
from response import ok_array, ok_object
from routes import _common
from services import offers as offer_service
from validation import (
    body_object,
    optional_datetime,
    optional_int,
    require_enum,
    require_int,
    require_string,
)

bp = Blueprint("offers", __name__)

AUDIENCE_SEGMENTS = ("HIGH_SPEND", "MEDIUM_SPEND", "LOW_SPEND", "ALL_CARDMEMBERS")
PRIVACY_STATES = ("DRAFT", "PRIVACY_REVIEW", "MERCHANT_CONSENT", "LIVE", "TERMINATED")
ACCEPTANCE_STATUSES = ("PENDING", "APPROVED", "PAID", "REVERSED")
FUNDERS = ("MERCHANT", "NETWORK")

STEWARD = ["NetworkDataSteward"]
STEWARD_OR_MERCHANT = ["NetworkDataSteward", "Merchant"]
STEWARD_OR_MEMBER = ["NetworkDataSteward", "CardMember"]


@bp.post("/offers")
def create_offer():
    caller = authenticate(STORE, request.headers)
    require_role(caller, STEWARD)
    body = body_object(request.get_json(silent=True) or {},
                       {"merchant_id", "audience_segment", "min_segment_spend_cents",
                        "reward_bps"})
    merchant_id = require_string(body, "merchant_id")
    audience_segment = require_enum(body, "audience_segment", AUDIENCE_SEGMENTS)
    min_segment_spend_cents = require_int(body, "min_segment_spend_cents", minimum=0)
    reward_bps = require_int(body, "reward_bps", minimum=0)

    _common.merchant(merchant_id)
    with STORE.lock:
        offer_id = STORE.new_id()
        now = STORE.clock.now()
        row = {
            "id": offer_id,
            "created_at": now,
            "updated_at": now,
            "version": 0,
            "_seq": STORE.next_created_seq(),
            "merchant_id": merchant_id,
            "audience_segment": audience_segment,
            "min_segment_spend_cents": min_segment_spend_cents,
            "reward_bps": reward_bps,
            "privacy_state": "DRAFT",
            "audience_size": 0,
            "aggregated_spend_cents": 0,
            "accepted_count": 0,
            "live_start_utc": None,
            "live_end_utc": None,
        }
        STORE.offers[offer_id] = row
    return ok_object(_common.render(row)), 201


@bp.get("/offers/<offer_id>")
def get_offer(offer_id):
    caller = authenticate(STORE, request.headers)
    require_role(caller, STEWARD_OR_MERCHANT)
    row = _common.offer(offer_id)
    if caller.role == "Merchant":
        require_owned_by_caller(caller, row["merchant_id"])
    return ok_object(_common.render(row))


@bp.get("/offers")
def list_offers():
    caller = authenticate(STORE, request.headers)
    require_role(caller, STEWARD)
    limit, offset = pagination(request.args)
    merchant_id = filter_arg(request.args, "merchant_id")
    privacy_state = filter_arg(request.args, "privacy_state", PRIVACY_STATES)

    rows = list(STORE.offers.values())
    if merchant_id is not None:
        rows = [row for row in rows if row["merchant_id"] == merchant_id]
    if privacy_state is not None:
        rows = [row for row in rows if row["privacy_state"] == privacy_state]
    rows = sort_rows(rows, "created_at")
    total = len(rows)
    page = paginate(rows, limit, offset)
    return ok_array([_common.render(row) for row in page], total, limit, offset)


@bp.post("/offers/<offer_id>/submit-review")
def submit_review(offer_id):
    caller = authenticate(STORE, request.headers)
    require_role(caller, STEWARD)
    body_object(request.get_json(silent=True) or {}, set())
    row = _common.offer(offer_id)
    with STORE.lock:
        offer_service.submit_review(STORE, row)
    return ok_object(_common.render(row))


@bp.post("/offers/<offer_id>/request-consent")
def request_consent(offer_id):
    caller = authenticate(STORE, request.headers)
    require_role(caller, STEWARD)
    body_object(request.get_json(silent=True) or {}, set())
    row = _common.offer(offer_id)
    with STORE.lock:
        offer_service.request_consent(STORE, row)
    return ok_object(_common.render(row))


@bp.post("/offers/<offer_id>/consent")
def consent(offer_id):
    caller = authenticate(STORE, request.headers)
    require_role(caller, ["Merchant"])
    body = body_object(request.get_json(silent=True) or {},
                       {"expected_offer_version", "live_start_utc", "live_end_utc"})
    expected_version = optional_int(body, "expected_offer_version", minimum=0, default=None)
    live_start = optional_datetime(body, "live_start_utc")
    live_end = optional_datetime(body, "live_end_utc")

    row = _common.offer(offer_id)
    require_owned_by_caller(caller, row["merchant_id"])
    funding_merchant = _common.merchant(row["merchant_id"])
    with STORE.lock:
        offer_service.consent(STORE, row, funding_merchant, expected_version,
                              live_start, live_end)
    return ok_object(_common.render(row))


@bp.post("/offers/<offer_id>/return-to-draft")
def return_to_draft(offer_id):
    caller = authenticate(STORE, request.headers)
    require_role(caller, STEWARD)
    body_object(request.get_json(silent=True) or {}, set())
    row = _common.offer(offer_id)
    with STORE.lock:
        offer_service.return_to_draft(STORE, row)
    return ok_object(_common.render(row))


@bp.post("/offers/<offer_id>/suspend")
def suspend(offer_id):
    caller = authenticate(STORE, request.headers)
    require_role(caller, STEWARD)
    body_object(request.get_json(silent=True) or {}, set())
    row = _common.offer(offer_id)
    with STORE.lock:
        offer_service.suspend(STORE, row)
    return ok_object(_common.render(row))


# --- Acceptances -----------------------------------------------------------

@bp.post("/offers/<offer_id>/accept")
def accept_offer(offer_id):
    caller = authenticate(STORE, request.headers)
    require_role(caller, ["CardMember"])
    body = body_object(request.get_json(silent=True) or {},
                       {"cardmember_id", "trigger_amount_cents"})
    cardmember_id = require_string(body, "cardmember_id")
    trigger_amount_cents = optional_int(body, "trigger_amount_cents", minimum=0, default=None)

    row = _common.offer(offer_id)
    member = _common.cardmember(cardmember_id)
    require_owned_by_caller(caller, member["id"])
    with STORE.lock:
        acceptance = offer_service.accept_offer(STORE, row, member, trigger_amount_cents)
    return ok_object(_common.render(acceptance)), 201


@bp.get("/offers/<offer_id>/acceptances")
def list_offer_acceptances(offer_id):
    caller = authenticate(STORE, request.headers)
    require_role(caller, STEWARD_OR_MERCHANT)
    limit, offset = pagination(request.args)
    row = _common.offer(offer_id)
    if caller.role == "Merchant":
        require_owned_by_caller(caller, row["merchant_id"])
    rows = [acceptance for acceptance in STORE.offer_acceptances.values()
            if acceptance["offer_id"] == row["id"]]
    rows = sort_rows(rows, "created_at")
    total = len(rows)
    page = paginate(rows, limit, offset)
    return ok_array([_common.render(item) for item in page], total, limit, offset)


@bp.get("/offer-acceptances/<acceptance_id>")
def get_acceptance(acceptance_id):
    caller = authenticate(STORE, request.headers)
    require_role(caller, STEWARD_OR_MEMBER)
    row = _common.acceptance(acceptance_id)
    if caller.role == "CardMember":
        require_owned_by_caller(caller, row["cardmember_id"])
    return ok_object(_common.render(row))


@bp.get("/offer-acceptances")
def list_acceptances():
    caller = authenticate(STORE, request.headers)
    require_role(caller, STEWARD_OR_MEMBER)
    limit, offset = pagination(request.args)
    cardmember_id = filter_arg(request.args, "cardmember_id")
    offer_id = filter_arg(request.args, "offer_id")
    acceptance_status = filter_arg(request.args, "acceptance_status", ACCEPTANCE_STATUSES)

    rows = list(STORE.offer_acceptances.values())
    if caller.role == "CardMember":
        rows = [row for row in rows if row["cardmember_id"] == caller.user_id]
    if cardmember_id is not None:
        rows = [row for row in rows if row["cardmember_id"] == cardmember_id]
    if offer_id is not None:
        rows = [row for row in rows if row["offer_id"] == offer_id]
    if acceptance_status is not None:
        rows = [row for row in rows if row["acceptance_status"] == acceptance_status]
    rows = sort_rows(rows, "created_at")
    total = len(rows)
    page = paginate(rows, limit, offset)
    return ok_array([_common.render(row) for row in page], total, limit, offset)


@bp.post("/offer-acceptances/<acceptance_id>/approve")
def approve_acceptance(acceptance_id):
    caller = authenticate(STORE, request.headers)
    require_role(caller, STEWARD)
    body_object(request.get_json(silent=True) or {}, set())
    row = _common.acceptance(acceptance_id)
    with STORE.lock:
        offer_service.approve_acceptance(STORE, row)
    return ok_object(_common.render(row))


@bp.post("/offer-acceptances/<acceptance_id>/pay")
def pay_acceptance(acceptance_id):
    caller = authenticate(STORE, request.headers)
    require_role(caller, STEWARD)
    body_object(request.get_json(silent=True) or {}, set())
    row = _common.acceptance(acceptance_id)
    with STORE.lock:
        offer_service.pay_acceptance(STORE, row)
    return ok_object(_common.render(row))


@bp.post("/offer-acceptances/<acceptance_id>/reverse")
def reverse_acceptance(acceptance_id):
    caller = authenticate(STORE, request.headers)
    require_role(caller, STEWARD)
    body_object(request.get_json(silent=True) or {}, set())
    row = _common.acceptance(acceptance_id)
    with STORE.lock:
        offer_service.reverse_acceptance(STORE, row)
    return ok_object(_common.render(row))


# --- Redemption pools ------------------------------------------------------

@bp.post("/offers/<offer_id>/redemption-pool")
def create_pool(offer_id):
    caller = authenticate(STORE, request.headers)
    require_role(caller, STEWARD)
    body = body_object(request.get_json(silent=True) or {},
                       {"funder", "initial_funded_cents"})
    funder = require_enum(body, "funder", FUNDERS)
    initial_funded_cents = require_int(body, "initial_funded_cents", minimum=0)
    row = _common.offer(offer_id)
    with STORE.lock:
        pool = offer_service.create_pool(STORE, row, funder, initial_funded_cents)
    return ok_object(_common.render(pool)), 201


@bp.post("/offers/<offer_id>/redemption-pool/topup")
def topup_pool(offer_id):
    caller = authenticate(STORE, request.headers)
    require_role(caller, STEWARD)
    body = body_object(request.get_json(silent=True) or {}, {"amount_cents"})
    amount_cents = require_int(body, "amount_cents", minimum=0)
    row = _common.offer(offer_id)
    with STORE.lock:
        pool = STORE.pool_for_offer(row["id"])
        if pool is None:
            raise ApiError(ERR_INVALID_REQUEST, "This offer has no redemption pool.")
        offer_service.topup_pool(STORE, pool, amount_cents)
    return ok_object(_common.render(pool))


@bp.get("/offers/<offer_id>/redemption-pool")
def get_offer_pool(offer_id):
    caller = authenticate(STORE, request.headers)
    require_role(caller, STEWARD_OR_MERCHANT)
    row = _common.offer(offer_id)
    if caller.role == "Merchant":
        require_owned_by_caller(caller, row["merchant_id"])
    pool_row = STORE.pool_for_offer(row["id"])
    rows = [pool_row] if pool_row is not None else []
    rendered = [_common.render(item) for item in rows]
    return ok_array(rendered, len(rendered), 10, 0)


@bp.get("/redemption-pools/<pool_id>")
def get_pool(pool_id):
    caller = authenticate(STORE, request.headers)
    require_role(caller, STEWARD_OR_MERCHANT)
    row = _common.pool(pool_id)
    if caller.role == "Merchant":
        require_owned_by_caller(caller, _offer_merchant(row))
    return ok_object(_common.render(row))


@bp.get("/redemption-pools")
def list_pools():
    caller = authenticate(STORE, request.headers)
    require_role(caller, STEWARD_OR_MERCHANT)
    limit, offset = pagination(request.args)
    offer_id = filter_arg(request.args, "offer_id")
    funder = filter_arg(request.args, "funder", FUNDERS)

    rows = list(STORE.offer_redemption_pools.values())
    if offer_id is not None:
        rows = [row for row in rows if row["offer_id"] == offer_id]
    if funder is not None:
        rows = [row for row in rows if row["funder"] == funder]
    if caller.role == "Merchant":
        rows = [row for row in rows if _offer_merchant(row) == caller.user_id]
    rows = sort_rows(rows, "created_at")
    total = len(rows)
    page = paginate(rows, limit, offset)
    return ok_array([_common.render(row) for row in page], total, limit, offset)


def _offer_merchant(pool):
    offer = STORE.offers.get(pool["offer_id"])
    return offer["merchant_id"] if offer else None