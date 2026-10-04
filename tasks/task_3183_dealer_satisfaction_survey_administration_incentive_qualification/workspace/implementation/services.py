"""Business logic: scoring, posture, sampling, tiering, benchmarks."""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import clock
import db
import helpers

WINDOW_DAYS = 14
MAX_PER_DEALER_KIND = 20
CONTACT_SUPPRESSION_DAYS = 90
MIN_RESPONSE_RATE = Decimal("0.30")


def D(x):
    return Decimal(str(x))


def round2(x):
    return D(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def round4(x):
    return D(x).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def dec_to_float(d):
    """Serialize a Decimal as a JSON number via float (values are pre-quantized)."""
    if d is None:
        return None
    return float(d)


# ---------------------------------------------------------------- responses


def compute_response_score(question_set, answers):
    """Weighted mean scaled to 0-100, round_half_up 2dp."""
    weights = {q["question_code"]: D(q["weight"]) for q in question_set["questions"]}
    w_total = sum(weights.values(), Decimal("0"))
    s = sum(
        (D(a["score"]) * weights[a["question_code"]] for a in answers),
        Decimal("0"),
    )
    return round2(s * Decimal("10") / w_total)


# ------------------------------------------------------------------- flags


def recompute_confirmed_flag_count(dealer):
    """Count CONFIRMED flags over the trailing two CLOSED waves.

    Window anchor: the closed_at of the second most recent closed wave. Flags
    confirmed at or after that anchor count; with fewer than two closed waves,
    all CONFIRMED flags count.
    """
    closed = [
        w
        for w in db.waves.values()
        if w["status"] in ("CLOSED", "FINALIZED") and w["closed_at"] is not None
    ]
    closed.sort(key=lambda w: w["closed_at"])
    threshold = closed[-2]["closed_at"] if len(closed) >= 2 else None
    count = 0
    for f in db.flags.values():
        if f["dealer_id"] != dealer["id"] or f["status"] != "CONFIRMED":
            continue
        confirmed_at = f.get("confirmed_at")
        if threshold is None or confirmed_at is None or confirmed_at >= threshold:
            count += 1
    dealer["confirmed_flag_count"] = count
    return count


def derive_posture(dealer):
    score = dealer["current_score_adjusted"]
    flags = dealer["confirmed_flag_count"]
    if score is None:
        return "GOOD_STANDING"
    if flags >= 3:
        return "SUSPENDED"
    if flags >= 2 or score < D(700):
        return "PROBATION"
    if flags == 1 or score < D(800):
        return "WATCH"
    return "GOOD_STANDING"


def apply_posture(dealer):
    """Re-derive posture; on transition to SUSPENDED auto-submit DRAFT plans."""
    new_posture = derive_posture(dealer)
    old_posture = dealer["posture"]
    if new_posture != old_posture:
        dealer["posture"] = new_posture
        helpers.touch(dealer)
    if new_posture == "SUSPENDED":
        for plan in db.action_plans.values():
            if plan["dealer_id"] == dealer["id"] and plan["status"] == "DRAFT":
                plan["status"] = "SUBMITTED"
                helpers.touch(plan)
    return new_posture


# ---------------------------------------------------------------- sampling


def _periods_overlap(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


def run_sampling_sweep(wave):
    """Runs once at DRAFT -> OPEN. Creates QUEUED invitations."""
    period_start = wave["period_start"]
    period_end = wave["period_end"]
    suppression_start = period_start - timedelta(days=CONTACT_SUPPRESSION_DAYS)

    other_waves = [w for w in db.waves.values() if w["id"] != wave["id"]]

    def is_suppressed(tx):
        for inv in db.invitations.values():
            if (
                inv["customer_id"] == tx["customer_id"]
                and inv["transaction_id"] != tx["id"]
            ):
                other_tx = db.transactions.get(inv["transaction_id"])
                if other_tx is None or other_tx["kind"] != tx["kind"]:
                    continue
                w2 = db.waves.get(inv["wave_id"])
                if w2 is None or w2["id"] == wave["id"]:
                    continue
                if _periods_overlap(
                    w2["period_start"],
                    w2["period_end"],
                    suppression_start,
                    period_end,
                ):
                    return True
        return False

    eligible = []
    for tx in db.transactions.values():
        if not (period_start <= tx["completed_at"] < period_end):
            continue
        cust = db.customers.get(tx["customer_id"])
        if cust is None or cust["do_not_contact"]:
            continue
        if is_suppressed(tx):
            continue
        eligible.append(tx)

    eligible.sort(key=lambda t: (t["completed_at"], t["created_at"]))

    per_group = {}
    for tx in eligible:
        key = (tx["dealer_id"], tx["kind"])
        per_group.setdefault(key, []).append(tx)

    for key, txs in per_group.items():
        for tx in txs[:MAX_PER_DEALER_KIND]:
            inv = helpers.make_record()
            inv.update(
                {
                    "transaction_id": tx["id"],
                    "customer_id": tx["customer_id"],
                    "wave_id": wave["id"],
                    "question_set_id": wave["question_set_id"],
                    "status": "QUEUED",
                    "sent_at": None,
                    "window_closes_at": None,
                }
            )
            db.invitations[inv["id"]] = inv
            wave["invitations_total"] += 1
            wave["queued_count"] += 1


# --------------------------------------------------------------- wave close


def dealer_ids_with_transactions_in_period(wave):
    ids = set()
    for tx in db.transactions.values():
        if wave["period_start"] <= tx["completed_at"] < wave["period_end"]:
            ids.add(tx["dealer_id"])
    return ids


def compute_dealer_wave_numbers(dealer_id, wave):
    """Return (raw_score, adjusted_score, response_rate) Decimals or None."""
    invitations = [
        inv
        for inv in db.invitations.values()
        if inv["wave_id"] == wave["id"]
        and db.transactions.get(inv["transaction_id"])
        and db.transactions[inv["transaction_id"]]["dealer_id"] == dealer_id
    ]
    if not invitations:
        return None, None, None
    responded = sum(1 for inv in invitations if inv["status"] == "RESPONDED")
    rate = round4(D(responded) / D(len(invitations)))
    scored = []
    for inv in invitations:
        for resp in db.responses.values():
            if resp["invitation_id"] == inv["id"] and resp["status"] == "SCORED":
                scored.append(resp)
    if not scored:
        return None, None, rate
    avg = sum((r["score"] for r in scored), Decimal("0")) / D(len(scored))
    raw = round2(avg * Decimal("10"))
    dealer = db.dealers[dealer_id]
    adjusted = round2(raw - Decimal("25") * D(dealer["confirmed_flag_count"]))
    if adjusted < 0:
        adjusted = Decimal("0.00")
    return raw, adjusted, rate


def close_wave(wave):
    now = clock.now()
    for inv in db.invitations.values():
        if inv["wave_id"] != wave["id"]:
            continue
        if inv["status"] == "QUEUED":
            inv["status"] = "EXPIRED"
            helpers.touch(inv)
            wave["queued_count"] -= 1
            wave["expired_count"] += 1
        elif inv["status"] == "SENT":
            inv["status"] = "EXPIRED"
            helpers.touch(inv)
            wave["sent_count"] -= 1
            wave["expired_count"] += 1
    wave["closed_at"] = now
    wave["status"] = "CLOSED"
    for dealer_id in dealer_ids_with_transactions_in_period(wave):
        dealer = db.dealers.get(dealer_id)
        if dealer is None:
            continue
        recompute_confirmed_flag_count(dealer)
        _raw, adjusted, rate = compute_dealer_wave_numbers(dealer_id, wave)
        dealer["current_score_adjusted"] = adjusted
        dealer["current_response_rate"] = rate
        apply_posture(dealer)
        helpers.touch(dealer)
    # lazy OVERDUE evaluation at wave close
    evaluate_overdue_plans()
    helpers.touch(wave)


# ------------------------------------------------------------- action plans


def evaluate_overdue_plans():
    now = clock.now()
    for plan in db.action_plans.values():
        if plan["status"] == "IN_PROGRESS" and now >= plan["due_date"]:
            plan["status"] = "OVERDUE"
            helpers.touch(plan)


def maybe_mark_overdue(plan):
    if plan["status"] == "IN_PROGRESS" and clock.now() >= plan["due_date"]:
        plan["status"] = "OVERDUE"
        helpers.touch(plan)


# ----------------------------------------------------------------- tiering


TIER_RATES = {
    "GOLD": Decimal("0.08"),
    "SILVER": Decimal("0.05"),
    "BRONZE": Decimal("0.02"),
    "INELIGIBLE": Decimal("0"),
}


def compute_tier(score_used, response_rate_used):
    if score_used is None or response_rate_used is None:
        return "INELIGIBLE"
    if D(response_rate_used) < MIN_RESPONSE_RATE:
        return "INELIGIBLE"
    s = D(score_used)
    if s >= D(900):
        return "GOLD"
    if s >= D(800):
        return "SILVER"
    if s >= D(700):
        return "BRONZE"
    return "INELIGIBLE"


def eligible_margin_cents(dealer_id, wave):
    total = 0
    for tx in db.transactions.values():
        if tx["dealer_id"] != dealer_id:
            continue
        if wave["period_start"] <= tx["completed_at"] < wave["period_end"]:
            total += tx["margin_cents"]
    return total


def compute_statement_values(dealer, wave):
    score_used = dealer["current_score_adjusted"]
    rate_used = dealer["current_response_rate"]
    margin = eligible_margin_cents(dealer["id"], wave)
    tier = compute_tier(score_used, rate_used)
    payout = int(
        (D(margin) * TIER_RATES[tier]).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )
    return {
        "score_used": score_used,
        "response_rate_used": rate_used,
        "tier": tier,
        "eligible_margin_cents": margin,
        "payout_cents": payout,
    }
