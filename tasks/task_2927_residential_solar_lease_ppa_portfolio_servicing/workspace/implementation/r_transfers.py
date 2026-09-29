"""Transfer at sale: assumption, prepayment and relocation (PRD §3.8)."""
from flask import Blueprint

import calc
from core import (
    ApiError, clock, fmt_date, fmt_instant, parse_date, sorted_rows, stamp_new,
    store, touch,
)
from guards import (
    OPEN_TRANSFER_STATUSES, TERMINAL_TRANSFER_STATUSES, homeowner_agreement_ids,
    homeowner_scope, lookup,
)
from serialize import agreement_view, transfer_case_view
from web import (
    apply_filters, authenticate, created, filters, ok, ok_list, paginate,
    pagination, validate_body,
)

bp = Blueprint("transfer_routes", __name__)

TRANSFER_TYPES = ("ASSUMPTION", "PREPAYMENT", "RELOCATION")
TRANSFER_STATUSES = ("INITIATED", "CREDIT_REVIEW", "CREDIT_APPROVED",
                     "CREDIT_DECLINED", "TITLE_CLEARED", "CLOSED", "CANCELLED")
NOT_ACTIVE_STATES = ("DRAFT", "PREPAID_CLOSED", "PURCHASED_CLOSED")

CASE_SPECS = [
    {"name": "agreement_id", "kind": "id", "required": True},
    {"name": "transfer_type", "kind": "enum", "required": True,
     "values": TRANSFER_TYPES},
    {"name": "closing_date", "kind": "date", "required": True},
    {"name": "buyer_homeowner_id", "kind": "id"},
    {"name": "new_site_address", "kind": "str", "minlen": 1, "maxlen": 200,
     "nonblank": True},
]

ASSUMPTION_CLEAR_OK = ("SUBORDINATED", "TERMINATED")
BUYOUT_CLEAR_OK = ("SUBORDINATED", "TERMINATION_REQUESTED", "TERMINATED")


def buyer_mismatch(message):
    return ApiError("ERR_BUYER_FIELD_MISMATCH", message)


