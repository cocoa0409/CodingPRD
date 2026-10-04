"""Calculations (scaffold §1.3, PRD §2.9 / §2.10 / §2.11).

Money is Decimal with ROUND_HALF_UP; credit units are integers.
"""

import math
from decimal import Decimal, ROUND_HALF_UP

from db import db
from services.common import total_pages

# --- constants ----------------------------------------------------------
PAGE_BLOCK = 10
FREE_SIGNERS = 5
SUSPENDED_DOUBLE = 2
TIER_MULTIPLIER = {"STANDARD": Decimal("1.0"), "PRO": Decimal("0.8"),
                   "ENTERPRISE": Decimal("0.5")}

PER_DOC_RATE = Decimal("12.335")

PAGE_BASE = Decimal("1500.00")
DISCOUNT_TIER_1_MAX = 500
DISCOUNT_TIER_2_MAX = 2000
RATE_TIER_1 = Decimal("0.02")
RATE_TIER_2 = Decimal("0.03")
RATE_TIER_3 = Decimal("0.04")

RISK_BASE = {"EMAIL_ACCESS": 10, "ACCESS_CODE": 30, "KBA": 55,
             "ID_DOCUMENT": 80}
FAIL_STEP = 5
ID_BONUS = 15
RISK_CEILING = 100
PEER_STEP = 10
STRONG_LEVELS = ("ACCESS_CODE", "KBA", "ID_DOCUMENT")

RETENTION_SCHEDULE = {"CA": 7, "IL": 5, "TX": 10}
RETENTION_DEFAULT = 3

SIGNER_APPROVER = ("SIGNER", "APPROVER")


def _round2(value):
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def signer_count(envelope_id):
    """Recipients with role SIGNER or APPROVER."""
    return sum(
        1 for r in db.recipients_of(envelope_id) if r["role"] in SIGNER_APPROVER
    )


# --- 1. credit_spend_consumption ----------------------------------------

def credit_spend_consumption(envelope, apply_suspended=True):
    """Integer credit units debited by a send (scaffold §1.3).

    page_overage_units      = ceil(max(0, total_pages - page_allowance) / 10)
    recipient_overage_units = max(0, signer_count - 5)
    base_units              = 1 + page_overage_units + recipient_overage_units
    credit_units            = ceil(base_units * tier_multiplier)
    if status == SUSPENDED: credit_units *= 2

    The `sender_visible_estimate` variant omits the SUSPENDED doubling, so a
    suspended account's estimate is half its actual debit.
    """
    account = db.account(envelope["sender_account_id"])
    if account is None:
        return 0
    pages = total_pages(envelope["id"])
    allowance = int(account["page_allowance"])
    page_overage = max(0, pages - allowance)
    page_units = math.ceil(page_overage / PAGE_BLOCK)
    recipient_units = max(0, signer_count(envelope["id"]) - FREE_SIGNERS)
    base_units = 1 + page_units + recipient_units
    multiplier = TIER_MULTIPLIER.get(account["tier"], Decimal("1.0"))
    units = int(math.ceil(Decimal(base_units) * multiplier))
    if apply_suspended and account["status"] == "SUSPENDED":
        units = units * SUSPENDED_DOUBLE
    return units


def credit_spend_estimate(envelope):
    """The sender-visible estimate: the same arithmetic without the doubling."""
    return credit_spend_consumption(envelope, apply_suspended=False)


# --- 2. envelope_page_fee ------------------------------------------------

def document_order(envelope_id):
    """Chargeable documents ordered by created_at, then name (id is forbidden
    as a tie-break by the scaffold)."""
    docs = [
        d for d in db.documents_of(envelope_id) if not d["is_certificate"]
    ]
    docs.sort(key=lambda d: (d["created_at"], d["name"], d.get("_ord", 0)))
    return docs


def envelope_page_fee(envelope):
    """Per-document page fee (scaffold §1.3).

    free_blocks       = floor(page_allowance / 10)
    per document      = max(0, ceil(page_count / 10) - free_blocks)
    fee              += round_half_up(chargeable_blocks * 12.335, 2)

    Rounded PER DOCUMENT before summing; the sum is never re-rounded.
    """
    account = db.account(envelope["sender_account_id"])
    allowance = int(account["page_allowance"]) if account else 0
    free_blocks = allowance // PAGE_BLOCK
    rows = []
    fee = Decimal("0.00")
    for doc in document_order(envelope["id"]):
        chargeable_blocks = max(
            0, math.ceil(doc["page_count"] / PAGE_BLOCK) - free_blocks
        )
        doc_fee = _round2(Decimal(chargeable_blocks) * PER_DOC_RATE)
        fee += doc_fee
        rows.append(
            {
                "envelope_document_id": doc["id"],
                "name": doc["name"],
                "page_count": doc["page_count"],
                "chargeable_blocks": chargeable_blocks,
                "per_document_fee": str(doc_fee),
            }
        )
    return fee, rows


# --- 3. envelope_fee_quote ----------------------------------------------

def discount_rate(pages):
    """Flat tier on the envelope's total page count (PRD §2.9)."""
    if pages < 100:
        return Decimal("0")
    if pages <= DISCOUNT_TIER_1_MAX:
        return RATE_TIER_1
    if pages <= DISCOUNT_TIER_2_MAX:
        return RATE_TIER_2
    return RATE_TIER_3


