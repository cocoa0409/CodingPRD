"""Core business logic: entities, state machines, calculations."""
import math
import uuid

import db
import errors

SECONDS_PER_DAY = 86400
FAMILY_DISCOUNT_BPS = 2500
RENEWAL_DISCLOSURE_LEAD_DAYS = 15
CELLULAR_RETRY_BASE_MINUTES = 15
SATELLITE_RETRY_BASE_MINUTES = 60
MAX_ATTEMPTS = 3
HW_ORDER = {"GEN1": 1, "GEN2": 2, "GEN3": 3}
PAID_KINDS = ("PAID", "SAVE_OFFER")
PAID_STATUSES = ("ACTIVE", "SUSPENDED", "CANCEL_SCHEDULED")
TERMINAL_SUB_STATUSES = ("CANCELLED", "EXPIRED", "TRANSFERRED_AWAY")


def new_id():
    return str(uuid.uuid4())


def now():
    return db.get_now()


def make_common(e):
    ts = now()
    e.setdefault("created_at", ts)
    e["updated_at"] = ts
    e["version"] = 1
    return e


def touch(e):
    e["updated_at"] = now()
    e["version"] = e.get("version", 0) + 1


def find_by(store, key, value):
    for e in store.values():
        if e.get(key) == value:
            return e
    return None


def ensure_unique(store, key, value, msg):
    if find_by(store, key, value) is not None:
        raise errors.duplicate(msg)


# ---------------------------------------------------------------- signals

def signal_path_for(radio):
    return "CELLULAR" if radio["hardware_generation"] in ("GEN2", "GEN3") else "SATELLITE"


def retry_base_minutes(path):
    return CELLULAR_RETRY_BASE_MINUTES if path == "CELLULAR" else SATELLITE_RETRY_BASE_MINUTES


def is_contradiction(a, b):
    return a != b


def apply_supersession(new_cmd):
    radio_id = new_cmd["radio_id"]
    for c in db.signal_commands.values():
        if c["id"] == new_cmd["id"]:
            continue
        if c["radio_id"] != radio_id:
            continue
        if c["status"] not in ("QUEUED", "SENT"):
            continue
        if c["created_at"] > new_cmd["created_at"]:
            continue
        if is_contradiction(c["command_type"], new_cmd["command_type"]):
            c["status"] = "SUPERSEDED"
            touch(c)


def enqueue_signal(radio_id, subscription_id, command_type, idem_key=None):
    radio = db.radios[radio_id]
    cmd = {
        "id": new_id(),
        "radio_id": radio_id,
        "subscription_id": subscription_id,
        "command_type": command_type,
        "path": signal_path_for(radio),
        "status": "QUEUED",
        "attempt_count": 0,
        "next_retry_at": None,
        "idempotency_key": idem_key,
        "_seq": db.next_seq(),
    }
    make_common(cmd)
    db.signal_commands[cmd["id"]] = cmd
    apply_supersession(cmd)
    return cmd


def radio_has_other_nonterminal_sub(radio_id, exclude_sub_id=None):
    for s in db.subscriptions.values():
        if s["radio_id"] != radio_id:
            continue
        if exclude_sub_id and s["id"] == exclude_sub_id:
            continue
        if s["status"] not in TERMINAL_SUB_STATUSES:
            return True
    return False


def radio_has_other_live_sub(radio_id, exclude_sub_id=None):
    """True when another subscription with live service (ACTIVE or SUSPENDED)
    references the radio. PENDING_ACTIVATION subscriptions have not been
    activated yet, so they do not hold service."""
    for s in db.subscriptions.values():
        if s["radio_id"] != radio_id:
            continue
        if exclude_sub_id and s["id"] == exclude_sub_id:
            continue
        if s["status"] in ("ACTIVE", "SUSPENDED"):
            return True
    return False


def radio_has_other_active_or_pending(radio_id, exclude_sub_id=None):
    for s in db.subscriptions.values():
        if s["radio_id"] != radio_id:
            continue
        if exclude_sub_id and s["id"] == exclude_sub_id:
            continue
        if s["status"] in ("ACTIVE", "PENDING_ACTIVATION"):
            return True
    return False


def dispatch_signal(cmd):
    """QUEUED -> SENT, attempt_count += 1."""
    if cmd["status"] != "QUEUED":
        raise errors.invalid_state("signal not QUEUED")
    cmd["status"] = "SENT"
    cmd["attempt_count"] += 1
    cmd["next_retry_at"] = None
    touch(cmd)


