"""Tool Fleet Management Subscription & Jobsite Service API.

Flask entry point. Implements the full /fleet API per PRD.md + SCAFFOLD.yaml.
The store starts empty on every boot; the logical clock starts at
2026-09-01T00:00:00Z.
"""
import os
from datetime import timedelta

from flask import Flask, request

from errors import (
    ApiError, unauthenticated, forbidden, validation, not_found, stale_version,
    invalid_state, duty_segregation, window_expired, capacity_exceeded,
    window_overlap, loaner_pool_empty, open_claims, return_incomplete,
    application_approval_required, credit_limit_exceeded, duplicate,
)
from response import (
    ROLES, success, success_list, error_response, iso, parse_dt, body,
    req_field, opt_field, check_str, check_int, check_bool, check_enum,
    check_list, pagination_params,
)
from services import (
    SLA_DAYS, add_months, billable_assets, compute_monthly_billing,
    commit_billing, compute_sla_credit, compute_theft_cost,
    compute_utilization, compute_order_total, compute_settlement,
    allocate_loaner, jobsite_inc, jobsite_dec, touch, add_balance,
    advance_clock,
)
from store import store

app = Flask(__name__)

TOOL_CATEGORIES = ("DRILL", "SAW", "BREAKER", "MEASURING", "ANCHORING")
WEIGHT_CLASSES = ("LIGHT", "HEAVY")
END_OF_TERM_OPTIONS = ("BUYOUT", "RENEWAL", "RETURN")
ENTITY_ROLES = ("ContractorManager", "JobsiteSupervisor")

ALL_ROLES = ("FleetAdmin", "ContractorManager", "JobsiteSupervisor",
             "ServiceCoordinator", "ClaimsAdjuster", "FieldEngineer")


# ---------------------------------------------------------------------------
# auth helpers
# ---------------------------------------------------------------------------

def actor():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise unauthenticated()
    return uid, role


def require_role(*allowed):
    uid, role = actor()
    if role not in allowed:
        raise forbidden()
    return uid, role


def scope_account(account_id):
    """Entity-backed roles (ContractorManager / JobsiteSupervisor) may only
    touch resources of their own ContractorAccount; cross-account references
    are hidden as ERR_NOT_FOUND."""
    uid, role = actor()
    if role in ENTITY_ROLES and uid != account_id:
        raise not_found("Resource not found")


# ---------------------------------------------------------------------------
# fetch helpers
# ---------------------------------------------------------------------------

def get_account_or_404(account_id):
    a = store.accounts.get(account_id)
    if a is None:
        raise not_found("Account not found")
    return a


def get_agreement_or_404(agreement_id, account_id=None):
    ag = store.agreements.get(agreement_id)
    if ag is None or (account_id is not None and ag["account_id"] != account_id):
        raise not_found("Agreement not found")
    return ag


def get_asset_or_404(asset_id):
    a = store.assets.get(asset_id)
    if a is None:
        raise not_found("Asset not found")
    return a


def get_jobsite_or_404(jobsite_id, account_id=None):
    j = store.jobsites.get(jobsite_id)
    if j is None or (account_id is not None and j["account_id"] != account_id):
        raise not_found("Jobsite not found")
    return j


def get_ticket_or_404(ticket_id):
    t = store.repair_tickets.get(ticket_id)
    if t is None:
        raise not_found("Repair ticket not found")
    return t


def get_claim_or_404(claim_id):
    c = store.theft_claims.get(claim_id)
    if c is None:
        raise not_found("Theft claim not found")
    return c


def get_order_or_404(order_id, account_id=None):
    o = store.consumable_orders.get(order_id)
    if o is None or (account_id is not None and o["account_id"] != account_id):
        raise not_found("Consumable order not found")
    return o


def get_case_or_404(case_id, account_id=None):
    c = store.support_cases.get(case_id)
    if c is None or (account_id is not None and c["account_id"] != account_id):
        raise not_found("Support case not found")
    return c


def get_loaner_or_404(unit_id):
    u = store.loaner_units.get(unit_id)
    if u is None:
        raise not_found("Loaner unit not found")
    return u


def asset_account_id(asset):
    return store.agreements[asset["agreement_id"]]["account_id"]


def ticket_agreement(ticket):
    return store.agreements[store.assets[ticket["asset_id"]]["agreement_id"]]


def require_ticket_agreement_active(ticket):
    if ticket_agreement(ticket)["status"] != "ACTIVE":
        raise invalid_state("Agreement is not ACTIVE")


# ---------------------------------------------------------------------------
# serializers
# ---------------------------------------------------------------------------

def _common(r):
    return {"created_at": iso(r["created_at"]), "updated_at": iso(r["updated_at"]),
            "version": r["version"]}


def ser_account(a):
    d = {"id": a["id"], "company_name": a["company_name"], "tax_id": a["tax_id"],
         "credit_limit_cents": a["credit_limit_cents"], "status": a["status"],
         "outstanding_balance_cents": a["outstanding_balance_cents"]}
    d.update(_common(a))
    return d


def ser_rate_card(r):
    d = {"id": r["id"], "code": r["code"], "tool_category": r["tool_category"],
         "base_monthly_rate_cents": r["base_monthly_rate_cents"],
         "tier2_threshold": r["tier2_threshold"],
         "tier2_monthly_rate_cents": r["tier2_monthly_rate_cents"],
         "tier3_threshold": r["tier3_threshold"],
         "tier3_monthly_rate_cents": r["tier3_monthly_rate_cents"],
         "min_monthly_fee_cents": r["min_monthly_fee_cents"],
         "effective_from": iso(r["effective_from"]),
         "effective_to": iso(r["effective_to"]), "status": r["status"]}
    d.update(_common(r))
    return d


def ser_tool_model(m):
    d = {"id": m["id"], "model_code": m["model_code"], "category": m["category"],
         "replacement_value_cents": m["replacement_value_cents"],
         "weight_class": m["weight_class"]}
    d.update(_common(m))
    return d


def ser_agreement(ag):
    d = {"id": ag["id"], "account_id": ag["account_id"],
         "agreement_number": ag["agreement_number"],
         "term_months": ag["term_months"], "start_date": iso(ag["start_date"]),
         "end_date": iso(ag["end_date"]), "status": ag["status"],
         "end_of_term_option": ag["end_of_term_option"],
         "fleet_size_target": store.fleet_size_target(ag),
         "billed_this_month_cents": ag["billed_this_month_cents"],
         "theft_claim_count": store.theft_claim_count(ag)}
    d.update(_common(ag))
    return d


def ser_asset(a):
    d = {"id": a["id"], "agreement_id": a["agreement_id"],
         "tool_model_id": a["tool_model_id"], "serial_number": a["serial_number"],
         "tag_code": a["tag_code"], "status": a["status"],
         "current_jobsite_id": a["current_jobsite_id"],
         "pending_jobsite_id": a["pending_jobsite_id"],
         "commissioned_on": iso(a["commissioned_on"]),
         "utilization_minutes_current_month": a["utilization_minutes_current_month"]}
    d.update(_common(a))
    return d


