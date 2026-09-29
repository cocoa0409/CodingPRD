"""Shared domain services: lookups, version discipline, ledger, cascades."""
from decimal import Decimal

from flask import g

import calc
import store as C
from errors import fail
from store import store
from util import add_days, add_hours, iso, latest, parse_dt, real_now_iso, sort_rows


# --- version / updated_at discipline (PRD 2.5, 2.9) --------------------------

def touch(row):
    """Bump version by exactly 1 and refresh updated_at, once per request."""
    seen = g.setdefault("_touched", set())
    if row["id"] in seen:
        return row
    seen.add(row["id"])
    row["version"] = int(row["version"]) + 1
    row["updated_at"] = real_now_iso()
    return row


# --- lookups (precedence checks 5-15) ---------------------------------------

def get_sale(sale_id):
    row = store.sales.get(sale_id)
    if row is None:
        fail("ERR_SALE_NOT_FOUND")
    return row


def get_case(case_id):
    row = store.cases.get(case_id)
    if row is None:
        fail("ERR_CASE_NOT_FOUND")
    return row


def get_round(case, round_id):
    row = store.rounds.get(round_id)
    if row is None or row["case_id"] != case["id"]:
        fail("ERR_ROUND_NOT_FOUND")
    return row


def get_seller(seller_id):
    row = store.sellers.get(seller_id)
    if row is None:
        fail("ERR_SELLER_NOT_FOUND")
    return row


def get_buyer(buyer_id):
    row = store.buyers.get(buyer_id)
    if row is None:
        fail("ERR_BUYER_NOT_FOUND")
    return row


def get_inspection(inspection_id):
    row = store.inspections.get(inspection_id)
    if row is None:
        fail("ERR_INSPECTION_NOT_FOUND")
    return row


def get_policy(policy_id):
    row = store.policies.get(policy_id)
    if row is None:
        fail("ERR_POLICY_NOT_FOUND")
    return row


def policy_for_defect_class(defect_class):
    for row in store.rows("policies"):
        if row["defect_class"] == defect_class:
            return row
    return None


def children(collection, field, value):
    return [r for r in store.rows(collection) if r[field] == value]


# --- settlement ledger (PRD 2.10) -------------------------------------------

def post_ledger(sale_id, case_id, party, entry_type, amount_signed_cents):
    row = {
        "sale_id": sale_id,
        "case_id": case_id,
        "party": party,
        "entry_type": entry_type,
        "amount_signed_cents": int(amount_signed_cents),
        "posted_at_utc": store.now_iso(),
    }
    return store.insert("ledger", row, mutable=False)


def post_transport_batches(sale_id, case_id, allocation):
    """One balanced TRANSPORT_ALLOCATION batch per leg, in leg created_at order."""
    for entry in allocation["per_leg"]:
        post_ledger(sale_id, case_id, "BUYER", "TRANSPORT_ALLOCATION", -entry["buyer"])
        post_ledger(sale_id, case_id, "SELLER", "TRANSPORT_ALLOCATION", -entry["seller"])
        post_ledger(sale_id, case_id, "AUCTION", "TRANSPORT_ALLOCATION",
                    entry["buyer"] + entry["seller"])


# --- post-sale inspections (PRD 3.3) ----------------------------------------

def governing_inspection(sale_id):
    """COMPLETED inspections on the sale, ranked completed_at_utc DESC, created_at DESC."""
    candidates = [r for r in store.inspections.values()
                  if r["sale_id"] == sale_id and r["status"] == "COMPLETED"]
    return latest(candidates, [lambda r: r["completed_at_utc"],
                              lambda r: r["created_at"],
                              lambda r: r["_seq"]])


# --- case derived readings from the evidence file (PRD 3.5) -----------------

def refresh_case_evidence_readings(case):
    rows = [r for r in store.evidence.values() if r["case_id"] == case["id"]]
    keys = [lambda r: r["recorded_at_utc"], lambda r: r["created_at"], lambda r: r["_seq"]]
    est_rows = [r for r in rows if r["verified"] and r["repair_estimate_cents"] is not None]
    best = latest(est_rows, keys)
    case["latest_verified_estimate_cents"] = int(best["repair_estimate_cents"]) if best else 0
    mileage_rows = [r for r in rows
                    if r["evidence_type"] == "THIRD_PARTY_VERIFICATION"
                    and r["verified"] and r["odometer_reading"] is not None]
    best_mileage = latest(mileage_rows, keys)
    case["verified_true_mileage"] = int(best_mileage["odometer_reading"]) if best_mileage else None