def _recompute_disclosure_state(sub):
    """State machine for disclosure_state computed from records."""
    if sub["disclosure_state"] == "REQUIRED":
        # check if matching record exists (sent) and if all acknowledged
        need = "SAVE_RENEWAL_NOTICE" if sub["kind"] == "SAVE_OFFER" else "RENEWAL_NOTICE"
        recs = [d for d in db.disclosures.values()
                if d["subscription_id"] == sub["id"] and d["disclosure_type"] == need]
        if recs:
            if all(r["acknowledged_at"] is not None for r in recs):
                sub["disclosure_state"] = "ACKNOWLEDGED"
            else:
                sub["disclosure_state"] = "SENT"


def apply_signal_effect(cmd):
    """On ACK: apply to radio and subscription."""
    ts = now()
    radio = db.radios[cmd["radio_id"]]
    sub = db.subscriptions.get(cmd["subscription_id"])
    ct = cmd["command_type"]
    radio_changed = False
    if ct == "ACTIVATE":
        if radio["activation_status"] in ("UNREGISTERED", "DEACTIVATED"):
            radio["activation_status"] = "REGISTERED"
            radio_changed = True
        radio["last_signal_at"] = ts
        if not radio_changed:
            touch(radio)
        else:
            touch(radio)
        if sub is not None and sub["status"] == "PENDING_ACTIVATION" and sub["start_at"] <= ts:
            sub["status"] = "ACTIVE"
            plan = db.plans[sub["plan_id"]]
            if sub["kind"] == "PAID" and sub["auto_renew"]:
                sub["disclosure_state"] = "REQUIRED"
            touch(sub)
            recompute_family(sub["customer_id"])
    elif ct == "SUSPEND":
        if not radio_has_other_active_or_pending(radio["id"], exclude_sub_id=cmd["subscription_id"]):
            if radio["activation_status"] == "REGISTERED":
                radio["activation_status"] = "SUSPENDED"
                touch(radio)
        radio["last_signal_at"] = ts
        touch(radio)
    elif ct == "RESUME":
        if radio["activation_status"] == "SUSPENDED":
            radio["activation_status"] = "REGISTERED"
            touch(radio)
        radio["last_signal_at"] = ts
        touch(radio)
    elif ct == "DEACTIVATE":
        # Deactivate once no surviving subscription holds live service on the
        # radio (ACTIVE/SUSPENDED). A fresh PENDING_ACTIVATION trial created
        # by the same transfer does not block deactivation — PRD §3.10 has
        # the radio cycle DEACTIVATED -> REGISTERED across owners.
        if not radio_has_other_live_sub(radio["id"], exclude_sub_id=cmd["subscription_id"]):
            if radio["activation_status"] in ("REGISTERED", "SUSPENDED"):
                radio["activation_status"] = "DEACTIVATED"
                touch(radio)
        radio["last_signal_at"] = ts
        touch(radio)


def ack_signal(cmd):
    if cmd["status"] != "SENT":
        raise errors.invalid_state("signal not SENT")
    cmd["status"] = "ACKED"
    touch(cmd)
    apply_signal_effect(cmd)


def fail_signal(cmd):
    if cmd["status"] != "SENT":
        raise errors.invalid_state("signal not SENT")
    cmd["status"] = "FAILED"
    touch(cmd)
    if cmd["attempt_count"] < MAX_ATTEMPTS:
        cmd["status"] = "QUEUED"
        base = retry_base_minutes(cmd["path"])
        cmd["next_retry_at"] = now() + cmd["attempt_count"] * base * 60
        touch(cmd)
    else:
        cmd["status"] = "EXHAUSTED"
        touch(cmd)


def has_exhausted_signal(subscription_id):
    for c in db.signal_commands.values():
        if (c["subscription_id"] == subscription_id
                and c["status"] == "EXHAUSTED"
                and not c.get("block_cleared")):
            return True
    return False


# ---------------------------------------------------------------- pricing

def _is_paid_candidate(s):
    return s["kind"] in PAID_KINDS and s["status"] in PAID_STATUSES


def compute_term_price(customer_id, plan, offer_step, is_primary):
    """term_pricing: base -> offer (floor pct, then flat, floor at 0) -> family (ceil)."""
    base = int(plan["price_cents"])
    offer_discount = 0
    if offer_step is not None:
        pct = math.floor(base * int(offer_step["discount_pct_bps"]) / 10000)
        offer_discount = pct + int(offer_step["flat_discount_cents"])
        if offer_discount > base:
            offer_discount = base
    after_offer = base - offer_discount
    if after_offer < 0:
        after_offer = 0
    family_discount = 0
    if not is_primary:
        cust = db.customers.get(customer_id)
        hh = cust["household_size"] if cust else 1
        if hh >= 2:
            # anchor must be ACTIVE/SUSPENDED paid
            anchor = find_anchor(customer_id)
            if anchor is not None and anchor["status"] in ("ACTIVE", "SUSPENDED"):
                family_discount = math.ceil(after_offer * FAMILY_DISCOUNT_BPS / 10000)
    price = after_offer - family_discount
    if price < 0:
        price = 0
    return price


