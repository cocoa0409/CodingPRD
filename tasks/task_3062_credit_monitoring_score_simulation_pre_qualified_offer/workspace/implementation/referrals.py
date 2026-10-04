"""Referrals, revenue recognition and the clawback ledger."""

from datetime import timedelta

from flask import Blueprint, request

import store
import models
import helpers
import consent as consent_mod
from auth import require
from envelope import ok, ok_list, limited
from errors import fail

bp = Blueprint("referrals", __name__)

READ_ROLES = ["Consumer", "LenderOps", "Referee", "ComplianceOfficer",
              "PlatformAdmin", "DataProtectionOfficer"]
ENTRY_READ_ROLES = ["LenderOps", "ComplianceOfficer", "PlatformAdmin"]
CHANNELS = ("WEB", "MOBILE_APP", "MARKETPLACE")
FUNDING_WINDOW_DAYS = 30


def _program_of_decision(dec):
    return store.lender_programs.get(dec["lender_program_id"])


def _pending_consent(dec):
    """Routing requires a still-PENDING one-time grant on a CONSENTED decision."""
    con = consent_mod.consent_for(dec["consumer_id"], dec["id"])
    if con is None or con["status"] != "PENDING":
        fail("ERR_CONSENT_ALREADY_CONSUMED")
    if dec.get("decision_status") != "CONSENTED":
        fail("ERR_CONSENT_ALREADY_CONSUMED")
    return con


def _fundable_consent(dec):
    """Funding accepts the grant either still pending or already sealed."""
    con = consent_mod.consent_for(dec["consumer_id"], dec["id"])
    if con is None or con["status"] == "NOT_SEALED":
        fail("ERR_CONSENT_ALREADY_CONSUMED")
    return con


def _consume(dec, con, prog):
    """Seal the consent and drive the decision to CONSUMED."""
    consent_mod.seal_consent(con, prog)
    moment = store.now()
    if dec["decision_status"] == "CONSENTED":
        dec["decision_status"] = "CONSUMED"
        dec["updated_at"] = moment
        dec["version"] = int(dec.get("version", 0)) + 1


def _recompute_calibration(dec):
    prog = _program_of_decision(dec)
    if prog is None:
        return
    import analytics
    analytics.calibration_index(prog["product_catalog_item_id"], "including_provisional")


def _new_referral(dec, channel, external_ref):
    prog = _program_of_decision(dec)
    moment = store.now()
    row = store.make_row({
        "consumer_id": dec["consumer_id"],
        "decision_id": dec["id"],
        "external_referral_ref": external_ref,
        "channel": channel,
        "revenue_share_bps": prog["revenue_share_bps"],
        "clawback_rate_bps": prog["clawback_rate_bps"],
        "clawback_days": prog["clawback_days"],
        "status": "SENT",
        "funded_amount_cents": None,
        "funded_at": None,
        "reversed_at": None,
        "sent_at": moment,
    }, moment)
    store.referrals[row["id"]] = row
    return row


def _duplicate_ref(external_ref):
    for row in store.referrals.values():
        if row["external_referral_ref"] == external_ref:
            return True
    return False


@bp.route("/referrals", methods=["POST"])
def create_referral():
    require(["LenderOps"])
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST", "A JSON object body is required.")
    channel = data.get("channel")
    if channel not in CHANNELS:
        fail("ERR_INVALID_REQUEST", "channel must be WEB, MOBILE_APP or MARKETPLACE.")
    ref = data.get("external_referral_ref")
    if not ref:
        fail("ERR_INVALID_REQUEST", "external_referral_ref is required.")
    offer_id = data.get("offer_id")
    if not offer_id:
        fail("ERR_INVALID_REQUEST", "offer_id is required.")
    row = helpers.offer(str(offer_id))
    dec = helpers.decision(row["decision_id"])
    if row["status"] in ("CONSUMED", "WITHDRAWN", "STALE"):
        fail("ERR_INVALID_STATE_TRANSITION",
             "The offer is in a terminal status and cannot be routed.")
    if row["status"] != "RENDERED":
        fail("ERR_OFFER_NOT_RENDERED")
    con = _pending_consent(dec)
    if _duplicate_ref(str(ref)):
        fail("ERR_DUPLICATE_REFERRAL_REF")
    referral = _new_referral(dec, channel, str(ref))
    _consume(dec, con, _program_of_decision(dec))
    row["status"] = "CONSUMED"
    row["updated_at"] = store.now()
    row["version"] = int(row.get("version", 0)) + 1
    helpers.bump_consumer(helpers.consumer(dec["consumer_id"]))
    return ok(models.referral(referral), store.now(), 201)


