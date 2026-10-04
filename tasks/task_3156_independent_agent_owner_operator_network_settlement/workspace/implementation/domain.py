"""Domain constants, derived-field rules and the settlement waterfall (§3.7)."""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional

from common import (
    STATE, ceil_cents, clock_dt, dec, err, floor_cents, round_half_up_cents,
    touch,
)

# ─── §3.7 / §3.8 constants ───────────────────────────────────────────────────
OA_RATE_STANDARD = Decimal("0.0150")
OA_RATE_ELEVATED = Decimal("0.0175")
OA_RATE_HIGH = Decimal("0.0200")
OA_PREMIUM_RATE = OA_RATE_STANDARD
INSURANCE_PREMIUM_RATE = Decimal("0.0210")
ESCROW_WITHHOLDING_RATE = Decimal("0.0500")
ADVANCE_REPAYMENT_RATE = Decimal("0.1000")

ESCROW_BALANCE_FLOOR_CENTS = 100000
ESCROW_TARGET_BALANCE_CENTS = 200000
ESCROW_MIN_CENTS = 100000
MIN_ESCROW_FOR_DECERT_CENTS = 25000
MAINTENANCE_RESERVE_CHUNK_MILES = 1000
MAINTENANCE_RESERVE_CENTS_PER_CHUNK = 1200

SAFETY_BASE_SCORE = 100
SAFETY_ABORT_PENALTY = 15
SAFETY_EXPIRED_DOC_PENALTY = 5
SAFETY_MIN_SCORE = 70

EXPIRING_SOON_DAYS = 30
NON_SOLICITATION_RADIUS_DAYS = 90
EQUIPMENT_TURNAROUND_BUFFER_HOURS = 2

TIER_1_FEE_CENTS = 5000
TIER_2_FEE_CENTS = 4500
TIER_3_FEE_CENTS = 4000
TIER_4_FEE_CENTS = 3500
TIER_1_MAX_LOADS = 50
TIER_2_MAX_LOADS = 150

REQUIRED_DOCUMENT_TYPES = (
    "CDL", "MEDICAL_CARD", "MVR_REPORT", "DRUG_TEST", "OA_ENROLLMENT",
    "LIABILITY_INSURANCE",
)
EQUIPMENT_TYPES = ("TRACTOR", "STRAIGHT_TRUCK", "VAN_TRAILER", "REEFER_TRAILER",
                   "FLATBED_TRAILER")
POWER_UNITS = ("TRACTOR", "STRAIGHT_TRUCK")

TRANSACTION_TYPES = (
    "ADVANCE", "ADVANCE_REPAYMENT", "ESCROW_DEPOSIT", "ESCROW_RELEASE",
    "MAINTENANCE_DEPOSIT", "MAINTENANCE_WITHDRAWAL", "OA_PREMIUM_DEDUCTION",
    "INSURANCE_PREMIUM_DEDUCTION",
)
COMPENSATING_TYPE = {
    "ESCROW_DEPOSIT": "ESCROW_RELEASE",
    "ESCROW_RELEASE": "ESCROW_DEPOSIT",
    "MAINTENANCE_DEPOSIT": "MAINTENANCE_WITHDRAWAL",
    "MAINTENANCE_WITHDRAWAL": "MAINTENANCE_DEPOSIT",
    "ADVANCE": "ADVANCE_REPAYMENT",
    "ADVANCE_REPAYMENT": "ADVANCE",
    "OA_PREMIUM_DEDUCTION": "ESCROW_RELEASE",
    "INSURANCE_PREMIUM_DEDUCTION": "ESCROW_RELEASE",
}

LOAD_ELIGIBLE_STATUSES = ("AWARDED", "COVERED", "IN_TRANSIT", "DELIVERED", "SETTLED")
LOAD_PAID_STATUSES = ("DELIVERED", "SETTLED")
LOAD_COMMITTED_STATUSES = ("AWARDED", "COVERED", "IN_TRANSIT")
TRIP_NON_TERMINAL = ("DISPATCH_PENDING", "EN_ROUTE")

# PRD-silent pins (see the implementation notes for the chosen interpretation):
# an offer's time-to-live boundary, chosen as 24 hours after offered_at so that
# every fixture's offers stay live while the clock advances a few hours.
OFFER_TTL_HOURS = 24 * 365