def envelope_fee_quote(envelope):
    """Pinned evaluation order (scaffold §1.3):

      1. page_component = envelope_page_fee
      2. subtotal       = 1500.00 + page_component
      3. discount       = round_half_up(subtotal * discount_rate, 2)
      4. total_fee      = subtotal - discount
    """
    pages = total_pages(envelope["id"])
    page_component, _rows = envelope_page_fee(envelope)
    subtotal = PAGE_BASE + page_component
    rate = discount_rate(pages)
    discount = _round2(subtotal * rate)
    total_fee = subtotal - discount
    return {
        "total_pages": pages,
        "page_component": float(page_component),
        "subtotal": float(subtotal),
        "discount": float(discount),
        "total_fee": float(total_fee),
    }


# --- 4. authentication_risk_score ---------------------------------------

def raw_risk_score(recipient):
    base = RISK_BASE.get(recipient["auth_level"], 0)
    raw = base + FAIL_STEP * int(recipient.get("kba_fail_count", 0))
    if recipient.get("identity_verified"):
        raw += ID_BONUS
    return raw


def provisional_risk_score(recipient):
    """Clamped into [0, 100]; carries no peer term."""
    return max(0, min(RISK_CEILING, raw_risk_score(recipient)))


def final_risk_score(recipient):
    """Raw + peer-consensus term, clamped only at the ceiling of 100.

    The peer term counts the OTHER recipients of the same envelope whose
    auth_status is AUTHENTICATED and whose auth_level is ACCESS_CODE or
    stronger.
    """
    raw = raw_risk_score(recipient)
    peers = 0
    for other in db.recipients_of(recipient["envelope_id"]):
        if other["id"] == recipient["id"]:
            continue
        if (
            other["auth_status"] == "AUTHENTICATED"
            and other["auth_level"] in STRONG_LEVELS
        ):
            peers += 1
    return min(RISK_CEILING, raw + PEER_STEP * peers)


def recompute_provisional_scores(envelope_id):
    """Rewrite auth_risk_score for every recipient of an envelope."""
    for recipient in db.recipients_of(envelope_id):
        recipient["auth_risk_score"] = provisional_risk_score(recipient)


# --- 5. audit_chain_hash -------------------------------------------------

def audit_certificate_view(envelope):
    """Replay verification + certificate figures (scaffold §1.3 replay variant).

    Returns (payload, tampered) where `tampered` is True when any stored
    event_hash disagrees with the recomputed value.
    """
    from services.common import compute_event_hash, ordered_events, sha256_hex

    events = ordered_events(envelope["id"])
    prev = None
    tampered = False
    for event in events:
        recomputed = compute_event_hash(event, prev)
        if event["event_hash"] != recomputed:
            tampered = True
        prev = event["event_hash"]
    certificate_hash = (
        sha256_hex("|".join(e["event_hash"] for e in events)) if events else None
    )
    return (
        {
            # PRD §3.6: the hash is recomputed over the ordered event_hash chain
            # on every read, not the value stamped at seal time.
            "certificate_hash": certificate_hash,
            "seal_hash": envelope.get("seal_hash"),
            "event_count": len(events),
        },
        tampered,
    )


# --- 6. retention_expiry -------------------------------------------------

def resolve_retention_years(envelope, policy):
    """GLOBAL uses the policy's own years; ACCOUNT defers to the state schedule."""
    if policy is None:
        return RETENTION_DEFAULT
    if policy["scope"] == "GLOBAL":
        return int(policy["retention_years"])
    account = db.account(envelope["sender_account_id"])
    state_code = (account or {}).get("state_code") or ""
    return RETENTION_SCHEDULE.get(state_code, RETENTION_DEFAULT)


def retention_anchor(envelope):
    """sent_at when it exists, created_at otherwise."""
    from timeutil import parse_iso

    if envelope.get("sent_at"):
        return parse_iso(envelope["sent_at"])
    return parse_iso(envelope["created_at"])


def purge_eligible_at(envelope):
    """anchor + retention_years calendar years + purge_grace_days calendar days,
    pinned to 00:00:00Z (scaffold §1.3)."""
    from timeutil import add_calendar_days, add_calendar_years, at_start_of_day

    policy = db.policy(envelope.get("retention_policy_id"))
    anchor = retention_anchor(envelope)
    if anchor is None:
        return None
    years = resolve_retention_years(envelope, policy)
    eligible = add_calendar_years(anchor, years)
    grace = int((policy or {}).get("purge_grace_days", 0) or 0)
    if grace:
        eligible = add_calendar_days(eligible, grace)
    return at_start_of_day(eligible)


def hold_blocks_purge(envelope, eligible):
    """Retention window [anchor, eligible) vs hold window
    [legal_hold_started_at, legal_hold_until or +inf).

    Adjacency semantics: a hold that starts exactly at `eligible` does not
    block, and one that lapses exactly at `eligible` does not block.
    """
    from timeutil import parse_iso

    if not envelope.get("legal_hold"):
        return False
    if eligible is None:
        return True
    start = parse_iso(envelope.get("legal_hold_started_at"))
    until = parse_iso(envelope.get("legal_hold_until"))
    if start is None:
        return True
    if start >= eligible:
        return False
    if until is not None and until <= eligible:
        return False
    return True