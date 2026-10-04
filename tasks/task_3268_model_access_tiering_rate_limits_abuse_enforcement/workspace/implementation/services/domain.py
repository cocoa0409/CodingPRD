"""Domain services: tier progression, rate limiting, clock-driven transitions,
abuse cascade helpers, and invoice arithmetic."""
from __future__ import annotations

import math
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import db

# --- tier thresholds ---
TIER_2_SPEND = 5_000_000
TIER_2_COUNT = 5
TIER_3_SPEND = 25_000_000
TIER_3_COUNT = 25
TIER_4_SPEND = 100_000_000
TIER_4_COUNT = 100
MIN_QUALIFYING_PAYMENT_CENTS = 1000

# --- rate limit constants ---
BURST_MULTIPLIER = 2
AVG_TOKENS_PER_REQUEST = 1000
THROTTLE_FACTOR = Decimal("0.25")
QUEUE_TTL_SECONDS = 120
QUEUE_MAX_DEPTH = 100

TIER_CAPS = {
    "TIER_1": (50, 50_000),
    "TIER_2": (200, 200_000),
    "TIER_3": (1000, 1_000_000),
    "TIER_4": (4000, 4_000_000),
}

MIGRATION_WINDOW_DAYS = 30
LOOKBACK_DAYS = 30

AUTO_ACTION_THRESHOLD = 0.95
BATCH_DISCOUNT_PCT = Decimal("0.5")

ACTION_RANK = {"WARN": 1, "THROTTLE": 2, "RESTRICT": 3, "SUSPEND": 3, "TERMINATE": 4}
SEVERITY_RANK = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}

PASS_THRESHOLDS = {"STANDARD": 0.70, "ELEVATED": 0.70, "FRONTIER": 0.90}


# ---------------------------------------------------------------------------
# Tier progression
# ---------------------------------------------------------------------------

def recompute_tier(org: dict) -> str:
    """Settled-only tier progression; ENTERPRISE if an ACTIVE agreement exists."""
    active_agreement = _active_agreement_for(org["id"])
    if active_agreement is not None:
        org["tier"] = "ENTERPRISE"
        return org["tier"]
    spend = org["lifetime_spend_cents"]
    count = org["qualifying_payment_count"]
    if spend >= TIER_4_SPEND and count >= TIER_4_COUNT:
        org["tier"] = "TIER_4"
    elif spend >= TIER_3_SPEND and count >= TIER_3_COUNT:
        org["tier"] = "TIER_3"
    elif spend >= TIER_2_SPEND and count >= TIER_2_COUNT:
        org["tier"] = "TIER_2"
    else:
        org["tier"] = "TIER_1"
    return org["tier"]


def preview_tier(org: dict) -> str:
    """Forward-looking projection: counts PENDING payments as if settled."""
    if _active_agreement_for(org["id"]) is not None:
        return "ENTERPRISE"
    spend = org["lifetime_spend_cents"]
    count = org["qualifying_payment_count"]
    for p in db.payment_events.values():
        if p["organization_id"] == org["id"] and p["status"] == "PENDING":
            spend += p["amount_cents"]
            if p["amount_cents"] >= MIN_QUALIFYING_PAYMENT_CENTS:
                count += 1
    if spend >= TIER_4_SPEND and count >= TIER_4_COUNT:
        return "TIER_4"
    if spend >= TIER_3_SPEND and count >= TIER_3_COUNT:
        return "TIER_3"
    if spend >= TIER_2_SPEND and count >= TIER_2_COUNT:
        return "TIER_2"
    return "TIER_1"


def _active_agreement_for(org_id: str):
    for a in db.enterprise_agreements.values():
        if a["organization_id"] == org_id and a["status"] == "ACTIVE":
            return a
    return None


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

def is_throttled(org_id: str) -> bool:
    """True if any ACTIONED case for the org has an unrevoked THROTTLE action."""
    for case in db.abuse_cases.values():
        if case["organization_id"] != org_id:
            continue
        if case["status"] != "ACTIONED":
            continue
        for action in db.abuse_actions.values():
            if (action["abuse_case_id"] == case["id"]
                    and action["action_type"] == "THROTTLE"
                    and action["revoked_at"] is None):
                return True
    return False


def effective_caps(org: dict) -> tuple[int, int]:
    """Effective (rpm, tpm) for the organization after tier, enterprise, throttle."""
    active_agreement = _active_agreement_for(org["id"])
    if org["tier"] == "ENTERPRISE" and active_agreement is not None:
        tpm = active_agreement["committed_tpm"]
        rpm = math.ceil(tpm / AVG_TOKENS_PER_REQUEST)
    else:
        rpm, tpm = TIER_CAPS.get(org["tier"], TIER_CAPS["TIER_1"])
    if is_throttled(org["id"]):
        rpm = max(1, math.floor(rpm * float(THROTTLE_FACTOR)))
        tpm = max(1, math.floor(tpm * float(THROTTLE_FACTOR)))
    return rpm, tpm