# --- open-claim counter conservation (PRD 2.9) ------------------------------

def sale_has_decision(sale_id):
    case_ids = {c["id"] for c in store.cases.values() if c["sale_id"] == sale_id}
    for decision in store.decisions.values():
        if decision["case_id"] in case_ids:
            return True
    return False


def open_claim_increment(sale, buyer, seller):
    sale["open_case_count"] = int(sale["open_case_count"]) + 1
    if sale["arbitration_status"] == "NONE":
        sale["arbitration_status"] = "ACTIVE"
    touch(sale)
    buyer["open_claim_count"] = int(buyer["open_claim_count"]) + 1
    buyer["lifetime_claim_count"] = int(buyer["lifetime_claim_count"]) + 1
    touch(buyer)
    seller["open_claim_count"] = int(seller["open_claim_count"]) + 1
    touch(seller)


def open_claim_release(sale, buyer, seller, resolved):
    """Release the counters a claim incremented.

    `resolved` is True for the decision / negotiated-accept paths (the sale's
    dispute dimension moves ACTIVE -> RESOLVED) and False for the compensating
    withdrawal / intake-expiry paths (ACTIVE -> NONE once nothing is open and no
    decision exists on the sale).
    """
    sale["open_case_count"] = max(0, int(sale["open_case_count"]) - 1)
    if resolved:
        sale["arbitration_status"] = "RESOLVED"
    elif sale["open_case_count"] == 0 and not sale_has_decision(sale["id"]):
        sale["arbitration_status"] = "NONE"
    touch(sale)
    buyer["open_claim_count"] = max(0, int(buyer["open_claim_count"]) - 1)
    touch(buyer)
    seller["open_claim_count"] = max(0, int(seller["open_claim_count"]) - 1)
    touch(seller)


# --- seller scorecard, tier movement and the settlement-hold cascade (PRD 3.9)

def seller_sales(seller_id):
    return [s for s in store.sales.values() if s["seller_id"] == seller_id]


def upheld_decisions_for_seller(seller_id):
    sale_ids = {s["id"] for s in seller_sales(seller_id)}
    rows = []
    for decision in store.decisions.values():
        if decision["outcome"] not in C.UPHELD_OUTCOMES:
            continue
        case = store.cases.get(decision["case_id"])
        if case is not None and case["sale_id"] in sale_ids:
            rows.append(decision)
    return rows


def compute_scorecard(seller):
    """Both variants of the arbitration rate against the current logical clock."""
    now = store.now()
    window_start = add_days(now, -C.SCORECARD_WINDOW_DAYS)
    sales = seller_sales(seller["id"])
    upheld = upheld_decisions_for_seller(seller["id"])

    rolling_sales = 0
    for sale in sales:
        hammer = parse_dt(sale["hammer_time_utc"])
        if hammer is not None and window_start < hammer <= now:
            rolling_sales += 1
    rolling_upheld = 0
    for decision in upheld:
        decided = parse_dt(decision["decided_at_utc"])
        if decided is not None and window_start < decided <= now:
            rolling_upheld += 1

    lifetime_sales = len(sales)
    lifetime_upheld = len(upheld)
    rolling_rate = calc.rate_bps(rolling_upheld, rolling_sales)
    lifetime_rate = calc.rate_bps(lifetime_upheld, lifetime_sales)
    return {
        "rolling_window_sales_count": rolling_sales,
        "rolling_window_upheld_count": rolling_upheld,
        "rolling_arbitration_rate_bps": rolling_rate,
        "lifetime_sales_count": lifetime_sales,
        "lifetime_upheld_count": lifetime_upheld,
        "lifetime_arbitration_rate_bps": lifetime_rate,
        "policy_tier": calc.tier_for(seller["policy_tier"], rolling_sales, rolling_rate),
    }


def append_policy_action(seller, case_id, action_type, from_tier, to_tier, rate_bps, note):
    row = {
        "seller_id": seller["id"],
        "triggered_by_case_id": case_id,
        "action_type": action_type,
        "from_tier": from_tier,
        "to_tier": to_tier,
        "rolling_rate_bps_at_action": int(rate_bps),
        "note": note,
        "effective_at_utc": store.now_iso(),
    }
    return store.insert("policy_actions", row, mutable=False)