def find_anchor(customer_id):
    cands = [s for s in db.subscriptions.values()
             if s["customer_id"] == customer_id and _is_paid_candidate(s)]
    if not cands:
        return None
    def key(s):
        plan = db.plans[s["plan_id"]]
        return (-int(plan["price_cents"]), s["created_at"])
    cands.sort(key=key)
    return cands[0]


def recompute_family(customer_id):
    cands = [s for s in db.subscriptions.values()
             if s["customer_id"] == customer_id and _is_paid_candidate(s)]
    anchor = find_anchor(customer_id)
    for s in cands:
        is_primary = (anchor is not None and s["id"] == anchor["id"])
        dirty = False
        if s["is_primary_for_discount"] != is_primary:
            s["is_primary_for_discount"] = is_primary
            dirty = True
        plan = db.plans[s["plan_id"]]
        # Save-offer subs keep their save pricing (recomputed at accept); do not re-derive here
        if s["kind"] != "SAVE_OFFER":
            red = None
            for r in db.redemptions.values():
                if r["subscription_id"] == s["id"]:
                    red = r
                    break
            step = db.offer_steps.get(red["offer_step_id"]) if red else None
            new_price = compute_term_price(customer_id, plan, step, is_primary)
            if new_price != s["current_term_price_cents"]:
                s["current_term_price_cents"] = new_price
                dirty = True
        if dirty:
            touch(s)


# ---------------------------------------------------------------- ledger

def post_ledger(subscription_id, entry_type, amount_cents, note="", idem_key=None):
    if idem_key is not None:
        existing = find_by(db.ledger_entries, "idempotency_key", idem_key)
        if existing is not None:
            return existing
    e = {
        "id": new_id(),
        "subscription_id": subscription_id,
        "entry_type": entry_type,
        "amount_cents": int(amount_cents),
        "effective_at": now(),
        "idempotency_key": idem_key,
        "note": note,
        "created_at": now(),
    }
    db.ledger_entries[e["id"]] = e
    return e


# ---------------------------------------------------------------- subscriptions

def create_subscription(customer_id, plan, radio_id, kind, origin, auto_renew=None,
                        offer_step=None, status_pending=True):
    ts = now()
    cust = db.customers.get(customer_id)
    if cust is None:
        raise errors.reference_not_found("customer_id does not resolve")
    term_days = int(plan["term_length_days"])
    sub = {
        "id": new_id(),
        "customer_id": customer_id,
        "radio_id": radio_id,
        "plan_id": plan["id"],
        "kind": kind,
        "status": "PENDING_ACTIVATION",
        "origin": origin,
        "start_at": ts,
        "end_at": ts + term_days * SECONDS_PER_DAY,
        "auto_renew": bool(auto_renew) if auto_renew is not None else bool(plan["auto_renew_default"]),
        "is_primary_for_discount": False,
        "current_term_price_cents": 0,
        "disclosure_state": "NONE",
        "save_offers_used_in_term": 0,
        "cancel_requested_at": None,
        "supersession_seq": 0,
    }
    make_common(sub)
    # supersession_seq: count existing subs with same (radio_id, customer_id)
    if radio_id is not None:
        count = sum(1 for s in db.subscriptions.values()
                    if s["radio_id"] == radio_id and s["customer_id"] == customer_id)
        sub["supersession_seq"] = count
    db.subscriptions[sub["id"]] = sub

    # Establish family anchor BEFORE initial price so family discount applies
    if kind in PAID_KINDS:
        anchor = find_anchor(customer_id)
        for s in db.subscriptions.values():
            if s["customer_id"] == customer_id and _is_paid_candidate(s):
                s["is_primary_for_discount"] = (anchor is not None and s["id"] == anchor["id"])
        is_primary = sub["is_primary_for_discount"]
        sub["current_term_price_cents"] = compute_term_price(customer_id, plan, offer_step, is_primary)
        post_ledger(sub["id"], "CHARGE", sub["current_term_price_cents"], note="subscription charge")
        if sub["auto_renew"]:
            sub["disclosure_state"] = "REQUIRED"

    # Streaming-only activates immediately
    if plan["service_mode"] == "STREAMING_ONLY":
        if sub["start_at"] <= ts:
            sub["status"] = "ACTIVE"

    # Signal for radio-backed subs
    if radio_id is not None:
        enqueue_signal(radio_id, sub["id"], "ACTIVATE")

    if kind in PAID_KINDS:
        recompute_family(customer_id)
    return sub


