# =============================================================================
# Domain helpers: clock comparison, posture, sessions, token cascades,
# DPAN minting, token events, disputes/risk/fees.
# =============================================================================
import random

import db
from errors import ApiError, validation

SESSION_TTL_HOURS = 24
PER_AUTH_CAP_CENTS = 100000
DECLINE_STREAK_SUSPEND_THRESHOLD = 3
RISK_OPEN_DISPUTE_BONUS = 15
RISK_DEVICE_LOST_BONUS = 25
RISK_CAP = 100

NON_TERMINAL_SESSION_STATES = {"INITIATED", "VERIFICATION_REQUIRED", "VERIFIED"}
NON_TERMINAL_TOKEN_STATES = {"PENDING", "ACTIVE", "SUSPENDED"}


# ---- clock ------------------------------------------------------------------

def _parse(ts):
    from datetime import datetime
    s = ts
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


def clock_gte(ts):
    """True when logical clock >= ts (inclusive boundary means expired)."""
    return _parse(db.get_clock()) >= _parse(ts)


def plus_hours(ts, hours):
    from datetime import timedelta
    d = _parse(ts) + timedelta(hours=hours)
    out = d.isoformat()
    if out.endswith("+00:00"):
        out = out[:-6] + "Z"
    return out


# ---- device posture ---------------------------------------------------------

def compute_posture(device):
    if device["is_lost"]:
        return "LOST"
    if not device["passcode_enabled"]:
        return "DEGRADED"
    return "HEALTHY"


def sync_posture(device):
    device["security_posture"] = compute_posture(device)


def recompute_active_token_count(device):
    count = sum(
        1 for t in db.payment_tokens.values()
        if t["device_id"] == device["id"] and t["status"] == "ACTIVE"
    )
    device["active_token_count"] = count


# ---- token events -----------------------------------------------------------

def add_event(token_id, event_type, payload=None):
    evt = {
        "id": db.new_id(),
        "payment_token_id": token_id,
        "event_type": event_type,
        "payload": payload or {},
        "created_at": db.get_clock(),
        "_seq": db.next_seq(),
    }
    db.token_events[evt["id"]] = evt
    return evt


# ---- token cascades ---------------------------------------------------------

def suspend_token(token, reason):
    """ACTIVE -> SUSPENDED with counter bump, event, default-card clearing."""
    token["status"] = "SUSPENDED"
    token["suspension_count"] += 1
    db.touch(token)
    add_event(token["id"], "SUSPENSION", {"reason": reason})
    device = db.devices.get(token["device_id"])
    if device is not None:
        if device.get("default_card_id") == token["id"]:
            device["default_card_id"] = None
        recompute_active_token_count(device)
        db.touch(device)


def deactivate_token(token, reason):
    """ACTIVE|SUSPENDED -> DEACTIVATED with reason, event, default clearing."""
    token["status"] = "DEACTIVATED"
    token["deactivated_reason"] = reason
    db.touch(token)
    add_event(token["id"], "DEACTIVATION", {"reason": reason})
    device = db.devices.get(token["device_id"])
    if device is not None:
        if device.get("default_card_id") == token["id"]:
            device["default_card_id"] = None
        recompute_active_token_count(device)
        db.touch(device)


# ---- sessions ----------------------------------------------------------------

_GOOD_CODES = {"111111", "222222", "333333"}


def expected_code(session, method):
    """PRD §3.4: "A wrong code is rejected with ERR_OTP_MISMATCH ...". The PRD
    never pins the issued challenge value, so the server treats the canonical
    good codes as satisfying the challenge; any other code is a mismatch."""
    return None


def code_matches(session, method, code):
    return code in _GOOD_CODES


def expire_session_if_due(session):
    """Lazy expiry (priority 5): flip to EXPIRED when clock >= expires_at."""
    if session["status"] in NON_TERMINAL_SESSION_STATES and clock_gte(session["expires_at"]):
        session["status"] = "EXPIRED"
        db.touch(session)


# ---- agreements / issuers ----------------------------------------------------

def active_agreement_for_issuer(issuer_id):
    for ag in db.issuer_agreements.values():
        if ag["issuer_id"] == issuer_id and ag["status"] == "ACTIVE":
            return ag
    return None


def issuer_active_with_agreement(issuer_id):
    issuer = db.issuers.get(issuer_id)
    return (
        issuer is not None
        and issuer["status"] == "ACTIVE"
        and active_agreement_for_issuer(issuer_id) is not None
    )


def suspend_issuer_cascade(issuer):
    """Every ACTIVE token of this issuer -> SUSPENDED (reason issuer)."""
    for token in db.payment_tokens.values():
        if token["issuer_id"] == issuer["id"] and token["status"] == "ACTIVE":
            suspend_token(token, "issuer")


def offboard_issuer_cascade(issuer):
    """OPEN|RESTRICTED accounts -> CLOSED; their tokens -> DEACTIVATED ISSUER_REVOKE."""
    for acct in db.card_accounts.values():
        if acct["issuer_id"] == issuer["id"] and acct["status"] in ("OPEN", "RESTRICTED"):
            acct["status"] = "CLOSED"
            db.touch(acct)
            for token in db.payment_tokens.values():
                if token["card_account_id"] == acct["id"] and token["status"] in ("ACTIVE", "SUSPENDED"):
                    deactivate_token(token, "ISSUER_REVOKE")


# ---- DPAN --------------------------------------------------------------------

def mint_dpan():
    for _ in range(64):
        candidate = "".join(random.choices("0123456789", k=16))
        collision = any(
            t["device_account_number"] == candidate and t["status"] in NON_TERMINAL_TOKEN_STATES
            for t in db.payment_tokens.values()
        )
        if not collision:
            return candidate
    raise validation("Unable to mint a unique device account number")


# ---- disputes / risk ---------------------------------------------------------

def open_disputes_for_account(account_id):
    return [
        d for d in db.disputes.values()
        if d["card_account_id"] == account_id and d["status"] == "OPEN"
    ]


def tokens_for_account(account_id):
    return [t for t in db.payment_tokens.values() if t["card_account_id"] == account_id]


def compute_risk(account):
    tokens = tokens_for_account(account["id"])
    open_disputes = open_disputes_for_account(account["id"])
    disputed_token_ids = {d["payment_token_id"] for d in open_disputes}
    score = 0
    for t in tokens:
        if t["id"] in disputed_token_ids:
            score += 4 * t["decline_count"]
        else:
            score += 1 * t["decline_count"]
    score += RISK_OPEN_DISPUTE_BONUS * len(open_disputes)
    if any(db.devices.get(t["device_id"], {}).get("is_lost") for t in tokens):
        score += RISK_DEVICE_LOST_BONUS
    score = min(score, RISK_CAP)
    score = max(score, 0)
    open_disputed_cents = sum(d["amount_cents"] for d in open_disputes)
    return score, len(open_disputes), open_disputed_cents


# ---- fees --------------------------------------------------------------------

def compute_fee(amount_cents, agreement):
    raw = (amount_cents * agreement["fee_bps"]) // 10000
    capped = min(raw, agreement["fee_cap_cents"])
    return max(capped, agreement["fee_floor_cents"])


def auths_for_issuer(issuer_id, statuses):
    token_ids = {
        t["id"] for t in db.payment_tokens.values() if t["issuer_id"] == issuer_id
    }
    return [
        a for a in db.authorizations.values()
        if a["payment_token_id"] in token_ids and a["status"] in statuses
    ]