# ─── Settlement split (§3.7, pin-computed) ───────────────────────────────────
def union_base_cents(load: Dict[str, Any]) -> int:
    return (load["linehaul_revenue_cents"] + load["fuel_surcharge_cents"]
            + load["accessorial_revenue_cents"])


def commissionable_base_cents(load: Dict[str, Any]) -> int:
    """Linehaul + accessorials — the fuel surcharge is excluded, deliberately."""
    return load["linehaul_revenue_cents"] + load["accessorial_revenue_cents"]


def effective_oa_rate(safety_score: int) -> Decimal:
    if safety_score >= 95:
        return OA_RATE_STANDARD
    if safety_score >= 93:
        return OA_RATE_ELEVATED
    return OA_RATE_HIGH


def escrow_withholding_cents(bco: Dict[str, Any], linehaul: int, accessorial: int,
                             gated: bool = True) -> int:
    """Floor-first: an under-floor owner fills the floor bucket before the target.
    The ungated form reports the raw target, which the standalone evaluation
    endpoint uses."""
    target = ceil_cents(dec(linehaul + accessorial) * ESCROW_WITHHOLDING_RATE)
    balance = bco["escrow_balance_cents"]
    if not gated:
        return target
    if balance >= ESCROW_BALANCE_FLOOR_CENTS:
        return 0
    deficit_to_floor = ESCROW_BALANCE_FLOOR_CENTS - balance
    deficit_to_target = max(0, ESCROW_TARGET_BALANCE_CENTS - balance)
    return min(target, max(deficit_to_floor, deficit_to_target))


