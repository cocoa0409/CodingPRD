"""Net positions, funding, corporate actions, clearing funds and defaults."""

from flask import Blueprint, request

from db import db, new_record, touch
from errors import (
    api_error,
    ERR_FUNDING_EXCEEDS_OBLIGATION,
    ERR_FUND_ALREADY_RECOMPUTED,
    ERR_INVALID_AMOUNT,
    ERR_INVALID_STATE,
    ERR_PARTICIPANT_NOT_ACTIVE,
    ERR_PARTICIPANT_NOT_FOUND,
    ERR_RESOURCE_NOT_FOUND,
    ERR_STALE_VERSION,
)
from lookups import (
    components_of_fund,
    loss_allocations_of_component,
    loss_allocations_of_proceeding,
    net_positions_of_participant,
    proceedings_of_participant,
)
from middleware import CLEARING_MEMBER, PLATFORM_ADMIN, RISK_OFFICER, principal
from request import body, check_unknown, optional, pagination, require
from routes.common import ok, ok_array, ok_list, paginate
from serializers import (
    clearing_fund as serialize_fund,
    corporate_action as serialize_action,
    default_proceeding as serialize_proceeding,
    fund_component as serialize_component,
    loss_allocation as serialize_loss,
    net_position as serialize_net_position,
)
from services.custody import apply_action, create_action, reverse_action
from services.defaults import (
    advance,
    allocate_loss,
    declare,
    liquidate,
    place_bid,
)
from services.deposit import derive_coverage
from services.funds import component_amount_for, next_generation, refresh_fund_totals
from services.marks import fail_mark_to_market
from timeutil import require_date, require_instant

bp = Blueprint("positions", __name__)

ACTION_TYPES = ("SPLIT", "REVERSE_SPLIT", "CASH_DIVIDEND")
FUND_STATUSES = ("OPEN", "RECOMPUTED")


def require_record(table, identifier):
    record = table.get(identifier)
    if record is None:
        raise api_error(ERR_RESOURCE_NOT_FOUND)
    return record