def subscription_refund_cents(sub):
    plan = db.plans[sub["plan_id"]]
    unused_seconds = sub["end_at"] - now()
    if unused_seconds <= 0:
        unused_days = 0
    else:
        unused_days = math.floor(unused_seconds / SECONDS_PER_DAY)
    term_days = int(plan["term_length_days"])
    if term_days <= 0:
        return 0
    return math.floor(int(sub["current_term_price_cents"]) * unused_days / term_days)


def _cancel_common_terminal(sub):
    """Side effects shared by cancel/finalize/expire paths."""
    if sub["radio_id"] is not None:
        enqueue_signal(sub["radio_id"], sub["id"], "DEACTIVATE")
    recompute_family(sub["customer_id"])


def cancel_immediate(sub):
    """Transition to CANCELLED from PENDING_ACTIVATION / ACTIVE / SUSPENDED."""
    refund = subscription_refund_cents(sub)
    if sub["kind"] in PAID_KINDS:
        post_ledger(sub["id"], "PRORATION_CREDIT", -refund, note="immediate cancel proration")
    sub["status"] = "CANCELLED"
    touch(sub)
    _cancel_common_terminal(sub)


def cancel_end_of_term(sub):
    sub["status"] = "CANCEL_SCHEDULED"
    sub["cancel_requested_at"] = now()
    sub["auto_renew"] = False
    touch(sub)


def finalize_cancel(sub):
    sub["status"] = "CANCELLED"
    touch(sub)
    _cancel_common_terminal(sub)


def expire_sub(sub):
    sub["status"] = "EXPIRED"
    touch(sub)
    _cancel_common_terminal(sub)


def run_renewals():
    ts = now()
    expired = renewed = blocked = finalized = 0
    for sub in list(db.subscriptions.values()):
        if sub["status"] == "CANCEL_SCHEDULED" and sub["end_at"] <= ts:
            finalize_cancel(sub)
            finalized += 1
    for sub in list(db.subscriptions.values()):
        if sub["status"] != "ACTIVE":
            continue
        if sub["end_at"] > ts:
            continue
        if sub["kind"] == "TRIAL" or not sub["auto_renew"]:
            expire_sub(sub)
            expired += 1
            continue
        # auto-renew paid/save sub: disclosure gate
        need = "SAVE_RENEWAL_NOTICE" if sub["kind"] == "SAVE_OFFER" else "RENEWAL_NOTICE"
        lead = RENEWAL_DISCLOSURE_LEAD_DAYS * SECONDS_PER_DAY
        ok = False
        late_but_present = False
        for d in db.disclosures.values():
            if d["subscription_id"] == sub["id"] and d["disclosure_type"] == need:
                if d["sent_at"] <= sub["end_at"] - lead:
                    ok = True
                    break
                late_but_present = True
        # Limbo exit (PRD §3.8): a subscription left ACTIVE past its end_at in
        # regulatory limbo stays there "until the disclosure is sent and a
        # later billing run picks it up" — once strictly past end_at, a
        # disclosure that missed the 15-day lead still lets a later batch
        # renew. At end_at itself the timely-disclosure rule governs.
        if not ok and late_but_present and ts > sub["end_at"]:
            ok = True
        if not ok:
            sub["disclosure_state"] = "REQUIRED"
            touch(sub)
            blocked += 1
            continue
        # renew in place
        plan = db.plans[sub["plan_id"]]
        old_end = sub["end_at"]
        sub["start_at"] = old_end
        sub["end_at"] = old_end + int(plan["term_length_days"]) * SECONDS_PER_DAY
        # renewal pricing: no offer carry, family carries
        anchor = find_anchor(sub["customer_id"])
        is_primary = anchor is not None and anchor["id"] == sub["id"]
        sub["current_term_price_cents"] = compute_term_price(sub["customer_id"], plan, None, is_primary)
        sub["save_offers_used_in_term"] = 0
        post_ledger(sub["id"], "CHARGE", sub["current_term_price_cents"], note="renewal charge")
        touch(sub)
        renewed += 1
        recompute_family(sub["customer_id"])
    return {
        "expired_count": expired,
        "renewed_count": renewed,
        "disclosure_blocked_count": blocked,
        "cancel_finalized_count": finalized,
    }
