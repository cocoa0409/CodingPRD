"""CompromisedCardEvent endpoints and the compromise cascade."""

from datetime import timedelta

from flask import Blueprint, request

import db
import errors
import middleware
import response
from services import domain

bp = Blueprint("compromised_card_events", __name__)

VALID_SOURCES = {"CAMS", "ADC"}


@bp.route("/fraudops/compromised-card-events", methods=["POST"])
def create_event():
    middleware.require_role("FraudOpsManager")
    body = request.get_json(silent=True) or {}
    network_source = body.get("network_source")
    event_reference = body.get("event_reference")
    merchant_id = body.get("merchant_id")
    window_start = body.get("window_start")
    window_end = body.get("window_end")

    if network_source not in VALID_SOURCES:
        raise errors.err_invalid_request("network_source must be CAMS or ADC")
    if not isinstance(event_reference, str) or not event_reference:
        raise errors.err_invalid_request("event_reference is required")
    if not isinstance(merchant_id, str) or not merchant_id:
        raise errors.err_invalid_request("merchant_id is required")
    if not isinstance(window_start, str) or not isinstance(window_end, str):
        raise errors.err_invalid_request("window_start and window_end are required")
    try:
        ws = db._parse_iso(window_start)
        we = db._parse_iso(window_end)
    except Exception:
        raise errors.err_invalid_request("window_start/window_end must be ISO 8601")
    if ws >= we:
        raise errors.err_invalid_window()

    for e in db.compromised_card_events.values():
        if e["event_reference"] == event_reference:
            raise errors.err_duplicate_event()

    rec = middleware.stamp_new(
        {
            "network_source": network_source,
            "event_reference": event_reference,
            "merchant_id": merchant_id,
            "window_start": window_start,
            "window_end": window_end,
            "event_status": "RECEIVED",
            "affected_card_count": 0,
            "confirmed_at": None,
        }
    )
    db.compromised_card_events[rec["id"]] = rec
    return response.success(domain.ser_event(rec), status_code=201)


@bp.route("/fraudops/compromised-card-events", methods=["GET"])
def list_events():
    middleware.require_role("FraudAnalyst", "FraudOpsManager")
    args = request.args
    items = sorted(db.compromised_card_events.values(), key=lambda e: (e["created_at"], e["id"]))
    for key in ("event_status", "network_source"):
        v = args.get(key)
        if v:
            items = [e for e in items if e.get(key) == v]
    limit, offset = domain.parse_pagination_args(args)
    sliced, pg = domain.paginate(items, limit, offset)
    return response.success([domain.ser_event(e) for e in sliced], pagination=pg)


@bp.route("/fraudops/compromised-card-events/<eid>", methods=["GET"])
def get_event(eid):
    middleware.require_role("FraudAnalyst", "FraudOpsManager")
    e = db.compromised_card_events.get(eid)
    if not e:
        raise errors.err_not_found("CompromisedCardEvent not found")
    domain._event_auto_close(eid)
    return response.success(domain.ser_event(e))


@bp.route("/fraudops/compromised-card-events/<eid>/confirm", methods=["POST"])
def confirm_event(eid):
    middleware.require_role("FraudOpsManager")
    e = db.compromised_card_events.get(eid)
    if not e:
        raise errors.err_not_found("CompromisedCardEvent not found")
    if e["event_status"] != "RECEIVED":
        raise errors.err_invalid_state("Event is not RECEIVED")

    confirmed_at = db.get_clock()
    e["confirmed_at"] = db.get_clock_iso()

    ws = db._parse_iso(e["window_start"])
    we = db._parse_iso(e["window_end"])
    merchant = e["merchant_id"]

    # Find exposed cards
    exposed: dict[str, dict] = {}  # card_id -> {"earliest": dt, "sum": int, "created_at": str}
    for t in db.auth_transactions.values():
        if t["merchant_id"] != merchant:
            continue
        ts = db._parse_iso(t["scored_at"])
        if not (ws <= ts < we):
            continue
        card = db.cards.get(t["card_id"])
        if not card:
            continue
        ent = exposed.get(card["id"])
        if ent is None:
            exposed[card["id"]] = {
                "earliest": ts,
                "sum": t["amount_cents"],
                "created_at": card["created_at"],
            }
        else:
            if ts < ent["earliest"]:
                ent["earliest"] = ts
            ent["sum"] += t["amount_cents"]

    # Deterministic creation order
    ordered_card_ids = sorted(
        exposed.keys(),
        key=lambda cid: (exposed[cid]["earliest"], exposed[cid]["created_at"]),
    )

    affected_accounts: set[str] = set()
    for cid in ordered_card_ids:
        card = db.cards[cid]
        affected_accounts.add(card["account_id"])
        # Set fraud_flag to COMPROMISED (only from CLEAN or WATCH; but per machine,
        # any card matched transitions; we set unconditionally)
        if card["fraud_flag"] != "COMPROMISED":
            card["fraud_flag"] = "COMPROMISED"
            middleware.touch(card)

        # Create PENDING ReissueDecision
        due_at = confirmed_at + timedelta(days=5)
        d = middleware.stamp_new(
            {
                "event_id": eid,
                "card_id": cid,
                "replacement_card_id": None,
                "decision": "PENDING",
                "exposure_cents": exposed[cid]["sum"],
                "due_at": domain._iso(due_at),
                "decided_by_user_id": None,
                "decided_at": None,
                "rationale": None,
            }
        )
        db.reissue_decisions[d["id"]] = d

    e["affected_card_count"] = len(ordered_card_ids)
    e["event_status"] = "CONFIRMED"
    middleware.touch(e)

    # Recompute tiers and escalate alerts for accounts that rose to HIGH
    for aid in affected_accounts:
        acct = db.accounts.get(aid)
        if not acct:
            continue
        old_tier = acct["risk_tier"]
        domain._recompute_account(aid)
        if acct["risk_tier"] == "HIGH" and old_tier != "HIGH":
            domain._escalate_open_alerts(aid)

    return response.success(domain.ser_event(e))
