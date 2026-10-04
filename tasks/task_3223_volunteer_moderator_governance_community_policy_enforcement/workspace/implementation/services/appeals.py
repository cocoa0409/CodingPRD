"""Appeals, appeals governance and the watchdog (§1.2 transitions (6) and (8)).

§3.6 contesting a sanction; §3.4 sanction lift/reinstatement.
"""

import db
from db import iso, now, advance, parse_dt, at_least_days
from errors import fail
from services import community as community_svc
from services import content

GROUND_CODES = ("ANALYSIS_ERROR", "MODERATOR_MISCONDUCT")
APPEAL_STATES = ("FILED", "SUBMITTED", "UNDER_WATCH", "GRANTED", "DENIED")

FILING_WINDOW_DAYS = 7
DECISION_DEADLINE_DAYS = 30
WATCHDOG_DAYS = 30
WATCHDOG_REFERRALS = 2


def _evidence_movement(appeal):
    return (appeal.get("new_evidence_url") is not None
            or bool(appeal.get("sanction_misapplication_present")))


def file_appeal(account_id, data):
    sanction = db.find("AccountSanction", data["sanction_id"])
    if sanction is None or sanction["account_id"] != account_id:
        fail("ERR_SANCTION_NOT_FOUND")
    if sanction["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE")
    ground = data["ground_code"]
    if ground not in GROUND_CODES:
        fail("ERR_INVALID_REQUEST", "ground_code is not a recognised value")
    content.ensure_account(account_id)

    record = {
        "community_id": sanction["community_id"],
        "account_id": account_id,
        "sanction_id": sanction["id"],
        "ground_code": ground,
        "new_evidence_url": data.get("new_evidence_url"),
        "sanction_misapplication_present": bool(
            data.get("sanction_misapplication_present", False)),
        "state": "FILED",
        "decision_reason_code": None,
        "filed_at_utc": iso(now()),
        "submitted_at_utc": None,
        "deadline_utc": None,
        "last_referred_at_utc": None,
        "referral_count": 0,
    }
    db.insert("Appeal", record)
    return record


def submit_appeal(appeal, actor):
    if actor.role == "Account" and appeal["account_id"] != actor.user_id:
        fail("ERR_FORBIDDEN_ROLE")
    if appeal["state"] != "FILED":
        fail("ERR_INVALID_STATE")
    sanction = db.find("AccountSanction", appeal["sanction_id"])
    if sanction is None or sanction["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE")
    filed = parse_dt(appeal["filed_at_utc"])
    if now() >= advance(filed, FILING_WINDOW_DAYS):
        fail("ERR_APPEAL_WINDOW_CLOSED")

    appeal["state"] = "SUBMITTED"
    appeal["submitted_at_utc"] = iso(now())
    appeal["deadline_utc"] = iso(advance(now(), DECISION_DEADLINE_DAYS))
    db.touch(appeal)
    return appeal


def refer_appeal(appeal, note=None):
    state = appeal["state"]
    if state == "SUBMITTED":
        appeal["state"] = "UNDER_WATCH"
    elif state == "UNDER_WATCH":
        appeal["state"] = "SUBMITTED"
    else:
        fail("ERR_INVALID_STATE")
    appeal["last_referred_at_utc"] = iso(now())
    appeal["referral_count"] += 1
    if note is not None:
        appeal["_last_referred_note"] = note
    db.touch(appeal)
    return appeal


def decide_appeal(appeal, decision):
    if decision not in ("GRANT", "DENY"):
        fail("ERR_INVALID_REQUEST", "decision must be GRANT or DENY")

    if decision == "GRANT":
        if appeal["state"] != "SUBMITTED":
            fail("ERR_INVALID_STATE")
        sanction = db.find("AccountSanction", appeal["sanction_id"])
        if sanction is None or sanction["status"] != "ACTIVE":
            fail("ERR_INVALID_STATE")
        if now() >= parse_dt(appeal["deadline_utc"]):
            fail("ERR_PRECEDENT_EXPIRED")
        if not _evidence_movement(appeal):
            fail("ERR_NO_NEW_EVIDENCE")
        appeal["state"] = "GRANTED"
        appeal["decision_reason_code"] = _reason_code(appeal)
        db.touch(appeal)
        lift_sanction(sanction)
        return appeal

    if now() >= parse_dt(appeal["deadline_utc"]):
        fail("ERR_PRECEDENT_EXPIRED")
    if appeal["state"] != "SUBMITTED":
        fail("ERR_INVALID_STATE")
    appeal["state"] = "DENIED"
    appeal["decision_reason_code"] = "NO_NEW_EVIDENCE"
    db.touch(appeal)
    return appeal


def _reason_code(appeal):
    if appeal.get("sanction_misapplication_present"):
        return "MISAPPLICATION_CONFIRMED"
    if appeal["ground_code"] == "MODERATOR_MISCONDUCT":
        return "MISCONDUCT_CONFIRMED"
    return "ANALYSIS_ERROR_CONFIRMED"


def lift_sanction(sanction):
    """The AccountSanction ACTIVE -> LIFTED transition and its side effects."""
    sanction["status"] = "LIFTED"
    sanction["sanitized_on_utc"] = iso(now())
    db.touch(sanction)
    content.recompute_account(sanction["account_id"])
    community = community_svc.fetch(sanction["community_id"])
    if community is not None:
        community_svc.recompute(community)
    return sanction


def settle_watchdog(community):
    """UNDER_WATCH -> GRANTED once the watchdog deadline lapses."""
    for appeal in db.children("Appeal", "community_id", community["id"]):
        if appeal["state"] != "UNDER_WATCH":
            continue
        if appeal["referral_count"] < WATCHDOG_REFERRALS:
            continue
        if not at_least_days(parse_dt(appeal.get("last_referred_at_utc")), WATCHDOG_DAYS):
            continue
        if _evidence_movement(appeal):
            continue
        appeal["state"] = "GRANTED"
        appeal["decision_reason_code"] = _reason_code(appeal)
        db.touch(appeal)
        sanction = db.find("AccountSanction", appeal["sanction_id"])
        if sanction is not None and sanction["status"] == "ACTIVE":
            sanction["status"] = "LIFTED"
            sanction["sanitized_on_utc"] = iso(now())
            db.touch(sanction)
            content.recompute_account(sanction["account_id"])
        community_svc.refresh_derived(community)
    return community