def apply_settlement_hold_cascade(seller):
    """Every UNSETTLED, arbitration_status NONE sale of the seller goes on hold."""
    targets = [s for s in seller_sales(seller["id"])
               if s["settlement_status"] == "UNSETTLED" and s["arbitration_status"] == "NONE"]
    for sale in sort_rows(targets):
        sale["settlement_hold"] = True
        touch(sale)


def recompute_seller_standing(seller, triggered_by_case_id):
    """Refresh the stored scorecard and move the tier; append an action when it moves."""
    figures = compute_scorecard(seller)
    from_tier = seller["policy_tier"]
    to_tier = figures.pop("policy_tier")
    for key, value in figures.items():
        seller[key] = value
    rate = seller["rolling_arbitration_rate_bps"]
    if to_tier != from_tier:
        seller["policy_tier"] = to_tier
        if to_tier in C.TIER_TO_ACTION_TYPE:
            append_policy_action(
                seller, triggered_by_case_id, C.TIER_TO_ACTION_TYPE[to_tier],
                from_tier, to_tier, rate,
                "auto tier change at %d bps" % rate,
            )
        if to_tier == "BLOCKED":
            seller["blocked_at_utc"] = store.now_iso()
    touch(seller)
    if to_tier == "BLOCKED" and from_tier != "BLOCKED":
        apply_settlement_hold_cascade(seller)


# --- negotiation round helpers (PRD 3.6, 3.8, 3.9) --------------------------

def supersede_rounds(case, statuses):
    for row in sort_rows([r for r in store.rounds.values() if r["case_id"] == case["id"]]):
        if row["status"] in statuses:
            row["status"] = "SUPERSEDED"
            touch(row)


def active_cooldown_round(case):
    now = store.now()
    for row in sort_rows([r for r in store.rounds.values() if r["case_id"] == case["id"]]):
        if row["status"] != "COUNTERED" or row["cooldown_until_utc"] is None:
            continue
        cooldown = parse_dt(row["cooldown_until_utc"])
        if cooldown is not None and cooldown >= now:
            return row
    return None


def create_round(case, response_type, response_note, seller_offer_cents, status):
    now = store.now()
    row = {
        "case_id": case["id"],
        "round_index": int(case["current_round_index"]) + 1,
        "response_type": response_type,
        "seller_offer_cents": int(seller_offer_cents),
        "buyer_demand_cents": None,
        "response_note": response_note,
        "counter_note": None,
        "opened_at_utc": iso(now),
        "response_deadline_utc": iso(add_hours(now, C.ROUND_RESPONSE_HOURS)),
        "countered_at_utc": None,
        "cooldown_until_utc": None,
        "status": status,
    }
    store.insert("rounds", row, mutable=True)
    case["current_round_index"] = row["round_index"]
    return row


# --- decision engine (PRD 3.6 hop 2-5, 3.8) ---------------------------------

def case_legs(case):
    return sort_rows([r for r in store.legs.values() if r["case_id"] == case["id"]])


def _new_decision(case, outcome, fault_party, rationale, requested, variant,
                  allowance, computed, allocation, decided_by):
    row = {
        "case_id": case["id"],
        "outcome": outcome,
        "allowance_variant": variant,
        "computed_award_cents": int(computed),
        "requested_allowance_cents": requested,
        "allowance_cents": int(allowance),
        "fault_party": fault_party,
        "transport_total_cents": allocation["transport_total_cents"],
        "transport_buyer_share_cents": allocation["transport_buyer_share_cents"],
        "transport_seller_share_cents": allocation["transport_seller_share_cents"],
        "transport_auction_share_cents": allocation["transport_auction_share_cents"],
        "sale_price_refund_cents": 0,
        "fee_offset_applied_cents": 0,
        "frivolous_fee_cents": 0,
        "total_buyer_payout_cents": 0,
        "rationale": rationale,
        "decided_by_arbitrator_user_id": decided_by,
        "decided_at_utc": store.now_iso(),
    }
    return store.insert("decisions", row, mutable=False)


def resolve_negotiated_accept(case, sale, buyer, seller, policy, round_row):
    """Five-hop transitive cascade behind a buyer accepting a standing offer."""
    round_row["status"] = "ACCEPTED"
    touch(round_row)
    case["status"] = "RESOLVED_ALLOWANCE"
    case["fault_party"] = "SELLER"

    computed = calc.computed_award_cents(case, sale, policy)
    allowance = int(round_row["seller_offer_cents"])
    allocation = calc.allocate_transport(case_legs(case), "REPAIR_ALLOWANCE", "SELLER")
    decision = _new_decision(
        case, "REPAIR_ALLOWANCE", "SELLER",
        "buyer accepted the seller's repair allowance offer", None,
        "NEGOTIATED_ACCEPT", allowance, computed, allocation, None,
    )
    post_ledger(sale["id"], case["id"], "BUYER", "REPAIR_ALLOWANCE", allowance)
    post_ledger(sale["id"], case["id"], "SELLER", "REPAIR_ALLOWANCE", -allowance)
    post_transport_batches(sale["id"], case["id"], allocation)

    open_claim_release(sale, buyer, seller, resolved=True)
    touch(case)
    recompute_seller_standing(seller, case["id"])
    return decision


