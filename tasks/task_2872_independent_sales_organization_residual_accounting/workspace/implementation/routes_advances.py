"""Agent advances and restructuring (PRD 3.6)."""
from decimal import Decimal

from flask import Blueprint

from apierrors import fail
from auth import authorize
from calc import advance_outstanding_cents, trailing_residual_cents
from envelope import apply_filters, list_response, object_response
from serial import advance as ser_advance
from shapes import (
    as_date,
    as_decimal,
    as_enum,
    as_int,
    as_month_string,
    body,
    check_month,
    check_pct_range,
    present,
    supplied,
)
from store import (
    BOOTSTRAP_ADVANCE_CEILING_CENTS,
    MAX_ADVANCE_EXPOSURE_MULTIPLE,
    MAX_TOTAL_RECOUPMENT_PCT,
    db,
    is_month,
    month_index,
    month_of_date,
    new_id,
    ordered,
    parse_date,
    stamp_new,
    touch,
)

bp = Blueprint("advances", __name__)

ADVANCE_TYPES = ("CASH_ADVANCE", "PORTFOLIO_BUYOUT")
RECOUPMENT_MODES = ("PERCENT_OF_RESIDUAL", "STRAIGHT_LINE_AMORTIZATION")


def _lookup(advance_id):
    row = db.advances.get(advance_id)
    if row is None:
        fail("ERR_ADVANCE_NOT_FOUND", "no agent advance with id %s" % advance_id)
    return row


def _check_window(mode, first_month, last_month, funded_on, amortization_months):
    """PRD 3.6: the three-part window shape rule."""
    if month_index(last_month) < month_index(first_month):
        fail("ERR_RECOUPMENT_WINDOW_INVALID",
             "last_recoupment_month must be >= first_recoupment_month")
    if month_index(first_month) < month_index(month_of_date(parse_date(funded_on))):
        fail("ERR_RECOUPMENT_WINDOW_INVALID",
             "first_recoupment_month must be >= the calendar month of funded_on")
    if mode == "STRAIGHT_LINE_AMORTIZATION":
        span = month_index(last_month) - month_index(first_month) + 1
        if amortization_months is None or span != amortization_months:
            fail("ERR_RECOUPMENT_WINDOW_INVALID",
                 "the inclusive window length must equal amortization_months")


def _check_pct_cap(recoupment_pct):
    if recoupment_pct is not None and recoupment_pct > MAX_TOTAL_RECOUPMENT_PCT:
        fail("ERR_RECOUPMENT_PCT_EXCEEDS_CAP",
             "recoupment_pct may not exceed %s" % MAX_TOTAL_RECOUPMENT_PCT)


@bp.route("/agents/<agent_id>/advances", methods=["POST"])
def fund_advance(agent_id):
    authorize("IsoAdmin")
    payload = body()
    # band 4 -- request shape
    advance_type = as_enum(payload, "advance_type", ADVANCE_TYPES)
    recoupment_mode = as_enum(payload, "recoupment_mode", RECOUPMENT_MODES)
    principal_cents = as_int(payload, "principal_cents", minimum=0)
    first_month = as_month_string(payload, "first_recoupment_month")
    last_month = as_month_string(payload, "last_recoupment_month")
    funded_on = as_date(payload, "funded_on")
    expected_agent_version = as_int(payload, "expected_agent_version")
    recoupment_pct = as_decimal(payload, "recoupment_pct", required=False)
    amortization_months = as_int(
        payload, "amortization_months", required=False, minimum=1, maximum=60)
    if principal_cents <= 0:
        fail("ERR_INVALID_REQUEST", "principal_cents must be strictly greater than zero")
    if recoupment_mode == "PERCENT_OF_RESIDUAL":
        if recoupment_pct is None:
            fail("ERR_INVALID_REQUEST",
                 "recoupment_pct is required when recoupment_mode is PERCENT_OF_RESIDUAL")
    else:
        if present(payload, "recoupment_pct"):
            fail("ERR_INVALID_REQUEST",
                 "recoupment_pct must be absent or null under STRAIGHT_LINE_AMORTIZATION")
        if amortization_months is None:
            fail("ERR_INVALID_REQUEST",
                 "amortization_months is required under STRAIGHT_LINE_AMORTIZATION")
    # band 5 -- field domains
    check_pct_range(recoupment_pct, "recoupment_pct")
    if recoupment_pct is not None and recoupment_pct <= Decimal("0"):
        fail("ERR_INVALID_PCT_RANGE", "recoupment_pct must be strictly greater than 0")
    check_month(first_month, "first_recoupment_month")
    check_month(last_month, "last_recoupment_month")
    # band 6 -- path existence
    agent = db.agents.get(agent_id)
    if agent is None:
        fail("ERR_AGENT_NOT_FOUND", "no agent with id %s" % agent_id)
    # band 8 -- optimistic concurrency
    if expected_agent_version != agent["version"]:
        fail("ERR_STALE_AGENT_VERSION",
             "expected_agent_version %d does not match the agent's current version %d"
             % (expected_agent_version, agent["version"]))
    # band 9 -- state precondition
    if agent["status"] != "ACTIVE":
        fail("ERR_AGENT_STATE_INVALID", "advances may only be funded to an ACTIVE agent")
    # band 11 -- business temporal
    _check_window(recoupment_mode, first_month, last_month, funded_on, amortization_months)
    # band 13 -- business fiscal
    _check_pct_cap(recoupment_pct)
    exposure = advance_outstanding_cents(agent_id) + principal_cents
    ceiling = max(
        BOOTSTRAP_ADVANCE_CEILING_CENTS,
        MAX_ADVANCE_EXPOSURE_MULTIPLE * trailing_residual_cents(agent_id),
    )
    if exposure > ceiling:
        fail("ERR_ADVANCE_EXPOSURE_EXCEEDED",
             "total advance exposure %d would exceed the ceiling %d" % (exposure, ceiling))
    row = {
        "id": new_id(),
        "agent_id": agent_id,
        "advance_type": advance_type,
        "recoupment_mode": recoupment_mode,
        "principal_cents": principal_cents,
        "recoupment_pct": recoupment_pct,
        "amortization_months": amortization_months,
        "first_recoupment_month": first_month,
        "last_recoupment_month": last_month,
        "funded_on": funded_on,
        "outstanding_cents": principal_cents,
        "cumulative_recouped_cents": 0,
        "months_recouped": 0,
        "state": "ACTIVE",
    }
    stamp_new(row)
    db.advances[row["id"]] = row
    touch(agent)
    return object_response(ser_advance(row), 201)