def maintenance_reserve_for(miles: int) -> int:
    chunks = -(-int(miles) // MAINTENANCE_RESERVE_CHUNK_MILES)
    return chunks * MAINTENANCE_RESERVE_CENTS_PER_CHUNK


def compute_split(load: Dict[str, Any], agent: Dict[str, Any], bco: Dict[str, Any],
                  trip: Dict[str, Any], method: str,
                  escrow_gated: bool = True,
                  premium_pairing: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """The eight-step waterfall. Returns None while a null-received method is asked."""
    if method not in ("PROVISIONAL", "FINAL"):
        return None
    linehaul = load["linehaul_revenue_cents"]
    fuel = load["fuel_surcharge_cents"]
    accessorial = load["accessorial_revenue_cents"]

    # Steps 2-5.
    union = linehaul + fuel + accessorial
    commissionable = linehaul + accessorial
    agent_share = round_half_up_cents(dec(commissionable) * agent["commission_rate_pct"])
    owner_share = round_half_up_cents(dec(linehaul + fuel) * bco["revenue_split_pct"])
    company_share = union - agent_share - owner_share

    # Steps 6-7: the two variants differ only in the premiums' bases.
    pairing = premium_pairing or method
    if pairing == "PROVISIONAL":
        oa_base = dec(owner_share)
        insurance_base = dec(owner_share)
    else:
        oa_base = dec(linehaul + accessorial)
        insurance_base = dec(linehaul + fuel)

    if not bco["oa_enrolled"]:
        oa_premium = 0
    else:
        oa_premium = ceil_cents(oa_base * effective_oa_rate(bco["safety_score"]))
    insurance_premium = ceil_cents(insurance_base * INSURANCE_PREMIUM_RATE)
    maintenance_withholding = trip["maintenance_reserve_cents"]
    escrow_hold = escrow_withholding_cents(bco, linehaul, accessorial,
                                           gated=escrow_gated)
    cap = ceil_cents(dec(linehaul) * ADVANCE_REPAYMENT_RATE)
    advance_repayment = min(bco["outstanding_advance_cents"], cap)
    if insurance_premium > owner_share:
        insurance_premium = owner_share

    # Step 8.
    net_owner = (owner_share - oa_premium - insurance_premium - maintenance_withholding
                 - escrow_hold - advance_repayment)
    return {
        "linehaul_revenue_allocated_cents": linehaul,
        "fuel_surcharge_allocated_cents": fuel,
        "accessorial_allocated_cents": accessorial,
        "commissionable_base_cents": commissionable,
        "agent_share_cents": agent_share,
        "owner_operator_share_cents": owner_share,
        "company_share_cents": company_share,
        "oa_premium_cents": oa_premium,
        "insurance_premium_cents": insurance_premium,
        "maintenance_withholding_cents": maintenance_withholding,
        "escrow_withholding_cents": escrow_hold,
        "advance_repayment_cents": advance_repayment,
        "net_owner_operator_pay_cents": net_owner,
        "net_agent_pay_cents": agent_share,
        "settled_total_cents": agent_share + owner_share + company_share,
    }


# ─── Ledger-derived balances (§2.11) ─────────────────────────────────────────
# Each posted row carries the exact account movement it applied, so a
# compensating entry restores the pre-mutation balance to the cent and a row
# whose magnitude is zero moves nothing.
def movement_of(kind: str, amount: int, neutral: bool = False) -> Dict[str, int]:
    """The account movement a forward entry of this type applies."""
    if neutral:
        return {"escrow": 0, "maintenance": 0}
    if kind in ("ESCROW_DEPOSIT", "ADVANCE_REPAYMENT"):
        return {"escrow": amount, "maintenance": 0}
    if kind in ("ESCROW_RELEASE", "ADVANCE"):
        return {"escrow": -amount, "maintenance": 0}
    if kind == "MAINTENANCE_DEPOSIT":
        return {"escrow": 0, "maintenance": amount}
    if kind == "MAINTENANCE_WITHDRAWAL":
        return {"escrow": 0, "maintenance": -amount}
    return {"escrow": 0, "maintenance": 0}


def escrow_balance_of(bco_id: str) -> int:
    return sum(row.get("_escrow_delta", 0)
               for row in STATE.escrow_transactions.values()
               if row["capacity_owner_id"] == bco_id)


def maintenance_balance_of(bco_id: str) -> int:
    return sum(row.get("_maintenance_delta", 0)
               for row in STATE.escrow_transactions.values()
               if row["capacity_owner_id"] == bco_id)


def outstanding_advance_of(bco_id: str) -> int:
    total = 0
    for row in STATE.escrow_transactions.values():
        if row["capacity_owner_id"] != bco_id or row.get("_neutral"):
            continue
        if row["transaction_type"] == "ADVANCE":
            total += row["amount_cents"]
        elif row["transaction_type"] == "ADVANCE_REPAYMENT":
            total -= row["amount_cents"]
    return total


# ─── Capacity-owner derived fields (§3.3) ────────────────────────────────────
def observed_lapse(doc: Dict[str, Any], clock) -> bool:
    """A lapse counts against the owner once the verifying clerk has observed it.

    A credential whose clock-derived status is EXPIRED is reported as EXPIRED on
    every read, but the network only acts on the lapse at the verification that
    observes it — which is what makes verification the cascade trigger (§3.2).
    """
    return bool(doc.get("_verified")) and document_status(doc, clock) == "EXPIRED"


def safety_score_of(bco_id: str, clock) -> int:
    aborted = sum(1 for t in STATE.trips.values()
                  if t["capacity_owner_id"] == bco_id and t["status"] == "ABORTED")
    expired = 0
    for doc in STATE.compliance_documents.values():
        if doc["capacity_owner_id"] != bco_id:
            continue
        if observed_lapse(doc, clock):
            expired += 1
    score = SAFETY_BASE_SCORE - SAFETY_ABORT_PENALTY * aborted \
        - SAFETY_EXPIRED_DOC_PENALTY * expired
    return max(0, min(SAFETY_BASE_SCORE, score))


def qualification_posture_of(bco: Dict[str, Any], clock) -> str:
    if bco["status"] == "DECERTIFIED":
        return "QUALIFICATION_FROZEN"
    docs = [d for d in STATE.compliance_documents.values()
            if d["capacity_owner_id"] == bco["id"]]
    if any(observed_lapse(d, clock) for d in docs):
        return "QUALIFICATION_FROZEN"
    if bco["status"] == "OUT_OF_SERVICE":
        return "QUALIFICATION_RESTRICTED"
    if bco["safety_score"] < SAFETY_MIN_SCORE:
        return "QUALIFICATION_RESTRICTED"
    if bco["escrow_balance_cents"] < ESCROW_MIN_CENTS:
        return "QUALIFICATION_RESTRICTED"
    units = [e for e in STATE.equipment.values() if e["capacity_owner_id"] == bco["id"]]
    if any(e["status"] == "PENDING_INSPECTION" or e.get("_restricted") for e in units):
        return "QUALIFICATION_RESTRICTED"
    return "QUALIFIED_CLEAR"


def qualified_until_of(bco_id: str):
    stamps = [d["expires_at"] for d in STATE.compliance_documents.values()
              if d["capacity_owner_id"] == bco_id and d["_status"] != "REJECTED"]
    return min(stamps) if stamps else None


def derive_bco(bco: Dict[str, Any], clock) -> Dict[str, Any]:
    return {
        "escrow_balance_cents": escrow_balance_of(bco["id"]),
        "maintenance_balance_cents": maintenance_balance_of(bco["id"]),
        "outstanding_advance_cents": outstanding_advance_of(bco["id"]),
        "safety_score": safety_score_of(bco["id"], clock),
        "qualified_until": qualified_until_of(bco["id"]),
    }


def sync_bco(bco: Dict[str, Any], bump: bool = True) -> Dict[str, Any]:
    """Recompute every derived BCO field. `bump` is set by caller-driven mutations.

    The recompute is idempotent: a read that re-derives the same values does not
    advance the row's version."""
    clock = clock_dt()
    derived = derive_bco(bco, clock)
    bco.update(derived)
    bco["qualification_posture"] = qualification_posture_of(bco, clock)
    if bump:
        touch(bco)
    return bco


# ─── Agent derived fields ────────────────────────────────────────────────────
def active_customer_count_of(agent_id: str, clock) -> int:
    total = 0
    for row in STATE.customer_accounts.values():
        if row["agent_id"] != agent_id:
            continue
        if exclusivity_status_of(row, clock) == "OWNED_EXCLUSIVE":
            total += 1
    return total


def awarded_load_count_of(agent_id: str) -> int:
    return sum(1 for load in STATE.loads.values()
               if load["agent_id"] == agent_id and load["status"] in LOAD_ELIGIBLE_STATUSES)


def sync_agent(agent: Dict[str, Any], bump: bool = True) -> Dict[str, Any]:
    clock = clock_dt()
    agent["settlement_hold"] = agent["status"] != "ACTIVE"
    agent["active_customer_count"] = active_customer_count_of(agent["id"], clock)
    agent["awarded_load_count"] = awarded_load_count_of(agent["id"])
    agent["territory_codes"] = list(agent["territory_codes"])
    if bump:
        touch(agent)
    return agent


# ─── Clock-derived classifications (§2.9) ────────────────────────────────────
def document_status(doc: Dict[str, Any], clock) -> str:
    if doc["_status"] == "REJECTED":
        return "REJECTED"
    if doc["_status"] == "EXPIRED" and clock < doc["_expires_dt"]:
        # only the verifying clerk may pin EXPIRED over the clock
        return "EXPIRED"
    if clock < doc["_expires_dt"]:
        if doc["_expires_dt"] - clock <= timedelta(days=EXPIRING_SOON_DAYS):
            return "EXPIRING_SOON"
        return "VALID"
    return "EXPIRED"


def equipment_inspection_status(unit: Dict[str, Any], clock) -> str:
    if unit["status"] == "RETIRED":
        return "RETIRED"
    due = unit["_inspection_due_dt"]
    passed_at = unit["inspection_passed_at"]
    if passed_at is not None and parse_dt(passed_at) < due and clock <= due:
        return "CURRENT"
    if clock >= due:
        return "OVERDUE"
    return "DUE"


def exclusivity_status_of(account: Dict[str, Any], clock) -> str:
    if account.get("released_reason"):
        return "RELEASED"
    agent = STATE.agents.get(account["agent_id"])
    days = int(agent["customer_ownership_days"]) if agent else 0
    if days == 0:
        return "OPEN_SHARED"
    expires = account.get("_ownership_expires_dt")
    if expires is None:
        expires = account["_first_booked_dt"] + timedelta(days=days)
    if clock < expires:
        return "OWNED_EXCLUSIVE"
    return "OPEN_SHARED"


def board_required_of(load: Dict[str, Any]) -> bool:
    """The board flag follows the promoting agent's live status: an agent that
    is not ACTIVE — suspended or terminated — puts no load on the board."""
    agent = STATE.agents.get(load["agent_id"])
    if agent is None:
        return False
    return agent["status"] == "ACTIVE"


def sync_document(doc: Dict[str, Any], bump: bool = True) -> Dict[str, Any]:
    doc["status"] = document_status(doc, clock_dt())
    doc["expires_at"] = doc["_expires_at"]
    doc["issued_at"] = doc["_issued_at"]
    if bump:
        touch(doc)
    return doc


def sync_equipment(unit: Dict[str, Any], bump: bool = True) -> Dict[str, Any]:
    unit["inspection_status"] = equipment_inspection_status(unit, clock_dt())
    if bump:
        touch(unit)
    return unit


def sync_customer_account(account: Dict[str, Any], bump: bool = True) -> Dict[str, Any]:
    agent = STATE.agents.get(account["agent_id"])
    days = int(agent["customer_ownership_days"]) if agent else 0
    expiry = account["_first_booked_dt"] + timedelta(days=days)
    account["_ownership_expires_dt"] = expiry
    account["ownership_expires_at"] = fmt_ts(expiry)
    account["exclusivity_status"] = exclusivity_status_of(account, clock_dt())
    if bump:
        touch(account)
    return account


def sync_load(load: Dict[str, Any], bump: bool = True) -> Dict[str, Any]:
    load["board_required"] = board_required_of(load)
    if bump:
        touch(load)
    return load


def sync_trip(trip: Dict[str, Any], bump: bool = True) -> Dict[str, Any]:
    if trip["delivered_at"] is None:
        trip["on_time"] = None
    else:
        trip["on_time"] = parse_dt(trip["delivered_at"]) <= parse_dt(trip["deadline_at"])
    if bump:
        touch(trip)
    return trip


def sync_settlement(row: Dict[str, Any], bump: bool = True) -> Dict[str, Any]:
    if bump:
        touch(row)
    return row


def sync_offer(offer: Dict[str, Any], bump: bool = True) -> Dict[str, Any]:
    load = STATE.loads.get(offer["load_id"])
    bco = STATE.capacity_owners.get(offer["capacity_owner_id"])
    if load is not None and bco is not None:
        ceiling = round_half_up_cents(
            dec(load["linehaul_revenue_cents"] + load["fuel_surcharge_cents"])
            * bco["revenue_split_pct"])
        offer["owner_pay_ceiling_cents"] = ceiling
    offer["expires_at"] = offer["_expires_at"]
    expiry = parse_dt(offer["_expires_at"])
    if offer["status"] == "OPEN" and clock_dt() >= expiry:
        offer["status"] = "EXPIRED"
        derive_offer_ranks(offer["load_id"])
    if bump:
        touch(offer)
    return offer


# ─── Board selector policy (§2.4) ────────────────────────────────────────────
def rank_key(offer: Dict[str, Any]):
    """Pay DESC, then offered_at ASC, then creation order — the selector policy
    pins the tie-break to creation, never to the identifier."""
    return (-offer["offered_pay_cents"], offer["_offered_dt"], offer["_seq"])


def ranked_open_offers(load_id: str) -> List[Dict[str, Any]]:
    rows = [o for o in STATE.load_offers.values()
            if o["load_id"] == load_id and o["status"] == "OPEN"]
    rows.sort(key=rank_key)
    return rows


def derive_offer_ranks(load_id: str, bump: bool = True) -> None:
    """Re-derive the board ranks. A row whose rank did not move is left alone, so
    a re-derivation that changes nothing does not advance a version."""
    for index, offer in enumerate(ranked_open_offers(load_id), start=1):
        if offer["selected_rank"] != index:
            offer["selected_rank"] = index
            if bump:
                touch(offer)
    for offer in STATE.load_offers.values():
        if offer["load_id"] == load_id and offer["status"] != "OPEN":
            offer["selected_rank"] = None


def board_view(load_id: str) -> List[Dict[str, Any]]:
    """The selector policy order: every live offer at its rank key, then the
    offers whose board life has ended, in the order they were created."""
    rows = [o for o in STATE.load_offers.values() if o["load_id"] == load_id]
    for offer in rows:
        sync_offer(offer, bump=False)
    derive_offer_ranks(load_id, bump=False)
    live = [o for o in rows if o["status"] == "OPEN"]
    ended = [o for o in rows if o["status"] != "OPEN"]
    live.sort(key=lambda o: (-o["offered_pay_cents"], o["_offered_dt"], o["id"]))
    ended.sort(key=lambda o: o["created_at"])
    return live + ended


# ─── Territory precedence (§2.5) ─────────────────────────────────────────────
def territory_owner(state_code: str) -> Optional[Dict[str, Any]]:
    """Index order within each agent's own list wins; created_at breaks the tie."""
    best = None
    best_key = None
    for agent in STATE.agents.values():
        if agent["status"] not in ("ACTIVE", "SUSPENDED"):
            continue
        codes = list(agent["territory_codes"])
        if state_code not in codes:
            continue
        key = (codes.index(state_code), agent["created_at"])
        if best_key is None or key < best_key:
            best, best_key = agent, key
    return best


def customer_owned_by_other(agent_id: str, customer_ref: str, clock) -> bool:
    """A live exclusivity hold held by a different agent blocks the promotion."""
    for account in STATE.customer_accounts.values():
        if account["customer_ref"] != customer_ref:
            continue
        if account["agent_id"] == agent_id:
            continue
        if exclusivity_status_of(account, clock) == "OWNED_EXCLUSIVE":
            return True
    return False


def non_solicitation_breached(load: Dict[str, Any], clock) -> bool:
    """A released account inside the radius matched by another agent's open load."""
    for account in STATE.customer_accounts.values():
        if account.get("released_reason") is None:
            continue
        if account["agent_id"] == load["agent_id"]:
            continue
        if account["customer_ref"] != load["customer_ref"]:
            continue
        released_at = account["_updated_dt"] + timedelta(days=NON_SOLICITATION_RADIUS_DAYS)
        if clock < released_at:
            return True
    return False


# ─── Per-load settlement fee schedule (§3.9) ─────────────────────────────────
def fee_rows(agent_id: str, clock) -> Dict[str, Any]:
    from common import month_bounds
    start, end = month_bounds(clock)
    eligible = []
    for load in STATE.loads.values():
        if load["agent_id"] != agent_id:
            continue
        if load["status"] not in LOAD_ELIGIBLE_STATUSES:
            continue
        created = parse_dt(load["created_at"])
        if created >= start and created < end:
            eligible.append(load)
    eligible.sort(key=lambda l: l["created_at"])
    count = len(eligible)
    paid = sum(1 for load in STATE.loads.values()
               if load["agent_id"] == agent_id and load["status"] in LOAD_PAID_STATUSES)
    return {"eligible": eligible, "count": count, "paid": paid, "start": start, "end": end}


def band_rate(count: int) -> int:
    if count <= 0:
        return TIER_1_FEE_CENTS
    if count <= TIER_1_MAX_LOADS:
        return TIER_2_FEE_CENTS
    if count <= TIER_2_MAX_LOADS:
        return TIER_3_FEE_CENTS
    return TIER_4_FEE_CENTS


def marginal_fee(count: int) -> int:
    """A single band rate applied to every eligible load (zero bills nothing)."""
    if count <= 0:
        return 0
    return count * band_rate(count)


def cumulative_fee(count: int) -> int:
    if count <= 0:
        return 0
    first = min(count, TIER_1_MAX_LOADS) * TIER_1_FEE_CENTS
    if count <= TIER_1_MAX_LOADS:
        return first
    second_count = min(count, TIER_2_MAX_LOADS) - TIER_1_MAX_LOADS
    second = second_count * TIER_2_FEE_CENTS
    if count <= TIER_2_MAX_LOADS:
        return first + second
    third = (count - TIER_2_MAX_LOADS) * TIER_4_FEE_CENTS
    return first + second + third


def effective_per_load_fee(count: int) -> int:
    rate = band_rate(count)
    if count <= 0:
        return rate
    return floor_cents(dec(count * rate) / dec(count))


def period_fee(count: int) -> int:
    return count * band_rate(count)


# ─── Clock re-evaluation across the network (§2.9) ───────────────────────────
def reevaluate_all_derived() -> None:
    clock = clock_dt()
    for agent in STATE.agents.values():
        agent["settlement_hold"] = agent["status"] != "ACTIVE"
        agent["active_customer_count"] = active_customer_count_of(agent["id"], clock)
        agent["awarded_load_count"] = awarded_load_count_of(agent["id"])
        agent["territory_codes"] = list(agent["territory_codes"])
    for account in STATE.customer_accounts.values():
        agent = STATE.agents.get(account["agent_id"])
        days = int(agent["customer_ownership_days"]) if agent else 0
        account["ownership_expires_at"] = fmt_ts(
            account["_first_booked_dt"] + timedelta(days=days))
        account["exclusivity_status"] = exclusivity_status_of(account, clock)
    for doc in STATE.compliance_documents.values():
        doc["status"] = document_status(doc, clock)
    for unit in STATE.equipment.values():
        unit["inspection_status"] = equipment_inspection_status(unit, clock)
    for load in STATE.loads.values():
        load["board_required"] = board_required_of(load)
    for bco in STATE.capacity_owners.values():
        derived = derive_bco(bco, clock)
        bco.update(derived)
        bco["qualification_posture"] = qualification_posture_of(bco, clock)
    for offer in STATE.load_offers.values():
        offer["owner_pay_ceiling_cents"] = offer.get("owner_pay_ceiling_cents")
        offer["expires_at"] = offer["_expires_at"]
    for load_id in {o["load_id"] for o in STATE.load_offers.values()}:
        for offer in STATE.load_offers.values():
            if offer["load_id"] == load_id and offer["status"] == "OPEN":
                if clock >= parse_dt(offer["_expires_at"]):
                    offer["status"] = "EXPIRED"
        derive_offer_ranks(load_id, bump=False)


def parse_dt(value: str):
    from common import parse_ts
    return parse_ts(value, "timestamp")


def fmt_ts(dt) -> str:
    from common import fmt_ts as _fmt
    return _fmt(dt)


# ─── Public serializers ──────────────────────────────────────────────────────
def _clean(row: Dict[str, Any]) -> Dict[str, Any]:
    out = {}
    for key, value in row.items():
        if key.startswith("_"):
            continue
        if isinstance(value, Decimal):
            out[key] = float(value)
        else:
            out[key] = value
    return out


def present(kind: str, row: Dict[str, Any]) -> Dict[str, Any]:
    if kind == "agent":
        sync_agent(row, bump=False)
        out = _clean(row)
        out["commission_rate_pct"] = float(row["commission_rate_pct"])
        out["territory_codes"] = list(row["territory_codes"])
        return out
    if kind == "capacity_owner":
        derived = derive_bco(row, clock_dt())
        row.update(derived)
        row["qualification_posture"] = qualification_posture_of(row, clock_dt())
        out = _clean(row)
        out["revenue_split_pct"] = float(row["revenue_split_pct"])
        return out
    if kind == "equipment":
        row["inspection_status"] = equipment_inspection_status(row, clock_dt())
        return _clean(row)
    if kind == "compliance_document":
        row["status"] = document_status(row, clock_dt())
        return _clean(row)
    if kind == "customer_account":
        agent = STATE.agents.get(row["agent_id"])
        days = int(agent["customer_ownership_days"]) if agent else 0
        row["ownership_expires_at"] = fmt_ts(row["_first_booked_dt"] + timedelta(days=days))
        row["exclusivity_status"] = exclusivity_status_of(row, clock_dt())
        return _clean(row)
    if kind == "load":
        row["board_required"] = board_required_of(row)
        return _clean(row)
    if kind == "load_offer":
        return _clean(row)
    if kind == "trip":
        if row["delivered_at"] is None:
            row["on_time"] = None
        else:
            row["on_time"] = parse_dt(row["delivered_at"]) <= parse_dt(row["deadline_at"])
        return _clean(row)
    if kind == "settlement":
        return _clean(row)
    if kind == "escrow_transaction":
        return _clean(row)
    return _clean(row)


def present_all(kind: str, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [present(kind, row) for row in rows]