"""End-of-term elections: purchase, renew or remove (PRD §3.10)."""
from flask import Blueprint

import calc
from calc import RENEWAL_TERM_YEARS
from core import (
    ApiError, add_years, clock, fmt_date, fmt_instant, parse_date, sorted_rows,
    stamp_new, store, touch,
)
from guards import (
    OPEN_TRANSFER_STATUSES, TERMINAL_TRANSFER_STATUSES, homeowner_agreement_ids,
    homeowner_scope, lookup,
)
from serialize import election_view
from web import (
    apply_filters, authenticate, created, filters, ok, ok_list, paginate,
    pagination, validate_body,
)

bp = Blueprint("election_routes", __name__)

ELECTION_TYPES = ("PURCHASE", "RENEW", "REMOVAL")
ELECTION_STATUSES = ("SUBMITTED", "ACCEPTED", "EXECUTED", "WITHDRAWN")
OPEN_ELECTION_STATUSES = ("SUBMITTED", "ACCEPTED")
NOT_ACTIVE_STATES = ("DRAFT", "PREPAID_CLOSED", "PURCHASED_CLOSED")
ROOF_BLOCKING = ("APPROVED", "PANELS_REMOVED", "ROOF_COMPLETE")

ELECTION_SPECS = [
    {"name": "agreement_id", "kind": "id", "required": True},
    {"name": "election_type", "kind": "enum", "required": True,
     "values": ELECTION_TYPES},
]


@bp.post("/servicing/end-of-term-elections")
def create_election():
    user_id, role = authenticate(("Homeowner", "ServicingAgent", "PortfolioAdmin"))
    body = validate_body(ELECTION_SPECS)
    ag = lookup("agreements", body["agreement_id"])
    homeowner_scope(role, user_id, ag)
    # rung 8 — TRANSFER_PENDING is deliberately not claimed here
    if ag["lifecycle_state"] in NOT_ACTIVE_STATES:
        raise ApiError("ERR_AGREEMENT_NOT_ACTIVE",
                       "The agreement's lifecycle_state is %s."
                       % ag["lifecycle_state"])
    open_elections = [e for e in store.elections.values()
                      if e["agreement_id"] == ag["id"]
                      and e["status"] in OPEN_ELECTION_STATUSES]
    if open_elections:
        raise ApiError("ERR_ELECTION_ALREADY_OPEN",
                       "Another election for that agreement is still open.")
    if ag["lifecycle_state"] not in ("ACTIVE", "TRANSFER_PENDING"):
        if ag["service_status"] != "DECOMMISSIONED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "Only an ACTIVE agreement may receive an election.")
    # rung 10
    if ag["service_status"] == "DECOMMISSIONED":
        raise ApiError("ERR_AGREEMENT_DECOMMISSIONED",
                       "The agreement's asset is decommissioned.")
    # rung 11 — the window is closed at both ends
    today = clock.today()
    window_open, window_close = calc.election_window(ag)
    if today < window_open or today > window_close:
        raise ApiError("ERR_ELECTION_WINDOW_CLOSED",
                       "The election window runs %s..%s."
                       % (fmt_date(window_open), fmt_date(window_close)))
    # rung 12
    blocking = [c for c in store.transfer_cases.values()
                if c["agreement_id"] == ag["id"]
                and c["status"] in OPEN_TRANSFER_STATUSES]
    if blocking:
        raise ApiError("ERR_TRANSFER_IN_PROGRESS",
                       "A transfer case on that agreement is still open.")

    pricing = calc.election_pricing(ag, body["election_type"], today)
    election = {
        "agreement_id": ag["id"],
        "election_type": body["election_type"],
        "elected_on_date": fmt_date(today),
        "window_open_date": fmt_date(window_open),
        "window_close_date": fmt_date(window_close),
        "elapsed_full_years": pricing["elapsed_full_years"],
        "residual_pct": pricing["residual_pct"],
        "fair_market_value_cents": pricing["fair_market_value_cents"],
        "renewal_monthly_payment_cents": pricing["renewal_monthly_payment_cents"],
        "removal_cost_cents": pricing["removal_cost_cents"],
        "elected_amount_cents": pricing["elected_amount_cents"],
        "elected_by_user_id": user_id,
        "accepted_at": None,
        "executed_at": None,
        "status": "SUBMITTED",
    }
    stamp_new(election)
    store.elections[election["id"]] = election
    ag["lifecycle_state"] = "END_OF_TERM_PENDING"
    touch(ag)
    return created(election_view(election))


@bp.get("/servicing/end-of-term-elections/<election_id>")
def get_election(election_id):
    user_id, role = authenticate(("Homeowner", "ServicingAgent", "PortfolioAdmin"))
    election = lookup("elections", election_id)
    homeowner_scope(role, user_id, store.agreements.get(election["agreement_id"]))
    return ok(election_view(election))