def ser_jobsite(j):
    d = {"id": j["id"], "account_id": j["account_id"], "name": j["name"],
         "address": j["address"], "capacity_assets": j["capacity_assets"],
         "geofence_radius_m": j["geofence_radius_m"],
         "deployed_asset_count": j["deployed_asset_count"]}
    d.update(_common(j))
    return d


def ser_usage_event(e):
    return {"id": e["id"], "asset_id": e["asset_id"],
            "started_at": iso(e["started_at"]), "ended_at": iso(e["ended_at"]),
            "minutes": e["minutes"], "created_at": iso(e["created_at"])}


def ser_loaner(u):
    d = {"id": u["id"], "tool_model_id": u["tool_model_id"],
         "serial_number": u["serial_number"], "status": u["status"],
         "assigned_ticket_id": u["assigned_ticket_id"]}
    d.update(_common(u))
    return d


def ser_ticket(t):
    d = {"id": t["id"], "asset_id": t["asset_id"], "opened_at": iso(t["opened_at"]),
         "promised_return_by": iso(t["promised_return_by"]),
         "loaner_requested": t["loaner_requested"],
         "loaner_unit_id": t["loaner_unit_id"], "closed_at": iso(t["closed_at"]),
         "sla_breach_credit_cents": t["sla_breach_credit_cents"],
         "status": t["status"], "reopen_count": t["reopen_count"]}
    d.update(_common(t))
    return d


def ser_claim(c):
    d = {"id": c["id"], "asset_id": c["asset_id"],
         "reported_at": iso(c["reported_at"]),
         "police_report_number": c["police_report_number"],
         "police_report_filed_at": iso(c["police_report_filed_at"]),
         "verified_by": c["verified_by"],
         "approved_replacement_value_cents": c["approved_replacement_value_cents"],
         "deductible_cents": c["deductible_cents"], "status": c["status"]}
    d.update(_common(c))
    return d


def ser_product(p):
    d = {"id": p["id"], "sku": p["sku"], "name": p["name"],
         "unit_price_cents": p["unit_price_cents"], "pack_size": p["pack_size"],
         "requires_application_approval": p["requires_application_approval"]}
    d.update(_common(p))
    return d


def ser_order(o):
    d = {"id": o["id"], "account_id": o["account_id"], "lines": o["lines"],
         "status": o["status"], "total_cents": o["total_cents"],
         "submitted_at": iso(o["submitted_at"])}
    d.update(_common(o))
    return d


def ser_case(c):
    d = {"id": c["id"], "account_id": c["account_id"], "kind": c["kind"],
         "jobsite_id": c["jobsite_id"], "scheduled_for": iso(c["scheduled_for"]),
         "approved_by_engineer_id": c["approved_by_engineer_id"],
         "documentation_url": c["documentation_url"], "status": c["status"]}
    d.update(_common(c))
    return d


def ser_settlement(s):
    return {"id": s["id"], "agreement_id": s["agreement_id"], "option": s["option"],
            "provisional_amount_cents": s["provisional_amount_cents"],
            "final_amount_cents": s["final_amount_cents"],
            "finalized": s["finalized"], "created_at": iso(s["created_at"])}