def get_or_create_window(org_id: str, model_version_id: str, window_start_iso: str) -> dict:
    key = (org_id, model_version_id, window_start_iso)
    wid = db.window_index.get(key)
    if wid is not None:
        return db.rate_limit_windows[wid]
    import uuid
    window = {
        "id": uuid.uuid4().hex,
        "organization_id": org_id,
        "model_version_id": model_version_id,
        "window_start": window_start_iso,
        "requests_used": 0,
        "tokens_used": 0,
        "burst_credits_used": 0,
        "created_at": window_start_iso,
    }
    db.rate_limit_windows[window["id"]] = window
    db.window_index[key] = window["id"]
    return window


def admit(org: dict, model_version_id: str, window_start_iso: str,
          requests_cost: int, tokens_cost: int) -> dict:
    """Apply the admission test for the window; mutate counters; return window.

    Raises nothing — callers check the boolean return.
    Returns (admitted: bool, window: dict).
    """
    rpm, tpm = effective_caps(org)
    window = get_or_create_window(org["id"], model_version_id, window_start_iso)
    if (window["requests_used"] + requests_cost <= rpm
            and window["tokens_used"] + tokens_cost <= tpm):
        window["requests_used"] += requests_cost
        window["tokens_used"] += tokens_cost
        return True, window
    # Burst: each credit covers 1 request slot OR 1 token slot, so the
    # overage in the larger dimension alone determines the credits needed.
    burst_pool = BURST_MULTIPLIER * rpm
    remaining = burst_pool - window["burst_credits_used"]
    need = 0
    if window["requests_used"] + requests_cost > rpm:
        need = max(need, (window["requests_used"] + requests_cost) - rpm)
    if window["tokens_used"] + tokens_cost > tpm:
        need = max(need, (window["tokens_used"] + tokens_cost) - tpm)
    if need > 0 and remaining >= need:
        window["burst_credits_used"] += need
        window["requests_used"] += requests_cost
        window["tokens_used"] += tokens_cost
        return True, window
    return False, window


def queue_depth(org_id: str, model_version_id: str) -> int:
    n = 0
    for q in db.queued_requests.values():
        if (q["organization_id"] == org_id
                and q["model_version_id"] == model_version_id
                and q["status"] == "QUEUED"):
            n += 1
    return n


# ---------------------------------------------------------------------------
# Invoice arithmetic
# ---------------------------------------------------------------------------

