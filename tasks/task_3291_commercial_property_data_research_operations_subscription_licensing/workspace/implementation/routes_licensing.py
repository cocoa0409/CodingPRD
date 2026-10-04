"""LicensingContract and LicenseSeat endpoints (PRD 3.6, 3.10)."""
from datetime import timedelta

from flask import Blueprint, request

import auth
import calc
import core
import lookups
import responses
from serializers_licensing import contract as ser_contract
from serializers_licensing import seat as ser_seat

bp = Blueprint("licensing", __name__, url_prefix="/data-research")

PRODUCTS = {"CORE_MARKET_DATA", "ANALYTICS_INDEX", "LISTING_SERVICE", "GLOBAL_ALL"}
AUDIT_INTENSITIES = {"STANDARD", "ENHANCED"}
INDEX_TIERS = {"TIER_1", "TIER_2", "TIER_3"}


def _revoke_seats(contract):
    for seat in lookups.seats_of(contract["id"]):
        seat["access_revoked"] = True
        seat["shared_flag"] = False
        core.touch(seat)


def _recompute_org_for(contract):
    org = core.organizations.get(contract["subscriber_organization_id"])
    if org is not None:
        lookups.recompute_organization_counters(org)
    return org


@bp.post("/licensing-contracts")
def create_contract():
    auth.authorize(["LicensingAdmin", "PlatformAdmin"])
    payload = core.body_of(request)
    subscriber_organization_id = core.require_string(payload, "subscriber_organization_id")
    product = core.require_enum(payload, "product", PRODUCTS)
    licensed_markets = core.require_string_list(payload, "licensed_markets")
    seat_count = core.require_int(payload, "seat_count")
    annual_fee_cents = core.require_int(payload, "annual_fee_cents")
    monthly_index_fee_cents = core.optional_int(payload, "monthly_index_fee_cents", 0)
    auto_renew = core.optional_bool(payload, "auto_renew", True)
    renewal_notice_days = core.optional_int(payload, "renewal_notice_days", 30)
    term_start = core.require_datetime(payload, "term_start")
    term_end = core.require_datetime(payload, "term_end")
    audit_intensity = core.optional_enum(payload, "audit_intensity", AUDIT_INTENSITIES, "STANDARD")

    if len(set(licensed_markets)) != len(licensed_markets):
        raise core.ApiError("ERR_INVALID_REQUEST", "licensed_markets entries must be unique.")
    if seat_count < 1:
        raise core.ApiError("ERR_INVALID_REQUEST", "seat_count must be at least one.")
    org = lookups.get_organization(subscriber_organization_id)
    if not term_end > term_start:
        raise core.ApiError("ERR_INVALID_REQUEST", "term_end must be strictly after term_start.")
    if annual_fee_cents <= 0:
        raise core.ApiError("ERR_FEE_NOT_POSITIVE")

    record = {
        "subscriber_organization_id": org["id"],
        "product": product,
        "licensed_markets": licensed_markets,
        "seat_count": seat_count,
        "annual_fee_cents": annual_fee_cents,
        "monthly_index_fee_cents": monthly_index_fee_cents,
        "auto_renew": auto_renew,
        "renewal_notice_days": renewal_notice_days,
        "term_start": core.fmt_dt(term_start),
        "term_end": core.fmt_dt(term_end),
        "renewal_decision": "NONE",
        "renewal_due_at": core.fmt_dt(term_end - timedelta(days=renewal_notice_days)),
        "status": "PENDING",
        "audit_intensity": audit_intensity,
    }
    core.stamp_created(record)
    core.contracts[record["id"]] = record
    lookups.recompute_organization_counters(org)
    return responses.ok_object(ser_contract(record), 201)


@bp.get("/licensing-contracts")
def list_contracts():
    auth.authorize(["LicensingAdmin", "EnforcementOfficer", "PlatformAdmin"])
    limit, offset = core.pagination_args(request)
    rows = list(core.contracts.values())
    org_filter = request.args.get("subscriber_organization_id")
    status_filter = request.args.get("status")
    if org_filter:
        rows = [c for c in rows if c["subscriber_organization_id"] == org_filter]
    if status_filter:
        rows = [c for c in rows if c["status"] == status_filter]
    return responses.paged(rows, limit, offset, ser_contract)


@bp.get("/licensing-contracts/<contract_id>")
def get_contract(contract_id):
    auth.authorize(["LicensingAdmin", "EnforcementOfficer", "PlatformAdmin"])
    record = lookups.get_contract(contract_id)
    return responses.ok_object(ser_contract(record))


@bp.get("/licensing-contracts/<contract_id>/seats")
def list_contract_seats(contract_id):
    auth.authorize(["LicensingAdmin", "EnforcementOfficer", "PlatformAdmin"])
    lookups.get_contract(contract_id)
    limit, offset = core.pagination_args(request)
    return responses.paged(lookups.seats_of(contract_id), limit, offset, ser_seat)