def list_response(items, serializer):
    limit, offset = pagination_params()
    items = sorted(items, key=lambda r: r["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serializer(r) for r in page], total, limit, offset)


# ---------------------------------------------------------------------------
# logical clock
# ---------------------------------------------------------------------------

@app.post("/fleet/_clock/set_current_utc")
def clock_set():
    require_role("FleetAdmin")
    data = body()
    to = parse_dt(req_field(data, "to_iso8601"), "to_iso8601")
    advance_clock(to)
    return success({"current_utc": iso(store.clock.now())})


# ---------------------------------------------------------------------------
# accounts
# ---------------------------------------------------------------------------

@app.post("/fleet/accounts")
def create_account():
    require_role("FleetAdmin")
    data = body()
    company = check_str(req_field(data, "company_name"), "company_name")
    tax = check_str(req_field(data, "tax_id"), "tax_id")
    credit = check_int(req_field(data, "credit_limit_cents"), "credit_limit_cents", 0)
    if any(a["tax_id"] == tax for a in store.accounts.values()):
        raise duplicate("tax_id already exists")
    now = store.clock.stamp()
    acct = {"id": store.new_id(), "company_name": company, "tax_id": tax,
            "credit_limit_cents": credit, "status": "ACTIVE",
            "outstanding_balance_cents": 0,
            "created_at": now, "updated_at": now, "version": 1}
    store.accounts[acct["id"]] = acct
    return success(ser_account(acct), 201)


@app.get("/fleet/accounts/<account_id>")
def get_account(account_id):
    require_role(*ALL_ROLES)
    acct = get_account_or_404(account_id)
    scope_account(account_id)
    return success(ser_account(acct))


@app.post("/fleet/accounts/<account_id>/suspend")
def suspend_account(account_id):
    require_role("FleetAdmin")
    acct = get_account_or_404(account_id)
    if acct["status"] != "ACTIVE":
        raise invalid_state("Account is not ACTIVE")
    if not (acct["outstanding_balance_cents"] > acct["credit_limit_cents"]):
        raise credit_limit_exceeded("Outstanding balance does not exceed credit limit")
    acct["status"] = "SUSPENDED"
    touch(acct)
    for ag in store.agreements.values():
        if ag["account_id"] == account_id and ag["status"] == "ACTIVE":
            ag["status"] = "SUSPENDED"
            touch(ag)
    return success(ser_account(acct))


@app.post("/fleet/accounts/<account_id>/reinstate")
def reinstate_account(account_id):
    require_role("FleetAdmin")
    acct = get_account_or_404(account_id)
    if acct["status"] != "SUSPENDED":
        raise invalid_state("Account is not SUSPENDED")
    if not (acct["outstanding_balance_cents"] <= acct["credit_limit_cents"]):
        raise credit_limit_exceeded("Outstanding balance still exceeds credit limit")
    acct["status"] = "ACTIVE"
    touch(acct)
    for ag in store.agreements.values():
        if ag["account_id"] == account_id and ag["status"] == "SUSPENDED":
            ag["status"] = "ACTIVE"
            touch(ag)
    return success(ser_account(acct))


@app.post("/fleet/accounts/<account_id>/payments")
def record_payment(account_id):
    require_role("ContractorManager")
    data = body()
    amount = check_int(req_field(data, "amount_cents"), "amount_cents", 1)
    acct = get_account_or_404(account_id)
    scope_account(account_id)
    add_balance(acct, -amount)
    return success(ser_account(acct))


# ---------------------------------------------------------------------------
# rate cards & catalog
# ---------------------------------------------------------------------------

@app.post("/fleet/rate-cards")
def create_rate_card():
    require_role("FleetAdmin")
    data = body()
    code = check_str(req_field(data, "code"), "code")
    category = check_enum(req_field(data, "tool_category"), "tool_category", TOOL_CATEGORIES)
    base = check_int(req_field(data, "base_monthly_rate_cents"), "base_monthly_rate_cents", 0)
    t2th = check_int(req_field(data, "tier2_threshold"), "tier2_threshold", 1)
    t2rate = check_int(req_field(data, "tier2_monthly_rate_cents"), "tier2_monthly_rate_cents", 0)
    t3th = check_int(req_field(data, "tier3_threshold"), "tier3_threshold", 1)
    t3rate = check_int(req_field(data, "tier3_monthly_rate_cents"), "tier3_monthly_rate_cents", 0)
    minfee = check_int(req_field(data, "min_monthly_fee_cents"), "min_monthly_fee_cents", 0)
    eff_from = parse_dt(req_field(data, "effective_from"), "effective_from")
    eff_to = parse_dt(req_field(data, "effective_to"), "effective_to")
    if not eff_to > eff_from:
        raise validation("effective_to must be strictly later than effective_from")
    for rc in store.rate_cards.values():
        if (rc["tool_category"] == category and rc["status"] == "ACTIVE"
                and rc["effective_from"] <= eff_to and eff_from <= rc["effective_to"]):
            raise window_overlap("Closed-interval overlap with an existing ACTIVE rate card")
    if any(rc["code"] == code for rc in store.rate_cards.values()):
        raise duplicate("code already exists")
    now = store.clock.stamp()
    rc = {"id": store.new_id(), "code": code, "tool_category": category,
          "base_monthly_rate_cents": base, "tier2_threshold": t2th,
          "tier2_monthly_rate_cents": t2rate, "tier3_threshold": t3th,
          "tier3_monthly_rate_cents": t3rate, "min_monthly_fee_cents": minfee,
          "effective_from": eff_from, "effective_to": eff_to, "status": "ACTIVE",
          "created_at": now, "updated_at": now, "version": 1}
    store.rate_cards[rc["id"]] = rc
    return success(ser_rate_card(rc), 201)


@app.post("/fleet/tool-models")
def create_tool_model():
    require_role("FleetAdmin")
    data = body()
    code = check_str(req_field(data, "model_code"), "model_code")
    category = check_enum(req_field(data, "category"), "category", TOOL_CATEGORIES)
    value = check_int(req_field(data, "replacement_value_cents"), "replacement_value_cents", 0)
    wc = check_enum(req_field(data, "weight_class"), "weight_class", WEIGHT_CLASSES)
    if any(m["model_code"] == code for m in store.tool_models.values()):
        raise duplicate("model_code already exists")
    now = store.clock.stamp()
    m = {"id": store.new_id(), "model_code": code, "category": category,
         "replacement_value_cents": value, "weight_class": wc,
         "created_at": now, "updated_at": now, "version": 1}
    store.tool_models[m["id"]] = m
    return success(ser_tool_model(m), 201)


# ---------------------------------------------------------------------------
# agreements
# ---------------------------------------------------------------------------

@app.post("/fleet/accounts/<account_id>/agreements")
def create_agreement(account_id):
    require_role("FleetAdmin")
    data = body()
    term = check_int(req_field(data, "term_months"), "term_months", 1)
    start = parse_dt(req_field(data, "start_date"), "start_date")
    option = check_enum(req_field(data, "end_of_term_option"), "end_of_term_option",
                        END_OF_TERM_OPTIONS)
    get_account_or_404(account_id)
    now = store.clock.stamp()
    ag = {"id": store.new_id(), "account_id": account_id,
          "agreement_number": store.mint_agreement_number(),
          "term_months": term, "start_date": start,
          "end_date": add_months(start, term), "status": "DRAFT",
          "end_of_term_option": option, "billed_this_month_cents": 0,
          "created_at": now, "updated_at": now, "version": 1}
    store.agreements[ag["id"]] = ag
    return success(ser_agreement(ag), 201)


@app.get("/fleet/accounts/<account_id>/agreements")
def list_agreements(account_id):
    require_role("FleetAdmin", "ContractorManager")
    get_account_or_404(account_id)
    scope_account(account_id)
    items = [a for a in store.agreements.values() if a["account_id"] == account_id]
    return list_response(items, ser_agreement)


@app.get("/fleet/agreements/<agreement_id>")
def get_agreement(agreement_id):
    require_role("FleetAdmin", "ContractorManager", "JobsiteSupervisor")
    ag = get_agreement_or_404(agreement_id)
    scope_account(ag["account_id"])
    return success(ser_agreement(ag))


@app.post("/fleet/accounts/<account_id>/agreements/<agreement_id>/activate")
def activate_agreement(account_id, agreement_id):
    require_role("FleetAdmin")
    acct = get_account_or_404(account_id)
    ag = get_agreement_or_404(agreement_id, account_id)
    if ag["status"] != "DRAFT":
        raise invalid_state("Agreement is not DRAFT")
    if acct["status"] != "ACTIVE":
        raise invalid_state("Owning account is not ACTIVE")
    if store.fleet_size_target(ag) < 1:
        raise validation("Agreement has no assets; add at least one via adjust-fleet")
    if ag["start_date"].date() < store.clock.now().date():
        raise validation("start_date is earlier than the logical clock's current date")
    ag["status"] = "ACTIVE"
    amount = compute_monthly_billing(ag, prorate=True)
    commit_billing(ag, amount)
    touch(ag)
    return success(ser_agreement(ag))


@app.post("/fleet/accounts/<account_id>/agreements/<agreement_id>/adjust-fleet")
def adjust_fleet(account_id, agreement_id):
    require_role("ContractorManager")
    data = body()
    expected = check_int(req_field(data, "expected_agreement_version"),
                         "expected_agreement_version", 0)
    add_ids = opt_field(data, "add_tool_model_ids", [])
    return_ids = opt_field(data, "return_asset_ids", [])
    add_ids = [check_str(x, "add_tool_model_ids[]") for x in check_list(add_ids, "add_tool_model_ids")]
    return_ids = [check_str(x, "return_asset_ids[]") for x in check_list(return_ids, "return_asset_ids")]
    get_account_or_404(account_id)
    ag = get_agreement_or_404(agreement_id, account_id)
    scope_account(account_id)
    # existence of body-referenced ids (priority 4)
    models = []
    for mid in add_ids:
        m = store.tool_models.get(mid)
        if m is None:
            raise not_found("Tool model not found")
        models.append(m)
    returned = []
    for aid in return_ids:
        a = store.assets.get(aid)
        if a is None or a["agreement_id"] != agreement_id:
            raise not_found("Asset not found")
        returned.append(a)
    # OCC (priority 5)
    if expected != ag["version"]:
        raise stale_version()
    # state (priority 6)
    if ag["status"] not in ("DRAFT", "ACTIVE"):
        raise invalid_state("Fleet adjustment is only allowed in DRAFT or ACTIVE")
    for a in returned:
        if a["status"] != "REGISTERED":
            raise invalid_state("Only REGISTERED assets can be returned")
    now = store.clock.stamp()
    for m in models:
        asset = {"id": store.new_id(), "agreement_id": agreement_id,
                 "tool_model_id": m["id"],
                 "serial_number": store.mint_serial(m["id"]),
                 "tag_code": store.mint_tag_code(), "status": "REGISTERED",
                 "current_jobsite_id": None, "pending_jobsite_id": None,
                 "commissioned_on": None, "utilization_minutes_current_month": 0,
                 "_transfer_origin_jobsite_id": None,
                 "created_at": now, "updated_at": now, "version": 1}
        store.assets[asset["id"]] = asset
    for a in returned:
        a["status"] = "RETIRED"
        touch(a)
    if ag["status"] == "ACTIVE":
        amount = compute_monthly_billing(ag, prorate=True)
        commit_billing(ag, amount)
    touch(ag)
    return success(ser_agreement(ag))


@app.post("/fleet/accounts/<account_id>/agreements/<agreement_id>/elect-end-of-term")
def elect_end_of_term(account_id, agreement_id):
    require_role("ContractorManager")
    data = body()
    expected = check_int(req_field(data, "expected_agreement_version"),
                         "expected_agreement_version", 0)
    option = check_enum(req_field(data, "end_of_term_option"), "end_of_term_option",
                        END_OF_TERM_OPTIONS)
    get_account_or_404(account_id)
    ag = get_agreement_or_404(agreement_id, account_id)
    scope_account(account_id)
    if expected != ag["version"]:
        raise stale_version()
    if ag["status"] != "ACTIVE":
        raise invalid_state("Agreement is not ACTIVE")
    now = store.clock.now()
    if now < ag["end_date"] - timedelta(days=30):
        raise window_expired("Election window opens 30 days before end_date")
    for c in store.theft_claims.values():
        asset = store.assets.get(c["asset_id"])
        if (asset and asset["agreement_id"] == agreement_id
                and c["status"] in ("REPORTED", "POLICE_VERIFIED")):
            raise open_claims()
    ag["status"] = "ENDING"
    ag["end_of_term_option"] = option
    provisional = compute_settlement(ag, option)
    st = {"id": store.new_id(), "agreement_id": agreement_id, "option": option,
          "provisional_amount_cents": provisional, "final_amount_cents": None,
          "finalized": False, "created_at": store.clock.stamp()}
    store.settlements[st["id"]] = st
    touch(ag)
    return success(ser_agreement(ag))


@app.post("/fleet/accounts/<account_id>/agreements/<agreement_id>/finalize-settlement")
def finalize_settlement(account_id, agreement_id):
    require_role("FleetAdmin")
    data = body()
    assessed = opt_field(data, "assessed_damage_cents", None)
    if assessed is not None:
        assessed = check_int(assessed, "assessed_damage_cents", 0)
    get_account_or_404(account_id)
    ag = get_agreement_or_404(agreement_id, account_id)
    if ag["status"] != "ENDING":
        raise invalid_state("Agreement is not ENDING")
    option = ag["end_of_term_option"]
    if option == "RETURN":
        for a in store.assets.values():
            if a["agreement_id"] == agreement_id and a["status"] not in ("REGISTERED", "RETIRED"):
                raise return_incomplete()
    final = compute_settlement(ag, option, assessed)
    st = next((s for s in store.settlements.values()
               if s["agreement_id"] == agreement_id), None)
    if st is None:
        st = {"id": store.new_id(), "agreement_id": agreement_id, "option": option,
              "provisional_amount_cents": final, "final_amount_cents": None,
              "finalized": False, "created_at": store.clock.stamp()}
        store.settlements[st["id"]] = st
    st["final_amount_cents"] = final
    st["finalized"] = True
    if option == "BUYOUT":
        for a in store.assets.values():
            if a["agreement_id"] == agreement_id and a["status"] not in ("LOST", "RETIRED"):
                a["status"] = "RETIRED"
                a["current_jobsite_id"] = None
                a["pending_jobsite_id"] = None
                touch(a)
        ag["status"] = "CLOSED"
    elif option == "RETURN":
        ag["status"] = "CLOSED"
    else:  # RENEWAL
        ag["term_months"] += 12
        ag["end_date"] = add_months(ag["start_date"], ag["term_months"])
        ag["status"] = "ACTIVE"
    touch(ag)
    return success(ser_agreement(ag))


@app.get("/fleet/agreements/<agreement_id>/utilization")
def agreement_utilization(agreement_id):
    require_role("FleetAdmin", "ContractorManager")
    ag = get_agreement_or_404(agreement_id)
    scope_account(ag["account_id"])
    mode = request.args.get("mode", "ACTUAL")
    if mode not in ("ACTUAL", "PROJECTED"):
        raise validation("mode must be ACTUAL or PROJECTED")
    pct, count = compute_utilization(ag, mode)
    return success({"utilization_pct": float(pct), "mode": mode, "asset_count": count})


@app.get("/fleet/agreements/<agreement_id>/settlement")
def agreement_settlement(agreement_id):
    require_role("FleetAdmin", "ContractorManager")
    ag = get_agreement_or_404(agreement_id)
    scope_account(ag["account_id"])
    items = [s for s in store.settlements.values() if s["agreement_id"] == agreement_id]
    return list_response(items, ser_settlement)


# ---------------------------------------------------------------------------
# jobsites
# ---------------------------------------------------------------------------

@app.post("/fleet/accounts/<account_id>/jobsites")
def create_jobsite(account_id):
    require_role("ContractorManager")
    data = body()
    name = check_str(req_field(data, "name"), "name")
    address = check_str(req_field(data, "address"), "address")
    capacity = check_int(req_field(data, "capacity_assets"), "capacity_assets", 0)
    geofence = check_int(req_field(data, "geofence_radius_m"), "geofence_radius_m", 0)
    get_account_or_404(account_id)
    scope_account(account_id)
    now = store.clock.stamp()
    j = {"id": store.new_id(), "account_id": account_id, "name": name,
         "address": address, "capacity_assets": capacity,
         "geofence_radius_m": geofence, "deployed_asset_count": 0,
         "created_at": now, "updated_at": now, "version": 1}
    store.jobsites[j["id"]] = j
    return success(ser_jobsite(j), 201)


@app.get("/fleet/accounts/<account_id>/jobsites")
def list_jobsites(account_id):
    require_role("FleetAdmin", "ContractorManager", "JobsiteSupervisor")
    get_account_or_404(account_id)
    scope_account(account_id)
    items = [j for j in store.jobsites.values() if j["account_id"] == account_id]
    return list_response(items, ser_jobsite)


@app.get("/fleet/jobsites/<jobsite_id>")
def get_jobsite(jobsite_id):
    require_role("FleetAdmin", "ContractorManager", "JobsiteSupervisor")
    j = get_jobsite_or_404(jobsite_id)
    scope_account(j["account_id"])
    return success(ser_jobsite(j))


# ---------------------------------------------------------------------------
# assets
# ---------------------------------------------------------------------------

@app.get("/fleet/assets")
def list_assets():
    uid, role = require_role("FleetAdmin", "ContractorManager", "JobsiteSupervisor",
                             "ServiceCoordinator", "ClaimsAdjuster")
    items = list(store.assets.values())
    if role in ENTITY_ROLES:
        items = [a for a in items if asset_account_id(a) == uid]
    f_agreement = request.args.get("agreement_id")
    f_model = request.args.get("tool_model_id")
    f_current = request.args.get("current_jobsite_id")
    f_pending = request.args.get("pending_jobsite_id")
    f_status = request.args.get("status")
    if f_agreement is not None:
        items = [a for a in items if a["agreement_id"] == f_agreement]
    if f_model is not None:
        items = [a for a in items if a["tool_model_id"] == f_model]
    if f_current is not None:
        items = [a for a in items if a["current_jobsite_id"] == f_current]
    if f_pending is not None:
        items = [a for a in items if a["pending_jobsite_id"] == f_pending]
    if f_status is not None:
        items = [a for a in items if a["status"] == f_status]
    return list_response(items, ser_asset)


@app.get("/fleet/assets/<asset_id>")
def get_asset(asset_id):
    require_role("FleetAdmin", "ContractorManager", "JobsiteSupervisor",
                 "ServiceCoordinator", "ClaimsAdjuster")
    a = get_asset_or_404(asset_id)
    scope_account(asset_account_id(a))
    return success(ser_asset(a))


@app.post("/fleet/assets/<asset_id>/deploy")
def deploy_asset(asset_id):
    require_role("JobsiteSupervisor")
    data = body()
    jobsite_id = check_str(req_field(data, "jobsite_id"), "jobsite_id")
    a = get_asset_or_404(asset_id)
    ag = store.agreements[a["agreement_id"]]
    scope_account(ag["account_id"])
    j = get_jobsite_or_404(jobsite_id, ag["account_id"])
    if a["status"] != "REGISTERED":
        raise invalid_state("Asset is not REGISTERED")
    if ag["status"] != "ACTIVE":
        raise invalid_state("Agreement is not ACTIVE")
    if j["deployed_asset_count"] >= j["capacity_assets"]:
        raise capacity_exceeded("Jobsite is at capacity")
    a["status"] = "DEPLOYED"
    a["current_jobsite_id"] = j["id"]
    a["pending_jobsite_id"] = None
    if a["commissioned_on"] is None:
        a["commissioned_on"] = store.clock.now()
    jobsite_inc(j["id"])
    touch(a)
    return success(ser_asset(a))


@app.post("/fleet/assets/<asset_id>/transfer")
def transfer_asset(asset_id):
    require_role("JobsiteSupervisor")
    data = body()
    target_id = check_str(req_field(data, "target_jobsite_id"), "target_jobsite_id")
    a = get_asset_or_404(asset_id)
    ag = store.agreements[a["agreement_id"]]
    scope_account(ag["account_id"])
    target = get_jobsite_or_404(target_id, ag["account_id"])
    if a["status"] != "DEPLOYED":
        raise invalid_state("Asset is not DEPLOYED")
    if ag["status"] != "ACTIVE":
        raise invalid_state("Agreement is not ACTIVE")
    if target["deployed_asset_count"] >= target["capacity_assets"]:
        raise capacity_exceeded("Target jobsite is at capacity")
    a["_transfer_origin_jobsite_id"] = a["current_jobsite_id"]
    jobsite_dec(a["current_jobsite_id"])
    a["current_jobsite_id"] = None
    a["pending_jobsite_id"] = target["id"]
    a["status"] = "IN_TRANSIT"
    touch(a)
    return success(ser_asset(a))


@app.post("/fleet/assets/<asset_id>/confirm-arrival")
def confirm_arrival(asset_id):
    require_role("JobsiteSupervisor")
    a = get_asset_or_404(asset_id)
    scope_account(asset_account_id(a))
    if a["status"] != "IN_TRANSIT":
        raise invalid_state("Asset is not IN_TRANSIT")
    target_id = a["pending_jobsite_id"]
    a["current_jobsite_id"] = target_id
    a["pending_jobsite_id"] = None
    a["_transfer_origin_jobsite_id"] = None
    a["status"] = "DEPLOYED"
    jobsite_inc(target_id)
    touch(a)
    return success(ser_asset(a))


@app.post("/fleet/assets/<asset_id>/cancel-transfer")
def cancel_transfer(asset_id):
    require_role("JobsiteSupervisor")
    a = get_asset_or_404(asset_id)
    scope_account(asset_account_id(a))
    if a["status"] != "IN_TRANSIT":
        raise invalid_state("Asset is not IN_TRANSIT")
    origin_id = a["_transfer_origin_jobsite_id"]
    a["current_jobsite_id"] = origin_id
    a["pending_jobsite_id"] = None
    a["_transfer_origin_jobsite_id"] = None
    a["status"] = "DEPLOYED"
    jobsite_inc(origin_id)
    touch(a)
    return success(ser_asset(a))


@app.post("/fleet/assets/<asset_id>/check-in")
def check_in_asset(asset_id):
    require_role("JobsiteSupervisor")
    a = get_asset_or_404(asset_id)
    scope_account(asset_account_id(a))
    if a["status"] != "DEPLOYED":
        raise invalid_state("Asset is not DEPLOYED")
    jobsite_dec(a["current_jobsite_id"])
    a["current_jobsite_id"] = None
    a["status"] = "REGISTERED"
    touch(a)
    return success(ser_asset(a))


@app.post("/fleet/assets/<asset_id>/usage-events")
def create_usage_event(asset_id):
    require_role("JobsiteSupervisor")
    data = body()
    started = parse_dt(req_field(data, "started_at"), "started_at")
    ended = parse_dt(req_field(data, "ended_at"), "ended_at")
    if not ended > started:
        raise validation("ended_at must be strictly after started_at")
    now = store.clock.now()
    if (started.year, started.month) != (now.year, now.month) \
            or (ended.year, ended.month) != (now.year, now.month):
        raise validation("Both timestamps must lie in the clock's current calendar month")
    a = get_asset_or_404(asset_id)
    scope_account(asset_account_id(a))
    if a["status"] != "DEPLOYED":
        raise invalid_state("Asset is not DEPLOYED")
    minutes = int((ended - started).total_seconds() // 60)
    e = {"id": store.new_id(), "asset_id": asset_id, "started_at": started,
         "ended_at": ended, "minutes": minutes, "created_at": store.clock.stamp()}
    store.usage_events[e["id"]] = e
    a["utilization_minutes_current_month"] += minutes
    touch(a)
    return success(ser_usage_event(e), 201)


@app.get("/fleet/assets/<asset_id>/usage-events")
def list_usage_events(asset_id):
    require_role("FleetAdmin", "ContractorManager", "JobsiteSupervisor")
    a = get_asset_or_404(asset_id)
    scope_account(asset_account_id(a))
    items = [e for e in store.usage_events.values() if e["asset_id"] == asset_id]
    return list_response(items, ser_usage_event)


# ---------------------------------------------------------------------------
# repair tickets
# ---------------------------------------------------------------------------

@app.post("/fleet/assets/<asset_id>/repair-tickets")
def create_repair_ticket(asset_id):
    require_role("JobsiteSupervisor")
    data = body()
    loaner = check_bool(req_field(data, "loaner_requested"), "loaner_requested")
    a = get_asset_or_404(asset_id)
    scope_account(asset_account_id(a))
    if a["status"] != "DEPLOYED":
        raise invalid_state("Asset is not DEPLOYED")
    model = store.tool_models[a["tool_model_id"]]
    now = store.clock.now()
    t = {"id": store.new_id(), "asset_id": asset_id, "opened_at": now,
         "promised_return_by": now + timedelta(days=SLA_DAYS[model["weight_class"]]),
         "loaner_requested": loaner, "loaner_unit_id": None, "closed_at": None,
         "sla_breach_credit_cents": None, "status": "OPENED", "reopen_count": 0,
         "created_at": store.clock.stamp(), "updated_at": store.clock.stamp(),
         "version": 1}
    store.repair_tickets[t["id"]] = t
    jobsite_dec(a["current_jobsite_id"])
    a["status"] = "IN_REPAIR"
    touch(a)
    return success(ser_ticket(t), 201)


@app.get("/fleet/assets/<asset_id>/repair-tickets")
def list_repair_tickets_for_asset(asset_id):
    require_role("FleetAdmin", "ContractorManager", "JobsiteSupervisor",
                 "ServiceCoordinator")
    a = get_asset_or_404(asset_id)
    scope_account(asset_account_id(a))
    items = [t for t in store.repair_tickets.values() if t["asset_id"] == asset_id]
    return list_response(items, ser_ticket)


@app.get("/fleet/repair-tickets/<ticket_id>")
def get_repair_ticket(ticket_id):
    require_role("FleetAdmin", "ContractorManager", "JobsiteSupervisor",
                 "ServiceCoordinator")
    t = get_ticket_or_404(ticket_id)
    scope_account(asset_account_id(store.assets[t["asset_id"]]))
    return success(ser_ticket(t))


@app.post("/fleet/repair-tickets/<ticket_id>/schedule-pickup")
def schedule_pickup(ticket_id):
    require_role("ServiceCoordinator")
    t = get_ticket_or_404(ticket_id)
    if t["status"] != "OPENED":
        raise invalid_state("Ticket is not OPENED")
    require_ticket_agreement_active(t)
    t["status"] = "PICKUP_SCHEDULED"
    touch(t)
    return success(ser_ticket(t))


@app.post("/fleet/repair-tickets/<ticket_id>/receive")
def receive_ticket(ticket_id):
    require_role("ServiceCoordinator")
    t = get_ticket_or_404(ticket_id)
    if t["status"] not in ("PICKUP_SCHEDULED", "REOPENED"):
        raise invalid_state("Ticket is not PICKUP_SCHEDULED or REOPENED")
    require_ticket_agreement_active(t)
    if t["status"] == "REOPENED":
        model = store.tool_models[store.assets[t["asset_id"]]["tool_model_id"]]
        t["promised_return_by"] = store.clock.now() + timedelta(
            days=SLA_DAYS[model["weight_class"]])
    t["status"] = "IN_SHOP"
    touch(t)
    return success(ser_ticket(t))


@app.post("/fleet/repair-tickets/<ticket_id>/dispatch-loaner")
def dispatch_loaner(ticket_id):
    require_role("ServiceCoordinator")
    t = get_ticket_or_404(ticket_id)
    if t["status"] != "IN_SHOP":
        raise invalid_state("Ticket is not IN_SHOP")
    require_ticket_agreement_active(t)
    if not t["loaner_requested"]:
        raise invalid_state("No loaner was requested for this ticket")
    model_id = store.assets[t["asset_id"]]["tool_model_id"]
    unit = allocate_loaner(model_id)
    unit["status"] = "DISPATCHED"
    unit["assigned_ticket_id"] = t["id"]
    touch(unit)
    t["loaner_unit_id"] = unit["id"]
    t["status"] = "LOANER_DISPATCHED"
    touch(t)
    return success(ser_ticket(t))


@app.post("/fleet/repair-tickets/<ticket_id>/complete-repair")
def complete_repair(ticket_id):
    require_role("ServiceCoordinator")
    t = get_ticket_or_404(ticket_id)
    if t["status"] not in ("IN_SHOP", "LOANER_DISPATCHED"):
        raise invalid_state("Ticket is not IN_SHOP or LOANER_DISPATCHED")
    require_ticket_agreement_active(t)
    t["status"] = "QUALITY_CHECK"
    touch(t)
    return success(ser_ticket(t))


@app.post("/fleet/repair-tickets/<ticket_id>/close")
def close_ticket(ticket_id):
    require_role("ServiceCoordinator")
    t = get_ticket_or_404(ticket_id)
    if t["status"] != "QUALITY_CHECK":
        raise invalid_state("Ticket is not QUALITY_CHECK")
    require_ticket_agreement_active(t)
    t["closed_at"] = store.clock.now()
    credit = compute_sla_credit(t)
    t["sla_breach_credit_cents"] = credit
    if t["loaner_unit_id"]:
        unit = store.loaner_units[t["loaner_unit_id"]]
        # two-hop cascade within one call: DISPATCHED -> RETURNED -> AVAILABLE
        unit["status"] = "RETURNED"
        unit["status"] = "AVAILABLE"
        unit["assigned_ticket_id"] = None
        touch(unit)
        t["loaner_unit_id"] = None
    asset = store.assets[t["asset_id"]]
    asset["status"] = "DEPLOYED"
    jobsite_inc(asset["current_jobsite_id"])
    touch(asset)
    if credit > 0:
        add_balance(store.accounts[ticket_agreement(t)["account_id"]], -credit)
    t["status"] = "CLOSED"
    touch(t)
    return success(ser_ticket(t))


@app.post("/fleet/repair-tickets/<ticket_id>/reopen")
def reopen_ticket(ticket_id):
    require_role("JobsiteSupervisor")
    t = get_ticket_or_404(ticket_id)
    scope_account(asset_account_id(store.assets[t["asset_id"]]))
    if t["status"] != "CLOSED":
        raise invalid_state("Ticket is not CLOSED")
    if store.clock.now() > t["closed_at"] + timedelta(days=14):
        raise window_expired("Reopen window (14 days after close) has passed")
    if t["reopen_count"] >= 2:
        raise capacity_exceeded("Ticket has already been reopened twice")
    asset = store.assets[t["asset_id"]]
    if asset["status"] == "DEPLOYED":
        jobsite_dec(asset["current_jobsite_id"])
    asset["status"] = "IN_REPAIR"
    touch(asset)
    t["reopen_count"] += 1
    t["status"] = "REOPENED"
    touch(t)
    return success(ser_ticket(t))


# ---------------------------------------------------------------------------
# loaner units
# ---------------------------------------------------------------------------

@app.post("/fleet/loaner-units")
def create_loaner_unit():
    require_role("FleetAdmin")
    data = body()
    model_id = check_str(req_field(data, "tool_model_id"), "tool_model_id")
    serial = check_str(req_field(data, "serial_number"), "serial_number")
    if model_id not in store.tool_models:
        raise not_found("Tool model not found")
    if any(u["serial_number"] == serial for u in store.loaner_units.values()):
        raise duplicate("serial_number already exists")
    now = store.clock.stamp()
    u = {"id": store.new_id(), "tool_model_id": model_id, "serial_number": serial,
         "status": "AVAILABLE", "assigned_ticket_id": None,
         "created_at": now, "updated_at": now, "version": 1}
    store.loaner_units[u["id"]] = u
    return success(ser_loaner(u), 201)


@app.get("/fleet/loaner-units")
def list_loaner_units():
    require_role("FleetAdmin", "ServiceCoordinator")
    items = list(store.loaner_units.values())
    f_model = request.args.get("tool_model_id")
    f_ticket = request.args.get("assigned_ticket_id")
    f_status = request.args.get("status")
    if f_model is not None:
        items = [u for u in items if u["tool_model_id"] == f_model]
    if f_ticket is not None:
        items = [u for u in items if u["assigned_ticket_id"] == f_ticket]
    if f_status is not None:
        items = [u for u in items if u["status"] == f_status]
    return list_response(items, ser_loaner)


@app.get("/fleet/loaner-units/<unit_id>")
def get_loaner_unit(unit_id):
    require_role("FleetAdmin", "ServiceCoordinator")
    u = get_loaner_or_404(unit_id)
    return success(ser_loaner(u))


@app.post("/fleet/loaner-units/<unit_id>/decommission")
def decommission_loaner(unit_id):
    require_role("FleetAdmin")
    u = get_loaner_or_404(unit_id)
    if u["status"] != "AVAILABLE":
        raise invalid_state("Loaner unit is not AVAILABLE")
    u["status"] = "DECOMMISSIONED"
    touch(u)
    return success(ser_loaner(u))


# ---------------------------------------------------------------------------
# theft claims
# ---------------------------------------------------------------------------

@app.post("/fleet/assets/<asset_id>/theft-claims")
def create_theft_claim(asset_id):
    require_role("JobsiteSupervisor")
    a = get_asset_or_404(asset_id)
    scope_account(asset_account_id(a))
    if a["status"] != "DEPLOYED":
        raise invalid_state("Asset is not DEPLOYED")
    stamp = store.clock.stamp()
    c = {"id": store.new_id(), "asset_id": asset_id,
         "reported_at": store.clock.now(), "police_report_number": None,
         "police_report_filed_at": None, "verified_by": None,
         "approved_replacement_value_cents": None, "deductible_cents": None,
         "status": "REPORTED", "created_at": stamp, "updated_at": stamp,
         "version": 1}
    store.theft_claims[c["id"]] = c
    return success(ser_claim(c), 201)


@app.get("/fleet/assets/<asset_id>/theft-claims")
def list_theft_claims(asset_id):
    require_role("FleetAdmin", "ClaimsAdjuster")
    get_asset_or_404(asset_id)
    items = [c for c in store.theft_claims.values() if c["asset_id"] == asset_id]
    return list_response(items, ser_claim)


@app.post("/fleet/theft-claims/<claim_id>/verify-police-report")
def verify_police_report(claim_id):
    uid, _ = require_role("FleetAdmin")
    data = body()
    number = check_str(req_field(data, "police_report_number"), "police_report_number")
    filed = parse_dt(req_field(data, "police_report_filed_at"), "police_report_filed_at")
    c = get_claim_or_404(claim_id)
    if c["status"] != "REPORTED":
        raise invalid_state("Claim is not REPORTED")
    if filed > c["reported_at"] + timedelta(hours=48):
        raise window_expired("Police report filed outside the 48-hour window")
    c["police_report_number"] = number
    c["police_report_filed_at"] = filed
    c["verified_by"] = uid
    c["status"] = "POLICE_VERIFIED"
    touch(c)
    return success(ser_claim(c))


@app.post("/fleet/theft-claims/<claim_id>/decide")
def decide_theft_claim(claim_id):
    uid, _ = require_role("ClaimsAdjuster")
    data = body()
    decision = check_enum(req_field(data, "decision"), "decision", ("APPROVE", "DENY"))
    c = get_claim_or_404(claim_id)
    if c["status"] != "POLICE_VERIFIED":
        raise invalid_state("Claim is not POLICE_VERIFIED")
    if uid == c["verified_by"]:
        raise duty_segregation()
    if decision == "DENY":
        c["status"] = "DENIED"
        touch(c)
        return success(ser_claim(c))
    asset = store.assets[c["asset_id"]]
    agreement = store.agreements[asset["agreement_id"]]
    deductible, approved = compute_theft_cost(c, asset, agreement)
    c["deductible_cents"] = deductible
    c["approved_replacement_value_cents"] = approved
    c["status"] = "APPROVED"
    touch(c)
    # asset DEPLOYED -> LOST
    jobsite_dec(asset["current_jobsite_id"])
    asset["current_jobsite_id"] = None
    asset["status"] = "LOST"
    touch(asset)
    add_balance(store.accounts[agreement["account_id"]], deductible)
    return success(ser_claim(c))


# ---------------------------------------------------------------------------
# consumables
# ---------------------------------------------------------------------------

@app.post("/fleet/consumable-products")
def create_consumable_product():
    require_role("FleetAdmin")
    data = body()
    sku = check_str(req_field(data, "sku"), "sku")
    name = check_str(req_field(data, "name"), "name")
    price = check_int(req_field(data, "unit_price_cents"), "unit_price_cents", 0)
    pack = check_int(req_field(data, "pack_size"), "pack_size", 1)
    requires = check_bool(req_field(data, "requires_application_approval"),
                          "requires_application_approval")
    if any(p["sku"] == sku for p in store.consumable_products.values()):
        raise duplicate("sku already exists")
    now = store.clock.stamp()
    p = {"id": store.new_id(), "sku": sku, "name": name, "unit_price_cents": price,
         "pack_size": pack, "requires_application_approval": requires,
         "created_at": now, "updated_at": now, "version": 1}
    store.consumable_products[p["id"]] = p
    return success(ser_product(p), 201)


def _validate_order_lines(lines):
    lines = check_list(lines, "lines")
    out = []
    for line in lines:
        if not isinstance(line, dict):
            raise validation("Each line must be an object")
        pid = check_str(req_field(line, "product_id"), "lines[].product_id")
        qty = check_int(req_field(line, "quantity_units"), "lines[].quantity_units", 1)
        if pid not in store.consumable_products:
            raise not_found("Consumable product not found")
        out.append({"product_id": pid, "quantity_units": qty})
    return out


@app.post("/fleet/accounts/<account_id>/consumable-orders")
def create_consumable_order(account_id):
    require_role("ContractorManager")
    data = body()
    lines = _validate_order_lines(req_field(data, "lines"))
    get_account_or_404(account_id)
    scope_account(account_id)
    now = store.clock.stamp()
    o = {"id": store.new_id(), "account_id": account_id, "lines": lines,
         "status": "DRAFT", "total_cents": 0, "submitted_at": None,
         "created_at": now, "updated_at": now, "version": 1}
    o["total_cents"] = compute_order_total(o)
    store.consumable_orders[o["id"]] = o
    return success(ser_order(o), 201)


@app.get("/fleet/accounts/<account_id>/consumable-orders")
def list_consumable_orders(account_id):
    require_role("FleetAdmin", "ContractorManager")
    get_account_or_404(account_id)
    scope_account(account_id)
    items = [o for o in store.consumable_orders.values() if o["account_id"] == account_id]
    return list_response(items, ser_order)


@app.get("/fleet/consumable-orders/<order_id>")
def get_consumable_order(order_id):
    require_role("FleetAdmin", "ContractorManager")
    o = get_order_or_404(order_id)
    scope_account(o["account_id"])
    return success(ser_order(o))


@app.post("/fleet/accounts/<account_id>/consumable-orders/<order_id>/submit")
def submit_consumable_order(account_id, order_id):
    require_role("ContractorManager")
    acct = get_account_or_404(account_id)
    o = get_order_or_404(order_id, account_id)
    scope_account(account_id)
    if o["status"] != "DRAFT":
        raise invalid_state("Order is not DRAFT")
    if not o["lines"]:
        raise validation("Order lines are empty")
    if acct["status"] != "ACTIVE":
        raise invalid_state("Account is not ACTIVE")
    needs_approval = any(
        store.consumable_products[line["product_id"]]["requires_application_approval"]
        for line in o["lines"])
    if needs_approval:
        covered = any(
            c["account_id"] == account_id and c["kind"] == "ANCHOR_DESIGN"
            and c["status"] == "DOCUMENTED"
            for c in store.support_cases.values())
        if not covered:
            raise application_approval_required()
    o["total_cents"] = compute_order_total(o)
    o["submitted_at"] = store.clock.now()
    o["status"] = "SUBMITTED"
    touch(o)
    return success(ser_order(o))


@app.post("/fleet/accounts/<account_id>/consumable-orders/<order_id>/decide")
def decide_consumable_order(account_id, order_id):
    require_role("FleetAdmin")
    data = body()
    decision = check_enum(req_field(data, "decision"), "decision", ("APPROVE", "REJECT"))
    acct = get_account_or_404(account_id)
    o = get_order_or_404(order_id, account_id)
    if o["status"] != "SUBMITTED":
        raise invalid_state("Order is not SUBMITTED")
    if decision == "REJECT":
        o["status"] = "REJECTED"
        touch(o)
        return success(ser_order(o))
    if o["total_cents"] + acct["outstanding_balance_cents"] > acct["credit_limit_cents"]:
        raise credit_limit_exceeded("Order total would exceed the credit limit")
    o["status"] = "APPROVED"
    touch(o)
    add_balance(acct, o["total_cents"])
    return success(ser_order(o))


@app.post("/fleet/accounts/<account_id>/consumable-orders/<order_id>/fulfill")
def fulfill_consumable_order(account_id, order_id):
    require_role("FleetAdmin")
    get_account_or_404(account_id)
    o = get_order_or_404(order_id, account_id)
    if o["status"] != "APPROVED":
        raise invalid_state("Order is not APPROVED")
    o["status"] = "FULFILLED"
    touch(o)
    return success(ser_order(o))


# ---------------------------------------------------------------------------
# support cases
# ---------------------------------------------------------------------------

@app.post("/fleet/accounts/<account_id>/support-cases")
def create_support_case(account_id):
    require_role("ContractorManager")
    data = body()
    kind = check_enum(req_field(data, "kind"), "kind", ("ANCHOR_DESIGN", "FIRESTOP"))
    jobsite_id = check_str(req_field(data, "jobsite_id"), "jobsite_id")
    scheduled = parse_dt(req_field(data, "scheduled_for"), "scheduled_for")
    get_account_or_404(account_id)
    scope_account(account_id)
    get_jobsite_or_404(jobsite_id, account_id)
    start = scheduled
    end = scheduled + timedelta(hours=2)
    for c in store.support_cases.values():
        if c["jobsite_id"] == jobsite_id and c["status"] != "REJECTED":
            c_start = c["scheduled_for"]
            c_end = c_start + timedelta(hours=2)
            if start < c_end and c_start < end:
                raise window_overlap("Overlapping support-case window at this jobsite")
    now = store.clock.stamp()
    c = {"id": store.new_id(), "account_id": account_id, "kind": kind,
         "jobsite_id": jobsite_id, "scheduled_for": scheduled,
         "approved_by_engineer_id": None, "documentation_url": None,
         "status": "OPEN", "created_at": now, "updated_at": now, "version": 1}
    store.support_cases[c["id"]] = c
    return success(ser_case(c), 201)


@app.get("/fleet/support-cases")
def list_support_cases():
    uid, role = require_role("FleetAdmin", "ContractorManager", "FieldEngineer")
    items = list(store.support_cases.values())
    if role in ENTITY_ROLES:
        items = [c for c in items if c["account_id"] == uid]
    f_account = request.args.get("account_id")
    f_jobsite = request.args.get("jobsite_id")
    f_status = request.args.get("status")
    f_kind = request.args.get("kind")
    if f_account is not None:
        items = [c for c in items if c["account_id"] == f_account]
    if f_jobsite is not None:
        items = [c for c in items if c["jobsite_id"] == f_jobsite]
    if f_status is not None:
        items = [c for c in items if c["status"] == f_status]
    if f_kind is not None:
        items = [c for c in items if c["kind"] == f_kind]
    return list_response(items, ser_case)


@app.get("/fleet/support-cases/<case_id>")
def get_support_case(case_id):
    require_role("FleetAdmin", "ContractorManager", "FieldEngineer")
    c = get_case_or_404(case_id)
    scope_account(c["account_id"])
    return success(ser_case(c))


@app.post("/fleet/accounts/<account_id>/support-cases/<case_id>/review")
def review_support_case(account_id, case_id):
    uid, _ = require_role("FieldEngineer")
    data = body()
    decision = check_enum(req_field(data, "decision"), "decision", ("APPROVE", "REJECT"))
    doc_url = opt_field(data, "documentation_url", None)
    if decision == "APPROVE":
        doc_url = check_str(doc_url, "documentation_url")
    elif doc_url is not None:
        doc_url = check_str(doc_url, "documentation_url")
    get_account_or_404(account_id)
    c = get_case_or_404(case_id, account_id)
    if c["status"] != "OPEN":
        raise invalid_state("Support case is not OPEN")
    if decision == "APPROVE":
        c["status"] = "DOCUMENTED"
        c["approved_by_engineer_id"] = uid
        c["documentation_url"] = doc_url
    else:
        c["status"] = "REJECTED"
    touch(c)
    return success(ser_case(c))


# ---------------------------------------------------------------------------
# error handlers
# ---------------------------------------------------------------------------

@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def handle_404(err):
    return error_response(not_found("Resource not found"))


@app.errorhandler(405)
def handle_405(err):
    return error_response(not_found("Resource not found"))


@app.errorhandler(Exception)
def handle_exception(err):
    if isinstance(err, ApiError):
        return error_response(err)
    return error_response(ApiError("ERR_INTERNAL", "Internal server error", 500))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