# ---------------------------------------------------------------------------
# Net positions
# ---------------------------------------------------------------------------
@bp.get("/clearing/net-positions")
def list_net_positions_route():
    principal((PLATFORM_ADMIN, RISK_OFFICER, CLEARING_MEMBER))
    limit, offset = pagination()
    rows = list(db.net_positions.values())
    for field in ("window_id", "participant_id", "security_id", "dvp_status"):
        value = request.args.get(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    page, total = paginate(rows, limit, offset, lambda r: r["created_at"])
    return ok_list([serialize_net_position(r) for r in page], limit, offset, total)


@bp.get("/clearing/net-positions/<nid>")
def read_net_position_route(nid):
    principal((PLATFORM_ADMIN, RISK_OFFICER, CLEARING_MEMBER))
    record = require_record(db.net_positions, nid)
    return ok(serialize_net_position(record))


@bp.get("/clearing/participants/<pid>/net-positions")
def participant_net_positions_route(pid):
    principal((PLATFORM_ADMIN, RISK_OFFICER, CLEARING_MEMBER))
    require_record(db.participants, pid)
    rows = net_positions_of_participant(pid)
    rows.sort(key=lambda r: r["created_at"])
    return ok_array([serialize_net_position(r) for r in rows])


@bp.post("/clearing/net-positions/<nid>/fund")
def fund_net_position_route(nid):
    actor = principal((CLEARING_MEMBER,))
    record = require_record(db.net_positions, nid)
    participant = db.participants.get(actor.user_id)
    if participant is None:
        raise api_error(ERR_PARTICIPANT_NOT_FOUND)

    # A ClearingMember may only fund its own obligation; PRD 2.1 makes the
    # header id the acting Participant and this endpoint is ownership-gated.
    if record["participant_id"] != participant["id"]:
        from errors import ERR_UNAUTHORIZED

        raise api_error(ERR_UNAUTHORIZED)

    data = body()
    check_unknown(data, ("amount_cents", "mark_to_market_only"))
    mark_only = optional(data, "mark_to_market_only", type_=bool, default=False)

    if mark_only:
        # The daily mark-to-market sweep moves no funds, so no amount is needed.
        # The "only an ACTIVE member may fund" gate belongs to the funding
        # path; the mark-only mode recomputes the fail mark and nothing else.
        if record["dvp_status"] == "FAILED":
            record["mark_to_market_cents"] = fail_mark_to_market(record)
            touch(record)
        return ok(serialize_net_position(record))

    if participant["membership_status"] != "ACTIVE":
        raise api_error(ERR_PARTICIPANT_NOT_ACTIVE)

    amount_cents = require(data, "amount_cents", type_=int)
    if amount_cents == 0:
        raise api_error(ERR_INVALID_AMOUNT)
    if record["settlement_obligation_cents"] <= 0:
        raise api_error(ERR_INVALID_AMOUNT)
    if record["funded_amount_cents"] + amount_cents > record["settlement_obligation_cents"]:
        raise api_error(ERR_FUNDING_EXCEEDS_OBLIGATION)

    record["funded_amount_cents"] += amount_cents
    touch(record)

    if record["funded_amount_cents"] >= record["settlement_obligation_cents"]:
        deposit = None
        for candidate in db.deposits.values():
            if candidate["participant_id"] == record["participant_id"]:
                deposit = candidate
                break
        if deposit is not None:
            derive_coverage(deposit)
            touch(deposit)
    return ok(serialize_net_position(record))


# ---------------------------------------------------------------------------
# Corporate actions
# ---------------------------------------------------------------------------
@bp.post("/clearing/corporate-actions")
def create_action_route():
    principal((PLATFORM_ADMIN,))
    data = body()
    check_unknown(
        data,
        (
            "security_id",
            "action_type",
            "ratio_numerator",
            "ratio_denominator",
            "cash_rate_cents_per_unit",
            "effective_date",
        ),
    )
    security_id = require(data, "security_id", type_=str)
    action_type = require(data, "action_type", type_=str, enum=ACTION_TYPES)
    numerator = optional(data, "ratio_numerator", type_=int, default=1)
    denominator = optional(data, "ratio_denominator", type_=int, default=1)
    cash_rate = optional(data, "cash_rate_cents_per_unit", type_=int, default=0)
    effective_date = require(data, "effective_date", type_=str)

    if db.securities.get(security_id) is None:
        from errors import ERR_SECURITY_NOT_FOUND

        raise api_error(ERR_SECURITY_NOT_FOUND)
    require_date(effective_date, "effective_date")
    if denominator <= 0:
        from errors import ERR_INVALID_REQUEST

        raise api_error(ERR_INVALID_REQUEST, "ratio_denominator must be greater than zero.")
    if numerator <= 0:
        from errors import ERR_INVALID_REQUEST

        raise api_error(ERR_INVALID_REQUEST, "ratio_numerator must be greater than zero.")

    record = create_action(
        security_id, action_type, numerator, denominator, cash_rate, effective_date
    )
    return ok(serialize_action(record), 201)


@bp.get("/clearing/corporate-actions")
def list_actions_route():
    principal((PLATFORM_ADMIN, RISK_OFFICER, CLEARING_MEMBER))
    limit, offset = pagination()
    rows = list(db.corporate_actions.values())
    security_id = request.args.get("security_id")
    status = request.args.get("status")
    if security_id is not None:
        rows = [r for r in rows if r["security_id"] == security_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset, lambda r: r["created_at"])
    return ok_list([serialize_action(r) for r in page], limit, offset, total)


@bp.get("/clearing/securities/<sid>/corporate-actions")
def security_actions_route(sid):
    principal((PLATFORM_ADMIN, RISK_OFFICER, CLEARING_MEMBER))
    require_record(db.securities, sid)
    rows = [r for r in db.corporate_actions.values() if r["security_id"] == sid]
    rows.sort(key=lambda r: r["created_at"])
    return ok_array([serialize_action(r) for r in rows])


@bp.post("/clearing/corporate-actions/<aid>/apply")
def apply_action_route(aid):
    principal((PLATFORM_ADMIN,))
    record = require_record(db.corporate_actions, aid)
    apply_action(record)
    return ok(serialize_action(record))


@bp.post("/clearing/corporate-actions/<aid>/reverse")
def reverse_action_route(aid):
    principal((PLATFORM_ADMIN,))
    record = require_record(db.corporate_actions, aid)
    reverse_action(record)
    for net_position in db.net_positions.values():
        if net_position["security_id"] == record["security_id"]:
            window = db.settlement_windows.get(net_position["window_id"])
            if window is not None:
                from services.netting import compute_position

                participant = db.participants.get(net_position["participant_id"])
                if participant is not None:
                    computed = compute_position(window, participant)
                    net_position["cash_delta_cents"] = computed["cash_delta_cents"]
                    touch(net_position)
    return ok(serialize_action(record))


# ---------------------------------------------------------------------------
# Clearing funds
# ---------------------------------------------------------------------------
@bp.post("/clearing/clearing-funds")
def create_fund_route():
    principal((RISK_OFFICER,))
    data = body()
    check_unknown(data, ("security_id", "participant_class"))
    security_id = require(data, "security_id", type_=str)
    participant_class = require(
        data,
        "participant_class",
        type_=str,
        enum=("BANK", "BROKER_DEALER", "CUSTODIAN_BANK", "INSURANCE_CARRIER"),
    )
    if db.securities.get(security_id) is None:
        from errors import ERR_SECURITY_NOT_FOUND

        raise api_error(ERR_SECURITY_NOT_FOUND)

    record = new_record(
        security_id=security_id,
        status="OPEN",
        fund_balance_cents=0,
        total_component_cents=0,
        last_computed_at=None,
        participant_class=participant_class,
        experiences_deficit=False,
    )
    db.clearing_funds[record["id"]] = record
    return ok(serialize_fund(record), 201)


@bp.get("/clearing/clearing-funds")
def list_funds_route():
    principal((PLATFORM_ADMIN, RISK_OFFICER, CLEARING_MEMBER))
    limit, offset = pagination()
    rows = list(db.clearing_funds.values())
    security_id = request.args.get("security_id")
    status = request.args.get("status")
    if security_id is not None:
        rows = [r for r in rows if r["security_id"] == security_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset, lambda r: r["created_at"])
    return ok_list([serialize_fund(r) for r in page], limit, offset, total)


@bp.get("/clearing/securities/<sid>/clearing-funds")
def security_funds_route(sid):
    principal((PLATFORM_ADMIN, RISK_OFFICER, CLEARING_MEMBER))
    require_record(db.securities, sid)
    rows = [r for r in db.clearing_funds.values() if r["security_id"] == sid]
    rows.sort(key=lambda r: r["created_at"])
    return ok_array([serialize_fund(r) for r in rows])


@bp.get("/clearing/clearing-funds/<fid>")
def read_fund_route(fid):
    principal((PLATFORM_ADMIN, RISK_OFFICER, CLEARING_MEMBER))
    record = require_record(db.clearing_funds, fid)
    return ok(serialize_fund(record))


@bp.post("/clearing/clearing-funds/<fid>/recompute")
def recompute_fund_route(fid):
    principal((RISK_OFFICER,))
    fund = require_record(db.clearing_funds, fid)

    data = body()
    check_unknown(data, ("expected_fund_version",))
    expected = require(data, "expected_fund_version", type_=int)
    # The optimistic-concurrency rejection is decided before the recompute
    # eligibility gate, so a caller presenting a version it never observed is
    # told its view is stale rather than that the fund is not recomputable.
    if expected != fund["version"]:
        raise api_error(ERR_STALE_VERSION)

    # A fund still RECOMPUTED has seen no intervening new net position on its
    # security, so a second sizing is refused as ERR_FUND_ALREADY_RECOMPUTED.
    if fund["status"] == "RECOMPUTED":
        raise api_error(ERR_FUND_ALREADY_RECOMPUTED)
    if fund["status"] != "OPEN":
        raise api_error(ERR_INVALID_STATE)

    security = db.securities[fund["security_id"]]
    generation = next_generation(fund["id"])
    for participant in db.participants.values():
        if participant["membership_status"] != "ACTIVE":
            continue
        if participant["participant_class"] != fund["participant_class"]:
            continue
        amount, _stacked, _floor = component_amount_for(participant, security)
        component = new_record(
            clearing_fund_id=fund["id"],
            participant_id=participant["id"],
            security_id=fund["security_id"],
            component_amount_cents=amount,
            component_balance_cents=amount,
            generation=generation,
            status="ASSESSED",
            reserved_cents=0,
        )
        db.fund_components[component["id"]] = component

    refresh_fund_totals(fund)
    fund["last_computed_at"] = db.get_clock()
    fund["status"] = "RECOMPUTED"
    touch(fund)
    return ok(serialize_fund(fund))


@bp.get("/clearing/clearing-funds/<fid>/components")
def fund_components_route(fid):
    principal((PLATFORM_ADMIN, RISK_OFFICER, CLEARING_MEMBER))
    require_record(db.clearing_funds, fid)
    limit, offset = pagination()
    rows = components_of_fund(fid)
    generation = request.args.get("generation")
    if generation is not None:
        try:
            generation_value = int(generation)
        except ValueError:
            from errors import ERR_INVALID_REQUEST

            raise api_error(ERR_INVALID_REQUEST, "'generation' must be an integer.")
        rows = [r for r in rows if r["generation"] == generation_value]
    page, total = paginate(rows, limit, offset, lambda r: r["created_at"])
    return ok_list([serialize_component(r) for r in page], limit, offset, total)


@bp.get("/clearing/fund-components")
def list_components_route():
    principal((PLATFORM_ADMIN, RISK_OFFICER, CLEARING_MEMBER))
    limit, offset = pagination()
    rows = list(db.fund_components.values())
    for field in ("clearing_fund_id", "participant_id", "status"):
        value = request.args.get(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    page, total = paginate(rows, limit, offset, lambda r: r["created_at"])
    return ok_list([serialize_component(r) for r in page], limit, offset, total)


@bp.get("/clearing/fund-components/<cid>")
def read_component_route(cid):
    principal((PLATFORM_ADMIN, RISK_OFFICER, CLEARING_MEMBER))
    record = require_record(db.fund_components, cid)
    return ok(serialize_component(record))


@bp.get("/clearing/fund-components/<cid>/loss-allocations")
def component_loss_allocations_route(cid):
    principal((PLATFORM_ADMIN, RISK_OFFICER))
    require_record(db.fund_components, cid)
    limit, offset = pagination()
    rows = loss_allocations_of_component(cid)
    page, total = paginate(rows, limit, offset, lambda r: r["created_at"])
    return ok_list([serialize_loss(r) for r in page], limit, offset, total)


@bp.get("/clearing/participants/<pid>/fund-components")
def participant_components_route(pid):
    principal((PLATFORM_ADMIN, RISK_OFFICER, CLEARING_MEMBER))
    require_record(db.participants, pid)
    rows = [r for r in db.fund_components.values() if r["participant_id"] == pid]
    rows.sort(key=lambda r: r["created_at"])
    return ok_array([serialize_component(r) for r in rows])


# ---------------------------------------------------------------------------
# Default proceedings
# ---------------------------------------------------------------------------
@bp.post("/clearing/default-proceedings")
def declare_default_route():
    principal((RISK_OFFICER,))
    data = body()
    check_unknown(data, ("participant_id", "reason_code"))
    participant_id = require(data, "participant_id", type_=str)
    reason_code = require(data, "reason_code", type_=str)
    participant = db.participants.get(participant_id)
    if participant is None:
        raise api_error(ERR_PARTICIPANT_NOT_FOUND)

    if participant["membership_status"] != "SUSPENDED":
        raise api_error(ERR_INVALID_STATE)
    from errors import ERR_FINANCIAL_STANDARD_NOT_MET

    if participant["financial_standard_status"] != "FAIL":
        raise api_error(ERR_FINANCIAL_STANDARD_NOT_MET)

    record = declare(participant, reason_code)
    participant["membership_status"] = "DEFAULTED"
    participant["is_defaulted"] = True
    touch(participant)
    for deposit in db.deposits.values():
        if deposit["participant_id"] == participant["id"]:
            deposit["status"] = "DEFICIENT_DEFAULT"
            touch(deposit)
    return ok(serialize_proceeding(record), 201)


@bp.get("/clearing/default-proceedings")
def list_proceedings_route():
    principal((PLATFORM_ADMIN, RISK_OFFICER))
    limit, offset = pagination()
    rows = list(db.default_proceedings.values())
    participant_id = request.args.get("participant_id")
    status = request.args.get("status")
    if participant_id is not None:
        rows = [r for r in rows if r["participant_id"] == participant_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset, lambda r: r["created_at"])
    return ok_list([serialize_proceeding(r) for r in page], limit, offset, total)


@bp.get("/clearing/participants/<pid>/default-proceedings")
def participant_proceedings_route(pid):
    principal((PLATFORM_ADMIN, RISK_OFFICER))
    require_record(db.participants, pid)
    rows = proceedings_of_participant(pid)
    rows.sort(key=lambda r: r["created_at"])
    return ok_array([serialize_proceeding(r) for r in rows])


@bp.get("/clearing/default-proceedings/<did>")
def read_proceeding_route(did):
    principal((PLATFORM_ADMIN, RISK_OFFICER))
    record = require_record(db.default_proceedings, did)
    return ok(serialize_proceeding(record))


@bp.put("/clearing/default-proceedings/<did>")
def advance_proceeding_route(did):
    principal((RISK_OFFICER,))
    record = require_record(db.default_proceedings, did)
    data = body()
    check_unknown(data, ("reason_code",))
    reason_code = optional(data, "reason_code", type_=str)
    advance(record, reason_code)
    return ok(serialize_proceeding(record))


@bp.post("/clearing/default-proceedings/<did>/bids")
def place_bid_route(did):
    actor = principal((CLEARING_MEMBER,))
    proceeding = require_record(db.default_proceedings, did)
    data = body()
    check_unknown(
        data, ("bid_price_cents", "quantity", "placed_at", "fund_component_id")
    )
    bid_price_cents = require(data, "bid_price_cents", type_=int)
    quantity = require(data, "quantity", type_=int, min_value=1)
    placed_at = require(data, "placed_at", type_=str)
    fund_component_id = require(data, "fund_component_id", type_=str)
    require_instant(placed_at, "placed_at")

    if bid_price_cents <= 0:
        raise api_error(ERR_INVALID_AMOUNT)
    component = require_record(db.fund_components, fund_component_id)
    participant = db.participants.get(actor.user_id)
    if participant is None:
        raise api_error(ERR_PARTICIPANT_NOT_FOUND)

    place_bid(
        proceeding,
        participant["id"],
        bid_price_cents,
        quantity,
        placed_at,
        component["id"],
    )
    return ok(serialize_proceeding(proceeding), 201)


@bp.post("/clearing/default-proceedings/<did>/liquidate")
def liquidate_route(did):
    principal((RISK_OFFICER,))
    record = require_record(db.default_proceedings, did)
    liquidate(record)
    return ok(serialize_proceeding(record))


@bp.post("/clearing/default-proceedings/<did>/allocate-loss")
def allocate_loss_route(did):
    principal((RISK_OFFICER,))
    record = require_record(db.default_proceedings, did)
    allocate_loss(record)
    return ok(serialize_proceeding(record))


@bp.get("/clearing/default-proceedings/<did>/loss-allocations")
def proceeding_loss_allocations_route(did):
    principal((PLATFORM_ADMIN, RISK_OFFICER))
    require_record(db.default_proceedings, did)
    limit, offset = pagination()
    rows = loss_allocations_of_proceeding(did)
    page, total = paginate(rows, limit, offset, lambda r: r["created_at"])
    return ok_list([serialize_loss(r) for r in page], limit, offset, total)


@bp.get("/clearing/loss-allocations")
def list_loss_allocations_route():
    principal((PLATFORM_ADMIN, RISK_OFFICER))
    limit, offset = pagination()
    rows = list(db.loss_allocations.values())
    for field in ("default_proceeding_id", "fund_component_id"):
        value = request.args.get(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    page, total = paginate(rows, limit, offset, lambda r: r["created_at"])
    return ok_list([serialize_loss(r) for r in page], limit, offset, total)