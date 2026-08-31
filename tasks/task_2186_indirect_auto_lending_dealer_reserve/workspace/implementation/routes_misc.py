"""Routes: reserve ledger, buyback demands, fair lending reviews."""
from flask import Blueprint, g

from core import (
    store, clock, new_rec, bump, stamp, putdt, dtv, fail, ok, list_response,
    require_roles, scope_dealer_id, scope_body_dealer_id, get_body,
    v_str, v_int, v_enum, v_dt, v_id, get_dealer, get_contract, get_demand,
    get_review, get_entry, qfilter, is_dealer_principal, serialize, ALL_ROLES,
    months_from_days, MIN_REVIEW_POPULATION,
)
import services as S

bp = Blueprint("misc", __name__)

DEMAND_ACTIONS = ("ACKNOWLEDGE", "DISPUTE", "SETTLE", "WITHDRAW")
DEALER_DEMAND_ACTIONS = ("ACKNOWLEDGE", "DISPUTE")
ADMIN_DEMAND_ACTIONS = ("SETTLE", "WITHDRAW")


# ---------------------------------------------------------------------------
# Reserve ledger
# ---------------------------------------------------------------------------
@bp.route("/lending/reserve-entries", methods=["GET"])
def list_reserve_entries():
    require_roles(*ALL_ROLES)
    records = list(store.entries.values())
    if is_dealer_principal():
        records = [e for e in records if e["dealer_id"] == g.user_id]
    for name in ("dealer_id", "contract_id", "entry_type"):
        value = qfilter(name)
        if value is not None:
            records = [e for e in records if e.get(name) == value]
    records.sort(key=lambda e: (e.get("created_at") or "", e.get("_seq") or 0))
    return list_response(records)


@bp.route("/lending/reserve-entries/<entry_id>", methods=["GET"])
def read_reserve_entry(entry_id):
    require_roles(*ALL_ROLES)
    entry = get_entry(entry_id)
    scope_dealer_id(entry["dealer_id"])
    return ok(serialize(entry))


# ---------------------------------------------------------------------------
# Buyback demands
# ---------------------------------------------------------------------------
@bp.route("/lending/buyback-demands", methods=["POST"])
def create_demand():
    require_roles("PortfolioAdmin")
    body = get_body()
    contract_id = v_id(body, "contract_id", required=True)
    reason = v_enum(body, "reason", ("DOC_DEFECT", "EARLY_DEFAULT", "FRAUD", "DEALER_TERMINATION"),
                    required=True)
    contract = get_contract(contract_id)
    scope_dealer_id(contract["dealer_id"])

    if contract["funding_status"] != "FUNDED" or S.has_open_demand(contract_id):
        fail("ERR_CONTRACT_NOT_FUNDED", "The contract is not FUNDED or already carries an open demand.")

    dealer = get_dealer(contract["dealer_id"])
    demand = S.issue_demand(dealer, contract, reason)
    return ok(serialize(demand), 201)


@bp.route("/lending/buyback-demands/<demand_id>", methods=["GET"])
def read_demand(demand_id):
    require_roles(*ALL_ROLES)
    demand = get_demand(demand_id)
    scope_dealer_id(demand["dealer_id"])
    return ok(serialize(demand))


@bp.route("/lending/buyback-demands", methods=["GET"])
def list_demands():
    require_roles(*ALL_ROLES)
    records = list(store.demands.values())
    if is_dealer_principal():
        records = [d for d in records if d["dealer_id"] == g.user_id]
    for name in ("dealer_id", "contract_id", "status"):
        value = qfilter(name)
        if value is not None:
            records = [d for d in records if d.get(name) == value]
    records.sort(key=lambda d: (d.get("created_at") or "", d.get("_seq") or 0))
    return list_response(records)


@bp.route("/lending/buyback-demands/<demand_id>/actions", methods=["POST"])
def demand_action(demand_id):
    require_roles("PortfolioAdmin", "DealerPrincipal")
    body = get_body()
    action = body.get("action")
    if isinstance(action, str) and action in DEMAND_ACTIONS:
        if action in DEALER_DEMAND_ACTIONS and g.role != "DealerPrincipal":
            fail("ERR_FORBIDDEN_ROLE", "Action %s requires DealerPrincipal." % action)
        if action in ADMIN_DEMAND_ACTIONS and g.role != "PortfolioAdmin":
            fail("ERR_FORBIDDEN_ROLE", "Action %s requires PortfolioAdmin." % action)

    demand = get_demand(demand_id)
    scope_dealer_id(demand["dealer_id"])

    action = v_enum(body, "action", DEMAND_ACTIONS, required=True)
    dispute_reason = v_str(body, "dispute_reason", required=False, min_len=1, max_len=None, default=None)
    settlement_raw, settlement_date = (None, None)
    if action == "SETTLE":
        settlement_raw, settlement_date = v_dt(body, "settlement_date", required=True)

    contract = store.contracts.get(demand["contract_id"])

    if action == "ACKNOWLEDGE":
        if demand["status"] not in ("ISSUED", "DISPUTED"):
            fail("ERR_INVALID_STATE", "ACKNOWLEDGE is not permitted from %s." % demand["status"])
        demand["status"] = "ACKNOWLEDGED"
        bump(demand)
    elif action == "DISPUTE":
        if demand["status"] not in ("ISSUED", "ACKNOWLEDGED"):
            fail("ERR_INVALID_STATE", "DISPUTE is not permitted from %s." % demand["status"])
        demand["status"] = "DISPUTED"
        demand["dispute_reason"] = dispute_reason
        bump(demand)
    elif action == "WITHDRAW":
        if demand["status"] not in ("ISSUED", "ACKNOWLEDGED", "DISPUTED"):
            fail("ERR_INVALID_STATE", "WITHDRAW is not permitted from %s." % demand["status"])
        demand["status"] = "WITHDRAWN"
        bump(demand)
        if contract is not None and contract["reserve_status"] == "HELD":
            contract["reserve_status"] = "ACCRUED"
            bump(contract)
    else:  # SETTLE
        if demand["status"] != "ACKNOWLEDGED":
            fail("ERR_INVALID_STATE", "SETTLE is only permitted from ACKNOWLEDGED.")
        if contract is None or contract["funding_status"] != "FUNDED":
            fail("ERR_INVALID_STATE", "The contract is no longer FUNDED.")
        dealer = get_dealer(demand["dealer_id"])
        demand["status"] = "SETTLED"
        putdt(demand, "settled_at", settlement_raw, settlement_date)
        bump(demand)

        contract["funding_status"] = "REPURCHASED"
        contract["reserve_status"] = "CHARGED_BACK"
        S.post_entry(dealer, contract["id"], "BUYBACK_OFFSET",
                     -demand["reserve_offset_cents"], "BUYBACK_OFFSET")

        funded_at = dtv(contract, "funded_at")
        months = months_from_days(funded_at, clock.now()) if funded_at else 0
        if months < 0:
            months = 0
        contract["unpaid_principal_cents"] = S.straight_line_unpaid(contract, months)
        dealer["repurchase_count"] += 1
        S.recompute_reserve_balance(dealer)
        S.recompute_exposure(dealer)
        contract["unpaid_principal_cents"] = 0
        bump(contract)
        bump(dealer)

    return ok(serialize(demand))