@bp.route("/referral-attempts", methods=["POST"])
def referral_attempt():
    require(["LenderOps"])
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST", "A JSON object body is required.")
    channel = data.get("channel")
    if channel not in CHANNELS:
        fail("ERR_INVALID_REQUEST", "channel must be WEB, MOBILE_APP or MARKETPLACE.")
    did = data.get("decision_id")
    if not did:
        fail("ERR_INVALID_REQUEST", "decision_id is required.")
    dec = helpers.decision(str(did))
    con = None
    for candidate in store.consent_records.values():
        if candidate["consumer_id"] == dec["consumer_id"] and candidate["decision_id"] == dec["id"]:
            con = candidate
            break
    if con is None or con["status"] != "PENDING":
        fail("ERR_CONSENT_ALREADY_CONSUMED")
    offer = None
    for candidate in store.pre_qualified_offers.values():
        if candidate["decision_id"] == dec["id"] and candidate["status"] == "RENDERED":
            offer = candidate
            break
    if offer is None:
        fail("ERR_OFFER_NOT_RENDERED")
    con = _pending_consent(dec)
    referral = _new_referral(dec, channel, None)
    _consume(dec, con, _program_of_decision(dec))
    offer["status"] = "CONSUMED"
    offer["updated_at"] = store.now()
    offer["version"] = int(offer.get("version", 0)) + 1
    helpers.bump_consumer(helpers.consumer(dec["consumer_id"]))
    return ok(models.referral(referral), store.now(), 201)


def refresh_referral(ref):
    """A SENT referral is released once its 30-day funding window elapses; the
    release is otherwise applied by the daily run's mobility stage (PRD 3.8)."""
    import consent as _consent
    if ref["status"] != "SENT":
        return ref
    sent = ref.get("sent_at") or ref["created_at"]
    if store.now() > sent + timedelta(days=FUNDING_WINDOW_DAYS):
        ref["status"] = "UNFUNDED"
        ref["updated_at"] = store.now()
        ref["version"] = int(ref.get("version", 0)) + 1
        con = _consent.consent_for(ref["consumer_id"], ref["decision_id"])
        if con is not None and con["status"] == "PENDING":
            _consent.release_consent(con)
    return ref


@bp.route("/referrals", methods=["GET"])
def list_referrals():
    require(READ_ROLES)
    for ref in list(store.referrals.values()):
        refresh_referral(ref)
    rows = list(store.referrals.values())
    cid = request.args.get("consumer_id")
    if cid:
        rows = [r for r in rows if r["consumer_id"] == cid]
    did = request.args.get("decision_id")
    if did:
        rows = [r for r in rows if r["decision_id"] == did]
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    window, pagination = limited(rows, request.args)
    return ok_list([models.referral(r) for r in window], store.now(), pagination)


@bp.route("/referrals/<rid>", methods=["GET"])
def get_referral(rid):
    uid, role = require(["Consumer", "LenderOps", "Referee", "ComplianceOfficer", "PlatformAdmin"])
    row = refresh_referral(helpers.referral(rid))
    helpers.owned(row, uid, role, field="consumer_id")
    return ok(models.referral(row), store.now())


def post_revenue_entry(ref):
    amount = (int(ref["funded_amount_cents"]) * int(ref["revenue_share_bps"])) // 10000
    moment = store.now()
    row = {
        "id": store.new_id(),
        "created_at": moment,
        "consumer_id": ref["consumer_id"],
        "referral_id": ref["id"],
        "entry_kind": "REVENUE",
        "realized_amount_cents": amount,
        "recognized_at": moment,
    }
    store.revenue_entries[row["id"]] = row
    return row


