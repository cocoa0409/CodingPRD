"""Traffic monitoring windows and the customer risk index (PRD 3.7)."""
from decimal import Decimal

from flask import Blueprint

import auth
import calc
import derive
import envelope
import errors
import ser
import store
import valid
from store import db, touch
from views_customer import load_customer
from views_provider import load_provider

bp = Blueprint("observations", __name__)

READ_ROLES = (auth.REGULATOR, auth.COMPLIANCE_OFFICER, auth.FRAUD_ANALYST,
              auth.PROVIDER_ADMIN)


def load_observation(observation_id):
    row = db.observations.get(observation_id)
    if row is None:
        errors.fail(errors.ERR_OBSERVATION_NOT_FOUND,
                    "No traffic observation with id %s" % observation_id)
    return row


@bp.route("/rmd/traffic-observations", methods=["POST"])
@auth.require(auth.PROVIDER_ADMIN)
def record_observation():
    data = valid.body()
    provider_id = valid.req_str(data, "provider_id")
    customer_id = valid.req_str(data, "customer_id")
    window_start, raw_start = valid.req_dt(data, "window_start")
    window_end, raw_end = valid.req_dt(data, "window_end")
    total = valid.req_count(data, "total_call_count")
    short = valid.req_count(data, "short_duration_call_count")
    unanswered = valid.req_count(data, "unanswered_call_count")
    complaints = valid.req_count(data, "complaint_count")
    if short > total:
        errors.fail(errors.ERR_INVALID_REQUEST,
                    "short_duration_call_count may not exceed "
                    "total_call_count")
    if unanswered > total:
        errors.fail(errors.ERR_INVALID_REQUEST,
                    "unanswered_call_count may not exceed total_call_count")
    valid.check_interval(window_start, window_end)
    load_provider(provider_id)
    customer = load_customer(customer_id)
    auth.own_provider(provider_id)

    now = db.now()
    if window_end > now:
        errors.fail(errors.ERR_WINDOW_IN_FUTURE,
                    "window_end lies after the current logical clock")
    for other in derive.observations_of(customer_id):
        if (window_start <= other["window_end"]
                and other["window_start"] <= window_end):
            errors.fail(errors.ERR_OBSERVATION_WINDOW_OVERLAP,
                        "The closed monitoring window touches or overlaps an "
                        "existing window of this customer")
    if customer["provider_id"] != provider_id:
        errors.fail(errors.ERR_CUSTOMER_PROVIDER_MISMATCH,
                    "The customer belongs to another provider")

    row = store.base_row(versioned=False)
    row.update({
        "provider_id": provider_id,
        "customer_id": customer_id,
        "window_start": window_start,
        "window_end": window_end,
        "total_call_count": total,
        "short_duration_call_count": short,
        "unanswered_call_count": unanswered,
        "complaint_count": complaints,
        "window_subscore": float(
            calc.window_subscore(total, short, unanswered, complaints)),
        "recorded_by_user_id": auth.acting_id(),
        "resulting_risk_index": 0.0,
        "triggered_suspension": False,
    })
    store.remember_raw(row, "window_start", raw_start)
    store.remember_raw(row, "window_end", raw_end)
    db.observations[row["id"]] = row

    values = derive.customer_derived(customer)
    customer.update(values)
    row["resulting_risk_index"] = values["traffic_risk_index"]
    triggered = (
        Decimal(str(values["traffic_risk_index"]))
        >= calc.AUTO_SUSPEND_THRESHOLD
        and customer["origination_state"] == "ENABLED")
    row["triggered_suspension"] = triggered
    if triggered:
        derive._mark_suspended(customer, "TRAFFIC_RISK_THRESHOLD", row["id"])
    touch(customer)
    if triggered:
        derive.cascade_suspend_assignments(customer)
    derive.recompute_provider_by_id(provider_id)
    return envelope.created(ser.observation(row))


@bp.route("/rmd/traffic-observations/<observation_id>", methods=["GET"])
@auth.require(*READ_ROLES)
def read_observation(observation_id):
    row = load_observation(observation_id)
    auth.own_provider(row["provider_id"])
    return envelope.ok(ser.observation(row))


@bp.route("/rmd/traffic-observations", methods=["GET"])
@auth.require(*READ_ROLES)
def list_observations():
    limit, offset = envelope.pagination()
    provider_id = valid.arg_str("provider_id")
    customer_id = valid.arg_str("customer_id")

    rows = auth.scope_rows(db.observations.values(),
                           provider_of=lambda r: r["provider_id"])
    if provider_id is not None:
        rows = [r for r in rows if r["provider_id"] == provider_id]
    if customer_id is not None:
        rows = [r for r in rows if r["customer_id"] == customer_id]
    return envelope.collection(rows, ser.observation, limit, offset)
