"""Risk-registry pricing rows and state lifetime-plan regulations."""

from flask import request

from constants import ALL_STATES_KEY
from db import DB
from middleware import guard
from response import (ApiError, Err, as_enum, as_int, as_num, as_str, body,
                      created_obj, ensure_known, ok_list, pagination,
                      sorted_by_created)
from services import core


def register(app):
    # --- credit-limit-registry-state -------------------------------------
    @app.route("/credit-limit-registry-state", methods=["POST"])
    def create_registry_row():
        guard(["ChainAdmin"])
        data = body()
        ensure_known(data, ["registry_key", "credit_tier", "base_limit_cents",
                            "min_down_payment_pct", "registry_type", "min_ticket_cents",
                            "all_states_key"],
                     optional=("min_ticket_cents", "all_states_key"))
        registry_type = as_enum(data, "registry_type", ("STATE", "GLOBAL"))
        all_states_key = data.get("all_states_key")
        if all_states_key is None:
            all_states_key = ALL_STATES_KEY
        if not isinstance(all_states_key, str):
            raise ApiError(Err.INVALID_REQUEST, "all_states_key must be a string.")
        row = core.new_row(
            "registry",
            registry_key=as_str(data, "registry_key"),
            credit_tier=as_enum(data, "credit_tier", ("TIER_1", "TIER_2", "TIER_3")),
            base_limit_cents=as_int(data, "base_limit_cents", required=True),
            min_down_payment_pct=as_num(data, "min_down_payment_pct", required=True),
            min_ticket_cents=as_int(data, "min_ticket_cents", default=0),
            all_states_key=all_states_key,
            registry_type=registry_type,
        )
        return created_obj(row)

    @app.route("/credit-limit-registry-state", methods=["GET"])
    def list_registry_rows():
        guard(["ChainAdmin", "CreditAnalyst", "StoreManager"])
        limit, offset = pagination()
        rows = DB.all("registry")
        for field in ("registry_key", "credit_tier", "registry_type"):
            value = request.args.get(field)
            if value is not None:
                rows = [r for r in rows if r[field] == value]
        rows = sorted_by_created(rows)
        return ok_list(rows, limit, offset, len(rows))

    # --- service-plan-regulations ---------------------------------------
    @app.route("/service-plan-regulations", methods=["POST"])
    def create_regulation():
        guard(["ChainAdmin"])
        data = body()
        ensure_known(data, ["state_code", "max_plan_term_months", "inspection_required_months",
                            "lapse_cure_days", "replacement_plus_pct",
                            "max_inspection_gap_days"],
                     optional=("max_inspection_gap_days",))
        row = core.new_row(
            "regulations",
            state_code=as_str(data, "state_code"),
            max_plan_term_months=as_int(data, "max_plan_term_months", required=True),
            inspection_required_months=as_int(data, "inspection_required_months", required=True),
            lapse_cure_days=as_int(data, "lapse_cure_days", required=True),
            replacement_plus_pct=as_num(data, "replacement_plus_pct", required=True),
            max_inspection_gap_days=as_int(data, "max_inspection_gap_days", default=0),
        )
        return created_obj(row)

    @app.route("/service-plan-regulations", methods=["GET"])
    def list_regulations():
        guard(["ChainAdmin", "StoreManager", "CreditAnalyst", "CustomerService"])
        limit, offset = pagination()
        rows = DB.all("regulations")
        state = request.args.get("state_code")
        if state is not None:
            rows = [r for r in rows if r["state_code"] == state]
        rows = sorted_by_created(rows)
        return ok_list(rows, limit, offset, len(rows))