@bp.post("/servicing/transfer-cases")
def create_transfer_case():
    authenticate(("ServicingAgent",))
    body = validate_body(CASE_SPECS)
    ag = lookup("agreements", body["agreement_id"])
    buyer = None
    if body.get("buyer_homeowner_id") is not None:
        buyer = lookup("homeowners", body["buyer_homeowner_id"])
    # rung 8
    if ag["lifecycle_state"] in NOT_ACTIVE_STATES:
        raise ApiError("ERR_AGREEMENT_NOT_ACTIVE",
                       "The agreement's lifecycle_state is %s."
                       % ag["lifecycle_state"])
    existing = [c for c in store.transfer_cases.values()
                if c["agreement_id"] == ag["id"]
                and c["status"] not in TERMINAL_TRANSFER_STATUSES]
    if existing:
        raise ApiError("ERR_TRANSFER_ALREADY_OPEN",
                       "Another transfer case for that agreement is still open.")
    if ag["lifecycle_state"] not in ("ACTIVE",) and ag["service_status"] != "DECOMMISSIONED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "Only an ACTIVE agreement may open a transfer case.")
    # rung 10
    if ag["service_status"] == "DECOMMISSIONED":
        raise ApiError("ERR_AGREEMENT_DECOMMISSIONED",
                       "The agreement's asset is decommissioned.")
    # rung 11
    closing = parse_date(body["closing_date"])
    if closing < clock.today():
        raise ApiError("ERR_CLOSING_DATE_IN_PAST",
                       "closing_date is before the current clock date.")
    # rung 12 — the field matrix
    ttype = body["transfer_type"]
    has_buyer = buyer is not None
    has_address = body.get("new_site_address") is not None
    if ttype == "ASSUMPTION":
        if not has_buyer:
            raise buyer_mismatch("An ASSUMPTION requires buyer_homeowner_id.")
        if has_address:
            raise buyer_mismatch("An ASSUMPTION may not carry new_site_address.")
        if buyer["id"] == ag["homeowner_id"]:
            raise buyer_mismatch("The buyer is already the agreement's homeowner.")
    elif ttype == "PREPAYMENT":
        if has_buyer:
            raise buyer_mismatch("A PREPAYMENT may not carry buyer_homeowner_id.")
        if has_address:
            raise buyer_mismatch("A PREPAYMENT may not carry new_site_address.")
    else:
        if has_buyer:
            raise buyer_mismatch("A RELOCATION may not carry buyer_homeowner_id.")
        if not has_address:
            raise buyer_mismatch("A RELOCATION requires new_site_address.")

    elapsed, remaining = calc.term_figures(ag, closing)
    case = {
        "agreement_id": ag["id"],
        "seller_homeowner_id": ag["homeowner_id"],
        "buyer_homeowner_id": buyer["id"] if buyer else None,
        "successor_agreement_id": None,
        "transfer_type": ttype,
        "closing_date": fmt_date(closing),
        "new_site_address": body.get("new_site_address"),
        "elapsed_term_months": elapsed,
        "remaining_term_months": remaining,
        "payoff_method": "NONE" if ttype == "ASSUMPTION" else None,
        "payoff_quote_cents": 0,
        "credit_fico_snapshot": None,
        "credit_dti_snapshot": None,
        "credit_composite_score": None,
        "credit_decision": None,
        "required_deposit_cents": 0,
        "credit_decided_by_user_id": None,
        "title_cleared_by_user_id": None,
        "status": "CREDIT_REVIEW" if ttype == "ASSUMPTION" else "INITIATED",
    }
    stamp_new(case)
    store.transfer_cases[case["id"]] = case
    ag["lifecycle_state"] = "TRANSFER_PENDING"
    touch(ag)
    return created(transfer_case_view(case))


@bp.get("/servicing/transfer-cases/<transfer_case_id>")
def get_transfer_case(transfer_case_id):
    user_id, role = authenticate(("ServicingAgent", "CreditUnderwriter", "TitleAgent",
                                  "PortfolioAdmin", "Homeowner"))
    case = lookup("transfer_cases", transfer_case_id)
    if role == "Homeowner" and case["buyer_homeowner_id"] != user_id:
        homeowner_scope(role, user_id, store.agreements.get(case["agreement_id"]))
    return ok(transfer_case_view(case))


@bp.get("/servicing/transfer-cases")
def list_transfer_cases():
    user_id, role = authenticate(("ServicingAgent", "CreditUnderwriter", "TitleAgent",
                                  "PortfolioAdmin", "Homeowner"))
    limit, offset = pagination()
    flt = filters([
        ("agreement_id", "str", None),
        ("seller_homeowner_id", "str", None),
        ("buyer_homeowner_id", "str", None),
        ("successor_agreement_id", "str", None),
        ("transfer_type", "enum", TRANSFER_TYPES),
        ("status", "enum", TRANSFER_STATUSES),
    ])
    rows = list(store.transfer_cases.values())
    if role == "Homeowner":
        if "agreement_id" in flt:
            homeowner_scope(role, user_id, store.agreements.get(flt["agreement_id"]))
        owned = homeowner_agreement_ids(user_id)
        rows = [r for r in rows
                if r["agreement_id"] in owned or r["buyer_homeowner_id"] == user_id]
    rows = apply_filters(sorted_rows(rows), flt)
    page, total = paginate(rows, limit, offset)
    return ok_list([transfer_case_view(r) for r in page], limit, offset, total)