@bp.route("/agent-advances", methods=["GET"])
def list_advances():
    authorize("IsoAdmin", "ResidualController")
    rows = apply_filters(
        list(db.advances.values()),
        [("agent_id", "agent_id"), ("state", "state"),
         ("recoupment_mode", "recoupment_mode")])
    return list_response(ordered(rows), ser_advance)


@bp.route("/agent-advances/<advance_id>", methods=["GET"])
def get_advance(advance_id):
    authorize("IsoAdmin", "ResidualController")
    return object_response(ser_advance(_lookup(advance_id)))


@bp.route("/agent-advances/<advance_id>/restructure", methods=["POST"])
def restructure_advance(advance_id):
    authorize("IsoAdmin")
    payload = body()
    # band 4 -- request shape
    recoupment_mode = as_enum(payload, "recoupment_mode", RECOUPMENT_MODES, required=False)
    recoupment_pct = as_decimal(payload, "recoupment_pct", required=False)
    amortization_months = as_int(
        payload, "amortization_months", required=False, minimum=1, maximum=60)
    last_month = as_month_string(payload, "last_recoupment_month", required=False)
    if last_month is not None and not is_month(last_month):
        fail("ERR_INVALID_REQUEST", "last_recoupment_month must match YYYY-MM")
    # band 6 -- path existence
    row = _lookup(advance_id)
    # band 9 -- state precondition, reported ahead of the result-shape complaint
    if row["state"] != "ACTIVE":
        fail("ERR_ADVANCE_STATE_INVALID", "only an ACTIVE advance may be restructured")
    result_mode = recoupment_mode if recoupment_mode is not None else row["recoupment_mode"]
    result_pct = recoupment_pct if supplied(payload, "recoupment_pct") else row["recoupment_pct"]
    result_months = (
        amortization_months if supplied(payload, "amortization_months")
        else row["amortization_months"])
    result_last = last_month if last_month is not None else row["last_recoupment_month"]
    if result_mode == "STRAIGHT_LINE_AMORTIZATION" and result_months is None:
        fail("ERR_INVALID_REQUEST",
             "amortization_months is required under STRAIGHT_LINE_AMORTIZATION")
    if result_mode == "PERCENT_OF_RESIDUAL" and result_pct is None:
        fail("ERR_INVALID_REQUEST",
             "recoupment_pct is required under PERCENT_OF_RESIDUAL")
    # band 11 -- the window shape rule against the restructured terms
    _check_window(result_mode, row["first_recoupment_month"], result_last,
                  row["funded_on"], result_months)
    # band 13 -- the half-of-residual cap against the restructured terms
    _check_pct_cap(result_pct)
    row["recoupment_mode"] = result_mode
    row["recoupment_pct"] = result_pct
    row["amortization_months"] = result_months
    row["last_recoupment_month"] = result_last
    touch(row)
    return object_response(ser_advance(row))