def _apply_unwind(case, sale, buyer, decision, allocation):
    """Pinned evaluation order for the buyer's unwind cash position (PRD 3.8)."""
    refund = int(sale["sale_price_cents"])
    decision["sale_price_refund_cents"] = refund
    prior_settlement = sale["settlement_status"]

    post_transport_batches(sale["id"], case["id"], allocation)
    sale["settlement_status"] = "REVERSED"
    if prior_settlement == "SETTLED":
        post_ledger(sale["id"], case["id"], "BUYER", "SALE_PROCEEDS_REVERSAL", refund)
        post_ledger(sale["id"], case["id"], "SELLER", "SALE_PROCEEDS_REVERSAL", -refund)

    offset = min(int(buyer["frivolous_fee_balance_cents"]), refund)
    decision["fee_offset_applied_cents"] = offset
    decision["total_buyer_payout_cents"] = (
        refund - allocation["transport_buyer_share_cents"] - offset)
    if offset > 0:
        buyer["frivolous_fee_balance_cents"] = int(buyer["frivolous_fee_balance_cents"]) - offset
        post_ledger(sale["id"], case["id"], "BUYER", "FRIVOLOUS_FEE_OFFSET", -offset)
        post_ledger(sale["id"], case["id"], "AUCTION", "FRIVOLOUS_FEE_OFFSET", offset)
    if (int(buyer["frivolous_fee_balance_cents"]) == 0
            and int(buyer["frivolous_claim_count"]) < C.FRIVOLOUS_SUSPENSION_COUNT
            and buyer["claim_privilege_status"] == "FEE_HOLD"):
        buyer["claim_privilege_status"] = "ACTIVE"
    touch(buyer)


def _apply_frivolous(case, sale, buyer, decision, allocation):
    """Four-hop cascade behind a FRIVOLOUS_DENIED decision (PRD 3.8)."""
    post_transport_batches(sale["id"], case["id"], allocation)
    prior_count = int(buyer["frivolous_claim_count"])
    fee = calc.frivolous_fee_cents(prior_count)
    assessment = {
        "case_id": case["id"],
        "buyer_id": buyer["id"],
        "prior_frivolous_count": prior_count,
        "fee_cents": fee,
        "reason": decision["rationale"],
        "assessed_at_utc": store.now_iso(),
    }
    store.insert("fees", assessment, mutable=False)
    decision["frivolous_fee_cents"] = fee
    post_ledger(sale["id"], case["id"], "BUYER", "FRIVOLOUS_FEE_ASSESSED", -fee)
    post_ledger(sale["id"], case["id"], "AUCTION", "FRIVOLOUS_FEE_ASSESSED", fee)

    new_count = prior_count + 1
    buyer["frivolous_claim_count"] = new_count
    buyer["frivolous_fee_balance_cents"] = int(buyer["frivolous_fee_balance_cents"]) + fee
    if new_count >= C.FRIVOLOUS_SUSPENSION_COUNT:
        buyer["claim_privilege_status"] = "SUSPENDED"
    elif int(buyer["frivolous_fee_balance_cents"]) > 0:
        buyer["claim_privilege_status"] = "FEE_HOLD"
    touch(buyer)
    if buyer["claim_privilege_status"] == "SUSPENDED":
        expire_buyer_inspections(buyer)
    return assessment


def expire_buyer_inspections(buyer):
    buyer_sale_ids = {s["id"] for s in store.sales.values() if s["buyer_id"] == buyer["id"]}
    targets = [i for i in store.inspections.values()
               if i["status"] == "REQUESTED" and i["sale_id"] in buyer_sale_ids]
    for inspection in sort_rows(targets):
        inspection["status"] = "EXPIRED"
        touch(inspection)