@bp.post("/servicing/transfer-cases/<transfer_case_id>/run-credit-review")
def run_credit_review(transfer_case_id):
    user_id, role = authenticate(("CreditUnderwriter",))
    validate_body([])
    case = lookup("transfer_cases", transfer_case_id)
    ag = store.agreements[case["agreement_id"]]
    if case["status"] != "CREDIT_REVIEW":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "Only a CREDIT_REVIEW case may be underwritten.")
    buyer = store.homeowners[case["buyer_homeowner_id"]]
    fico, dti, composite, decision, deposit = calc.credit_qualification(ag, buyer)
    case["credit_fico_snapshot"] = fico
    case["credit_dti_snapshot"] = dti
    case["credit_composite_score"] = composite
    case["credit_decision"] = decision
    case["required_deposit_cents"] = deposit
    case["credit_decided_by_user_id"] = user_id
    if decision == "DECLINED":
        case["status"] = "CREDIT_DECLINED"
        ag["lifecycle_state"] = "ACTIVE"
        touch(ag)
    else:
        case["status"] = "CREDIT_APPROVED"
    touch(case)
    return ok(transfer_case_view(case))


@bp.post("/servicing/transfer-cases/<transfer_case_id>/clear-title")
def clear_title(transfer_case_id):
    user_id, role = authenticate(("TitleAgent",))
    validate_body([])
    case = lookup("transfer_cases", transfer_case_id)
    ag = store.agreements[case["agreement_id"]]
    ttype = case["transfer_type"]
    if ttype == "ASSUMPTION":
        if case["status"] != "CREDIT_APPROVED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "An ASSUMPTION must be CREDIT_APPROVED before title "
                           "clearance.")
        acceptable = ASSUMPTION_CLEAR_OK
    else:
        if case["status"] != "INITIATED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "Only an INITIATED buyout may clear title.")
        acceptable = BUYOUT_CLEAR_OK
    # rung 11
    if parse_date(case["closing_date"]) < clock.today():
        raise ApiError("ERR_CLOSING_DATE_IN_PAST",
                       "closing_date has slipped into the past.")
    # rung 12
    filings = [f for f in store.ucc_filings.values()
               if f["agreement_id"] == ag["id"]]
    for f in filings:
        if f["status"] not in acceptable:
            raise ApiError("ERR_TITLE_NOT_CLEAR",
                           "UCC filing %s is in %s." % (f["filing_number"],
                                                        f["status"]))
    case["status"] = "TITLE_CLEARED"
    case["title_cleared_by_user_id"] = user_id
    if ttype != "ASSUMPTION":
        case["payoff_method"] = ("NPV_REMAINING_PAYMENTS" if ttype == "PREPAYMENT"
                                 else "UNAMORTIZED_SYSTEM_COST")
        case["payoff_quote_cents"] = calc.payoff_quote(ag, case)
    for f in filings:
        if f.get("requested_by_transfer_case_id") is None:
            f["requested_by_transfer_case_id"] = case["id"]
            touch(f)
    if ttype == "RELOCATION":
        ag["service_status"] = "DECOMMISSION_PENDING"
        touch(ag)
    touch(case)
    return ok(transfer_case_view(case))


def terminate_filings_for_prepayment(ag, case):
    """PRD §3.8: the prepayment cascade reaches FILED, SUBORDINATED and
    TERMINATION_REQUESTED alike; a TERMINATED filing is never touched twice."""
    today = fmt_date(clock.today())
    for f in store.ucc_filings.values():
        if f["agreement_id"] != ag["id"] or f["status"] == "TERMINATED":
            continue
        was = f["status"]
        f["status"] = "TERMINATED"
        f["terminated_date"] = today
        if was in ("FILED", "SUBORDINATED"):
            f["requested_by_transfer_case_id"] = case["id"]
        touch(f)


