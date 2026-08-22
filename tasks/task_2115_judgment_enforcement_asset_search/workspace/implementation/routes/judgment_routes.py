"""Judgments: docketing, reads, the payoff quote and renewal."""

from flask import request

from auth import ALL_STAFF, check_judgment_ownership
from domain import (
    JUDGMENT_TERM_YEARS,
    MAX_RENEWALS,
    RENEWAL_FEE_CENTS,
    RENEWAL_TERM_YEARS,
    RENEWAL_WINDOW_DAYS,
    add_days,
    add_years,
    by_seq,
    get_creditor,
    get_debtor,
    get_judgment,
    guard_judgment_alive,
    recompute_balances,
    recount_creditor,
    refresh_totals,
    replay,
    to_date,
)
from errors import ApiError
from store import bump, new_row, store
from validators import (
    ENUM_APPLICATION_ORDER,
    check_enum,
    json_body,
    non_negative,
    parse_date,
    positive,
    present,
    require_date,
    require_int,
    require_state_code,
    require_string,
)
from web import endpoint, make_list

from .helpers import apply_filter, scope, serialize

READ_ROLES = ALL_STAFF + ("Creditor", "Debtor")


def register(app):
    # ---- POST /judgments --------------------------------------------------
    @endpoint(app, "/judgments", "POST", ("CaseManager",), 201)
    def create_judgment(ctx):
        body = json_body()
        # rung 6 - body foreign keys, in the declared field order
        creditor = get_creditor(body.get("creditor_id")) if present(body, "creditor_id") else None
        get_debtor(body.get("debtor_id")) if present(body, "debtor_id") else None
        # rung 7 - presence, type and declared ranges
        creditor_id = require_string(body, "creditor_id")
        debtor_id = require_string(body, "debtor_id")
        court_case_number = require_string(body, "court_case_number")
        state_code = require_state_code(body, "state_code")
        principal = require_int(body, "original_principal_cents")
        rate_bps = require_int(body, "interest_rate_bps")
        if rate_bps > 3000:
            raise ApiError("ERR_INVALID_REQUEST", "interest_rate_bps may not exceed 3000.")
        entered_on = require_date(body, "entered_on")
        filing_costs = require_int(body, "filing_costs_cents", optional=True, default=0)
        # rung 9 - sign constraints
        positive(principal, "original_principal_cents")
        non_negative(rate_bps, "interest_rate_bps")
        non_negative(filing_costs, "filing_costs_cents")
        # rung 33 - court_case_number is unique within state_code
        for existing in store.judgments.values():
            if existing["court_case_number"] == court_case_number and existing["state_code"] == state_code:
                raise ApiError("ERR_DUPLICATE_CASE_NUMBER",
                               "court_case_number already exists within this state.")

        row = new_row({
            "creditor_id": creditor_id,
            "debtor_id": debtor_id,
            "court_case_number": court_case_number,
            "state_code": state_code,
            "original_principal_cents": principal,
            "interest_rate_bps": rate_bps,
            "entered_on": entered_on.isoformat(),
            "filing_costs_cents": filing_costs,
            "expires_on": add_years(entered_on, JUDGMENT_TERM_YEARS).isoformat(),
            "principal_balance_cents": principal,
            "accrued_interest_cents": 0,
            "costs_balance_cents": filing_costs,
            "total_payoff_cents": principal + filing_costs,
            "accrued_through_on": None,
            "collected_to_date_cents": 0,
            "forgiven_cents": 0,
            "gross_exposure_cents": principal + filing_costs,
            "contingency_fee_cents": 0,
            "net_to_creditor_cents": 0,
            "application_order": "STATUTORY_ORDER",
            "status": "ACTIVE",
            "enforcement_posture": "NONE",
            "renewal_count": 0,
            "renewal_dates": [],
            "active_enforcement_count": 0,
            "open_offer_count": 0,
            "perfected_county_count": 0,
            "_recorded_fees": 0,
            "_sheriff_fees": 0,
        })
        store.judgments[row["id"]] = row
        recompute_balances(row)
        recount_creditor(creditor)
        bump(creditor)
        return serialize(row)

    # ---- GET /judgments ---------------------------------------------------
    @endpoint(app, "/judgments", "GET", READ_ROLES, 200)
    def list_judgments(ctx):
        from validators import pagination
        limit, offset = pagination(request.args)
        rows = by_seq(list(store.judgments.values()))
        rows = apply_filter(rows, request.args, "creditor_id")
        rows = apply_filter(rows, request.args, "debtor_id")
        rows = apply_filter(rows, request.args, "status")
        rows = apply_filter(rows, request.args, "enforcement_posture")
        rows = scope(ctx, rows, lambda r: r)
        return make_list(rows, limit, offset, serialize)

    # ---- GET /judgments/{judgment_id} ------------------------------------
    @endpoint(app, "/judgments/<judgment_id>", "GET", READ_ROLES, 200)
    def read_judgment(ctx, judgment_id):
        judgment = get_judgment(judgment_id)
        check_judgment_ownership(ctx, judgment)
        return serialize(judgment)

    # ---- GET /judgments/{judgment_id}/payoff ------------------------------
    @endpoint(app, "/judgments/<judgment_id>/payoff", "GET",
              ("CaseManager", "EnforcementOfficer", "ComplianceOfficer", "Creditor", "Debtor"), 200)
    def payoff_quote(ctx, judgment_id):
        judgment = get_judgment(judgment_id)
        check_judgment_ownership(ctx, judgment)
        raw_as_of = request.args.get("as_of")
        if raw_as_of is None or raw_as_of == "":
            as_of = store.clock_date()
        else:
            as_of = parse_date(raw_as_of)
            if as_of is None:
                raise ApiError("ERR_INVALID_REQUEST", "as_of must be an ISO 8601 calendar date.")
        raw_order = request.args.get("application_order")
        if raw_order is None or raw_order == "":
            order = judgment["application_order"]
        else:
            order = check_enum({"application_order": raw_order}, "application_order",
                               ENUM_APPLICATION_ORDER)
        result = replay(judgment, as_of, order)
        collected = judgment["collected_to_date_cents"]
        return {
            "as_of": as_of.isoformat(),
            "application_order": order,
            "principal_balance_cents": result["principal"],
            "accrued_interest_cents": result["interest"],
            "costs_balance_cents": result["costs"],
            "total_payoff_cents": result["total"],
            "collected_to_date_cents": collected,
            "gross_exposure_cents": result["total"] + collected,
            "segment_count": result["segments"],
        }

    # ---- POST /judgments/{judgment_id}/renew ------------------------------
    @endpoint(app, "/judgments/<judgment_id>/renew", "POST", ("ComplianceOfficer",), 200)
    def renew_judgment(ctx, judgment_id):
        judgment = get_judgment(judgment_id)
        # rungs 15 and 16 - a dead judgment is never renewed
        guard_judgment_alive(judgment)
        renewal_date = store.clock_date()
        expires_on = to_date(judgment["expires_on"])
        # rung 22 - the renewal window opens 180 days before expiry, inclusive
        if renewal_date < add_days(expires_on, -RENEWAL_WINDOW_DAYS):
            raise ApiError("ERR_RENEWAL_WINDOW_NOT_OPEN", "The renewal window is not open yet.")
        # rung 37 - at most two renewals
        if judgment["renewal_count"] >= MAX_RENEWALS:
            raise ApiError("ERR_RENEWAL_LIMIT_REACHED", "This judgment has no renewals left.")

        recompute_balances(judgment)
        judgment["principal_balance_cents"] += judgment["accrued_interest_cents"]
        judgment["accrued_interest_cents"] = 0
        judgment["costs_balance_cents"] += RENEWAL_FEE_CENTS
        judgment["renewal_dates"].append(renewal_date.isoformat())
        judgment["expires_on"] = add_years(expires_on, RENEWAL_TERM_YEARS).isoformat()
        judgment["renewal_count"] += 1
        judgment["accrued_through_on"] = renewal_date.isoformat()
        refresh_totals(judgment)
        bump(judgment)
        return serialize(judgment)