@bp.get("/servicing/end-of-term-elections")
def list_elections():
    user_id, role = authenticate(("Homeowner", "ServicingAgent", "PortfolioAdmin"))
    limit, offset = pagination()
    flt = filters([
        ("agreement_id", "str", None),
        ("election_type", "enum", ELECTION_TYPES),
        ("status", "enum", ELECTION_STATUSES),
    ])
    rows = list(store.elections.values())
    if role == "Homeowner":
        if "agreement_id" in flt:
            homeowner_scope(role, user_id, store.agreements.get(flt["agreement_id"]))
        owned = homeowner_agreement_ids(user_id)
        rows = [r for r in rows if r["agreement_id"] in owned]
    rows = apply_filters(sorted_rows(rows), flt)
    page, total = paginate(rows, limit, offset)
    return ok_list([election_view(r) for r in page], limit, offset, total)


@bp.post("/servicing/end-of-term-elections/<election_id>/accept")
def accept_election(election_id):
    authenticate(("ServicingAgent", "PortfolioAdmin"))
    validate_body([])
    election = lookup("elections", election_id)
    ag = store.agreements[election["agreement_id"]]
    if election["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "Only a SUBMITTED election may be accepted.")
    # rung 12
    if election["election_type"] == "PURCHASE" and ag["credit_balance_cents"] > 0:
        raise ApiError("ERR_UNAPPLIED_CREDIT_BLOCKS_PURCHASE",
                       "Unapplied guarantee credit must be settled before a "
                       "purchase is accepted.")
    election["status"] = "ACCEPTED"
    election["accepted_at"] = fmt_instant(clock.now())
    touch(election)
    if election["election_type"] == "REMOVAL":
        ag["service_status"] = "DECOMMISSION_PENDING"
        touch(ag)
    return ok(election_view(election))


def terminate_filings_for_election(ag):
    """PRD §3.9: the election cascade reaches FILED and SUBORDINATED filings."""
    today = fmt_date(clock.today())
    for f in store.ucc_filings.values():
        if f["agreement_id"] != ag["id"]:
            continue
        if f["status"] not in ("FILED", "SUBORDINATED"):
            continue
        f["status"] = "TERMINATED"
        f["terminated_date"] = today
        touch(f)


@bp.post("/servicing/end-of-term-elections/<election_id>/execute")
def execute_election(election_id):
    authenticate(("PortfolioAdmin",))
    validate_body([])
    election = lookup("elections", election_id)
    ag = store.agreements[election["agreement_id"]]
    if election["status"] != "ACCEPTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "Only an ACCEPTED election may be executed.")
    # rung 12, in the order the PRD lists them
    for order in store.roof_work_orders.values():
        if (order["agreement_id"] == ag["id"]
                and order["status"] in ROOF_BLOCKING):
            raise ApiError("ERR_ROOF_WORK_IN_PROGRESS",
                           "A roof-work order on that agreement is in flight.")
    for case in store.transfer_cases.values():
        if (case["agreement_id"] == ag["id"]
                and case["status"] not in TERMINAL_TRANSFER_STATUSES):
            raise ApiError("ERR_TRANSFER_IN_PROGRESS",
                           "A transfer case on that agreement is still open.")

    etype = election["election_type"]
    if etype == "REMOVAL" and ag["service_status"] != "DECOMMISSION_PENDING":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "The asset must be DECOMMISSION_PENDING before removal.")
    election["status"] = "EXECUTED"
    election["executed_at"] = fmt_instant(clock.now())
    touch(election)
    if etype == "RENEW":
        ag["lifecycle_state"] = "ACTIVE"
        ag["renewal_count"] += 1
        ag["contract_end_date"] = fmt_date(
            add_years(parse_date(ag["contract_end_date"]), RENEWAL_TERM_YEARS))
    elif etype == "PURCHASE":
        ag["lifecycle_state"] = "PURCHASED_CLOSED"
        terminate_filings_for_election(ag)
    else:
        ag["lifecycle_state"] = "REMOVED_CLOSED"
        ag["service_status"] = "DECOMMISSIONED"
        terminate_filings_for_election(ag)
    touch(ag)
    return ok(election_view(election))


@bp.post("/servicing/end-of-term-elections/<election_id>/withdraw")
def withdraw_election(election_id):
    user_id, role = authenticate(("Homeowner", "ServicingAgent", "PortfolioAdmin"))
    validate_body([])
    election = lookup("elections", election_id)
    ag = store.agreements[election["agreement_id"]]
    homeowner_scope(role, user_id, ag)
    if election["status"] not in ("SUBMITTED", "ACCEPTED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "Only a pre-execution election may be withdrawn.")
    was_accepted = election["status"] == "ACCEPTED"
    election["status"] = "WITHDRAWN"
    touch(election)
    ag["lifecycle_state"] = "ACTIVE"
    if (was_accepted and election["election_type"] == "REMOVAL"
            and ag["service_status"] == "DECOMMISSION_PENDING"):
        ag["service_status"] = "IN_SERVICE"
    touch(ag)
    return ok(election_view(election))