def mint_successor_agreement(ag, case):
    """PRD §3.8: every economic term is copied verbatim; only the site moves."""
    tariff = store.tariffs.get(ag["tariff_id"])
    successor = {
        "homeowner_id": ag["homeowner_id"],
        "tariff_id": ag["tariff_id"],
        "relocated_from_agreement_id": ag["id"],
        "site_address": case["new_site_address"],
        "state_code": ag["state_code"],
        "product_type": ag["product_type"],
        "term_years": ag["term_years"],
        "contract_start_date": ag["contract_start_date"],
        "contract_end_date": None,
        "escalator_pct": ag["escalator_pct"],
        "base_monthly_lease_cents": ag["base_monthly_lease_cents"],
        "base_ppa_rate_per_kwh_millicents": ag["base_ppa_rate_per_kwh_millicents"],
        "guaranteed_annual_kwh": ag["guaranteed_annual_kwh"],
        "guarantee_band_pct": ag["guarantee_band_pct"],
        "system_dc_kw": ag["system_dc_kw"],
        "lifecycle_state": "ACTIVE",
        "monitoring_status": "MONITORING_OK",
        "service_status": "IN_SERVICE",
        "current_contract_year": 1,
        "credit_earned_cents": 0,
        "credit_applied_cents": 0,
        "credit_balance_cents": 0,
        "grandfathered_export_rate_millicents": (
            tariff["export_credit_rate_per_kwh_millicents"] if tariff else 0),
        "tariff_grandfathered": False,
        "renewal_count": 0,
        "open_outage_count": 0,
        "excused_downtime_minutes": 0,
    }
    successor["contract_end_date"] = fmt_date(calc.derive_contract_end_date(successor))
    stamp_new(successor)
    successor["tariff_grandfathered"] = calc.evaluate_grandfathered(successor, tariff)
    successor["current_contract_year"] = calc.current_contract_year(successor)
    store.agreements[successor["id"]] = successor
    return successor


@bp.post("/servicing/transfer-cases/<transfer_case_id>/close")
def close_transfer_case(transfer_case_id):
    authenticate(("ServicingAgent", "PortfolioAdmin"))
    validate_body([])
    case = lookup("transfer_cases", transfer_case_id)
    ag = store.agreements[case["agreement_id"]]
    if case["status"] != "TITLE_CLEARED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "Only a TITLE_CLEARED case may be closed.")
    if clock.today() < parse_date(case["closing_date"]):
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "The clock date has not reached closing_date.")
    ttype = case["transfer_type"]
    if ttype == "ASSUMPTION":
        ag["lifecycle_state"] = "ACTIVE"
        ag["homeowner_id"] = case["buyer_homeowner_id"]
    elif ttype == "PREPAYMENT":
        ag["lifecycle_state"] = "PREPAID_CLOSED"
        applied = min(ag["credit_balance_cents"], case["payoff_quote_cents"])
        ag["credit_applied_cents"] += applied
        ag["credit_balance_cents"] -= applied
        terminate_filings_for_prepayment(ag, case)
    else:
        ag["lifecycle_state"] = "RELOCATED_CLOSED"
        ag["service_status"] = "DECOMMISSIONED"
        successor = mint_successor_agreement(ag, case)
        case["successor_agreement_id"] = successor["id"]
    case["status"] = "CLOSED"
    touch(case)
    touch(ag)
    return ok(transfer_case_view(case))


@bp.post("/servicing/transfer-cases/<transfer_case_id>/cancel")
def cancel_transfer_case(transfer_case_id):
    authenticate(("ServicingAgent", "PortfolioAdmin"))
    validate_body([])
    case = lookup("transfer_cases", transfer_case_id)
    ag = store.agreements[case["agreement_id"]]
    if case["status"] not in OPEN_TRANSFER_STATUSES:
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "Only an open transfer case may be cancelled.")
    was_cleared = case["status"] == "TITLE_CLEARED"
    case["status"] = "CANCELLED"
    touch(case)
    ag["lifecycle_state"] = "ACTIVE"
    if (was_cleared and case["transfer_type"] == "RELOCATION"
            and ag["service_status"] == "DECOMMISSION_PENDING"):
        ag["service_status"] = "IN_SERVICE"
    touch(ag)
    return ok(transfer_case_view(case))
