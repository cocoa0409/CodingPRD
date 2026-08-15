"""Core domain services: serialization, computed fields, lazy transitions,
scoring, alert lifecycle, compromise cascade, loss/recovery cascade, rings."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

import db
import errors
import middleware


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

def _parse_iso(s: str) -> datetime:
    return db._parse_iso(s)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _today() -> date:
    return db.get_clock().date()


def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def ser_account(a):
    return {
        "id": a["id"],
        "account_number": a["account_number"],
        "cardholder_name": a["cardholder_name"],
        "home_country": a["home_country"],
        "account_status": a["account_status"],
        "credit_balance_cents": a["credit_balance_cents"],
        "open_alert_count": a["open_alert_count"],
        "rolling_90d_loss_cents": a["rolling_90d_loss_cents"],
        "risk_tier": a["risk_tier"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def ser_card(c):
    return {
        "id": c["id"],
        "account_id": c["account_id"],
        "pan_token": c["pan_token"],
        "product_type": c["product_type"],
        "network": c["network"],
        "card_status": c["card_status"],
        "fraud_flag": c["fraud_flag"],
        "block_reason": c["block_reason"],
        "replaces_card_id": c["replaces_card_id"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def ser_ruleset(r):
    return {
        "id": r["id"],
        "scope": r["scope"],
        "base_score": r["base_score"],
        "review_threshold": r["review_threshold"],
        "decline_threshold": r["decline_threshold"],
        "amount_tiers": r["amount_tiers"],
        "channel_weights": r["channel_weights"],
        "cross_border_weight": r["cross_border_weight"],
        "high_risk_multiplier": r["high_risk_multiplier"],
        "watch_weight": r["watch_weight"],
        "compromised_weight": r["compromised_weight"],
        "high_risk_countries": r["high_risk_countries"],
        "ruleset_status": r["ruleset_status"],
        "created_by_user_id": r["created_by_user_id"],
        "activated_by_user_id": r["activated_by_user_id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_txn(t):
    return {
        "id": t["id"],
        "card_id": t["card_id"],
        "account_id": t["account_id"],
        "ruleset_id": t["ruleset_id"],
        "amount_cents": t["amount_cents"],
        "currency": t["currency"],
        "merchant_id": t["merchant_id"],
        "merchant_category_code": t["merchant_category_code"],
        "channel": t["channel"],
        "origin_country": t["origin_country"],
        "home_country": t["home_country"],
        "scored_at": t["scored_at"],
        "auth_score": t["auth_score"],
        "decision": t["decision"],
        "decision_reason": t["decision_reason"],
        "shadow_score": t.get("shadow_score"),
        "shadow_decision": t.get("shadow_decision"),
        "shadow_ruleset_id": t.get("shadow_ruleset_id"),
        "final_disposition": t["final_disposition"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def ser_alert(a):
    return {
        "id": a["id"],
        "account_id": a["account_id"],
        "card_id": a["card_id"],
        "auth_transaction_id": a["auth_transaction_id"],
        "source": a["source"],
        "alert_status": a["alert_status"],
        "band_points": a["band_points"],
        "priority": a["priority"],
        "assigned_to_user_id": a["assigned_to_user_id"],
        "reopen_count": a["reopen_count"],
        "resolution": a["resolution"],
        "fraud_credit_cents": a["fraud_credit_cents"],
        "sla_expires_at": a["sla_expires_at"],
        "resolved_at": a["resolved_at"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def ser_contact(c):
    return {
        "id": c["id"],
        "alert_id": c["alert_id"],
        "account_id": c["account_id"],
        "channel": c["channel"],
        "contact_status": c["contact_status"],
        "outcome": c["outcome"],
        "contacted_at": c["contacted_at"],
        "created_by_user_id": c["created_by_user_id"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def ser_event(e):
    return {
        "id": e["id"],
        "network_source": e["network_source"],
        "event_reference": e["event_reference"],
        "merchant_id": e["merchant_id"],
        "window_start": e["window_start"],
        "window_end": e["window_end"],
        "event_status": e["event_status"],
        "affected_card_count": e["affected_card_count"],
        "confirmed_at": e["confirmed_at"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def ser_reissue(r):
    return {
        "id": r["id"],
        "event_id": r["event_id"],
        "card_id": r["card_id"],
        "replacement_card_id": r["replacement_card_id"],
        "decision": r["decision"],
        "exposure_cents": r["exposure_cents"],
        "due_at": r["due_at"],
        "decided_by_user_id": r["decided_by_user_id"],
        "decided_at": r["decided_at"],
        "rationale": r["rationale"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_notice(n):
    return {
        "id": n["id"],
        "card_id": n["card_id"],
        "region_country": n["region_country"],
        "start_date": n["start_date"],
        "end_date": n["end_date"],
        "notice_status": n["notice_status"],
        "created_at": n["created_at"],
        "updated_at": n["updated_at"],
        "version": n["version"],
    }


def ser_cb(c):
    return {
        "id": c["id"],
        "auth_transaction_id": c["auth_transaction_id"],
        "account_id": c["account_id"],
        "reason_code": c["reason_code"],
        "provisional_credit_cents": c["provisional_credit_cents"],
        "cb_status": c["cb_status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def ser_loss(l):
    return {
        "id": l["id"],
        "account_id": l["account_id"],
        "transaction_ids": l["transaction_ids"],
        "provisional_amount_cents": l["provisional_amount_cents"],
        "tolerance_cents": l["tolerance_cents"],
        "final_amount_cents": l["final_amount_cents"],
        "outstanding_cents": l["outstanding_cents"],
        "written_off_cents": l["written_off_cents"],
        "loss_status": l["loss_status"],
        "booked_by_user_id": l["booked_by_user_id"],
        "booked_at": l["booked_at"],
        "finalized_at": l["finalized_at"],
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
        "version": l["version"],
    }


def ser_filing(f):
    return {
        "id": f["id"],
        "loss_entry_id": f["loss_entry_id"],
        "network_reference": f["network_reference"],
        "claimed_cents": f["claimed_cents"],
        "paid_cents": f["paid_cents"],
        "filing_status": f["filing_status"],
        "filed_by_user_id": f["filed_by_user_id"],
        "created_at": f["created_at"],
        "updated_at": f["updated_at"],
        "version": f["version"],
    }


def ser_ring(r):
    return {
        "id": r["id"],
        "signal_type": r["signal_type"],
        "merchant_id": r["merchant_id"],
        "window_start": r["window_start"],
        "window_end": r["window_end"],
        "ring_status": r["ring_status"],
        "member_count": r["member_count"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_membership(m):
    return {
        "id": m["id"],
        "ring_id": m["ring_id"],
        "account_id": m["account_id"],
        "evidence_txn_count": m["evidence_txn_count"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


# ---------------------------------------------------------------------------
# Account derived fields
# ---------------------------------------------------------------------------

def _recompute_account(account_id: str) -> None:
    """Recompute credit_balance_cents, open_alert_count, rolling_90d_loss_cents, risk_tier."""
    acct = db.accounts.get(account_id)
    if not acct:
        return

    # credit_balance_cents
    cb_sum = 0
    for c in db.chargeback_cases.values():
        if c["account_id"] == account_id and c["cb_status"] in (
            "PROVISIONAL_CREDIT_POSTED",
            "REPRESENTMENT_FILED",
            "RESOLVED_WON",
        ):
            cb_sum += c["provisional_credit_cents"]
    fc_sum = 0
    for a in db.fraud_alerts.values():
        if a["account_id"] == account_id and a["alert_status"] == "RESOLVED_FRAUD":
            fc_sum += a["fraud_credit_cents"]

    # open_alert_count
    open_count = 0
    for a in db.fraud_alerts.values():
        if a["account_id"] == account_id and a["alert_status"] in (
            "OPEN",
            "IN_REVIEW",
            "CONTACT_PENDING",
        ):
            open_count += 1

    # rolling_90d_loss_cents
    now = db.get_clock()
    window_start = now - timedelta(days=90)
    rolling = 0
    for l in db.loss_entries.values():
        if l["account_id"] != account_id:
            continue
        if l["loss_status"] not in ("FINALIZED", "PARTIALLY_RECOVERED", "WRITTEN_OFF"):
            continue
        if not l["finalized_at"]:
            continue
        fa = _parse_iso(l["finalized_at"])
        if window_start <= fa <= now:
            rolling += l["final_amount_cents"] or 0

    # risk_tier
    has_compromised = any(
        c["account_id"] == account_id and c["fraud_flag"] == "COMPROMISED"
        for c in db.cards.values()
    )
    has_watch = any(
        c["account_id"] == account_id and c["fraud_flag"] == "WATCH"
        for c in db.cards.values()
    )
    if open_count >= 2 or rolling >= 100000 or has_compromised:
        tier = "HIGH"
    elif open_count == 1 or rolling >= 25000 or has_watch:
        tier = "MEDIUM"
    else:
        tier = "LOW"

    changed = (
        acct["credit_balance_cents"] != cb_sum + fc_sum
        or acct["open_alert_count"] != open_count
        or acct["rolling_90d_loss_cents"] != rolling
        or acct["risk_tier"] != tier
    )
    if changed:
        acct["credit_balance_cents"] = cb_sum + fc_sum
        acct["open_alert_count"] = open_count
        acct["rolling_90d_loss_cents"] = rolling
        acct["risk_tier"] = tier
        middleware.touch(acct)


def _escalate_open_alerts(account_id: str) -> None:
    """For accounts that just reached HIGH, raise open alerts per escalation rule."""
    for a in db.fraud_alerts.values():
        if a["account_id"] != account_id:
            continue
        if a["alert_status"] not in ("OPEN", "IN_REVIEW", "CONTACT_PENDING"):
            continue
        new_priority = max(a["priority"], 200 + a["band_points"])
        if new_priority != a["priority"]:
            a["priority"] = new_priority
            middleware.touch(a)


# ---------------------------------------------------------------------------
# Lazy time-based transitions
# ---------------------------------------------------------------------------

def apply_time_based_transitions() -> None:
    """Apply lazy transitions across alerts, reissue decisions, travel notices,
    and (cascade) compromise event auto-close. Called on clock advance."""
    _apply_alert_expiry_all()
    _apply_reissue_auto_approve_all()
    _apply_travel_notice_expiry_all()
    _apply_event_auto_close_all()
    # The rolling 90-day loss window (§2.11) ends at the *current* logical time,
    # so a clock advance alone can change an account's rolling_90d_loss_cents
    # and risk_tier without any write. Recompute every account so the stored
    # derived fields always match their §2.11/§3.1 definitions.
    for aid in list(db.accounts.keys()):
        _recompute_account(aid)


def _apply_alert_expiry_all() -> None:
    now = db.get_clock()
    for a in list(db.fraud_alerts.values()):
        if a["alert_status"] in ("OPEN", "IN_REVIEW", "CONTACT_PENDING"):
            if now >= _parse_iso(a["sla_expires_at"]):
                a["alert_status"] = "EXPIRED"
                middleware.touch(a)
                _recompute_account(a["account_id"])


def _apply_alert_expiry(alert: dict) -> None:
    if alert["alert_status"] in ("OPEN", "IN_REVIEW", "CONTACT_PENDING"):
        if db.get_clock() >= _parse_iso(alert["sla_expires_at"]):
            alert["alert_status"] = "EXPIRED"
            middleware.touch(alert)
            _recompute_account(alert["account_id"])


def _apply_reissue_auto_approve_all() -> None:
    now = db.get_clock()
    for d in list(db.reissue_decisions.values()):
        if d["decision"] == "PENDING" and now >= _parse_iso(d["due_at"]):
            _auto_approve_decision(d)


def _apply_reissue_auto_approve(decision: dict) -> None:
    if decision["decision"] == "PENDING" and db.get_clock() >= _parse_iso(decision["due_at"]):
        _auto_approve_decision(decision)


def _auto_approve_decision(d: dict) -> None:
    d["decision"] = "AUTO_APPROVED"
    d["decided_by_user_id"] = "SYSTEM"
    d["decided_at"] = db.get_clock_iso()
    _mint_replacement(d)
    middleware.touch(d)
    _event_auto_close(d["event_id"])


def _mint_replacement(d: dict) -> None:
    """Mint a replacement card and mark the exposed card REPLACED."""
    old = db.cards.get(d["card_id"])
    if not old:
        return
    new_card = middleware.stamp_new(
        {
            "account_id": old["account_id"],
            "pan_token": middleware.new_id(),
            "product_type": old["product_type"],
            "network": old["network"],
            "card_status": "ACTIVE",
            "fraud_flag": "WATCH",
            "block_reason": None,
            "replaces_card_id": old["id"],
        }
    )
    db.cards[new_card["id"]] = new_card
    d["replacement_card_id"] = new_card["id"]

    if old["card_status"] in ("ACTIVE", "SOFT_BLOCKED"):
        old["card_status"] = "REPLACED"
        old["block_reason"] = None
        middleware.touch(old)
        # Cancel active travel notices of the old card
        for n in db.travel_notices.values():
            if n["card_id"] == old["id"] and n["notice_status"] == "ACTIVE":
                n["notice_status"] = "CANCELLED"
                middleware.touch(n)
    _recompute_account(old["account_id"])


def _apply_travel_notice_expiry_all() -> None:
    today = _today()
    for n in db.travel_notices.values():
        if n["notice_status"] == "ACTIVE":
            if today >= _parse_date(n["end_date"]):
                n["notice_status"] = "EXPIRED"
                middleware.touch(n)


def _apply_travel_notice_expiry(notice: dict) -> None:
    if notice["notice_status"] == "ACTIVE":
        if _today() >= _parse_date(notice["end_date"]):
            notice["notice_status"] = "EXPIRED"
            middleware.touch(notice)


def _apply_event_auto_close_all() -> None:
    for e in list(db.compromised_card_events.values()):
        if e["event_status"] == "CONFIRMED":
            _event_auto_close(e["id"])


def _event_auto_close(event_id: str) -> None:
    e = db.compromised_card_events.get(event_id)
    if not e or e["event_status"] != "CONFIRMED":
        return
    pending = any(
        d["event_id"] == event_id and d["decision"] == "PENDING"
        for d in db.reissue_decisions.values()
    )
    if not pending:
        e["event_status"] = "CLOSED"
        middleware.touch(e)


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _active_ruleset_for_scope(scope: str):
    for r in db.rule_sets.values():
        if r["ruleset_status"] == "ACTIVE" and r["scope"] == scope:
            return r
    return None


def resolve_scoring_ruleset(product_type: str):
    scope = "DEBIT_CARD" if product_type == "DEBIT" else "CREDIT_CARD"
    r = _active_ruleset_for_scope(scope)
    if r:
        return r
    return _active_ruleset_for_scope("GLOBAL")


def _travel_suppressed(card_id: str, origin_country: str, scored_at_iso: str) -> bool:
    scored_date = _parse_iso(scored_at_iso).date()
    for n in db.travel_notices.values():
        if n["card_id"] != card_id:
            continue
        if n["notice_status"] != "ACTIVE":
            continue
        if n["region_country"] != origin_country:
            continue
        if _parse_date(n["start_date"]) <= scored_date < _parse_date(n["end_date"]):
            return True
    return False


def compute_score(card: dict, account: dict, ruleset: dict, amount_cents: int,
                  channel: str, origin_country: str, scored_at_iso: str) -> int:
    """Compute authorization score per §3.3."""
    amount_points = 0
    best_min = None
    for tier in ruleset["amount_tiers"]:
        m = tier["min_amount_cents"]
        if m <= amount_cents and (best_min is None or m > best_min):
            best_min = m
            amount_points = tier["points"]
    channel_points = ruleset["channel_weights"][channel]

    if origin_country == account["home_country"]:
        cross = 0
    elif origin_country in ruleset["high_risk_countries"]:
        prod = Decimal(str(ruleset["cross_border_weight"])) * Decimal(
            str(ruleset["high_risk_multiplier"])
        )
        cross = int(prod)
    else:
        cross = ruleset["cross_border_weight"]

    if _travel_suppressed(card["id"], origin_country, scored_at_iso):
        cross = 0

    if card["fraud_flag"] == "WATCH":
        flag = ruleset["watch_weight"]
    elif card["fraud_flag"] == "COMPROMISED":
        flag = ruleset["compromised_weight"]
    else:
        flag = 0

    return ruleset["base_score"] + amount_points + channel_points + cross + flag


def score_decision(ruleset: dict, score: int) -> str:
    if score >= ruleset["decline_threshold"]:
        return "DECLINE"
    if score >= ruleset["review_threshold"]:
        return "REVIEW"
    return "APPROVE"


# ---------------------------------------------------------------------------
# Alert helpers
# ---------------------------------------------------------------------------

TIER_POINTS = {"LOW": 0, "MEDIUM": 100, "HIGH": 200}


def _risk_tier_excluding_alert(account_id: str, exclude_alert_id: str | None) -> str:
    """Compute account risk tier as if the given alert did not exist."""
    open_count = 0
    for a in db.fraud_alerts.values():
        if a["id"] == exclude_alert_id:
            continue
        if a["account_id"] == account_id and a["alert_status"] in (
            "OPEN",
            "IN_REVIEW",
            "CONTACT_PENDING",
        ):
            open_count += 1

    now = db.get_clock()
    window_start = now - timedelta(days=90)
    rolling = 0
    for l in db.loss_entries.values():
        if l["account_id"] != account_id:
            continue
        if l["loss_status"] not in ("FINALIZED", "PARTIALLY_RECOVERED", "WRITTEN_OFF"):
            continue
        if not l["finalized_at"]:
            continue
        fa = _parse_iso(l["finalized_at"])
        if window_start <= fa <= now:
            rolling += l["final_amount_cents"] or 0

    has_compromised = any(
        c["account_id"] == account_id and c["fraud_flag"] == "COMPROMISED"
        for c in db.cards.values()
    )
    has_watch = any(
        c["account_id"] == account_id and c["fraud_flag"] == "WATCH"
        for c in db.cards.values()
    )
    if open_count >= 2 or rolling >= 100000 or has_compromised:
        return "HIGH"
    if open_count == 1 or rolling >= 25000 or has_watch:
        return "MEDIUM"
    return "LOW"


def create_alert(account_id: str, card_id: str | None, auth_transaction_id: str | None,
                 source: str, band_points: int) -> dict:
    """Create an alert with priority per the pinned 3-step order."""
    tier = _risk_tier_excluding_alert(account_id, exclude_alert_id=None)
    priority = TIER_POINTS[tier] + band_points
    created = db.get_clock()
    sla = created + timedelta(hours=72)
    alert = middleware.stamp_new(
        {
            "account_id": account_id,
            "card_id": card_id,
            "auth_transaction_id": auth_transaction_id,
            "source": source,
            "alert_status": "OPEN",
            "band_points": band_points,
            "priority": priority,
            "assigned_to_user_id": None,
            "reopen_count": 0,
            "resolution": None,
            "fraud_credit_cents": 0,
            "sla_expires_at": _iso(sla),
            "resolved_at": None,
        }
    )
    db.fraud_alerts[alert["id"]] = alert
    _recompute_account(account_id)
    return alert


# ---------------------------------------------------------------------------
# Loss / recovery helpers
# ---------------------------------------------------------------------------

RECOVERY_RATE = {"VISA": Decimal("0.45"), "MASTERCARD": Decimal("0.40")}


def _round_half_up_cents(d: Decimal) -> int:
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def compute_provisional(transaction_ids: list) -> int:
    total = 0
    for tid in transaction_ids:
        t = db.auth_transactions[tid]
        card = db.cards[t["card_id"]]
        rate = RECOVERY_RATE[card["network"]]
        line = Decimal(t["amount_cents"]) * (Decimal("1") - rate)
        total += _round_half_up_cents(line)
    return total


def compute_tolerance(provisional: int) -> int:
    return _round_half_up_cents(Decimal(provisional) * Decimal("0.10"))


def recompute_loss_outstanding(loss: dict) -> None:
    """Recompute outstanding_cents per INV-LOSS and cascade status changes."""
    paid_sum = sum(
        f["paid_cents"]
        for f in db.recovery_filings.values()
        if f["loss_entry_id"] == loss["id"] and f["filing_status"] == "PAID" and f["paid_cents"] is not None
    )
    final = loss["final_amount_cents"]
    if final is None:
        return
    new_outstanding = final - paid_sum - (loss["written_off_cents"] or 0)
    changed = False
    if new_outstanding != loss["outstanding_cents"]:
        loss["outstanding_cents"] = new_outstanding
        changed = True

    # status transitions driven by paid/reversed
    if loss["loss_status"] in ("FINALIZED", "PARTIALLY_RECOVERED", "FULLY_RECOVERED"):
        if new_outstanding == 0 and loss["loss_status"] != "FULLY_RECOVERED":
            loss["loss_status"] = "FULLY_RECOVERED"
            changed = True
        elif new_outstanding > 0:
            if loss["loss_status"] == "FULLY_RECOVERED":
                # reversal path
                if new_outstanding == final:
                    loss["loss_status"] = "FINALIZED"
                else:
                    loss["loss_status"] = "PARTIALLY_RECOVERED"
                changed = True
            elif loss["loss_status"] == "FINALIZED" and new_outstanding < final:
                loss["loss_status"] = "PARTIALLY_RECOVERED"
                changed = True
            elif loss["loss_status"] == "PARTIALLY_RECOVERED" and new_outstanding == final:
                loss["loss_status"] = "FINALIZED"
                changed = True

    if changed:
        middleware.touch(loss)
        _recompute_account(loss["account_id"])


# ---------------------------------------------------------------------------
# Shadow rescore
# ---------------------------------------------------------------------------

def apply_shadow(txn: dict) -> None:
    """Compute shadow_score/shadow_decision/shadow_ruleset_id at read time."""
    card = db.cards.get(txn["card_id"])
    if not card:
        txn["shadow_score"] = None
        txn["shadow_decision"] = None
        txn["shadow_ruleset_id"] = None
        return
    ruleset = resolve_scoring_ruleset(card["product_type"])
    if not ruleset:
        txn["shadow_score"] = None
        txn["shadow_decision"] = None
        txn["shadow_ruleset_id"] = None
        return
    if card["card_status"] != "ACTIVE":
        txn["shadow_score"] = None
        txn["shadow_decision"] = "DECLINE"
        txn["shadow_ruleset_id"] = ruleset["id"]
        return
    account = db.accounts[txn["account_id"]]
    score = compute_score(
        card, account, ruleset, txn["amount_cents"], txn["channel"],
        txn["origin_country"], txn["scored_at"],
    )
    txn["shadow_score"] = score
    txn["shadow_decision"] = score_decision(ruleset, score)
    txn["shadow_ruleset_id"] = ruleset["id"]


# ---------------------------------------------------------------------------
# Pagination helper
# ---------------------------------------------------------------------------

def paginate(items: list, limit: int, offset: int) -> tuple[list, dict]:
    total = len(items)
    sliced = items[offset:offset + limit]
    has_more = offset + limit < total
    return sliced, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": has_more,
    }


def parse_pagination_args(args) -> tuple[int, int]:
    try:
        limit = int(args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset
