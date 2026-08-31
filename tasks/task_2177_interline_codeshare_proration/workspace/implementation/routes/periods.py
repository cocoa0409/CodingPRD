"""Settlement calendar, FX quote table and the logical clock
(PRD sections 2.5, 3.3, 3.7)."""

from flask import Blueprint

import calculations as C
from calculations import (coupons_of_invoice, ffp_period_true_up,
                          recompute_net_position, round_half_up,
                          select_rate_scaled)
from errors import ApiError
from responses import ok
from routes.carriers import sweep_agreements
from store import db, fmt_dt, must_find, new_row, ordered, serialize, touch
import validation as V

bp = Blueprint("periods", __name__)


@bp.route("/interline/settlement-periods", methods=["POST"])
def create_period():
    V.require([V.ROLE_OPERATOR])
    data = V.body()
    period_code = V.req_str(data, "period_code")
    start_raw, start = V.req_dt(data, "period_start")
    end_raw, end = V.req_dt(data, "period_end")
    if end <= start:
        V.bad("period_end must be strictly after period_start.")
    deadline_raw, deadline = V.req_dt(data, "submission_deadline")
    fixing_raw, fixing = V.req_dt(data, "rate_fixing_date")
    settlement_currency = V.opt_enum(data, "settlement_currency", V.CURRENCIES,
                                     default="USD")

    # Half-open interval rule.
    for other in db.periods.values():
        if other["status"] not in ("OPEN", "CLOSED"):
            continue
        if start < other["_period_end"] and other["_period_start"] < end:
            raise ApiError("ERR_PERIOD_WINDOW_OVERLAP")

    period = new_row({
        "period_code": period_code,
        "period_start": start_raw,
        "period_end": end_raw,
        "submission_deadline": deadline_raw,
        "rate_fixing_date": fixing_raw,
        "settlement_currency": settlement_currency,
        "status": "OPEN",
        "cleared_invoice_count": 0,
        "closed_at": None,
        "settled_at": None,
    })
    period["_period_start"] = start
    period["_period_end"] = end
    period["_submission_deadline"] = deadline
    period["_rate_fixing_date"] = fixing
    db.periods[period["id"]] = period
    return ok(serialize(period), 201)


@bp.route("/interline/settlement-periods/<period_id>", methods=["GET"])
def get_period(period_id):
    V.require(V.ALL_ROLES)
    period = must_find("period", period_id)
    return ok(serialize(period))


@bp.route("/interline/settlement-periods/<period_id>/close", methods=["POST"])
def close_period(period_id):
    V.require([V.ROLE_OPERATOR])
    V.body()
    period = must_find("period", period_id)
    if period["status"] != "OPEN":
        raise ApiError("ERR_PERIOD_NOT_OPEN")

    submitted = ordered([i for i in db.invoices.values()
                         if i["settlement_period_id"] == period["id"]
                         and i["status"] == "SUBMITTED"])

    # Ladder step 42 — every required quote must resolve before anything moves.
    anchor = period["_rate_fixing_date"]
    rates = {}
    for invoice in submitted:
        rate = select_rate_scaled(invoice["billing_currency"],
                                  period["settlement_currency"], anchor)
        if rate is None:
            raise ApiError("ERR_NO_EXCHANGE_RATE")
        rates[invoice["id"]] = rate

    # Hop 1 — the period's own row is stamped first.
    closed_at = db.clock
    period["status"] = "CLOSED"
    period["closed_at"] = fmt_dt(closed_at)
    period["_closed_at"] = closed_at

    for invoice in submitted:
        # Hop 2 — the invoice clears at the fixed rate.
        rate = rates[invoice["id"]]
        final_settlement = round_half_up(
            invoice["total_claim_minor"] * rate, C.RATE_SCALE)
        invoice["fixed_rate_scaled"] = rate
        invoice["final_settlement_minor"] = final_settlement
        invoice["fx_variance_minor"] = (
            final_settlement - invoice["provisional_settlement_minor"])
        invoice["cleared_at"] = period["closed_at"]
        invoice["_cleared_at"] = closed_at
        invoice["status"] = "CLEARED"
        touch(invoice)
        period["cleared_invoice_count"] += 1

        # Hop 3 — balances move on both carriers.
        billing = db.carriers.get(invoice["billing_carrier_id"])
        billed = db.carriers.get(invoice["billed_carrier_id"])
        provisional = invoice["provisional_settlement_minor"]
        if billing is not None:
            billing["pending_receivable_minor"] -= provisional
            billing["settled_receivable_minor"] += final_settlement
            recompute_net_position(billing)
            touch(billing)
        if billed is not None:
            billed["pending_payable_minor"] -= provisional
            billed["settled_payable_minor"] += final_settlement
            recompute_net_position(billed)
            touch(billed)

    # Hop 4 — over-limit carriers are suspended.
    for carrier in ordered(list(db.carriers.values())):
        if carrier["status"] != "ACTIVE":
            continue
        exposure = (carrier["settled_payable_minor"]
                    - carrier["settled_receivable_minor"])
        if exposure > carrier["credit_limit_minor"]:
            carrier["status"] = "SUSPENDED"
            touch(carrier)
            # Hop 5 — their agreements follow.
            sweep_agreements(carrier)

    # The frequent-flyer true-up, independent of the five hops above.
    for carrier in ordered(list(db.carriers.values())):
        if ffp_period_true_up(carrier, period):
            touch(carrier)

    touch(period)
    return ok(serialize(period))