@bp.post("/licensing-contracts/<contract_id>/seats")
def create_seat(contract_id):
    auth.authorize(["LicensingAdmin"])
    payload = core.body_of(request)
    market = core.require_string(payload, "market")
    index_tier = core.optional_enum(payload, "index_tier", INDEX_TIERS, "TIER_2")
    last_usage_cycle = core.require_datetime(payload, "last_usage_cycle")
    contract = lookups.get_contract(contract_id)

    if market not in contract["licensed_markets"]:
        raise core.ApiError("ERR_SEAT_MARKET_NOT_LICENSED")
    if len(lookups.seats_of(contract["id"])) + 1 > contract["seat_count"]:
        raise core.ApiError("ERR_SEAT_CAPACITY_EXCEEDED")

    record = {
        "contract_id": contract["id"],
        "occupant_user_id": None,
        "market": market,
        "index_tier": index_tier,
        "monthly_active_days": 0,
        "monthly_unauthorized_markets": [],
        "distinctive_ip_count": 0,
        "shared_flag": False,
        "overage_fee_cents": 0,
        "owner_user_id": None,
        "owner_share_pct": 0.0,
        "billed_owner_share_pct": 0.0,
        "access_revoked": False,
        "last_usage_cycle": core.fmt_dt(last_usage_cycle),
    }
    core.stamp_created(record)
    core.seats[record["id"]] = record
    core.touch(contract)
    return responses.ok_object(ser_seat(record), 201)


@bp.get("/seats")
def list_seats():
    auth.authorize(["LicensingAdmin", "EnforcementOfficer", "PlatformAdmin"])
    limit, offset = core.pagination_args(request)
    rows = list(core.seats.values())
    for param, field in (
        ("contract_id", "contract_id"),
        ("occupant_user_id", "occupant_user_id"),
        ("market", "market"),
    ):
        wanted = request.args.get(param)
        if wanted:
            rows = [s for s in rows if s[field] == wanted]
    return responses.paged(rows, limit, offset, ser_seat)


@bp.get("/seats/<seat_id>")
def get_seat(seat_id):
    auth.authorize(["LicensingAdmin", "EnforcementOfficer", "SeatUser", "PlatformAdmin"])
    record = lookups.get_seat_any(seat_id)
    return responses.ok_object(ser_seat(record))


@bp.post("/licensing-contracts/<contract_id>/activate")
def activate_contract(contract_id):
    auth.authorize(["LicensingAdmin"])
    payload = core.body_of(request)
    expected_version = core.require_int(payload, "expected_contract_version")
    contract = lookups.get_contract(contract_id)

    if contract["status"] != "PENDING":
        raise core.ApiError("ERR_INVALID_STATE")
    seats = lookups.seats_of(contract["id"])
    if not seats:
        raise core.ApiError("ERR_NO_SEATS")
    for seat in seats:
        if seat["market"] not in contract["licensed_markets"]:
            raise core.ApiError("ERR_SEAT_MARKET_NOT_LICENSED")
    if expected_version != contract["version"]:
        raise core.ApiError("ERR_STALE_VERSION")

    contract["status"] = "ACTIVE"
    term_end = core.parse_dt(contract["term_end"])
    contract["renewal_due_at"] = core.fmt_dt(
        term_end - timedelta(days=contract["renewal_notice_days"]))
    core.touch(contract)
    _recompute_org_for(contract)
    return responses.ok_object(ser_contract(contract))


@bp.post("/licensing-contracts/<contract_id>/markets")
def add_contract_market(contract_id):
    auth.authorize(["LicensingAdmin"])
    payload = core.body_of(request)
    market = core.require_string(payload, "market")
    expected_version = core.require_int(payload, "expected_contract_version")
    contract = lookups.get_contract(contract_id)

    if contract["status"] != "ACTIVE":
        raise core.ApiError("ERR_INVALID_STATE")
    if market in contract["licensed_markets"]:
        raise core.ApiError("ERR_MARKET_ALREADY_LICENSED")
    if expected_version != contract["version"]:
        raise core.ApiError("ERR_STALE_VERSION")

    org = lookups.get_organization(contract["subscriber_organization_id"])
    fee = calc.market_addition_fee(contract, org)
    contract["licensed_markets"] = contract["licensed_markets"] + [market]
    contract["annual_fee_cents"] = contract["annual_fee_cents"] + fee
    core.touch(contract)
    lookups.recompute_organization_counters(org)
    return responses.ok_object(ser_contract(contract))


