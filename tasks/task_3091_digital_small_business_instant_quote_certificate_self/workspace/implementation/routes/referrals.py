"""Referral routes: get, approve, decline."""
from datetime import timedelta

from flask import Blueprint

import db
import errors
import middleware as mw
import response as resp
from services import underwriting as uw
from services import serialize as ser
from services import audit as aud

bp = Blueprint("referrals", __name__)


def _get_referral(rid):
    r = db.referrals.get(rid)
    if r is None:
        raise errors.not_found("Referral not found")
    return r


@bp.get("/ins/referrals/<rid>")
def get_referral(rid):
    actor = mw.get_actor()
    mw.require_role(actor, "PlatformAdmin", "Underwriter")
    r = _get_referral(rid)
    return resp.ok_object(ser.public(r))


@bp.post("/ins/referrals/<rid>/approve")
def approve_referral(rid):
    actor = mw.get_actor()
    mw.require_role(actor, "Underwriter")
    r = _get_referral(rid)
    if r["status"] != "OPEN":
        raise errors.invalid_state("Referral is not OPEN")
    q = db.quotes.get(r["quote_id"])
    if q is None:
        raise errors.not_found("Quote not found")
    now = db.clock_now()
    if q.get("expires_at"):
        exp = db.parse_iso(q["expires_at"])
        if now >= exp:
            raise errors.quote_expired()

    cls = db.class_codes.get(q["class_code_id"])
    acct = db.business_accounts[q["business_account_id"]]

    before_r = ser.public(r)
    r["decision"] = "APPROVED"
    r["status"] = "RESOLVED"
    r["assigned_underwriter"] = actor.user_id
    r["updated_at"] = db.fmt_iso(now)
    r["version"] += 1

    premium = uw.premium_cents(cls, q["selected_lines"], q["exposure_units"],
                               acct["claims_free_flag"], variant="provisional")
    pend = uw.pending_signals(q["business_account_id"])
    q["annual_premium_cents"] = premium
    q["expires_at"] = db.fmt_iso(now + timedelta(hours=168))
    q["premium_basis_hash"] = uw.premium_basis_hash(
        cls["id"], q["selected_lines"], q["exposure_units"],
        q["uw_answers"], [s["id"] for s in pend])
    q["status"] = "QUOTED"
    q["updated_at"] = db.fmt_iso(now)
    q["version"] += 1
    for s in pend:
        s["status"] = "APPLIED"
        s["updated_at"] = db.fmt_iso(now)
        s["version"] += 1

    aud.record(actor.role, actor.user_id, "UnderwriterReferral", r["id"], "approve",
               before=before_r, after=ser.public(r))
    aud.record(actor.role, actor.user_id, "Quote", q["id"], "quoted",
               before={"status": "REFERRED"}, after={"status": "QUOTED"})
    return resp.ok_object(ser.public(r))


@bp.post("/ins/referrals/<rid>/decline")
def decline_referral(rid):
    actor = mw.get_actor()
    mw.require_role(actor, "Underwriter")
    r = _get_referral(rid)
    if r["status"] != "OPEN":
        raise errors.invalid_state("Referral is not OPEN")
    q = db.quotes.get(r["quote_id"])
    if q is None:
        raise errors.not_found("Quote not found")
    now = db.clock_now()
    before_r = ser.public(r)
    r["decision"] = "DECLINED"
    r["status"] = "RESOLVED"
    r["assigned_underwriter"] = actor.user_id
    r["updated_at"] = db.fmt_iso(now)
    r["version"] += 1
    q["status"] = "DECLINED"
    q["updated_at"] = db.fmt_iso(now)
    q["version"] += 1
    aud.record(actor.role, actor.user_id, "UnderwriterReferral", r["id"], "decline",
               before=before_r, after=ser.public(r))
    aud.record(actor.role, actor.user_id, "Quote", q["id"], "declined",
               before={"status": "REFERRED"}, after={"status": "DECLINED"})
    return resp.ok_object(ser.public(r))