def post_clawback_entry(ref):
    """The clawback leg restores the referral's clawback share (PRD 3.8 invariant:
    net recognized == gross share - clawback share)."""
    rate = int(ref.get("clawback_rate_bps") or 0)
    amount = -1 * ((int(ref["funded_amount_cents"]) * rate) // 10000)
    moment = store.now()
    row = {
        "id": store.new_id(),
        "created_at": moment,
        "consumer_id": ref["consumer_id"],
        "referral_id": ref["id"],
        "entry_kind": "CLAWBACK",
        "realized_amount_cents": amount,
        "recognized_at": moment,
    }
    store.revenue_entries[row["id"]] = row
    return row


def has_entry(referral_id, kind):
    for row in store.revenue_entries.values():
        if row["referral_id"] == referral_id and row["entry_kind"] == kind:
            return True
    return False


def has_outcome(decision_id):
    """True once any referral of this decision has reached a terminal outcome."""
    for ref in store.referrals.values():
        if ref["decision_id"] == decision_id and ref["status"] in (
                "FUNDED", "REVERSED", "DECLINED", "UNFUNDED"):
            return True
    return False


def refresh_settled(dec):
    """modeled_odds_settled flips true once a realized outcome exists (PRD 3.5).

    The stored modeled_odds_pct keeps its provisional two-decimal value; the
    settled integer (0/100) presentation is applied on read, so the calibration
    variants can diverge for identical decision rows (PRD 3.8).
    """
    dec["modeled_odds_settled"] = has_outcome(dec["id"])
    return dec


@bp.route("/referrals/<rid>/fund", methods=["POST"])
def fund_referral(rid):
    require(["LenderOps"])
    ref = helpers.referral(rid)
    dec = helpers.decision(ref["decision_id"])
    con = _fundable_consent(dec)
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST", "A JSON object body is required.")
    if ref["status"] != "SENT":
        if ref["status"] == "FUNDED":
            fail("ERR_REFERRAL_ALREADY_FUNDED")
        fail("ERR_INVALID_STATE_TRANSITION", "Only a SENT referral may be funded.")
    amount = data.get("funded_amount_cents")
    if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
        fail("ERR_INVALID_REQUEST", "funded_amount_cents must be a positive integer.")
    moment = store.now()
    ref["status"] = "FUNDED"
    ref["funded_amount_cents"] = amount
    ref["funded_at"] = moment
    ref["updated_at"] = moment
    ref["version"] = int(ref.get("version", 0)) + 1
    prog = _program_of_decision(dec)
    consent_mod.seal_consent(con, prog)
    if dec["decision_status"] == "CONSENTED":
        dec["decision_status"] = "CONSUMED"
        dec["updated_at"] = moment
        dec["version"] = int(dec.get("version", 0)) + 1
    dec["modeled_odds_settled"] = True
    post_revenue_entry(ref)
    refresh_settled(dec)
    _recompute_calibration(dec)
    helpers.bump_consumer(helpers.consumer(ref["consumer_id"]))
    return ok(models.referral(ref), store.now())


@bp.route("/referrals/<rid>/decline", methods=["POST"])
def decline_referral(rid):
    require(["LenderOps"])
    ref = helpers.referral(rid)
    if ref["status"] != "SENT":
        fail("ERR_INVALID_STATE_TRANSITION", "Only a SENT referral may be declined.")
    dec = helpers.decision(ref["decision_id"])
    con = consent_mod.consent_for(dec["consumer_id"], dec["id"])
    if con is not None and con["status"] != "NOT_SEALED":
        consent_mod.release_consent(con)
    ref["status"] = "DECLINED"
    ref["updated_at"] = store.now()
    ref["version"] = int(ref.get("version", 0)) + 1
    dec["modeled_odds_settled"] = True
    refresh_settled(dec)
    _recompute_calibration(dec)
    return ok(models.referral(ref), store.now())


@bp.route("/referrals/<rid>/reverse", methods=["POST"])
def reverse_referral(rid):
    require(["ComplianceOfficer", "PlatformAdmin"])
    ref = helpers.referral(rid)
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST", "A JSON object body is required.")
    if ref["status"] == "SENT":
        fail("ERR_REFERRAL_NOT_FUNDED")
    if ref["status"] != "FUNDED":
        fail("ERR_INVALID_STATE_TRANSITION", "Only a FUNDED referral may be reversed.")
    window_close = ref["funded_at"] + timedelta(days=int(ref["clawback_days"]))
    if store.now() > window_close:
        fail("ERR_CLAWBACK_WINDOW_CLOSED")
    moment = store.now()
    ref["status"] = "REVERSED"
    ref["reversed_at"] = moment
    ref["updated_at"] = moment
    ref["version"] = int(ref.get("version", 0)) + 1
    post_clawback_entry(ref)
    dec = helpers.decision(ref["decision_id"])
    dec["modeled_odds_settled"] = True
    refresh_settled(dec)
    _recompute_calibration(dec)
    helpers.bump_consumer(helpers.consumer(ref["consumer_id"]))
    return ok(models.referral(ref), store.now())


@bp.route("/revenue-recognition-entries", methods=["GET"])
def list_entries():
    require(ENTRY_READ_ROLES)
    rows = list(store.revenue_entries.values())
    rid = request.args.get("referral_id")
    if rid:
        rows = [r for r in rows if r["referral_id"] == rid]
    cid = request.args.get("consumer_id")
    if cid:
        rows = [r for r in rows if r["consumer_id"] == cid]
    kind = request.args.get("entry_kind")
    if kind:
        rows = [r for r in rows if r["entry_kind"] == kind]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    window, pagination = limited(rows, request.args)
    return ok_list([models.revenue(r) for r in window], store.now(), pagination)


@bp.route("/revenue-recognition-entries/<eid>", methods=["GET"])
def get_entry(eid):
    require(ENTRY_READ_ROLES)
    row = store.revenue_entries.get(eid)
    if row is None:
        fail("ERR_CONSUMER_NOT_FOUND", "RevenueRecognitionEntry not found.")
    return ok(models.revenue(row), store.now())


@bp.route("/referrals/<rid>/revenue-recognition-entries", methods=["GET"])
def referral_entries(rid):
    require(ENTRY_READ_ROLES)
    helpers.referral(rid)
    rows = [r for r in store.revenue_entries.values() if r["referral_id"] == rid]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    window, pagination = limited(rows, request.args)
    return ok_list([models.revenue(r) for r in window], store.now(), pagination)


@bp.route("/consumers/<cid>/revenue-recognition-entries", methods=["GET"])
def consumer_entries(cid):
    require(ENTRY_READ_ROLES)
    helpers.consumer(cid)
    rows = [r for r in store.revenue_entries.values() if r["consumer_id"] == cid]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    window, pagination = limited(rows, request.args)
    return ok_list([models.revenue(r) for r in window], store.now(), pagination)