# ---------------------------------------------------------------------------
# Fair lending reviews
# ---------------------------------------------------------------------------
@bp.route("/lending/fair-lending-reviews", methods=["POST"])
def create_review():
    require_roles("ComplianceOfficer")
    body = get_body()
    dealer_id = v_id(body, "dealer_id", required=True)
    start_raw, window_start = v_dt(body, "window_start", required=True)
    end_raw, window_end = v_dt(body, "window_end", required=True)
    if window_end <= window_start:
        fail("ERR_INVALID_REQUEST", "window_end must be strictly after window_start.")

    dealer = get_dealer(dealer_id)
    population = S.review_population(dealer_id, window_start, window_end)
    if len(population) < MIN_REVIEW_POPULATION:
        fail("ERR_INSUFFICIENT_REVIEW_POPULATION",
             "The review window holds fewer than %d funded contracts." % MIN_REVIEW_POPULATION)

    review = new_rec()
    review["dealer_id"] = dealer_id
    putdt(review, "window_start", start_raw, window_start)
    putdt(review, "window_end", end_raw, window_end)
    S.compute_review(review, population)
    review["status"] = "DRAFT"
    stamp(review, "published_at", None)
    stamp(review, "closed_at", None)
    store.reviews[review["id"]] = review
    return ok(serialize(review), 201)


@bp.route("/lending/fair-lending-reviews/<review_id>", methods=["GET"])
def read_review(review_id):
    require_roles(*ALL_ROLES)
    review = get_review(review_id)
    scope_dealer_id(review["dealer_id"])
    return ok(serialize(review))


@bp.route("/lending/fair-lending-reviews", methods=["GET"])
def list_reviews():
    require_roles(*ALL_ROLES)
    records = list(store.reviews.values())
    if is_dealer_principal():
        records = [r for r in records if r["dealer_id"] == g.user_id]
    for name in ("dealer_id", "status"):
        value = qfilter(name)
        if value is not None:
            records = [r for r in records if r.get(name) == value]
    records.sort(key=lambda r: (r.get("created_at") or "", r.get("_seq") or 0))
    return list_response(records)


@bp.route("/lending/fair-lending-reviews/<review_id>/transition", methods=["POST"])
def transition_review(review_id):
    require_roles("ComplianceOfficer")
    review = get_review(review_id)
    body = get_body()
    action = v_enum(body, "action", ("PUBLISH", "CLOSE"), required=True)
    dealer = store.dealers.get(review["dealer_id"])

    if action == "PUBLISH":
        if review["status"] != "DRAFT":
            fail("ERR_INVALID_STATE", "Only a DRAFT review may be published.")
        if review["finding"] == "WITHIN_TOLERANCE":
            review["status"] = "PUBLISHED"
            stamp(review, "published_at", clock.now())
            bump(review)
        else:
            pool = review["remediation_pool_cents"]
            if dealer is None or pool > dealer["reserve_balance_cents"]:
                fail("ERR_RESERVE_BALANCE_NEGATIVE",
                     "The remediation pool exceeds the dealership's reserve balance.")
            review["status"] = "REMEDIATION_ORDERED"
            stamp(review, "published_at", clock.now())
            bump(review)
            S.post_entry(dealer, None, "REMEDIATION", -pool, "REMEDIATION")
            dealer["compliance_hold"] = True
            S.recompute_reserve_balance(dealer)
            bump(dealer)
    else:
        if review["status"] not in ("PUBLISHED", "REMEDIATION_ORDERED"):
            fail("ERR_INVALID_STATE", "CLOSE is not permitted from %s." % review["status"])
        was_remediation = review["status"] == "REMEDIATION_ORDERED"
        review["status"] = "CLOSED"
        stamp(review, "closed_at", clock.now())
        bump(review)
        if was_remediation and dealer is not None:
            others = [r for r in S.dealer_reviews(dealer["id"])
                      if r["id"] != review["id"] and r["status"] == "REMEDIATION_ORDERED"]
            if not others:
                dealer["compliance_hold"] = False
            bump(dealer)

    return ok(serialize(review))
