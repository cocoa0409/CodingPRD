"""Tone trials, gear exchange and the conserved gear-credit balance.

PRD §3.8.
"""

from db import DB, add_days, iso, parse_dt
from errors import ApiError, Err
from middleware import guard
from response import (as_enum, as_str, body, created_obj, ensure_known, ok_obj,
                      page)
from services import calc, core

REASONS = ("TONE_MISMATCH", "DEFECT_DOA", "WRONG_MODEL", "CHANGED_MIND")
EXCHANGE_ROLES = ["PlatformAdmin", "SalesEngineerOps", "SupportAgent"]


def register(app):
    @app.route("/gear-exchanges", methods=["POST"])
    def create_exchange():
        guard(["SupportAgent"])
        data = body()
        ensure_known(data, ["quote_line_id", "customer_id", "reason"])
        line = core.fetch("quote_lines", as_str(data, "quote_line_id", required=True),
                          Err.REFERENCED_RESOURCE_NOT_FOUND)
        customer = core.fetch("customers", as_str(data, "customer_id", required=True),
                              Err.CUSTOMER_NOT_FOUND)
        row = core.new_row(
            "gear_exchanges",
            quote_line_id=line["id"],
            customer_id=customer["id"],
            reason=as_enum(data, "reason", REASONS),
            trial_start_date=None,
            trial_end_date=None,
            days_remaining=0,
            restocking_fee_bps=0,
            restocking_fee_cents=0,
            refund_credit_cents=0,
            status="DRAFT",
        )
        return created_obj(core.public(row))

    @app.route("/gear-exchanges", methods=["GET"])
    def list_exchanges():
        guard(EXCHANGE_ROLES)
        return page(core.all_rows("gear_exchanges"), filters=(
            ("customer_id", "customer_id", None),
            ("quote_line_id", "quote_line_id", None),
            ("status", "status", None),
        ))

    @app.route("/gear-exchanges/<ident>", methods=["GET"])
    def get_exchange(ident):
        guard(EXCHANGE_ROLES)
        return ok_obj(core.public(core.fetch("gear_exchanges", ident,
                                             Err.GEAR_EXCHANGE_NOT_FOUND)))

    @app.route("/gear-exchanges/<ident>/start-trial", methods=["POST"])
    def start_trial(ident):
        guard(["SupportAgent"])
        exchange = core.fetch("gear_exchanges", ident, Err.GEAR_EXCHANGE_NOT_FOUND)
        core.require_state(exchange, ("DRAFT",))
        # priority 8: an unowned account has no engineer to stand behind it.
        holder = core.active_assignment(exchange["customer_id"])
        if holder is None:
            raise ApiError(Err.CUSTOMER_ASSIGNMENT_REQUIRED)

        # The configured clock is a DATE (logical clock): the trial anchor is
        # the same calendar day the request is made.
        anchor = parse_dt(DB.now().strftime("%Y-%m-%dT00:00:00+00:00"))
        exchange["trial_start_date"] = iso(anchor)
        exchange["trial_end_date"] = iso(add_days(anchor, calc.TRIAL_WINDOW_DAYS))
        exchange["status"] = "TRIAL_ACTIVE"
        exchange["days_remaining"] = core.exchange_days_remaining(exchange)
        core.compute_restocking_fee(exchange, "provisional")
        return ok_obj(core.public(exchange))

    @app.route("/gear-exchanges/<ident>/request-return", methods=["POST"])
    def request_return(ident):
        guard(["SupportAgent"])
        exchange = core.fetch("gear_exchanges", ident, Err.GEAR_EXCHANGE_NOT_FOUND)
        core.require_state(exchange, ("TRIAL_ACTIVE",))
        exchange["days_remaining"] = core.exchange_days_remaining(exchange)
        if exchange["reason"] != "TONE_MISMATCH":
            # The record shows the denial and how much trial time remained.
            exchange["status"] = "DENIED"
            core.touch(exchange)
            raise ApiError(Err.RETURN_REASON_NOT_ELIGIBLE)
        exchange["status"] = "RETURN_REQUESTED"
        core.compute_restocking_fee(exchange, "final")
        return ok_obj(core.public(exchange))

    @app.route("/gear-exchanges/<ident>/withdraw-return", methods=["POST"])
    def withdraw_return(ident):
        guard(["SupportAgent"])
        exchange = core.fetch("gear_exchanges", ident, Err.GEAR_EXCHANGE_NOT_FOUND)
        core.require_state(exchange, ("RETURN_REQUESTED",))
        if _past_trial(exchange):
            raise ApiError(Err.TRIAL_WINDOW_EXPIRED)
        exchange["status"] = "TRIAL_ACTIVE"
        core.touch(exchange)
        return ok_obj(core.public(exchange))

    @app.route("/gear-exchanges/<ident>/complete", methods=["POST"])
    def complete_exchange(ident):
        guard(["SupportAgent"])
        exchange = core.fetch("gear_exchanges", ident, Err.GEAR_EXCHANGE_NOT_FOUND)
        core.require_state(exchange, ("RETURN_REQUESTED",))
        if _past_trial(exchange):
            raise ApiError(Err.TRIAL_WINDOW_EXPIRED)

        core.compute_restocking_fee(exchange, "final")
        line_total = core.exchange_line_total(exchange)
        exchange["refund_credit_cents"] = line_total - exchange["restocking_fee_cents"]
        exchange["status"] = "EXCHANGED"
        core.touch(exchange)

        # Hop 1 + hop 2: the refund credit lands, then the restocking fee is
        # credited back as an offset in the same mutation, so the conservation
        # invariant is exact and the two can never drift apart.
        customer = core.fetch("customers", exchange["customer_id"],
                              Err.CUSTOMER_NOT_FOUND)
        balance = int(customer.get("lifetime_gear_credit_cents") or 0)
        balance += exchange["refund_credit_cents"]
        balance += exchange["restocking_fee_cents"]
        customer["lifetime_gear_credit_cents"] = balance
        core.touch(customer)
        return ok_obj(core.public(exchange))

    @app.route("/gear-exchanges/<ident>/cancel", methods=["POST"])
    def cancel_exchange(ident):
        guard(["SupportAgent"])
        exchange = core.fetch("gear_exchanges", ident, Err.GEAR_EXCHANGE_NOT_FOUND)
        core.require_state(exchange, ("DRAFT", "TRIAL_ACTIVE", "RETURN_REQUESTED"))
        exchange["status"] = "CANCELLED"
        core.touch(exchange)
        return ok_obj(core.public(exchange))


def _past_trial(exchange):
    end = parse_dt(exchange.get("trial_end_date"))
    if end is None:
        return False
    # Half-open window: landing exactly on trial_end_date is still in time.
    return DB.now() > end