@bp.route("/interline/settlement-periods/<period_id>/settle", methods=["POST"])
def settle_period(period_id):
    V.require([V.ROLE_OPERATOR])
    V.body()
    period = must_find("period", period_id)
    if period["status"] != "CLOSED":
        raise ApiError("ERR_PERIOD_NOT_CLOSED")

    settled_at = db.clock
    period["status"] = "SETTLED"
    period["settled_at"] = fmt_dt(settled_at)
    period["_settled_at"] = settled_at

    invoices = ordered([i for i in db.invoices.values()
                        if i["settlement_period_id"] == period["id"]
                        and i["status"] in ("CLEARED", "PARTIALLY_REJECTED",
                                            "FULLY_REJECTED")])
    ticket_ids = []
    for invoice in invoices:
        for coupon in coupons_of_invoice(invoice["id"]):
            if coupon["ticket_id"] not in ticket_ids:
                ticket_ids.append(coupon["ticket_id"])
        invoice["status"] = "SETTLED"
        touch(invoice)

    for ticket in ordered([db.tickets[t] for t in ticket_ids
                           if t in db.tickets]):
        if ticket["billing_status"] == "BILLED":
            ticket["billing_status"] = "SETTLED"
            touch(ticket)

    for carrier in ordered(list(db.carriers.values())):
        if (carrier["period_accrued_miles"] != 0
                or carrier["period_ffp_cost_estimate_minor"] != 0):
            carrier["period_accrued_miles"] = 0
            carrier["period_ffp_cost_estimate_minor"] = 0
            touch(carrier)

    touch(period)
    return ok(serialize(period))


@bp.route("/interline/exchange-rates", methods=["POST"])
def create_exchange_rate():
    V.require([V.ROLE_OPERATOR])
    data = V.body()
    from_currency = V.req_enum(data, "from_currency", V.CURRENCIES)
    to_currency = V.req_enum(data, "to_currency", V.CURRENCIES)
    if from_currency == to_currency:
        V.bad("from_currency must differ from to_currency.")
    effective_raw, effective = V.req_dt(data, "effective_date")
    rate_scaled = V.req_int(data, "rate_scaled", minimum=1)

    for other in db.rates.values():
        if (other["from_currency"] == from_currency
                and other["to_currency"] == to_currency
                and other["_effective_date"] == effective):
            raise ApiError("ERR_DUPLICATE_EXCHANGE_RATE")

    rate = new_row({
        "from_currency": from_currency,
        "to_currency": to_currency,
        "effective_date": effective_raw,
        "rate_scaled": rate_scaled,
    }, versioned=False)
    rate["_effective_date"] = effective
    db.rates[rate["id"]] = rate
    return ok(serialize(rate), 201)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    V.require([V.ROLE_OPERATOR])
    data = V.body()
    _raw, parsed = V.req_dt(data, "to_iso8601")
    db.clock = parsed
    return ok({"current_utc": fmt_dt(db.clock)})