@bp.post("/licensing-contracts/<contract_id>/renewals")
def renew_contract(contract_id):
    auth.authorize(["LicensingAdmin"])
    payload = core.body_of(request)
    new_term_end = core.require_datetime(payload, "new_term_end")
    new_annual_fee_cents = core.require_int(payload, "new_annual_fee_cents")
    expected_version = core.require_int(payload, "expected_contract_version")
    contract = lookups.get_contract(contract_id)

    if contract["status"] != "ACTIVE":
        raise core.ApiError("ERR_INVALID_STATE")
    if contract["auto_renew"] is not True:
        raise core.ApiError("ERR_AUTO_RENEW_DISABLED")
    if contract["renewal_decision"] == "TERMINATED":
        raise core.ApiError("ERR_RENEWAL_TERMINATED")
    if not core.clock.now() < core.parse_dt(contract["renewal_due_at"]):
        raise core.ApiError("ERR_RENEWAL_LAPSED")
    if new_annual_fee_cents <= 0:
        raise core.ApiError("ERR_FEE_NOT_POSITIVE")
    if expected_version != contract["version"]:
        raise core.ApiError("ERR_STALE_VERSION")

    contract["term_start"] = contract["term_end"]
    contract["term_end"] = core.fmt_dt(new_term_end)
    contract["annual_fee_cents"] = new_annual_fee_cents
    contract["status"] = "RENEWED"
    contract["renewal_decision"] = "NONE"
    contract["renewal_due_at"] = core.fmt_dt(
        new_term_end - timedelta(days=contract["renewal_notice_days"]))
    core.touch(contract)
    _recompute_org_for(contract)
    return responses.ok_object(ser_contract(contract))


@bp.post("/licensing-contracts/<contract_id>/terminations")
def terminate_contract(contract_id):
    auth.authorize(["LicensingAdmin"])
    payload = core.body_of(request)
    expected_version = core.require_int(payload, "expected_contract_version")
    contract = lookups.get_contract(contract_id)

    if contract["status"] not in ("ACTIVE", "GRACE"):
        raise core.ApiError("ERR_INVALID_STATE")
    if contract["status"] == "ACTIVE":
        if not core.clock.now() < core.parse_dt(contract["renewal_due_at"]):
            raise core.ApiError("ERR_TERMINATION_WINDOW_CLOSED")
    else:
        if not core.clock.now() < core.parse_dt(contract["term_end"]):
            raise core.ApiError("ERR_TERMINATION_WINDOW_CLOSED")
    if expected_version != contract["version"]:
        raise core.ApiError("ERR_STALE_VERSION")

    was_active = contract["status"] == "ACTIVE"
    contract["status"] = "TERMINATED"
    contract["renewal_decision"] = "TERMINATED"
    _revoke_seats(contract)
    if was_active:
        core.touch(contract)
    _recompute_org_for(contract)
    return responses.ok_object(ser_contract(contract))


@bp.post("/licensing-contracts/<contract_id>/seats/<seat_id>/assignment")
def assign_seat(contract_id, seat_id):
    actor = auth.authorize(["LicensingAdmin"])
    payload = core.body_of(request)
    occupant_user_id = core.require_string(payload, "occupant_user_id")
    expected_version = core.require_int(payload, "expected_contract_version")
    contract = lookups.get_contract(contract_id)
    seat = lookups.get_seat(contract_id, seat_id)

    if seat["occupant_user_id"] is not None:
        raise core.ApiError("ERR_SEAT_ALREADY_ASSIGNED")
    user = lookups.get_user(occupant_user_id)
    if user["status"] != "ACTIVE":
        raise core.ApiError("ERR_USER_INACTIVE")
    if user["organization_id"] != contract["subscriber_organization_id"]:
        raise core.ApiError("ERR_USER_OUT_OF_SCOPE")
    if contract["status"] not in ("ACTIVE", "GRACE"):
        raise core.ApiError("ERR_SUBSCRIPTION_INACTIVE")
    if expected_version != contract["version"]:
        raise core.ApiError("ERR_STALE_VERSION")

    seat["occupant_user_id"] = user["id"]
    seat["access_revoked"] = False
    core.touch(seat)
    core.touch(contract)
    return responses.ok_object(ser_seat(seat))


@bp.post("/licensing-contracts/<contract_id>/seats/<seat_id>/unassignment")
def unassign_seat(contract_id, seat_id):
    auth.authorize(["LicensingAdmin"])
    payload = core.body_of(request)
    expected_version = core.require_int(payload, "expected_contract_version")
    contract = lookups.get_contract(contract_id)
    seat = lookups.get_seat(contract_id, seat_id)

    if seat["occupant_user_id"] is None:
        raise core.ApiError("ERR_INVALID_STATE")
    if expected_version != contract["version"]:
        raise core.ApiError("ERR_STALE_VERSION")

    seat["occupant_user_id"] = None
    core.touch(seat)
    core.touch(contract)
    return responses.ok_object(ser_seat(seat))


@bp.post("/licensing-contracts/<contract_id>/seats/<seat_id>/fee-assignments")
def rebase_seat_fee(contract_id, seat_id):
    auth.authorize(["LicensingAdmin"])
    payload = core.body_of(request)
    expected_version = core.require_int(payload, "expected_contract_version")
    contract = lookups.get_contract(contract_id)
    seat = lookups.get_seat(contract_id, seat_id)

    if expected_version != contract["version"]:
        raise core.ApiError("ERR_STALE_VERSION")

    seat["overage_fee_cents"] = calc.seat_overage_fee(seat, contract)
    _owner, share = calc.seat_owner_attribution(seat, "monthly_cycle")
    seat["billed_owner_share_pct"] = share
    core.touch(seat)
    core.touch(contract)
    return responses.ok_object(ser_seat(seat))