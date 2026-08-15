"""Business logic: serializers, fee ledger, cascades, draw, payouts, settlement.

All state-machine cascades and calculation rules trace to PRD section 3 and the
scaffold state_machines / calculations tables. Money is integer cents with
round-half-up applied per entry at charge time (never on aggregates).
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from db import DB, CLOCK, new_id, next_seq, now_iso
from errors import ApiError
from util import parse_dt, round_half_up_cents

# ---- pinned constants (scaffold calculations) ----
SANCTION_FLAT_CENTS = 600
RETENTION_PCT = Decimal("0.12")
AVERAGE_SHARE_PCT = Decimal("0.30")
MAX_OUTS_PER_RODEO = 3
PAYOUT_PCTS = {1: [100], 2: [60, 40], 3: [50, 30, 20], 4: [40, 30, 20, 10]}

ROUGH_STOCK_CODES = {"BAREBACK", "SADDLE_BRONC", "BULL_RIDING"}
EVENT_CODES = ROUGH_STOCK_CODES | {
    "TIE_DOWN_ROPING",
    "STEER_WRESTLING",
    "TEAM_ROPING",
    "BARREL_RACING",
}
RODEO_POSTURES = [
    "DRAFT",
    "ENTRIES_OPEN",
    "DRAW_LOCKED",
    "IN_PROGRESS",
    "COMPLETED",
    "SETTLED",
    "CANCELLED",
]
ENTRY_NONTERMINAL_DUP = {"ENTERED", "WAITLISTED", "DRAWN"}
ENTRY_TERMINAL = {"CANCELLED", "DRAWN_OUT", "COMPETED"}

_FAR = datetime.max.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# stamps / serialization
# ---------------------------------------------------------------------------

def stamp(rec):
    ts = now_iso()
    rec["created_at"] = ts
    rec["updated_at"] = ts
    rec["version"] = 1
    rec["_seq"] = next_seq()
    return rec


def stamp_immutable(rec):
    """VetReport: id + created_at only (no updated_at / version, PRD 2.5)."""
    rec["created_at"] = now_iso()
    rec["_seq"] = next_seq()
    return rec


def touch(rec):
    """Every mutation refreshes updated_at and increments version (PRD 2.5/2.7)."""
    rec["updated_at"] = now_iso()
    rec["version"] += 1
    return rec


def ser(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def sorted_created(recs):
    return sorted(recs, key=lambda r: r["_seq"])


def get_or_404(collection, rid):
    rec = DB[collection].get(rid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Referenced resource does not exist")
    return rec


def fk_or_404(collection, value, field):
    """Body foreign-key existence: absent -> ERR_VALIDATION, unknown -> 404."""
    if value is None:
        raise ApiError("ERR_VALIDATION", 400, f"Missing required field: {field}")
    return get_or_404(collection, value)


def clock_before(iso_dt):
    return CLOCK["dt"] < iso_dt


# ---------------------------------------------------------------------------
# fee ledger (PRD 3.2 / calculation entry_fee_split)
# ---------------------------------------------------------------------------

def fee_split(fee_cents):
    """Per-entry split, round-half-up per entry at charge time (PRD 2.6)."""
    sanction = SANCTION_FLAT_CENTS
    retention = round_half_up_cents(Decimal(fee_cents) * RETENTION_PCT)
    contribution = fee_cents - retention - sanction
    return sanction, retention, contribution


def charge_entry(entry, fee_cents):
    """Apply a fresh charge: latest split fields + cumulative charge totals."""
    sanction, retention, contribution = fee_split(fee_cents)
    entry["entry_fee_cents"] = fee_cents
    entry["sanction_fee_cents"] = sanction
    entry["committee_retention_cents"] = retention
    entry["purse_contribution_cents"] = contribution
    entry["fee_charges_cents"] += fee_cents
    entry["contribution_charges_cents"] += contribution


def refund_contribution_and_retention(entry):
    """CANCEL_ENTRY: contribution + retention returned, sanction kept."""
    entry["refunded_cents"] += (
        entry["purse_contribution_cents"] + entry["committee_retention_cents"]
    )
    entry["refunded_contribution_cents"] += entry["purse_contribution_cents"]


def refund_contribution_only(entry):
    """MEDICAL turn-out: only the purse contribution is returned."""
    entry["refunded_cents"] += entry["purse_contribution_cents"]
    entry["refunded_contribution_cents"] += entry["purse_contribution_cents"]


def refund_full(entry):
    """Full refund incl. sanction (DRAW_OUT / suspension / rodeo cancel).

    Operates on the latest charge: a live (ENTERED/WAITLISTED/DRAWN) entry has
    none of its latest charge refunded yet; a TURNED_OUT entry refunded its
    contribution already when the turn-out was MEDICAL.
    """
    if entry["status"] == "TURNED_OUT" and entry["turn_out_reason"] == "MEDICAL":
        entry["refunded_cents"] += (
            entry["entry_fee_cents"] - entry["purse_contribution_cents"]
        )
    else:
        entry["refunded_cents"] += entry["entry_fee_cents"]
        entry["refunded_contribution_cents"] += entry["purse_contribution_cents"]


# ---------------------------------------------------------------------------
# shared lookups
# ---------------------------------------------------------------------------

def rodeo_of_event(event):
    return DB["rodeos"][event["rodeo_id"]]


def rodeo_of_entry(entry):
    return rodeo_of_event(DB["rodeo_events"][entry["rodeo_event_id"]])


def events_of_rodeo(rodeo_id):
    return [e for e in DB["rodeo_events"].values() if e["rodeo_id"] == rodeo_id]


def perfs_of_rodeo(rodeo_id):
    return [p for p in DB["performances"].values() if p["rodeo_id"] == rodeo_id]


def entries_of_event(event_id):
    return [e for e in DB["entries"].values() if e["rodeo_event_id"] == event_id]


def payout_of_event(event_id):
    for p in DB["payouts"].values():
        if p["rodeo_event_id"] == event_id:
            return p
    return None


# ---------------------------------------------------------------------------
# cascades (PRD 2.7 / state machine side effects)
# ---------------------------------------------------------------------------

def release_assignment(assignment, free_animal=True):
    """PENDING -> RELEASED; the drawn animal returns to AVAILABLE."""
    if assignment["status"] != "PENDING":
        return
    assignment["status"] = "RELEASED"
    touch(assignment)
    if free_animal and assignment["animal_id"]:
        animal = DB["stock_animals"].get(assignment["animal_id"])
        if animal is not None and animal["status"] == "DRAWN":
            animal["status"] = "AVAILABLE"
            touch(animal)


def release_entry_assignments(entry, free_animals=True):
    """Release every PENDING assignment of an entry, freeing drawn animals."""
    for a in DB["draw_assignments"].values():
        if a["entry_id"] == entry["id"] and a["status"] == "PENDING":
            release_assignment(a, free_animal=free_animals)


# ---------------------------------------------------------------------------
# draw (PRD 3.5)
# ---------------------------------------------------------------------------

def plan_draw(rodeo, event, go_round):
    """Build the full draw plan without mutating anything (atomic draw).

    Returns (prior_pending, prev_waitlisted, slots, waitlisted, animals).
    Raises ERR_INSUFFICIENT_STOCK when rough stock cannot cover every slot.
    """
    event_id = event["id"]
    prior_pending = [
        a
        for a in DB["draw_assignments"].values()
        if a["rodeo_event_id"] == event_id
        and a["go_round_number"] == go_round
        and a["status"] == "PENDING"
    ]
    freed_animal_ids = [a["animal_id"] for a in prior_pending if a["animal_id"]]
    prev_waitlisted = [
        e
        for e in entries_of_event(event_id)
        if e["status"] == "WAITLISTED" and e.get("_waitlisted_round") == go_round
    ]
    prev_wl_ids = {e["id"] for e in prev_waitlisted}
    # Pool: the event's ENTERED entries plus entries still DRAWN from other
    # go-rounds, plus this go-round's prior waitlisted entries (which the
    # supersede returns to ENTERED before the new draw is built).
    pool = [
        e
        for e in entries_of_event(event_id)
        if e["status"] in ("ENTERED", "DRAWN") or e["id"] in prev_wl_ids
    ]
    contestants = DB["contestants"]
    pool.sort(
        key=lambda e: (
            e["created_at"],
            contestants[e["contestant_id"]]["card_number"],
            e["_seq"],
        )
    )
    perfs = [
        p
        for p in perfs_of_rodeo(rodeo["id"])
        if p["status"] == "SCHEDULED"
    ]
    perfs.sort(key=lambda p: (p["_starts_dt"], p["_seq"]))
    slots_cap = event["per_performance_slots"]
    used = {p["id"]: 0 for p in perfs}
    n_perf = len(perfs)
    slots = []  # (entry, performance, draw_position)
    waitlisted = []
    ptr = 0
    for entry in pool:
        chosen = None
        for i in range(n_perf):
            idx = (ptr + i) % n_perf
            if used[perfs[idx]["id"]] < slots_cap:
                chosen = idx
                break
        if chosen is None:
            waitlisted.append(entry)
        else:
            perf = perfs[chosen]
            used[perf["id"]] += 1
            slots.append((entry, perf, used[perf["id"]]))
            ptr = (chosen + 1) % n_perf
    animals = []
    if event["discipline"] == "ROUGH_STOCK" and slots:
        contracts = DB["stock_contracts"]

        def eligible(animal):
            if animal["event_code"] != event["event_code"]:
                return False
            if animal["welfare_out_count"] >= MAX_OUTS_PER_RODEO:
                return False
            contract = contracts[animal["contract_id"]]
            if contract["status"] != "ACTIVE":
                return False
            return True

        pool_animals = [
            a
            for a in DB["stock_animals"].values()
            if a["status"] == "AVAILABLE" and eligible(a)
        ]
        seen = {a["id"] for a in pool_animals}
        for aid in freed_animal_ids:
            # Animals the supersede frees become AVAILABLE again before the
            # new draw is built, so they rejoin the eligible pool.
            animal = DB["stock_animals"][aid]
            if animal["id"] not in seen and eligible(animal):
                pool_animals.append(animal)
                seen.add(animal["id"])
        pool_animals.sort(key=lambda a: a["tag_number"])
        if len(pool_animals) < len(slots):
            raise ApiError(
                "ERR_INSUFFICIENT_STOCK",
                409,
                "Not enough eligible animals for an atomic rough-stock draw",
            )
        animals = pool_animals[: len(slots)]
    return prior_pending, prev_waitlisted, slots, waitlisted, animals


def commit_draw(rodeo, event, go_round, plan):
    prior_pending, prev_waitlisted, slots, waitlisted, animals = plan
    # Supersede: release the prior draw of this go-round first.
    for assignment in prior_pending:
        release_assignment(assignment)
    for entry in prev_waitlisted:
        entry["status"] = "ENTERED"
        entry["_waitlisted_round"] = None
        touch(entry)
    for i, (entry, perf, position) in enumerate(slots):
        animal_id = animals[i]["id"] if animals else None
        rec = {
            "id": new_id(),
            "entry_id": entry["id"],
            "rodeo_event_id": event["id"],
            "go_round_number": go_round,
            "performance_id": perf["id"],
            "animal_id": animal_id,
            "draw_position": position,
            "status": "PENDING",
        }
        stamp(rec)
        DB["draw_assignments"][rec["id"]] = rec
        if animal_id is not None:
            animal = DB["stock_animals"][animal_id]
            animal["status"] = "DRAWN"
            touch(animal)
        if entry["status"] != "DRAWN":
            entry["status"] = "DRAWN"
            touch(entry)
    for entry in waitlisted:
        entry["status"] = "WAITLISTED"
        entry["_waitlisted_round"] = go_round
        touch(entry)
    if go_round not in event["drawn_rounds"]:
        event["drawn_rounds"].append(go_round)
    touch(event)  # executing a draw increments the event version by 1
    return len(slots), len(waitlisted)


# ---------------------------------------------------------------------------
# results: verify / amend cascades (PRD 3.4)
# ---------------------------------------------------------------------------

def bubble_up_entry(entry):
    """DRAWN -> COMPETED once every go-round 1..N has a COMPLETED assignment."""
    if entry["status"] != "DRAWN":
        return
    event = DB["rodeo_events"][entry["rodeo_event_id"]]
    assignments = [
        a for a in DB["draw_assignments"].values() if a["entry_id"] == entry["id"]
    ]
    for g in range(1, event["go_rounds"] + 1):
        if not any(
            a["go_round_number"] == g and a["status"] == "COMPLETED"
            for a in assignments
        ):
            return
    entry["status"] = "COMPETED"
    touch(entry)


def verify_cascade(result):
    """RECORDED/AMENDED -> VERIFIED: assignment, animal welfare, entry bubble."""
    result["status"] = "VERIFIED"
    result["verified_at"] = now_iso()
    result["_verified_dt"] = parse_dt(result["verified_at"])
    assignment = DB["draw_assignments"][result["draw_assignment_id"]]
    if assignment["status"] == "PENDING":
        assignment["status"] = "COMPLETED"
        touch(assignment)
        if assignment["animal_id"]:
            animal = DB["stock_animals"][assignment["animal_id"]]
            animal["welfare_out_count"] += 1
            if animal["status"] == "DRAWN":
                # DRAWN -> COMPETED, then auto-release or auto-retire (3 outs,
                # boundary inclusive).
                if animal["welfare_out_count"] >= MAX_OUTS_PER_RODEO:
                    animal["status"] = "RETIRED"
                else:
                    animal["status"] = "AVAILABLE"
            touch(animal)
        entry = DB["entries"][assignment["entry_id"]]
        bubble_up_entry(entry)
    touch(result)


def amend_compensate(result):
    """VERIFIED -> AMENDED: unwind the verification cascade."""
    assignment = DB["draw_assignments"][result["draw_assignment_id"]]
    if assignment["status"] == "COMPLETED":
        assignment["status"] = "PENDING"
        touch(assignment)
    if assignment["animal_id"]:
        animal = DB["stock_animals"][assignment["animal_id"]]
        animal["welfare_out_count"] = max(0, animal["welfare_out_count"] - 1)
        if animal["status"] in ("COMPETED", "RETIRED", "AVAILABLE"):
            animal["status"] = "DRAWN"
        touch(animal)
    entry = DB["entries"][assignment["entry_id"]]
    if entry["status"] == "COMPETED":
        entry["status"] = "DRAWN"
        touch(entry)


# ---------------------------------------------------------------------------
# payout computation (PRD 3.7 / calculation purse_and_places)
# ---------------------------------------------------------------------------

def _result_order_key(result):
    """Tie-remainder receiver: verified_at ASC (never-verified last), then
    RunResult.created_at ASC (insertion order). Never resource id."""
    return (result.get("_verified_dt") or _FAR, result["_seq"])


def _allocate(scope, pool_cents, ranked, payout_places, metric_fn, cid_fn, order_fn):
    """Split a pool across paid places with pinned tie-splitting.

    ranked: items sorted best-first. The last paid place receives the pool
    residual after earlier places are rounded half-up (PRD 2.6).
    """
    k = min(payout_places, len(ranked))
    if k == 0:
        return []
    pcts = PAYOUT_PCTS[payout_places]
    amounts = []
    for i in range(k):
        if i < k - 1:
            amounts.append(round_half_up_cents(Decimal(pool_cents) * pcts[i] / 100))
        else:
            amounts.append(pool_cents - sum(amounts))
    lines = []
    i = 0
    while i < k:
        j = i
        while j + 1 < k and metric_fn(ranked[j + 1]) == metric_fn(ranked[i]):
            j += 1
        group = ranked[i : j + 1]
        m = len(group)
        combined = sum(amounts[i : j + 1])
        each = round_half_up_cents(Decimal(combined) / m)
        leftover = combined - m * each
        receiver = min(group, key=order_fn)
        for member in group:
            amount = each + (leftover if member is receiver else 0)
            lines.append(
                {
                    "scope": scope,
                    "place": i + 1,
                    "contestant_id": cid_fn(member),
                    "amount_cents": amount,
                    "tied_count": m,
                }
            )
        i = j + 1
    return lines


def compute_purse_and_places(event, variant):
    """purse_and_places + average_aggregate. variant: PROVISIONAL | FINAL."""
    statuses = {"RECORDED", "VERIFIED"} if variant == "PROVISIONAL" else {"VERIFIED"}
    entries = entries_of_event(event["id"])
    purse = event["added_money_cents"] + sum(
        e["contribution_charges_cents"] - e["refunded_contribution_cents"]
        for e in entries
    )
    n_rounds = event["go_rounds"]
    pool_g = round_half_up_cents(
        Decimal(purse) * (Decimal(1) - AVERAGE_SHARE_PCT) / Decimal(n_rounds)
    )
    rough = event["discipline"] == "ROUGH_STOCK"
    assignments = DB["draw_assignments"]
    results = [
        r
        for r in DB["run_results"].values()
        if r["rodeo_event_id"] == event["id"] and r["status"] in statuses
    ]

    def metric(result):
        return result["total_score"] if rough else result["total_time_ms"]

    def contestant_of(result):
        return DB["entries"][result["entry_id"]]["contestant_id"]

    go_round_pools = []
    place_lines = []
    non_empty_sum = 0
    for g in range(1, n_rounds + 1):
        round_results = [
            r
            for r in results
            if r["outcome"] == "QUALIFIED"
            and assignments[r["draw_assignment_id"]]["go_round_number"] == g
        ]
        ranked = sorted(round_results, key=lambda r: -metric(r) if rough else metric(r))
        go_round_pools.append({"go_round": g, "pool_cents": pool_g})
        if ranked:
            non_empty_sum += pool_g
        place_lines.extend(
            _allocate(
                f"GO_ROUND_{g}",
                pool_g,
                ranked,
                event["payout_places"],
                metric,
                contestant_of,
                _result_order_key,
            )
        )
    # The average pool absorbs every cent not allocated to non-empty go-rounds.
    average_pool = purse - non_empty_sum

    # average_aggregate: a contestant is eligible only with a QUALIFIED
    # in-scope result in EVERY go-round 1..go_rounds.
    by_contestant = {}
    for r in results:
        if r["outcome"] != "QUALIFIED":
            continue
        cid = contestant_of(r)
        g = assignments[r["draw_assignment_id"]]["go_round_number"]
        by_contestant.setdefault(cid, {})
        by_contestant[cid].setdefault(g, r)
    eligible = []
    for cid, gmap in by_contestant.items():
        if all(g in gmap for g in range(1, n_rounds + 1)):
            aggregate = sum(metric(gmap[g]) for g in range(1, n_rounds + 1))
            best = min(gmap.values(), key=_result_order_key)
            eligible.append({"cid": cid, "agg": aggregate, "best": best})
    eligible.sort(key=lambda t: -t["agg"] if rough else t["agg"])
    place_lines.extend(
        _allocate(
            "AVERAGE",
            average_pool,
            eligible,
            event["payout_places"],
            lambda t: t["agg"],
            lambda t: t["cid"],
            lambda t: _result_order_key(t["best"]),
        )
    )
    return {
        "purse_cents": purse,
        "go_round_pools": go_round_pools,
        "average_pool_cents": average_pool,
        "place_lines": place_lines,
    }


# ---------------------------------------------------------------------------
# contractor settlement (PRD 3.7 / calculation contractor_settlement)
# ---------------------------------------------------------------------------

def settle_contract(contract, rodeo_id):
    days = {
        p["_starts_dt"].date()
        for p in perfs_of_rodeo(rodeo_id)
        if p["status"] in ("SCHEDULED", "COMPLETED")
    }
    day_rate_total = contract["day_rate_cents"] * len(days)
    contract_animals = {
        a["id"] for a in DB["stock_animals"].values() if a["contract_id"] == contract["id"]
    }
    outs = sum(
        1
        for a in DB["draw_assignments"].values()
        if a["status"] == "COMPLETED" and a["animal_id"] in contract_animals
    )
    per_out_total = contract["per_out_fee_cents"] * outs
    contract["day_rate_total_cents"] = day_rate_total
    contract["per_out_total_cents"] = per_out_total
    contract["settlement_cents"] = max(day_rate_total, per_out_total)
    # Tie pays the day rate.
    contract["settlement_basis"] = (
        "DAY_RATE" if day_rate_total >= per_out_total else "PER_OUT"
    )
    contract["status"] = "SETTLED"
    touch(contract)


# ---------------------------------------------------------------------------
# rodeo-level cascades (PRD 3.1 / state machine Rodeo)
# ---------------------------------------------------------------------------

def unlock_draw_cascade(rodeo_id):
    event_ids = {e["id"] for e in events_of_rodeo(rodeo_id)}
    for a in DB["draw_assignments"].values():
        if a["rodeo_event_id"] in event_ids and a["status"] == "PENDING":
            release_assignment(a)
    for e in DB["entries"].values():
        if e["rodeo_event_id"] in event_ids and e["status"] in ("WAITLISTED", "DRAWN"):
            e["status"] = "ENTERED"
            e["_waitlisted_round"] = None
            touch(e)
    for event in events_of_rodeo(rodeo_id):
        if event["drawn_rounds"]:
            event["drawn_rounds"] = []
            touch(event)


def cancel_rodeo_cascade(rodeo_id):
    event_ids = {e["id"] for e in events_of_rodeo(rodeo_id)}
    for e in DB["entries"].values():
        if e["rodeo_event_id"] in event_ids and e["status"] not in ENTRY_TERMINAL:
            release_entry_assignments(e)
            refund_full(e)
            e["status"] = "CANCELLED"
            touch(e)
    for a in DB["draw_assignments"].values():
        if a["rodeo_event_id"] in event_ids and a["status"] == "PENDING":
            release_assignment(a)


def settle_rodeo_cascade(rodeo):
    rodeo_id = rodeo["id"]
    for event in events_of_rodeo(rodeo_id):
        payout = payout_of_event(event["id"])
        if payout is not None and payout["status"] == "FINAL":
            payout["status"] = "DISBURSED"
            touch(payout)
    for contract in DB["stock_contracts"].values():
        if contract["rodeo_id"] == rodeo_id and contract["status"] == "ACTIVE":
            settle_contract(contract, rodeo_id)
    for event in events_of_rodeo(rodeo_id):
        payout = payout_of_event(event["id"])
        if payout is None:
            continue
        has_average = any(l["scope"] == "AVERAGE" for l in payout["place_lines"])
        if not has_average:
            rodeo["unclaimed_purse_cents"] += payout["average_pool_cents"]


def suspend_contestant_cascade(contestant_id):
    for e in DB["entries"].values():
        if e["contestant_id"] != contestant_id:
            continue
        if e["status"] in ("ENTERED", "WAITLISTED"):
            refund_full(e)
            e["status"] = "CANCELLED"
            touch(e)
        elif e["status"] == "DRAWN":
            release_entry_assignments(e)
            refund_full(e)
            e["status"] = "DRAWN_OUT"
            touch(e)


def terminate_contract_cascade(contract):
    for animal in DB["stock_animals"].values():
        if animal["contract_id"] != contract["id"]:
            continue
        if animal["status"] in ("AVAILABLE", "INJURED"):
            animal["status"] = "RETIRED"
            touch(animal)
        elif animal["status"] == "DRAWN":
            pending = [
                a
                for a in DB["draw_assignments"].values()
                if a["animal_id"] == animal["id"] and a["status"] == "PENDING"
            ]
            entry_ids = []
            for a in pending:
                a["status"] = "RELEASED"
                touch(a)
                entry_ids.append(a["entry_id"])
            for entry_id in entry_ids:
                entry = DB["entries"][entry_id]
                if entry["status"] == "DRAWN":
                    release_entry_assignments(entry)
                    refund_full(entry)
                    entry["status"] = "DRAWN_OUT"
                    touch(entry)
            animal["status"] = "RETIRED"
            touch(animal)


def animal_injury_cascade(animal, report, new_status):
    """DRAWN animal injury/retire: release its assignments, turn out entries
    medically with contribution refund, then move the animal."""
    pending = [
        a
        for a in DB["draw_assignments"].values()
        if a["animal_id"] == animal["id"] and a["status"] == "PENDING"
    ]
    entry_ids = []
    for a in pending:
        a["status"] = "RELEASED"
        touch(a)
        entry_ids.append(a["entry_id"])
    for entry_id in entry_ids:
        entry = DB["entries"][entry_id]
        if entry["status"] == "DRAWN":
            release_entry_assignments(entry)
            refund_contribution_only(entry)
            entry["turn_out_reason"] = "MEDICAL"
            entry["vet_report_id"] = report["id"]
            entry["status"] = "TURNED_OUT"
            touch(entry)
    animal["status"] = new_status
    touch(animal)


def recompute_sold_tickets(performance):
    performance["sold_tickets"] = sum(
        o["quantity"]
        for o in DB["ticket_orders"].values()
        if o["performance_id"] == performance["id"] and o["status"] == "PAID"
    )


def cancel_performance_cascade(performance):
    for order in DB["ticket_orders"].values():
        if order["performance_id"] == performance["id"] and order["status"] == "PAID":
            order["status"] = "REFUNDED"
            touch(order)
    recompute_sold_tickets(performance)