def round_half_up_cents(numerator: int, denominator: int = 1_000_000) -> int:
    val = Decimal(numerator) / Decimal(denominator)
    return int(val.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def finalize_invoice(invoice: dict, org: dict) -> None:
    lines = [l for l in db.invoice_lines.values() if l["invoice_id"] == invoice["id"]]
    subtotal = 0
    batch_sum = 0
    for line in lines:
        amount = round_half_up_cents(line["quantity"] * line["rate_per_mtok_cents"])
        line["amount_cents"] = amount
        subtotal += amount
        if line.get("batch"):
            batch_sum += amount
    discount = int((Decimal(batch_sum) * BATCH_DISCOUNT_PCT).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    total = max(0, subtotal - discount)
    invoice["subtotal_cents"] = subtotal
    invoice["batch_discount_cents"] = discount
    invoice["total_cents"] = total
    debit = min(total, org["credit_balance_cents"])
    org["credit_balance_cents"] -= debit
    if org["credit_balance_cents"] < 0:  # pragma: no cover - defensive
        from errors import insufficient_credit
        raise insufficient_credit()
    invoice["status"] = "FINALIZED"


# ---------------------------------------------------------------------------
# Migration-window / model availability
# ---------------------------------------------------------------------------

def check_model_available(org: dict, model: dict) -> bool:
    """True when usage may be recorded against the model version by this org."""
    if model["status"] in ("ACTIVE", "DRAFT", "GATED"):
        # §3.3 rejects usage only for SUNSET versions and for DEPRECATED
        # versions consumed by an unpinned organization without recent usage.
        return True
    if org.get("pinned_model_version_id") == model["id"]:
        return True
    if model["status"] == "SUNSET":
        return False
    if model["status"] == "DEPRECATED":
        # unpinned orgs need recent usage in the trailing 30 days before deprecation
        announced = model.get("deprecation_announced_at")
        if not announced:
            return False
        try:
            announced_dt = db.parse_iso(announced)
        except Exception:
            return False
        cutoff = announced_dt - timedelta(days=LOOKBACK_DAYS)
        for u in db.usage_records.values():
            if u["organization_id"] != org["id"] or u["model_version_id"] != model["id"]:
                continue
            try:
                ts = db.parse_iso(u["minute_window_start"])
            except Exception:
                continue
            if cutoff <= ts:
                return True
        return False
    return False


# ---------------------------------------------------------------------------
# Clock-driven transitions
# ---------------------------------------------------------------------------

def run_clock_transitions() -> None:
    """Re-evaluate time-driven auto-transitions against the logical clock.

    Order: queue TTL expiry -> agreement expiry -> model sunset -> queue admission.
    """
    now = db.now()

    # 1. Queue TTL expiry
    for q in db.queued_requests.values():
        if q["status"] != "QUEUED":
            continue
        enq = db.parse_iso(q["enqueued_at"])
        if now >= enq + timedelta(seconds=QUEUE_TTL_SECONDS):
            q["status"] = "EXPIRED"
            q["updated_at"] = db.fmt_clock(now)
            q["version"] = q.get("version", 1) + 1

    # 2. Agreement expiry
    for a in db.enterprise_agreements.values():
        if a["status"] != "ACTIVE":
            continue
        expires = db.parse_iso(a["expires_at"])
        if now >= expires:
            a["status"] = "EXPIRED"
            a["updated_at"] = db.fmt_clock(now)
            a["version"] = a.get("version", 1) + 1
            org = db.organizations.get(a["organization_id"])
            if org is not None and org.get("enterprise_agreement_id") == a["id"]:
                org["enterprise_agreement_id"] = None
                recompute_tier(org)
                org["version"] = org.get("version", 1) + 1
                org["updated_at"] = db.fmt_clock(now)

    # 3. Model sunset
    for m in db.model_versions.values():
        if m["status"] != "DEPRECATED":
            continue
        sunset = m.get("sunset_at")
        if not sunset:
            continue
        if now >= db.parse_iso(sunset):
            m["status"] = "SUNSET"
            m["updated_at"] = db.fmt_clock(now)
            m["version"] = m.get("version", 1) + 1

    # 4. Queue admission at each minute boundary crossed.
    # A new window opens for the minute containing `now`; the head-of-line
    # item — the oldest by enqueued_at — is admitted if the target window
    # has residual capacity covering its declared costs (PRD §2.8).
    minute_start = now.replace(second=0, microsecond=0)
    window_start_iso = db.fmt_clock(minute_start)
    # Group queued items per (org, model)
    queues: dict[tuple, list] = {}
    for q in db.queued_requests.values():
        if q["status"] == "QUEUED":
            queues.setdefault((q["organization_id"], q["model_version_id"]), []).append(q)
    for (org_id, mv_id), items in queues.items():
        # Oldest by enqueued_at; ties fall back to insertion order (dict order)
        # rather than random id, per PRD §2.8 "oldest by enqueued_at ascending".
        items.sort(key=lambda x: db.parse_iso(x["enqueued_at"]))
        org = db.organizations.get(org_id)
        if org is None:
            continue
        if org["status"] in ("RESTRICTED", "SUSPENDED", "TERMINATED"):
            continue
        if not items:
            continue
        head = items[0]
        admitted, window = admit(org, mv_id, window_start_iso,
                                 head["requests_cost"], head["tokens_cost"])
        if admitted:
            head["status"] = "ADMITTED"
            head["updated_at"] = db.fmt_clock(now)
            head["version"] = head.get("version", 1) + 1


# ---------------------------------------------------------------------------
# Abuse cascades
# ---------------------------------------------------------------------------

def drop_queued_requests(org_id: str) -> None:
    now = db.now()
    for q in db.queued_requests.values():
        if q["organization_id"] == org_id and q["status"] == "QUEUED":
            q["status"] = "DROPPED"
            q["updated_at"] = db.fmt_clock(now)
            q["version"] = q.get("version", 1) + 1


def terminate_agreements(org_id: str, statuses: set[str]) -> None:
    now = db.now()
    for a in db.enterprise_agreements.values():
        if a["organization_id"] == org_id and a["status"] in statuses:
            a["status"] = "TERMINATED"
            a["updated_at"] = db.fmt_clock(now)
            a["version"] = a.get("version", 1) + 1
    org = db.organizations.get(org_id)
    if org is not None and org.get("enterprise_agreement_id"):
        org["enterprise_agreement_id"] = None
        recompute_tier(org)