def render_decision(case, sale, buyer, seller, policy, outcome, fault_party, rationale,
                    requested, decided_by):
    """Create the decision row, run its outcome branch and close the case."""
    case["fault_party"] = fault_party
    legs = case_legs(case)
    allocation = calc.allocate_transport(legs, outcome, fault_party)

    variant = "NONE"
    allowance = 0
    computed = 0
    stored_requested = None
    if outcome == "REPAIR_ALLOWANCE":
        variant = "ARBITRATOR_AWARD"
        computed = calc.computed_award_cents(case, sale, policy)
        stored_requested = int(requested)
        allowance = min(stored_requested, computed)

    decision = _new_decision(case, outcome, fault_party, rationale, stored_requested,
                             variant, allowance, computed, allocation, decided_by)

    if outcome == "UNWIND":
        case["status"] = "UNWOUND"
        _apply_unwind(case, sale, buyer, decision, allocation)
    elif outcome == "REPAIR_ALLOWANCE":
        case["status"] = "RESOLVED_ALLOWANCE"
        post_ledger(sale["id"], case["id"], "BUYER", "REPAIR_ALLOWANCE", allowance)
        post_ledger(sale["id"], case["id"], "SELLER", "REPAIR_ALLOWANCE", -allowance)
        post_transport_batches(sale["id"], case["id"], allocation)
    elif outcome == "CLAIM_DENIED":
        case["status"] = "DENIED"
        post_transport_batches(sale["id"], case["id"], allocation)
    else:
        case["status"] = "DENIED"
        _apply_frivolous(case, sale, buyer, decision, allocation)

    open_claim_release(sale, buyer, seller, resolved=True)
    touch(case)
    if outcome in C.UPHELD_OUTCOMES:
        recompute_seller_standing(seller, case["id"])
    else:
        touch(seller)
    return decision


# --- the deadline sweep (PRD 3.9) -------------------------------------------

def run_sweep():
    """Four phases in a fixed order; rows processed in ascending created_at order."""
    now = store.now()
    report = {"inspections_expired": 0, "rounds_expired": 0,
              "seller_response_timeouts": 0, "cases_expired": 0}

    # phase 1 — outstanding inspections whose window_end_utc the clock has reached
    for inspection in store.rows("inspections"):
        if inspection["status"] != "REQUESTED":
            continue
        window_end = parse_dt(inspection["window_end_utc"])
        if window_end is not None and now >= window_end:
            inspection["status"] = "EXPIRED"
            touch(inspection)
            report["inspections_expired"] += 1

    # phase 2 — lapsed offers (strictly past the response deadline)
    for round_row in store.rows("rounds"):
        if round_row["status"] != "OPEN":
            continue
        deadline = parse_dt(round_row["response_deadline_utc"])
        if deadline is None or now <= deadline:
            continue
        round_row["status"] = "EXPIRED"
        touch(round_row)
        report["rounds_expired"] += 1
        case = store.cases.get(round_row["case_id"])
        if case is not None and case["status"] == "NEGOTIATION":
            case["status"] = "ARBITRATOR_REVIEW"
            case["fault_party"] = "BUYER"
            touch(case)

    # phase 3 — silent consignors
    for case in store.rows("cases"):
        if case["status"] != "UNDER_REVIEW":
            continue
        opened = parse_dt(case["review_opened_at_utc"])
        policy = store.policies.get(case["policy_id"])
        if opened is None or policy is None:
            continue
        hours = policy["seller_response_hours"]
        if hours is None:
            hours = C.DEFAULT_SELLER_RESPONSE_HOURS
        if now <= add_hours(opened, int(hours)):
            continue
        create_round(case, "TIMEOUT", "seller response timed out", 0, "CLOSED")
        case["status"] = "ARBITRATOR_REVIEW"
        case["seller_response_timed_out"] = True
        case["fault_party"] = "SELLER"
        touch(case)
        report["seller_response_timeouts"] += 1

    # phase 4 — abandoned intakes
    for case in store.rows("cases"):
        if case["status"] != "SUBMITTED":
            continue
        claimed = parse_dt(case["claimed_at_utc"])
        if claimed is None or now <= add_hours(claimed, C.INTAKE_GRACE_HOURS):
            continue
        case["status"] = "EXPIRED"
        sale = store.sales.get(case["sale_id"])
        buyer = store.buyers.get(case["claimant_buyer_id"])
        seller = store.sellers.get(sale["seller_id"]) if sale else None
        if sale is not None and buyer is not None and seller is not None:
            open_claim_release(sale, buyer, seller, resolved=False)
        touch(case)
        report["cases_expired"] += 1

    return report
